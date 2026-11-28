"""Guardrail: the public API changes only by addition within a version (D-1047, W2.2/W2.13).

`docs/api/public-openapi.json` is the committed contract of `/api/v1/**`: every operation
and every schema reachable from one. This check builds the same document from the live app
and compares, and the comparison is ASYMMETRIC, because the promise in `docs/WEBHOOKS.md`
§0 is: within a `Calevate-Version`, nothing an integration relies on goes away or changes.

Breaking, and refused:
- an operation removed, or its permission changed;
- a parameter removed, retyped, or a new REQUIRED one;
- a schema removed; a property removed or retyped; an enum narrowed;
- a request body gaining a required field (a client that sent yesterday's body is refused).

Additive, and accepted once written: a new operation, parameter, schema, property or enum
value, and a response field becoming required (more is promised, nothing is withdrawn).

A breaking change is not fixed by `--write`: it is refused there too, because it needs a new
dated version (`public_api/version.py`) and a transform for the old one. An addition that is
not yet in the snapshot fails the check until `--write` records it, so the published
document never lags the code.

Run: `uv run python -m scripts.check_public_api_snapshot`  (`--write` to record additions)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SNAPSHOT = Path(__file__).resolve().parent.parent / "docs" / "api" / "public-openapi.json"
PREFIX = "/api/v1/"
METHODS = ("get", "post", "put", "patch", "delete")
_PROSE = frozenset({"title", "description", "summary", "example", "examples", "tags"})


def _refs(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.add(ref.rsplit("/", 1)[-1])
        for value in node.values():
            found |= _refs(value)
    elif isinstance(node, list):
        for item in node:
            found |= _refs(item)
    return found


def _closure(names: set[str], schemas: dict[str, Any]) -> set[str]:
    seen: set[str] = set()
    todo = list(names)
    while todo:
        name = todo.pop()
        if name in seen or name not in schemas:
            continue
        seen.add(name)
        todo.extend(_refs(schemas[name]) - seen)
    return seen


def public_document(spec: dict[str, Any]) -> dict[str, Any]:
    """The `/api/v1/` part of `spec`, with prose removed and nothing else."""
    paths = {p: ops for p, ops in sorted(spec.get("paths", {}).items()) if p.startswith(PREFIX)}
    schemas = spec.get("components", {}).get("schemas", {})
    reachable = _closure(_refs(paths), schemas)
    request_roots = set()
    for ops in paths.values():
        for method, op in ops.items():
            if method in METHODS:
                request_roots |= _refs(op.get("requestBody", {}))
    return _strip(
        {
            "openapi": spec.get("openapi"),
            "paths": paths,
            "components": {"schemas": {n: schemas[n] for n in sorted(reachable)}},
            "x-request-schemas": sorted(_closure(request_roots, schemas)),
        }
    )


def _strip(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip(v) for k, v in sorted(node.items()) if k not in _PROSE}
    if isinstance(node, list):
        return [_strip(v) for v in node]
    return node


def _without_enum(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _without_enum(v) for k, v in node.items() if k != "enum"}
    if isinstance(node, list):
        return [_without_enum(v) for v in node]
    return node


def _enum_narrowed(old: Any, new: Any) -> bool:
    if isinstance(old, dict) and isinstance(new, dict):
        if isinstance(old.get("enum"), list):
            if not isinstance(new.get("enum"), list) and "enum" in new:
                return True
            if isinstance(new.get("enum"), list) and not set(old["enum"]) <= set(new["enum"]):
                return True
        return any(_enum_narrowed(old[k], new[k]) for k in old.keys() & new.keys())
    if isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        return any(_enum_narrowed(a, b) for a, b in zip(old, new, strict=True))
    return False


def _same_type(old: Any, new: Any) -> bool:
    return bool(_without_enum(old) == _without_enum(new)) and not _enum_narrowed(old, new)


def breaking_changes(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for path, ops in old.get("paths", {}).items():
        for method, op in ops.items():
            if method not in METHODS:
                continue
            now = new.get("paths", {}).get(path, {}).get(method)
            where = f"{method.upper()} {path}"
            if now is None:
                problems.append(f"{where}: removed")
                continue
            if op.get("x-calevate-permission") != now.get("x-calevate-permission"):
                problems.append(f"{where}: permission changed")
            before = {(p["name"], p["in"]): p for p in op.get("parameters", [])}
            after = {(p["name"], p["in"]): p for p in now.get("parameters", [])}
            for key, param in before.items():
                if key not in after:
                    problems.append(f"{where}: parameter {key[0]} removed")
                elif not _same_type(param.get("schema"), after[key].get("schema")):
                    problems.append(f"{where}: parameter {key[0]} changed type")
            for key, param in after.items():
                if key not in before and param.get("required"):
                    problems.append(f"{where}: new required parameter {key[0]}")
            for status in op.get("responses", {}):
                if status not in now.get("responses", {}):
                    problems.append(f"{where}: response {status} removed")
    requests = set(new.get("x-request-schemas", []))
    old_schemas = old.get("components", {}).get("schemas", {})
    new_schemas = new.get("components", {}).get("schemas", {})
    for name, schema in old_schemas.items():
        current = new_schemas.get(name)
        if current is None:
            problems.append(f"schema {name}: removed")
            continue
        props = schema.get("properties", {})
        now_props = current.get("properties", {})
        for prop, sig in props.items():
            if prop not in now_props:
                problems.append(f"schema {name}.{prop}: removed")
            elif not _same_type(sig, now_props[prop]):
                problems.append(f"schema {name}.{prop}: changed type")
        if name in requests:
            added = set(current.get("required", [])) - set(schema.get("required", []))
            for prop in sorted(added):
                problems.append(f"schema {name}.{prop}: request field became required")
        elif not set(schema.get("required", [])) <= set(current.get("required", [])):
            problems.append(f"schema {name}: a response field stopped being required")
    return problems


def _live() -> dict[str, Any]:
    from apps.api.main import app

    return public_document(app.openapi())


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    live = _live()
    old = json.loads(SNAPSHOT.read_text(encoding="utf-8")) if SNAPSHOT.exists() else {}
    problems = breaking_changes(old, live) if old else []
    if problems:
        print("PUBLIC API SNAPSHOT: BREAKING — " + "; ".join(problems))
        print(
            "Within a version the public API changes only by addition (docs/WEBHOOKS.md §0). "
            "Restore the field, or ship a new dated version with a transform."
        )
        return 1
    if "--write" in args:
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(live, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"PUBLIC API SNAPSHOT: written to {SNAPSHOT.name}")
        return 0
    if live != old:
        print(
            "PUBLIC API SNAPSHOT: STALE — additions are not recorded. Run "
            "`uv run python -m scripts.check_public_api_snapshot --write` and commit it."
        )
        return 1
    print(f"PUBLIC API SNAPSHOT: OK ({len(live.get('paths', {}))} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
