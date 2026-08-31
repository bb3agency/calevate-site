"""The copilot's read tool: its schema, its stop condition, and what it says when it cannot
answer. The database half is `tests/retrieval_copilot_tool_test.py`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from apps.api.copilot import prompt as prompt_module
from apps.api.copilot.read_tools import (
    BUDGET_SPENT,
    MAX_SEARCHES,
    NOTHING_FOUND,
    SEARCH_KNOWLEDGE_TOOL_NAME,
    search_knowledge_tool,
    serve_searches,
)


@dataclass(frozen=True)
class _Call:
    """The shape `chat.ChatOutcome.tool_calls` carries, reduced to what this file reads."""

    id: str
    name: str
    arguments: str


def _search(index: int, question: str = "opening hours") -> _Call:
    return _Call(
        id=f"call_{index}",
        name=SEARCH_KNOWLEDGE_TOOL_NAME,
        arguments=json.dumps({"question": question}),
    )


async def _echo(question: str) -> str:
    return f"answered:{question}"


# --- the schema -----------------------------------------------------------------------


def test_the_tool_takes_a_question_and_nothing_that_could_widen_the_scope() -> None:
    """THE TENANCY PROPERTY AT THIS SEAM. The tenant is captured in the closure the route
    builds; the model supplies a question. If a tenant id, an agent id or a namespace ever
    became an argument, a model could be talked into naming another account's.
    """
    params = search_knowledge_tool()["function"]["parameters"]
    assert set(params["properties"]) == {"question"}
    assert params["additionalProperties"] is False
    assert params["required"] == ["question"]


def test_the_tool_schema_uses_the_same_strict_subset_as_the_write_tool() -> None:
    """One idea of what a strict schema is, not two (`prompt.set_fields_tool` argues the
    subset and cites openai-python's `to_strict_json_schema`)."""
    read = search_knowledge_tool()["function"]
    write = prompt_module.set_fields_tool()["function"]
    assert read["strict"] == write["strict"] is True
    assert set(read) == set(write)
    forbidden = ("pattern", "format", "minLength", "minimum", "minItems", "uniqueItems")
    serialized = json.dumps(read)
    for key in forbidden:
        assert f'"{key}"' not in serialized


def test_the_loop_offers_two_distinctly_named_tools() -> None:
    """A model that sees two tools with one name cannot be told which it called."""
    names = {
        search_knowledge_tool()["function"]["name"],
        prompt_module.set_fields_tool()["function"]["name"],
    }
    assert len(names) == 2


# --- the stop condition ---------------------------------------------------------------


async def test_a_turn_with_no_search_is_left_alone() -> None:
    """An empty list means "this turn asked for no search", which is what tells the loop to
    treat the turn exactly as it always did."""
    fill = _Call(id="c1", name=prompt_module.SET_FIELDS_TOOL_NAME, arguments="{}")
    assert await serve_searches([fill], lookup=_echo, remaining=MAX_SEARCHES) == []


async def test_every_search_call_gets_a_reply_including_the_ones_over_budget() -> None:
    """THE STOP CONDITION, and the shape that keeps the conversation well-formed. A provider
    rejects a `tool_call` with no matching tool message, so an over-budget call is ANSWERED
    with a refusal rather than dropped — and the refusal is a sentence the model can act on,
    because a tool that returns nothing invites another call.
    """
    calls = [_search(1), _search(2), _search(3)]
    served = await serve_searches(list(calls), lookup=_echo, remaining=1)
    assert [message["tool_call_id"] for message in served] == ["call_1", "call_2", "call_3"]
    assert served[0]["content"].startswith("answered:")
    assert served[1]["content"] == BUDGET_SPENT
    assert served[2]["content"] == BUDGET_SPENT


async def test_no_searches_left_answers_every_call_with_the_budget_sentence() -> None:
    served = await serve_searches([_search(1)], lookup=_echo, remaining=0)
    assert served[0]["content"] == BUDGET_SPENT


async def test_the_budget_is_small_on_purpose() -> None:
    """A number, pinned so raising it is an argument rather than an edit. Each extra search
    is a whole extra turn — the conversation and the screen resent — over a corpus of at
    most a few dozen compiled lines."""
    assert MAX_SEARCHES == 2


# --- malformed arguments --------------------------------------------------------------


async def test_a_malformed_tool_call_answers_nothing_found_rather_than_raising() -> None:
    """A truncated tool call is an ordinary event on a streamed leg. An exception here would
    end a stream somebody is reading; `NOTHING_FOUND` is the honest answer and the model
    can act on it."""
    recorded: list[str] = []

    async def lookup(question: str) -> str:
        recorded.append(question)
        return NOTHING_FOUND if not question else "found"

    broken = _Call(id="c1", name=SEARCH_KNOWLEDGE_TOOL_NAME, arguments='{"question": ')
    served = await serve_searches([broken], lookup=lookup, remaining=1)
    assert recorded == [""]
    assert served[0]["content"] == NOTHING_FOUND


async def test_a_tool_call_whose_argument_is_not_an_object_is_tolerated() -> None:
    odd = _Call(id="c1", name=SEARCH_KNOWLEDGE_TOOL_NAME, arguments='"hours"')
    served = await serve_searches([odd], lookup=_echo, remaining=1)
    assert served[0]["content"] == "answered:"
