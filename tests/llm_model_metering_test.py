"""The ledger names the language model a call ran, and says which level chose it (D-454).

**THE GAP THESE TESTS CLOSE.** D-454 made the in-call language model a CLIENT'S choice —
`agents.llm_model`, falling back to `organizations.default_llm_model`, falling back to the
platform's own — and the two selectable models differ by 2.7x on both token legs. Both of
those columns are editable at any moment from two screens, in two realms. So on the day
after a call, "which model did that call run" is not answerable from the live rows: they
have moved on. `usage_events` is append-only (hard rule 4), which means the answer cannot
be back-filled by an UPDATE either — it is stamped at metering time or it is gone.

That is the identical argument `tts_tier`/`tts_tier_source` already won for the voice rung
(`tests/tts_tier_metering_test.py`), arriving on a second, dearer leg. These tests are the
tripwire for it: delete either meta key from `pipeline._meter` and a month in which a
client switched models becomes one nobody can take apart, silently.

**WHAT IS AND IS NOT CLAIMED.** `llm_model` is the model the call was CONFIGURED to run,
resolved at metering time — not a measurement. No execution payload names the model that
served the call (`billing/rates.py` argues that vendor hole at length), so `llm_model_source`
carries the provenance in the open: `agent` and `organization` mean somebody chose at that
level, `platform` means nobody did. Nothing here is a price. The in-call leg is BYOK — the
engine pays nothing for it and reports no token count — so this is the identifier a future
reconciliation against the Azure invoice would be keyed on, never a charge.

Run: uv run pytest -q tests/llm_model_metering_test.py
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from apps.api.agents.llm_models import platform_default_model
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers.pipeline import _meter
from calevate_shared.engine import AZURE_OPENAI_MODELS, CostBreakdown, ExecutionSnapshot
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant

#: A model that is NOT the platform's own, so "the agent chose" and "nobody chose" can
#: never be told apart by accident. Derived from the allow-list rather than typed, for
#: D-104's reason: a third model added to the Literal must not leave this fixture pinning
#: a string that is no longer the alternative.
#:
#: `min` rather than `next(iter(...))`, which is the idiom elsewhere: that one is
#: deterministic only while the difference holds exactly one member, and Python randomises
#: string hashing per process — so the day a third model lands, an `iter` over a frozenset
#: would make WHICH model this suite exercises vary run to run, and the failure would look
#: like flakiness rather than like the fixture it is.
_OTHER_MODEL = min(AZURE_OPENAI_MODELS - {platform_default_model()})


def _snapshot() -> ExecutionSnapshot:
    """A priced, billable execution — the only shape `_meter` writes rows for.

    `llm_inr` is zero and stays zero: the in-call language leg is BYOK, so the engine
    charges us nothing for it and reports nothing about it. That is exactly why the model
    has to be recorded as an IDENTIFIER rather than derived from a cost.
    """
    return ExecutionSnapshot(
        engine_call_id=f"exec_{uuid.uuid4().hex[:12]}",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        duration_s=120,
        cost=CostBreakdown(
            total_inr=Decimal("6.0000"),
            platform_inr=Decimal("3.0000"),
            network_inr=Decimal("0.8000"),
            llm_inr=Decimal("0.0000"),
            tts_inr=Decimal("2.0000"),
            stt_inr=Decimal("1.0000"),
            source_currency="INR",
            source_amount=Decimal("6.0000"),
            fx_rate=Decimal("1"),
        ),
        engine="fake",
    )


async def _metered_call(
    label: str, *, agent_model: str | None = None, org_model: str | None = None
) -> list[dict[str, Any]]:
    """Seed a tenant at one rung of the resolution, meter one call, return its rows.

    The two model columns are written by UPDATE rather than by a route so that this test
    exercises the METER against a database state, not the API's own validation — the
    columns are what `_meter` reads, and a fixture that could only reach them through a
    validated write would stop covering the arm where an operator's edit outlives a
    published agent.
    """
    tenant_id, agent_id = await _seed_tenant(f"fakeagent_{label}_{uuid.uuid4().hex[:8]}")
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET llm_model = CAST(:m AS text) WHERE id = :a"),
            {"m": agent_model, "a": agent_id},
        )
        await session.execute(
            text("UPDATE organizations SET default_llm_model = CAST(:m AS text) WHERE id = :t"),
            {"m": org_model, "t": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "to_e164, status, created_at, updated_at) VALUES (:i, :t, :a, :e, 'outbound', "
                "'+919876500001', 'completed', now(), now())"
            ),
            {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"exec_{uuid.uuid4().hex[:12]}"},
        )
    await _meter(tenant_id, call_id, _snapshot())
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT unit_type, meta FROM usage_events "
                    "WHERE tenant_id = :t AND call_id = :c ORDER BY unit_type"
                ),
                {"t": tenant_id, "c": call_id},
            )
        ).all()
    assert rows, "the call metered something"
    return [{"unit_type": r[0], "meta": r[1] or {}} for r in rows]


async def test_an_agents_own_choice_is_the_model_on_every_row() -> None:
    """The top rung. `source` says `agent`, so a reader knows this was a deliberate
    per-agent selection and not an account default that has since moved."""
    rows = await _metered_call("agentpick", agent_model=_OTHER_MODEL)
    assert {row["meta"]["llm_model"] for row in rows} == {_OTHER_MODEL}
    assert {row["meta"]["llm_model_source"] for row in rows} == {"agent"}


async def test_an_account_default_is_recorded_as_the_accounts_choice() -> None:
    """The middle rung, and the one a later read cannot reconstruct: the agent row holds
    nothing, so once `organizations.default_llm_model` moves there is no trace left of
    what this call ran except this one."""
    rows = await _metered_call("orgpick", org_model=_OTHER_MODEL)
    assert {row["meta"]["llm_model"] for row in rows} == {_OTHER_MODEL}
    assert {row["meta"]["llm_model_source"] for row in rows} == {"organization"}


async def test_an_agents_choice_beats_its_accounts() -> None:
    """Both rungs set, and they disagree. The agent wins — the same precedence
    `agents/llm_models.resolve_llm_model` publishes, asserted where the money is."""
    rows = await _metered_call(
        "bothpick", agent_model=platform_default_model(), org_model=_OTHER_MODEL
    )
    assert {row["meta"]["llm_model"] for row in rows} == {platform_default_model()}
    assert {row["meta"]["llm_model_source"] for row in rows} == {"agent"}


async def test_nobody_choosing_is_recorded_as_the_platform_rung_and_says_so() -> None:
    """The default state of every account that has never opened the picker.

    `platform` is the honest label rather than a silent copy of the model name: on a
    deployment with an Azure leg it IS `Settings.azure_openai_model`, and on one with no
    Azure credential `in_call_llm` sends no model at all, so the engine's own default
    runs. One string cannot be true under both; the string plus its level is.
    """
    rows = await _metered_call("nopick")
    assert {row["meta"]["llm_model"] for row in rows} == {platform_default_model()}
    assert {row["meta"]["llm_model_source"] for row in rows} == {"platform"}


async def test_the_model_is_on_every_row_of_the_call_not_just_one() -> None:
    """`_tier_totals` and every other reader group these rows freely, so a fact carried
    by only one unit type is a fact a `WHERE unit_type = ...` silently loses — the same
    property `tts_tier` holds and for the same reason."""
    rows = await _metered_call("everyrow", agent_model=_OTHER_MODEL)
    assert len(rows) > 1, "the fixture must meter more than one unit type to prove this"
    assert all(row["meta"].get("llm_model") == _OTHER_MODEL for row in rows)
    assert all(row["meta"].get("llm_model_source") == "agent" for row in rows)


async def test_recording_the_model_does_not_move_the_money() -> None:
    """Attribution is meta, and meta is not money. The margin panel sums
    `qty * unit_cost_paid`; a model label appearing on the row must not change a paisa of
    it — least of all because the two selectable models differ by 2.7x and a reader could
    reasonably expect that to land somewhere. It does not: the in-call leg is BYOK and
    the engine's figures are what they were.
    """
    cheap = await _metered_call("moneycheap", agent_model=platform_default_model())
    dear = await _metered_call("moneydear", agent_model=_OTHER_MODEL)

    async def _cost(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {row["unit_type"]: row["meta"].get("source_amount") for row in rows}

    assert await _cost(cheap) == await _cost(dear)
    assert {row["unit_type"] for row in cheap} == {row["unit_type"] for row in dear}
