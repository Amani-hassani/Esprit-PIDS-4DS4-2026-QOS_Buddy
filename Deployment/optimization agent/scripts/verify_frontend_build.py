from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from deployment.core.settings import get_settings
from deployment.release import frontend_build_status


def main() -> int:
    status = frontend_build_status()
    payload = status.to_dict()
    if not status.ok:
        print(payload)
        return 1

    build_dir = get_settings().paths.frontend_build
    js_assets = sorted(build_dir.rglob("*.js"))
    contents = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in js_assets)
    forbidden = ['searchParams.set("token"', "searchParams.set('token'"]
    required = ["/api/session"]
    payload["bundle_checks"] = {
        "forbidden_patterns": [pattern for pattern in forbidden if pattern in contents],
        "required_patterns_missing": [pattern for pattern in required if pattern not in contents],
    }
    print(payload)
    return 0 if not payload["bundle_checks"]["forbidden_patterns"] and not payload["bundle_checks"]["required_patterns_missing"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
