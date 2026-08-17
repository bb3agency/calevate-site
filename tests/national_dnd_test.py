"""The NATIONAL half of SEC-COMP §3's DNC promise — the half that had no writer.

§3 certifies a contact list as "DNC-scrubbed (national DND + tenant dnc_list) with scrub
timestamp". Before migration `a1c8e40f27b9` the sentence was true of one of its three
clauses: `dnc_list.scope='global'` was read everywhere and written nowhere, and no scrub
timestamp was recorded at all. Two mechanisms close it and this file is the evidence for
both.

**The global scope has a writer, and only ops can reach it.** The first two tests are
the pair that matters: a platform-wide suppression now blocks every tenant, and a TENANT
session still cannot create one — which is the escalation `17a91a69dee9`'s asymmetric
policy exists to prevent and which the widened `WITH CHECK` must not have reopened.

**The national preference scrub is a recorded RUN, not a loaded list.** The register is
not obtainable (`apps/api/compliance/preference_scrub.py` carries the sources); an access
provider's DLT platform scrubs a submitted list and returns a reference, a count and a
verdict valid to the end of the day. So the tests below assert about a run: that a
promotional campaign cannot launch without a current one, that transactional campaigns
are not gated on a scrub the register does not perform, that a run expires at midnight
IST and stops a RUNNING campaign, that a list which grew after its scrub is refused, and
that the artefact cannot be edited afterwards.

`record_test_scrub` is exported because several existing campaign suites build a
launch-ready campaign, and a launch-ready promotional campaign is now one whose list has
been scrubbed. Those fixtures SUPPLY the fact through the production code path; they do
not soften the gate, and the first test here proves the refusal is real by not supplying
it. (Same shape as `conftest.platform_tm_registration_is_live` and as
`tests/impersonation_grant_test.view_as_headers`, which other suites import the same way.)

CONCURRENCY: every case mints its own tenant and asserts only on rows it created. Global
DNC rows have no tenant, so they use run-unique numbers and are asserted by id.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.campaigns import service as campaign_service
from apps.api.compliance import dnc, preference_scrub
from apps.api.compliance.national_dnd_routes import (
    RELEASE_GLOBALLY_CONFIRMATION,
    SUPPRESS_GLOBALLY_CONFIRMATION,
    preference_scrub_confirmation,
    release_globally_confirmation,
)
from apps.api.compliance.service import IST, check_dispatch
from apps.api.core.errors import ProblemError
from apps.api.core.logging import JsonFormatter
from apps.api.core.rbac import iter_api_routes
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

PROVIDER = "airtel-dlt"


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the dial gate's clock to 11:00 IST so `calling_hours` never stands in for the
    rule under test — a DNC assertion that passes at 22:00 proves nothing."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + IST
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _number() -> str:
    """A fresh dialable Indian mobile. Global rows outlive a tenant, so a constant here
    would couple every run of this file to every other."""
    return f"+9198{uuid.uuid4().int % 100000000:08d}"


def _code(response: Any) -> str:
    """RFC-9457 has no `code` field; the machine identifier is `type`'s last segment."""
    return str(response.json()["type"]).rsplit("/", 1)[-1]


async def _admin_token(role: str = "superadmin") -> str:
    """Same idiom as `route_shape_test._make_admin` / `ops_spend_cap_recompute_test`."""
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


async def _tenant() -> tuple[uuid.UUID, uuid.UUID, str, str]:
    """(tenant_id, agent_id, slug, client bearer token) for a fresh org with an owner."""
    created = await admin_service.create_organization(
        name="Preference Motors",
        slug=f"pref-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id, slug = created["id"], created["agent_id"], created["slug"]
    user_id, user_id = uuid.uuid4(), f"user_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )
        await session.execute(
            text("UPDATE agents SET status = 'live', direction = 'outbound' WHERE id = :a"),
            {"a": agent_id},
        )
    return tenant_id, agent_id, str(slug), f"dev:client:{user_id}"


async def record_test_scrub(
    session: Any,
    campaign_id: uuid.UUID,
    *,
    scrubbed_at: datetime | None = None,
    blocked_numbers: list[str] | None = None,
) -> preference_scrub.ScrubRecorded:
    """Supply the fact that a campaign's list was preference-scrubbed.

    THE PRODUCTION PATH, deliberately — `record_scrub_run`, not an INSERT. A fixture
    that wrote the row by hand would keep passing after the writer stopped computing the
    expiry, the counts or the contact marking correctly, which is the whole of what this
    artefact is for.

    Exported for the campaign suites that build a launch-ready campaign: a promotional
    campaign is launch-ready only once its list is scrubbed, so their fixtures now say
    so. It supplies the fact and softens nothing —
    `test_a_promotional_campaign_cannot_launch_without_a_national_dnd_scrub` proves the
    refusal by leaving it out.
    """
    return await preference_scrub.record_scrub_run(
        session,
        campaign_id=campaign_id,
        provider=PROVIDER,
        scrub_ref=f"SCRUB-{uuid.uuid4().hex[:10].upper()}",
        scrubbed_at=scrubbed_at or datetime.now(UTC),
        blocked_numbers=blocked_numbers or [],
        recorded_by_admin_id=None,
    )


async def _campaign(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    classification: str = "promotional",
    phones: tuple[str, ...] = (),
) -> uuid.UUID:
    """A campaign that is launch-ready EXCEPT for the national scrub, so every launch
    assertion below turns on that one fact and not on a missing template."""
    series = "140" if classification == "promotional" else "160"
    async with tenant_session(tenant_id) as session:
        number_id, template_id = uuid7(), uuid7()
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, e164, series, dlt_status, "
                "created_at, updated_at) VALUES (:id, :tid, :e, :s, 'registered', now(), now())"
            ),
            {
                "id": number_id,
                "tid": tenant_id,
                "e": f"+9180{uuid.uuid4().int % 100000000:08d}",
                "s": series,
            },
        )
        await session.execute(
            text(
                "INSERT INTO dlt_templates (id, tenant_id, kind, classification, body, status, "
                "created_at, updated_at) VALUES (:id, :tid, 'voice', :cls, :body, "
                "'approved', now(), now())"
            ),
            {
                "id": template_id,
                "tid": tenant_id,
                "cls": classification,
                "body": "Hello from {#var#}, this is an AI assistant calling about your enquiry.",
            },
        )
        await session.execute(
            text(
                "INSERT INTO dlt_registrations (id, tenant_id, pe_id, entity_name, status, "
                "tm_link_status, registered_at, verified_at, created_at, updated_at) VALUES "
                "(:id, :tid, 'PE-TEST-0001', 'Preference Motors', 'active', 'active', "
                "now(), now(), now(), now()) ON CONFLICT (tenant_id) DO NOTHING"
            ),
            {"id": uuid7(), "tid": tenant_id},
        )
        campaign_id = await campaign_service.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Diwali offers",
            classification=classification,
            number_id=number_id,
            dlt_template_id=template_id,
            concurrency=1,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )
        if phones:
            await campaign_service.add_contacts(
                session,
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                contacts=[{"phone": p, "name": None} for p in phones],
            )
    return campaign_id


