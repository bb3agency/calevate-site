"""Pilot gate 8 (OPERATIONS §2, expanded by D-33) — the knowledge slice, as probes.

Gate 8 is a SOFT gate that decides real architecture, so it is the one gate whose
"inconclusive" answer costs as much as a red one. Four questions live here:

1. **The two KB-lifecycle questions D-41's detach contract cannot answer from docs.**
   Bolna publishes no OpenAPI spec, so every BODY on the `/knowledgebase` path is a
   hand-maintained claim (TRD §5, and the standing warning in `apps/api/engine/bolna.py`):
   (a) does `GET /knowledgebase/all` carry the AGENT LINKAGE `list_kb` filters on, and
   (b) does `DELETE /knowledgebase/{rag_id}` also clear the AGENT's reference to it?
2. **Telugu retrieval in the multilingual KB mode** — which names Hindi and Tamil and
   NOT Telugu, and whose mode is IMMUTABLE at KB creation.
3. **The custom-function tool-call budget** — 100ms by TRD §6.2, against a vendor that
   documents no timeout at all.
4. **H1 in-call working memory** (TRD §6.1) — truncation/summarisation at a window
   limit, and provider context caching on BYOK keys.
Plus the batch-campaign built-in, whose verification closes or drops the
`Campaign.engine_campaign_ref` UNWIRED_BASELINE entry (`scripts/check_wiring.py`).

**WHAT THIS MODULE IS.** Executable probes, not a checklist. A checklist item is ticked
by an operator's memory of what they saw; a probe states in advance which observation
means which architecture, so the answer cannot be argued about afterwards. Every probe
therefore carries its CONSEQUENCE in the sub-check detail: what we change if the answer
comes back that way. That is the difference between a pilot that produces evidence and
a pilot that produces opinions.

**WHAT IT DELIBERATELY IS NOT.** It never talks to a vendor itself. Everything that
needs credentials, a phone number, a live call or a raw HTTP response arrives as a
callable seam supplied by the runner (`scripts/pilot/runner.py`, another slice). Two
reasons, and the second is the binding one:

* hard rule 2 — vendor payload shapes live in `apps/api/engine/` and nowhere else, so a
  probe module that parsed `/knowledgebase/all` itself would be the leak the rule
  exists to prevent;
* a probe with no seam is a probe that can only be run once, in one environment, by the
  person who wrote it. With seams, every outcome that matters — linkage ABSENT, a
  dangling `rag_id`, Telugu scoring poorly, a tool endpoint that hangs — is exercised
  against the `fake` adapter in the normal suite (`tests/pilot_knowledge_test.py`). A
  probe that has never run is exactly as unverified as the vendor it is aimed at.

**INCONCLUSIVE.** `scripts/pilot/results.py` has three statuses on purpose, and this
module does not add a fourth: `inconclusive()` below returns a `not_run` sub-check whose
reason is prefixed, so the pessimistic roll-up keeps working and no reader can mistake
"we looked and could not tell" for "we looked and it was fine". The rejected alternative
— a fourth `GateStatus` — would have changed the roll-up in every other gate module for
the benefit of one, and the erring direction here is safe: an undecided probe reads as
unrun, which is the state it leaves the decision in anyway.

**HARD RULE 6.** A KB probe handles caller-facing content and retrieval queries. Nothing
in this module accepts, returns or records a query string, an answer, or a caller
utterance: retrieval is scored by an opaque `question_id` and a boolean, and the scoring
itself happens in the runner's seam. `KbRetrievalLog.query`'s class docstring
(`apps/api/kb/models.py`) is a DATED DEFERRAL for precisely this reason — the column has
no `text_redacted` counterpart — and this module must not become the producer that
deferral was waiting for by the back door.
"""

from __future__ import annotations

import contextlib
import itertools
import math
import os
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Protocol

from calevate_shared.engine import AgentSnapshot, EngineAgentRef, EngineKBRef, KBSourceRef
from pydantic import BaseModel, ValidationError
from pydantic import Field as PydanticField

from scripts.pilot.results import GateRun, SubCheck, failed, not_run, passed

GATE_NUMBER = 8
GATE_TITLE = "KB + campaigns + tools + H1 handling"

#: Sub-check names, in report order. `run_gate8` emits EVERY one of these on every run —
#: a probe whose inputs were missing appears as NOT RUN rather than not appearing, which
#: is the only way a reader can tell "we did not measure this" from "this gate is short".
CHECK_NAMES: tuple[str, ...] = (
    "kb_list_carries_agent_linkage",
    "kb_delete_clears_agent_reference",
    "telugu_builtin_kb_retrieval",
    "telugu_external_kb_fallback",
    "custom_function_tool_call_budget",
    "custom_function_slow_endpoint_behaviour",
    "h1_history_window_handling",
    "h1_provider_context_caching",
    "batch_campaign_retry_policy",
    "batch_campaign_per_contact_status",
)


class ProbeMisuseError(Exception):
    """The harness was asked to do something whose result could not be trusted.

    Distinct from a failing probe: a failing probe is evidence, this is a bug in the
    run. It is raised rather than reported so a misused probe can never contribute a
    row to a scorecard.
    """


def inconclusive(name: str, reason: str, **measurements: int | float | str | Decimal) -> SubCheck:
    """A probe that ran and could not decide. See the module docstring for why this is
    a prefixed `not_run` rather than a fourth status."""
    return not_run(name, f"INCONCLUSIVE — {reason}", **measurements)


# --- seams the runner supplies ------------------------------------------------
#
# Types, not prose, so the wiring slice knows exactly what to hand over. Every one of
# them is OPTIONAL at the input boundary: absent seam ⇒ NOT RUN with the reason, never a
# silently skipped row.


class KbEngine(Protocol):
    """The three KB methods, narrowed from `VoiceEngine`.

    Narrower than the full Protocol on purpose: these probes must run against a stub
    that implements only the KB surface (a linkage-blind list, a delete that leaves the
    agent's reference dangling), and a probe that demanded `verify_webhook` too could
    not be pointed at one.
    """

    async def attach_kb(self, ref: EngineAgentRef, source: KBSourceRef) -> EngineKBRef: ...

    async def detach_kb(self, ref: EngineAgentRef, kb: EngineKBRef) -> None: ...

    async def list_kb(self, ref: EngineAgentRef) -> list[EngineKBRef]: ...


#: Reads back the KB handles the AGENT's own configuration references — NOT the account
#: KB list. The distinction is the whole of D-41 question (b): `DELETE /knowledgebase/
#: {rag_id}` removes the knowledge base, and whether the agent object still points at it
#: is a different object's state.
#:
#: `VoiceEngine.get_agent` now supplies this seam (`agent_ref_reader_from_engine`), which
#: is what makes the question askable through the adapter at all. It returns **None** for
#: "the agent's references could not be read" — an empty list would say "the agent
#: references nothing", and those are opposite answers: one closes D-41 with "detach is a
#: single call", the other is the adapter admitting it could not find the field. Only one
#: of them is evidence.
AgentKbRefReader = Callable[[EngineAgentRef], Awaitable[Sequence[str] | None]]

#: Places a live call and reports whether the agent still answered from a source we
#: withdrew. The behavioural substitute for the read-back above; needs PSTN and credit.
#: Takes an opaque question id — never a question — for hard rule 6.
WithdrawnSourceStillAnswered = Callable[[EngineAgentRef, str], Awaitable[bool]]

#: Scores ONE retrieval question. Returns a boolean and a latency; the question text and
#: the agent's answer never cross this boundary.
RetrievalScorer = Callable[[str], Awaitable["RetrievalOutcome"]]


@dataclass(frozen=True, slots=True)
class RetrievalOutcome:
    """One scored retrieval. `question_id` is an opaque handle into the operator's own
    Telugu question sheet, which lives outside the repo with the recordings."""

    question_id: str
    answered: bool
    latency_ms: float | None = None


@dataclass(frozen=True, slots=True)
class KbProbeAgent:
    """An agent to probe with, and the source to attach to it."""

    ref: EngineAgentRef
    source: KBSourceRef


@dataclass(frozen=True, slots=True)
class SlowEndpointObservation:
    """What the ENGINE did when our custom-function endpoint was slow or broken.

    `behaviour` is the vendor-side outcome an operator can actually observe on the call:
      * `answered`  — the engine waited for us and used the result;
      * `apologised` — the engine gave up and said something to the caller;
      * `hung`      — dead air, the call stalled;
      * `dropped`   — the call ended.
    `gave_up_after_ms` is the measured wait before it stopped waiting, and is None when
    the engine did not give up (or when nobody timed it — ABSENT, not zero).
    """

    injected_delay_ms: int
    behaviour: Literal["answered", "apologised", "hung", "dropped"]
    gave_up_after_ms: int | None = None


