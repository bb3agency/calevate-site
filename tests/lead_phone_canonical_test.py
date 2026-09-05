"""The engine's spelling of a phone number is not a KEY, and it was being used as three.

`leads.phone_e164` is a third of `UNIQUE(tenant_id, phone_e164, agent_id)`, it is what
`compliance.check_dispatch` compares to `dnc_list.phone_e164` with `=`, and it is what a
DPDP erasure matches on (`workers/retention.execute_deletion_request`). Every OTHER
producer of that column already goes through `ingest.normalize_phone` — the webhook path,
`record_call_optout`, `subject_phone`, the DNC and consent routes — and the post-call
pipeline was the one door that let an un-normalised vendor string in
(`engine/bolna.py::_first_e164` returns whatever the vendor printed, from any of four
documented spellings, and normalises none of them).

The three properties measured here are the three things that then break, none of which
raises:

1. one caller spelled two ways becomes TWO leads, so the same customer is in the CRM
   twice and `is_repeat_caller` never flips;
2. the stored number is not the one the DNC list and the consent ledger are keyed on, so
   the dial gate stops protecting that person;
3. the stored number is not the one a data principal's erasure request carries, so their
   rows are unreachable by the one query in this repo with a statutory clock on it.

Scope discipline: every test builds its own tenant and asserts only on rows it created.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.db.session import tenant_session
from apps.api.ingest.service import normalize_phone
from apps.workers import pipeline
from calevate_shared.engine import ExecutionSnapshot
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant

pytestmark = [pytest.mark.rls]


def _snapshot(execution: str, *, from_e164: str) -> ExecutionSnapshot:
    return ExecutionSnapshot(
        engine_call_id=execution,
        direction="inbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        from_e164=from_e164,
        to_e164="+911140000000",
        engine="fake",
    )


async def _leads(tenant_id: uuid.UUID) -> list[str]:
    async with tenant_session(tenant_id) as session:
        return [
            str(row[0])
            for row in (
                await session.execute(text("SELECT phone_e164 FROM leads ORDER BY created_at"))
            ).all()
        ]


async def test_two_spellings_of_one_caller_are_one_lead() -> None:
    """The dedupe key is the CANONICAL number, so the vendor changing its formatting
    between two calls does not split one customer into two CRM rows.

    Both spellings below are the same subscriber. Before the fix the second call inserted
    a second row (the unique constraint saw two different strings), the client's Leads
    screen showed the customer twice, and `is_repeat_caller` — which the repeat-caller
    context injection depends on — stayed false on both.
    """
    tenant_id, agent_id = await _seed_tenant(f"canon_{uuid.uuid4().hex[:10]}")
    digits = f"+9198{uuid.uuid4().int % 100000000:08d}"
    spaced = f"{digits[:3]} {digits[3:8]} {digits[8:]}"
    assert spaced != digits and normalize_phone(spaced) == digits

    first = await pipeline._upsert_lead(
        tenant_id,
        agent_id,
        uuid.uuid4(),
        _snapshot(f"e1_{uuid.uuid4().hex[:8]}", from_e164=digits),
        direction="inbound",
        data={},
        schema_version=1,
    )
    second = await pipeline._upsert_lead(
        tenant_id,
        agent_id,
        uuid.uuid4(),
        _snapshot(f"e2_{uuid.uuid4().hex[:8]}", from_e164=spaced),
        direction="inbound",
        data={},
        schema_version=1,
    )

    assert first == second, "one caller, two spellings, must be one lead"
    assert await _leads(tenant_id) == [digits]

    async with tenant_session(tenant_id) as session:
        repeat = (
            await session.execute(
                text("SELECT call_count, is_repeat_caller FROM leads WHERE id = :lid"),
                {"lid": first},
            )
        ).first()
    assert repeat is not None
    assert (int(repeat[0]), bool(repeat[1])) == (2, True)


async def test_the_stored_number_is_the_one_the_dnc_list_is_keyed_on() -> None:
    """`check_dispatch` compares `phone_e164` to `dnc_list.phone_e164` with `=`, and the
    DNC list is stored normalised. A spaced spelling still starts `+91`, so it passes the
    India-destination check and MISSES the DNC row — the gate looks like it ran and
    protected nobody. Asserted as an equality against the normaliser rather than against a
    literal, so this test moves with the one door and cannot drift from it."""
    tenant_id, agent_id = await _seed_tenant(f"dnc_{uuid.uuid4().hex[:10]}")
    digits = f"+9198{uuid.uuid4().int % 100000000:08d}"
    lead_id = await pipeline._upsert_lead(
        tenant_id,
        agent_id,
        uuid.uuid4(),
        _snapshot(f"e3_{uuid.uuid4().hex[:8]}", from_e164=f"{digits[:3]} {digits[3:]}"),
        direction="inbound",
        data={},
        schema_version=1,
    )
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT phone_e164 FROM leads WHERE id = :lid"), {"lid": lead_id}
            )
        ).scalar()
    assert stored == normalize_phone(str(stored))


async def test_the_call_row_carries_the_number_an_erasure_will_look_for() -> None:
    """`execute_deletion_request` matches `calls.from_e164 = :phone` against the
    normalised number on the request, so an un-normalised call row is unreachable by the
    subject's own erasure. Same door, same reason, other table."""
    tenant_id, agent_id = await _seed_tenant(f"eras_{uuid.uuid4().hex[:10]}")
    digits = f"+9198{uuid.uuid4().int % 100000000:08d}"
    execution = f"e4_{uuid.uuid4().hex[:8]}"
    await pipeline._upsert_call(
        tenant_id,
        agent_id,
        _snapshot(execution, from_e164=f" {digits[:3]}-{digits[3:]} "),
        None,
    )
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT from_e164 FROM calls WHERE engine_call_id = :e"), {"e": execution}
            )
        ).first()
    assert row is not None and row[0] == digits


async def test_a_number_we_cannot_canonicalise_is_kept_rather_than_dropped() -> None:
    """`normalize_phone` returns None rather than guessing a country, and that refusal is
    right — but the alternative HERE is no number at all, which loses the lead its only
    key and the call its only link to a subject. So the raw string survives: this change
    can only ever improve a row, never empty one, and the odd value stays visible in the
    CRM where a human can correct it."""
    tenant_id, agent_id = await _seed_tenant(f"odd_{uuid.uuid4().hex[:10]}")
    unreadable = "0" + f"98{uuid.uuid4().int % 100000000:08d}"  # 11 digits, no country
    assert normalize_phone(unreadable) is None

    lead_id = await pipeline._upsert_lead(
        tenant_id,
        agent_id,
        uuid.uuid4(),
        _snapshot(f"e5_{uuid.uuid4().hex[:8]}", from_e164=unreadable),
        direction="inbound",
        data={},
        schema_version=1,
    )
    assert lead_id is not None
    assert await _leads(tenant_id) == [unreadable]
