from pathlib import Path
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import joblib

from sklearn.preprocessing import StandardScaler

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset


DATA_DIR = Path("data")
OUTPUT_DIR = Path("outputs/autoencoder_pro")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_timeseries() -> pd.DataFrame:
    files = sorted(DATA_DIR.glob("qos_timeseries_*.csv"))
    if not files:
        raise FileNotFoundError("Aucun fichier qos_timeseries_*.csv trouve dans data/")

    dfs = []
    for file in files:
        df = pd.read_csv(file)
        df["source_file"] = file.name
        dfs.append(df)

    df = pd.concat(dfs, ignore_index=True)

    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

    return df


def prepare_features(df: pd.DataFrame):
    work = df.copy()

    feature_names = [
        "latency_ms",
        "jitter_ms",
        "packet_loss_pct",
        "throughput_mbps",
        "rsrp_dbm",
        "sinr_db",
        "channel_util_pct"
    ]
    feature_names = [f for f in feature_names if f in work.columns]

    if not feature_names:
        raise ValueError("Aucune feature exploitable pour l'autoencoder.")

    for col in feature_names:
        work[col] = pd.to_numeric(work[col], errors="coerce")

    work = work.dropna(subset=feature_names).copy()

    if "anomaly_flag" in work.columns:
        work["anomaly_flag_str"] = work["anomaly_flag"].astype(str).str.lower()
    else:
        work["anomaly_flag_str"] = "false"

    normal_df = work[work["anomaly_flag_str"] == "false"].copy()
    if normal_df.empty:
        raise ValueError("Aucune donnee normale disponible pour entrainer l'autoencoder.")

    return work, normal_df, feature_names


class Autoencoder(nn.Module):
    def __init__(self, input_dim: int):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, 32),
            nn.ReLU(),
            nn.Linear(32, 16),
            nn.ReLU(),
            nn.Linear(16, 8),
            nn.ReLU(),
        )
        self.decoder = nn.Sequential(
            nn.Linear(8, 16),
            nn.ReLU(),
            nn.Linear(16, 32),
            nn.ReLU(),
            nn.Linear(32, input_dim),
        )

    def forward(self, x):
        z = self.encoder(x)
        out = self.decoder(z)
        return out


def assign_dl_label(row: pd.Series) -> str:
    error = row.get("reconstruction_error", 0.0)
    threshold_95 = row.get("threshold_95", np.inf)
    threshold_99 = row.get("threshold_99", np.inf)

    if error > threshold_99:
        return "Highly Atypical Time Window"
    if error > threshold_95:
        return "Atypical Time Window"
    return "Typical Time Window"


