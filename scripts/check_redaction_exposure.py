"""Guardrail: raw transcript text never appears in a default response (hard rule 5).

D-29's critical four, third check. The rule it enforces: `text_redacted` is what every
API response returns; raw `text` requires a role check AND an audit_log write. Review
catches that on the day it is written and misses it six months later, which is exactly
when the codebase is growing fastest.

Mechanism (raghava's `serializer:exposure-check` pattern, adapted): walk every response
model reachable from the live OpenAPI schema and fail if a model exposes a raw-PII
field, unless the route carrying it is on the explicitly-listed role-gated allowlist.

Run: `uv run python -m scripts.check_redaction_exposure`
"""

from __future__ import annotations

import sys
from typing import Any

# Field names that carry raw personal data. A response model may only expose these
# from a route on ALLOWED_ROUTES, each of which must be role-checked and audited.
RAW_PII_FIELDS: frozenset[str] = frozenset({"phone_e164", "from_e164", "to_e164", "email"})

# Routes permitted to return raw values, with the reason each is safe. Adding an entry
# is a deliberate act that shows up in review as a change to THIS file.
ALLOWED_ROUTES: dict[str, str] = {
    "/v1/calls/{call_id}/transcript/raw": (
        "requires calls:read_raw AND writes audit_log in the same transaction"
    ),
    "/v1/leads/export.csv": (
        "the client's own contact data, role-gated and audit-logged; a CSV of masked "
        "numbers cannot serve the follow-up call it exists for"
    ),
}

# Response models whose raw-looking field is not raw. `TranscriptTurnOut.text` holds
# `text_redacted` by default and carries a `redacted` flag saying which it is.
KNOWN_SAFE_MODELS: frozenset[str] = frozenset({"TranscriptTurnOut"})


def _model_names_in(schema: dict[str, Any]) -> set[str]:
    """Collect every `$ref`-ed component name inside a response schema."""
    names: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                names.add(ref.rsplit("/", 1)[1])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    return names


def check(spec: dict[str, Any]) -> list[str]:
    schemas = spec.get("components", {}).get("schemas", {})
    offenders: list[str] = []

    for path, operations in spec.get("paths", {}).items():
        if path in ALLOWED_ROUTES:
            continue
        for method, operation in operations.items():
            if method not in ("get", "post", "patch", "put", "delete"):
                continue
            responses = operation.get("responses", {})
            for status, response in responses.items():
                if not str(status).startswith("2"):
                    continue
                for model_name in _model_names_in(response):
                    if model_name in KNOWN_SAFE_MODELS:
                        continue
                    properties = schemas.get(model_name, {}).get("properties", {})
                    exposed = RAW_PII_FIELDS & set(properties)
                    if exposed:
                        offenders.append(
                            f"{method.upper()} {path} → {model_name} exposes {sorted(exposed)}"
                        )
    return sorted(set(offenders))


def main() -> int:
    from apps.api.main import app

    offenders = check(app.openapi())
    if offenders:
        print("REDACTION EXPOSURE: FAIL — raw PII reachable from a default response")
        for offender in offenders:
            print(f"  - {offender}")
        print(
            "\nHard rule 5: responses return masked/redacted values by default. Either mask "
            "the field in the response model, or add the route to ALLOWED_ROUTES in this "
            "script WITH its role check and audit_log write."
        )
        return 1

    print(
        f"REDACTION EXPOSURE: OK ({len(ALLOWED_ROUTES)} role-gated exceptions, "
        f"{len(RAW_PII_FIELDS)} field patterns checked)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
