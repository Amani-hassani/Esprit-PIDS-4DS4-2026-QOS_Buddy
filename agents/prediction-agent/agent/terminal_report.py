"""Print a concise prediction summary to the process stdout (Streamlit server terminal)."""

from __future__ import annotations

import math
import sys
from typing import TextIO

import numpy as np

from agent.result import PredictionResult


def print_prediction_terminal_summary(
    result: PredictionResult,
    *,
    stream: TextIO | None = None,
) -> None:
    """
    Emit metrics and key fields to the terminal. When running ``streamlit run``,
    this appears in the same console that launched Streamlit.
    """
    out = stream or sys.stdout
    vals = list(result.risk_probs.values()) if result.risk_probs else []
    max_p = max(vals) if vals else 0.0
    max_disp = f"{max_p:.4f}" if vals and math.isfinite(max_p) else "(n/a)"
    lines = [
        "",
        "=" * 72,
        " QoS Prediction Agent — terminal summary",
        "=" * 72,
        f"  node_id ........................ {result.node_id}",
        f"  timestamp ...................... {result.timestamp}",
        f"  severity ....................... {result.severity}",
        f"  max ensemble risk .............. {max_disp}",
        f"  capacity_exhaustion_eta_min .... {result.capacity_exhaustion_eta_min}",
        "-" * 72,
        "  Ensemble risk_probs:",
    ]
    for k, v in sorted(result.risk_probs.items()):
        vs = f"{float(v):.6f}" if np.isfinite(v) else "nan"
        lines.append(f"    {k:28s} {vs}")
    lines.append("-" * 72)
    lines.append("  SHAP (aggregated top contributors):")
    # Flatten target-grouped features for terminal display
    if isinstance(result.shap_features, dict):
        for target, features in sorted(result.shap_features.items()):
            lines.append(f"    [{target}]")
            for row in features[:3]:  # Show top 3 per target
                feat_name = row.get('feature', '?')
                feat_val = row.get('value', 0)
                direction = row.get('direction', '')
                lines.append(f"      {feat_name}: value={feat_val:.5f} ({direction})")
    else:
        # Fallback for flat format compatibility
        for row in result.shap_features:
            lines.append(
                f"    {row.get('feature', '?')}: value={row.get('value', 0):.5f} "
                f"({row.get('direction', '')})"
            )
    lines.append("-" * 72)
    lines.append(f"  RAG incidents retrieved ....... {len(result.retrieved_incidents)}")
    for i, inc in enumerate(result.retrieved_incidents, 1):
        doc = inc.get("document") or str(inc)
        lines.append(f"    [{i}] {doc[:120]}{'...' if len(str(doc)) > 120 else ''}")
    lines.append("-" * 72)
    expl = (result.explanation or "").strip().replace("\n", " ")
    if len(expl) > 200:
        expl = expl[:200] + "..."
    lines.append(f"  LLM explanation (preview) .... {expl or '(none)'}")
    lines.append("=" * 72)
    print("\n".join(lines), file=out, flush=True)