def _rules(blockers: list[campaign_service.LaunchBlocker]) -> set[str]:
    return {blocker.rule for blocker in blockers}


# --------------------------------------------------- the global scope gets a writer


async def test_a_global_suppression_now_exists_and_blocks_every_tenant() -> None:
    """THE DEFECT, closed. `scope='global'` was read by the gate, ranked above a tenant
    entry, refused by `remove_entry` and included in the launch scrub — and no code path
    anywhere could create one, so the whole apparatus stood over an empty set.

    Asserted across TWO tenants, because "global" is the claim being tested: a row one
    ops action wrote must refuse a number for a client who has never heard of it.
    """
    a_tenant, a_agent, _slug, _token = await _tenant()
    b_tenant, b_agent, _b_slug, _b_token = await _tenant()
    phone = _number()

    async with tenant_session(a_tenant) as session:
        before = await check_dispatch(
            session, tenant_id=a_tenant, agent_id=a_agent, phone_e164=phone
        )
    assert before.allowed, f"baseline must be dialable, got {before.rule}"

    async with untenanted_session() as ops:
        added = await dnc.add_global_numbers(ops, raw_numbers=[phone], source="regulator")
    assert (added.added, added.already_suppressed, added.malformed) == (1, 0, 0)

    for tenant_id, agent_id in ((a_tenant, a_agent), (b_tenant, b_agent)):
        async with tenant_session(tenant_id) as session:
            decision = await check_dispatch(
                session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone
            )
            seen = await dnc.check_number(session, tenant_id=tenant_id, raw=phone)
        assert not decision.allowed and decision.rule == "dnc"
        assert seen.suppressed and seen.scope == "global", (
            "a tenant must be able to see WHICH list caught the number"
        )


async def test_a_tenant_session_still_cannot_write_a_global_row() -> None:
    """The property `17a91a69dee9` wrote the asymmetric policy for, and the one the
    widened WITH CHECK must not have reopened.

    If a tenant could insert `tenant_id IS NULL`, any client could suppress a number for
    every other client on the platform. The new ops branch is guarded on the GUC being
    ABSENT, so this INSERT — the exact statement `add_global_numbers` runs, on a tenant
    session — has to be refused by the database rather than by a code path someone could
    forget.
    """
    tenant_id, _agent_id, _slug, _token = await _tenant()
    phone = _number()

    with pytest.raises(DBAPIError) as caught:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source, "
                    "added_at, created_at) VALUES (:id, NULL, :phone, 'global', "
                    "'regulator', now(), now())"
                ),
                {"id": uuid7(), "phone": phone},
            )
    assert "row-level security" in str(caught.value).lower(), str(caught.value)

    # And nothing was written: a refusal that leaked a row would be worse than no
    # refusal, because the list would be wrong and the policy would look right.
    async with untenanted_session() as ops:
        rows = (
            await ops.execute(
                text("SELECT count(*) FROM dnc_list WHERE phone_e164 = :p"), {"p": phone}
            )
        ).scalar()
    assert rows == 0


async def test_suppressing_the_same_number_twice_globally_leaves_one_row() -> None:
    """`UNIQUE (tenant_id, phone_e164)` never constrained global rows and nobody could
    notice, because nothing could write one: Postgres treats NULLs as distinct in a
    unique index, so two `tenant_id IS NULL` rows for one number do not conflict. The
    partial unique index migration `a1c8e40f27b9` adds is what makes the second call a
    no-op instead of a duplicate."""
    phone = _number()
    async with untenanted_session() as ops:
        first = await dnc.add_global_numbers(ops, raw_numbers=[phone], source="regulator")
        second = await dnc.add_global_numbers(
            ops, raw_numbers=[phone, "not a number"], source="platform_block"
        )
        rows = (
            await ops.execute(
                text("SELECT count(*) FROM dnc_list WHERE phone_e164 = :p AND tenant_id IS NULL"),
                {"p": phone},
            )
        ).scalar()
    assert (first.added, first.already_suppressed) == (1, 0)
    assert (second.added, second.already_suppressed, second.malformed) == (0, 1, 1)
    assert rows == 1, "the partial unique index is what stops a second identical row"


