from pathlib import Path
import pandas as pd

DATA_DIR = Path("data")


def load_timeseries() -> pd.DataFrame:
    files = sorted(DATA_DIR.glob("qos_timeseries_*.csv"))
    if not files:
        raise FileNotFoundError("Aucun fichier qos_timeseries_*.csv trouvé dans data/")

    dfs = []
    for file in files:
        df = pd.read_csv(file)
        df["source_file"] = file.name
        dfs.append(df)

    result = pd.concat(dfs, ignore_index=True)

    if "timestamp" in result.columns:
        result["timestamp"] = pd.to_datetime(result["timestamp"], errors="coerce")

    return result.sort_values("timestamp", na_position="last").reset_index(drop=True)


def load_incidents() -> pd.DataFrame:
    files = sorted(DATA_DIR.glob("incidents_*.csv"))
    if not files:
        raise FileNotFoundError("Aucun fichier incidents_*.csv trouvé dans data/")

    dfs = []
    for file in files:
        df = pd.read_csv(file)
        df["source_file"] = file.name
        dfs.append(df)

    result = pd.concat(dfs, ignore_index=True)

    if "start_timestamp" in result.columns:
        result["start_timestamp"] = pd.to_datetime(result["start_timestamp"], errors="coerce")
    if "end_timestamp" in result.columns:
        result["end_timestamp"] = pd.to_datetime(result["end_timestamp"], errors="coerce")

    return result.sort_values("start_timestamp", na_position="last").reset_index(drop=True)


def safe_value(row: dict, key: str, default="N/A"):
    value = row.get(key, default)
    if pd.isna(value):
        return default
    return value


def to_float(value, default=None):
    try:
        if value is None:
            return default
        if isinstance(value, str) and value.strip() == "":
            return default
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default