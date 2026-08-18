"""Guardrail: no response grows with a caller's row count (D-302).

The rule: a route whose response can contain a LIST must either take a `limit` the
schema bounds, or be written down here with what bounds it instead.

WHY IT IS A GUARDRAIL AND NOT A REVIEW NOTE. Every unbounded list in this API was
written by somebody who knew the list was short — and every one of them was right on
the day they wrote it. `GET /v1/members` is a picker, `GET /v1/kb/sources` is "the
handful of documents this clinic uploaded", `GET /v1/agents` is two rows. The failure
is not that somebody was careless; it is that "short today" is a fact about the FIRST
tenant and the check for it happens exactly once, in a review, against an empty
database. The whole result is materialised in Python and serialised to JSON, so the
first client who succeeds at using the product is the one who finds out.

THE DISTINCTION THIS ENCODES, which is the part worth arguing. Not every list needs a
ceiling. What needs one is a list whose length is CALLER-CONTROLLED: rows a tenant can
mint (members, invitations, endpoints, knowledge sources, campaigns) or that accumulate
per tenant without anybody minting them (`prompt_versions` is append-only). What does
NOT need one is a list bounded by something we provision or declare — the voice
catalogue, the permission set of a role, the configuration registry, the seven days of a
week, the number of CLIENTS the platform has signed. The second kind is bounded by an
operational number that has an alarm on it (`client_health`'s walk budget), not by an
attacker's patience, and truncating it would silently drop an account from a triage
board — a worse failure than the one this check exists to prevent.

So the registry below is not an allowlist of things we got around to: each entry names
the OTHER bound, and the check verifies the entry still names a live route.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
* **It does not read SQL.** A `LIMIT` literal inside a service is invisible here, and
  that is the right answer rather than a limitation: a ceiling the schema does not state
  is indistinguishable, from outside, from a client who really does have that many rows.
  `GET /v1/campaigns` had exactly that — `LIMIT 100` buried in a service — and the fix
  was to make the number a parameter, not to teach this check to find it.
* **It does not judge the SIZE of the ceiling.** Whether 200 is right for a team picker
  is a product question. Whether there is one at all is not.
* **It does not look at `offset`.** Deep pagination is a performance question this repo
  answers per route (`crm.service.MAX_PAGE`); an unbounded page is a memory question,
  and only the second one can take a process down.

Run: `uv run python -m scripts.check_list_bounds`
"""

from __future__ import annotations

import sys
import typing
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import cost is paid only when the check runs
    from fastapi import FastAPI
    from fastapi.routing import APIRoute

_MIN_REASON = 40

#: How deep to walk a response model looking for a list. Three levels covers every shape
#: in this app (`Out.items[].sub[]`) and stops a recursive model from hanging the check.
_MAX_DEPTH = 3

#: Parameter names that mean "how many rows may come back". `days` is here because
#: `GET /v1/performance` bounds its response that way — the list is one entry per hour
#: of the window — and a rule that only knew the word `limit` would have demanded a
#: second, meaningless parameter beside it.
_BOUNDING_PARAMS = frozenset({"limit", "days"})


@dataclass(frozen=True, slots=True)
class BoundedByConstruction:
    """A list route with no `limit`, and the thing that bounds it instead.

    `by` must name the mechanism — a constant, a schema ceiling, a CHECK constraint, a
    registry — not merely assert that the list is short. "It is always small" is the
    belief this check exists to stop trusting.
    """

    by: str


