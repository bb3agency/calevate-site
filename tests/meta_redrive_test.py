"""A Meta lead refused for want of a token, recovered after Meta stopped retrying.

`tests/crm_egress_known_gaps_test.py` recorded this and refused to half-build it. The
defect it recorded: a verified leadgen notification we cannot read is written `failed`
against its `leadgen_id`, and `claim_inbox_event` re-claims a failed row by CAS — so
attaching a Page access token DOES recover the lead, but only while Meta is still
redelivering. Meta gives up after ~36 hours and unsubscribes the Page. After that the
`leadgen_id` was durable and unreachable: no route, no job and no screen acted on a
recorded refusal. The lead was not lost from the DATABASE, it was lost from the PRODUCT.

What is under test, in the order it matters:

1. **The lead comes back**, through `POST /v1/lead-sources/{id}/meta/redrive`, with Meta
   long since unsubscribed — nothing here posts a second notification.
2. **It comes back through the path production runs.** The claim is the SAME inbox row
   (not a second one), the capability selector is the same, and — the one that must never
   be reimplemented — the compliance gate and the consent branch are the same. A lead
   whose form said "no" is recovered and NOT dialled.
3. **Only a recoverable refusal is a candidate.** A lead Meta deleted, a lead with no
   dialable number and a lead that already landed are all left exactly where they are.
4. **Hard rule 1**: another tenant's lead source is a 404 and their rows are untouched.
5. **The affordance exists.** The activity view says WHICH rows are recoverable and which
   source they belong to, because a route with no affordance is the half-wired feature
   the gaps registry exists to refuse.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, get_args

import pytest
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import GRANTED_PERMISSIONS, Permission
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.ingest import meta
from apps.api.ingest.routes import ingest_activity, meta_redrive
from apps.api.ingest.service import NO_CONSENT_FIELD_RULE
from sqlalchemy import text
from starlette.requests import Request
from tests.meta_lead_ads_test import (
    CONSENT_QUESTION,
    _client,
    _daytime,  # noqa: F401 — the autouse clock fixture; the gate refuses to dial at night
    _notification,
    _retriever,
    _signed,
    _tenant_with_meta_source,
    _wire,
)

REDRIVE_PERMISSION = "org:manage"


def _principal(tenant_id: uuid.UUID) -> Principal:
    return Principal(
        realm="client",
        user_id=uuid.uuid4(),
        clerk_user_id="u",
        tenant_id=tenant_id,
        role="owner",
        impersonating=False,
    )


def _request() -> Request:
    """`write_audit` reads `request.client` for the audited IP, so the route takes a real
    Request rather than a stub that happens to have the attribute today."""
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/lead-sources/redrive",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 4321),
        }
    )


async def _deliver(webhook_id: uuid.UUID, leadgen_id: str) -> int:
    """One signed leadgen notification, exactly as Meta sends it."""
    raw, headers = _signed(_notification(leadgen_id=leadgen_id))
    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/meta/{webhook_id}", content=raw, headers=headers
        )
    return response.status_code


async def _inbox(webhook_id: uuid.UUID) -> list[tuple[Any, ...]]:
    async with untenanted_session() as session:
        return list(
            (
                await session.execute(
                    text(
                        "SELECT event_key, status, last_error, duplicate_count "
                        "FROM webhook_inbox_events WHERE provider = :p ORDER BY created_at"
                    ),
                    {"p": meta.inbox_provider(webhook_id)},
                )
            ).all()
        )


async def _leads(tenant_id: uuid.UUID) -> list[tuple[Any, ...]]:
    async with tenant_session(tenant_id) as session:
        return list(
            (
                await session.execute(
                    text("SELECT phone_e164, name, data FROM leads ORDER BY created_at")
                )
            ).all()
        )


async def _call_count(tenant_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int((await session.execute(text("SELECT count(*) FROM calls"))).scalar() or 0)


async def _redrive(tenant_id: uuid.UUID, webhook_id: uuid.UUID) -> Any:
    return await meta_redrive(webhook_id, _request(), _principal(tenant_id))


# ------------------------------------------------------------------ the permission


def test_the_permission_the_route_declares_is_one_a_role_actually_holds() -> None:
    """D-119 shipped a typo'd permission string: a route that reads as guarded and is a
    403 for the entire population. The string is checked against BOTH registries because
    a name in the type that no role holds fails exactly the same way.

    `tests/rbac_registry_test.py` walks every route for this; this assertion is here so
    that the failure names THIS route when it is this route that broke.
    """
    assert REDRIVE_PERMISSION in get_args(Permission)
    assert REDRIVE_PERMISSION in GRANTED_PERMISSIONS


# --------------------------------------------------- the lead comes back, correctly


async def test_a_lead_refused_for_want_of_a_token_is_recovered_long_after_meta_gave_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole defect. Meta delivers once into a deployment with no token, records the
    refusal, and — as far as this test is concerned — never comes back. The token is
    attached; the button is pressed; the lead exists."""
    tenant_id, _, webhook_id = await _tenant_with_meta_source(
        mapping={"phone": "phone_number", "name": "full_name"}
    )
    _wire(monkeypatch, None, reason=meta.NO_TOKEN_REASON)
    assert await _deliver(webhook_id, "900000001000001") == 200
    assert await _leads(tenant_id) == [], "nothing was readable, so nothing was invented"
    assert [(r[1], r[2]) for r in await _inbox(webhook_id)] == [("failed", meta.NO_TOKEN_REASON)]

    # The operator attaches the Page access token. Nothing else changes, and Meta is not
    # asked for anything — the notification is never re-sent in this test.
    _wire(monkeypatch, _retriever(phone="9876511001", name="Recovered Ravi", consent=None))

    result = await _redrive(tenant_id, webhook_id)

    assert (result.candidates, result.accepted, result.refused) == (1, 1, 0)
    leads = await _leads(tenant_id)
    assert len(leads) == 1
    assert leads[0][0] == "+919876511001"
    assert leads[0][1] == "Recovered Ravi"