async def test_the_ops_surface_is_step_up_confirmed_audited_and_echoes_no_number() -> None:
    """Three properties of one request, because on this route they are one event: a
    stolen session cannot stop the whole platform dialling a number with a bare POST,
    the response carries counts rather than the list, and the audit entry names the
    operator without naming the number (hard rule 6)."""
    token = await _admin_token()
    phone = _number()
    headers = {"Authorization": f"Bearer {token}"}
    body = {"numbers": [phone], "source": "regulator", "reason": "TRAI escalation TT-4417"}

    async with _client() as http:
        unconfirmed = await http.post("/v1/ops/dnc/global", headers=headers, json=body)
        wrong_action = await http.post(
            "/v1/ops/dnc/global",
            headers={**headers, "X-Confirm-Action": RELEASE_GLOBALLY_CONFIRMATION},
            json=body,
        )
        created = await http.post(
            "/v1/ops/dnc/global",
            headers={**headers, "X-Confirm-Action": SUPPRESS_GLOBALLY_CONFIRMATION},
            json=body,
        )
        listed = await http.get("/v1/ops/dnc/global", headers=headers)

    assert unconfirmed.status_code == 403 and _code(unconfirmed) == "step_up_required"
    assert wrong_action.status_code == 403, "a confirmation for the opposite act is not consent"
    assert created.status_code == 201, created.text
    assert created.json() == {"added": 1, "already_suppressed": 0, "malformed": 0}
    assert phone not in created.text and phone.lstrip("+") not in created.text

    assert listed.status_code == 200
    entry = next(e for e in listed.json() if e["phone_masked"] == f"••••••{phone[-2:]}")
    assert entry["scope"] == "global" and entry["removable"] is False
    assert phone not in listed.text and phone.lstrip("+") not in listed.text

    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT actor_type, object_type FROM audit_log "
                    "WHERE action = 'ops.dnc_global_added' ORDER BY created_at DESC LIMIT 1"
                )
            )
        ).first()
    assert row is not None, "suppressing a number for every tenant must leave a record"
    assert (row[0], row[1]) == ("admin", "dnc_list")


async def test_a_global_entry_is_lifted_by_ops_and_by_nobody_else() -> None:
    """The two halves of `remove_entry`'s `dnc_global_entry` refusal, which named a desk
    that did not exist until now: the client still cannot delete it, and operations now
    can."""
    _tenant_id, _agent_id, slug, client_token = await _tenant()
    ops_token = await _admin_token()
    phone = _number()

    async with untenanted_session() as ops:
        await dnc.add_global_numbers(ops, raw_numbers=[phone], source="platform_block")
        entry_id = (
            await ops.execute(
                text("SELECT id FROM dnc_list WHERE phone_e164 = :p AND tenant_id IS NULL"),
                {"p": phone},
            )
        ).scalar()

    async with _client() as http:
        by_client = await http.delete(
            f"/v1/dnc/{entry_id}",
            headers={"Authorization": f"Bearer {client_token}", "X-Org-Slug": slug},
        )
        unconfirmed = await http.delete(
            f"/v1/ops/dnc/global/{entry_id}", headers={"Authorization": f"Bearer {ops_token}"}
        )
        # The confirmation from a DIFFERENT row, which is the realistic replay: an
        # operator with a curl in their shell history changes the id and re-runs it.
        # Before the string carried its subject this deleted the entry.
        wrong_row = await http.delete(
            f"/v1/ops/dnc/global/{entry_id}",
            headers={
                "Authorization": f"Bearer {ops_token}",
                "X-Confirm-Action": release_globally_confirmation(uuid.uuid4()),
            },
        )
        # And the bare stem, which is what the route accepted before D-141.
        bare_stem = await http.delete(
            f"/v1/ops/dnc/global/{entry_id}",
            headers={
                "Authorization": f"Bearer {ops_token}",
                "X-Confirm-Action": RELEASE_GLOBALLY_CONFIRMATION,
            },
        )
        by_ops = await http.delete(
            f"/v1/ops/dnc/global/{entry_id}",
            headers={
                "Authorization": f"Bearer {ops_token}",
                "X-Confirm-Action": release_globally_confirmation(entry_id),
            },
        )

    assert by_client.status_code == 422 and _code(by_client) == "dnc_global_entry"
    assert unconfirmed.status_code == 403 and _code(unconfirmed) == "step_up_required"
    assert wrong_row.status_code == 403 and _code(wrong_row) == "step_up_required", wrong_row.text
    assert bare_stem.status_code == 403 and _code(bare_stem) == "step_up_required", bare_stem.text
    # The refusals ran BEFORE the delete — `require_step_up` is the first statement in
    # the handler, and an entry that survived two refused requests is what proves it.
    assert by_ops.status_code == 204 and by_ops.content == b""

    async with untenanted_session() as ops:
        survives = (
            await ops.execute(text("SELECT count(*) FROM dnc_list WHERE id = :i"), {"i": entry_id})
        ).scalar()
    assert survives == 0


async def test_ops_cannot_reach_a_tenants_own_suppression_through_the_global_route() -> None:
    """The mistake in the other direction. `/v1/ops/dnc/global` exists to lift a
    PLATFORM-WIDE block; an operator who pasted a tenant entry's id into it must not
    delete a client's own opt-out record — that is the client's list, and
    `DELETE /v1/dnc/{id}` (with its `dnc_consumer_optout` refusal) is the only door to it.

    Two controls stand here and this asserts the OUTCOME rather than either of them:
    `remove_global_entry` filters on `tenant_id IS NULL`, and the ops session carries no
    `app.tenant_id` so RLS shows it global rows only. If one is removed the other still
    holds; if the RLS half ever regresses, this fails.
    """
    tenant_id, _agent_id, _slug, _token = await _tenant()
    ops_token = await _admin_token()
    phone = _number()

    async with tenant_session(tenant_id) as session:
        await dnc.add_numbers(
            session, tenant_id=tenant_id, raw_numbers=[phone], source="call_optout"
        )
        entry_id = (
            await session.execute(
                text("SELECT id FROM dnc_list WHERE tenant_id = :t AND phone_e164 = :p"),
                {"t": tenant_id, "p": phone},
            )
        ).scalar()

    async with _client() as http:
        refused = await http.delete(
            f"/v1/ops/dnc/global/{entry_id}",
            headers={
                "Authorization": f"Bearer {ops_token}",
                "X-Confirm-Action": release_globally_confirmation(entry_id),
            },
        )

    # 404 and not 403: the confirmation is correct for this id, so the refusal being
    # asserted is the scope filter and not the step-up standing in front of it.
    assert refused.status_code == 404, refused.text
    async with tenant_session(tenant_id) as session:
        survives = (
            await session.execute(
                text("SELECT count(*) FROM dnc_list WHERE id = :i"), {"i": entry_id}
            )
        ).scalar()
    assert survives == 1, "a consumer's opt-out is not ops's to delete from here"