#: Every list-shaped route that legitimately has no `limit`, keyed `"METHOD /path"`.
BOUNDED_LISTS: dict[str, BoundedByConstruction] = {
    # --- bounded by a constant or a registry in this repo ---------------------------
    "GET /v1/me": BoundedByConstruction(
        by="`permissions` is the role's permission set — at most `len(get_args(Permission))`."
    ),
    "GET /v1/admin/me": BoundedByConstruction(
        by="`permissions` is the role's permission set — at most `len(get_args(Permission))`."
    ),
    "GET /v1/agents/voices": BoundedByConstruction(
        by="the voice catalogue, a constant in `agents/voices.py` — not a table."
    ),
    "GET /v1/agents/lanes": BoundedByConstruction(
        by="the publishing lanes, a constant tuple in `agents/publishing.py`."
    ),
    "GET /v1/integrations/events": BoundedByConstruction(
        by="`integrations.service.EVENT_TYPES`, the four events an endpoint may subscribe to."
    ),
    "POST /v1/integrations/endpoints": BoundedByConstruction(
        by="`events` of the ONE endpoint just created, a subset of `EVENT_TYPES`."
    ),
    "POST /v1/integrations/endpoints/sheets": BoundedByConstruction(
        by="`events` of the ONE endpoint just created, a subset of `EVENT_TYPES`."
    ),
    "GET /v1/admin/tenants/{tenant_id}/feature-flags": BoundedByConstruction(
        by="the flag registry in `flags/service.py` — one row per DECLARED flag."
    ),
    "GET /v1/ops/config": BoundedByConstruction(
        by="the console-managed field registry in `core/platform_config.py`."
    ),
    "PUT /v1/ops/config/{key}": BoundedByConstruction(
        by="the ONE field written, and its `options` list from the same registry."
    ),
    "DELETE /v1/ops/config/{key}": BoundedByConstruction(
        by="the ONE field reset, and its `options` list from the same registry."
    ),
    "GET /v1/ops/secrets": BoundedByConstruction(
        by="the vendor-credential registry in `ops/secrets.py` — one row per known key."
    ),
    "POST /v1/ops/secrets/kek/rewrap": BoundedByConstruction(
        by="`unreadable` is at most one entry per registry key, same registry as above."
    ),
    "GET /v1/ops/platform": BoundedByConstruction(
        by="`by_job` is one entry per registered ARQ job (`workers/settings.FUNCTIONS`)."
    ),
    "POST /v1/ops/platform": BoundedByConstruction(
        by="`by_job` is one entry per registered ARQ job (`workers/settings.FUNCTIONS`)."
    ),
    "GET /v1/ops/audit/verify": BoundedByConstruction(
        by="`compliance.audit._MAX_REPORTED_BREAKS` caps the reported breaks at 20; the "
        "full count rides as `breaks_found`, an integer."
    ),
    "GET /v1/dashboard": BoundedByConstruction(
        by="`daily_7d` is seven days — the window is a constant in the query, not a "
        "parameter, so there is nothing a caller can widen."
    ),
    "POST /v1/auth/signup": BoundedByConstruction(
        by="`next_steps` is the fixed onboarding checklist in `tenancy/signup.py`."
    ),
    "GET /v1/compliance/caller-notice": BoundedByConstruction(
        by="one entry per declared collection purpose and retention class — both constants."
    ),
    "GET /v1/campaigns/{campaign_id}/launch-check": BoundedByConstruction(
        by="`blockers` is at most one per launch-gate RULE, a fixed set."
    ),
    "POST /v1/admin/tenants/{tenant_id}/agents/{agent_id}/intake/draft": BoundedByConstruction(
        by="`blockers` is at most one per intake completeness rule, a fixed set."
    ),
    "GET /v1/admin/tenants/{tenant_id}": BoundedByConstruction(
        by="`holds` is at most one per compliance hold rule (`admin/holds.py`), a fixed set."
    ),
    "GET /v1/agents/{agent_id}/experiment": BoundedByConstruction(
        by="two variants by construction, and `metrics` is the CONVERSION_METRICS constant."
    ),
    "POST /v1/admin/tenants/{tenant_id}/agents/{agent_id}/experiment": BoundedByConstruction(
        by="`variant_ids` is the two arms this call just created."
    ),
    "POST /v1/campaigns/{campaign_id}/recurrence": BoundedByConstruction(
        by="`days` is ISO weekdays — seven, enforced by the request model."
    ),
    "GET /v1/campaigns/{campaign_id}": BoundedByConstruction(
        by="`recurrence.days` is seven; `schedule_blocked_rules` is one per gate rule."
    ),
    "POST /v1/lead-sources/{webhook_id}/test": BoundedByConstruction(
        by="`steps` is the fixed dry-run ladder in `ingest/service.py`."
    ),
    "POST /v1/leads/views": BoundedByConstruction(
        by="`stale_*_keys` are bounded by `MAX_VIEW_FILTER_KEYS` (10) on the view itself."
    ),
    "PATCH /v1/leads/views/{view_id}": BoundedByConstruction(
        by="`stale_*_keys` are bounded by `MAX_VIEW_FILTER_KEYS` (10) on the view itself."
    ),
    "GET /v1/leads/views": BoundedByConstruction(
        by="`crm.schemas.MAX_SAVED_VIEWS_PER_USER` (50), enforced at create time, and the "
        "list is scoped to the caller's own views."
    ),
    "GET /v1/leads/facets": BoundedByConstruction(
        by="`crm.service.MAX_FACET_FIELDS` (8) x `MAX_FACET_VALUES` (50)."
    ),
    "POST /v1/leads/facets": BoundedByConstruction(
        by="`crm.service.MAX_FACET_FIELDS` (8) x `MAX_FACET_VALUES` (50)."
    ),
    "POST /v1/leads/bulk": BoundedByConstruction(
        by="`failures` is at most one per submitted id, and `MAX_BULK_LEADS` (500) bounds "
        "the request."
    ),
    "GET /v1/agents/{agent_id}": BoundedByConstruction(
        by="`extraction_fields` is one agent's extraction schema, bounded by the schema "
        "editor's own field ceiling."
    ),
    "GET /v1/agents/{agent_id}/pending": BoundedByConstruction(
        by="one entry per publishable ATTRIBUTE of one agent — a fixed list of fields."
    ),
    "GET /v1/kb/sources/{source_id}/preview": BoundedByConstruction(
        by="`SubmitIn.body` is capped at 200,000 characters and `kb.service.MAX_CHUNK_CHARS` "
        "is 700, so one source is at most ~286 chunks."
    ),
    "GET /v1/calls/{call_id}": BoundedByConstruction(
        by="the turns of ONE call, and `agents.models.CALL_CAP_MAX_S` (3600) bounds how "
        "long a call may be."
    ),
    "GET /v1/calls/{call_id}/transcript/raw": BoundedByConstruction(
        by="the turns of ONE call, bounded by `CALL_CAP_MAX_S` (3600) like the redacted twin."
    ),
    "GET /v1/admin/qa-samples/{sample_id}": BoundedByConstruction(
        by="the turns of ONE call, bounded by `CALL_CAP_MAX_S` (3600)."
    ),
    "GET /v1/admin/tenants/{tenant_id}/invoice": BoundedByConstruction(
        by="line items are one per metered UNIT KIND and taxes one per GST component — "
        "both fixed by the rate card, not by usage volume."
    ),
    "GET /v1/billing/invoice": BoundedByConstruction(
        by="line items are one per metered UNIT KIND and taxes one per GST component — "
        "both fixed by the rate card, not by usage volume."
    ),
    "GET /v1/admin/tenants/{tenant_id}/agents/{agent_id}/intake": BoundedByConstruction(
        by="one intake document, whose every list field is bounded by the request model "
        "that wrote it (`IntakeIn`)."
    ),
    "GET /v1/admin/tenants/{tenant_id}/commercial-terms": BoundedByConstruction(
        by="`history` is one row per re-pricing of one client, written by an operator "
        "through `POST` on the same path — a commercial event, not a data volume."
    ),
    "GET /v1/campaigns/numbers": BoundedByConstruction(
        by="the numbers WE provision for a tenant; a client cannot mint one "
        "(`POST /v1/numbers/purchase` is `org:manage` and provisions through the engine)."
    ),
    "GET /v1/campaigns/templates": BoundedByConstruction(
        by="DLT templates, which only an operator can file (`POST /v1/admin/tenants/"
        "{tenant_id}/dlt-templates`) and which the regulator's own registration bounds."
    ),
    # --- bounded by the number of CLIENTS, which we provision -----------------------
    "GET /v1/admin/tenants": BoundedByConstruction(
        by="one row per signed client. Truncating the operator's directory would hide an "
        "account from the only screen that lists them; the cost of the walk is watched "
        "instead — `admin/health.py` logs `client_health_walk_over_budget` and names the "
        "remedy (materialize `tenant_health`)."
    ),
    "GET /v1/admin/client-health": BoundedByConstruction(
        by="one row per signed client, ranked worst-first — a LIMIT would truncate BEFORE "
        "the triage sort and hide the account most in trouble. Watched by "
        "`WALK_BUDGET_S`, same as the directory above."
    ),
    "GET /v1/admin/compliance/holds": BoundedByConstruction(
        by="one row per signed client currently held by a human gate — a work queue that "
        "is empty in the steady state and is bounded by the client count in the worst."
    ),
    "GET /v1/admin/onboarding/unfinished": BoundedByConstruction(
        by="one row per signed client whose wizard is incomplete — bounded by the client "
        "count, and the whole point of the screen is that nothing is missed."
    ),
    # --- bounded by one data subject's own history ----------------------------------
    "POST /v1/compliance/subject-export": BoundedByConstruction(
        by="one PERSON's own record, keyed on their phone number. Completeness is the "
        "legal obligation (DPDP access request) — a truncated subject-access document "
        "is a non-compliant one, so the bound is the subject's own call history rather "
        "than a page size."
    ),
    "POST /v1/compliance/deletion-requests": BoundedByConstruction(
        by="the erasure proof for ONE subject: what was erased and what was not, bounded "
        "by that subject's own rows. The proof is evidence and must be whole."
    ),
    "GET /v1/compliance/deletion-requests/{request_id}": BoundedByConstruction(
        by="the erasure proof for ONE subject — see the POST above."
    ),
    "POST /v1/admin/tenants/{tenant_id}/erasure": BoundedByConstruction(
        by="the erasure proof for ONE tenant wind-down: limitations and unerased "
        "references, which are evidence and must be whole."
    ),
    "GET /v1/admin/tenants/{tenant_id}/erasure/{request_id}": BoundedByConstruction(
        by="the erasure proof for ONE tenant wind-down — see the POST above."
    ),
}


