"""Guardrail: raw transcript text and raw PII never appear in a default response
(hard rule 5; ENGINEERING-PRACTICES §2 "critical four").

The rule it enforces: `text_redacted` is what every API response returns; raw `text`
requires a role check AND an audit_log write. Review catches that on the day it is
written and misses it six months later, which is exactly when the codebase is growing
fastest.

Mechanism (raghava's `serializer:exposure-check` pattern, adapted). Three parts, because
there are three ways raw text reaches a browser:

1. **Declared fields** — walk every response model reachable from the live OpenAPI
   schema, TRANSITIVELY: a model is not safe because the model that nests it is. The
   previous version only inspected the models `$ref`-ed directly by the response, so a
   raw field one level down was invisible.
2. **Free-form passthroughs** — a `dict[str, Any]` field is an undeclared response
   model; whatever the query put in it ships. Existing ones are acknowledged by name
   with a reason, so a NEW one is a deliberate, reviewable act.
3. **The allowlist's own promises** — a route is on ALLOWED_ROUTES because it is
   role-checked and audited. This check verifies that claim against the live app
   instead of trusting the comment: the permission must be declared AND enforced, and
   the handler must write audit_log. Otherwise removing the role check from the raw
   transcript endpoint would leave this guardrail green.

Run: `uv run python -m scripts.check_redaction_exposure`
"""

from __future__ import annotations

import inspect
import sys
from dataclasses import dataclass
from typing import Any, get_args

# Field names that carry raw personal data or raw transcript text. A response model may
# only expose these from a route on ALLOWED_ROUTES, each role-checked and audited.
RAW_PII_FIELDS: frozenset[str] = frozenset(
    {
        "phone_e164",
        "from_e164",
        "to_e164",
        "caller_e164",
        "phone",
        "phone_number",
        "email",
        # Hard rule 5 names transcript text specifically: `text` vs `text_redacted`.
        "text",
        "raw_text",
        "text_raw",
        "transcript_text",
        # The engine's own recording URL is vendor-scoped and long-lived; clients get a
        # short-lived presigned link to OUR copy instead.
        "recording_url",
    }
)

# Routes permitted to return raw values, with the reason each is safe. Adding an entry
# is a deliberate act that shows up in review as a change to THIS file — and each entry
# is verified against the live app below, not taken on trust.
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

# `dict[str, Any]` response fields: the serializer cannot vouch for their contents, so
# each one is acknowledged here with the reason it is not a redaction bypass.
ACKNOWLEDGED_PASSTHROUGH: dict[str, str] = {
    "LeadOut.data": (
        "the tenant's OWN extraction payload — the schema-driven CRM columns ARE the "
        "product (TRD §7). Tenant-scoped by RLS; the phone column beside it is masked."
    ),
    "CallDetailOut.extraction": (
        "the tenant's own extracted fields for this call, same schema-driven surface as "
        "LeadOut.data; never the raw vendor payload, which lives in object storage."
    ),
}

_METHODS = ("get", "post", "patch", "put", "delete")


# --- 1 + 2: what the schema declares ------------------------------------------


def _refs_in(node: Any) -> set[str]:
    """Every `$ref`-ed component name inside a schema fragment."""
    names: set[str] = set()

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            ref = item.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                names.add(ref.rsplit("/", 1)[1])
            for value in item.values():
                walk(value)
        elif isinstance(item, list):
            for entry in item:
                walk(entry)

    walk(node)
    return names


def reachable_models(node: Any, schemas: dict[str, Any]) -> set[str]:
    """Transitive closure of `$ref`s. Nesting is not a hiding place."""
    seen: set[str] = set()
    pending = list(_refs_in(node))
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        pending += [n for n in _refs_in(schemas.get(name, {})) if n not in seen]
    return seen


def _is_freeform_object(schema: Any) -> bool:
    """`dict[str, Any]` — an object with no declared properties that accepts anything."""
    if not isinstance(schema, dict):
        return False
    variants = [schema]
    for key in ("anyOf", "oneOf", "allOf"):
        variants += [v for v in schema.get(key, []) if isinstance(v, dict)]
    return any(
        variant.get("type") == "object"
        and "properties" not in variant
        and variant.get("additionalProperties", True) is True
        for variant in variants
    )


def check(spec: dict[str, Any]) -> list[str]:
    """Schema-level exposure: declared raw fields and undeclared passthroughs."""
    schemas = spec.get("components", {}).get("schemas", {})
    offenders: list[str] = []

    for path, operations in spec.get("paths", {}).items():
        if path in ALLOWED_ROUTES:
            continue
        for method, operation in operations.items():
            if method not in _METHODS or not isinstance(operation, dict):
                continue
            for status, response in operation.get("responses", {}).items():
                if not str(status).startswith("2"):
                    continue
                for model_name in sorted(reachable_models(response, schemas)):
                    if model_name in KNOWN_SAFE_MODELS:
                        continue
                    properties = schemas.get(model_name, {}).get("properties", {})
                    exposed = RAW_PII_FIELDS & set(properties)
                    if exposed:
                        offenders.append(
                            f"{method.upper()} {path} → {model_name} exposes {sorted(exposed)}"
                        )
                    for field, field_schema in sorted(properties.items()):
                        key = f"{model_name}.{field}"
                        if key in ACKNOWLEDGED_PASSTHROUGH:
                            continue
                        if _is_freeform_object(field_schema):
                            offenders.append(
                                f"{method.upper()} {path} → {key} is a free-form dict: "
                                "whatever the query selected is serialized verbatim"
                            )
    return sorted(set(offenders))


