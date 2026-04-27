from pathlib import Path
import json
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import joblib

from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score


DATA_DIR = Path("data")
OUTPUT_DIR = Path("outputs/kmeans_pro")
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

    if "start_timestamp" in work.columns:
        work["hour_of_day"] = work["start_timestamp"].dt.hour

    if "duration_sec" in work.columns:
        work["duration_sec"] = pd.to_numeric(work["duration_sec"], errors="coerce")

    if "max_score" in work.columns:
        work["max_score"] = pd.to_numeric(work["max_score"], errors="coerce")

    if "samples" in work.columns:
        work["samples"] = pd.to_numeric(work["samples"], errors="coerce")

    if {"max_score", "severity_rank"}.issubset(work.columns):
        work["incident_weight"] = work["max_score"] * work["severity_rank"]

    feature_names = [
        "duration_sec",
        "max_score",
        "severity_rank",
        "hour_of_day",
        "incident_weight",
        "samples"
    ]
    feature_names = [f for f in feature_names if f in work.columns]

    X = work[feature_names].copy()
    X = X.apply(pd.to_numeric, errors="coerce")
    valid_idx = X.dropna().index
    X = X.loc[valid_idx].copy()

    return work.loc[valid_idx].copy(), feature_names


def elbow_and_silhouette(X_scaled: np.ndarray, k_values=range(2, 7)) -> pd.DataFrame:
    rows = []
    for k in k_values:
        model = KMeans(n_clusters=k, random_state=42, n_init=20)
        labels = model.fit_predict(X_scaled)
        inertia = model.inertia_
        sil = silhouette_score(X_scaled, labels) if len(set(labels)) > 1 else np.nan
        rows.append({"k": k, "inertia": inertia, "silhouette_score": sil})
    return pd.DataFrame(rows)


def choose_cluster_name(row: pd.Series) -> str:
    severity = row.get("severity_rank", 0)
    score = row.get("max_score", 0)
    duration = row.get("duration_sec", 0)

    if severity >= 3 or score >= 0.7 or duration >= 100:
        return "Critical Incidents"
    if severity >= 2 or score >= 0.4 or duration >= 30:
        return "Moderate Incidents"
    return "Minor Incidents"


def run_kmeans(k: int = 3):
    print(" Lancement K-Means professionnel...", flush=True)

    incidents = load_incidents()
    print(f"Nombre d'incidents chargés : {len(incidents)}", flush=True)

    incidents_ready, feature_names = prepare_features(incidents)
    if incidents_ready.empty:
        raise ValueError("Aucune ligne exploitable après préparation des features.")

    X = incidents_ready[feature_names].copy()

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Elbow + silhouette
    eval_df = elbow_and_silhouette(X_scaled, k_values=range(2, 7))
    eval_df.to_csv(OUTPUT_DIR / "kmeans_model_selection.csv", index=False)

    plt.figure(figsize=(8, 5))
    plt.plot(eval_df["k"], eval_df["inertia"], marker="o")
    plt.title("K-Means Elbow Method")
    plt.xlabel("Nombre de clusters (k)")
    plt.ylabel("Inertia")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "elbow_method.png", dpi=150)
    plt.close()

    plt.figure(figsize=(8, 5))
    plt.plot(eval_df["k"], eval_df["silhouette_score"], marker="o")
    plt.title("K-Means Silhouette Score")
    plt.xlabel("Nombre de clusters (k)")
    plt.ylabel("Silhouette Score")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "silhouette_scores.png", dpi=150)
    plt.close()

    # Final model
    model = KMeans(n_clusters=k, random_state=42, n_init=20)
    labels = model.fit_predict(X_scaled)

    clustered = incidents_ready.copy()
    clustered["cluster_id"] = labels

    # PCA
    pca = PCA(n_components=2, random_state=42)
    X_pca = pca.fit_transform(X_scaled)
    clustered["pca_1"] = X_pca[:, 0]
    clustered["pca_2"] = X_pca[:, 1]

    plt.figure(figsize=(8, 6))
    for cluster in sorted(clustered["cluster_id"].unique()):
        subset = clustered[clustered["cluster_id"] == cluster]
        plt.scatter(subset["pca_1"], subset["pca_2"], label=f"Cluster {cluster}", alpha=0.7)

    plt.title("Projection PCA des clusters K-Means")
    plt.xlabel("PCA 1")
    plt.ylabel("PCA 2")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "clusters_pca.png", dpi=150)
    plt.close()

    # Cluster summary
    summary_features = [f for f in feature_names if f in clustered.columns]
    cluster_summary = clustered.groupby("cluster_id")[summary_features].mean().round(3)

    if "incident_type" in clustered.columns:
        cluster_summary["dominant_incident_type"] = (
            clustered.groupby("cluster_id")["incident_type"]
            .agg(lambda x: x.mode().iloc[0] if not x.mode().empty else "N/A")
        )

    if "severity" in clustered.columns:
        cluster_summary["dominant_severity"] = (
            clustered.groupby("cluster_id")["severity"]
            .agg(lambda x: x.mode().iloc[0] if not x.mode().empty else "N/A")
        )

    cluster_summary["cluster_size"] = clustered["cluster_id"].value_counts().sort_index()

    # Add business labels
    cluster_summary["cluster_label"] = cluster_summary.apply(choose_cluster_name, axis=1)

    cluster_summary.to_csv(OUTPUT_DIR / "cluster_summary.csv")

    # Save clustered incidents
    clustered.to_csv(OUTPUT_DIR / "incidents_clustered.csv", index=False)

    # Save model artifacts
    joblib.dump(model, OUTPUT_DIR / "kmeans_model.joblib")
    joblib.dump(scaler, OUTPUT_DIR / "kmeans_scaler.joblib")
    joblib.dump(feature_names, OUTPUT_DIR / "kmeans_features.joblib")

    metadata = {
        "chosen_k": k,
        "feature_names": feature_names,
        "n_samples": int(len(clustered)),
        "silhouette_final": float(silhouette_score(X_scaled, labels)),
    }

    with open(OUTPUT_DIR / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print("\nK-Means termine.", flush=True)
    print(cluster_summary, flush=True)


if __name__ == "__main__":
    run_kmeans(k=3)