class ListBoundsError(RuntimeError):
    """The check could not be run — a broken premise, not a verdict."""


def build_app() -> FastAPI:
    from apps.api.main import app

    return app


def _returns_a_list(route: APIRoute) -> bool:
    """Can this route's declared response contain a list, at any depth?

    Reads the RESPONSE MODEL rather than the handler, because the model is the thing
    that is serialised — a route whose service returns a generator still materialises
    it here.
    """
    from pydantic import BaseModel

    model = route.response_model
    if model is None:
        return False
    if typing.get_origin(model) is list:
        return True

    seen: set[type] = set()

    def walk(candidate: object, depth: int) -> bool:
        if depth > _MAX_DEPTH:
            return False
        if not (isinstance(candidate, type) and issubclass(candidate, BaseModel)):
            return False
        if candidate in seen:
            return False
        seen.add(candidate)
        for field in candidate.model_fields.values():
            annotation = field.annotation
            args = typing.get_args(annotation)
            if typing.get_origin(annotation) is list:
                return True
            for arg in args:
                if typing.get_origin(arg) is list:
                    return True
                if walk(arg, depth + 1):
                    return True
            if walk(annotation, depth + 1):
                return True
        return False

    return walk(model, 0)


def _bounding_parameter(route: APIRoute) -> str | None:
    """The name of a bounded `limit`-like parameter, query or body, or None.

    BOUNDED, not merely present: `limit: int = Query(50)` with no `le` is a parameter a
    caller sets to a million. The upper bound may be written as `le=` on the `Query` or
    as an `annotated_types.Le` in the field's metadata, which is where Pydantic v2 puts
    it — both are read, because which one a route uses is a spelling choice.
    """
    from pydantic import BaseModel

    def upper_bound(field_info: object) -> bool:
        if getattr(field_info, "le", None) is not None:
            return True
        if getattr(field_info, "lt", None) is not None:
            return True
        return any(
            getattr(entry, "le", None) is not None or getattr(entry, "lt", None) is not None
            for entry in getattr(field_info, "metadata", ())
        )

    for param in route.dependant.query_params:
        if param.name in _BOUNDING_PARAMS and upper_bound(param.field_info):
            return param.name

    body = route.body_field
    if body is not None:
        annotation = body.field_info.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            for name, field in annotation.model_fields.items():
                if name in _BOUNDING_PARAMS and upper_bound(field):
                    return name
    return None