async def test_the_redrive_reuses_the_recorded_claim_instead_of_opening_a_second_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One `leadgen_id`, one inbox row, before and after.

    This is the assertion that the row's own `payload_hash` is what re-claims it. A
    `LeadNotification` rebuilt from the row carries the id and no provenance, so hashing
    it would present a DIFFERENT digest for the same key — which `claim_inbox_event`
    correctly reads as a doctored replay and refuses with `webhook_payload_mismatch`.
    """
    tenant_id, _, webhook_id = await _tenant_with_meta_source()
    _wire(monkeypatch, None, reason=meta.NO_TOKEN_REASON)
    await _deliver(webhook_id, "900000001000010")
    _wire(monkeypatch, _retriever(phone="9876511010", name="One Row", consent=None))

    await _redrive(tenant_id, webhook_id)

    rows = await _inbox(webhook_id)
    assert len(rows) == 1, "the re-drive opened a second claim for one lead"
    assert rows[0][0] == "900000001000010"
    assert rows[0][1] == "processed", "the row the refusal was recorded on is now done"


async def test_a_second_press_finds_nothing_left_and_rings_nobody_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The selection is `status = 'failed'`, so a recovered lead stops being a candidate.
    A button that re-dialled its own successes on every press is worse than no button."""
    tenant_id, _, webhook_id = await _tenant_with_meta_source(
        mapping={"phone": "phone_number", "name": "full_name"}
    )
    _wire(monkeypatch, None, reason=meta.NO_TOKEN_REASON)
    await _deliver(webhook_id, "900000001000020")
    _wire(monkeypatch, _retriever(phone="9876511020", name="Once Only", consent=None))

    first = await _redrive(tenant_id, webhook_id)
    calls_after_first = await _call_count(tenant_id)
    second = await _redrive(tenant_id, webhook_id)

    assert (first.candidates, first.accepted) == (1, 1)
    assert (second.candidates, second.accepted) == (0, 0)
    assert len(await _leads(tenant_id)) == 1
    assert await _call_count(tenant_id) == calls_after_first


