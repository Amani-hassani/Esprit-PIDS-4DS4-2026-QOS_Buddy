"""PyTorch LSTM multi-label trainer with MinMaxScaler fit on training windows only."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import joblib
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import MinMaxScaler
from torch.utils.data import DataLoader, TensorDataset

from config import LSTM_WINDOW, N_SPLITS, SAVED_MODELS_DIR, TARGET_NAMES
from data_pipeline.features import resolve_feature_columns

import logging
logger = logging.getLogger(__name__)


@dataclass
class LSTMTrainArtifacts:
    state_dict: dict
    scaler_object: MinMaxScaler | None = None  # ✅ Full scaler object (preferred)
    scaler_min: np.ndarray | None = None       # ⚠️ Deprecated (fragile private attrs)
    scaler_max: np.ndarray | None = None       # ⚠️ Deprecated (fragile private attrs)
    feature_cols: List[str] | None = None
    window: int = LSTM_WINDOW


class QoSLSTM(nn.Module):
    def __init__(self, input_dim: int, hidden: int = 128, layers: int = 2, out_dim: int = 6):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden,
            num_layers=layers,
            batch_first=True,
            dropout=0.3,
        )
        self.fc1 = nn.Linear(hidden, 64)
        self.act = nn.ReLU()
        self.drop = nn.Dropout(0.2)
        self.fc2 = nn.Linear(64, out_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        last = out[:, -1, :]
        h = self.act(self.fc1(last))
        h = self.drop(h)
        return self.fc2(h)


def _build_windows(
    df: pd.DataFrame, feature_cols: List[str], window: int
) -> Tuple[np.ndarray, np.ndarray]:
    """Build time-series windows for LSTM training (no leakage).
    
    Each window contains historical feature data and a corresponding label from the next timestep.
    This ensures no temporal leakage: the model sees past data and predicts future events.
    
    Issue #3 FIX: Logs skipped nodes explicitly (no silent failures).
    """
    X_list: list[np.ndarray] = []
    y_list: list[np.ndarray] = []
    
    skipped_nodes: list[tuple[str, int, str]] = []  # (node_id, rows, reason)
    processed_nodes = 0
    total_rows_used = 0
    total_rows_skipped = 0
    
    for node_id, g in df.groupby("node_id", sort=False):
        g = g.reset_index(drop=True)
        if len(g) <= window:
            skipped_nodes.append((str(node_id), len(g), f"rows <= window ({window})"))
            total_rows_skipped += len(g)
            continue
            
        processed_nodes += 1
        feats = g[feature_cols].to_numpy(dtype=np.float32)
        labels = g[list(TARGET_NAMES)].to_numpy(dtype=np.float32)
        
        for t in range(window, len(g)):
            X_list.append(feats[t - window : t, :])  # rows [t-window, ..., t-1]
            y_list.append(labels[t, :])              # row t (future data, safe)
            total_rows_used += 1
    
    # Log skipped nodes diagnostics (Issue #3 FIX)
    if skipped_nodes:
        logger.warning(
            f"_build_windows: Skipped {len(skipped_nodes)} nodes ({total_rows_skipped} rows). "
            f"Processed {processed_nodes} nodes ({total_rows_used} windows)."
        )
        for node_id, n_rows, reason in skipped_nodes[:10]:  # Log first 10
            logger.debug(f"  Skipped node_id={node_id}: {n_rows} rows ({reason})")
        if len(skipped_nodes) > 10:
            logger.debug(f"  ... and {len(skipped_nodes) - 10} more skipped nodes")
    else:
        logger.info(
            f"_build_windows: Processed {processed_nodes} nodes, "
            f"generated {total_rows_used} windows (all rows used)."
        )
    
    if not X_list:
        logger.error(
            f"_build_windows: CRITICAL - No windows generated! "
            f"Check that data has nodes with >{window} rows."
        )
        return np.empty((0, window, len(feature_cols))), np.empty((0, len(TARGET_NAMES)))
    
    X_arr = np.stack(X_list, axis=0)
    y_arr = np.vstack(y_list)
    return X_arr, y_arr


def train_lstm(
    df: pd.DataFrame,
    out_path: Path | None = None,
    epochs: int = 25,
    batch_size: int = 64,
    lr: float = 1e-3,
    device: str | None = None,
    random_state: int = 42,
) -> Path:
    out_path = Path(out_path) if out_path is not None else SAVED_MODELS_DIR / "lstm_qos.pt"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    feature_cols = resolve_feature_columns(df)
    if not feature_cols:
        raise ValueError("No feature columns for LSTM.")

    X_win, y_win = _build_windows(df, feature_cols, LSTM_WINDOW)
    if len(X_win) < 32:
        raise ValueError("Not enough sequences to train LSTM (need more rows per node).")

    tss = TimeSeriesSplit(n_splits=N_SPLITS)
    last_train_idx = None
    for train_idx, _ in tss.split(X_win):
        last_train_idx = train_idx
    assert last_train_idx is not None

    X_train = X_win[last_train_idx]
    y_train = y_win[last_train_idx]

    nsamples, nsteps, nfeat = X_train.shape
    flat = X_train.reshape(-1, nfeat)
    scaler = MinMaxScaler()
    scaler.fit(flat)

    def scale(batch: np.ndarray) -> np.ndarray:
        b, t, f = batch.shape
        z = scaler.transform(batch.reshape(-1, f)).reshape(b, t, f)
        return z.astype(np.float32)

    X_train_s = scale(X_train)

    dev = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    torch.manual_seed(random_state)
    np.random.seed(random_state)

    model = QoSLSTM(input_dim=nfeat).to(dev)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.BCEWithLogitsLoss()

    ds = TensorDataset(
        torch.from_numpy(X_train_s),
        torch.from_numpy(y_train).float(),
    )
    dl = DataLoader(ds, batch_size=batch_size, shuffle=False)

    model.train()
    for _ in range(epochs):
        for xb, yb in dl:
            xb = xb.to(dev)
            yb = yb.to(dev)
            opt.zero_grad()
            pred = model(xb)
            loss = loss_fn(pred, yb)
            loss.backward()
            opt.step()

    model.eval()
    artifacts = LSTMTrainArtifacts(
        state_dict=model.state_dict(),
        scaler_object=scaler,  # ✅ Save entire scaler object (robust)
        scaler_min=None,       # ⚠️ Deprecated (no longer using private attributes)
        scaler_max=None,       # ⚠️ Deprecated (no longer using private attributes)
        feature_cols=feature_cols,
        window=LSTM_WINDOW,
    )
    torch.save(artifacts.__dict__, out_path)
    joblib.dump(feature_cols, out_path.parent / "lstm_feature_columns.joblib")
    return out_path


def load_lstm_artifacts(path: Path | None = None) -> LSTMTrainArtifacts:
    """Load LSTM artifacts from saved checkpoint.
    
    Handles both new format (scaler_object) and legacy format (scaler_min/max).
    
    Args:
        path: Path to saved artifacts (default: models/saved/lstm_qos.pt)
        
    Returns:
        LSTMTrainArtifacts with state_dict, scaler, and feature columns
        
    Notes:
        - If new format (scaler_object): uses full MinMaxScaler directly
        - If legacy format (scaler_min/max): reconstructs scaler_min/max for scale_window()
    """
    p = Path(path) if path is not None else SAVED_MODELS_DIR / "lstm_qos.pt"
    try:
        raw = torch.load(p, map_location="cpu", weights_only=False)
    except TypeError:
        raw = torch.load(p, map_location="cpu")
    
    # Handle scaler: prefer scaler_object if available (new format)
    scaler_object = raw.get("scaler_object", None)
    scaler_min = raw.get("scaler_min", None)
    scaler_max = raw.get("scaler_max", None)
    
    if scaler_object is None and scaler_min is not None and scaler_max is not None:
        # Legacy format: reconstruct from saved min/max for backward compatibility
        # Create a dummy scaler with the loaded parameters
        scaler_object = MinMaxScaler()
        scaler_object.data_min_ = scaler_min
        scaler_object.data_max_ = scaler_max
        scaler_object.n_features_in_ = len(scaler_min)
    
    return LSTMTrainArtifacts(
        state_dict=raw["state_dict"],
        scaler_object=scaler_object,
        scaler_min=None,  # Not used anymore if scaler_object is available
        scaler_max=None,  # Not used anymore if scaler_object is available
        feature_cols=list(raw["feature_cols"]),
        window=int(raw["window"]),
    )


def scale_window(
    x: np.ndarray, 
    scaler_min: np.ndarray | None = None, 
    scaler_max: np.ndarray | None = None,
    scaler_object: MinMaxScaler | None = None,
) -> np.ndarray:
    """Apply MinMaxScaler normalization to a window of features.
    
    Supports both:
    - New method: Full scaler_object (robust, recommended)
    - Legacy method: Reconstructed from scaler_min/max (fragile but backward-compatible)
    
    Args:
        x: Feature array of shape (batch, window_size, n_features) or (window_size, n_features)
        scaler_min: [Deprecated] Minimum values from training (legacy reconstruction)
        scaler_max: [Deprecated] Maximum values from training (legacy reconstruction)
        scaler_object: MinMaxScaler object (preferred, new method)
        
    Returns:
        Scaled array with values in [0, 1], same shape as input
        
    Raises:
        ValueError: If neither scaler_object nor scaler_min/max provided
        
    Notes:
        - If scaler_object available: uses it directly (no fragile private attribute access)
        - If only min/max available: manually reconstructs transformation (legacy)
        - Features with zero range (constant in training) → output 0
        - Out-of-distribution values clipped to [0, 1]
    """
    # Ensure 3D shape for batch processing
    original_shape = x.shape
    if x.ndim == 2:
        x = x[np.newaxis, :, :]
    
    if x.ndim != 3:
        raise ValueError(f"Expected 2D or 3D input, got {original_shape}")
    
    batch_size, window_size, n_features = x.shape
    
    # Use scaler_object if available (new, robust method)
    if scaler_object is not None:
        try:
            # Reshape for sklearn: (batch*window, n_features)
            x_flat = x.reshape(-1, n_features)
            x_scaled_flat = scaler_object.transform(x_flat)
            x_scaled = x_scaled_flat.reshape(batch_size, window_size, n_features)
            return x_scaled.astype(np.float32)
        except Exception as e:
            raise ValueError(
                f"Scaler transform failed: {e}\n"
                f"Input shape: {original_shape}, Expected n_features: {scaler_object.n_features_in_}"
            ) from e
    
    # Fallback: reconstruct from scaler_min/max (legacy, backward-compatible)
    if scaler_min is None or scaler_max is None:
        raise ValueError(
            "Must provide either scaler_object (new method) or both scaler_min/max (legacy)"
        )
    
    # Validate dimensions
    if len(scaler_min) != n_features or len(scaler_max) != n_features:
        raise ValueError(
            f"Scaler dimensions mismatch: got {n_features} features, "
            f"but scaler has {len(scaler_min)} dimensions"
        )
    
    # Manual reconstruction: (x - min) / (max - min)
    denom = np.where(
        (scaler_max - scaler_min) == 0,
        1.0,  # Avoid division by zero
        (scaler_max - scaler_min)
    )
    
    z = (x - scaler_min) / denom
    return np.clip(z, 0.0, 1.0).astype(np.float32)
