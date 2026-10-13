"""The in-call tool wire models, and the call-knowledge vocabulary.

The engine's in-call actions (`apps/api/worker/engine_actions.py`) parse their request
into these models and hand them to `apps/api/worker/in_call_tools.py`, which answers with
the `*Out` models. They live in `packages/shared` because the vocabulary is shared with
the tests of every engine that reaches those tools.

`KnowledgeState` is the vocabulary of `calls.knowledge_state`, kept for the rows that
carry it.
"""

from __future__ import annotations

from typing import Final, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

#: Every model here forbids unknown fields: a body carrying a key the server does not know
#: is a client built against a different contract, and answering it 422 at the edge is how
#: that is found on the first call rather than in a column nobody filled.
_STRICT = ConfigDict(extra="forbid")

#: WHO IS ON THE FAR END, OR THE NAMED REASON WE CANNOT SAY. A `None` number that means
#: several unrelated things cannot be triaged:
#:
#: * ``known`` — a number is in hand.
#: * ``withheld_by_carrier`` — the carrier put nothing in the caller field.
#: * ``unparsed_by_client`` — nothing maps a caller field for this call, so nobody can say
#:   whether one was sent. An UNKNOWN, not a finding.
#: * ``not_read`` — nobody looked. The default.
CallerIdentityState = Literal["known", "withheld_by_carrier", "unparsed_by_client", "not_read"]


#: WHETHER A CALL HAD ITS CLIENT'S KNOWLEDGE, OR THE NAMED REASON IT DID NOT — the values
#: `calls.knowledge_state` may hold (its CHECK constraint is built from `KNOWLEDGE_STATES`).
#:
#: * ``available`` — the knowledge loaded and every question was answered out of it.
#: * ``no_pack`` — the agent had no knowledge base. Ordinary, not a degradation.
#: * the four below — knowledge WAS configured and the call ran without it.
KnowledgeUnavailableReason = Literal[
    "fetch_failed", "absent", "unsupported_format", "identity_mismatch"
]
KnowledgeState = Literal[
    "available",
    "no_pack",
    "fetch_failed",
    "absent",
    "unsupported_format",
    "identity_mismatch",
]

#: Every state, for the CHECK constraint and for a caller that needs membership.
KNOWLEDGE_STATES: Final[frozenset[str]] = frozenset(get_args(KnowledgeState))

#: The states that mean THE CALL ANSWERED NOTHING — what an alarm fires on and what an
#: operator counts.
DEGRADED_KNOWLEDGE_STATES: Final[frozenset[str]] = frozenset(get_args(KnowledgeUnavailableReason))

#: An identifier the server matches or stores: a date, a time, a machine code.
MAX_IDENTIFIER: Final = 64


# --- the four in-call tools ----------------------------------------------------------
#
# `apps/api/worker/in_call_tools.py` reaches the one service function that owns each write
# (`compliance/optout.record_call_optout`, `callbacks/service.book`,
# `callbacks/service.cancel_for_phones`). Two implementations of "add this caller to the DNC
# list" is the defect this arrangement exists to prevent.
#
# **THE STATUS WORDS ARE `recorded` / `booked` / `cancelled`, NOT `accepted`**: the write
# happens IN THE REQUEST, so saying "accepted" would be under-claiming in a sentence an
# agent reads out.
#
# **`say` IS GUIDANCE FOR THE AGENT, IN ENGLISH, WHICH ITS OWN LLM RENDERS INTO THE
# CALLER'S LANGUAGE** — `calling_window.SlotRefusal`'s rule, which these follow because the
# caller may be speaking Telugu and a bare status word is not something a model can say.

#: The longest model-authored string a tool body may carry. `workers/optout._REASON_CHARS`
#: (80) and `callbacks.MAX_NOTE` (200) are what the values are truncated to where they are
#: STORED; this is the bound at the edge: a language model has no length contract and an unbounded
#: body is a 1 vCPU host materialising it.
MAX_TOOL_TEXT: Final = 500


class CallerIdentityIn(BaseModel):
    """Who is on the far end, carried per tool call.

    **IT IS ON THE TOOL BODY BECAUSE THE DECISION IS SYNCHRONOUS.** The agent is waiting for an
    answer it is about to SAY, so whether the
    call names a caller has to be readable in the moment, not discovered by a job after the
    caller has hung up believing they were removed.

    `state` is the fact; `e164` is the number and only ever travels with `state="known"`.
    Hard rule 6: the number is carried, never logged — the server logs `state` and nothing
    else, and `state` is set by our own code rather than built from wire data, so it
    cannot smuggle one.
    """

    model_config = _STRICT

    state: CallerIdentityState = "not_read"
    e164: str | None = None


class OptOutToolIn(BaseModel):
    """ "Do not call me again", as the model reports it. Both fields are hints.

    They become EVIDENCE text in `consent_ledger` (append-only, hard rule 4) and nothing
    else: the number suppressed is never taken from either.
    """

    model_config = _STRICT

    reason: str | None = Field(default=None, max_length=MAX_TOOL_TEXT)
    language: str | None = Field(default=None, max_length=8)
    caller: CallerIdentityIn = Field(default_factory=CallerIdentityIn)


class OptOutToolOut(BaseModel):
    """Two statuses, and the second one is the whole reason this model is not a bare ack.

    **`not_recorded` MUST NOT READ AS SUCCESS ANYWHERE.** A person who asked not to be
    called again and was told "done" when nothing was written is the worst outcome
    available — worse than being told a person will handle it, because they will not ring
    again to check. So the failure carries its own `say`, and the agent is told in words
    what it may and may not claim.
    """

    model_config = _STRICT

    status: Literal["recorded", "not_recorded"]
    say: str
    #: A machine code an operator can grep, never prose for the caller: `caller_number_unknown`
    #: (with the identity state appended), `not_suppressible`, or `""` on success.
    reason: str = ""


