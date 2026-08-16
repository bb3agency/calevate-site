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
   raw field one level down was invisible. Fields whose name matches a pattern but
   whose value is the redacted view are exempted ONE AT A TIME in `KNOWN_SAFE_FIELDS`
   (`Model.field`) — never by model, which would exempt the next field somebody adds
   to it as well.
2. **Free-form passthroughs** — a `dict[str, Any]` field is an undeclared response
   model; whatever the query put in it ships. Existing ones are acknowledged by name
   with a reason, so a NEW one is a deliberate, reviewable act.
3. **The allowlist's own promises** — a route is on ALLOWED_ROUTES because it is
   role-checked and audited. This check verifies that claim against the live app
   instead of trusting the comment: the permission must be declared AND enforced, and
   the handler must write audit_log. Otherwise removing the role check from the raw
   transcript endpoint would leave this guardrail green.

WHAT THIS CHECK CANNOT SEE, said plainly so nobody mistakes a green run for a whole
answer. It walks the OPENAPI SCHEMA, so it only ever judges values that leave through a
declared API response. Three egress paths carry the same data and are invisible to it:
the CSV export's BYTES (a `Response` with no model — which is exactly why its allowlist
entry is the widest form, a whole-path skip), the signed D-23 webhook body, and the
Google Sheets row. Nothing static can judge those, so they are covered at RUNTIME by
`tests/crm_egress_redaction_test.py`, which asserts a real-shaped number spoken inside a
call appears in none of the bytes that actually leave — the response, the file, the POST
body handed to the socket and the cells handed to the sheets transport. Treat the two as
one guardrail: this file proves the schema declares nothing raw, that file proves the
wire carries nothing raw.

An allowlist entry may also NAME the raw fields it is permitted to return instead of
switching the walk off for the whole path (`RawDisclosure.fields`) — so the DPDP subject
access document may echo the subject's own `phone_e164` back at them while every other
field in it stays under inspection. A whole-path skip is the widest form this registry
has, and it is the right shape only where there is no response model to judge.

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
        # DERIVED transcript text is still transcript text. `calls.summary` is stored
        # unredacted and is model-written prose about the conversation — the offline
        # extractor's is a transcript line copied VERBATIM — so a response model that
        # declares `summary` is declaring a field that can carry a caller's phone
        # number. This list not naming it is why the calls list shipped that column raw
        # to every `calls:read` holder while the check reported OK. `call_summary` is
        # the name the next panel is likely to reach for.
        #
        # NOT `notes`: an admin's note on a prompt version or a top-up is prose a
        # colleague typed about our own records, and a pattern that fires on it teaches
        # readers to add exemptions rather than to look. Every entry here has to mean
        # "a caller's own words could be in this".
        "summary",
        "call_summary",
        # The engine's own recording URL is vendor-scoped and long-lived; clients get a
        # short-lived presigned link to OUR copy instead.
        "recording_url",
    }
)


@dataclass(frozen=True)
class RawDisclosure:
    """A route permitted to return raw values, and HOW MUCH of it is permitted.

    `fields=None` means the whole response: the route returns a file, a byte-for-byte
    stored body or a shape with no model to inspect, so there is nothing for the field
    walk to judge. Naming a field set instead keeps the walk switched ON for that route
    and allows only those names — every OTHER raw field, including one added to the same
    model next year, is still reported.

    That distinction is the point. A blanket path skip was the only form this registry
    had, and it turns "this route may disclose the subject's own number" into "this route
    may disclose anything forever" — which is how a route earns an exemption for one field
    and keeps it for the next ten.
    """

    reason: str
    fields: frozenset[str] | None = None


# Routes permitted to return raw values, with the reason each is safe. Adding an entry
# is a deliberate act that shows up in review as a change to THIS file — and each entry
# is verified against the live app below, not taken on trust.
ALLOWED_ROUTES: dict[str, RawDisclosure] = {
    "/v1/calls/{call_id}/transcript/raw": RawDisclosure(
        "requires calls:read_raw AND writes audit_log in the same transaction"
    ),
    "/v1/integrations/deliveries/{delivery_id}/payload": RawDisclosure(
        "the delivered CRM body, byte for byte — a lead's name and number in whatever "
        "form the endpoint's own opt-in produced. Requires calls:read_raw AND writes "
        "audit_log in the same transaction; a redacted copy could not answer the "
        "question it exists for ('you sent us the wrong lead')"
    ),
    "/v1/leads/export.csv": RawDisclosure(
        "the client's own contact data, role-gated and audit-logged; a CSV of masked "
        "numbers cannot serve the follow-up call it exists for"
    ),
    "/v1/compliance/subject-export": RawDisclosure(
        "the DPDP subject access document: one person's own record, disclosed to that "
        "person. Requires calls:read_raw AND writes audit_log in the same transaction. "
        "Scoped to `phone_e164` — the subject's OWN number, echoed back so the recipient "
        "can check the document is about them (compliance/export.py decision 3). "
        "Everything else in the document is inspected normally: the transcript text is "
        "`text_redacted`, the call summary is masked, and a raw field added to any of "
        "these models tomorrow is reported like any other",
        fields=frozenset({"phone_e164"}),
    ),
}

