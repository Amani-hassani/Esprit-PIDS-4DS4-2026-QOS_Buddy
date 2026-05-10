from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import traceback
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cloudpickle
import joblib


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NOTEBOOK = PROJECT_ROOT / "01_benchmark_and_defence2.ipynb"
DEFAULT_OUT = PROJECT_ROOT / "artifacts" / "models"

OBJECTS_TO_EXPORT = [
    "m8_policy",
    "base_eg_robust_bandit",
    "base_m6_robust_bandit",
    "base_m7_robust_bandit",
    "arbiter_cache",
    "train_stats",
    "final_score_table",
    "model_role_table",
    "hybrid_decisions",
    "rule_trace",
    "eg_trace",
    "m6_trace",
    "m7_trace",
    "m8_trace",
    "hybrid_trace",
    "RC_TO_ACTIONS",
    "ACTIONS",
    "ACTION_CODES",
    "ACTION_BY_CODE",
    "RC_VOCAB",
    "RC_SCOPE",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _patch_display(namespace: dict[str, Any]) -> None:
    try:
        go = namespace.get("go")
        if go is not None:
            go.Figure.show = lambda self, *args, **kwargs: None
    except Exception:
        pass
    try:
        px = namespace.get("px")
        if px is not None:
            import plotly.graph_objects as go

            go.Figure.show = lambda self, *args, **kwargs: None
    except Exception:
        pass


def execute_notebook(notebook_path: Path) -> dict[str, Any]:
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
    os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")
    raw = json.loads(notebook_path.read_text(encoding="utf-8"))
    module_name = "__qos_notebook_export__"
    module = types.ModuleType(module_name)
    module.__file__ = str(notebook_path)
    sys.modules[module_name] = module
    namespace = module.__dict__
    namespace.update(
        {
            "__name__": module_name,
            "__file__": str(notebook_path),
            "NOTEBOOK_EXPORT_MODE": True,
            "display": lambda *args, **kwargs: None,
        }
    )
    os.chdir(PROJECT_ROOT)
    code_cells = [cell for cell in raw["cells"] if cell.get("cell_type") == "code"]
    for index, cell in enumerate(code_cells, start=1):
        source = "".join(cell.get("source", ""))
        if not source.strip():
            continue
        _patch_display(namespace)
        try:
            exec(compile(source, f"{notebook_path.name}:code_cell_{index}", "exec"), namespace)
        except Exception as exc:
            print(f"\nFAILED executing code cell {index}: {exc}", file=sys.stderr)
            traceback.print_exc()
            raise
    _patch_display(namespace)
    return namespace


def export_objects(namespace: dict[str, Any], out_dir: Path, notebook_path: Path) -> dict[str, Any]:
    out_dir = out_dir.resolve()
    notebook_path = notebook_path.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    exported: dict[str, str] = {}
    missing = []
    bundle = {}
    for name in OBJECTS_TO_EXPORT:
        if name in namespace:
            bundle[name] = namespace[name]
        else:
            missing.append(name)

    sys.modules.pop("__qos_notebook_export__", None)
    bundle_path = out_dir / "notebook_hybrid_bundle.cloudpickle.pkl"
    with bundle_path.open("wb") as handle:
        cloudpickle.dump(bundle, handle)
    exported["notebook_hybrid_bundle"] = str(bundle_path.relative_to(PROJECT_ROOT))

    for name, obj in bundle.items():
        obj_module = getattr(getattr(obj, "__class__", None), "__module__", "")
        if obj_module == "__qos_notebook_export__":
            pkl_path = out_dir / f"{name}.cloudpickle.pkl"
            with pkl_path.open("wb") as handle:
                cloudpickle.dump(obj, handle)
            exported[name] = str(pkl_path.relative_to(PROJECT_ROOT))
        else:
            path = out_dir / f"{name}.joblib"
            try:
                joblib.dump(obj, path)
                exported[name] = str(path.relative_to(PROJECT_ROOT))
            except Exception as exc:
                pkl_path = out_dir / f"{name}.cloudpickle.pkl"
                with pkl_path.open("wb") as handle:
                    cloudpickle.dump(obj, handle)
                exported[name] = str(pkl_path.relative_to(PROJECT_ROOT))
                exported[f"{name}_joblib_error"] = str(exc)

    scorecard = None
    if "final_score_table" in namespace:
        try:
            scorecard = namespace["final_score_table"].to_dict(orient="records")
        except Exception:
            scorecard = str(namespace["final_score_table"])

    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "notebook": str(notebook_path.relative_to(PROJECT_ROOT)),
        "notebook_sha256": _sha256(notebook_path),
        "exported": exported,
        "missing": missing,
        "scorecard": scorecard,
        "load_note": (
            "Use notebook_hybrid_bundle.cloudpickle.pkl for exact notebook-defined classes. "
            "Individual .joblib files are also written when the object supports standard joblib loading."
        ),
    }
    metadata_path = out_dir / "model_export_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute benchmark notebook and export trained model objects.")
    parser.add_argument("--notebook", type=Path, default=DEFAULT_NOTEBOOK)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    start = time.time()
    namespace = execute_notebook(args.notebook)
    metadata = export_objects(namespace, args.out, args.notebook)
    elapsed = time.time() - start
    print(json.dumps({"elapsed_sec": round(elapsed, 2), "metadata": metadata}, indent=2, default=str))


if __name__ == "__main__":
    main()