async def test_an_unrecognised_global_source_is_refused_by_name() -> None:
    """`GLOBAL_SOURCES` is deliberately disjoint from the two consumer sources: nobody
    asks a client's receptionist to suppress a number for every business on the
    platform, and accepting `call_optout` here would invite exactly that widening."""
    async with untenanted_session() as ops:
        with pytest.raises(ProblemError) as caught:
            await dnc.add_global_numbers(ops, raw_numbers=[_number()], source="call_optout")
    assert caught.value.code == "dnc_unknown_global_source"
    assert set(dnc.GLOBAL_SOURCES).isdisjoint({"customer_request", "call_optout"})


# ------------------------------------------------- the national preference scrub run


async def test_a_promotional_campaign_cannot_launch_without_a_national_dnd_scrub() -> None:
    """THE HONESTY TEST. SEC-COMP §3 certifies the list as scrubbed against the national
    DND; before this, that clause was a claim the system could not support and a
    promotional campaign launched anyway.

    The refusal is by NAME and the wording says who acts, because a client holds no DLT
    login and a blocker phrased as their to-do would be worse than silence.
    """
    tenant_id, agent_id, _slug, _token = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id, phones=("9876500011", "9876500012"))

    async with tenant_session(tenant_id) as session:
        blocked = await campaign_service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        with pytest.raises(ProblemError) as refused:
            await campaign_service.launch_campaign(
                session, tenant_id=tenant_id, campaign_id=campaign_id
            )

    assert "national_dnd_scrub_missing" in _rules(blocked), _rules(blocked)
    assert refused.value.code == "campaign_launch_blocked"
    reason = next(
        f["message"]
        for f in (refused.value.fields or [])
        if f["rule"] == "national_dnd_scrub_missing"
    )
    assert "preference register" in reason
    assert "nothing to do at your end" in reason.lower(), (
        "a blocker a client cannot act on must say so, like tm_registration_missing"
    )

    # ...and with a scrub recorded, the same campaign launches. Nothing else changed.
    async with tenant_session(tenant_id) as session:
        await record_test_scrub(session, campaign_id)
        result = await campaign_service.launch_campaign(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    assert result["status"] == "running"


async def test_a_transactional_campaign_is_not_gated_on_a_scrub_the_register_never_does() -> None:
    """Precision, not leniency. Under full DND every category is blocked EXCEPT
    service-implicit, and transactional traffic is delivered whatever the preference —
    so refusing a transactional campaign for want of a preference scrub would suppress
    the one class of call a fully-blocked subscriber is entitled to receive."""
    tenant_id, agent_id, _slug, _token = await _tenant()
    transactional = await _campaign(
        tenant_id, agent_id, classification="transactional", phones=("9876500021",)
    )
    service_campaign = await _campaign(
        tenant_id, agent_id, classification="service", phones=("9876500022",)
    )

    async with tenant_session(tenant_id) as session:
        for campaign_id in (transactional, service_campaign):
            blocked = await campaign_service.launch_blockers(
                session, tenant_id=tenant_id, campaign_id=campaign_id
            )
            assert not any(rule.startswith("national_dnd") for rule in _rules(blocked)), (
                f"{campaign_id}: {_rules(blocked)}"
            )
    assert preference_scrub.PREFERENCE_SCRUBBED_CLASSIFICATIONS == ("promotional",)


async def test_a_scrub_expires_at_the_end_of_its_ist_day_and_stops_a_running_campaign() -> None:
    """A provider's scrub is valid only until 23:59:59 IST of the day it was produced,
    and preference registrations change daily — so a campaign that launched on a valid
    scrub is dialling an unscrubbed list by morning.

    Three assertions, in the order the fact travels: the expiry is the END OF THE DAY
    rather than 24 hours later; an aged run refuses a LAUNCH by its own name; and an
    aged run refuses a campaign that is already RUNNING, which is the half
    `dispatch_blockers` exists for and the reason this rule is not asked only once.
    """
    tenant_id, agent_id, _slug, _token = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id, phones=("9876500031",))
    two_days_ago = datetime.now(UTC) - timedelta(days=2)

    async with tenant_session(tenant_id) as session:
        recorded = await record_test_scrub(session, campaign_id, scrubbed_at=two_days_ago)
        expires_at = recorded.state.expires_at
        assert expires_at == preference_scrub.scrub_expiry(two_days_ago)
        assert expires_at is not None and (expires_at + IST).strftime("%H:%M:%S") == "23:59:59"
        assert (expires_at + IST).date() == (two_days_ago + IST).date()
        assert recorded.state.is_current is False

        stale = await campaign_service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        assert "national_dnd_scrub_expired" in _rules(stale), _rules(stale)

        # The campaign reaches `running` WITHOUT relaunching — which is exactly the real
        # sequence: it launched yesterday on a scrub that was valid then. The row cannot
        # be back-dated (append-only), so the campaign moves instead of the evidence.
        await session.execute(
            text("UPDATE campaigns SET status = 'running', updated_at = now() WHERE id = :cid"),
            {"cid": campaign_id},
        )
        ticking = await campaign_service.dispatch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    assert "national_dnd_scrub_expired" in _rules(ticking), (
        "a running campaign whose scrub aged out overnight must stop at the next tick"
    )


async def test_the_newest_run_by_the_providers_clock_is_the_one_that_counts() -> None:
    """Re-scrubbing is an INSERT, so a campaign accumulates runs; the current one is the
    newest by `scrubbed_at` — when the PROVIDER ran it — not by when we typed it in. Two
    recordings out of order must still resolve to the newer scrub."""
    tenant_id, agent_id, _slug, _token = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id, phones=("9876500041",))

    async with tenant_session(tenant_id) as session:
        await record_test_scrub(session, campaign_id)
        # Recorded second, ran three days ago: it must not become the current run.
        await record_test_scrub(
            session, campaign_id, scrubbed_at=datetime.now(UTC) - timedelta(days=3)
        )
        current = await preference_scrub.read_current_scrub(session, campaign_id=campaign_id)
        blockers = await campaign_service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    assert current.is_current is True
    assert not any(rule.startswith("national_dnd") for rule in _rules(blockers)), _rules(blockers)


