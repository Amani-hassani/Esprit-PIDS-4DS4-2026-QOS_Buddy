"""
NOC-language translation table.

Every data-science / ML term that the agents emit internally MUST be translated
to NOC-friendly language before reaching the NOC views. The `translate()`
function is the single chokepoint — call it whenever you build a `display_label`.

Engineer view bypasses this and uses `technical_label` directly.
"""

from __future__ import annotations

from typing import Final

# canonical mapping; keys are case-insensitive
_TRANSLATIONS: Final[dict[str, str]] = {
    # detection / models
    "lstm anomaly": "Behavioral anomaly",
    "lstm": "Behavioral model",
    "isolation forest": "Outlier detector",
    "autoencoder": "Pattern detector",
    "kmeans": "Cluster analysis",
    # explainability
    "shap": "Top contributing factors",
    "shap values": "Top contributing factors",
    "feature importance": "Top contributing factors",
    # forecasting
    "prophet forecast": "Forecast",
    "prophet": "Forecast",
    "tte": "Time to breach",
    "time-to-event": "Time to breach",
    # similarity / RAG
    "faiss": "Similar past incidents",
    "faiss similarity": "Similar past incidents",
    "vector search": "Similar past incidents",
    "embedding": "Pattern signature",
    "embeddings": "Pattern signatures",
    "vectorize": "Index for similarity",
    # bandits / RL
    "mab": "Recommendation engine",
    "multi-armed bandit": "Recommendation engine",
    "thompson sampling": "Recommendation confidence",
    "policy gate": "Safety checks",
    # MLOps
    "drift": "Network behavior shift",
    "ks test": "Behavior shift test",
    "model retrain": "Self-improvement event",
    "model promotion": "Self-improvement event",
    "champion-challenger": "Self-improvement event",
    "confusion matrix": "Detection accuracy",
    "precision": "Correct alerts ratio",
    "recall": "Caught incidents ratio",
    # observability
    "provenance graph": "Decision trail",
    "trace": "Decision trail",
    "worm ledger": "Audit log",
    "watchdog": "Auto-rollback monitor",
    "counterfactual": "What-if comparison",
    # actions
    "playbook": "Recommended action",
    "ansible": "Network change tool",
    "rollback": "Auto-rollback",
}


def translate(term: str) -> str:
    """Return the NOC-friendly version of `term`. Falls back to the input if unknown."""
    return _TRANSLATIONS.get(term.strip().lower(), term)


def has_jargon(text: str) -> list[str]:
    """Scan `text` and return any jargon terms found.

    Use this in tests to assert no NOC view text contains forbidden words.
    """
    lowered = text.lower()
    return [k for k in _TRANSLATIONS if k in lowered]


# convenience labels used by producers when emitting NOC-language fields

NOC_FACTOR_LABELS: Final[dict[str, str]] = {
    # raw feature → NOC display label
    "latency_ms": "Round-trip delay",
    "jitter_ms": "Delay variation",
    "packet_loss_pct": "Packet loss",
    "throughput_mbps": "Throughput",
    "bler_proxy_pct": "Block error rate",
    "tcp_retransmit_rate": "Retransmission rate",
    "active_connections": "Active sessions",
    "cpu_pct": "Host CPU pressure",
    "memory_pct": "Host memory pressure",
    "rsrp_dbm": "Signal strength",
    "rsrq_db": "Signal quality",
    "sinr_db": "Signal-to-noise",
    "rssi_dbm": "Received signal level",
    "mos_estimate": "Voice quality score",
    "anomaly_score": "Anomaly intensity",
    "latency_volatility": "Delay instability",
    "jitter_rolling_mean": "Recent average jitter",
    "throughput_rolling_std": "Throughput instability",
}


def factor_label(technical_name: str) -> str:
    """Return the NOC label for an internal feature name."""
    return NOC_FACTOR_LABELS.get(technical_name, technical_name.replace("_", " ").title())
