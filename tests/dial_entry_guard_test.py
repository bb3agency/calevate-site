"""The refusals guarding the single outbound entry point (`agents.service`).

`dispatch_call` is the ONE function that places an outbound call — the property
`scripts/check_compliance_invariants` asserts — which makes every way it can refuse a
last line of defence shared by the campaign tick, the D-21 button, the callback and the
instant-lead webhook at once. Two of those refusals had never been executed:

- an agent that is **not published** has no engine object to dial, and passing an empty
  ref to the vendor is how a "successful" dispatch becomes a call that never happened
  and a call row that says it did;
- an agent that has been **deleted** must not be loadable at all. `_load_agent` filters
  on `deleted_at IS NULL`, and the row it would otherwise return still carries a live
  `engine_agent_ref` — the vendor object outlives our row, so a missing filter here is a
  call placed by an agent the client believes they removed.

The third is `set_number_dlt_status` answering for a number that is not there: the
number's `series` and registration are what the campaign gate matches a classification
against, so "we recorded it as registered" against nothing is a DLT violation that
looks like paperwork done.

`verify_ingest_secret` is here for the same reason — it is the door in front of the
instant-lead path, whose next step is a dial.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import service as agents_service
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import reset_engine_cache
from apps.api.ingest.service import IngestConfig, verify_ingest_secret
from sqlalchemy import text
from tests.conftest import accept_agreements


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Entry Clinic",
        slug=f"entry-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    # The four agreements, accepted (migration a9d4e70c31b8) — supplied, never assumed
    # away, in the shape `arm_agent_for_outbound` established. Every dial, launch and
    # publish gate now refuses an organisation that has not accepted them, so a fixture
    # without this reports `agreements_not_accepted` in place of the answer under test.
    await accept_agreements(uuid.UUID(str(created["id"])))
    return uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))


async def _calls(tenant_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int((await session.execute(text("SELECT count(*) FROM calls"))).scalar() or 0)


async def test_an_unpublished_agent_cannot_place_a_call_and_the_message_says_what_to_do() -> None:
    """An agent with no `engine_agent_ref` has no engine object behind it. The refusal
    is a business rule with a remediation, not a vendor error: every caller of
    `dispatch_call` surfaces it to somebody who can act on it ("publish the agent"),
    and none of them can distinguish a vendor 4xx from a configuration mistake.

    No call row either — a `queued` row for a dispatch that never reached an engine is
    a call the client is shown and nobody ever placed.
    """
    tenant_id, agent_id = await _tenant()

    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as excinfo:
            await agents_service.dispatch_call(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                lead_id=None,
                phone_e164="+919876700001",
            )

    assert excinfo.value.code == "agent_not_published", excinfo.value.code
    assert excinfo.value.kind == "business_rule"
    assert excinfo.value.remediation, "a refusal a client cannot act on is a dead end"
    assert await _calls(tenant_id) == 0


async def test_a_deleted_agent_is_not_dialable_even_though_the_engine_still_holds_it() -> None:
    """Deletion is a soft delete, and the row keeps its `engine_agent_ref` — the vendor
    object is not ours to remove synchronously. So the only thing standing between a
    deleted agent and a placed call is `_load_agent`'s `deleted_at IS NULL`, and this is
    the test that stands on it.

    The answer is `not_found`: under RLS "deleted" and "never existed" are deliberately
    the same answer, and neither of them is a phone ringing.
    """
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET engine_agent_ref = 'fakeagent_ghost', status = 'live', "
                "direction = 'outbound', deleted_at = now() WHERE id = :a"
            ),
            {"a": agent_id},
        )

        with pytest.raises(ProblemError) as excinfo:
            await agents_service.dispatch_call(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                lead_id=None,
                phone_e164="+919876700002",
            )

    assert excinfo.value.kind == "not_found", excinfo.value.kind
    assert await _calls(tenant_id) == 0, "a deleted agent places no calls"


async def test_recording_a_dlt_status_against_a_number_we_do_not_hold_is_refused() -> None:
    """`phone_numbers.dlt_status` is what the campaign gate reads to decide a header is
    registered. An UPDATE that matched nothing and returned quietly would let an
    operator believe a registration was recorded — and the next thing they do is launch
    a campaign that the gate can no longer stop, because the fact it checks was never
    written. Zero rows updated is an error, not a no-op.
    """
    tenant_id, _agent_id = await _tenant()

    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as excinfo:
            await agents_service.set_number_dlt_status(
                session, number_id=uuid7(), dlt_status="registered"
            )

    assert excinfo.value.kind == "not_found", excinfo.value.kind


def test_a_lead_delivery_that_presents_no_secret_is_refused_before_anything_else() -> None:
    """The ingest endpoint's URL is a bearer of nothing: knowing it must not be enough
    to inject a lead, because the very next step of that path is an outbound dial to
    whatever number the payload carried.

    An absent header is refused WITHOUT reaching `compare_digest` — which is also what
    keeps the comparison from raising on `None` and turning a 401 into a 500 on a
    surface that is never shed.
    """
    config = IngestConfig(
        id=uuid7(),
        tenant_id=uuid7(),
        agent_id=uuid7(),
        source="custom",
        mapping={},
        secret_ref="s3cret-value",
    )

    assert verify_ingest_secret(config, None) is False, "no credential, no delivery"
    assert verify_ingest_secret(config, "") is False, "an empty header is not a credential"
    assert verify_ingest_secret(config, "s3cret-value") is True, (
        "and the real secret still opens the door — a refusal that refuses everything "
        "proves nothing"
    )