# ---------------------------------------------------------------- hard rule 5 holds


async def test_a_recovered_lead_whose_form_said_no_is_saved_and_never_dialled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate is the one thing that must not have two implementations (hard rule 5,
    D-117's `no_consent`). Tapping a lead ad handed a number to META, not permission for
    a voice agent to ring it — and a lead recovered on a Tuesday must be judged by the
    rule the Monday lead was judged by, because it is literally the same call."""
    tenant_id, _, webhook_id = await _tenant_with_meta_source(
        mapping={
            "phone": "phone_number",
            "name": "full_name",
            "consent_field": CONSENT_QUESTION,
        }
    )
    _wire(monkeypatch, None, reason=meta.NO_TOKEN_REASON)
    await _deliver(webhook_id, "900000001000030")
    _wire(monkeypatch, _retriever(phone="9876511030", name="Said No", consent="no"))

    result = await _redrive(tenant_id, webhook_id)

    assert result.accepted == 1, "the lead is kept — it is the DIAL that is refused"
    assert len(await _leads(tenant_id)) == 1
    assert await _call_count(tenant_id) == 0, "a re-driven lead reached a phone unasked"


async def test_a_recovered_lead_that_may_be_called_is_dialled_like_any_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other arm, so the refusal above cannot be "the re-drive never dials"."""
    tenant_id, _, webhook_id = await _tenant_with_meta_source(
        mapping={
            "phone": "phone_number",
            "name": "full_name",
            "consent_field": CONSENT_QUESTION,
        }
    )
    _wire(monkeypatch, None, reason=meta.NO_TOKEN_REASON)
    await _deliver(webhook_id, "900000001000031")
    _wire(monkeypatch, _retriever(phone="9876511031", name="Said Yes", consent="yes"))

    await _redrive(tenant_id, webhook_id)

    assert await _call_count(tenant_id) == 1


# --------------------------------------------------------- what is NOT a candidate


async def test_a_refusal_a_retry_cannot_fix_is_left_exactly_where_it_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`meta.REDRIVABLE_REASONS` is the whole selection. A lead with no answers at all is
    a verdict about the client's FORM, and re-running it would spend a Graph call to
    reach the same refusal — while making the client believe something was retried."""
    tenant_id, _, webhook_id = await _tenant_with_meta_source()
    _wire(monkeypatch, _retriever(phone="", name="", consent=None))
    await _deliver(webhook_id, "900000001000040")
    assert [(r[1], r[2]) for r in await _inbox(webhook_id)] == [("failed", meta.NO_ANSWERS_REASON)]

    result = await _redrive(tenant_id, webhook_id)

    assert result.candidates == 0
    assert [(r[1], r[2]) for r in await _inbox(webhook_id)] == [
        ("failed", meta.NO_ANSWERS_REASON)
    ], "a permanent verdict was re-run and re-recorded"


async def test_a_transient_graph_failure_leaves_the_row_recoverable_for_the_next_press(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Graph timing out during a re-drive is not a verdict about the lead. The row stays
    `failed` on the reason it already carried, so the next press finds it again — and the
    count says `deferred` rather than pretending it was refused."""
    tenant_id, _, webhook_id = await _tenant_with_meta_source()
    _wire(monkeypatch, None, reason=meta.NO_TOKEN_REASON)
    await _deliver(webhook_id, "900000001000050")

    transient = _retriever(phone="9876511050", name="Later", consent=None)
    monkeypatch.setattr(
        transient,
        "fetch_answers",
        lambda **_kwargs: _transient(),
    )
    _wire(monkeypatch, transient)
    deferred = await _redrive(tenant_id, webhook_id)

    assert (deferred.candidates, deferred.deferred, deferred.accepted) == (1, 1, 0)
    assert await _leads(tenant_id) == []

    # Graph recovers, the client presses again, and the lead lands.
    _wire(monkeypatch, _retriever(phone="9876511050", name="Later", consent=None))
    assert (await _redrive(tenant_id, webhook_id)).accepted == 1
    assert len(await _leads(tenant_id)) == 1


async def _transient() -> meta.RetrievedLead:
    return meta.RetrievedLead(
        status=meta.RetrievalStatus.TRANSIENT, reason="meta_graph_unavailable"
    )


# ------------------------------------------------------------------ hard rule 1


async def test_another_tenants_lead_source_is_a_404_and_their_leads_stay_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`webhook_inbox_events` has NO `tenant_id` — it is keyspaced by provider — so the
    only thing between one tenant and another's recorded leads is that `load_config` runs
    under RLS and resolves nothing. Worth pinning precisely because the table cannot
    defend itself."""
    mine, _, my_source = await _tenant_with_meta_source()
    theirs, _, their_source = await _tenant_with_meta_source()
    _wire(monkeypatch, None, reason=meta.NO_TOKEN_REASON)
    await _deliver(their_source, "900000001000060")
    _wire(monkeypatch, _retriever(phone="9876511060", name="Not Yours", consent=None))

    with pytest.raises(ProblemError) as excinfo:
        await _redrive(mine, their_source)

    assert excinfo.value.as_problem()["status"] == 404
    assert [(r[1], r[2]) for r in await _inbox(their_source)] == [
        ("failed", meta.NO_TOKEN_REASON)
    ], "a neighbour re-drove leads that were never theirs"
    assert await _leads(theirs) == []
    # And the caller's own source, which has nothing recorded, is a legitimate no-op.
    assert (await _redrive(mine, my_source)).candidates == 0


# ------------------------------------------------------------------- it is audited


async def test_the_act_is_audited_with_a_count_and_no_meta_lead_id(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Audited into the hash-chained ledger against the lead source, by a named actor.

    The summary is not a COLUMN — `write_audit` puts it on the log stream — so it is
    asserted where it lands. A 15-digit `leadgen_id` is phone-shaped, the redactor masks
    it, and a field that always reads `[phone]` is worse than a count: the ids stay
    durable in `webhook_inbox_events.event_key`, which is the row this just re-drove.
    """
    tenant_id, _, webhook_id = await _tenant_with_meta_source()
    _wire(monkeypatch, None, reason=meta.NO_TOKEN_REASON)
    await _deliver(webhook_id, "900000001000070")
    _wire(monkeypatch, _retriever(phone="9876511070", name="Audited", consent=None))
    principal = _principal(tenant_id)

    with caplog.at_level(logging.INFO, logger="apps.api.compliance.audit"):
        await meta_redrive(webhook_id, _request(), principal)

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT object_type, object_id, actor_id, actor_type, ip FROM audit_log "
                    "WHERE action = 'lead_source.meta_redriven' AND object_id = :w"
                ),
                {"w": str(webhook_id)},
            )
        ).all()
    assert len(rows) == 1, "the act was not recorded in the ledger"
    assert rows[0][0] == "inbound_webhook"
    assert rows[0][1] == str(webhook_id)
    assert (str(rows[0][2]), rows[0][3], rows[0][4]) == (
        str(principal.user_id),
        "user",
        "127.0.0.1",
    )

    summaries = [r for r in caplog.records if r.getMessage() == "audit"]
    assert [getattr(r, "candidates", None) for r in summaries] == ["1"]
    assert "900000001000070" not in json.dumps(
        {k: str(v) for k, v in vars(summaries[0]).items() if not k.startswith("_")}
    ), "the Meta lead id reached the log stream through the audit summary"