@dataclass(frozen=True, slots=True)
class HistoryObservation:
    """Per-turn LLM input accounting for ONE long call (H1, TRD §6.1).

    Token counts, not cost: under D-36 the default LLM is Sarvam 105B at ₹0.00 per
    token, so the LLM leg's COST is zero however the history is handled and cannot
    distinguish anything. Whoever reaches for the cost breakdown here will find a
    column of zeros that looks like a measurement.
    """

    turn_index: int
    input_tokens: int | None = None
    cached_input_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ContactOutcome:
    """One contact in the 10-contact batch. Ids and counts only — no numbers."""

    contact_id: str
    attempts: int
    terminal_status: str | None
    #: The outcomes that triggered each retry, in order.
    retried_after: tuple[str, ...] = ()


#: Outcomes Bolna's batch documentation names as retry triggers (No Answer, Busy,
#: Failed, Error, Voicemail; ≤3 attempts, increasing delays) — TRD §5, and re-checked
#: Aug 2026 against their batch-calling page, which describes this as DASHBOARD
#: configuration and publishes no API mechanics. A retry from anything outside this set
#: is a documentation defect worth more than a passing row.
DOCUMENTED_RETRY_OUTCOMES: frozenset[str] = frozenset(
    {"no-answer", "busy", "failed", "error", "voicemail"}
)
DOCUMENTED_MAX_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class ProbeOutput:
    """A probe's slice of the gate: its rows, plus anything it learned about US.

    `findings` are places OUR adapter or OUR contract cannot answer the question. They
    are never scored — a gap on our side is not a vendor failure — but they are the
    output of this slice that no amount of reading the vendor's docs would produce.
    """

    checks: tuple[SubCheck, ...]
    findings: tuple[str, ...] = ()


# --- 1(a). Does the KB list carry the agent linkage? --------------------------


async def probe_kb_agent_linkage(
    engine: KbEngine,
    primary: KbProbeAgent,
    control: KbProbeAgent,
) -> ProbeOutput:
    """D-41 question (a), answered WITHOUT reading a vendor payload.

    Why a second agent. `list_kb` attributes strictly — our single account holds every
    tenant's agents, so a row that does not name the agent is not counted (bolna.py).
    The consequence if the linkage field is absent or named differently is that
    `list_kb` returns `[]` for everyone: every agent reports as holding no knowledge
    base, publish's read-back proves nothing, and D-41's detach verification silently
    passes over text that is still live. That is a wrong answer wearing the costume of
    a working feature, and it is cross-tenant.

    An empty list is therefore ambiguous by construction, and the probe's whole job is
    to disambiguate it. The control agent separates the three worlds:

      * primary's handle in primary's list, control's handle only in control's ⇒ the
        linkage exists AND is the field we filter on. PASS.
      * control's handle appears in primary's list ⇒ the response is not agent-scoped
        and our filter is not filtering: one tenant's knowledge attributed to another
        tenant's agent. FAIL, and the worst outcome of the four.
      * both lists empty ⇒ either the linkage is missing/renamed or nothing was
        attached at all. Those are opposite conclusions, so the probe asks a third
        question: DELETE the handle POST handed back. A delete the engine ACCEPTS
        proves the knowledge base existed and the list simply did not attribute it ⇒
        FAIL, definitively, with no raw payload needed. A delete it rejects means we
        never had a KB to list ⇒ INCONCLUSIVE, because a broken attach cannot testify
        about a list.
      * anything else (one side populated, one side empty) ⇒ INCONCLUSIVE: a partial
        list is as likely to be propagation delay as it is to be a shape problem, and
        guessing between them is exactly what this gate exists to stop.

    Rejected alternative: fetching `/knowledgebase/all` here and inspecting the row for
    an `agent_id` key. It is the direct answer and it is forbidden — hard rule 2 puts
    vendor shapes in `engine/` only, and a probe that duplicated the parse would answer
    a question about ITS parse rather than about the adapter's. Reading the shape needs
    a capture hook inside the adapter, which this slice must not add; the finding below
    records that, and the fixture-recorder slice owns the transport-level capture.

    DESTRUCTIVE: this probe attaches and then removes what it attached. Point it at
    pilot agents, never at a published client agent.
    """
    findings: list[str] = []
    try:
        primary_handle = await engine.attach_kb(primary.ref, primary.source)
        control_handle = await engine.attach_kb(control.ref, control.source)
    except Exception as exc:
        return ProbeOutput(
            checks=(
                inconclusive(
                    "kb_list_carries_agent_linkage",
                    "attach_kb failed, so there was nothing to list: "
                    f"{type(exc).__name__}. Re-run after gate 2 passes.",
                ),
            )
        )

    listed_primary = await engine.list_kb(primary.ref)
    listed_control = await engine.list_kb(control.ref)
    measurements: dict[str, int | float | str | Decimal] = {
        "rows_attributed_to_primary": len(listed_primary),
        "rows_attributed_to_control": len(listed_control),
    }

    check: SubCheck
    if control_handle in listed_primary or primary_handle in listed_control:
        check = failed(
            "kb_list_carries_agent_linkage",
            "The KB list is NOT agent-scoped: one agent's list contains another "
            "agent's handle. Our account holds every tenant's agents, so this is a "
            "cross-tenant attribution bug the moment two clients are live. "
            "CONSEQUENCE: `list_kb` cannot be used as the detach read-back (D-41) "
            "until the adapter can filter on a field that really scopes the row; "
            "publish's verification must not ship on this list as it stands.",
            **measurements,
        )
    elif primary_handle in listed_primary and control_handle in listed_control:
        check = passed(
            "kb_list_carries_agent_linkage",
            "Each agent's list contains its own handle and not the other's — the "
            "linkage field exists and is the one `list_kb` filters on. D-41's "
            "read-back verification stands as written.",
            **measurements,
        )
    elif not listed_primary and not listed_control:
        deleted = await _delete_is_accepted(engine, primary.ref, primary_handle)
        measurements["delete_accepted_handle"] = int(deleted)
        if deleted:
            check = failed(
                "kb_list_carries_agent_linkage",
                "The knowledge base EXISTS (DELETE accepted the handle POST returned) "
                "but no listed row named the agent: the linkage field is absent or "
                "carries a different name. CONSEQUENCE: `list_kb` today reports EVERY "
                "agent as holding no knowledge base — a wrong answer that looks like a "
                "working feature — so D-41's detach read-back proves nothing and the "
                "adapter needs the real field name before publish can trust it.",
                **measurements,
            )
        else:
            check = inconclusive(
                "kb_list_carries_agent_linkage",
                "Both lists were empty AND the engine refused to delete the handle it "
                "returned, so we cannot tell a linkage-blind list from an attach that "
                "never took effect. Re-run; if it repeats, the attach path is the "
                "defect and this question is not answerable until it is fixed.",
                **measurements,
            )
    else:
        check = inconclusive(
            "kb_list_carries_agent_linkage",
            "One agent's list was populated and the other's was empty. That is as "
            "consistent with propagation delay as with a shape problem; re-run after a "
            "pause before concluding anything.",
            **measurements,
        )

    findings.append(
        "Answering (a) by READING the list row's fields is impossible from outside "
        "`apps/api/engine/` (hard rule 2), and the adapter exposes no raw-response "
        "capture hook. This probe therefore answers it behaviourally (attach → list → "
        "delete). If the pilot needs the row shape itself as a fixture, that capture "
        "belongs in the adapter/transport, owned by the fixture-recorder slice — not "
        "here."
    )
    await _best_effort_detach(engine, primary.ref, primary_handle)
    await _best_effort_detach(engine, control.ref, control_handle)
    return ProbeOutput(checks=(check,), findings=tuple(findings))


