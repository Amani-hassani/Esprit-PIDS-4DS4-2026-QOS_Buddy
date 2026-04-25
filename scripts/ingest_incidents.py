"""Load incident CSVs and ingest them into the Chroma incident store."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_pipeline.loader import load_incidents
from rag.incident_store import IncidentStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest incidents into ChromaDB.")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Drop and recreate the collection before ingest.",
    )
    args = parser.parse_args()

    df = load_incidents()
    if df.empty:
        print("No incident rows found; nothing to ingest.")
        return

    store = IncidentStore()
    n = store.ingest(df, replace=args.replace)
    print(f"Ingested {n} incidents into {store.persist_dir}")


if __name__ == "__main__":
    main()
