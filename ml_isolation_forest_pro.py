from pathlib import Path
import json
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import joblib

from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA


DATA_DIR = Path("data")
OUTPUT_DIR = Path("outputs/isolation_forest_pro")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_incidents() -> pd.DataFrame:
    files = sorted(DATA_DIR.glob("incidents_*.csv"))
    if not files:
        raise FileNotFoundError("Aucun fichier incidents_*.csv trouvé dans data/")

    dfs = []
    for file in files:
        df = pd.read_csv(file)
        df["source_file"] = file.name
        dfs.append(df)

    df = pd.concat(dfs, ignore_index=True)

    if "start_timestamp" in df.columns:
        df["start_timestamp"] = pd.to_datetime(df["start_timestamp"], errors="coerce")
    if "end_timestamp" in df.columns:
        df["end_timestamp"] = pd.to_datetime(df["end_timestamp"], errors="coerce")

    return df


def prepare_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    work = df.copy()

    severity_map = {
        "low": 1,
        "medium": 2,
        "high": 3,
        "critical": 4
    }

    if "severity" in work.columns:
        work["severity_rank"] = work["severity"].astype(str).str.lower().map(severity_map)

    if "duration_sec" in work.columns:
        work["duration_sec"] = pd.to_numeric(work["duration_sec"], errors="coerce")

    if "max_score" in work.columns:
        work["max_score"] = pd.to_numeric(work["max_score"], errors="coerce")

    if {"max_score", "severity_rank"}.issubset(work.columns):
        work["incident_weight"] = work["max_score"] * work["severity_rank"]

    feature_names = [
        "max_score",
        "duration_sec",
        "severity_rank",
        "incident_weight"
    ]
    feature_names = [f for f in feature_names if f in work.columns]

    if not feature_names:
        raise ValueError("Aucune feature valide pour Isolation Forest.")

    X = work[feature_names].copy()
    X = X.apply(pd.to_numeric, errors="coerce")
    valid_idx = X.dropna().index

    return work.loc[valid_idx].copy(), feature_names


def assign_outlier_label(row: pd.Series) -> str:
    score = row.get("isolation_score", 0)
    severity = row.get("severity_rank", 0)
    duration = row.get("duration_sec", 0)

    if score < -0.10 and (severity >= 3 or duration >= 100):
        return "Highly Atypical Critical Incident"
    if score < -0.05:
        return "Atypical Incident"
    return "Typical Incident"


def run_isolation_forest(contamination: float = 0.10):
    print("Lancement Isolation Forest professionnel...", flush=True)

    incidents = load_incidents()
    print(f"Nombre d'incidents charges : {len(incidents)}", flush=True)

    incidents_ready, feature_names = prepare_features(incidents)
    if incidents_ready.empty:
        raise ValueError("Aucune ligne exploitable apres preparation des features.")

    X = incidents_ready[feature_names].copy()

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = IsolationForest(
        contamination=contamination,
        random_state=42,
        n_estimators=200
    )

    model.fit(X_scaled)

    # decision_function : plus bas = plus atypique
    decision_scores = model.decision_function(X_scaled)
    predictions = model.predict(X_scaled)  # -1 anomalie, 1 normal

    enriched = incidents_ready.copy()
    enriched["isolation_score"] = decision_scores
    enriched["is_outlier"] = predictions
    enriched["outlier_flag"] = enriched["is_outlier"].map({-1: "yes", 1: "no"})
    enriched["outlier_label"] = enriched.apply(assign_outlier_label, axis=1)

    # PCA 2D pour visualisation
    pca = PCA(n_components=2, random_state=42)
    X_pca = pca.fit_transform(X_scaled)
    enriched["pca_1"] = X_pca[:, 0]
    enriched["pca_2"] = X_pca[:, 1]

    plt.figure(figsize=(8, 6))
    normal_df = enriched[enriched["outlier_flag"] == "no"]
    outlier_df = enriched[enriched["outlier_flag"] == "yes"]

    plt.scatter(normal_df["pca_1"], normal_df["pca_2"], alpha=0.6, label="Typical")
    plt.scatter(outlier_df["pca_1"], outlier_df["pca_2"], alpha=0.9, label="Atypical")
    plt.title("Isolation Forest - Projection PCA des incidents")
    plt.xlabel("PCA 1")
    plt.ylabel("PCA 2")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "isolation_pca.png", dpi=150)
    plt.close()

    # Histogramme des scores
    plt.figure(figsize=(8, 5))
    plt.hist(enriched["isolation_score"], bins=20)
    plt.title("Distribution des scores Isolation Forest")
    plt.xlabel("Isolation Score")
    plt.ylabel("Nombre d'incidents")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "isolation_score_distribution.png", dpi=150)
    plt.close()

    # Top incidents les plus atypiques
    top_atypical = enriched.sort_values("isolation_score", ascending=True).head(15).copy()

    display_cols = [c for c in [
        "incident_type",
        "severity",
        "duration_sec",
        "max_score",
        "severity_rank",
        "incident_weight",
        "isolation_score",
        "outlier_flag",
        "outlier_label",
        "source_file",
        "start_timestamp"
    ] if c in top_atypical.columns]

    top_atypical[display_cols].to_csv(OUTPUT_DIR / "top_atypical_incidents.csv", index=False)
    enriched.to_csv(OUTPUT_DIR / "incidents_isolation_scored.csv", index=False)

    summary = {
        "n_samples": int(len(enriched)),
        "n_outliers": int((enriched["outlier_flag"] == "yes").sum()),
        "outlier_ratio": round(float((enriched["outlier_flag"] == "yes").mean()), 4),
        "contamination": contamination,
        "feature_names": feature_names
    }

    with open(OUTPUT_DIR / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    # Sauvegarde modèle
    joblib.dump(model, OUTPUT_DIR / "isolation_forest_model.joblib")
    joblib.dump(scaler, OUTPUT_DIR / "isolation_forest_scaler.joblib")
    joblib.dump(feature_names, OUTPUT_DIR / "isolation_forest_features.joblib")

    print("\nIsolation Forest termine.", flush=True)
    print(json.dumps(summary, indent=2), flush=True)
    print("\nTop incidents atypiques :", flush=True)
    print(top_atypical[display_cols].head(10), flush=True)


if __name__ == "__main__":
    run_isolation_forest(contamination=0.10)