async def test_recording_a_scrub_marks_the_blocked_contacts_and_reports_counts_only() -> None:
    """What the provider suppressed comes out of the campaign, and nothing else does.

    The blocked numbers are deliberately NOT written to `dnc_list`: a preference blocks
    this class of traffic today, it does not suppress the person for this tenant
    forever, and a `dnc_list` row would refuse a lawful transactional call to the same
    subscriber tomorrow.
    """
    tenant_id, agent_id, _slug, _token = await _tenant()
    keep, other, drop = "9876500051", "9876500053", "9876500052"
    # THREE contacts and TWO readable blocked numbers, deliberately unequal: `submitted`
    # is the size of the LIST, not of the caller's input, and a fixture where the two
    # coincide cannot tell the difference.
    campaign_id = await _campaign(tenant_id, agent_id, phones=(keep, other, drop))

    async with tenant_session(tenant_id) as session:
        recorded = await record_test_scrub(
            session, campaign_id, blocked_numbers=[drop, "9876599999", "banana"]
        )
        statuses = {
            row[0]: row[1]
            for row in (
                await session.execute(
                    text(
                        "SELECT right(phone_e164, 4), status FROM campaign_contacts "
                        "WHERE campaign_id = :cid"
                    ),
                    {"cid": campaign_id},
                )
            ).all()
        }
        in_dnc = (
            await session.execute(
                text("SELECT count(*) FROM dnc_list WHERE phone_e164 = :p"),
                {"p": f"+91{drop}"},
            )
        ).scalar()

    assert recorded.submitted == 3, "the size of the LIST is read, never taken on trust"
    assert recorded.suppressed == 1
    assert recorded.unmatched == 1, "a number the campaign never held is reported, not silent"
    assert recorded.malformed == 1
    assert statuses[drop[-4:]] == "dnc_blocked"
    assert statuses[keep[-4:]] == "pending"
    assert statuses[other[-4:]] == "pending"
    assert in_dnc == 0, "a preference block is not a permanent suppression of the person"


async def test_recording_the_same_provider_reference_twice_records_one_run() -> None:
    """Idempotency on `(campaign, provider, reference)`: a retry whose response was lost
    must not become a second scrub, and the contact marking must still be applied so a
    replay cannot leave the first attempt half done."""
    tenant_id, agent_id, _slug, _token = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id, phones=("9876500061", "9876500062"))
    ref = f"SCRUB-{uuid.uuid4().hex[:10].upper()}"
    when = datetime.now(UTC)

    async def _record() -> preference_scrub.ScrubRecorded:
        async with tenant_session(tenant_id) as session:
            return await preference_scrub.record_scrub_run(
                session,
                campaign_id=campaign_id,
                provider=PROVIDER,
                scrub_ref=ref,
                scrubbed_at=when,
                blocked_numbers=["9876500062"],
                recorded_by_admin_id=None,
            )

    first, second = await _record(), await _record()
    async with tenant_session(tenant_id) as session:
        runs = (
            await session.execute(
                text("SELECT count(*) FROM preference_scrub_runs WHERE campaign_id = :cid"),
                {"cid": campaign_id},
            )
        ).scalar()
    assert first.first_time is True
    assert second.first_time is False, "the same reference is one scrub, not two"
    assert runs == 1


async def test_a_list_that_grew_after_its_scrub_does_not_launch_on_it() -> None:
    """Scrub three numbers, add five thousand, launch — a sequence that needs no bad
    intent (a client finishes their upload while we are on the portal) and would put
    unscrubbed numbers through a gate reporting itself green."""
    tenant_id, agent_id, _slug, _token = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id, phones=("9876500071",))

    async with tenant_session(tenant_id) as session:
        await record_test_scrub(session, campaign_id)
        ready = await campaign_service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        assert not any(rule.startswith("national_dnd") for rule in _rules(ready))

        await campaign_service.add_contacts(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            contacts=[{"phone": "9876500072", "name": None}],
        )
        grown = await campaign_service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    assert "national_dnd_scrub_incomplete" in _rules(grown), _rules(grown)


async def test_a_recorded_scrub_cannot_be_edited_or_deleted() -> None:
    """Hard rule 4. A scrub is evidence that a list was clean at an instant: an UPDATE
    that moved `scrubbed_at` forward would launder a stale scrub into a fresh one, and a
    DELETE would erase the basis for calls already placed on it."""
    tenant_id, agent_id, _slug, _token = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id, phones=("9876500081",))

    async with tenant_session(tenant_id) as session:
        await record_test_scrub(session, campaign_id)

    for statement in (
        "UPDATE preference_scrub_runs SET scrubbed_at = now() WHERE campaign_id = :cid",
        "DELETE FROM preference_scrub_runs WHERE campaign_id = :cid",
    ):
        with pytest.raises(DBAPIError) as caught:
            async with tenant_session(tenant_id) as session:
                await session.execute(text(statement), {"cid": campaign_id})
        assert "append-only" in str(caught.value).lower(), str(caught.value)


async def test_deleting_the_campaign_keeps_the_evidence_and_drops_only_the_pointer() -> None:
    """The ONE mutation the append-only trigger permits, and why it is not a hole.

    `ON DELETE SET NULL` is executed by Postgres as an ordinary UPDATE of the
    referencing row, so a blanket immutability trigger would make a scrubbed campaign
    undeletable forever — a product decision taken as a side effect of storing evidence.
    The trigger therefore permits exactly `campaign_id` going non-NULL → NULL with every
    other column unchanged, and the run survives still naming its tenant, its provider,
    its reference and its counts.
    """
    tenant_id, agent_id, _slug, _token = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id, phones=("9876500121",))

    async with tenant_session(tenant_id) as session:
        recorded = await record_test_scrub(session, campaign_id)
        await session.execute(
            text("DELETE FROM campaign_contacts WHERE campaign_id = :cid"), {"cid": campaign_id}
        )
        await session.execute(text("DELETE FROM campaigns WHERE id = :cid"), {"cid": campaign_id})
        orphan = (
            await session.execute(
                text(
                    "SELECT campaign_id, provider, scrub_ref, submitted_count "
                    "FROM preference_scrub_runs WHERE scrub_ref = :ref"
                ),
                {"ref": recorded.state.scrub_ref},
            )
        ).first()
    assert orphan is not None, "deleting a campaign must not destroy the scrub it dialled on"
    assert orphan[0] is None, "only the pointer goes"
    assert (orphan[1], orphan[2]) == (PROVIDER, recorded.state.scrub_ref)
    assert orphan[3] == recorded.submitted


