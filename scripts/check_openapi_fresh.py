"""Guardrail: the committed OpenAPI snapshot matches the live app (D-29).

The frontend's types are generated from `apps/web/src/lib/api/openapi.json`. When a
response model changes and nobody re-runs `pnpm gen:api`, TypeScript keeps compiling
against a schema the server no longer serves — and the failure appears at runtime, in
a browser, as a field that is silently undefined.

So the snapshot is committed and this check regenerates it in memory and diffs. It
compares the CONTRACT rather than the whole document, because the parts that
legitimately churn (descriptions, summaries, titles, examples) are not what breaks a
typed client. The contract is:

- per operation: the methods, the **declared permission** (`x-calevate-permission`),
  the parameters (name/in/required), the request body model and the response status
  codes with their models. A route whose permission changed while its path did not is
  a client-visible change — the old shape compared paths and property NAMES only, so
  `calls:read_raw` quietly becoming `calls:read` produced no diff at all.
- per schema: each property's type signature (type/format/$ref/enum/nullability) and
  the required list. A field flipping `str -> int` or optional -> required breaks the
  generated client exactly as loudly as a renamed field.

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

METHODS = ("get", "post", "patch", "put", "delete")
# Prose. It changes constantly and breaks nothing downstream.
_COSMETIC = frozenset({"title", "description", "summary", "example", "examples", "tags"})
# Validation bounds. `le=200` becoming `le=500` is a server-side policy change: the
# generated TypeScript is byte-identical either way, so making it fail this guardrail
# would train everyone to regenerate the snapshot without reading the diff — which is
# how a guardrail stops being read at all.
_VALIDATION = frozenset(
    {
        "default",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "uniqueItems",
    }
)
_IGNORED = _COSMETIC | _VALIDATION


def _signature(node: Any) -> Any:
    """A schema fragment with prose and validation stripped — what is left is the
    contract a generated client is compiled against."""
    if isinstance(node, dict):
        return {k: _signature(v) for k, v in sorted(node.items()) if k not in _IGNORED}
    if isinstance(node, list):
        return [_signature(item) for item in node]
    return node


def _operation_shape(operation: dict[str, Any]) -> dict[str, Any]:
    body = operation.get("requestBody", {}) or {}
    return {
        "permission": operation.get("x-calevate-permission"),
        "operationId": operation.get("operationId"),
        "parameters": sorted(
            [
                p.get("name", ""),
                p.get("in", ""),
                str(bool(p.get("required"))),
                json.dumps(_signature(p.get("schema", {})), sort_keys=True),
            ]
            for p in operation.get("parameters", []) or []
        ),
        "requestBody": json.dumps(_signature(body.get("content", {})), sort_keys=True),
        "responses": {
            str(status): json.dumps(_signature(response.get("content", {})), sort_keys=True)
            for status, response in sorted((operation.get("responses", {}) or {}).items())
        },
    }


def _shape(spec: dict[str, Any]) -> dict[str, Any]:
    """The parts a typed client — and a reviewer reading a permission — depend on."""
    return {
        "paths": {
            path: {
                method: _operation_shape(operation)
                for method, operation in sorted(operations.items())
                if method in METHODS and isinstance(operation, dict)
            }
            for path, operations in sorted(spec.get("paths", {}).items())
        },
        "schemas": {
            name: {
                "required": sorted(definition.get("required", []) or []),
                "properties": {
                    prop: json.dumps(_signature(schema), sort_keys=True)
                    for prop, schema in sorted((definition.get("properties", {}) or {}).items())
                },
            }
            for name, definition in sorted(spec.get("components", {}).get("schemas", {}).items())
        },
    }


def diff(committed: dict[str, Any], current: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for label, key in (("path", "paths"), ("schema", "schemas")):
        added = sorted(set(current[key]) - set(committed[key]))
        removed = sorted(set(committed[key]) - set(current[key]))
        changed = sorted(
            name
            for name in set(current[key]) & set(committed[key])
            if current[key][name] != committed[key][name]
        )
        lines += [f"  + {label} {name}" for name in added]
        lines += [f"  - {label} {name}" for name in removed]
        for name in changed:
            lines.append(f"  ~ {label} {name}")
            was, now = committed[key][name], current[key][name]
            if isinstance(was, dict) and isinstance(now, dict):
                for field in sorted(set(was) | set(now)):
                    if was.get(field) != now.get(field):
                        lines.append(f"      {field}: {was.get(field)!r} -> {now.get(field)!r}")
    return lines


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
        print(
            f"OPENAPI: OK ({len(current['paths'])} paths, {len(current['schemas'])} schemas; "
            "permissions, parameters and property types compared)"
        )
        return 0

    print("OPENAPI: FAIL — the committed schema is stale")
    for line in diff(committed, current):
        print(line)
    print(
        "\nRegenerate: uv run python -m scripts.check_openapi_fresh --write "
        "&& pnpm -C apps/web gen:api"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