class CallbackBookIn(BaseModel):
    """ "Ring me back Tuesday at four", already resolved by the model into date and time.

    `confirmed` IS A BOOL HERE AND A NARROW PARSE AT THE EDGE (`true`/`"yes"` and nothing
    else, `worker/engine_actions.py`), so the tool receives a decided boolean rather than a
    string to re-interpret.
    """

    model_config = _STRICT

    callback_date: str | None = Field(default=None, max_length=MAX_IDENTIFIER)
    callback_time: str | None = Field(default=None, max_length=MAX_IDENTIFIER)
    confirmed: bool = False
    note: str | None = Field(default=None, max_length=MAX_TOOL_TEXT)
    language: str | None = Field(default=None, max_length=8)
    caller: CallerIdentityIn = Field(default_factory=CallerIdentityIn)


class CallbackToolOut(BaseModel):
    """The booking's four answers.

    `needs_confirmation` and `not_booked` are that model's, unchanged and for its reasons:
    confirm-before-commit is a SERVER-SIDE control, and a time outside 09:00-21:00 IST is
    unlawful to dial (TCCCPR; SEC-COMP §3) and must be refused while the caller is still on
    the phone. `booked` replaces `accepted` because the row is written in this request.

    The fourth is `not_booked` with `reason="caller_number_unknown"`: a promise to ring
    somebody back needs a number to ring, and this leg can be told there is none.
    """

    model_config = _STRICT

    status: Literal["booked", "needs_confirmation", "not_booked"]
    say: str
    #: The unambiguous spoken form the agent must read back — "Tuesday 8 September at
    #: 4:00 PM". Weekday and month NAME, never a numeric date (`calling_window.Slot`).
    booked_for: str = ""
    reason: str = ""


class CallbackCancelIn(BaseModel):
    """ "Actually, don't ring me back." No time in it at all.

    A cancellation must not be able to fail because a date could not be parsed, and it is
    NOT an opt-out: "do not ring me back on Tuesday" is not "never call me again", and
    answering it with a DNC entry would suppress a number on a sentence nobody said.
    """

    model_config = _STRICT

    caller: CallerIdentityIn = Field(default_factory=CallerIdentityIn)


class CallbackCancelOut(BaseModel):
    """What was called off. `cancelled` is a count so "nothing was booked" is sayable."""

    model_config = _STRICT

    status: Literal["cancelled", "not_cancelled"]
    say: str
    cancelled: int = 0
    reason: str = ""


class HandoffToolIn(BaseModel):
    """The model's own words about why it wants a person, passed through unread.

    Both are conversation content and neither is logged (hard rule 6).
    """

    model_config = _STRICT

    reason: str | None = Field(default=None, max_length=MAX_TOOL_TEXT)
    summary: str | None = Field(default=None, max_length=MAX_TOOL_TEXT)


#: What became of a request for a person, in a word the agent can act on.
#:
#: **THE THREE FAILURES ARE SEPARATE WORDS BECAUSE THEY ARE SEPARATE SENTENCES.** "Nobody
#: picked up", "there is nobody on duty" and "this line cannot transfer at all" all end the
#: same way — a call back — and collapsing them would hand a worried caller one flat
#: apology for three different situations. They also differ in what is true later: the
#: first may work on the next call, the second will work in the morning, the third never
#: will until a carrier leg is written.
#:
#: **`connected` IS THE ONLY WORD THAT LICENSES "I AM PUTTING YOU THROUGH", AND IT MEANS A
#: PERSON ACCEPTED** — not that a number was dialled, not that it is ringing. The
#: destination pattern is whisper-then-accept: the person we ring hears who is calling and
#: about what, and has to accept before the bridge. A caller told they are getting a person
#: and then handed silence is the worst outcome this feature has.
#:
#: `not_transferred` is the WIDE one: it did not happen and the answer cannot say which of
#: the three it was. It is what an engine with no handover at all has always returned, so
#: it stays a member rather than being migrated away.
HandoffOutcome = Literal[
    "connected",
    "no_answer",
    "nobody_on_duty",
    "not_available",
    "not_transferred",
]


class HandoffToolOut(BaseModel):
    """What became of the request for a person, in a word the agent has a sentence for.

    No engine we run carries a second leg of ours, so `not_available` is the only answer
    given today (`worker/in_call_tools.request_handoff_unplaced`). That is better than no
    tool: a model asked to fetch a human with no tool at all answers from its priors, says
    "putting you through now", and the caller hears nothing happen.
    """

    model_config = _STRICT

    status: HandoffOutcome
    say: str
    reason: str = ""


__all__ = [
    "DEGRADED_KNOWLEDGE_STATES",
    "KNOWLEDGE_STATES",
    "MAX_IDENTIFIER",
    "MAX_TOOL_TEXT",
    "CallbackBookIn",
    "CallbackCancelIn",
    "CallbackCancelOut",
    "CallbackToolOut",
    "CallerIdentityIn",
    "CallerIdentityState",
    "HandoffOutcome",
    "HandoffToolIn",
    "HandoffToolOut",
    "KnowledgeState",
    "KnowledgeUnavailableReason",
    "OptOutToolIn",
    "OptOutToolOut",
]
