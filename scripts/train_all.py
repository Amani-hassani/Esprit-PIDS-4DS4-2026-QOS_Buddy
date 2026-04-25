"""End-to-end training: preprocess → features → labels → XGB + LSTM + Prophet."""

from __future__ import annotations

import sys
from pathlib import Path

import joblib

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import SAVED_MODELS_DIR, TARGET_NAMES
from data_pipeline.features import engineer_features, resolve_feature_columns
from data_pipeline.label_engineer import build_labels
from data_pipeline.loader import load_qos
from data_pipeline.preprocessor import Preprocessor
from models.eta_trainer import train_eta_models
from models.lstm_trainer import train_lstm
from models.prophet_forecaster import ProphetForecaster
from models.xgb_trainer import train_xgb_models


def main() -> None:
    df = load_qos()
    if df.empty:
        raise SystemExit("No QoS CSVs found under data/raw (expected qos_timeseries_*.csv).")

    df = df.sort_values(["timestamp", "node_id"], na_position="last").reset_index(drop=True)
    cut = max(int(0.8 * len(df)), 1)
    pre = Preprocessor()
    pre.fit(df.iloc[:cut])
    df_t = pre.transform(df)
    df_t = engineer_features(df_t)
    df_l = build_labels(df_t)
    if df_l.empty:
        raise SystemExit("Label engineering produced an empty frame; check input schema.")

    # Verify label distributions before training — flag issues early
    print("\n── Label distributions after build_labels() ──")
    for t in TARGET_NAMES:
        if t in df_l.columns:
            pct = float(df_l[t].astype(float).mean() * 100)
            if pct < 5 or pct > 95:
                status = f"⚠  EVALUABILITY PROBLEM — {pct:.1f}% positive (ROC-AUC will be invalid)"
            elif pct < 15 or pct > 85:
                status = f"⚠  marginal — consider adjusting threshold"
            else:
                status = "✓"
            print(f"  {t:30s}  {pct:5.1f}%  {status}")
    print()

    resolve_feature_columns(df_l)
    SAVED_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(pre, SAVED_MODELS_DIR / "preprocessor.joblib")

    train_xgb_models(df_l, out_dir=SAVED_MODELS_DIR)
    train_lstm(df_l, out_path=SAVED_MODELS_DIR / "lstm_qos.pt")
    train_eta_models(df_l, out_dir=SAVED_MODELS_DIR)

    ProphetForecaster(SAVED_MODELS_DIR).fit_all_nodes(df_l)
    print(f"Training complete. Artifacts written to {SAVED_MODELS_DIR}")


if __name__ == "__main__":
    main()
