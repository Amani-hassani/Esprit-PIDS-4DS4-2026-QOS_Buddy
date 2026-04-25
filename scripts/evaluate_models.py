"""Evaluate saved XGB + LSTM ensemble on a time-ordered holdout (same logic as PredictionAgent)."""

from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import torch
from sklearn.metrics import average_precision_score, roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.prediction_agent import _impute_model_inputs, _sanitize_prob_matrix
from config import LSTM_WINDOW, SAVED_MODELS_DIR, TARGET_NAMES
from data_pipeline.features import engineer_features
from data_pipeline.label_engineer import ETA_TARGETS, TTE_COLUMN_MAP, build_labels
from data_pipeline.loader import load_qos
from evaluation.evaluator import evaluate_multilabel
from models.eta_trainer import load_eta_models, predict_eta_minutes
from models.ensemble import ensemble_predict
from models.lstm_trainer import QoSLSTM, load_lstm_artifacts, scale_window
from models.xgb_trainer import load_xgb_feature_columns, load_xgb_models


def _interpret_roc_auc(value: float) -> str:
    if np.isnan(value):
        return "n/a"
    if value < 0.60:
        return "weak"
    if value < 0.70:
        return "fair"
    if value < 0.80:
        return "good"
    return "strong"


def _interpret_ap(value: float, positive_rate: float) -> str:
    if np.isnan(value):
        return "n/a"
    if value < max(positive_rate, 0.10):
        return "weak"
    if value < max(positive_rate + 0.10, 0.20):
        return "fair"
    if value < 0.80:
        return "good"
    return "strong"


def _binary_metrics_at_threshold(
    y_true_col: np.ndarray,
    y_score_col: np.ndarray,
    threshold: float,
) -> tuple[float, float, float]:
    pred = (y_score_col >= threshold).astype(np.int8)
    tp = int(((pred == 1) & (y_true_col == 1)).sum())
    fp = int(((pred == 1) & (y_true_col == 0)).sum())
    fn = int(((pred == 0) & (y_true_col == 1)).sum())

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2.0 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return float(precision), float(recall), float(f1)


def _best_threshold_by_f1(
    y_true_col: np.ndarray,
    y_score_col: np.ndarray,
    candidates: np.ndarray,
) -> tuple[float, float, float, float]:
    best_thr = 0.5
    best_p, best_r, best_f1 = 0.0, 0.0, -1.0
    for thr in candidates:
        p, r, f1 = _binary_metrics_at_threshold(y_true_col, y_score_col, float(thr))
        if f1 > best_f1:
            best_thr = float(thr)
            best_p, best_r, best_f1 = p, r, f1
    return best_thr, best_p, best_r, best_f1


def _ensemble_for_history(
    hist: pd.DataFrame,
    *,
    feature_cols: list[str],
    feature_cols_per_target: dict[str, list[str]],
    feat_cols: list[str],
    xgb_models,
    lstm_model: torch.nn.Module,
    lstm_art,
    device: torch.device,
) -> np.ndarray:
    """Match PredictionAgent scoring on prepared+imputed frame ``hist`` (single node, time-sorted)."""
    model_cols = sorted(set(feature_cols) | set(feat_cols))
    df = _impute_model_inputs(hist, model_cols)
    last_row = df.iloc[-1]

    xgb_probs = np.zeros((1, len(TARGET_NAMES)), dtype=float)
    for i, name in enumerate(TARGET_NAMES):
        m = xgb_models.get(name)
        if m is None:
            continue
        target_cols = feature_cols_per_target.get(name, feature_cols)
        available = [c for c in target_cols if c in df.columns]
        xgb_mat = last_row[available].to_numpy(dtype=np.float32).reshape(1, -1)
        proba = np.asarray(m.predict_proba(xgb_mat), dtype=float)
        if proba.ndim != 2 or proba.shape[0] < 1:
            continue
        if proba.shape[1] == 1:
            xgb_probs[0, i] = float(proba[0, 0])
        else:
            xgb_probs[0, i] = float(proba[0, 1])
    xgb_probs = _sanitize_prob_matrix(xgb_probs)

    win = df.iloc[-LSTM_WINDOW:][feat_cols].to_numpy(dtype=np.float32)
    win = np.nan_to_num(win, nan=0.0, posinf=0.0, neginf=0.0)
    win_scaled = scale_window(win, scaler_object=lstm_art.scaler_object)
    win_scaled = np.nan_to_num(win_scaled, nan=0.0, posinf=1.0, neginf=0.0)
    tensor = torch.from_numpy(win_scaled.reshape(1, LSTM_WINDOW, -1)).to(device)
    with torch.no_grad():
        logits = lstm_model(tensor)
        lstm_out = torch.sigmoid(logits).cpu().numpy()
    lstm_probs = _sanitize_prob_matrix(lstm_out)

    ens = ensemble_predict(xgb_probs, lstm_probs)[0]
    return _sanitize_prob_matrix(ens.reshape(1, -1)).reshape(-1)