async def test_one_tenants_scrub_runs_are_invisible_to_another() -> None:
    """Hard rule 1's cross-tenant zero-rows test for the new table.

    Two halves: B cannot READ A's run, and B cannot use A's campaign id to make one —
    the FK alone would have accepted the id, so the second half is what proves RLS is
    doing the isolation rather than the foreign key.
    """
    a_tenant, a_agent, _a_slug, _a_token = await _tenant()
    b_tenant, _b_agent, _b_slug, _b_token = await _tenant()
    a_campaign = await _campaign(a_tenant, a_agent, phones=("9876500091",))

    async with tenant_session(a_tenant) as session:
        await record_test_scrub(session, a_campaign)

    async with tenant_session(b_tenant) as session:
        visible = (
            await session.execute(text("SELECT count(*) FROM preference_scrub_runs"))
        ).scalar()
        by_id = (
            await session.execute(
                text("SELECT count(*) FROM preference_scrub_runs WHERE campaign_id = :cid"),
                {"cid": a_campaign},
            )
        ).scalar()
        neighbours = await preference_scrub.read_current_scrub(session, campaign_id=a_campaign)
        with pytest.raises(ProblemError) as forged:
            await record_test_scrub(session, a_campaign)

    assert visible == 0, "another tenant's scrub runs must be invisible"
    assert by_id == 0
    assert neighbours.recorded is False
    assert forged.value.status == 404, "another tenant's campaign is not found, not forbidden"


async def test_the_scrub_endpoint_is_step_up_confirmed_and_logs_no_number(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The operator surface, end to end: bound to THIS campaign, audited, and its log
    line carries the provider's reference and the counts and never a number."""
    tenant_id, agent_id, _slug, _token = await _tenant()
    blocked = "9876500101"
    campaign_id = await _campaign(tenant_id, agent_id, phones=(blocked, "9876500102"))
    token = await _admin_token()
    route = f"/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/preference-scrub"
    body = {
        "provider": PROVIDER,
        "scrub_ref": f"SCRUB-{uuid.uuid4().hex[:8].upper()}",
        "scrubbed_at": datetime.now(UTC).isoformat(),
        "blocked_numbers": [blocked],
    }
    formatter = JsonFormatter()

    caplog.set_level(logging.INFO)
    async with _client() as http:
        unconfirmed = await http.post(
            route, headers={"Authorization": f"Bearer {token}"}, json=body
        )
        other_campaign = await http.post(
            route,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Confirm-Action": preference_scrub_confirmation(uuid.uuid4()),
            },
            json=body,
        )
        recorded = await http.post(
            route,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Confirm-Action": preference_scrub_confirmation(campaign_id),
            },
            json=body,
        )

    assert unconfirmed.status_code == 403 and _code(unconfirmed) == "step_up_required"
    assert other_campaign.status_code == 403, (
        "a confirmation captured for one campaign must not scrub another"
    )
    assert recorded.status_code == 201, recorded.text
    payload = recorded.json()
    assert (payload["recorded"], payload["submitted"], payload["suppressed"]) == (True, 2, 1)
    assert payload["is_current"] is True
    assert blocked not in recorded.text and f"+91{blocked}" not in recorded.text

    rendered = "\n".join(formatter.format(record) for record in caplog.records)
    assert "preference_scrub_recorded" in rendered
    assert blocked not in rendered and f"+91{blocked}" not in rendered

    # The formatter's masking is the BACKSTOP, not the control, so the call site is
    # asserted too: the fields it passes are pinned as a set, and any new one fails here
    # rather than relying on `redact_text` recognising whatever shape it is in. A
    # rendered-only assertion passes with the numbers fully present in `extra`.
    emitted = next(r for r in caplog.records if r.getMessage() == "preference_scrub_recorded")
    # `makeLogRecord` gives the built-in attribute set; `taskName`/`message` are added by
    # the runtime rather than by the call site, so the difference is exactly the `extra`.
    builtin = set(vars(logging.makeLogRecord({}))) | {"message", "taskName", "asctime"}
    passed_fields = set(vars(emitted)) - builtin
    assert passed_fields == {
        "campaign_id",
        "provider",
        "scrub_ref",
        "submitted",
        "suppressed",
        "first_time",
    }, passed_fields

    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT object_type, object_id, actor_type FROM audit_log "
                    "WHERE action = 'compliance.preference_scrub_recorded' "
                    "AND tenant_id = :tid ORDER BY created_at DESC LIMIT 1"
                ),
                {"tid": tenant_id},
            )
        ).first()
    assert row is not None
    assert (row[0], row[1], row[2]) == ("preference_scrub_run", str(campaign_id), "admin")


async def test_the_progress_screen_tells_one_scrubbed_list_from_two() -> None:
    """The requirement §3's promise implies and nothing rendered: an operator and a
    client must be able to tell "scrubbed against both lists" from "scrubbed against
    one". Before this pair of fields the two looked identical from every screen."""
    tenant_id, agent_id, slug, token = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id, phones=("9876500111",))
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}

    async with _client() as http:
        before = await http.get(f"/v1/campaigns/{campaign_id}", headers=headers)

    assert before.status_code == 200, before.text
    assert before.json()["dnc_scrubbed_at"] is None
    assert before.json()["national_dnd_scrub"] is None, "no run recorded is not 'scrubbed'"

    async with tenant_session(tenant_id) as session:
        await record_test_scrub(session, campaign_id)
        await campaign_service.launch_campaign(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )

    async with _client() as http:
        after = await http.get(f"/v1/campaigns/{campaign_id}", headers=headers)

    body = after.json()
    assert body["dnc_scrubbed_at"] is not None, "our own scrub finally records when it ran"
    scrub = body["national_dnd_scrub"]
    assert scrub["provider"] == PROVIDER
    assert scrub["is_current"] is True
    assert scrub["scrub_ref"], "the provider's reference is what makes the claim checkable"


