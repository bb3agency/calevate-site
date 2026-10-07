"""What a hosted engine's own limits and console mean for our product surfaces.

A `control_plane` engine holds our agent in ITS records, so some of our text has to fit
ITS fields, and some of our setup happens in ITS console rather than through an API. Both
are vendor facts (hard rule 2 keeps them in this package), and both are needed OUTSIDE the
adapter: the publish path must refuse an agent that will not fit before anything is written
to the vendor, and the admin numbers screen must tell an operator which console steps make
a phone ring. So each adapter's ceilings are collected here from the adapter's own
constants, keyed by its `name`, and business code asks this module instead of an adapter.

An engine with no entry has no limit we know of and no console step to show — the answer
for every engine whose agents and numbers we manage ourselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from calevate_shared.engine import VoiceEngine

from apps.api.engine.text_split import split_for_text_cap
from apps.api.engine.thinnest import (
    GREETING_MAX_CHARS,
    INSTRUCTIONS_MAX_CHARS,
    KB_TEXT_MAX_CHARS,
    PURPOSE_MAX_CHARS,
)


@dataclass(frozen=True, slots=True)
class HostedAgentLimits:
    """The ceilings an engine puts on the text we hand it. `None` is "no ceiling known"."""

    #: The agent's whole system prompt, as `compose_engine_prompt` renders it.
    prompt_chars: int | None
    #: The agent-level first utterance (the opening line, spoken on an inbound call).
    greeting_chars: int | None
    #: The per-call first utterance on an outbound dial.
    call_opening_chars: int | None
    #: Does an outbound dial REQUIRE a first utterance? Where it does, an agent whose
    #: opening line is empty (both notices switched off, D-163) cannot place a call at all.
    call_opening_required: bool
    #: One knowledge document's text.
    kb_text_chars: int | None
    #: Does the engine hold the business facts (the prompt's [T0 FACTS] block) as a knowledge
    #: document instead of in the prompt? On ThinnestAI the prompt is re-sent on every turn
    #: and costs on each one, so the facts move out and the prompt holds the rules and the script
    #: (founder's decision, 6 Oct 2026; `agents/engine_facts.py`).
    facts_in_knowledge: bool = False


NO_HOSTED_LIMITS: Final = HostedAgentLimits(
    prompt_chars=None,
    greeting_chars=None,
    call_opening_chars=None,
    call_opening_required=False,
    kb_text_chars=None,
)

#: ThinnestAI's field ceilings, read from the adapter that sends the fields so there is one
#: copy of each. VERIFIED-VENDOR-DOCS, `thinnest-findings/mirror/snapshots/2026-10-07/pages/`:
#: `instructions` up to 20,000 characters and `greeting` up to 200
#: (`api-reference/agents/update-agent.md:426-436`); a call's `purpose` is required, spoken
#: first, under 300 (`api-reference/calls/place-call.md:7`); knowledge `text` capped at
#: 200,000 (6 Oct record, `pages/api-reference/knowledge.md:52`).
THINNEST_LIMITS: Final = HostedAgentLimits(
    prompt_chars=INSTRUCTIONS_MAX_CHARS,
    greeting_chars=GREETING_MAX_CHARS,
    call_opening_chars=PURPOSE_MAX_CHARS,
    call_opening_required=True,
    kb_text_chars=KB_TEXT_MAX_CHARS,
    facts_in_knowledge=True,
)

_LIMITS_BY_ENGINE: Final[dict[str, HostedAgentLimits]] = {"thinnest": THINNEST_LIMITS}


def hosted_agent_limits(engine: VoiceEngine) -> HostedAgentLimits:
    """The text ceilings of `engine`, or `NO_HOSTED_LIMITS`."""
    return _LIMITS_BY_ENGINE.get(engine.name, NO_HOSTED_LIMITS)


@dataclass(frozen=True, slots=True)
class EngineNumberConsole:
    """Where an engine's numbers are rented and attached, when that is a console step.

    Exists for engines that rent numbers and route them to agents ONLY in their own
    console (`provision_number` and `bind_inbound_number` refuse by name there): the
    admin numbers screen lists what the engine holds and shows these steps instead of a
    buy button that would refuse.
    """

    platform_label: str
    steps: tuple[str, ...]
    notes: tuple[str, ...]


#: ThinnestAI: renting and attaching are console-only
#: (`api-reference/voices-and-models.md:86-87`). Steps paraphrase
#: `channels/phone-numbers.md:29-56` (rent and point), `:77-84` (Indian KYC), `:488-512`
#: (Inbound and Outbound pickers), `:431-434` (Dial-out ready), `:664-669` (140-series for
#: promotional calls), `:457-463` and `:615-619` (owner/admin only; releasing is permanent).
THINNEST_NUMBER_CONSOLE: Final = EngineNumberConsole(
    platform_label="ThinnestAI",
    steps=(
        "In the ThinnestAI console, open Phone Numbers in the main sidebar and choose "
        "Buy / Import number.",
        "Pick India, and a city if you want a local code, then choose a number and confirm "
        "its monthly price. An Indian number is issued only after the business's KYC "
        "clears, on the KYC tab of the same page.",
        "On the Phone Numbers page, set Inbound to the agent Calevate published for this "
        "client (its ThinnestAI id is on the agent's row below). It answers immediately.",
        "If the agent also calls out, set Outbound to the same agent and check that the "
        "Dial-out ready column says yes.",
        "Ring the number. You should hear the agent's opening line, then the agent.",
    ),
    notes=(
        "Promotional calls in India need a 140-series number registered with DLT. An "
        "ordinary number is for service and transactional calls only.",
        "Renting, moving and releasing numbers needs an owner or admin on the ThinnestAI "
        "workspace. Releasing a rented number is permanent.",
    ),
)

_NUMBER_CONSOLE_BY_ENGINE: Final[dict[str, EngineNumberConsole]] = {
    "thinnest": THINNEST_NUMBER_CONSOLE
}


def engine_platform_label(engine: VoiceEngine) -> str:
    """The name an OPERATOR knows this engine's vendor by, for operator-facing sentences.

    Never put in a client-facing sentence: which platform runs a client's calls is our
    deployment detail.
    """
    console = _NUMBER_CONSOLE_BY_ENGINE.get(engine.name)
    return console.platform_label if console is not None else "the voice platform"


def engine_number_console(engine: VoiceEngine | str) -> EngineNumberConsole | None:
    """The console steps for `engine`'s numbers, or `None` where we manage them ourselves.

    Takes the engine NAME as well as an adapter, for callers that hold only the configured
    name (`campaigns/provisioning.provisioning_not_configured`).
    """
    name = engine if isinstance(engine, str) else engine.name
    return _NUMBER_CONSOLE_BY_ENGINE.get(name)


__all__ = [
    "NO_HOSTED_LIMITS",
    "THINNEST_LIMITS",
    "THINNEST_NUMBER_CONSOLE",
    "EngineNumberConsole",
    "HostedAgentLimits",
    "engine_number_console",
    "engine_platform_label",
    "hosted_agent_limits",
    "split_for_text_cap",
]