# Fields whose NAME matches a pattern above but whose VALUE is the redacted view, each
# with the reason and — more usefully — the test that proves it.
#
# Keyed `Model.field`, never by model. A model-level exemption is a hole shaped like the
# next field somebody adds: exempting `CallSummaryOut` for the sake of `summary` would
# have blinded this check to a `from_e164` appearing beside it, which is precisely the
# regression `guardrail_audit_test` mutates the live schema to catch. This registry is a
# NAMING exemption only — a static schema walk cannot see whether a value was redacted,
# so each entry names the runtime test that can.
KNOWN_SAFE_FIELDS: dict[str, str] = {
    "TranscriptTurnOut.text": (
        "holds `text_redacted` by default and carries a `redacted` flag saying which it "
        "is; raw only from the allowlisted route (tests/api_security_test.py)"
    ),
    "CallSummaryOut.summary": (
        "transcript-derived prose put through the same `redact()` pass as "
        "`text_redacted` by `crm.service.redacted_summary`; the list has no raw variant "
        "at all (tests/call_summary_redaction_test.py)"
    ),
    "CallDetailOut.summary": (
        "same pass as its own transcript turns, and raw ONLY when the detail is served "
        "by the allowlisted raw-transcript route, which is role-checked and audited "
        "(tests/call_summary_redaction_test.py)"
    ),
    "CallAssistOut.summary": (
        "the assistant's re-summarise. Redacted TWICE and the first pass is the one that "
        "matters: the model is handed `transcript_turns.text_redacted` and `run_assist` "
        "refuses input that `redact()` still changes, so there is no unredacted digit "
        "for it to copy; the output then goes out through `crm.service.redacted_summary` "
        "like every other summary on this surface (tests/call_assist_test.py)"
    ),
    "SubjectExportTurnOut.text": (
        "holds `text_redacted` and never the raw column — the raw column is not even "
        "named in the query that builds it — and an unredacted turn ships as "
        "`export.REDACTION_PENDING` rather than falling back "
        "(tests/subject_export_test.py)"
    ),
    "SubjectExportCallOut.summary": (
        "model-written prose with every phone-shaped run that is NOT the subject's own "
        "replaced by `export.mask_foreign_numbers` before it ships; the subject's own "
        "number survives it by design, which is the allowance the route declares "
        "(tests/subject_export_test.py)"
    ),
}

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
    "SubjectExportLeadOut.data": (
        "the same schema-driven extraction payload as LeadOut.data, inside the DPDP "
        "subject access document. It is the subject's OWN data by construction — the "
        "client defined those fields to describe this caller — so masking it would "
        "corrupt the very answer the request asks for (compliance/export.py decision 3)."
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


def check(spec: dict[str, Any], safe_fields: dict[str, str] | None = None) -> list[str]:
    """Schema-level exposure: declared raw fields and undeclared passthroughs.

    `safe_fields` is injectable for the same reason `check_allowlist`'s allowlist is: a
    guardrail whose exemptions cannot be taken away in a test is a guardrail nobody can
    prove still sees anything.
    """
    known_safe = KNOWN_SAFE_FIELDS if safe_fields is None else safe_fields
    schemas = spec.get("components", {}).get("schemas", {})
    offenders: list[str] = []

    for path, operations in spec.get("paths", {}).items():
        # An allowlisted route is either skipped whole (`fields is None`) or kept under
        # inspection with a named set of raw fields permitted — see `RawDisclosure`.
        permitted: frozenset[str] = frozenset()
        allowance = ALLOWED_ROUTES.get(path)
        if allowance is not None:
            if allowance.fields is None:
                continue
            permitted = allowance.fields
        for method, operation in operations.items():
            if method not in _METHODS or not isinstance(operation, dict):
                continue
            for status, response in operation.get("responses", {}).items():
                if not str(status).startswith("2"):
                    continue
                for model_name in sorted(reachable_models(response, schemas)):
                    properties = schemas.get(model_name, {}).get("properties", {})
                    exposed = {
                        field
                        for field in (RAW_PII_FIELDS & set(properties)) - permitted
                        if f"{model_name}.{field}" not in known_safe
                    }
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
    for key in sorted(KNOWN_SAFE_FIELDS):
        model, _, field = key.partition(".")
        if field not in schemas.get(model, {}).get("properties", {}):
            failures.append(f"KNOWN_SAFE_FIELDS entry {key} no longer exists — remove it")
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
        f"transitively, {len(KNOWN_SAFE_FIELDS)} redacted-value fields, "
        f"{len(ACKNOWLEDGED_PASSTHROUGH)} acknowledged passthroughs)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
