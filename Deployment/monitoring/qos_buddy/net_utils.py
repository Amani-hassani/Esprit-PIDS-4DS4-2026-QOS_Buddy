"""
Cross-platform networking helpers shared across the QoS Buddy collector.

The single public entry point is `find_default_gateway()`, which returns the
machine's default IPv4 gateway as a string (e.g. '192.168.100.1') or None
when nothing usable is reachable. The resolver is intentionally tolerant:
it walks a chain of strategies and returns the first valid answer so the
collector keeps running on any LAN without manual config edits.
"""

from __future__ import annotations

import ipaddress
import logging
import platform
import re
import socket
import subprocess
from functools import lru_cache
from typing import Iterable, List, Optional, Tuple

logger = logging.getLogger("QoSBuddy")

_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_PROBE_PORTS: Tuple[int, ...] = (80, 443, 53, 8080)
_PROBE_TIMEOUT = 0.6  # seconds


def _is_ipv4(value: str) -> bool:
    if not value or not _IPV4_RE.match(value):
        return False
    try:
        addr = ipaddress.IPv4Address(value)
    except ValueError:
        return False
    return not (addr.is_unspecified or addr.is_loopback or addr.is_multicast)


def _local_ipv4() -> Optional[str]:
    """Best-effort local IPv4 used to source outbound traffic."""
    # The UDP-connect trick: no packet is actually sent, but the kernel
    # binds the socket to the interface that would route to 8.8.8.8.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.5)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if _is_ipv4(ip) and not ip.startswith("127."):
                return ip
    except OSError:
        pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if _is_ipv4(ip) and not ip.startswith("127."):
            return ip
    except OSError:
        return None
    return None


def _from_psutil() -> Optional[str]:
    """Pull default gateway from psutil's routing/interface tables when present."""
    try:
        import psutil  # type: ignore
    except ImportError:
        return None
    # psutil exposes net_if_addrs but not a default route directly. We use
    # the local IP to find which interface is active, then look at peers.
    local_ip = _local_ipv4()
    if not local_ip:
        return None
    try:
        addrs = psutil.net_if_addrs()
    except Exception:
        return None
    for _ifname, snics in addrs.items():
        for snic in snics:
            if getattr(snic, "family", None) == socket.AF_INET and snic.address == local_ip:
                # Same-subnet probe handled below; psutil alone isn't enough.
                return None
    return None


def _from_windows() -> Optional[str]:
    if platform.system() != "Windows":
        return None
    # Try Get-NetRoute first (modern, structured).
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' "
                "-ErrorAction SilentlyContinue | "
                "Sort-Object RouteMetric, ifMetric | "
                "Select-Object -First 1).NextHop",
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=4,
        )
        gw = (proc.stdout or "").strip()
        if _is_ipv4(gw):
            return gw
    except Exception:
        pass
    # Legacy fallback: parse `route print -4`.
    try:
        proc = subprocess.run(
            ["route", "print", "-4"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=4,
        )
        for line in (proc.stdout or "").splitlines():
            parts = line.split()
            # Lines look like: "          0.0.0.0          0.0.0.0   192.168.1.1   192.168.1.20  35"
            if len(parts) >= 5 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
                if _is_ipv4(parts[2]):
                    return parts[2]
    except Exception:
        pass
    return None


def _from_linux() -> Optional[str]:
    if platform.system() != "Linux":
        return None
    # Preferred: `ip -4 route show default`.
    try:
        proc = subprocess.run(
            ["ip", "-4", "route", "show", "default"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=3,
        )
        for line in (proc.stdout or "").splitlines():
            tokens = line.split()
            if "via" in tokens:
                idx = tokens.index("via")
                if idx + 1 < len(tokens) and _is_ipv4(tokens[idx + 1]):
                    return tokens[idx + 1]
    except Exception:
        pass
    # Fallback: parse /proc/net/route.
    try:
        with open("/proc/net/route", "r", encoding="ascii") as f:
            next(f, None)  # skip header
            for line in f:
                fields = line.strip().split()
                if len(fields) >= 3 and fields[1] == "00000000":
                    raw = fields[2]
                    if len(raw) == 8:
                        octets = [int(raw[i : i + 2], 16) for i in (6, 4, 2, 0)]
                        gw = ".".join(str(o) for o in octets)
                        if _is_ipv4(gw):
                            return gw
    except OSError:
        pass
    return None


def _from_macos() -> Optional[str]:
    if platform.system() != "Darwin":
        return None
    try:
        proc = subprocess.run(
            ["route", "-n", "get", "default"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=3,
        )
        for line in (proc.stdout or "").splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("gateway:"):
                gw = stripped.split(":", 1)[1].strip()
                if _is_ipv4(gw):
                    return gw
    except Exception:
        pass
    return None


def _candidates_for_subnet(local_ip: Optional[str]) -> List[str]:
    """Generate plausible gateway IPs ranked by local subnet match."""
    bases = [
        "192.168.1.",
        "192.168.0.",
        "192.168.8.",
        "192.168.100.",
        "10.0.0.",
        "10.0.1.",
        "172.16.0.",
    ]
    seen: List[str] = []

    def push(ip: str) -> None:
        if ip not in seen and _is_ipv4(ip):
            seen.append(ip)

    if local_ip:
        try:
            net24 = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
            base = str(net24.network_address).rsplit(".", 1)[0] + "."
            for suffix in (1, 254, 100):
                push(f"{base}{suffix}")
        except ValueError:
            pass
    for base in bases:
        push(f"{base}1")
    return seen


def _probe(host: str) -> bool:
    for port in _PROBE_PORTS:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(_PROBE_TIMEOUT)
                if s.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            continue
    return False


def _probe_candidates() -> Optional[str]:
    local_ip = _local_ipv4()
    for candidate in _candidates_for_subnet(local_ip):
        if _probe(candidate):
            return candidate
    return None


def _strategies() -> Iterable:
    yield _from_windows
    yield _from_linux
    yield _from_macos
    yield _from_psutil
    yield _probe_candidates


@lru_cache(maxsize=1)
def find_default_gateway() -> Optional[str]:
    """Return the machine's default IPv4 gateway, or None if unresolved.

    Result is cached for the life of the process — a laptop's default
    gateway rarely changes mid-session, and callers (router probe, ping
    fallback) hit this on every collection cycle.
    """
    for strategy in _strategies():
        try:
            gw = strategy()
        except Exception as exc:  # noqa: BLE001 — strategies must never crash callers
            logger.debug("gateway strategy %s failed: %s", strategy.__name__, exc)
            continue
        if gw and _is_ipv4(gw):
            logger.info("default gateway resolved via %s: %s", strategy.__name__, gw)
            return gw
    logger.warning("default gateway could not be resolved automatically")
    return None


def is_auto_sentinel(value: Optional[str]) -> bool:
    """True when a config value should trigger auto-detect."""
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    return value.strip().lower() in {"", "auto", "none", "null"}