def list_routes(app: FastAPI) -> dict[str, APIRoute]:
    """`"METHOD /path"` -> route, for every route whose response can hold a list."""
    from apps.api.core.rbac import iter_api_routes

    found: dict[str, APIRoute] = {}
    for route in iter_api_routes(app):
        if not _returns_a_list(route):
            continue
        for method in sorted(route.methods or []):
            found[f"{method} {route.path}"] = route
    return found


def unbounded(routes: dict[str, APIRoute]) -> list[str]:
    """A list route with neither a bounded parameter nor a declaration."""
    problems: list[str] = []
    for key, route in sorted(routes.items()):
        if _bounding_parameter(route) is not None:
            continue
        if key in BOUNDED_LISTS:
            continue
        problems.append(
            f"{key} can return a list, takes no bounded `limit`, and is in no BOUNDED_LISTS entry"
        )
    return problems


def stale_declarations(routes: dict[str, APIRoute]) -> list[str]:
    """A declaration outliving its route, or one that stopped being needed.

    The second half matters as much as the first: a route that GAINED a `limit` keeps
    an entry here saying it does not need one, and the next reader believes the entry.
    """
    problems: list[str] = []
    for key in sorted(BOUNDED_LISTS):
        route = routes.get(key)
        if route is None:
            problems.append(
                f"{key} is declared bounded-by-construction but is not a live list route "
                "— delete the entry"
            )
            continue
        parameter = _bounding_parameter(route)
        if parameter is not None:
            problems.append(
                f"{key} now takes a bounded `{parameter}`, so its BOUNDED_LISTS entry is "
                "a false statement about the route — delete it"
            )
    return problems


def thin_reasons() -> list[str]:
    return sorted(
        f"{key}: reason is {len(entry.by.strip())} characters; {_MIN_REASON} is the floor"
        for key, entry in BOUNDED_LISTS.items()
        if len(entry.by.strip()) < _MIN_REASON
    )


def audit(app: FastAPI) -> list[str]:
    routes = list_routes(app)
    if not routes:
        raise ListBoundsError(
            "no list-returning routes found. Either route discovery is broken or the "
            "response-model walk is — a clean report from a check that found nothing to "
            "check is not a clean report."
        )
    return [*unbounded(routes), *stale_declarations(routes), *thin_reasons()]


def main() -> int:
    try:
        problems = audit(build_app())
    except ListBoundsError as exc:
        print(f"FAIL check_list_bounds: {exc}", file=sys.stderr)
        return 2

    if problems:
        print("FAIL check_list_bounds — a response can grow with somebody's data:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\n  Either take a bounded page (`limit: int = Query(50, ge=1, le=200)`, and "
            "put the LIMIT in the query) or add a BOUNDED_LISTS entry naming what bounds "
            "the list instead.",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK check_list_bounds: {len(BOUNDED_LISTS)} lists bounded by construction, "
        "every other list route takes a bounded page"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