def agent_ref_reader_from_engine(engine: object) -> AgentKbRefReader | None:
    """Derive the D-41 (b) instrument from an adapter, or None if it has no read-back.

    WHY DUCK-TYPED RATHER THAN `isinstance(engine, VoiceEngine)`. The engine the runner
    hands over may be a narrowed double (this module's probes deliberately accept
    `KbEngine`, three methods), and demanding the whole Protocol would refuse a perfectly
    good reader. `getattr` asks the only question that matters: can this object be asked
    what an agent references?

    The reader passes the adapter's tri-state through untouched. `AgentSnapshot
    .knowledge_base_refs_readable` is False when the adapter could not FIND the reference
    field, and flattening that to `[]` here would turn "we could not tell" into "the
    agent references nothing" — the single most expensive mistranslation available in
    this file, because it answers D-41 in the direction that adds no work to our code.
    """
    read = getattr(engine, "get_agent", None)
    if read is None:
        return None

    async def reader(ref: EngineAgentRef) -> Sequence[str] | None:
        snapshot: AgentSnapshot = await read(ref)
        if not snapshot.knowledge_base_refs_readable:
            return None
        return snapshot.knowledge_base_refs

    return reader


async def _delete_is_accepted(engine: KbEngine, ref: EngineAgentRef, kb: EngineKBRef) -> bool:
    """Does the engine accept a DELETE for this handle? A `True` is proof the knowledge
    base existed — the contract requires detaching an unknown handle to RAISE (D-41)."""
    try:
        await engine.detach_kb(ref, kb)
    except Exception:
        return False
    return True


async def _best_effort_detach(engine: KbEngine, ref: EngineAgentRef, kb: EngineKBRef) -> None:
    """Clean up what the probe attached, without letting cleanup rewrite the verdict.

    A raise here is expected in the normal case — the probe may already have deleted
    the handle as evidence — so it is swallowed. It is swallowed ONLY in cleanup, and
    never anywhere a swallowed exception could make a probe look green.
    """
    with contextlib.suppress(Exception):
        await engine.detach_kb(ref, kb)


# --- 1(b). Does deleting a KB clear the agent's reference? --------------------


async def probe_kb_delete_clears_agent_reference(
    engine: KbEngine,
    agent: KbProbeAgent,
    *,
    agent_ref_reader: AgentKbRefReader | None = None,
    still_answered: WithdrawnSourceStillAnswered | None = None,
    withdrawn_question_id: str | None = None,
) -> ProbeOutput:
    """D-41 question (b): after `DELETE /knowledgebase/{rag_id}`, does the AGENT still
    point at the dead handle?

    Why it matters more than it sounds. D-41 makes publish detach-then-attach and makes
    a failed detach ABORT the publish. If the delete leaves the agent's config holding a
    dangling `rag_id`, then detach is not one call — it is a delete PLUS an agent update
    — and every publish that skipped the second call left the agent pointing at
    knowledge that no longer exists. Detach does NOT become optional in that world; it
    grows a step. This is the answer that adds work to our code, which is why it must be
    measured rather than assumed either way.

    Three instruments, in descending order of authority:
      1. `agent_ref_reader` — read the agent object back and look for the handle. Direct,
         and now derivable from any adapter implementing `VoiceEngine.get_agent`
         (`agent_ref_reader_from_engine`). It may DECLINE by returning None, which is a
         third outcome rather than a negative one: see the branch below.
      2. `still_answered` — place a call and ask something only the withdrawn source
         could answer. Behavioural, slower, needs PSTN and credit, and answers the
         question the client actually cares about.
      3. Neither ⇒ INCONCLUSIVE with a finding. Never a pass: "nothing told us the
         reference survived" and "the reference was cleared" are different sentences.

    Either way it first re-proves the D-41 invariant it can prove: after the delete, the
    handle must be gone from `list_kb`. A delete the KB list still shows is a detach
    that did nothing, which is the silent lie D-41 was written about.
    """
    try:
        handle = await engine.attach_kb(agent.ref, agent.source)
        await engine.detach_kb(agent.ref, handle)
    except Exception as exc:
        return ProbeOutput(
            checks=(
                inconclusive(
                    "kb_delete_clears_agent_reference",
                    "The attach/delete round trip itself failed "
                    f"({type(exc).__name__}), so nothing can be said about what the "
                    "agent references afterwards.",
                ),
            )
        )
    still_listed = handle in await engine.list_kb(agent.ref)

    checks: list[SubCheck] = []
    findings: list[str] = []
    if still_listed:
        # Not the question asked, but a stronger finding than the one asked for: the
        # read-back the whole contract rests on has just contradicted the call.
        checks.append(
            failed(
                "kb_delete_clears_agent_reference",
                "The handle is STILL in `list_kb` after a delete the engine accepted. "
                "The detach did not remove anything, which is exactly the silent lie "
                "D-41 forbids. CONSEQUENCE: publish must not treat a 2xx delete as "
                "removal; the read-back becomes mandatory and a still-listed handle "
                "must abort the publish.",
                handle_still_listed=1,
            )
        )
        return ProbeOutput(checks=tuple(checks), findings=tuple(findings))

    agent_refs: Sequence[str] | None = None
    reader_error: str | None = None
    if agent_ref_reader is not None:
        try:
            agent_refs = await agent_ref_reader(agent.ref)
        except Exception as exc:
            # The read-back can fail for reasons that say nothing about D-41: an unknown
            # agent ref in the inputs file, an endpoint path that is itself an unverified
            # vendor claim (`BolnaEngine.get_agent`), a throttle. None of those is a
            # verdict, and none of them may take the rest of gate 8 down with them — this
            # probe runs mid-scorecard on the one day the vendor is being exercised.
            # Type name only: an httpx error's `str()` carries the request URL.
            reader_error = type(exc).__name__

    if agent_refs is not None:
        dangling = handle in agent_refs
        if dangling:
            checks.append(
                failed(
                    "kb_delete_clears_agent_reference",
                    "The agent config still references the deleted `rag_id`. "
                    "CONSEQUENCE: `detach_kb` grows a SECOND call (an agent update "
                    "clearing the reference) and stays mandatory — D-41's "
                    "detach-then-attach ordering is unchanged, but its first step is "
                    "now two operations, and a publish that did only the delete has "
                    "left the agent pointing at knowledge that no longer exists.",
                    agent_refs_after_delete=len(agent_refs),
                )
            )
        else:
            checks.append(
                passed(
                    "kb_delete_clears_agent_reference",
                    "Deleting the knowledge base also cleared the agent's reference; "
                    "`detach_kb` remains a single call as D-41 assumes.",
                    agent_refs_after_delete=len(agent_refs),
                )
            )
    elif still_answered is not None and withdrawn_question_id is not None:
        answered = await still_answered(agent.ref, withdrawn_question_id)
        if answered:
            checks.append(
                failed(
                    "kb_delete_clears_agent_reference",
                    "On a live call the agent still answered from the WITHDRAWN "
                    "source. Whatever the config says, the engine is still serving "
                    "deleted knowledge. CONSEQUENCE: the same second call as above, "
                    "plus a publish-time verification that survives caching — a "
                    "superseded price can still be quoted today.",
                    behavioural_probe=1,
                )
            )
        else:
            checks.append(
                passed(
                    "kb_delete_clears_agent_reference",
                    "On a live call the agent no longer answered from the withdrawn "
                    "source (behavioural evidence; the agent object itself was not "
                    "read back).",
                    behavioural_probe=1,
                )
            )
    elif reader_error is not None:
        checks.append(
            inconclusive(
                "kb_delete_clears_agent_reference",
                f"The agent read-back raised ({reader_error}), so nothing can be said "
                "about what the agent references. Check that the agent ref in the inputs "
                "file exists on the account and that the read-back endpoint answered at "
                "all — its path is an unverified vendor claim (`BolnaEngine.get_agent`), "
                "and a 404 there is our defect, not the vendor's answer.",
            )
        )
    elif agent_ref_reader is not None:
        # The reader ran and DECLINED. That is a different fact from "no instrument", and
        # it is itself a finding about the vendor's agent object: the adapter walked what
        # the engine returned and found none of the field names a KB reference might use.
        # It is emphatically NOT "the reference was cleared" — recording it as a pass is
        # the one way this probe could answer D-41 in the direction that adds no work to
        # our code while measuring nothing.
        checks.append(
            inconclusive(
                "kb_delete_clears_agent_reference",
                "The agent read-back ran and could not locate any knowledge-base "
                "reference field in the agent object, so it cannot say whether the "
                "handle dangles. This is NOT evidence that the reference was cleared. "
                "Capture one raw agent payload and either name the real field in "
                "`bolna._AGENT_KB_REF_KEYS` or record that the agent object carries no "
                "KB reference at all — at which point the question is answered by the "
                "shape rather than by this probe.",
            )
        )
        findings.append(
            "D-41 (b) REACHED THE ADAPTER AND STOPPED AT THE FIELD NAME. "
            "`VoiceEngine.get_agent` exists now, so the agent object IS read back; what "
            "is still unknown is where — or whether — Bolna's agent object references a "
            "`rag_id`. Nothing in their published documentation says, so "
            "`bolna._AGENT_KB_REF_KEYS` is a guessed set of names and the adapter reports "
            "`knowledge_base_refs_readable=False` rather than an empty list. One captured "
            "agent payload settles it."
        )
    else:
        checks.append(
            inconclusive(
                "kb_delete_clears_agent_reference",
                "No instrument was supplied. `list_kb` reads the KB LIST, not the "
                "agent's own reference, so this run cannot answer the question — supply "
                "an engine whose adapter implements `get_agent` (the reader is derived "
                "from it automatically) or `still_answered` (a live call).",
            )
        )
        findings.append(
            "No agent read-back was wired for this run. `VoiceEngine.get_agent` is on the "
            "contract and `agent_ref_reader_from_engine` derives the reader from any "
            "adapter that implements it, so an unsupplied reader now means the engine "
            "handed to the harness has none — not that the contract lacks the method."
        )
    return ProbeOutput(checks=tuple(checks), findings=tuple(findings))


