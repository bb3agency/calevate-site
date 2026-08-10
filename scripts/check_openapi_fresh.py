"""Guardrail: the committed OpenAPI snapshot matches the live app (D-29).

The frontend's types are generated from `apps/web/src/lib/api/openapi.json`. When a
response model changes and nobody re-runs `pnpm gen:api`, TypeScript keeps compiling
against a schema the server no longer serves — and the failure appears at runtime, in
a browser, as a field that is silently undefined.

So the snapshot is committed and this check regenerates it in memory and diffs. It
compares PATHS and SCHEMAS rather than the whole document, because the parts that
legitimately churn (descriptions, examples) are not what breaks a typed client.

Run: `uv run python -m scripts.check_openapi_fresh`  (`--write` to refresh)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SNAPSHOT = (
    Path(__file__).resolve().parent.parent / "apps" / "web" / "src" / "lib" / "api" / "openapi.json"
)


def _shape(spec: dict[str, Any]) -> dict[str, Any]:
    """The parts a typed client actually depends on."""
    return {
        "paths": {
            path: sorted(m for m in operations if m in ("get", "post", "patch", "put", "delete"))
            for path, operations in sorted(spec.get("paths", {}).items())
        },
        "schemas": {
            name: sorted(definition.get("properties", {}))
            for name, definition in sorted(spec.get("components", {}).get("schemas", {}).items())
        },
    }


def main() -> int:
    from apps.api.main import app

    live = app.openapi()
    write = "--write" in sys.argv

    if write:
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(live, indent=2, sort_keys=True) + "\n")
        print(f"OPENAPI: snapshot refreshed ({len(live.get('paths', {}))} paths)")
        print("Now run: pnpm -C apps/web gen:api")
        return 0

    if not SNAPSHOT.exists():
        print(f"OPENAPI: FAIL — no snapshot at {SNAPSHOT}")
        print("Run: uv run python -m scripts.check_openapi_fresh --write")
        return 1

    committed = _shape(json.loads(SNAPSHOT.read_text()))
    current = _shape(live)
    if committed == current:
        print(f"OPENAPI: OK ({len(current['paths'])} paths, {len(current['schemas'])} schemas)")
        return 0

    print("OPENAPI: FAIL — the committed schema is stale")
    for label, key in (("path", "paths"), ("schema", "schemas")):
        added = sorted(set(current[key]) - set(committed[key]))
        removed = sorted(set(committed[key]) - set(current[key]))
        changed = sorted(
            name
            for name in set(current[key]) & set(committed[key])
            if current[key][name] != committed[key][name]
        )
        for name in added:
            print(f"  + {label} {name}")
        for name in removed:
            print(f"  - {label} {name}")
        for name in changed:
            print(f"  ~ {label} {name}")
    print(
        "\nRegenerate: uv run python -m scripts.check_openapi_fresh --write "
        "&& pnpm -C apps/web gen:api"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
