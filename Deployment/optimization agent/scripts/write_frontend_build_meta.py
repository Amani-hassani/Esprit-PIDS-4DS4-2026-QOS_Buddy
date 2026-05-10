from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from deployment.release import write_build_meta


if __name__ == "__main__":
    path = write_build_meta()
    print(path)