# --- 2. Telugu retrieval, and the one-way door -------------------------------


class KbModeLedger:
    """Makes the multilingual mode's immutability impossible for an operator to trip on.

    The mode is fixed when the knowledge base is CREATED and cannot be changed
    afterwards (D-33). The failure it invites is mundane and expensive: a second run
    "just re-testing in the other mode" against the same `rag_id`, producing a number
    that describes neither mode, and a one-way door walked through on the strength of
    it. The ledger refuses that at the call site instead of trusting a note in a
    runbook, and it refuses loudly (`ProbeMisuseError`) because a quiet refusal would be one
    more thing to read past at 1am.
    """

    def __init__(self) -> None:
        self._modes: dict[EngineKBRef, str] = {}

    def record(self, kb: EngineKBRef, mode: str) -> None:
        known = self._modes.setdefault(kb, mode)
        if known != mode:
            raise ProbeMisuseError(
                f"knowledge base {kb!r} was created in mode {known!r}; the mode is "
                f"IMMUTABLE at creation, so it cannot now be measured as {mode!r}. "
                "Create a NEW knowledge base for the other mode."
            )

    def mode_of(self, kb: EngineKBRef) -> str | None:
        return self._modes.get(kb)


async def probe_telugu_retrieval(
    *,
    kb_handle: EngineKBRef,
    kb_mode: str,
    question_ids: Sequence[str],
    builtin: RetrievalScorer | None,
    external: RetrievalScorer | None,
    ledger: KbModeLedger,
    min_recall: float = 0.8,
) -> ProbeOutput:
    """Measure BOTH retrieval routes in one run, because the door only opens once.

    Telugu is not named in Bolna's multilingual mode (Hindi and Tamil are) and the mode
    is immutable at KB creation, so if the built-in KB retrieves Telugu poorly the
    fallback is the external custom-function route (TRD §6.2) — and the session where
    you could still have measured it is over. Hence the shape of this probe: the
    built-in result is reported, but it is NOT allowed to stand alone. Without the
    external comparison the fallback row comes back NOT RUN with the door named in its
    reason, so the scorecard cannot be read as "built-in is fine, we're done".

    `min_recall` defaults to 0.8 and that number is CHOSEN here, not vendor-documented:
    TRD §6.2's tier model has T0 compiled context answering ~80% with zero retrieval, so
    a retrieval tier scoring below that is worse than the prompt we already compile.
    Override it explicitly rather than arguing with it silently.

    Hard rule 6: `question_ids` are opaque; the questions and answers stay in the
    operator's sheet with the recordings, and no scorer output carries text.
    """
    if not question_ids:
        raise ProbeMisuseError("probe_telugu_retrieval needs at least one question id")
    ledger.record(kb_handle, kb_mode)

    checks: list[SubCheck] = []
    findings: list[str] = []

    if builtin is None:
        checks.append(
            not_run(
                "telugu_builtin_kb_retrieval",
                "No built-in-KB scorer supplied (needs a live agent, a Telugu FAQ "
                "uploaded to the rag_id KB, and PSTN calls).",
                kb_mode=kb_mode,
            )
        )
        builtin_recall: float | None = None
    else:
        builtin_recall, builtin_measurements = await _score(builtin, question_ids)
        detail = (
            f"Built-in KB (mode {kb_mode!r}) answered "
            f"{builtin_measurements['answered']}/{len(question_ids)} Telugu questions."
        )
        if builtin_recall >= min_recall:
            checks.append(
                passed(
                    "telugu_builtin_kb_retrieval",
                    detail + " At or above the T0 floor, so v1 keeps in-call retrieval "
                    "on the built-in KB as D-33 assumes.",
                    kb_mode=kb_mode,
                    min_recall=min_recall,
                    **builtin_measurements,
                )
            )
        else:
            checks.append(
                failed(
                    "telugu_builtin_kb_retrieval",
                    detail + f" Below the {min_recall:.0%} floor (TRD §6.2: T0 compiled "
                    "context alone answers ~80% with no retrieval at all). "
                    "CONSEQUENCE: D-33's named fallback triggers — in-call retrieval "
                    "moves to the external custom-function route and we accept the "
                    "+150-400ms round trip masked by the T3 filler utterance. The mode "
                    "cannot be changed on this knowledge base; a different mode means a "
                    "NEW one.",
                    kb_mode=kb_mode,
                    min_recall=min_recall,
                    **builtin_measurements,
                )
            )

    if external is None:
        checks.append(
            not_run(
                "telugu_external_kb_fallback",
                "The custom-function fallback was NOT measured in this session. The KB "
                "mode is immutable at creation, so a built-in result on its own cannot "
                "be acted on: if Telugu retrieval is poor there is no later session in "
                "which this comparison is still cheap. Measure both, or record the "
                "gate as unfinished.",
            )
        )
        if builtin_recall is not None and builtin_recall < min_recall:
            findings.append(
                "The built-in KB scored below the floor and the external fallback was "
                "not measured alongside it — the one-way door (immutable KB mode) has "
                "been walked up to without the comparison D-33 requires. Re-open the "
                "session before choosing."
            )
    else:
        external_recall, external_measurements = await _score(external, question_ids)
        if external_recall >= min_recall:
            checks.append(
                passed(
                    "telugu_external_kb_fallback",
                    "The external custom-function route reached the floor on the same "
                    "Telugu question set, so D-33's fallback is real and available.",
                    min_recall=min_recall,
                    **external_measurements,
                )
            )
        else:
            checks.append(
                failed(
                    "telugu_external_kb_fallback",
                    "The external route ALSO scored below the floor on the same "
                    "questions. CONSEQUENCE: this is no longer a route choice — "
                    "neither path answers Telugu well enough, and the D-28 provider "
                    "bake-off (retrieval quality, not just Mumbai latency) has to run "
                    "before in-call retrieval is promised to a client at all.",
                    min_recall=min_recall,
                    **external_measurements,
                )
            )
        if builtin_recall is not None and builtin_recall < min_recall <= external_recall:
            findings.append(
                "Telugu retrieval is materially better on the external route than in "
                "the built-in multilingual mode. TRD §6.2's in-call KB choice inverts, "
                "and the 100ms tool budget (below) becomes load-bearing rather than "
                "advisory."
            )
    return ProbeOutput(checks=tuple(checks), findings=tuple(findings))


async def _score(
    scorer: RetrievalScorer, question_ids: Sequence[str]
) -> tuple[float, dict[str, int | float | str | Decimal]]:
    """Recall plus the latencies, with nothing text-shaped kept."""
    answered = 0
    latencies: list[float] = []
    for qid in question_ids:
        outcome = await scorer(qid)
        answered += int(outcome.answered)
        if outcome.latency_ms is not None:
            latencies.append(outcome.latency_ms)
    measurements: dict[str, int | float | str | Decimal] = {
        "questions": len(question_ids),
        "answered": answered,
        "recall": round(answered / len(question_ids), 3),
    }
    # Absent ≠ zero: a latency key only appears if something was actually timed.
    if latencies:
        measurements["retrieval_p50_ms"] = round(percentile(latencies, 0.50), 1)
        measurements["retrieval_p95_ms"] = round(percentile(latencies, 0.95), 1)
    return answered / len(question_ids), measurements


