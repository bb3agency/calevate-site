"""The founder's paid test call of 21 Nov 2026: an outbound agent greeted twice.

The engine spoke a short opening (greeting, the business, "is now a good time?"); after the
caller's "go ahead" the model said a whole second opening: greeting, who it was, why it rang
and "is now a good time?" again. START OF THE CALL quotes the words the engine speaks as
already said, and those are the agent's [OPENING] (`compose_first_utterance`), but the
script went on carrying its [OPENING ON CALLS YOU PLACE], which only a "both" agent speaks
(D-920). An agent that was "both" and is now outbound keeps that section (a direction change
does not rewrite the script), and so does a campaign that speaks a "both" voice's script as
an outbound holder. The model read it as the opening of this placed call, still to say.

Composed the way each holder path composes it: the test copy holding the agent (D-859
option A), the "Just the business" copy (D-1000), and a campaign over a "both" voice's script
(D-1003); a "both" agent keeps both openings and both are quoted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents.business_only import business_row
from apps.api.agents.service import (
    AgentRow,
    _load_agent,
    _to_config,
    campaign_agent_row,
    dial_first_words,
)
from apps.api.campaigns import service as campaigns
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from calevate_shared.call_script import (
    NOTICES_HEADER,
    OPENING_HEADER,
    OUTBOUND_OPENING_HEADER,
    CallScript,
    compile_call_script,
    opening_line_of,
    outbound_opening_of,
    without_placed_opening,
)
from calevate_shared.engine import (
    START_OF_CALL_HEADER,
    AgentConfig,
    compose_engine_prompt,
    compose_first_utterance,
    engine_prompt_layers,
    quoted_client_words,
)
from calevate_shared.opening_notices import OpeningNotices
from tests.dispatch_budget_test import _dlt_rows, _tenant

SHORT = "Namaskaram, I am calling from Rytu Khata. Is now a good time to talk?"
FULL = (
    "Namaskaram garu, I am calling from Rytu Khata. You registered on our app, and I called "
    "to help you put it on your phone as an app in five minutes. Is now a good time to talk?"
)
AI_WORDS = "I am an AI assistant"


def _script(*, placed: str = FULL) -> CallScript:
    return CallScript(
        schema_version=2,
        opening_line=SHORT,
        outbound_opening_line=placed,
        goal="Help the farmer put the app on their phone.",
    )


# --- the section the engine never speaks ---------------------------------------------------


def test_a_placed_opening_is_taken_out_and_everything_else_kept() -> None:
    body = compile_call_script(_script())
    assert outbound_opening_of(body) == FULL

    kept = without_placed_opening(body)

    assert OUTBOUND_OPENING_HEADER not in kept and FULL not in kept
    assert opening_line_of(kept) == SHORT
    assert kept == compile_call_script(_script(placed=""))
    # A body with nothing to take out is the same string, so its digest does not move.
    plain = compile_call_script(_script(placed=""))
    assert without_placed_opening(plain) is plain


def test_the_notice_rows_of_a_placed_opening_go_with_it() -> None:
    woven = f"Namaskaram, {AI_WORDS} from Rytu Khata. Is now a good time?"
    both = compile_call_script(
        CallScript(
            schema_version=2,
            opening_line=woven,
            opening_notices=OpeningNotices(line=woven, ai=AI_WORDS),
            outbound_opening_line=woven,
            outbound_opening_notices=OpeningNotices(line=woven, ai=AI_WORDS),
        )
    )
    kept = without_placed_opening(both)
    assert "Your opening line tells the caller you are an AI" in kept
    assert "Your opening on calls you place" not in kept

    only_placed = compile_call_script(
        CallScript(
            schema_version=2,
            opening_line=SHORT,
            outbound_opening_line=woven,
            outbound_opening_notices=OpeningNotices(line=woven, ai=AI_WORDS),
        )
    )
    assert NOTICES_HEADER in only_placed
    assert NOTICES_HEADER not in without_placed_opening(only_placed)


# --- every holder path quotes the opening it speaks and holds no other -----------------------


async def _agent(direction: str) -> tuple[UUID, UUID, AgentRow]:
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        loaded = await _load_agent(session, tenant_id, agent_id)
    script = _script()
    row: dict[str, Any] = {
        **dict(loaded),
        "direction": direction,
        "business_name": "Rytu Khata",
        "prompt": compile_call_script(script),
        "structured_script": script.model_dump(mode="json"),
    }
    return tenant_id, agent_id, row  # type: ignore[return-value]


def _start(cfg: AgentConfig) -> str:
    return dict(engine_prompt_layers(cfg))["notices"]


def _speaks_only_its_greeting(cfg: AgentConfig) -> None:
    greeting = compose_first_utterance(cfg)
    assert SHORT in greeting
    assert _start(cfg).startswith(
        f"{START_OF_CALL_HEADER}\nAlready said for you as your first turn: "
        f'"{quoted_client_words(greeting)}".'
    )
    prompt = compose_engine_prompt(cfg)
    assert FULL not in prompt and OUTBOUND_OPENING_HEADER not in prompt
    assert f"{OPENING_HEADER}\n{SHORT}" in cfg.system_prompt


@pytest.mark.rls
async def test_an_outbound_agents_test_copies_read_only_the_opening_they_speak() -> None:
    """The call of 21 Nov 2026: an outbound agent's test call brings no first words of its own
    (`dial_first_words` is None), so the engine speaks the copy's greeting."""
    tenant_id, _agent_id, row = await _agent("outbound")
    assert dial_first_words(row, test_call=True, call_is_recorded=True) is None
    async with tenant_session(tenant_id) as session:
        business = await business_row(session, tenant_id=tenant_id, agent=row)
    for held in (row, business):
        _speaks_only_its_greeting(_to_config(tenant_id, held, engine=get_engine()))


@pytest.mark.rls
async def test_a_campaign_over_a_both_voices_script_reads_only_the_opening_it_speaks() -> None:
    """A campaign with no script of its own speaks its voice's (D-1003) and only places
    calls, so its holder is outbound and greets with the voice's [OPENING]."""
    tenant_id, agent_id, row = await _agent("both")
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        campaign_id = await campaigns.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="App installs",
            classification="promotional",
            number_id=number_id,
            dlt_template_id=template_id,
            concurrency=1,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )
        speaker = await campaign_agent_row(
            session, tenant_id=tenant_id, campaign_id=campaign_id, agent=row
        )
    assert speaker["direction"] == "outbound"
    assert dial_first_words(speaker, test_call=False, call_is_recorded=True) is None
    _speaks_only_its_greeting(_to_config(tenant_id, speaker, engine=get_engine()))


@pytest.mark.rls
async def test_a_both_agent_keeps_both_openings_and_quotes_the_one_it_dials_with() -> None:
    tenant_id, _agent_id, row = await _agent("both")
    cfg = _to_config(tenant_id, row, engine=get_engine())
    said = dial_first_words(row, test_call=True, call_is_recorded=True)

    assert outbound_opening_of(cfg.system_prompt) == FULL
    assert said is not None and FULL in said
    assert f'on a call you place, "{quoted_client_words(said)}".' in _start(cfg)
