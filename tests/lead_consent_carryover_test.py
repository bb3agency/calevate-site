"""A lead ad fill is not permission to be telephoned — and the refusal has to LAST.

`ingest.service.ingest_lead` gets this right at the front door: a Meta lead-ad fill on a
form with no opt-in question is saved and NOT dialled, recorded on the timeline as
`no_consent_field_configured` (`meta_lead_ads_test` pins that). This file asks the next
question, which is the one that decides whether the front door matters: **once that lead
is a row in the CRM, does anything still know it was never allowed to be called?**

It does not, today, and this file is the evidence rather than the assertion. The refusal
lives in ONE place — a `lead_events` row of type `note` — which the timeline renders as
prose for a human and which no dial path reads. `compliance.service.check_dispatch` — the
gate every dispatcher goes through — asks about the platform halt, the account, the
agent, KYC, the spend cap, the credits, the calling hours and the DNC list. It does not
ask whether this person ever consented, because there is nothing per-lead for it to ask.

So the two tests below are opposite in kind and that is deliberate:

* `test_the_ingest_path_refuses_the_dial` re-states the property that HOLDS, from this
  file's own fixture, so the gap test below cannot be read as "consent is not enforced
  anywhere".
* `test_the_manual_dial_button_does_not_know_the_lead_was_consent_blocked` asserts the
  CURRENT behaviour with an equality, exactly like `reliability_known_gaps_test`: it is
  a registry entry that fails the day somebody closes the gap, so the gap cannot be
  closed and left undocumented, and it cannot rot into a claim nobody checks.

WHY IT IS NOT CLOSED IN THIS CHANGE. The durable half belongs in `consent_ledger` — the
append-only, RLS'd, DPDP-shaped table that already exists with `purpose='callback'`,
`status='declined'` and `consent_source='web_form_optin'` in its CHECK constraints, i.e.
it was designed for exactly this row. The READ half belongs in
`compliance.service.check_dispatch`, so that every dial path inherits it at once rather
than the leads screen growing its own answer and the campaign dispatcher keeping the old
one. `apps/api/compliance/**` and `apps/workers/dispatcher.py` are outside this slice's
write boundary, and a write with no reader is the half-wired feature CLAUDE.md forbids —
writing the ledger row here alone would make the product look consent-aware while
dialling exactly as before.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from apps.api.compliance.service import check_dispatch
from apps.api.db.session import tenant_session
from apps.api.ingest import meta
from sqlalchemy import text
from tests.meta_lead_ads_test import (
    _client,
    _notification,
    _retriever,
    _signed,
    _tenant_with_meta_source,
    _wire,
)

#: HOW IT WAS CLOSED (D-117), kept so the shape of the fix travels with the assertions.
CLOSED_BY = (
    "1. `ingest.service._record_dial_consent_declined` writes a `consent_ledger` row on "
    "both refusal branches — `purpose='callback', status='declined', "
    "consent_source='web_form_optin'` — keyed on the PHONE, because the ledger's unit is "
    "a person and the same person can arrive twice as two lead rows. 2. "
    "`compliance.service.check_dispatch` grows a `no_consent` rule reading the LATEST "
    "row for `(tenant_id, phone_e164, purpose='callback')` and refusing on any status "
    "outside `granted`, so the leads-screen button, the campaign dispatcher and the "
    "ingest path inherit ONE answer. Absence stays permissive: most dialable leads have "
    "no ledger row at all."
)


async def _consent_blocked_lead() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, str]:
    """A real Meta lead-ad fill on a form that asked no permission question.

    Built through the receiver rather than by INSERT: the property under test is what
    the shipped ingest path leaves behind, and a hand-written `leads` row would prove
    something about this file instead.
    """
    tenant_id, agent_id, webhook_id = await _tenant_with_meta_source()
    monkey = pytest.MonkeyPatch()
    try:
        _wire(monkey, _retriever(phone="9876504444", name="Unconsented", consent=None))
        raw, headers = _signed(_notification(leadgen_id="900000000000900"))
        async with _client() as http:
            ack = await http.post(
                f"/hooks/v1/ingest/meta/{webhook_id}", content=raw, headers=headers
            )
    finally:
        monkey.undo()
    assert ack.json()["accepted"] == 1, ack.text

    async with tenant_session(tenant_id) as session:
        # Scoped to THIS fill's number. An unscoped `SELECT id FROM leads` picks an
        # arbitrary row once the database holds more than one — which made a sabotage
        # round report the same two failures for four different breaks, because the
        # baseline was never green. A fixture that can pick the wrong row makes every
        # assertion built on it meaningless.
        lead_id = (
            await session.execute(
                text("SELECT id FROM leads WHERE phone_e164 = :p"), {"p": "+919876504444"}
            )
        ).scalar()
    assert lead_id is not None
    return tenant_id, agent_id, uuid.UUID(str(lead_id)), "+919876504444"


async def test_the_ingest_path_refuses_the_dial_and_says_why_on_the_timeline() -> None:
    """The property that HOLDS. Asserted here so the gap below is read for what it is."""
    tenant_id, _, lead_id, _ = await _consent_blocked_lead()
    async with tenant_session(tenant_id) as session:
        calls = (await session.execute(text("SELECT count(*) FROM calls"))).scalar()
        note = (
            await session.execute(
                text(
                    "SELECT payload FROM lead_events WHERE lead_id = :lid AND type = 'note' "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"lid": lead_id},
            )
        ).scalar()
    assert calls == 0, "the receiver dialled a person who never said we could"
    assert note == {"kind": "blocked", "rule": meta.NO_CONSENT_FIELD_RULE}


async def test_the_manual_dial_button_now_refuses_a_consent_blocked_lead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gap this file recorded, now closed and pinned the other way round (D-117).

    `POST /v1/leads/{id}/call` is the "Call this lead" button on the Leads screen. It
    always ran the full compliance gate — DNC, calling hours, spend cap, platform halt —
    which is why this was a gap and not a hole. What it could not apply was the one
    refusal this lead had already earned an hour earlier at the front door, because that
    refusal was prose on a timeline instead of a fact in `consent_ledger`.

    The assertions below are deliberately BOTH halves: the route refuses, AND no call row
    exists. A test that only read the response body would keep passing if the refusal
    became a 200 with a sad message beside a placed call.
    """
    from datetime import UTC, datetime, timedelta

    # The gate refuses at night, and this test is not about the calling-hours rule.
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)

    tenant_id, agent_id, lead_id, _phone = await _consent_blocked_lead()
    token, slug = await _owner_session(tenant_id)

    async with _client() as http:
        response = await http.post(
            f"/v1/leads/{lead_id}/call",
            json={"agent_id": str(agent_id)},
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "blocked", (
        "a person who was never asked for permission was dialled from the leads screen"
    )
    assert body["blocked_rule"] == "no_consent", (
        f"refused, but under the wrong rule — an operator reading {body['blocked_rule']!r} "
        "would go looking at the DNC list or the calling hours"
    )

    async with tenant_session(tenant_id) as session:
        dialled = (
            await session.execute(
                text("SELECT count(*) FROM calls WHERE lead_id = :l"), {"l": lead_id}
            )
        ).scalar()
    assert dialled == 0, "the route said blocked and placed the call anyway"


async def test_the_refusal_is_a_durable_fact_about_the_person_not_prose_on_one_lead() -> None:
    """The write half, asserted where it lives rather than through its effect.

    Keyed on the phone rather than the lead id, which is the part that survives the
    obvious future mistake: the same person arriving a second time as a new lead row from
    a different form must still be refused, and a refusal attached to lead #1 would be
    silently undone by lead #2.
    """
    tenant_id, _agent_id, _lead_id, phone = await _consent_blocked_lead()
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT purpose, status, consent_source FROM consent_ledger "
                    "WHERE phone_e164 = :p ORDER BY captured_at DESC LIMIT 1"
                ),
                {"p": phone},
            )
        ).first()
    assert row is not None, "the front door refused the dial and recorded nothing durable"
    assert tuple(row) == ("callback", "declined", "web_form_optin")