# --- 3. The custom-function tool-call budget ---------------------------------


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile: the p95 IS one of the observed samples.

    Interpolating (numpy's default) invents a value between two measurements, which is
    the one thing a pilot artefact must not do — and with the sample sizes here (tens,
    not thousands) the interpolated number moves with the estimator rather than with
    the vendor.
    """
    if not values:
        raise ProbeMisuseError("percentile of an empty sample")
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]


def probe_tool_call_budget(
    *,
    latencies_ms: Sequence[float] | None,
    slow_endpoint: Sequence[SlowEndpointObservation] | None,
    budget_ms: float = 100.0,
    min_samples: int = 20,
) -> ProbeOutput:
    """The 100ms in-call budget, and the undocumented ceiling behind it.

    Two independent questions, two rows, because they fail differently:

    * **p95 against the budget.** CLAUDE.md gives the in-call RAG tool endpoint a 100ms
      budget and says to measure it. Under `min_samples` observations the row is NOT
      RUN, not a number: a p95 over a handful of samples is the maximum wearing a
      percentile's name.
    * **What the engine does when we are slow or broken.** This is the one that decides
      whether T3 retrieval is viable at all, and Bolna documents NO tool-call timeout,
      so the ceiling is unmeasured rather than generous. Dead air on a Telugu call is
      worse than a slow answer, and a caller hearing nothing for four seconds has
      already formed a view of the client's business.
    """
    checks: list[SubCheck] = []
    findings: list[str] = []

    if not latencies_ms:
        checks.append(
            not_run(
                "custom_function_tool_call_budget",
                "No tool-call latencies were measured (needs a live agent calling our "
                "custom-function endpoint).",
            )
        )
    elif len(latencies_ms) < min_samples:
        checks.append(
            not_run(
                "custom_function_tool_call_budget",
                f"Only {len(latencies_ms)} samples; a p95 needs at least {min_samples} "
                "or it is just the slowest call with a percentile's name on it.",
                samples=len(latencies_ms),
            )
        )
    else:
        p50 = percentile(latencies_ms, 0.50)
        p95 = percentile(latencies_ms, 0.95)
        measurements: dict[str, int | float | str | Decimal] = {
            "samples": len(latencies_ms),
            "tool_call_p50_ms": round(p50, 1),
            "tool_call_p95_ms": round(p95, 1),
            "budget_ms": budget_ms,
        }
        if p95 <= budget_ms:
            checks.append(
                passed(
                    "custom_function_tool_call_budget",
                    "Tool-call p95 is inside the 100ms in-call budget, so the external "
                    "KB route is viable on latency grounds.",
                    **measurements,
                )
            )
        else:
            checks.append(
                failed(
                    "custom_function_tool_call_budget",
                    "Tool-call p95 exceeds the in-call budget. CONSEQUENCE: T3 cold "
                    "lookup over the external route needs the filler utterance to be "
                    "mandatory rather than a mask of last resort, and if the overshoot "
                    "is large the external fallback stops being a fallback — which "
                    "makes the built-in KB's Telugu quality (above) decisive rather "
                    "than preferable.",
                    **measurements,
                )
            )

    if not slow_endpoint:
        checks.append(
            not_run(
                "custom_function_slow_endpoint_behaviour",
                "Nobody made the endpoint slow or broken, so the vendor's timeout "
                "ceiling remains UNMEASURED — not generous, unmeasured. This is the "
                "observation that decides whether T3 retrieval is viable at all.",
            )
        )
    else:
        gave_up = [o for o in slow_endpoint if o.gave_up_after_ms is not None]
        hung = [o for o in slow_endpoint if o.behaviour in ("hung", "dropped")]
        obs: dict[str, int | float | str | Decimal] = {
            "injections": len(slow_endpoint),
            "max_injected_delay_ms": max(o.injected_delay_ms for o in slow_endpoint),
        }
        if gave_up:
            # ABSENT unless somebody timed it — this key never gets a zero default.
            obs["observed_timeout_ceiling_ms"] = min(
                o.gave_up_after_ms for o in gave_up if o.gave_up_after_ms is not None
            )
        if hung:
            checks.append(
                failed(
                    "custom_function_slow_endpoint_behaviour",
                    "A slow or failing endpoint left the call in dead air (or ended "
                    "it). CONSEQUENCE: our endpoint must answer within its own hard "
                    "deadline and return a 'don't know' rather than block — the T4 "
                    "refuse-and-escalate path, not the retrieval path, is what a slow "
                    "provider must fall into. It also rules out any synchronous "
                    "provider call inside the tool endpoint.",
                    **obs,
                )
            )
        elif gave_up:
            checks.append(
                passed(
                    "custom_function_slow_endpoint_behaviour",
                    "The engine stops waiting and keeps the call alive (the agent "
                    "speaks rather than stalling). The measured ceiling is now OUR "
                    "endpoint's deadline budget — record it in TRD §6.2 beside the "
                    "100ms target.",
                    **obs,
                )
            )
            findings.append(
                "An engine-side tool-call ceiling was OBSERVED where the vendor "
                "documents none. It is a measurement of one account on one day, so it "
                "belongs in the adapter as a marked assumption with the date, never as "
                "a constant somebody later reads as a guarantee."
            )
        else:
            checks.append(
                inconclusive(
                    "custom_function_slow_endpoint_behaviour",
                    "The engine waited out every injected delay without giving up and "
                    "without stalling, so no ceiling was found in the range tested. "
                    "Push the injected delay higher before concluding there is none.",
                    **obs,
                )
            )
    return ProbeOutput(checks=tuple(checks), findings=tuple(findings))


# --- 4. H1 in-call working memory --------------------------------------------


def probe_h1_history_handling(
    observations: Sequence[HistoryObservation] | None,
) -> ProbeOutput:
    """Does the engine truncate or summarise the history, and does it cache?

    TRD §6.1 says the full conversation is resent to the LLM every turn, so input tokens
    grow through the call and minute 10 costs more than minute 1 — the ₹0.15-0.20/min
    LLM figure is a blended average that long calls skew above. Whether Bolna truncates,
    summarises, or enables provider context caching on BYOK keys is UNVERIFIED, and all
    three change the cost model in different directions.

    The instrument is per-turn INPUT TOKENS, not cost, and the reason is worth stating
    because the obvious approach is broken: under D-36 the default LLM is Sarvam 105B at
    ₹0.00 per token, so the LLM leg of `cost_breakdown` is zero on every call however
    the history is handled. A cost-based probe here would produce a tidy column of zeros
    and conclude nothing while looking like a measurement.

    What the shape tells us:
      * strictly rising input tokens ⇒ full resend, no truncation. The blended average
        needs a long-call correction and the Gemini fallback's cost is understated.
      * a plateau or a drop ⇒ truncation or summarisation. Which of the two is NOT
        distinguishable from token counts, and distinguishing them would mean reading
        the prompt the engine sent — caller utterances, hard rule 6. Say "one of the
        two", never guess which.
    Caching is a separate row because `cached_input_tokens` may simply not be reported;
    unreported is ABSENT, and ABSENT is not "caching is off".
    """
    if not observations:
        return ProbeOutput(
            checks=(
                not_run(
                    "h1_history_window_handling",
                    "No per-turn token accounting captured (needs a long live call and "
                    "the provider-side usage view).",
                ),
                not_run(
                    "h1_provider_context_caching",
                    "No per-turn token accounting captured, so cached-token reporting "
                    "was never looked at.",
                ),
            )
        )

    ordered = sorted(observations, key=lambda o: o.turn_index)
    tokens = [(o.turn_index, o.input_tokens) for o in ordered if o.input_tokens is not None]
    checks: list[SubCheck] = []
    findings: list[str] = []

    if len(tokens) < 3:
        checks.append(
            inconclusive(
                "h1_history_window_handling",
                "Fewer than three turns carried an input-token count; a growth shape "
                "cannot be read off two points.",
                turns_with_tokens=len(tokens),
            )
        )
    else:
        counts = [t for _, t in tokens]
        rising = all(b > a for a, b in itertools.pairwise(counts))
        measurements: dict[str, int | float | str | Decimal] = {
            "turns_with_tokens": len(counts),
            "first_turn_input_tokens": counts[0],
            "last_turn_input_tokens": counts[-1],
            "max_turn_input_tokens": max(counts),
        }
        if rising:
            checks.append(
                passed(
                    "h1_history_window_handling",
                    "Input tokens rise every turn: the engine resends the full history "
                    "and does not truncate within the call length tested. TRD §6.1's "
                    "assumption holds; long calls cost more per minute than short ones "
                    "and the blended LLM rate needs a duration correction.",
                    **measurements,
                )
            )
        else:
            checks.append(
                passed(
                    "h1_history_window_handling",
                    "Input tokens stop rising partway through the call: the engine "
                    "truncates OR summarises at a window limit. Which of the two is "
                    "not distinguishable from token counts, and telling them apart "
                    "would mean reading the prompt the engine sent — caller "
                    "utterances, hard rule 6. CONSEQUENCE: long-call LLM cost is "
                    "bounded (good for the model), and the agent may silently lose "
                    "early-call context — which is an eval-suite scenario, not a "
                    "billing note.",
                    **measurements,
                )
            )
            findings.append(
                "History is bounded somewhere inside a call. The eval harness "
                "(OPERATIONS §3) needs a long-call scenario that asserts a fact stated "
                "in minute 1 is still honoured in minute 10 — nothing tests that today."
            )

    cached = [o.cached_input_tokens for o in ordered if o.cached_input_tokens is not None]
    if not cached:
        checks.append(
            not_run(
                "h1_provider_context_caching",
                "No turn reported a cached-token count. That is ABSENT, not zero — the "
                "provider console may simply not surface it for this key, and "
                "recording it as 'caching off' would be an invented measurement.",
            )
        )
    elif any(c > 0 for c in cached):
        checks.append(
            passed(
                "h1_provider_context_caching",
                "Cached input tokens were reported on our BYOK key, so the provider's "
                "context caching is in effect and the long-call cost curve flattens.",
                turns_with_cached_tokens=sum(1 for c in cached if c > 0),
                max_cached_input_tokens=max(cached),
            )
        )
    else:
        checks.append(
            failed(
                "h1_provider_context_caching",
                "Cached-token counts were reported and are zero on every turn: the "
                "engine does not enable provider context caching on our BYOK key. "
                "CONSEQUENCE: the full history is re-billed every turn on any priced "
                "LLM (the Gemini fallback), so R-04's cost step is larger than the "
                "blended figure suggests.",
                turns_with_cached_tokens=0,
            )
        )
    return ProbeOutput(checks=tuple(checks), findings=tuple(findings))


# --- 5. Batch campaign built-ins ---------------------------------------------


def probe_batch_campaign(
    outcomes: Sequence[ContactOutcome] | None,
    *,
    expected_contacts: int = 10,
) -> ProbeOutput:
    """The 10-contact batch: retry policy and per-contact statuses.

    The standing decision this probe settles: TRD §5 lists engine campaigns as
    UNVERIFIED, so dispatch runs in OUR layer and `Campaign.engine_campaign_ref` is an
    `UNWIRED_BASELINE` entry (`scripts/check_wiring.py`) that "closes with the campaign
    built-in verification or is dropped in a two-step". A green row here is what lets
    that column be wired; a red one is what lets it be dropped. NOT RUN closes nothing,
    which is why it says so in its own reason.

    Bolna's published batch behaviour — retry on No Answer / Busy / Failed / Error /
    Voicemail, up to 3 attempts, increasing delays — is DASHBOARD documentation with no
    API mechanics published (re-checked Aug 2026), so what is verified here is that the
    documented policy is what the API actually does.
    """
    if outcomes is None:
        return ProbeOutput(
            checks=(
                not_run(
                    "batch_campaign_retry_policy",
                    "No batch was run. `Campaign.engine_campaign_ref` stays an "
                    "UNWIRED_BASELINE entry — this gate closes it or drops it, and NOT "
                    "RUN does neither.",
                ),
                not_run(
                    "batch_campaign_per_contact_status",
                    "No batch was run, so per-contact statuses were never read.",
                ),
            ),
            findings=(
                "`VoiceEngine` has no batch method at all (dispatch is ours by "
                "decision), so this probe cannot drive a batch through the adapter — "
                "the runner must supply the outcomes from whatever it used. That is a "
                "contract gap to weigh only if the batch built-in passes: adopting it "
                "means a new Protocol method, and rejecting it means our dispatcher "
                "stays the one way per problem.",
            ),
        )

    over_limit = [o for o in outcomes if o.attempts > DOCUMENTED_MAX_ATTEMPTS]
    undocumented = sorted(
        {r for o in outcomes for r in o.retried_after if r not in DOCUMENTED_RETRY_OUTCOMES}
    )
    missing_status = [o for o in outcomes if not o.terminal_status]

    checks: list[SubCheck] = []
    findings: list[str] = []
    retry_measurements: dict[str, int | float | str | Decimal] = {
        "contacts": len(outcomes),
        "max_attempts_observed": max((o.attempts for o in outcomes), default=0),
        "retried_contacts": sum(1 for o in outcomes if o.attempts > 1),
    }
    if over_limit or undocumented:
        reasons = []
        if over_limit:
            reasons.append(
                f"{len(over_limit)} contact(s) exceeded {DOCUMENTED_MAX_ATTEMPTS} attempts"
            )
        if undocumented:
            reasons.append(f"retries fired on undocumented outcomes: {', '.join(undocumented)}")
        checks.append(
            failed(
                "batch_campaign_retry_policy",
                "The batch built-in does not do what its documentation says — "
                + "; ".join(reasons)
                + ". CONSEQUENCE: the engine's retry policy cannot be trusted to "
                "respect our calling-hours and DNC guarantees between attempts, so "
                "dispatch stays in OUR layer and `Campaign.engine_campaign_ref` is "
                "dropped in a two-step (hard rule 8).",
                **retry_measurements,
            )
        )
        findings.append(
            "Every engine-side retry is a dial we did not authorise at that moment: "
            "our DNC additions must propagate before the NEXT dispatch tick (hard rule "
            "5), and an engine that re-dials on its own schedule is outside that "
            "guarantee. Adopting the built-in needs that answered even if the policy "
            "matches the docs."
        )
    else:
        checks.append(
            passed(
                "batch_campaign_retry_policy",
                "Retries stayed within the documented outcomes and attempt ceiling.",
                **retry_measurements,
            )
        )

    if missing_status or len(outcomes) != expected_contacts:
        checks.append(
            failed(
                "batch_campaign_per_contact_status",
                f"{len(missing_status)} of {len(outcomes)} contacts carried no terminal "
                f"status (expected {expected_contacts} contacts). CONSEQUENCE: a batch "
                "we cannot reconcile per contact cannot back a per-lead outcome in the "
                "CRM, which is the only reason to adopt it.",
                contacts=len(outcomes),
                contacts_without_terminal_status=len(missing_status),
            )
        )
    else:
        checks.append(
            passed(
                "batch_campaign_per_contact_status",
                "Every contact ended with a terminal status the batch reported.",
                contacts=len(outcomes),
            )
        )
    return ProbeOutput(checks=tuple(checks), findings=tuple(findings))


# --- the gate ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KnowledgeProbeInputs:
    """Everything gate 8 needs, all optional — the runner's wiring surface.

    Optional is the point: this harness runs on a laptop with no Bolna account, no
    Sarvam key, no number and no credit, and what it must do there is report each
    missing piece as NOT RUN with a reason rather than quietly emit a short gate.
    """

    engine: KbEngine | None = None
    primary_agent: KbProbeAgent | None = None
    control_agent: KbProbeAgent | None = None
    agent_ref_reader: AgentKbRefReader | None = None
    still_answered: WithdrawnSourceStillAnswered | None = None
    withdrawn_question_id: str | None = None
    kb_handle: EngineKBRef | None = None
    kb_mode: str = "multilingual"
    question_ids: tuple[str, ...] = ()
    builtin_scorer: RetrievalScorer | None = None
    external_scorer: RetrievalScorer | None = None
    min_recall: float = 0.8
    tool_call_latencies_ms: tuple[float, ...] | None = None
    slow_endpoint: tuple[SlowEndpointObservation, ...] | None = None
    history: tuple[HistoryObservation, ...] | None = None
    batch_outcomes: tuple[ContactOutcome, ...] | None = None
    ledger: KbModeLedger = field(default_factory=KbModeLedger)


async def run_gate8(inputs: KnowledgeProbeInputs) -> GateRun:
    """Run every gate-8 probe the inputs allow and return the scorecard row.

    The invariant a reader depends on: the returned gate carries exactly `CHECK_NAMES`,
    in that order, on every run. Missing inputs produce NOT RUN rows, never absent ones,
    and `GateRun.status` rolls up pessimistically — one unexecuted probe and the gate
    is not green.
    """
    checks: dict[str, SubCheck] = {}
    findings: list[str] = []

    def absorb(output: ProbeOutput) -> None:
        for check in output.checks:
            checks[check.name] = check
        findings.extend(output.findings)

    if inputs.engine is not None and inputs.primary_agent and inputs.control_agent:
        absorb(
            await probe_kb_agent_linkage(inputs.engine, inputs.primary_agent, inputs.control_agent)
        )
    if inputs.engine is not None and inputs.primary_agent:
        absorb(
            await probe_kb_delete_clears_agent_reference(
                inputs.engine,
                inputs.primary_agent,
                agent_ref_reader=inputs.agent_ref_reader,
                still_answered=inputs.still_answered,
                withdrawn_question_id=inputs.withdrawn_question_id,
            )
        )
    if inputs.kb_handle and inputs.question_ids:
        absorb(
            await probe_telugu_retrieval(
                kb_handle=inputs.kb_handle,
                kb_mode=inputs.kb_mode,
                question_ids=inputs.question_ids,
                builtin=inputs.builtin_scorer,
                external=inputs.external_scorer,
                ledger=inputs.ledger,
                min_recall=inputs.min_recall,
            )
        )
    absorb(
        probe_tool_call_budget(
            latencies_ms=inputs.tool_call_latencies_ms,
            slow_endpoint=inputs.slow_endpoint,
        )
    )
    absorb(probe_h1_history_handling(inputs.history))
    absorb(probe_batch_campaign(inputs.batch_outcomes))

    ordered = tuple(
        checks.get(name)
        or not_run(name, "Probe did not run: its inputs were not supplied to the harness.")
        for name in CHECK_NAMES
    )
    return GateRun(
        number=GATE_NUMBER,
        title=GATE_TITLE,
        checks=ordered,
        findings=tuple(dict.fromkeys(findings)),
    )


# --- wiring into the harness ---------------------------------------------------
#
# `scripts/pilot/runner.py` names this module in OPTIONAL_GATE_MODULES and reads a
# `GATES: {number: runner}` mapping. Everything above this line is seams and arithmetic;
# everything below is how an operator's day-of observations reach them.
#
# WHY A FILE AND NOT CLI FLAGS. `latency.py` (gate 4) and `concurrency.py` (gate 13)
# already answered this question for gates whose inputs are typed in by a human rather
# than measured by the harness: a JSON file under `docs/evidence/` with an env override.
# This gate has more of those inputs than either, so a flag per field would be a shell
# line nobody can review; and the runner's `--attest` vocabulary is CLOSED and owned by
# another module, so extending it means editing someone else's file mid-flight. One way
# per problem: the same seam, the same spelling, a third gate.

#: Where gate 8's observations live, and the override for a run against a copy.
INPUTS_ENV = "CALEVATE_PILOT_GATE8_INPUTS"
DEFAULT_INPUTS_PATH = "docs/evidence/gate8-inputs.json"

#: Reported on every run of this gate, because it governs how its numbers must be read.
#: Nothing in gate 8 is a harness measurement: there is no automatic scorer for "did the
#: agent answer this Telugu question correctly", no way to time a tool call from outside
#: the call, and no token counter of ours inside their prompt. Every number in the inputs
#: file was observed by a person, exactly as gate 4's stopwatch samples are.
OPERATOR_SOURCED_FINDING = (
    "EVERY GATE-8 NUMBER IS OPERATOR-OBSERVED, NOT HARNESS-MEASURED. Retrieval outcomes, "
    "tool-call latencies, per-turn token counts and batch outcomes are typed into the "
    "inputs file by the person who ran the calls (the same arrangement as gate 4's "
    "stopwatch ledger); the harness owns the arithmetic, the thresholds and the verdicts. "
    "The two KB-lifecycle probes are the exception — they drive the adapter live."
)

#: The two D-41 instruments this file deliberately does NOT offer, and why. Both
#: `agent_ref_reader` and `still_answered` must answer about the handle the probe mints
#: DURING the run, so a pre-recorded answer in a JSON file would be an answer about a
#: different handle at a different time — a measurement of nothing, wearing a verdict.
#: The row therefore stays INCONCLUSIVE with the missing-`get_agent` finding attached,
#: which is the true state of the world and is what OPERATIONS §2 already records.
UNSUPPLIABLE_INSTRUMENTS_FINDING = (
    "D-41's dangling-`rag_id` question cannot be answered from an inputs file: both "
    "instruments (an agent read-back, or a live call asking about the withdrawn source) "
    "must address the handle the probe creates during the run, so a pre-recorded answer "
    "would describe a different handle. The read-back is therefore DERIVED FROM THE "
    "ADAPTER — `VoiceEngine.get_agent` via `agent_ref_reader_from_engine` — and runs live "
    "against the handle this run mints. It can still decline: the Bolna adapter reports "
    "`knowledge_base_refs_readable=False` while nobody knows where (or whether) the agent "
    "object holds a `rag_id`, and that declination is reported as INCONCLUSIVE, never as "
    "a cleared reference. The live-call instrument (`still_answered`) remains unwired."
)


class KbSourceInput(BaseModel):
    """A knowledge source to attach during the KB-lifecycle probes.

    The text may live beside the file rather than in it (`text_path`): a Telugu FAQ is
    business content, and `docs/evidence/` is committed — keeping it out of the JSON
    means the evidence file stays reviewable at a glance.
    """

    kb_id: str
    title: str
    text: str | None = None
    text_path: str | None = None

    def resolve(self) -> KBSourceRef:
        if self.text is not None:
            body = self.text
        elif self.text_path is not None:
            body = Path(self.text_path).read_text(encoding="utf-8")
        else:
            raise ProbeMisuseError(
                f"kb source {self.kb_id!r} carries neither `text` nor `text_path`; "
                "attaching an empty knowledge base would measure retrieval against nothing"
            )
        return KBSourceRef(kb_id=self.kb_id, title=self.title, text=body)


class AgentProbeInput(BaseModel):
    """One pilot agent and the source to attach to it. DESTRUCTIVE: the probes attach
    and then delete, so this must name a pilot agent and never a published client one."""

    agent_ref: str
    source: KbSourceInput

    def resolve(self) -> KbProbeAgent:
        return KbProbeAgent(ref=self.agent_ref, source=self.source.resolve())


class RetrievalOutcomeInput(BaseModel):
    """One scored Telugu question. `question_id` is opaque — the question and the
    agent's answer stay in the operator's sheet with the recordings (hard rule 6)."""

    question_id: str
    answered: bool
    latency_ms: float | None = PydanticField(default=None, ge=0)


class SlowEndpointInput(BaseModel):
    injected_delay_ms: int = PydanticField(ge=0)
    behaviour: Literal["answered", "apologised", "hung", "dropped"]
    gave_up_after_ms: int | None = PydanticField(default=None, ge=0)


class HistoryInput(BaseModel):
    turn_index: int = PydanticField(ge=0)
    input_tokens: int | None = PydanticField(default=None, ge=0)
    cached_input_tokens: int | None = PydanticField(default=None, ge=0)


class ContactOutcomeInput(BaseModel):
    contact_id: str
    attempts: int = PydanticField(ge=0)
    terminal_status: str | None = None
    retried_after: list[str] = PydanticField(default_factory=list)


class Gate8Inputs(BaseModel):
    """What the operator supplies. Every field optional; absent stays absent, and an
    absent probe reports NOT RUN with its reason rather than vanishing from the gate."""

    primary_agent: AgentProbeInput | None = None
    control_agent: AgentProbeInput | None = None
    kb_handle: str | None = None
    kb_mode: str = "multilingual"
    #: Defaults to the ids actually scored, in order. Set it explicitly when the sheet
    #: has ten questions and only eight came back — the denominator is the sheet, and a
    #: recall that silently shrinks its denominator is a recall that always looks good.
    question_ids: list[str] = PydanticField(default_factory=list)
    builtin_retrieval: list[RetrievalOutcomeInput] = PydanticField(default_factory=list)
    external_retrieval: list[RetrievalOutcomeInput] = PydanticField(default_factory=list)
    #: Bounded to a fraction, because pydantic coerces "0.8 percent of a typo" into a
    #: float perfectly happily: an unbounded threshold above 1.0 makes the retrieval row
    #: impossible to pass and reads as the vendor failing rather than as a typo.
    min_recall: float = PydanticField(default=0.8, ge=0.0, le=1.0)
    tool_call_latencies_ms: list[float] | None = None
    slow_endpoint: list[SlowEndpointInput] | None = None
    history: list[HistoryInput] | None = None
    batch_outcomes: list[ContactOutcomeInput] | None = None

    def resolved_question_ids(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for outcome in [*self.builtin_retrieval, *self.external_retrieval]:
            seen.setdefault(outcome.question_id, None)
        return tuple(self.question_ids) or tuple(seen)


class Gate8InputsError(ValueError):
    """The inputs file exists but cannot be read as evidence.

    Raised rather than tolerated: a partially-parsed file would drop observations
    silently, and a gate that quietly scored six of ten questions is worse than one that
    refused to score any.
    """


def replay_scorer(outcomes: Sequence[RetrievalOutcomeInput]) -> RetrievalScorer:
    """Turn recorded outcomes into the `RetrievalScorer` seam.

    An id with no recorded outcome RAISES rather than scoring `answered=False`: a
    question nobody asked and a question the agent failed are opposite facts, and
    defaulting one to the other would move recall in the direction that passes the gate.
    """
    by_id = {outcome.question_id: outcome for outcome in outcomes}

    async def score(question_id: str) -> RetrievalOutcome:
        recorded = by_id.get(question_id)
        if recorded is None:
            raise ProbeMisuseError(
                f"question {question_id!r} has no recorded outcome in the gate 8 inputs "
                "file. An unasked question is not a failed one — record it or remove it "
                "from `question_ids`."
            )
        return RetrievalOutcome(
            question_id=recorded.question_id,
            answered=recorded.answered,
            latency_ms=recorded.latency_ms,
        )

    return score


def build_probe_inputs(inputs: Gate8Inputs, engine: KbEngine | None) -> KnowledgeProbeInputs:
    """Project the operator's file onto the probe seams.

    `engine` is the live adapter and is used only by the two KB-lifecycle probes, which
    are DESTRUCTIVE (they attach a knowledge base and then delete it). What stops them
    running is the ABSENCE OF AGENTS to point them at: `run_gate8` reaches them only when
    `primary_agent`/`control_agent` are set, so the engine is handed over unconditionally
    here rather than re-guarded. The rejected alternative — nulling the engine as well —
    is a second copy of one rule, and no test can tell the two copies apart, which is how
    a guard survives long after the rule it mirrors has moved.

    See `UNSUPPLIABLE_INSTRUMENTS_FINDING` for the two seams left deliberately unsupplied.
    """
    primary = inputs.primary_agent.resolve() if inputs.primary_agent else None
    control = inputs.control_agent.resolve() if inputs.control_agent else None
    return KnowledgeProbeInputs(
        engine=engine,
        primary_agent=primary,
        control_agent=control,
        # Derived from the adapter, not typed into the file: the reader must answer about
        # the handle the probe mints DURING this run, which no pre-recorded answer can
        # (see `UNSUPPLIABLE_INSTRUMENTS_FINDING`). None when the adapter has no
        # `get_agent`, which the probe reports as an absent instrument rather than a pass.
        agent_ref_reader=agent_ref_reader_from_engine(engine) if engine is not None else None,
        kb_handle=inputs.kb_handle,
        kb_mode=inputs.kb_mode,
        question_ids=inputs.resolved_question_ids(),
        builtin_scorer=(
            replay_scorer(inputs.builtin_retrieval) if inputs.builtin_retrieval else None
        ),
        external_scorer=(
            replay_scorer(inputs.external_retrieval) if inputs.external_retrieval else None
        ),
        min_recall=inputs.min_recall,
        tool_call_latencies_ms=(
            tuple(inputs.tool_call_latencies_ms)
            if inputs.tool_call_latencies_ms is not None
            else None
        ),
        slow_endpoint=(
            tuple(
                SlowEndpointObservation(
                    injected_delay_ms=o.injected_delay_ms,
                    behaviour=o.behaviour,
                    gave_up_after_ms=o.gave_up_after_ms,
                )
                for o in inputs.slow_endpoint
            )
            if inputs.slow_endpoint is not None
            else None
        ),
        history=(
            tuple(
                HistoryObservation(
                    turn_index=o.turn_index,
                    input_tokens=o.input_tokens,
                    cached_input_tokens=o.cached_input_tokens,
                )
                for o in inputs.history
            )
            if inputs.history is not None
            else None
        ),
        batch_outcomes=(
            tuple(
                ContactOutcome(
                    contact_id=o.contact_id,
                    attempts=o.attempts,
                    terminal_status=o.terminal_status,
                    retried_after=tuple(o.retried_after),
                )
                for o in inputs.batch_outcomes
            )
            if inputs.batch_outcomes is not None
            else None
        ),
    )


def load_gate8_inputs(path_str: str | None = None) -> Gate8Inputs | None:
    """Read the operator's file, or None when there is none. Never invents inputs."""
    path = Path(path_str or os.environ.get(INPUTS_ENV) or DEFAULT_INPUTS_PATH)
    if not path.exists():
        return None
    try:
        return Gate8Inputs.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValidationError, ValueError) as exc:
        # The message can quote the file's own content, which may hold a Telugu FAQ or a
        # number the operator pasted by accident. Type and path only (hard rule 6).
        raise Gate8InputsError(
            f"{path} could not be read as gate 8 inputs: {type(exc).__name__}"
        ) from exc


