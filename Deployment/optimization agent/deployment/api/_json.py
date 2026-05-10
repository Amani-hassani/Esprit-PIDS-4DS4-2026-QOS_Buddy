from __future__ import annotations

from typing import Any


def _to_primitive(value: Any) -> Any:
    # NumPy scalars expose .item() returning a native Python value.
    if hasattr(value, "item") and not isinstance(value, (bytes, bytearray, str)):
        try:
            return value.item()
        except (ValueError, TypeError):
            pass
    # pandas NaT / numpy.nan — collapse to None for the frontend.
    try:
        import math

        if isinstance(value, float) and math.isnan(value):
            return None
    except Exception:
        pass
    return value


def json_safe(obj: Any) -> Any:
    """Recursively coerce numpy/pandas scalars into plain Python types that FastAPI can encode."""
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return _to_primitive(obj)
