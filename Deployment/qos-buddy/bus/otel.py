"""
OpenTelemetry tracer setup for QOS-Buddy bridges.

Each bridge service calls `init_tracer(service_name)` once at startup. The
helper is a no-op when `OTEL_EXPORTER_OTLP_ENDPOINT` is unset, so unit tests
and one-off runs don't need a collector. When the env var is set, spans
export to that endpoint over OTLP/gRPC.

The bus layer (`redis_streams.py`) uses `propagator` to inject W3C
traceparent headers into published events and to extract them on consume,
so a single trace stitches together monitoring → detection → diagnostic →
optimization → execution.
"""

from __future__ import annotations

import logging
import os

from opentelemetry import propagate, trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Tracer

log = logging.getLogger("qos.otel")

_initialised = False


def init_tracer(service_name: str) -> Tracer:
    """Initialise the global tracer provider once. Returns a tracer for `service_name`."""
    global _initialised

    if not _initialised:
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        if not endpoint:
            log.info("otel disabled (OTEL_EXPORTER_OTLP_ENDPOINT not set)")
            trace.set_tracer_provider(TracerProvider(resource=Resource.create({"service.name": service_name})))
        else:
            resource = Resource.create({"service.name": service_name})
            provider = TracerProvider(resource=resource)
            exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(provider)
            log.info("otel tracer ready service=%s endpoint=%s", service_name, endpoint)
        _initialised = True

    return trace.get_tracer(service_name)


def inject_context(carrier: dict[str, str]) -> None:
    """W3C-inject the active trace context into `carrier` (mutated in place)."""
    propagate.inject(carrier)


def extract_context(carrier: dict[str, str]):
    """Return a Context object reconstructed from `carrier` headers."""
    return propagate.extract(carrier)


def flush_tracer() -> None:
    """Force-flush spans before process exit when the SDK provider supports it."""
    provider = trace.get_tracer_provider()
    flush = getattr(provider, "force_flush", None)
    if callable(flush):
        try:
            flush()
        except Exception as exc:  # noqa: BLE001
            log.warning("otel flush failed: %s", exc)
