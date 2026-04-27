from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import joblib
from sklearn.metrics import mean_absolute_error, mean_squared_error
from xgboost import XGBRegressor


DATA_DIR = Path("data")
OUTPUT_DIR = Path("outputs/xgboost_nhs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_timeseries() -> pd.DataFrame:
    files = sorted(DATA_DIR.glob("qos_timeseries_*.csv"))
    if not files:
        raise FileNotFoundError("Aucun fichier qos_timeseries_*.csv trouvé dans data/")

    dfs = []
    for file in files:
        df = pd.read_csv(file)
        df["source_file"] = file.name
        dfs.append(df)

    ts = pd.concat(dfs, ignore_index=True)

    if "timestamp" in ts.columns:
        ts["timestamp"] = pd.to_datetime(ts["timestamp"], errors="coerce")

    return ts


def load_incidents() -> pd.DataFrame:
    files = sorted(DATA_DIR.glob("incidents_*.csv"))
    if not files:
        raise FileNotFoundError("Aucun fichier incidents_*.csv trouvé dans data/")

    dfs = []
    for file in files:
        df = pd.read_csv(file)
        df["source_file"] = file.name
        dfs.append(df)

    incidents = pd.concat(dfs, ignore_index=True)

    if "start_timestamp" in incidents.columns:
        incidents["start_timestamp"] = pd.to_datetime(incidents["start_timestamp"], errors="coerce")

    return incidents


def safe_numeric(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    work = df.copy()
    for col in columns:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")
    return work


def compute_nhs_row(row: pd.Series) -> float:
    """
    NHS = score composite 0..100
    Formule projet raisonnable si le NHS officiel n'existe pas dans les données.
    """

    latency = row.get("latency_ms", np.nan)
    jitter = row.get("jitter_ms", np.nan)
    loss = row.get("packet_loss_pct", np.nan)
    throughput = row.get("throughput_mbps", np.nan)
    anomaly_score = row.get("anomaly_score", 0)

    # Sous-scores
    latency_score = max(0, min(100, 100 * (1 - (latency / 300)))) if pd.notna(latency) else 50
    jitter_score = max(0, min(100, 100 * (1 - (jitter / 150)))) if pd.notna(jitter) else 50
    loss_score = max(0, min(100, 100 * (1 - (loss / 10)))) if pd.notna(loss) else 50
    throughput_score = max(0, min(100, 100 * (throughput / 10))) if pd.notna(throughput) else 50

    base = (
        0.35 * latency_score +
        0.20 * jitter_score +
        0.20 * loss_score +
        0.25 * throughput_score
    )

    if pd.notna(anomaly_score):
        base -= float(anomaly_score) * 20

    return round(max(0, min(100, base)), 3)


def prepare_hourly_dataset(timeseries: pd.DataFrame, incidents: pd.DataFrame) -> pd.DataFrame:
    ts = timeseries.copy()
    ts = safe_numeric(ts, [
        "latency_ms", "jitter_ms", "throughput_mbps",
        "packet_loss_pct", "anomaly_score"
    ])

    ts = ts.dropna(subset=["timestamp"])
    ts["hour"] = ts["timestamp"].dt.floor("h")
    ts["day_of_week"] = ts["timestamp"].dt.dayofweek
    ts["hour_of_day"] = ts["timestamp"].dt.hour
    ts["is_peak_hour"] = ts["hour_of_day"].between(18, 23).astype(int)

    # NHS calculé par ligne
    ts["nhs_row"] = ts.apply(compute_nhs_row, axis=1)

    hourly_ts = ts.groupby("hour", as_index=False).agg({
        "latency_ms": "mean",
        "jitter_ms": "mean",
        "throughput_mbps": "mean",
        "nhs_row": "mean",
        "is_peak_hour": "max",
        "day_of_week": "max"
    })

    hourly_ts = hourly_ts.rename(columns={
        "latency_ms": "mean_latency_1h",
        "jitter_ms": "mean_jitter_1h",
        "throughput_mbps": "mean_throughput_1h",
        "nhs_row": "nhs_1h"
    })

    # Incidents par heure
    inc = incidents.copy()
    if not inc.empty and "start_timestamp" in inc.columns:
        inc["hour"] = pd.to_datetime(inc["start_timestamp"], errors="coerce").dt.floor("h")
        

        severity_map = {
            "low": 1,
            "medium": 2,
            "high": 3,
            "critical": 4
        }

        if "severity" in inc.columns:
            inc["severity_rank"] = inc["severity"].astype(str).str.lower().map(severity_map)

        hourly_inc = inc.groupby("hour", as_index=False).agg({
            "incident_type": "count",
            "severity_rank": "max"
        }).rename(columns={
            "incident_type": "nb_incidents_1h",
            "severity_rank": "max_severity_1h"
        })
    else:
        hourly_inc = pd.DataFrame(columns=["hour", "nb_incidents_1h", "max_severity_1h"])

    # Merge
    hourly = pd.merge(hourly_ts, hourly_inc, on="hour", how="left")
    hourly["nb_incidents_1h"] = hourly["nb_incidents_1h"].fillna(0)
    hourly["max_severity_1h"] = hourly["max_severity_1h"].fillna(0)

    # Targets futurs
    hourly = hourly.sort_values("hour").reset_index(drop=True)
    hourly["target_nhs_plus_1h"] = hourly["nhs_1h"].shift(-1)
    hourly["target_nhs_plus_2h"] = hourly["nhs_1h"].shift(-2)
    hourly["target_nhs_plus_6h"] = hourly["nhs_1h"].shift(-6)

    return hourly


def train_single_horizon(df: pd.DataFrame, target_col: str, model_name: str):
    features = [
        "nb_incidents_1h",
        "max_severity_1h",
        "mean_latency_1h",
        "mean_jitter_1h",
        "mean_throughput_1h",
        "is_peak_hour",
        "day_of_week"
    ]

    work = df.dropna(subset=features + [target_col]).copy()
    if len(work) < 10:
        print(f"⚠️ Pas assez de données pour entraîner {model_name}")
        return None

    X = work[features]
    y = work[target_col]

    # Split chronologique 80/20
    split_idx = int(len(work) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    model = XGBRegressor(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=42
    )

    model.fit(X_train, y_train)

    preds = model.predict(X_test)

    mae = mean_absolute_error(y_test, preds)
    rmse = np.sqrt(mean_squared_error(y_test, preds))

    pred_df = pd.DataFrame({
        "actual": y_test.values,
        "predicted": preds
    })
    pred_df.to_csv(OUTPUT_DIR / f"predictions_{model_name}.csv", index=False)

    joblib.dump(model, OUTPUT_DIR / f"{model_name}.joblib")

    # Plot
    plt.figure(figsize=(8, 5))
    plt.plot(pred_df.index, pred_df["actual"], label="Réel")
    plt.plot(pred_df.index, pred_df["predicted"], label="Prédit")
    plt.title(f"NHS réel vs prédit — {model_name}")
    plt.xlabel("Index test")
    plt.ylabel("NHS")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / f"{model_name}_actual_vs_pred.png", dpi=150)
    plt.close()

    return {
        "model_name": model_name,
        "target": target_col,
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "train_size": len(X_train),
        "test_size": len(X_test)
    }


def run_xgboost_nhs():
    print("Chargement des timeseries et incidents...")
    timeseries = load_timeseries()
    incidents = load_incidents()

    print("Préparation du dataset horaire...")
    hourly = prepare_hourly_dataset(timeseries, incidents)
    hourly.to_csv(OUTPUT_DIR / "hourly_nhs_dataset.csv", index=False)

    print("Entraînement XGBoost pour +1h, +2h, +6h...")
    results = []

    for target_col, model_name in [
        ("target_nhs_plus_1h", "xgb_nhs_plus_1h"),
        ("target_nhs_plus_2h", "xgb_nhs_plus_2h"),
        ("target_nhs_plus_6h", "xgb_nhs_plus_6h"),
    ]:
        result = train_single_horizon(hourly, target_col, model_name)
        if result:
            results.append(result)

    results_df = pd.DataFrame(results)
    results_df.to_csv(OUTPUT_DIR / "xgboost_results.csv", index=False)

    print("\n✅ XGBoost NHS terminé.")
    print(f"Dataset horaire : {OUTPUT_DIR / 'hourly_nhs_dataset.csv'}")
    print(f"Résultats : {OUTPUT_DIR / 'xgboost_results.csv'}")
    print("\nAperçu des résultats :")
    print(results_df)


if __name__ == "__main__":
    run_xgboost_nhs()