def test_the_runbook_prints_the_headers_the_api_actually_accepts() -> None:
    """`runbooks/dnc-complaint.md` §6 is what an operator types mid-incident, so the
    literals in it are pinned here — the discipline `spend_cap_confirmation` already has.
    Renaming a confirmation must fail a test, not leave a runbook telling somebody to
    send a header the API refuses."""
    runbook = Path("runbooks/dnc-complaint.md").read_text(encoding="utf-8")
    assert f"X-Confirm-Action: {SUPPRESS_GLOBALLY_CONFIRMATION}" in runbook
    # The release header is PARAMETRISED, so the runbook has to print the `{entry_id}`
    # placeholder too. Asserting only the stem would keep passing against the pre-D-141
    # curl, which the API now refuses — the exact failure this test exists to prevent.
    # The join is read off the builder rather than respelled here, so a change to it
    # fails this assertion instead of being mirrored into it.
    sample = uuid.UUID("00000000-0000-7000-8000-0000000000ff")
    parametrised = release_globally_confirmation(sample).replace(str(sample), "{entry_id}")
    assert f"X-Confirm-Action: {parametrised}" in runbook
    assert "POST /v1/ops/dnc/global" in runbook


async def test_both_operator_routes_are_mounted() -> None:
    """A route nobody mounted is the defect this whole slice is about, in miniature:
    everything below `scope='global'` was built and nothing could reach it."""
    paths = {route.path for route in iter_api_routes(app)}
    assert "/v1/ops/dnc/global" in paths
    assert "/v1/ops/dnc/global/{entry_id}" in paths
    assert "/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/preference-scrub" in paths


# --------------------------------------------------------------- what is NOT closed


#: Rule names SEC-COMP §3's DNC bullet promises that this slice does NOT enforce.
#:
#: Asserted as an equality rather than written in a comment, for the reason D-103's
#: `KNOWN_OPEN_COPIES` is: a comment describing a gap outlives the gap and quietly
#: becomes false, while an equality fails the day somebody closes one — so the entry
#: cannot survive its own defect.
#:
#: The recorded `scrub_ref` is taken ON TRUST. `record_scrub_run` stores what an
#: operator read off the provider's portal, and a typo, a stale paste or an invention is
#: indistinguishable from a real reference — so what the gate proves is that SOMEBODY
#: accountable asserted a scrub, not that one happened. Closing it needs an
#: access-provider DLT API to query the reference against, which is the same EXTERNAL
#: blocker as running the scrub at all: a Registered Telemarketer relationship with an
#: access provider (R-01, `platform_state.tm_registration_status`). The controls that do
#: hold meanwhile are step-up confirmation, an `audit_log` entry naming the operator,
#: and the reference being stored so a human can check it on the portal.
#:
#: Asserted as an equality rather than written in a comment, the way D-103 recorded
#: `KNOWN_OPEN_COPIES`: a comment about a gap outlives the gap and quietly becomes
#: false, while this fails the day somebody makes a provider call from this module — so
#: the entry cannot survive its own defect.
UNVERIFIED_SCRUB_EVIDENCE = ("scrub_ref recorded from an operator, never queried back",)


def test_the_recorded_scrub_reference_is_still_taken_on_trust() -> None:
    """The gap above, pinned so it cannot outlive itself."""
    import inspect

    source = inspect.getsource(preference_scrub)
    assert UNVERIFIED_SCRUB_EVIDENCE == ("scrub_ref recorded from an operator, never queried back",)
    for client in ("httpx", "requests", "aiohttp", "urllib"):
        assert f"import {client}" not in source, (
            f"{client} appears in preference_scrub: if the reference is now verified "
            "against a provider, delete UNVERIFIED_SCRUB_EVIDENCE and this test"
        )
    # And the module still names the external blocker, so the next reader inherits WHY
    # rather than only THAT.
    assert "Registered Telemarketer relationship" in (preference_scrub.__doc__ or "")


# --- the refusal paths D-107 shipped and the ratchet caught uncovered -----------------
#
# WHY THIS SECTION EXISTS. D-107 raised `compliance-gate`'s uncovered count 9 → 21, and
# D-29's rule is that the number only ever shrinks: new untested branches on a hard-rule-5
# surface get covered, never waived. Every branch below is a REFUSAL, which is the half of
# a compliance gate that matters — the happy path is exercised by every other test in this
# file, and a refusal nothing drives is a refusal nobody knows still works.


async def test_a_global_add_of_nothing_dialable_writes_no_row_and_says_so() -> None:
    """All-malformed input must be counted, not silently succeed as an empty write.

    The early return exists so `add_global_numbers` never issues an INSERT with no rows,
    and the operator gets `malformed` rather than a cheerful `added=0` that reads like
    "these were already suppressed".
    """
    async with untenanted_session() as session:
        result = await dnc.add_global_numbers(
            session, raw_numbers=["not-a-number", "12", ""], source="regulator"
        )
    assert (result.added, result.already_suppressed, result.malformed) == (0, 0, 3)