async def run_gate_8(ctx: Any) -> GateRun:
    """Gate 8 for `scripts.pilot.runner`.

    Places no calls of its own — the KB-lifecycle probes drive the adapter's KB surface
    and everything else is replayed observation — so it needs no call budget and can
    never dial. A `ProbeMisuseError` is caught and returned as a BLOCKED gate rather than
    allowed to propagate: it means the run cannot be trusted, and on the day that matters
    it must not also take the remaining gates down with it.
    """
    try:
        inputs = load_gate8_inputs()
    except Gate8InputsError as exc:
        return GateRun(number=GATE_NUMBER, title=GATE_TITLE, blocked=str(exc))

    if inputs is None:
        return GateRun(
            number=GATE_NUMBER,
            title=GATE_TITLE,
            blocked=(
                f"no inputs file at {DEFAULT_INPUTS_PATH} (override with ${INPUTS_ENV}); "
                "it carries the Telugu retrieval scores, the tool-call latencies, the "
                "per-turn token counts and the batch outcomes — all observed on live "
                "calls, none of them derivable here."
            ),
            findings=(OPERATOR_SOURCED_FINDING, UNSUPPLIABLE_INSTRUMENTS_FINDING),
        )

    engine = getattr(ctx, "engine", None)
    try:
        probe_inputs = build_probe_inputs(inputs, engine)
        result = await run_gate8(probe_inputs)
    except ProbeMisuseError as exc:
        return GateRun(number=GATE_NUMBER, title=GATE_TITLE, blocked=f"probe misuse: {exc}")
    except OSError as exc:
        return GateRun(
            number=GATE_NUMBER,
            title=GATE_TITLE,
            blocked=f"a knowledge source named in the inputs file could not be read: "
            f"{type(exc).__name__}",
        )
    return GateRun(
        number=result.number,
        title=result.title,
        checks=result.checks,
        findings=(*result.findings, OPERATOR_SOURCED_FINDING, UNSUPPLIABLE_INSTRUMENTS_FINDING),
    )