def main() -> None:
    model_dir = SAVED_MODELS_DIR
    max_rows = None
    if "--max-rows" in sys.argv:
        try:
            i = sys.argv.index("--max-rows")
            max_rows = int(sys.argv[i + 1])
        except Exception:
            raise SystemExit("Usage: python scripts/evaluate_models.py --max-rows N")

    pr_thresholds = [0.3, 0.5, 0.7]
    if "--pr-thresholds" in sys.argv:
        try:
            i = sys.argv.index("--pr-thresholds")
            raw = sys.argv[i + 1]
            parsed = [float(x.strip()) for x in raw.split(",") if x.strip()]
            if not parsed:
                raise ValueError
            pr_thresholds = [min(0.99, max(0.01, v)) for v in parsed]
        except Exception:
            raise SystemExit("Usage: python scripts/evaluate_models.py --pr-thresholds 0.3,0.5,0.7")

    pre_path = model_dir / "preprocessor.joblib"
    if not pre_path.exists():
        raise SystemExit(f"Missing {pre_path}. Run python scripts/train_all.py first.")

    df_raw = load_qos()
    if df_raw.empty:
        raise SystemExit("No QoS CSVs under data/raw.")

    df_raw = df_raw.sort_values(["timestamp", "node_id"], na_position="last").reset_index(drop=True)
    pre = joblib.load(pre_path)
    df_t = engineer_features(pre.transform(df_raw.copy()))
    df_l = build_labels(df_t)
    if df_l.empty:
        raise SystemExit("Label frame empty after build_labels.")

    df_l = df_l.sort_values(["timestamp", "node_id"], na_position="last").reset_index(drop=True)

    feature_cols: list[str] = list(joblib.load(model_dir / "xgb_feature_columns.joblib"))
    feature_cols_per_target = load_xgb_feature_columns(model_dir, fallback_cols=feature_cols)
    lstm_art = load_lstm_artifacts(model_dir / "lstm_qos.pt")
    feat_cols = list(lstm_art.feature_cols)
    xgb_models = load_xgb_models(model_dir)
    eta_models = load_eta_models(model_dir)

    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    lstm_model = QoSLSTM(input_dim=len(feat_cols)).to(dev)
    lstm_model.load_state_dict(lstm_art.state_dict)
    lstm_model.eval()

    records: list[tuple[pd.Timestamp, str, np.ndarray, np.ndarray]] = []
    eta_records: dict[str, list[tuple[float, float]]] = {name: [] for name in ETA_TARGETS}
    scored = 0

    model_cols = sorted(set(feature_cols) | set(feat_cols))

    for node_id, g in df_l.groupby("node_id", sort=False):
        g = g.sort_values("timestamp", na_position="last").reset_index(drop=True)
        if len(g) < LSTM_WINDOW:
            continue
        for c in feat_cols:
            if c not in g.columns:
                raise SystemExit(f"Missing column {c} in labeled frame.")
        nid = str(node_id)
        start_pos = LSTM_WINDOW - 1
        if max_rows is not None and max_rows > 0:
            start_pos = max(start_pos, len(g) - max_rows)
        for pos in range(start_pos, len(g)):
            hist = g.iloc[: pos + 1]
            prepared = _impute_model_inputs(hist, model_cols)
            row_for_eta = prepared.iloc[-1]
            ens = _ensemble_for_history(
                hist,
                feature_cols=feature_cols,
                feature_cols_per_target=feature_cols_per_target,
                feat_cols=feat_cols,
                xgb_models=xgb_models,
                lstm_model=lstm_model,
                lstm_art=lstm_art,
                device=dev,
            )
            row = g.iloc[pos]
            y_t = row[list(TARGET_NAMES)].to_numpy(dtype=np.float64)
            ts = row["timestamp"]
            records.append((ts, nid, y_t, ens))

            for target in ETA_TARGETS:
                pred_eta = predict_eta_minutes(eta_models.get(target), row_for_eta)
                tte_col = TTE_COLUMN_MAP[target]
                raw_true_eta = row_for_eta.get(tte_col, np.nan) if tte_col in row_for_eta.index else np.nan
                try:
                    true_eta = float(raw_true_eta)
                except (TypeError, ValueError):
                    true_eta = float("nan")
                eta_records[target].append((true_eta, pred_eta))

            scored += 1
            if scored % 200 == 0:
                print(f"Scored {scored} row(s)...")

    records.sort(key=lambda r: (r[0], r[1]))
    y_true_rows = [r[2] for r in records]
    y_score_rows = [r[3] for r in records]

    if len(y_true_rows) < 50:
        raise SystemExit(f"Too few scored rows ({len(y_true_rows)}); need diverse time series.")

    y_true = np.vstack(y_true_rows)
    y_score = np.vstack(y_score_rows)

    use_last_15 = "--last-15pct" in sys.argv
    if use_last_15:
        cut = int(0.85 * len(y_true))
        y_true = y_true[cut:]
        y_score = y_score[cut:]
        print(f"Holdout: last 15% of scored timeline ({len(y_true)} rows).")
        per_target: dict = {}
        for i, name in enumerate(TARGET_NAMES):
            col_y = y_true[:, i]
            col_s = y_score[:, i]
            if len(np.unique(col_y)) < 2:
                per_target[name] = {"roc_auc": float("nan"), "average_precision": float("nan")}
            else:
                per_target[name] = {
                    "roc_auc": float(roc_auc_score(col_y, col_s)),
                    "average_precision": float(average_precision_score(col_y, col_s)),
                }
    else:
        print(
            f"Scored timeline: {len(y_true)} rows (per-node windows, global time order). "
            "Metrics use evaluate_multilabel -> last TimeSeriesSplit(5) test fold on this sequence."
        )
        per_target = evaluate_multilabel(y_true, y_score, n_splits=5)

    print("-" * 60)
    print("Holdout positive rate and metric meaning:")
    decision_thresholds: dict[str, float] = {}
    for name in TARGET_NAMES:
        m = per_target.get(name, {})
        idx = TARGET_NAMES.index(name)
        positive_rate = float(y_true[:, idx].mean()) if len(y_true) else float("nan")
        col_y = y_true[:, idx]
        col_s = y_score[:, idx]
        best_thr, best_p, best_r, best_f1 = _best_threshold_by_f1(
            col_y,
            col_s,
            candidates=np.linspace(0.1, 0.9, 17),
        )
        decision_thresholds[name] = best_thr
        print(
            f"  {name:26s}  pos_rate: {positive_rate:6.1%}   "
            f"ROC-AUC: {m.get('roc_auc', float('nan')):8.4f} ({_interpret_roc_auc(m.get('roc_auc', float('nan')))} )   "
            f"AP: {m.get('average_precision', float('nan')):8.4f} ({_interpret_ap(m.get('average_precision', float('nan')), positive_rate)} )"
        )
        print(
            f"{'':30s}best_thr(F1): {best_thr:0.2f}   "
            f"precision: {best_p:0.3f}   recall: {best_r:0.3f}   f1: {best_f1:0.3f}"
        )

        for thr in pr_thresholds:
            p_t, r_t, f1_t = _binary_metrics_at_threshold(col_y, col_s, thr)
            print(
                f"{'':30s}thr={thr:0.2f} -> precision: {p_t:0.3f}, recall: {r_t:0.3f}, f1: {f1_t:0.3f}"
            )
    print("-" * 60)
    roc_values = [v.get("roc_auc", float("nan")) for v in per_target.values()]
    ap_values = [v.get("average_precision", float("nan")) for v in per_target.values()]
    print(f"Average ROC-AUC: {float(np.nanmean(roc_values)):.4f}")
    print(f"Average AP:      {float(np.nanmean(ap_values)):.4f}")
    print("Interpretation: ROC-AUC measures ranking quality; AP measures how reliable alerts are on the selected holdout.")

    if eta_models:
        print("-" * 60)
        print("ETA evaluation (time-to-event models):")
        for target in ETA_TARGETS:
            pairs = eta_records.get(target, [])
            valid_pairs = [(t, p) for t, p in pairs if np.isfinite(t) and np.isfinite(p)]
            censored_rate = float(np.mean([not np.isfinite(t) for t, _ in pairs])) if pairs else float("nan")
            if not valid_pairs:
                print(f"  {target:26s}  no observed events in holdout")
                continue
            true_vals = np.array([t for t, _ in valid_pairs], dtype=float)
            pred_vals = np.array([p for _, p in valid_pairs], dtype=float)
            abs_err = np.abs(pred_vals - true_vals)
            mae = float(abs_err.mean())
            medae = float(np.median(abs_err))
            coverage_5 = float(np.mean(abs_err <= 5.0))
            print(
                f"  {target:26s}  MAE: {mae:6.2f} min   medAE: {medae:6.2f} min   "
                f"coverage±5m: {coverage_5:5.1%}   N/A/censored: {censored_rate:5.1%}"
            )

    out_thresholds = model_dir / "decision_thresholds.joblib"
    joblib.dump(decision_thresholds, out_thresholds)
    print(f"Saved recommended per-target decision thresholds to: {out_thresholds}")
    print("Tip: pass --last-15pct to score only the final 15% of scored rows (no inner split).")


if __name__ == "__main__":
    main()