# ------------------------------------------------------- the affordance, server side


async def test_the_activity_view_says_which_leads_are_recoverable_and_from_where(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Half of this feature is a route; the other half is a screen able to offer it. The
    view has to answer both questions a button needs — IS this row recoverable, and WHICH
    source would recover it — from the server, because a console comparing `error`
    against its own copy of the reason list would offer a button the route will not act
    on the day the list changes.
    """
    tenant_id, _, recoverable_source = await _tenant_with_meta_source()
    _wire(monkeypatch, None, reason=meta.NO_TOKEN_REASON)
    await _deliver(recoverable_source, "900000001000080")
    # A refusal on the same account that is NOT recoverable: the form had no answers.
    _wire(monkeypatch, _retriever(phone="", name="", consent=None))
    await _deliver(recoverable_source, "900000001000081")

    async with tenant_session(tenant_id) as session:
        activity = await ingest_activity(session, 50, _principal(tenant_id))

    by_key = {item.event_key: item for item in activity.items}
    recoverable = by_key["900000001000080"]
    assert recoverable.outcome == "rejected"
    assert recoverable.recoverable is True
    assert recoverable.lead_source_id == recoverable_source
    assert by_key["900000001000081"].recoverable is False, (
        "a permanent verdict was offered as recoverable"
    )


async def test_a_recovered_row_stops_being_offered_as_recoverable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The flag is derived from the row's live status, not from the reason it once
    carried — a button that stayed lit after the work was done would be pressed again."""
    tenant_id, _, webhook_id = await _tenant_with_meta_source()
    _wire(monkeypatch, None, reason=meta.NO_TOKEN_REASON)
    await _deliver(webhook_id, "900000001000090")
    _wire(monkeypatch, _retriever(phone="9876511090", name="Done", consent=None))
    await _redrive(tenant_id, webhook_id)

    async with tenant_session(tenant_id) as session:
        activity = await ingest_activity(session, 50, _principal(tenant_id))

    item = next(i for i in activity.items if i.event_key == "900000001000090")
    assert (item.outcome, item.recoverable) == ("accepted", False)


async def test_a_shared_secret_refusal_is_never_offered_a_meta_redrive() -> None:
    """The `ingest:` keyspace has the whole payload behind it and nothing to re-fetch, so
    there is no re-drive to offer — and the Meta route would not select it anyway. The
    flag has to say so, or the screen lights a button that answers zero candidates."""
    tenant_id, _, _ = await _tenant_with_meta_source(source="website_form")
    async with tenant_session(tenant_id) as session:
        webhook_id = (
            await session.execute(text("SELECT id FROM inbound_webhooks LIMIT 1"))
        ).scalar()
        await session.execute(
            text(
                "INSERT INTO webhook_inbox_events (id, provider, event_key, payload_hash, "
                "status, last_error, created_at, updated_at) VALUES (gen_random_uuid(), "
                ":p, 'digest-abc', 'digest-abc', 'failed', :e, now(), now())"
            ),
            {"p": f"ingest:{webhook_id}", "e": meta.NO_TOKEN_REASON},
        )
        activity = await ingest_activity(session, 50, _principal(tenant_id))

    item = next(i for i in activity.items if i.event_key == "digest-abc")
    assert item.recoverable is False


# ------------------------------------------------------------------ the consent rule


def test_the_consent_rule_the_redrive_inherits_is_the_one_ingest_raises() -> None:
    """One spelling of one rule. The re-drive adds no vocabulary of its own — it cannot,
    because it calls `_absorb_leadgen`, which calls `ingest_lead`."""
    assert meta.NO_CONSENT_FIELD_RULE == NO_CONSENT_FIELD_RULE


def test_the_redrivable_reasons_are_capability_refusals_and_nothing_else() -> None:
    """Every entry has to be a state ATTACHING A CREDENTIAL undoes. A verdict about the
    lead in this tuple would make the button re-run refusals forever."""
    assert set(meta.REDRIVABLE_REASONS) == {meta.NO_TOKEN_REASON, meta.NO_RETRIEVER_REASON}
    assert meta.NO_ANSWERS_REASON not in meta.REDRIVABLE_REASONS