GATES = {GATE_NUMBER: run_gate_8}


__all__ = [
    "CHECK_NAMES",
    "DEFAULT_INPUTS_PATH",
    "DOCUMENTED_MAX_ATTEMPTS",
    "DOCUMENTED_RETRY_OUTCOMES",
    "GATES",
    "GATE_NUMBER",
    "GATE_TITLE",
    "INPUTS_ENV",
    "OPERATOR_SOURCED_FINDING",
    "UNSUPPLIABLE_INSTRUMENTS_FINDING",
    "AgentKbRefReader",
    "AgentProbeInput",
    "ContactOutcome",
    "ContactOutcomeInput",
    "Gate8Inputs",
    "Gate8InputsError",
    "HistoryInput",
    "HistoryObservation",
    "KbEngine",
    "KbModeLedger",
    "KbProbeAgent",
    "KbSourceInput",
    "KnowledgeProbeInputs",
    "ProbeMisuseError",
    "ProbeOutput",
    "RetrievalOutcome",
    "RetrievalOutcomeInput",
    "RetrievalScorer",
    "SlowEndpointInput",
    "SlowEndpointObservation",
    "WithdrawnSourceStillAnswered",
    "agent_ref_reader_from_engine",
    "build_probe_inputs",
    "inconclusive",
    "load_gate8_inputs",
    "percentile",
    "probe_batch_campaign",
    "probe_h1_history_handling",
    "probe_kb_agent_linkage",
    "probe_kb_delete_clears_agent_reference",
    "probe_telugu_retrieval",
    "probe_tool_call_budget",
    "replay_scorer",
    "run_gate8",
    "run_gate_8",
]
