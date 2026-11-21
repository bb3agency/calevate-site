"""D-1026: a placed call tells the model the words it actually opened with.

One engine agent serves every dial of a campaign or line and quotes one greeting, while a dial
may open with the campaign's second opening or a name check instead. The dial sends its own
first words as THIS CALL's "Said first", and START OF THE CALL says those replace the quote.
"""

from __future__ import annotations

import httpx
from calevate_shared.engine import (
    SAID_FIRST_LINE,
    SAID_FIRST_RULE,
    START_OF_CALL_HEADER,
    THIS_CALL_HEADER,
    AgentConfig,
    CallContext,
    compose_engine_prompt,
    said_first_values,
)
from tests.thinnest_engine_test import _agent_with_greeting, _body, _engine, _recorder

SECOND = "Namaskaram Asha garu, a quick call about the offer you asked for. Is now a good time?"


def _dial_handler() -> tuple[object, list[httpx.Request]]:
    return _recorder(
        {
            ("GET", "/agents/ag_1"): _agent_with_greeting("Namaskaram, Sunrise nunchi."),
            ("POST", "/calls"): httpx.Response(202, json={"id": "out_1", "status": "ringing"}),
        }
    )


async def test_a_dial_with_its_own_first_words_sends_them_as_said_first() -> None:
    handler, seen = _dial_handler()
    await _engine(handler).start_outbound_call(
        "ag_1", "+919876543210", CallContext(lead_name="Asha", opening=SECOND)
    )
    body = _body(seen[-1])
    assert body["purpose"] == SECOND
    assert body["variables"]["said"] == SECOND
    assert "said_2" not in body["variables"]


async def test_a_dial_on_the_agents_own_greeting_sends_no_said_first() -> None:
    handler, seen = _dial_handler()
    await _engine(handler).start_outbound_call("ag_1", "+919876543210", CallContext())
    variables = _body(seen[-1])["variables"]
    assert "said" not in variables and "said_2" not in variables


def test_a_long_opening_is_split_on_a_word_across_the_two_values() -> None:
    opening = " ".join(["the east facing two bedroom flat you asked about"] * 6)
    values = said_first_values(opening)
    assert all(len(v) <= 150 for v in values.values())
    assert opening.startswith(f"{values['said']} {values['said_2']}")
    assert opening[len(values["said"])] == " ", "cut mid-word"


async def test_said_first_takes_room_from_list_columns_not_from_the_lookup() -> None:
    handler, seen = _dial_handler()
    lookup = {f"lookup_{i}": "x" for i in range(14)}
    columns = {f"col {i}": str(i) for i in range(10)}
    ctx = CallContext(lead_name="Asha", fields=lookup, contact_details=columns, opening=SECOND)
    await _engine(handler).start_outbound_call("ag_1", "+919876543210", ctx)
    variables = _body(seen[-1])["variables"]
    assert len(variables) == 20
    assert all(key in variables for key in lookup)
    assert variables["said"] == SECOND
    assert [k for k in variables if k.startswith("col_")] == ["col_0"]


def _cfg(**kw: object) -> AgentConfig:
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="Sunrise",
        system_prompt="[OPENING]\nNamaskaram, Sunrise nunchi. Is now a good time?",
        opening_line="Idi AI assistant.",
        **kw,  # type: ignore[arg-type]
    )


def test_an_agent_that_places_calls_reads_said_first_beside_its_quoted_greeting() -> None:
    for cfg in (
        _cfg(direction="outbound"),
        _cfg(direction="inbound", places_call_backs=True),
    ):
        prompt = compose_engine_prompt(cfg)
        start = prompt[prompt.index(START_OF_CALL_HEADER) :]
        quoted_end = start.index('".') + 2
        assert start[quoted_end:].startswith(SAID_FIRST_RULE), cfg.direction
        assert SAID_FIRST_LINE in prompt[prompt.rindex(THIS_CALL_HEADER) :]


def test_an_answering_agent_that_places_no_calls_reads_neither() -> None:
    prompt = compose_engine_prompt(_cfg(direction="inbound"))
    assert SAID_FIRST_RULE not in prompt and SAID_FIRST_LINE not in prompt
