"""What every `/v1/admin/tenants/{tenant_id}/…` route answers for a tenant that is not there.

D-133 found four routes of one shape — a missing existence check, so a mistyped tenant
uuid produced a 500 (`dlt-templates`, `kyc`), a misleading 409 (`numbers`, "It may belong
to another account") or a refusal about the wrong object (`add_contacts`, "Contacts can
only be added before a campaign is launched"). It fixed the four it drove. **The class
was not exhausted**, and it could not have been: the fix was made per route, so the next
route to name a tenant in its path started from nothing again.

This file is the census instead of the fifth one-off. Every route the app serves whose
path begins `/v1/admin/tenants/{tenant_id}` (plus the one `/v1/ops/tenants/{tenant_id}`
route) is driven with an id no organization holds, and must answer **404 `not_found`**.
A route with no entry in the table below fails the completeness assertion, so the rule
arrives with the next route rather than after it.

WHY 404 AND NOT SOMETHING GENTLER. `admin.service.tenant_exists` — the one definition —
already says it: callers turn a False into a 404 "rather than an FK violation rendered as
a 500, or worse a cheerful 200 describing a tenant that is not there". The tenant id in
these paths is a uuid an operator COPIES off a console URL; it is the one parameter on
these routes that is neither typed nor chosen from a list.

WHAT THIS RUN FOUND, over and above D-133's four (each fixed in the same change):

* `POST …/dlt-registration` → **500 `internal_error`**, from
  `fk_dlt_registrations_tenant_id_organizations`. The third member of the family whose
  other two (`dlt-templates`, `kyc`) D-133 fixed — missed because it is an `ON CONFLICT`
  upsert and so reads like a write that cannot fail on a key.
* `POST …/first-campaign-review` → **500 `internal_error`**, from
  `fk_first_campaign_reviews_tenant_id_organizations`. Its own docstring claims the shape
  of `record_kyc_verification`, which had the guard.
* `GET`/`POST …/whatsapp-alerts` → **422 `alert_optin_no_owner_with_a_number`**: "This
  account has no active owner with a mobile number. Add a mobile number to the owner's
  profile, then record the opt-in." A real refusal, correct for the state it was written
  for, sending an operator to edit a profile in an account that does not exist. This is
  D-133's `number_taken` defect in another module.
* `GET …/margin` → **200** with a ₹0 margin card computed from an empty aggregate. A
  tenant with no usage and a tenant that never existed both sum to nothing.
* `GET …/commercial-terms` → **200 `state: none`** — "no terms have ever been set, the
  state every new tenant is in" — next to its own POST, which answers 404 for the same
  id. One screen, two verdicts on whether the client exists.
* `GET …/invitations` → **200 `[]`**, i.e. "no key to this account is outstanding", which
  is the exact claim the endpoint exists to make actionable.
* `GET …/agents/{agent_id}/prompt` → **200 `[]`**, indistinguishable from a real agent
  whose first script has not been written (the state `publish` refuses as
  `agent_has_no_script`). Fixed in `prompts.list_prompt_versions`, so the read now goes
  through the same `_agent_state` predicate as the two writes beside it.

CONCURRENCY: every case uses a fresh random uuid and asserts on no shared row.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.agents.voices import DEFAULT_VOICE_ID
from apps.api.core.rbac import iter_api_routes
from apps.api.db.session import untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import accept_agreements

#: The path prefixes this census owns. `/v1/ops/tenants/…` is included because it is the
#: same act — an operator naming one client in a URL — under the platform router.
TENANT_PATH_PREFIXES = ("/v1/admin/tenants/{tenant_id}", "/v1/ops/tenants/{tenant_id}")

#: A flag the registry actually declares. A name it does not declare is refused 422
#: BEFORE the tenant is looked at, which would make this route's entry vacuous.
REAL_FLAG = "call_timing_breakdown"

TEMPLATE_BODY = "Namaste, calling from {#var#} about your appointment on {#var#}."
PROMPT_BODY = "[IDENTITY]\nYou are the receptionist for the clinic.\n"


#: A body each route ACCEPTS, so the 404 comes from the tenant and not from Pydantic.
#:
#: `None` means the route takes no body at all. The distinction is kept — rather than
#: sending `{}` everywhere — because the completeness assertion reads MEMBERSHIP of this
#: table, and a route silently defaulting to "no body" is how a new route with a required
#: payload would join the census answering 422 forever.
#:
#: Every value here is valid: a 422 anywhere in this suite means the fixture is stale,
#: not that the route is safe, and the assertion below says so in those words.
BODIES: dict[str, dict[str, Any] | None] = {
    "POST /v1/admin/tenants/{tenant_id}/agents/{agent_id}/experiment": {
        "name": "greeting tweak",
        "control_version": 1,
        "challenger_version": 2,
    },
    "POST /v1/admin/tenants/{tenant_id}/agents/{agent_id}/experiment/conclude": {
        "experiment_id": str(uuid.uuid4())
    },
    "PATCH /v1/admin/tenants/{tenant_id}/agents/{agent_id}/call-cap": {"max_call_duration_s": 300},
    "POST /v1/admin/tenants/{tenant_id}/agents/{agent_id}/prompt": {"body": PROMPT_BODY},
    "POST /v1/admin/tenants/{tenant_id}/agents/{agent_id}/prompt/rollback": {"version": 1},
    # THE CATALOGUE'S OWN DEFAULT, not a literal. A voice id is `<tts_model>:<speaker>`
    # since D-358, and this route validates membership before it looks the tenant up — so a
    # stale literal here would 422 and this census would stop measuring the 404 it is about.
    "PATCH /v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice": {"voice_id": DEFAULT_VOICE_ID},
    # An EMPTY variable list is a valid body (a schema may capture nothing extra), so the
    # route validates and reaches the tenant lookup — which 404s for a tenant that names
    # nothing. A non-empty body would work too; empty is the minimal one that gets past
    # `_validate_fields` to the 404 this census is about.
    "PUT /v1/admin/tenants/{tenant_id}/agents/{agent_id}/extraction-schema": {"fields": []},
    "POST /v1/admin/tenants/{tenant_id}/agents/{agent_id}/intake": {},
    # D-538. The close demands a reason, so an empty body would 422 and this census would
    # stop measuring the 404 it is about. The undo and the read take no body at all.
    "POST /v1/admin/tenants/{tenant_id}/closure": {"reason": "Census"},
    "DELETE /v1/admin/tenants/{tenant_id}/closure": None,
    "GET /v1/admin/tenants/{tenant_id}/closure": None,
    # An EMPTY body is the ordinary resend — "send it again to the address it has" — and
    # it is the one that reaches the tenant lookup rather than the address validator.
    "POST /v1/admin/tenants/{tenant_id}/invitations/{invitation_id}/resend": {},
    "POST /v1/admin/tenants/{tenant_id}/agents/{agent_id}/intake/draft": {},
    "POST /v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/preference-scrub": {
        "provider": "airtel",
        "scrub_ref": "REF-12345",
        "scrubbed_at": "2026-08-16T05:00:00+05:30",
        "blocked_numbers": [],
    },
    "POST /v1/admin/tenants/{tenant_id}/commercial-terms": {"monthly_fee_inr": "10000"},
    "POST /v1/admin/tenants/{tenant_id}/credits": {
        "amount_inr": "1000",
        "payment_ref": "UTR-CENSUS-1",
    },
    # POSITIVE: `record_adjustment` refuses a non-positive amount with a business rule
    # BEFORE it looks at the tenant, so a negative here would make the entry vacuous.
    "POST /v1/admin/tenants/{tenant_id}/credits/adjustments": {
        "amount_inr": "100",
        "corrects_entry_id": str(uuid.uuid4()),
        "reason": "census",
    },
    "POST /v1/admin/tenants/{tenant_id}/credits/restatements": {
        "payment_ref": "UTR-CENSUS-1",
        "corrected_amount_inr": "900",
        "reason": "census",
    },
    "POST /v1/admin/tenants/{tenant_id}/dlt-registration": {
        "pe_id": "PE1234567890",
        "entity_name": "Census Clinic",
        "status": "active",
        "tm_link_status": "active",
    },
    "POST /v1/admin/tenants/{tenant_id}/dlt-templates": {
        "classification": "service",
        "body": TEMPLATE_BODY,
    },
    "POST /v1/admin/tenants/{tenant_id}/dlt-templates/{template_id}/status": {"status": "approved"},
    "POST /v1/admin/tenants/{tenant_id}/erasure": {"reason": "offboarding, census"},
    "PUT /v1/admin/tenants/{tenant_id}/feature-flags/{flag}": {
        "enabled": True,
        "reason": "census",
    },
    "POST /v1/admin/tenants/{tenant_id}/first-campaign-review": {
        "decision": "approved",
        "note": "list, script and disclosure line checked",
    },
    "POST /v1/admin/tenants/{tenant_id}/invitations": {
        "email": "census@example.com",
        "role": "owner",
    },
    "POST /v1/admin/tenants/{tenant_id}/kb/{source_id}/reject": {"reason": "out of scope"},
    "POST /v1/admin/tenants/{tenant_id}/kyc": {"status": "in_review"},
    "POST /v1/admin/tenants/{tenant_id}/refunds": {
        "payment_id": "pay_CENSUS0000001",
        "reason": "census — duplicate top-up",
    },
    "POST /v1/admin/tenants/{tenant_id}/numbers": {
        "e164": f"+9198{uuid.uuid4().int % 100000000:08d}",
        "series": "160",
    },
    "POST /v1/admin/tenants/{tenant_id}/numbers/{number_id}/dlt-status": {
        "dlt_status": "registered"
    },
    "POST /v1/admin/tenants/{tenant_id}/plan-tier": {
        "plan_tier": "managed",
        "reason": "census",
    },
    "POST /v1/admin/tenants/{tenant_id}/status": {
        "status": "suspended",
        "reason": "census",
    },
    "POST /v1/admin/tenants/{tenant_id}/whatsapp-alerts": {
        "status": "granted",
        "evidence": {"ref": "onboarding form"},
    },
    # All optional fields, but the payload model itself is REQUIRED — an absent body is a
    # 422 before the agent is looked at.
    "POST /v1/admin/tenants/{tenant_id}/agents/{agent_id}/apply": {},
    # No request body at all.
    "GET /v1/admin/tenants/{tenant_id}": None,
    "GET /v1/admin/tenants/{tenant_id}/agents/{agent_id}/intake": None,
    "GET /v1/admin/tenants/{tenant_id}/agents/{agent_id}/prompt": None,
    "GET /v1/admin/tenants/{tenant_id}/commercial-terms": None,
    "GET /v1/admin/tenants/{tenant_id}/credits": None,
    "GET /v1/admin/tenants/{tenant_id}/erasure/{request_id}": None,
    "GET /v1/admin/tenants/{tenant_id}/feature-flags": None,
    "GET /v1/admin/tenants/{tenant_id}/invitations": None,
    "GET /v1/admin/tenants/{tenant_id}/invoice": None,
    "GET /v1/admin/tenants/{tenant_id}/margin": None,
    "GET /v1/admin/tenants/{tenant_id}/spend": None,
    "GET /v1/admin/tenants/{tenant_id}/whatsapp-alerts": None,
    "DELETE /v1/admin/tenants/{tenant_id}/invitations/{invitation_id}": None,
    "POST /v1/admin/tenants/{tenant_id}/agents/{agent_id}/publish": None,
    "POST /v1/admin/tenants/{tenant_id}/agents/{agent_id}/undo": None,
    "POST /v1/admin/tenants/{tenant_id}/kb/{source_id}/approve": None,
    "POST /v1/admin/tenants/{tenant_id}/kb/{source_id}/publish": None,
    "POST /v1/ops/tenants/{tenant_id}/spend-cap/recompute": None,
}


def _confirmation_for(key: str, ids: dict[str, str]) -> str | None:
    """The step-up header this route demands, built the way the route builds it.

    A route whose step-up is unsatisfied answers 403 before it looks at the tenant, so
    without these the entry would pass on the wrong refusal. Spelled out here rather than
    imported wholesale so that a confirmation string changing shape shows up as a failure
    in this census too, not only in its own suite.
    """
    subject = ids.get("tenant_id", "")
    return {
        "POST /v1/admin/tenants/{tenant_id}/commercial-terms": f"loosen_spend_ceiling:{subject}",
        "POST /v1/admin/tenants/{tenant_id}/erasure": f"erase_tenant_data:{subject}",
        "POST /v1/admin/tenants/{tenant_id}/closure": f"close_and_schedule_erasure:{subject}",
        "POST /v1/admin/tenants/{tenant_id}/credits/adjustments": f"adjust_credits:{subject}",
        "POST /v1/admin/tenants/{tenant_id}/credits/restatements": (
            "restate_topup:UTR-CENSUS-1:900.00"
        ),
        "POST /v1/ops/tenants/{tenant_id}/spend-cap/recompute": f"recompute_spend_cap:{subject}",
        "POST /v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/preference-scrub": (
            f"record_preference_scrub:{ids.get('campaign_id', '')}"
        ),
    }.get(key)


#: Routes that legitimately answer something other than 404, each with the reason and
#: what would close it. Keyed exactly as the census keys a route, in the manner of
#: `impersonation_reads_test.ADMIN_CONSOLE_GETS`: an entry that stops matching a live
#: route fails, so this cannot quietly become the place defects go.
NOT_A_404: dict[str, str] = {
    "GET /v1/admin/tenants/{tenant_id}/erasure": (
        "the ONE surface whose subject is the deletion. `tenant_erasure_routes` argues it "
        "at module level: `tenant_exists` treats a soft-deleted tenant as absent, so "
        "using it here would make the certificate unreachable at the instant the erasure "
        "that produced it succeeded. It answers `[]` for an id that names nothing, which "
        "is weaker than the reads above it but is not a claim about a client's state — "
        "the tenant DETAIL screen this list hangs off already 404s (`get_tenant`), so the "
        "list is not reachable with a mistyped id from the console. CLOSED BY: a "
        "predicate for 'an organizations row exists, deleted or not', which is a second "
        "existence definition and is not worth minting for one list route. The per-record "
        "read beside it (`GET …/erasure/{request_id}`) is already a 404."
    ),
}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "superadmin") -> str:
    """A SUPERADMIN, because three of these routes check `ops:manage` before anything
    else and an `operator` would be refused 403 on them for a reason this census is not
    about."""
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return f"dev:admin:{admin_id}"


def _tenant_path_routes() -> list[tuple[str, str, list[str]]]:
    """(method, path template, path parameter names) for every route in the census."""
    found: list[tuple[str, str, list[str]]] = []
    for route in iter_api_routes(app):
        if not route.path.startswith(TENANT_PATH_PREFIXES):
            continue
        params = [param.name for param in route.dependant.path_params]
        for method in sorted((route.methods or set()) - {"HEAD", "OPTIONS"}):
            found.append((method, route.path, params))
    return sorted(found)


@pytest.fixture(scope="module")
def census() -> list[tuple[str, str, list[str]]]:
    return _tenant_path_routes()


def test_the_census_is_not_empty(census: list[tuple[str, str, list[str]]]) -> None:
    """Non-vacuity. If route discovery breaks, every assertion below passes over nothing
    and this file reports that the whole class is clean."""
    assert len(census) >= 40, f"only {len(census)} tenant-path routes found — discovery broke"


def test_every_tenant_path_route_is_in_this_suite(
    census: list[tuple[str, str, list[str]]],
) -> None:
    """The completeness half, and the reason this is a census rather than three more
    one-off tests: a route added tomorrow that names a tenant in its path is in the class
    on the day it lands, whether or not anybody remembers this file exists."""
    missing = [
        f"{method} {path}"
        for method, path, _params in census
        if f"{method} {path}" not in BODIES and f"{method} {path}" not in NOT_A_404
    ]
    assert not missing, (
        f"these tenant-path routes are not in this census: {missing}. Add each to BODIES "
        "with a body the route ACCEPTS (a 422 proves nothing) or `None` if it takes no "
        "body — or, if the route legitimately answers something other than 404 for an "
        "absent tenant, add it to NOT_A_404 with the reason and what closes it."
    )


def test_no_exemption_names_a_route_that_is_gone(
    census: list[tuple[str, str, list[str]]],
) -> None:
    """A stale exemption is how an allowlist becomes a hole — the path gets renamed, the
    entry stays, and the next route to land on it inherits a pass it never earned. Same
    assertion `impersonation_reads_test` and `loadshed_exemption_test` carry."""
    live = {f"{method} {path}" for method, path, _params in census}
    stale = sorted((set(NOT_A_404) | set(BODIES)) - live)
    assert not stale, (
        f"this census names routes that no longer exist: {stale} — remove them from "
        "BODIES / NOT_A_404 rather than leaving an entry the next route can land on."
    )


async def test_a_tenant_id_that_names_nothing_is_a_404_on_every_route(
    census: list[tuple[str, str, list[str]]],
) -> None:
    """The whole class, driven.

    Every id in the path is fresh and random, so nothing in this run names a real row —
    which means a 404 is the ONLY correct answer regardless of which id the route looks
    at first. That is deliberate: this census is not about which object a route names in
    its refusal, it is about the refusal being a refusal and not a 500, a 422 about the
    wrong thing, or a 200 describing an account that does not exist.
    """
    token = await _make_admin()
    wrong: list[str] = []
    fixture_stale: list[str] = []

    async with _client() as http:
        for method, path, params in census:
            key = f"{method} {path}"
            if key in NOT_A_404:
                continue
            url = path
            ids: dict[str, str] = {}
            for name in params:
                value = REAL_FLAG if name == "flag" else str(uuid.uuid4())
                ids[name] = value
                url = url.replace("{" + name + "}", value)
            headers = {"Authorization": f"Bearer {token}"}
            confirmation = _confirmation_for(key, ids)
            if confirmation is not None:
                headers["X-Confirm-Action"] = confirmation
            body = BODIES.get(key)
            response = await http.request(
                method, url, headers=headers, json=body if body is not None else None
            )
            if response.status_code == 422:
                # 422 is reported apart from the rest because it has TWO causes and they
                # want opposite fixes: a stale body here, or a route that refuses an
                # absent tenant with a business rule about something else — which is
                # exactly the `alert_optin_no_owner_with_a_number` defect this file
                # found. Both are failures; the message has to name both so the next
                # reader does not "fix" the fixture past a real regression.
                validation = str(response.json().get("kind"))
                fixture_stale.append(f"{key} -> [{validation}] {response.text[:160]}")
                continue
            if response.status_code != 404:
                wrong.append(f"{key} -> {response.status_code} {response.text[:160]}")
                continue
            payload = response.json()
            if payload.get("kind") != "not_found":
                wrong.append(f"{key} -> 404 but kind={payload.get('kind')!r}")

    assert not fixture_stale, (
        f"these routes answered 422 for a tenant that does not exist: {fixture_stale}. "
        "`kind=validation` means THIS FILE's `BODIES` entry is stale and the route was "
        "never reached — fix the body, because a 422 there hides whatever the route "
        "really does. Any other `kind` means the ROUTE answered a business rule about "
        "something else (a missing owner, a wrong state) to an account that is not "
        "there, which is the defect this census exists for: guard with "
        "`admin.service.tenant_exists` first."
    )
    assert not wrong, (
        "a tenant id that names no organization must be a 404 `not_found` on every route "
        f"that takes one in its path: {wrong}. Ask `admin.service.tenant_exists` inside "
        "the `tenant_session(tenant_id)` block and raise `ProblemError.not_found('Client')` "
        "— see D-133 and the module docstring here for what each of the other answers "
        "cost an operator."
    )


async def test_nothing_was_written_for_a_tenant_that_does_not_exist() -> None:
    """The other half of a refusal: it refused BEFORE the write.

    The sweep above proves the status code. This proves the row — because two of the
    defects it found were foreign-key violations, and a fix that answered 404 by catching
    the `IntegrityError` after the statement had run would satisfy the sweep while leaving
    the write attempt, the alert and (on a shared transaction) the rollback in place.
    """
    absent = uuid.uuid4()
    token = await _make_admin()

    async with _client() as http:
        for path, body in (
            (
                f"/v1/admin/tenants/{absent}/dlt-registration",
                {
                    "pe_id": "PE1234567890",
                    "entity_name": "Census Clinic",
                    "status": "active",
                    "tm_link_status": "active",
                },
            ),
            (
                f"/v1/admin/tenants/{absent}/first-campaign-review",
                {"decision": "approved", "note": "list, script and disclosure checked"},
            ),
            (
                f"/v1/admin/tenants/{absent}/whatsapp-alerts",
                {"status": "granted", "evidence": {"ref": "onboarding form"}},
            ),
        ):
            response = await http.post(
                path, headers={"Authorization": f"Bearer {token}"}, json=body
            )
            assert response.status_code == 404, f"{path}: {response.text}"

    async with untenanted_session() as session:
        counts = (
            await session.execute(
                text(
                    "SELECT (SELECT count(*) FROM dlt_registrations WHERE tenant_id = :t), "
                    "(SELECT count(*) FROM first_campaign_reviews WHERE tenant_id = :t), "
                    "(SELECT count(*) FROM whatsapp_alert_optin_ledger WHERE tenant_id = :t), "
                    "(SELECT count(*) FROM audit_log WHERE tenant_id = :t)"
                ),
                {"t": absent},
            )
        ).one()
    assert tuple(counts) == (0, 0, 0, 0), (
        "a refused request for a tenant that does not exist left a row behind: "
        f"(dlt_registrations, first_campaign_reviews, whatsapp_alert_optin_ledger, "
        f"audit_log) = {tuple(counts)}"
    )


async def test_the_two_reads_that_answered_200_now_name_the_missing_client() -> None:
    """The three cheerful 200s, asserted on the SENTENCE and not only on the status.

    `GET …/margin`, `GET …/commercial-terms` and `GET …/invitations` each rendered a
    complete, plausible screen about an account that does not exist: a ₹0 margin card,
    "no terms have ever been set", and "no invitation is outstanding". None of the three
    is an empty payload a caller would notice — they are the payloads a REAL new client
    produces, which is exactly why nobody noticed.
    """
    absent = uuid.uuid4()
    token = await _make_admin()
    headers = {"Authorization": f"Bearer {token}"}

    async with _client() as http:
        margin = await http.get(f"/v1/admin/tenants/{absent}/margin", headers=headers)
        terms = await http.get(f"/v1/admin/tenants/{absent}/commercial-terms", headers=headers)
        invitations = await http.get(f"/v1/admin/tenants/{absent}/invitations", headers=headers)

    for name, response in (("margin", margin), ("terms", terms), ("invitations", invitations)):
        assert response.status_code == 404, f"{name}: {response.text}"
        assert response.json()["kind"] == "not_found", f"{name}: {response.text}"
        assert "client" in response.json()["detail"].lower(), f"{name}: {response.text}"
    # The specific claims that must NOT come back.
    assert "state" not in terms.json(), terms.text
    assert invitations.json() != [], "an empty list is the answer this test exists to delete"


async def test_an_agent_id_that_names_nothing_has_no_prompt_history() -> None:
    """`GET …/agents/{agent_id}/prompt` answered `[]`, which is a real state of a real
    agent — the one `publish` refuses as `agent_has_no_script` — so a mistyped agent id
    looked like a live agent awaiting its first script.

    Driven with a REAL tenant and a fake agent, because the interesting id here is the
    agent: with both absent the answer would be a 404 either way and the fix would not be
    the thing under test.
    """
    from apps.api.admin import service as admin_service

    token = await _make_admin()
    org = await admin_service.create_organization(
        name="Prompt History Clinic",
        slug=f"ph-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    # The four agreements, accepted (migration a9d4e70c31b8) — supplied, never assumed
    # away, in the shape `arm_agent_for_outbound` established. Every dial, launch and
    # publish gate now refuses an organisation that has not accepted them, so a fixture
    # without this reports `agreements_not_accepted` in place of the answer under test.
    await accept_agreements(uuid.UUID(str(org["id"])))

    async with _client() as http:
        absent_agent = await http.get(
            f"/v1/admin/tenants/{org['id']}/agents/{uuid.uuid4()}/prompt",
            headers={"Authorization": f"Bearer {token}"},
        )
        # The control: the tenant's OWN agent answers 200, so the 404 above is about the
        # agent id and not about the route having become unreachable.
        real_agent = await http.get(
            f"/v1/admin/tenants/{org['id']}/agents/{org['agent_id']}/prompt",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert absent_agent.status_code == 404, absent_agent.text
    assert absent_agent.json()["kind"] == "not_found"
    assert "agent" in absent_agent.json()["detail"].lower()
    assert real_agent.status_code == 200, real_agent.text
    assert isinstance(real_agent.json(), list)