async def test_a_tenant_cannot_lift_a_global_suppression_through_the_ops_helper() -> None:
    """RLS refusing the DELETE looks exactly like a missing row, and must be reported as
    one rather than as success.

    This is the branch the function's own comment names. A tenant session CAN read a
    global row — it must, or a nationally suppressed number would still be dialled — so
    the SELECT finds it and only the DELETE is refused. Reporting `rowcount == 0` as a
    completed removal would tell an operator a regulator instruction had been lifted
    while it was still in force.
    """
    tenant_id, _agent_id, _slug, _token = await _tenant()
    number = _number()
    async with untenanted_session() as session:
        await dnc.add_global_numbers(session, raw_numbers=[number], source="regulator")
    async with untenanted_session() as session:
        entry_id = (
            await session.execute(
                text("SELECT id FROM dnc_list WHERE phone_e164 = :p AND tenant_id IS NULL"),
                {"p": number},
            )
        ).scalar_one()

    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as caught:
            await dnc.remove_global_entry(session, entry_id=entry_id)
    assert caught.value.code == "not_found"

    # And the suppression is still standing — the point of refusing.
    async with untenanted_session() as session:
        still_there = (
            await session.execute(
                text("SELECT count(*) FROM dnc_list WHERE id = :i"), {"i": entry_id}
            )
        ).scalar_one()
    assert still_there == 1


def test_a_scrub_that_was_never_recorded_is_never_current() -> None:
    """`is_current` is what the gate asks. It must answer False for the two absences —
    no run at all, and a run with no expiry — rather than raising on the None."""
    assert preference_scrub.NOT_SCRUBBED.is_current is False
    assert preference_scrub.ScrubState(recorded=True, expires_at=None).is_current is False


async def test_a_scrub_cannot_be_recorded_against_a_campaign_that_will_never_dial() -> None:
    """A scrub of a finished campaign's list records nothing true.

    The refusal is named rather than a 404 because the campaign DOES exist and the
    operator is not lost — they are recording evidence against the wrong row, and
    `campaign_not_dialable` is the sentence that tells them which.
    """
    tenant_id, agent_id, _slug, _token = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET status = 'completed' WHERE id = :c"), {"c": campaign_id}
        )
        with pytest.raises(ProblemError) as caught:
            await record_test_scrub(session, campaign_id)
    assert caught.value.code == "campaign_not_dialable"


async def test_a_naive_scrub_timestamp_is_read_as_utc_rather_than_raising() -> None:
    """UTC in the DB, IST at the edge. A naive instant reaching the comparison against an
    aware `now()` would raise `TypeError` out of a compliance write — so the coercion is
    pinned, and pinned to UTC specifically, because guessing IST here would silently date
    a scrub five and a half hours early and expire it a day sooner than the provider said.
    """
    tenant_id, agent_id, _slug, _token = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    naive = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)
    async with tenant_session(tenant_id) as session:
        recorded = await record_test_scrub(session, campaign_id, scrubbed_at=naive)
    assert recorded.state.scrubbed_at is not None
    assert recorded.state.scrubbed_at.tzinfo is not None
    assert recorded.state.scrubbed_at == naive.replace(tzinfo=UTC)


async def test_a_scrub_dated_in_the_future_is_refused() -> None:
    """A scrub records something a provider ALREADY did.

    Accepting a future timestamp would mint an artefact whose expiry outlives the day it
    claims to cover — the one way to make `national_dnd_scrub_expired` unreachable, and
    therefore the one way to dial an unscrubbed list past midnight with the gate green.
    """
    tenant_id, agent_id, _slug, _token = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as caught:
            await record_test_scrub(
                session, campaign_id, scrubbed_at=datetime.now(UTC) + timedelta(hours=2)
            )
    assert caught.value.code == "preference_scrub_in_the_future"


async def test_the_database_itself_refuses_a_tenants_delete_of_a_global_row() -> None:
    """The hole `e4f2a86b13d7` closes, asserted at the table rather than at the route.

    `WITH CHECK` is not evaluated on DELETE — Postgres consults `USING` alone — and
    `dnc_list`'s `USING` admits `tenant_id IS NULL` so a tenant can READ a national
    suppression. Before the RESTRICTIVE `FOR DELETE` policy, that same clause let a tenant
    session DELETE one: measured at `DELETE 1`, one client lifting a regulator instruction
    for every other client.

    Asserted with raw SQL and not through `remove_global_entry`, deliberately. That
    function's `rowcount != 1` guard was written believing RLS refused the delete, and an
    application `if` cannot constrain psql, a future caller, or the next function somebody
    writes. Hard rule 1 says RLS is the enforcement; this is the test that says so too.
    """
    tenant_id, _agent_id, _slug, _token = await _tenant()
    number = _number()
    async with untenanted_session() as session:
        await dnc.add_global_numbers(session, raw_numbers=[number], source="regulator")

    async with tenant_session(tenant_id) as session:
        # The tenant CAN see it — that half must not regress, or a suppressed number
        # becomes dialable.
        visible = (
            await session.execute(
                text("SELECT count(*) FROM dnc_list WHERE phone_e164 = :p"), {"p": number}
            )
        ).scalar_one()
        assert visible == 1, "a tenant must still READ global suppressions"

        deleted = await session.execute(
            text("DELETE FROM dnc_list WHERE phone_e164 = :p"), {"p": number}
        )
        assert deleted.rowcount == 0, (
            "a tenant session deleted a platform-wide suppression: the FOR DELETE "
            "restrictive policy is missing and WITH CHECK does not cover this verb"
        )

    async with untenanted_session() as session:
        survives = (
            await session.execute(
                text("SELECT count(*) FROM dnc_list WHERE phone_e164 = :p"), {"p": number}
            )
        ).scalar_one()
    assert survives == 1


async def test_ops_can_still_lift_a_global_suppression() -> None:
    """The other direction, so the fix above is a narrowing and not a wall. An operator
    session carries no tenant GUC and must still be able to withdraw an instruction that
    was itself withdrawn."""
    number = _number()
    async with untenanted_session() as session:
        await dnc.add_global_numbers(session, raw_numbers=[number], source="regulator")
        entry_id = (
            await session.execute(
                text("SELECT id FROM dnc_list WHERE phone_e164 = :p AND tenant_id IS NULL"),
                {"p": number},
            )
        ).scalar_one()
        assert await dnc.remove_global_entry(session, entry_id=entry_id) == "regulator"
        gone = (
            await session.execute(
                text("SELECT count(*) FROM dnc_list WHERE id = :i"), {"i": entry_id}
            )
        ).scalar_one()
    assert gone == 0
