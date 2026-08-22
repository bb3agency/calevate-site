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

AND IT CHECKS THE OTHER HALF OF THE SAME SEAM: that `schema.d.ts` — the TypeScript the
screens actually compile against — was regenerated from that snapshot. Two files go stale
here, not one, and only this one was ever guarded: a lane that ran `--write` and skipped
`pnpm gen:api` left the frontend compiling against the PREVIOUS contract, `tsc --noEmit`
green, and the drift invisible until a field came back undefined in a browser. That is not
hypothetical — it is how `LifecycleOut` was renamed to `AgentLifecycleOut` on the server
while two `lib/api/*.ts` modules still aliased the collision-qualified names the generator
had stopped emitting.

The comparison is the NAME SETS — every path, every component schema, every operationId —
and deliberately not the property types: openapi-typescript's output format is its own to
change between versions, and a guardrail that re-implements a generator is a guardrail that
fails on an upgrade. Names are what the modules under `src/lib/api/` index into by hand
(`components["schemas"]["AgentLifecycleOut"]`), so a name set that matches is the property
those aliases depend on. This half needs no Node, which is why it can run in CI's Python
job beside the snapshot check rather than in the frontend one.

Run: `uv run python -m scripts.check_openapi_fresh`  (`--write` to refresh)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_API_DIR = Path(__file__).resolve().parent.parent / "apps" / "web" / "src" / "lib" / "api"
SNAPSHOT = _API_DIR / "openapi.json"
#: What `pnpm -C apps/web gen:api` writes FROM the snapshot. Guarded together with it.
GENERATED = _API_DIR / "schema.d.ts"

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


# ------------------------------------------------------------------ the generated half
#
# openapi-typescript writes ONE `export interface <block> {` per section and one key per
# name inside it, at a fixed indent. Reading those key lines is the whole parser: it needs
# no Node, no TypeScript AST and no knowledge of how the generator renders a TYPE — which
# is the part that is free to change under an upgrade.

#: `interface <name> {` -> the indent its own keys sit at. `components` is skipped and
#: `schemas` read directly, because the schema names are one level further in.
_BLOCKS = (
    ("paths", "export interface paths {", 4),
    ("schemas", "    schemas: {", 8),
    ("operations", "export interface operations {", 4),
)


def _keys_at(text: str, header: str, indent: int) -> set[str]:
    """The key names declared directly inside `header`'s block, at exactly `indent`.

    Stops at the first line that dedents past the block — the closing brace — so a nested
    object's own keys (which sit deeper) are never mistaken for the block's.
    """
    lines = text.splitlines()
    try:
        start = lines.index(header)
    except ValueError:
        return set()
    pad = " " * indent
    names: set[str] = set()
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped and not line.startswith(pad):
            break  # the block's own closing brace, at a shallower indent
        if not line.startswith(pad) or line.startswith(pad + " "):
            continue
        key, sep, _ = stripped.partition(":")
        if not sep:
            continue
        names.add(key.rstrip("?").strip('"'))
    return names


def _generated_names(spec: dict[str, Any]) -> dict[str, set[str]]:
    """The names `gen:api` MUST have emitted for this snapshot."""
    operations = {
        operation["operationId"]
        for methods in spec.get("paths", {}).values()
        for method, operation in methods.items()
        if method in METHODS and isinstance(operation, dict) and operation.get("operationId")
    }
    return {
        "paths": set(spec.get("paths", {})),
        "schemas": set(spec.get("components", {}).get("schemas", {})),
        "operations": operations,
    }


def generated_drift(spec: dict[str, Any], generated: str) -> list[str]:
    """Names the snapshot declares that `schema.d.ts` does not carry, and vice versa.

    THE PREMISE IS ASSERTED, not assumed. This reads openapi-typescript's OUTPUT FORMAT —
    one `export interface <block> {` per section, one key per name at a fixed indent — and
    that format is the generator's to change on an upgrade. A parser that quietly stopped
    matching would report every name as MISSING, which at least fails loudly; a parser that
    matched a block and found it empty would too. What would NOT fail is the shape in
    between, so an empty block against a non-empty expectation is called out as a broken
    PARSER rather than as a stale client — the two have completely different fixes, and
    sending somebody to `pnpm gen:api` for a parser bug is how a guardrail gets deleted.
    """
    expected = _generated_names(spec)
    lines: list[str] = []
    for label, header, indent in _BLOCKS:
        found = _keys_at(generated, header, indent)
        want = expected[label]
        if want and not found:
            lines.append(
                f"  ! {label}: the snapshot declares {len(want)} but schema.d.ts appears to "
                f"declare none. That is this checker failing to read "
                f"`{header.strip()}`, not a stale client — openapi-typescript's output "
                f"format has probably moved. Fix _BLOCKS/_keys_at in this file."
            )
            continue
        lines += [
            f"  + {label} {name} (in openapi.json, not in schema.d.ts)"
            for name in sorted(want - found)
        ]
        lines += [
            f"  - {label} {name} (in schema.d.ts, not in openapi.json)"
            for name in sorted(found - want)
        ]
    return lines


def check_generated(spec: dict[str, Any]) -> int:
    if not GENERATED.exists():
        print(f"OPENAPI: FAIL — no generated client at {GENERATED}")
        print("Run: pnpm -C apps/web gen:api")
        return 1
    drift = generated_drift(spec, GENERATED.read_text(encoding="utf-8"))
    if drift:
        print("OPENAPI: FAIL — schema.d.ts was not regenerated from openapi.json")
        for line in drift:
            print(line)
        print("\nRegenerate: pnpm -C apps/web gen:api")
        return 1
    return 0


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

    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    committed = _shape(snapshot)
    current = _shape(live)
    if committed == current:
        # Only now: a stale snapshot makes a schema.d.ts diff a CONSEQUENCE rather than a
        # finding, and printing both would send the reader to the wrong `pnpm` command.
        if check_generated(snapshot) != 0:
            return 1
        print(
            f"OPENAPI: OK ({len(current['paths'])} paths, {len(current['schemas'])} schemas; "
            "permissions, parameters and property types compared, schema.d.ts regenerated)"
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
