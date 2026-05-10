from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import cloudpickle
import joblib


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = PROJECT_ROOT / "artifacts" / "models"
BUNDLE_PATH = MODEL_DIR / "notebook_hybrid_bundle.cloudpickle.pkl"


@lru_cache(maxsize=1)
def load_notebook_bundle(path: Path = BUNDLE_PATH) -> dict[str, Any]:
    with path.open("rb") as handle:
        return cloudpickle.load(handle)


def load_table_or_contract(name: str) -> Any:
    return joblib.load(MODEL_DIR / f"{name}.joblib")


def load_policy(name: str) -> Any:
    cloud_path = MODEL_DIR / f"{name}.cloudpickle.pkl"
    if cloud_path.exists():
        with cloud_path.open("rb") as handle:
            return cloudpickle.load(handle)
    return joblib.load(MODEL_DIR / f"{name}.joblib")

