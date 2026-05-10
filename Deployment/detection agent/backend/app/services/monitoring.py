import psutil
import time
from datetime import datetime
from typing import Dict, Any

_start_time = time.time()


def get_system_metrics() -> Dict[str, Any]:
    """Retourne les métriques système en temps réel"""
    cpu = psutil.cpu_percent(interval=0.5)
    memory = psutil.virtual_memory()
    net = psutil.net_io_counters()

    return {
        "cpu_usage": cpu,
        "memory_usage": memory.percent,
        "memory_total_mb": round(memory.total / 1024 / 1024),
        "memory_used_mb": round(memory.used / 1024 / 1024),
        "request_rate": 0,           # à brancher sur un middleware de comptage si besoin
        "active_connections": len(psutil.net_connections()),
        "uptime": round(time.time() - _start_time),
        "bytes_sent": net.bytes_sent,
        "bytes_recv": net.bytes_recv,
        "timestamp": datetime.utcnow().isoformat()
    }
