"""
Monitoring → Redis bridge.

Tails the real `network_stream.jsonl` produced by the monitoring agent
(`monitoring/qos_buddy_collector.py`) and republishes each sample to
`qos.metrics.raw` as a `MetricEvent`.

Every field already produced by the collector is preserved:
  • strict KPI fields go into the typed columns of MetricEvent
  • everything else is forwarded under `extra` so downstream agents
    (detection, prediction) keep their full feature set without changes.

This is the live data path. There is no mock fallback by design.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator

import orjson

from contracts.schemas import MetricEvent, StreamName

from .graceful import install_sigterm_handler
from .otel import flush_tracer, init_tracer
from .redis_streams import RedisStreamsBus

log = logging.getLogger("qos.bridge.monitoring")

# Strict KPI columns; everything else lands in `extra` to stay forward-compatible.
_STRICT_FIELDS: frozenset[str] = frozenset(
    {
        "latency_ms",
        "jitter_ms",
        "packet_loss_pct",
        "throughput_mbps",
        "mos_estimate",
        "bler_proxy_pct",
        "tcp_retransmit_rate",
        "anomaly_score",
        "anomaly_flag",
        "anomaly_type",
        "rsrp_dbm",
        "rsrq_db",
        "sinr_db",
        "rssi_dbm",
        "cqi",
        "pci",
        "earfcn",
        "cpu_pct",
        "memory_pct",
        "active_connections",
        "data_source",
        "data_quality_rating",
        "device_type",
    }
)
_SCOPE_FIELDS: frozenset[str] = frozenset({"zone_id", "cell_id", "node_id", "tenant_id"})
_META_FIELDS: frozenset[str] = frozenset({"timestamp", "published_at"})


class MonitoringBridge:
    """Tails JSONL produced by the monitoring agent and forwards to Redis Streams."""

    def __init__(
        self,
        bus: RedisStreamsBus,
        *,
        jsonl_path: str | Path | None = None,
        producer: str = "monitoring",
        producer_version: str = "1.2",
        poll_interval: float = 0.25,
    ) -> None:
        path = jsonl_path or os.getenv(
            "QOS_MONITORING_JSONL",
            # default points at the real file produced by the existing agent
            str(Path(__file__).resolve().parents[2] / "monitoring" / "network_stream.jsonl"),
        )
        self.path = Path(path)
        self.bus = bus
        self.producer = producer
        self.producer_version = producer_version
        self.poll_interval = poll_interval

    # ─── public ───────────────────────────────────────────────────────

    async def run(self) -> None:
        mode = os.getenv("QOS_MONITORING_MODE", "tail").lower()
        log.info("bridge starting jsonl=%s mode=%s", self.path, mode)
        await self._wait_for_file()
        source = self._replay() if mode == "replay" else self._tail()
        async for sample in source:
            try:
                event = self._to_metric_event(sample)
            except Exception as exc:  # noqa: BLE001
                log.exception("normalize failed: %s", exc)
                continue
            try:
                await self.bus.publish(StreamName.METRICS_RAW, event)
            except Exception as exc:  # noqa: BLE001
                log.exception("publish failed: %s", exc)
                # do NOT drop on publish failure; back off and retry
                await asyncio.sleep(0.5)

    # ─── internals ────────────────────────────────────────────────────

    async def _wait_for_file(self) -> None:
        warned = False
        while not self.path.exists():
            if not warned:
                log.warning(
                    "monitoring jsonl not yet present at %s — waiting for the collector to start",
                    self.path,
                )
                warned = True
            await asyncio.sleep(1.0)
        log.info("monitoring jsonl found, beginning tail")

    async def _replay(self) -> AsyncIterator[dict[str, Any]]:
        """Loop a recorded JSONL forever at a fixed cadence.

        This mode is only for intentional backfills or offline demos. The
        default deployment path is `_tail()`, which follows the collector's
        live JSONL output.
        """
        interval = float(os.getenv("QOS_REPLAY_INTERVAL_SECONDS", "1.0"))
        speed = max(0.1, float(os.getenv("QOS_REPLAY_SPEED", "1.0")))
        sleep_for = max(0.05, interval / speed)

        # Load the entire JSONL once. ~5 MB — trivial.
        samples: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8-sig") as f:
            for line_num, raw in enumerate(f, 1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    samples.append(orjson.loads(line))
                except orjson.JSONDecodeError as exc:
                    log.warning(
                        "replay: skipped malformed line %d (%s)", line_num, exc
                    )
        if not samples:
            log.error("replay: %s is empty — no samples to publish", self.path)
            return

        log.info(
            "replay: loaded %d samples, interval=%.2fs speed=%.1fx",
            len(samples),
            interval,
            speed,
        )

        loop_count = 0
        while True:
            for sample in samples:
                # Restamp so downstream sees the event as fresh.
                fresh = dict(sample)
                fresh["timestamp"] = datetime.utcnow().isoformat() + "Z"
                yield fresh
                await asyncio.sleep(sleep_for)
            loop_count += 1
            log.info("replay: completed loop %d — restarting", loop_count)

    async def _tail(self) -> AsyncIterator[dict[str, Any]]:
        """Tail-f the JSONL. Survives file truncation/rotation."""
        position = 0
        # Start at end so the bridge always reflects "live now", not a replay
        # of historical data. Use REPLAY_FROM_START=true to override for backfills.
        replay_from_start = os.getenv("QOS_BRIDGE_REPLAY", "false").lower() == "true"
        if not replay_from_start:
            try:
                position = self.path.stat().st_size
            except FileNotFoundError:
                position = 0

        last_inode: int | None = None
        while True:
            try:
                stat = self.path.stat()
            except FileNotFoundError:
                await asyncio.sleep(self.poll_interval)
                continue

            inode = getattr(stat, "st_ino", None)
            if last_inode is not None and inode != last_inode:
                log.info("monitoring jsonl rotated, resetting position")
                position = 0
            last_inode = inode

            if stat.st_size < position:
                # truncated
                position = 0

            if stat.st_size == position:
                await asyncio.sleep(self.poll_interval)
                continue

            with self.path.open("r", encoding="utf-8") as f:
                f.seek(position)
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield orjson.loads(line)
                    except orjson.JSONDecodeError:
                        log.warning("dropped malformed line in jsonl")
                        continue
                position = f.tell()

    def _to_metric_event(self, sample: dict[str, Any]) -> MetricEvent:
        # Pull strict KPI fields
        strict = {k: sample.get(k) for k in _STRICT_FIELDS if k in sample}
        # Pull scoping
        scope = {k: sample.get(k) for k in _SCOPE_FIELDS if sample.get(k) is not None}
        # Everything else goes into extra (rolling stats, signal_health_overall, etc.)
        extra = {
            k: v
            for k, v in sample.items()
            if k not in _STRICT_FIELDS and k not in _SCOPE_FIELDS and k not in _META_FIELDS
        }

        # occurred_at ← collector timestamp when present
        occurred_at_str = sample.get("timestamp")
        occurred_at = None
        if occurred_at_str:
            try:
                occurred_at = datetime.fromisoformat(occurred_at_str)
            except ValueError:
                occurred_at = None

        kwargs: dict[str, Any] = {
            **strict,
            "extra": extra,
            "producer": self.producer,
            "producer_version": self.producer_version,
            "tenant_id": scope.get("tenant_id", "default"),
            "zone_id": scope.get("zone_id"),
            "cell_id": scope.get("cell_id"),
            "node_id": scope.get("node_id"),
        }
        if occurred_at is not None:
            kwargs["occurred_at"] = occurred_at

        return MetricEvent(**kwargs)


# ─── entry point: `python -m bus.monitoring_bridge` ─────────────────────

async def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    install_sigterm_handler(log)
    init_tracer(os.getenv("OTEL_SERVICE_NAME", "monitoring-bridge"))
    bus = RedisStreamsBus()
    await bus.connect()
    bridge = MonitoringBridge(bus)
    try:
        await bridge.run()
    finally:
        await bus.close()
        flush_tracer()
        log.info("Shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
