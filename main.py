"""Simple, readable end-to-end pipeline entry point."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

import joblib

from config import SAVED_MODELS_DIR, TARGET_NAMES
from data_pipeline.features import engineer_features, resolve_feature_columns
from data_pipeline.label_engineer import build_labels
from data_pipeline.loader import load_qos
from data_pipeline.preprocessor import Preprocessor
from models.eta_trainer import train_eta_models
from models.lstm_trainer import train_lstm
from models.prophet_forecaster import ProphetForecaster
from models.xgb_trainer import train_xgb_models


def _print_section(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def _print_label_summary(df_l) -> None:
    print("Label balance on the full labeled dataset:")
    for target in TARGET_NAMES:
        if target not in df_l.columns:
            continue
        rate = float(df_l[target].astype(float).mean() * 100.0)
        count = int(df_l[target].sum())
        print(f"  {target:26s}  {rate:5.1f}% positives   ({count} / {len(df_l)})")


def _run_holdout_evaluation() -> None:
    eval_script = Path(__file__).resolve().parent / "scripts" / "evaluate_models.py"
    old_argv = sys.argv[:]
    try:
        sys.argv = [str(eval_script), "--last-15pct"]
        runpy.run_path(str(eval_script), run_name="__main__")
    finally:
        sys.argv = old_argv


def main() -> None:
    _print_section("QoS Prediction Agent - Full Pipeline")
    print("This run will:")
    print("  1. load QoS data")
    print("  2. clean and preprocess it")
    print("  3. engineer temporal features")
    print("  4. build future-window labels")
    print("  5. train XGBoost, LSTM, ETA models, and Prophet")
    print("  6. evaluate the saved ensemble on the last 15% holdout")

    _print_section("1/6 - Load raw QoS data")
    df = load_qos()
    if df.empty:
        raise SystemExit("No QoS CSVs found under data/raw (expected qos_timeseries_*.csv).")
    df = df.sort_values(["timestamp", "node_id"], na_position="last").reset_index(drop=True)
    print(f"Loaded {len(df)} rows from {df['node_id'].nunique()} node(s).")
    print(f"Time span: {df['timestamp'].min()} -> {df['timestamp'].max()}")

    _print_section("2/6 - Preprocess the data")
    cut = max(int(0.8 * len(df)), 1)
    pre = Preprocessor()
    pre.fit(df.iloc[:cut])
    df_t = pre.transform(df)
    print(f"Preprocessor fitted on the first {cut} rows, then applied to the full dataset.")
    print(f"Shape after preprocessing: {df_t.shape[0]} rows x {df_t.shape[1]} columns")

    _print_section("3/6 - Engineer features")
    df_t = engineer_features(df_t)
    feature_examples = [
        "rsrp_slope_5min",
        "signal_instability_index",
        "mos_trend_slope",
        "voice_qoe_score",
        "congestion_index",
    ]
    present_examples = [name for name in feature_examples if name in df_t.columns]
    print(f"Feature engineering complete: {df_t.shape[1]} total columns.")
    if present_examples:
        print("Example engineered features:")
        for name in present_examples:
            print(f"  - {name}")

    _print_section("4/6 - Build labels")
    df_l = build_labels(df_t)
    if df_l.empty:
        raise SystemExit("Label engineering produced an empty frame; check input schema.")
    df_l = df_l.sort_values(["timestamp", "node_id"], na_position="last").reset_index(drop=True)
    print(f"Labeled frame: {len(df_l)} rows.")
    _print_label_summary(df_l)

    resolve_feature_columns(df_l)
    SAVED_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(pre, SAVED_MODELS_DIR / "preprocessor.joblib")

    _print_section("5/6 - Train models")
    print("Training XGBoost classifiers...")
    train_xgb_models(df_l, out_dir=SAVED_MODELS_DIR)
    print("Training LSTM model...")
    train_lstm(df_l, out_path=SAVED_MODELS_DIR / "lstm_qos.pt")
    print("Training target-specific ETA models...")
    train_eta_models(df_l, out_dir=SAVED_MODELS_DIR)
    print("Training Prophet forecaster...")
    ProphetForecaster(SAVED_MODELS_DIR).fit_all_nodes(df_l)
    print(f"Training complete. Artifacts written to {SAVED_MODELS_DIR}")

    _print_section("6/6 - Evaluate on the last 15% holdout")
    print("This is the easiest version to explain in class: train on the past, test on the future.")
    print("ROC-AUC = ranking quality. AP = precision of alerting.")
    _run_holdout_evaluation()

if __name__ == "__main__":
    main()