def check_registry_freshness(spec: dict[str, Any]) -> list[str]:
    """A stale exemption is a hole with a comment on it."""
    schemas = spec.get("components", {}).get("schemas", {})
    failures: list[str] = []
    for path in sorted(ALLOWED_ROUTES):
        if path not in spec.get("paths", {}):
            failures.append(f"ALLOWED_ROUTES entry {path} matches no route — remove it")
    for model in sorted(KNOWN_SAFE_MODELS):
        if model not in schemas:
            failures.append(f"KNOWN_SAFE_MODELS entry {model} no longer exists — remove it")
    for key in sorted(ACKNOWLEDGED_PASSTHROUGH):
        model, _, field = key.partition(".")
        if field not in schemas.get(model, {}).get("properties", {}):
            failures.append(f"ACKNOWLEDGED_PASSTHROUGH entry {key} no longer exists — remove it")
    return failures


# --- 3: the allowlist keeps its promises --------------------------------------


@dataclass(frozen=True)
class RouteFacts:
    path: str
    methods: frozenset[str]
    declared: str | None
    enforced: frozenset[str]
    source: str


def route_facts() -> list[RouteFacts]:
    """What the running app actually enforces, read off the mounted routes."""
    from apps.api.core.rbac import Permission, iter_api_routes
    from apps.api.main import app

    permissions = set(get_args(Permission))
    facts: list[RouteFacts] = []
    for route in iter_api_routes(app):
        enforced: set[str] = set()
        for dependency in route.dependant.dependencies:
            call = getattr(dependency, "call", None)
            for cell in getattr(call, "__closure__", None) or ():
                try:
                    value = cell.cell_contents
                except ValueError:  # pragma: no cover - empty cell
                    continue
                if isinstance(value, str) and value in permissions:
                    enforced.add(value)
        try:
            source = inspect.getsource(route.endpoint)
        except OSError:  # pragma: no cover - dynamically built endpoint
            source = ""
        facts.append(
            RouteFacts(
                path=route.path,
                methods=frozenset(route.methods or ()),
                declared=(route.openapi_extra or {}).get("x-calevate-permission"),
                enforced=frozenset(enforced),
                source=source,
            )
        )
    return facts


def check_allowlist(routes: list[RouteFacts], allowed: dict[str, str] | None = None) -> list[str]:
    """Every allowlisted route must actually be role-checked and audited."""
    allowlist = ALLOWED_ROUTES if allowed is None else allowed
    failures: list[str] = []

    if routes and not any(route.enforced for route in routes):
        # Same doctrine as the RBAC boot assertion: a check that finds nothing to check
        # reads as a pass. If permission extraction ever breaks, say so loudly.
        return [
            "permission extraction found no enforced permission on ANY route — this "
            "check is blind. Fix route_facts() rather than deleting the check."
        ]

    for path in sorted(allowlist):
        matches = [route for route in routes if route.path == path]
        if not matches:
            failures.append(f"{path}: on the raw-PII allowlist but not mounted by the app")
            continue
        for route in matches:
            if not route.declared:
                failures.append(f"{path}: returns raw PII with NO declared permission")
                continue
            if route.declared not in route.enforced:
                failures.append(
                    f"{path}: declares {route.declared} but the route enforces "
                    f"{sorted(route.enforced) or 'nothing'} — the metadata is decoration"
                )
            if "write_audit" not in route.source:
                failures.append(
                    f"{path}: returns raw PII without writing audit_log in the handler "
                    "(hard rule 5: role check AND audit, in the same transaction)"
                )
    return failures


def main() -> int:
    from apps.api.main import app

    spec = app.openapi()
    offenders = check(spec)
    if offenders:
        print("REDACTION EXPOSURE: FAIL — raw PII reachable from a default response")
        for offender in offenders:
            print(f"  - {offender}")
        print(
            "\nHard rule 5: responses return masked/redacted values by default. Either mask "
            "the field in the response model, or add the route to ALLOWED_ROUTES in this "
            "script WITH its role check and audit_log write (a free-form dict field is "
            "acknowledged in ACKNOWLEDGED_PASSTHROUGH with the reason it is safe)."
        )
        return 1

    failures = check_registry_freshness(spec) + check_allowlist(route_facts())
    if failures:
        print("REDACTION EXPOSURE: FAIL — an exemption does not hold up")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print(
        f"REDACTION EXPOSURE: OK ({len(ALLOWED_ROUTES)} role-gated exceptions verified "
        f"role-checked + audited, {len(RAW_PII_FIELDS)} field patterns checked "
        f"transitively, {len(ACKNOWLEDGED_PASSTHROUGH)} acknowledged passthroughs)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