def train_autoencoder(model, train_loader, val_loader, device, epochs=50, lr=0.001, patience=10):
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)

    best_val_loss = float("inf")
    best_state = None
    patience_counter = 0

    history = {
        "train_loss": [],
        "val_loss": []
    }

    for epoch in range(epochs):
        model.train()
        train_losses = []

        for batch_x, in train_loader:
            batch_x = batch_x.to(device)

            optimizer.zero_grad()
            outputs = model(batch_x)
            loss = criterion(outputs, batch_x)
            loss.backward()
            optimizer.step()

            train_losses.append(loss.item())

        model.eval()
        val_losses = []

        with torch.no_grad():
            for batch_x, in val_loader:
                batch_x = batch_x.to(device)
                outputs = model(batch_x)
                loss = criterion(outputs, batch_x)
                val_losses.append(loss.item())

        train_loss = float(np.mean(train_losses)) if train_losses else 0.0
        val_loss = float(np.mean(val_losses)) if val_losses else 0.0

        history["train_loss"].append(train_loss)
        history["val_loss"].append(val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = model.state_dict()
            patience_counter = 0
        else:
            patience_counter += 1

        if patience_counter >= patience:
            break

    if best_state is not None:
        model.load_state_dict(best_state)

    return history


def run_autoencoder():
    print("Lancement Autoencoder professionnel avec PyTorch...", flush=True)

    df = load_timeseries()
    print(f"Nombre total de mesures chargees : {len(df)}", flush=True)

    full_df, normal_df, feature_names = prepare_features(df)

    print(f"Nombre de mesures normales pour l'entrainement : {len(normal_df)}", flush=True)
    print(f"Features utilisees : {feature_names}", flush=True)

    scaler = StandardScaler()
    X_train_full = scaler.fit_transform(normal_df[feature_names])
    X_all = scaler.transform(full_df[feature_names])

    # Split train / val
    split_idx = int(len(X_train_full) * 0.8)
    X_train = X_train_full[:split_idx]
    X_val = X_train_full[split_idx:] if split_idx < len(X_train_full) else X_train_full[:1]

    X_train_tensor = torch.tensor(X_train, dtype=torch.float32)
    X_val_tensor = torch.tensor(X_val, dtype=torch.float32)
    X_all_tensor = torch.tensor(X_all, dtype=torch.float32)

    train_loader = DataLoader(TensorDataset(X_train_tensor), batch_size=32, shuffle=True)
    val_loader = DataLoader(TensorDataset(X_val_tensor), batch_size=32, shuffle=False)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = Autoencoder(input_dim=len(feature_names)).to(device)

    history = train_autoencoder(
        model=model,
        train_loader=train_loader,
        val_loader=val_loader,
        device=device,
        epochs=50,
        lr=0.001,
        patience=10
    )

    model.eval()
    with torch.no_grad():
        X_all_pred = model(X_all_tensor.to(device)).cpu().numpy()

    reconstruction_error = np.mean(np.power(X_all - X_all_pred, 2), axis=1)

    threshold_95 = np.percentile(reconstruction_error, 95)
    threshold_99 = np.percentile(reconstruction_error, 99)

    result_df = full_df.copy()
    result_df["reconstruction_error"] = reconstruction_error
    result_df["threshold_95"] = threshold_95
    result_df["threshold_99"] = threshold_99
    result_df["dl_anomaly_flag"] = result_df["reconstruction_error"] > threshold_95
    result_df["dl_label"] = result_df.apply(assign_dl_label, axis=1)

    result_df.to_csv(OUTPUT_DIR / "autoencoder_results.csv", index=False)

    top_anomalies = result_df.sort_values("reconstruction_error", ascending=False).head(20).copy()

    top_cols = [c for c in [
        "timestamp",
        "latency_ms",
        "jitter_ms",
        "packet_loss_pct",
        "throughput_mbps",
        "rsrp_dbm",
        "sinr_db",
        "channel_util_pct",
        "anomaly_type",
        "anomaly_score",
        "reconstruction_error",
        "dl_anomaly_flag",
        "dl_label",
        "source_file"
    ] if c in top_anomalies.columns]

    top_anomalies[top_cols].to_csv(OUTPUT_DIR / "top_dl_anomalies.csv", index=False)

    # Distribution des erreurs
    plt.figure(figsize=(8, 5))
    plt.hist(result_df["reconstruction_error"], bins=30)
    plt.axvline(threshold_95, linestyle="--", label="Seuil 95e percentile")
    plt.axvline(threshold_99, linestyle="--", label="Seuil 99e percentile")
    plt.title("Distribution des erreurs de reconstruction")
    plt.xlabel("Reconstruction Error")
    plt.ylabel("Nombre de mesures")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "reconstruction_error_distribution.png", dpi=150)
    plt.close()

    # Erreur dans le temps
    if "timestamp" in result_df.columns:
        plot_df = result_df.dropna(subset=["timestamp"]).copy()
        plot_df = plot_df.sort_values("timestamp")

        plt.figure(figsize=(10, 5))
        plt.plot(plot_df["timestamp"], plot_df["reconstruction_error"], label="Erreur reconstruction")
        plt.axhline(threshold_95, linestyle="--", label="Seuil 95e percentile")
        plt.title("Erreur de reconstruction dans le temps")
        plt.xlabel("Temps")
        plt.ylabel("Reconstruction Error")
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(OUTPUT_DIR / "reconstruction_error_timeseries.png", dpi=150)
        plt.close()

    # Courbe d'apprentissage
    plt.figure(figsize=(8, 5))
    plt.plot(history["train_loss"], label="Train Loss")
    plt.plot(history["val_loss"], label="Validation Loss")
    plt.title("Courbe d'apprentissage Autoencoder")
    plt.xlabel("Epoch")
    plt.ylabel("Loss")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "training_loss.png", dpi=150)
    plt.close()

    # Sauvegardes
    torch.save(model.state_dict(), OUTPUT_DIR / "autoencoder_model.pt")
    joblib.dump(scaler, OUTPUT_DIR / "autoencoder_scaler.joblib")
    joblib.dump(feature_names, OUTPUT_DIR / "autoencoder_features.joblib")

    metadata = {
        "framework": "PyTorch",
        "n_total_samples": int(len(result_df)),
        "n_training_normal_samples": int(len(normal_df)),
        "n_dl_anomalies": int(result_df["dl_anomaly_flag"].sum()),
        "dl_anomaly_ratio": round(float(result_df["dl_anomaly_flag"].mean()), 4),
        "threshold_95": float(threshold_95),
        "threshold_99": float(threshold_99),
        "feature_names": feature_names,
        "epochs_trained": int(len(history["train_loss"]))
    }

    with open(OUTPUT_DIR / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print("\nAutoencoder termine.", flush=True)
    print(json.dumps(metadata, indent=2), flush=True)
    print("\nTop anomalies DL :", flush=True)
    print(top_anomalies[top_cols].head(10), flush=True)


if __name__ == "__main__":
    run_autoencoder()