async def test_absence_of_a_consent_row_is_not_a_refusal() -> None:
    """ABSENCE IS NOT A REFUSAL, asserted at the gate where the rule lives.

    Most dialable numbers have no `consent_ledger` row at all — typed in by staff,
    imported from a CSV, or a caller who rang US. Reading silence as `declined` would
    refuse every one of them, which an operator meets as a total outbound outage rather
    than as a rule. This is the case that breaks if somebody later "tightens" the gate
    into requiring a positive grant, so it is pinned rather than assumed.

    Driven through `check_dispatch` rather than through Meta ingest: the property belongs
    to the gate, and routing it through a lead-source fixture would make the test depend
    on that fixture's mapping instead of on the rule.
    """
    tenant_id, agent_id, _webhook_id = await _tenant_with_meta_source()
    async with tenant_session(tenant_id) as session:
        silent = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919876506666"
        )
    assert silent.rule != "no_consent", (
        "a number nobody has recorded an opinion about was refused for want of consent; "
        "every staff-typed and CSV-imported lead in the product is that number"
    )


async def test_a_later_grant_supersedes_an_earlier_decline() -> None:
    """The ledger's own doctrine, applied to this rule: the current state of a
    `(tenant, phone, purpose)` is the LATEST row, and a change of mind is a new row
    rather than an edit of the old one — which is also the only shape hard rule 4 allows.

    Without this the gate would be a one-way door: a person who ticked the box on a
    second, better form could never be called, and the only remedy would be an UPDATE to
    an append-only table.
    """
    tenant_id, agent_id, _webhook_id = await _tenant_with_meta_source()
    phone = "+919876507777"
    async with tenant_session(tenant_id) as session:
        for status in ("declined", "granted"):
            await session.execute(
                text(
                    "INSERT INTO consent_ledger (id, tenant_id, phone_e164, purpose, status, "
                    "consent_source, evidence, captured_at, created_at) VALUES (:id, :tid, :p, "
                    "'callback', :st, 'web_form_optin', CAST(:ev AS jsonb), now() + :off, now())"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "p": phone,
                    "st": status,
                    # `ck_consent_ledger_granted_consent_carries_evidence`: a GRANT must
                    # say how it was obtained. The constraint is the reason this test
                    # cannot fabricate a bare "yes", and it is right to insist.
                    "ev": '{"form": "second-form", "answer": "yes"}'
                    if status == "granted"
                    else None,
                    "off": timedelta(seconds=0 if status == "declined" else 5),
                },
            )
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone
        )
    assert decision.rule != "no_consent", (
        "a person who later gave permission is still refused — the gate reads the "
        "earliest row instead of the latest, and an append-only ledger has no way back"
    )


async def _owner_session(tenant_id: uuid.UUID) -> tuple[str, str]:
    """An owner bearer token for a tenant that already exists.

    `tests.api_security_test._make_tenant` mints its own organization, and this lead is
    in one built by the Meta fixture, so the membership is added here instead.
    """
    user_id = uuid.uuid4()
    clerk_id = f"user_{uuid.uuid4().hex[:12]}"
    from apps.api.db.session import untenanted_session

    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, created_at, updated_at) "
                "VALUES (:id, :cid, :email, now(), now())"
            ),
            {"id": user_id, "cid": clerk_id, "email": f"{clerk_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        # Inside the TENANT session, not the untenanted one: `organizations` is RLS'd,
        # so an untenanted read returns no row and the slug becomes the string "None" —
        # which the auth dependency answers with a 403 that reads like a missing
        # membership rather than like a broken fixture.
        slug = (
            await session.execute(
                text("SELECT slug FROM organizations WHERE id = :t"), {"t": tenant_id}
            )
        ).scalar()
        assert slug, "the fixture could not read its own tenant's slug"
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )
    return f"dev:client:{clerk_id}", str(slug)


__all__: list[Any] = []
