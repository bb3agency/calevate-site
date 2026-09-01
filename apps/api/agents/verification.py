"""Did the engine ACCEPT the write, or is it RUNNING it? — the publish read-back.

WHAT WAS WRONG
--------------
`publish_agent` called `create_agent`/`update_agent`, got no exception, and wrote
`status = 'live'`, `engine_agent_ref`, `live_tts_voice` and (through `apply_to_live`)
`live_prompt_id`. Every one of those columns is a claim about the ENGINE, and all of
them were derived from a single fact about OURSELVES: that our HTTP call returned
without raising.

D-64 added `VoiceEngine.get_agent` precisely so that gap could be closed — its docstring
names it: *"A 2xx on the update says the vendor took the bytes. Whether the agent is now
RUNNING that prompt is a different claim, and it is the one a client's compliance
disclosure depends on."* Nothing called it. `AgentSnapshot.carries_prompt_marker`,
`holds_speech` and the three `*_readable` tri-states existed with no production reader,
so the instrument was built and never attached.

WHAT A 2xx DOES NOT RULE OUT
----------------------------
Every one of these produces a 2xx, or produces nothing at all, and none of them is
distinguishable from success without reading the agent back:

* the vendor validated the envelope and dropped a field it did not recognise;
* the vendor applied the write to a *different* task on the same agent;
* the vendor accepted and queued, and the running config is still the old one;
* our adapter's request body drifted from the shape the vendor now expects, so the
  prompt went into a key nobody reads;
* a connection reset arrived AFTER the vendor committed, so we saw a failure on a write
  that landed (this one is the reverse case, and it is why `drift_of` exists as a
  standalone read rather than only as a publish-time step).

THE FOUR VERDICTS, AND WHY `unreadable` IS NOT `applied`
--------------------------------------------------------
    applied      the engine was read back and every checkable property MATCHED.
    not_applied  the engine was read back and a property PROVABLY did not match.
                 A REFUSAL: `publish_agent` raises, the transaction rolls back, and no
                 column claims a script the engine is not holding.
    unreadable   the engine answered and the adapter could not FIND the property. Not
                 a match and not a mismatch — `AgentSnapshot`'s whole `*_readable`
                 doctrine is that those are different facts and only one of them is
                 evidence. Recorded, never counted as proof.
    unreachable  the read-back itself failed. The write may well have landed; we cannot
                 say. Recorded.

`unreadable`/`unreachable` do NOT block the publish, and that is a decision rather than
a softening. On a `create` the write has already happened at the vendor: refusing at
this point rolls our side back and leaves an agent object we can no longer address
(`publish_agent` logs that case as `engine_agent_orphaned`). Refusing would therefore
trade a recorded uncertainty for a guaranteed orphan plus the same uncertainty. What we
do instead is carry the verdict all the way to the screen, so "live" never renders
without saying what was actually confirmed.

HARD RULE 2. Nothing here imports an adapter or sees a vendor field: it consumes
`AgentSnapshot` and `EngineCapabilities` and returns our own verdict. The one import from
`apps.api.engine` is the capability REFUSAL — the seam's own vocabulary, not a vendor's —
and it is the same one every other surface raises for an absent capability.

HARD RULE 6. `detail` names fields and verdicts, never prompt bodies — the strings here
reach a log line and a banner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from calevate_shared.engine import (
    TRUTHFUL_ANSWER_MARKER,
    AgentConfig,
    AgentSnapshot,
    EngineAgentRef,
    VoiceEngine,
)

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.engine import engine_lacks

log = get_logger(__name__)

#: The four verdicts, plus the pre-migration/never-attempted value the COLUMN carries.
#: `not_applied` is never stored: it is a refusal, so the transaction that would have
#: written it does not commit.
VerifyState = Literal["applied", "not_applied", "unreadable", "unreachable"]

#: What `agents.live_verify_state` may hold. `unverified` is the column default and means
#: "no read-back has ever been attempted for this agent" — every row published before this
#: module existed, which is why it is a distinct value from `unreachable` (we tried and
#: could not) rather than folded into it.
StoredVerifyState = Literal["unverified", "applied", "unreadable", "unreachable"]


@dataclass(frozen=True, slots=True)
class PublishVerification:
    """What the engine was actually observed to be holding, one publish at a time."""

    state: VerifyState
    #: Tri-state per property, the `AgentSnapshot` doctrine: None = could not be read.
    prompt_applied: bool | None
    #: **The disclosure in the field that SPEAKS** — the engine's greeting
    #: (`agent_welcome_message` / `introduction`), which is the deterministic first
    #: utterance. This is the property OPERATIONS §7 escalates and the one with the legal
    #: consequence (SEC-COMP §1, hard rule 5).
    #:
    #: It used to be computed from the PROMPT (P3.3), which our own adapter prepends the
    #: line to on the way out — so it read `True` by construction of our own string
    #: formatting and could not have failed for the reason it exists. An incident signal
    #: wired to the wrong half.
    disclosure_applied: bool | None
    #: The disclosure in the PROMPT — the second copy, and the weaker evidence: an
    #: instruction the model may reorder or drop, not an utterance that is played.
    #: Recorded because both adapters deliberately send it in both places (belt and
    #: braces, `bolna._agent_body` argues it), so an engine holding one and not the
    #: other is a fact worth being able to see rather than one to average away. Only a
    #: `control_plane` engine reaches this at all: an externally-deployed one has no agent
    #: record to hold either copy, which is why `verify_publish` refuses it outright.
    #: `None` when the agent volunteers no opening at all — there is no second copy of
    #: an empty string, and `"" in anything` is True, which is a verdict about nothing.
    prompt_disclosure_applied: bool | None
    #: **THE PROPERTY NO TENANT MAY SWITCH OFF** (D-163, hard rule 5). Is
    #: `TRUTHFUL_ANSWER_MARKER` in the prompt the engine is actually holding?
    #:
    #: It is scored SEPARATELY from `prompt_applied` even though both read the same
    #: string, for the reason `disclosure_applied` is scored separately from the script:
    #: the failure mode is specific and asymmetric. `compose_engine_prompt` puts the
    #: directive LAST, which is where a vendor's prompt-length ceiling truncates, so an
    #: engine can hold every word of a client's script — passing the script check
    #: outright — while holding none of the rules that make the agent answer honestly.
    #: Folding the two together would report that agent as fully applied.
    truthful_answer_applied: bool | None
    voice_applied: bool | None
    #: One operator-readable sentence. Never carries a prompt body (hard rule 6).
    detail: str

    @property
    def proven(self) -> bool:
        """Did we POSITIVELY confirm the engine holds what we sent? Never true by
        default — an unread property is not a passed one."""
        return self.state == "applied"

    @property
    def stored_state(self) -> StoredVerifyState:
        """The value `agents.live_verify_state` records. `not_applied` cannot reach a
        column: it is refused before the transaction commits."""
        if self.state == "not_applied":  # pragma: no cover - refused upstream
            raise AssertionError("a not_applied verification must be refused, never stored")
        return self.state


def _voice_expected(engine: VoiceEngine, cfg: AgentConfig) -> str | None:
    """The voice we are entitled to read back, or None when there is nothing to check.

    Two ways there is nothing to check, and they are both genuine rather than excuses:
    the agent has no voice configured, or the ENGINE dictates its own speech
    (`EngineCapabilities.is_ours('tts')` is False), in which case our catalogue value
    addresses nothing on their side and `AgentSnapshot.models.tts_voice` is None BY
    CONTRACT. Comparing against it there would report every publish on such an engine as
    a mismatch, which is the failure mode that teaches an operator to ignore the verdict.

    ⚠ **THE SPEAKER ONLY, NOT THE MODEL, AND THAT IS DELIBERATE SINCE D-358.** The TTS leg
    now sends two strings — `provider_config.model` and `provider_config.voice`/`voice_id`
    — and `AgentSnapshot.models.tts_model` reads the first one back. It is not compared
    here, because whether their platform ECHOES that key is exactly what OPERATIONS §2
    gate 3 has not answered yet: an engine that stores the model and reports it under
    another name would make `held_model` None, and `judge` turns a None into
    `state="unreadable"` — so every publish in the product would stop reporting as applied
    on an unanswered vendor question. The speaker is the string an operator PICKED and the
    one a caller HEARS, so it is the one worth refusing a publish over. When gate 3 says
    what comes back, adding the model here is one line and a `checked` entry.
    """
    if not engine.capabilities.is_ours("tts"):
        return None
    return cfg.models.tts_voice or None


def _greeting_verdict(cfg: AgentConfig, snapshot: AgentSnapshot) -> bool | None:
    """Is the engine's greeting what this agent's notice toggles say it should be?

    TWO QUESTIONS, NOT ONE (D-163), and the second one only exists because a notice can
    now be WITHDRAWN:

    * **An opening was configured** — the ordinary case. Containment, per
      `carries_greeting_marker`: any rendering that kept the text satisfies it.
    * **No opening was configured** — both toggles off. The check inverts: the engine must
      be holding NO greeting. A vendor that kept the previous welcome message is still
      opening every call with a notice our own row says was withdrawn, so a client reading
      "recording notice: off" would be reading something untrue about their phone line.
      That is a provable mismatch and it refuses the publish, exactly as a dropped
      disclosure does — the direction of the error is different, the falsehood is not.

    `None` stays `None` throughout: an unreadable greeting is not evidence either way, and
    that is the whole `AgentSnapshot.*_readable` doctrine.
    """
    if cfg.opening_line.strip():
        return snapshot.carries_greeting_marker(cfg.opening_line)
    if not snapshot.greeting_readable:
        return None
    return not (snapshot.greeting or "").strip()


def judge(engine: VoiceEngine, cfg: AgentConfig, snapshot: AgentSnapshot) -> PublishVerification:
    """Score one read-back against the config it was supposed to apply.

    CONTAINMENT, NOT EQUALITY, for both text properties — `carries_prompt_marker` argues
    it at the Protocol: every engine renders our `AgentConfig` into its own object (ours
    PREPENDS the disclosure line, hard rule 5), so an equality check would fail on a
    correctly applied update and turn this into a test of our own string formatting.

    The disclosure line is checked SEPARATELY from the script and not merely as part of
    it. Hard rule 5 is the one property here with a legal consequence, and an engine that
    kept the script while dropping the greeting would otherwise pass on the script check
    alone — which is exactly the shape of the failure (a field the vendor did not
    recognise) that this whole read-back exists to catch.

    **AND SINCE D-163 SO IS THE TRUTHFUL-ANSWER RULE, which is now the part of hard rule 5
    that cannot be switched off.** The two notices at the top of a call are per-agent
    toggles; the answer to a caller who asks outright is not. `compose_engine_prompt`
    appends `TRUTHFUL_ANSWER_DIRECTIVE` to every prompt every adapter sends, and this
    function reads `TRUTHFUL_ANSWER_MARKER` back off the engine. A proven absence is a
    REFUSAL — the publish rolls back, the agent does not go live — because "we appended
    it" is a fact about our request body and the whole point of this module is that a
    request body is not evidence. It is not folded into the script check: the directive
    sits at the END of the prompt, which is where a vendor's length ceiling truncates, so
    an engine can hold a client's entire script and none of the rules beneath it.

    **AND IT IS CHECKED IN THE GREETING, WHICH IS WHERE IT IS SPOKEN (P3.3).** This
    function used to score the disclosure with `carries_prompt_marker` — against the
    prompt `_agent_body` had just PREPENDED the line to. That verdict was true whenever
    the prompt round-tripped at all, so the single property with a legal consequence
    could not fail for its own reason, and the paragraph above describing "an engine that
    dropped the greeting" described a case the code could not detect. The greeting is now
    its own read (`carries_greeting_marker`) and it is what `disclosure_applied` means;
    the prompt copy is reported beside it, never instead of it.
    """
    prompt = snapshot.carries_prompt_marker(cfg.system_prompt)
    disclosure = _greeting_verdict(cfg, snapshot)
    prompt_disclosure = (
        snapshot.carries_prompt_marker(cfg.opening_line) if cfg.opening_line.strip() else None
    )
    # EVERY prompt the engine will run, not only the one we published. On Bolna a
    # console-added language carries its own `system_prompt` that the platform switches
    # to mid-call, and nothing in this tree ever wrote the floor into it — so scoring the
    # base prompt alone answered `True` about a string that is not in the path for the
    # language the caller switched into (`AgentSnapshot.alternate_prompts`,
    # `bolna._agent_alternate_prompts`). The script and disclosure checks deliberately
    # stay on `carries_prompt_marker`: a translated prompt is not obliged to contain the
    # client's base script, and refusing it would be a refusal about translation rather
    # than about compliance. The FLOOR is ours and belongs in all of them.
    truthful = snapshot.every_prompt_carries(TRUTHFUL_ANSWER_MARKER)
    expected_voice = _voice_expected(engine, cfg)
    held_voice = snapshot.holds_speech("tts")
    voice: bool | None
    if expected_voice is None:
        # Nothing was asked of this leg, so nothing about it can fail. True rather than
        # None: None means "we could not tell", and we can tell — there was no claim.
        voice = True
    elif held_voice is None:
        voice = None
    else:
        voice = held_voice == expected_voice

    # THE PROMPT COPY IS NOT IN `checked`, and that is a decision. The greeting is the
    # utterance; the prompt copy is a second belt on the same trousers, and an engine
    # holding the greeting while rendering the prompt differently is not a compliance
    # failure worth refusing a publish over — it is a fact worth RECORDING, which is what
    # the field beside the verdict is for. Putting it in `checked` would make every
    # engine that normalises whitespace inside a system prompt fail hard rule 5.
    checked = (
        ("greeting disclosure", disclosure),
        ("truthful-answer rule", truthful),
        ("script", prompt),
        ("voice", voice),
    )
    mismatched = [name for name, verdict in checked if verdict is False]
    if mismatched:
        return PublishVerification(
            state="not_applied",
            prompt_applied=prompt,
            disclosure_applied=disclosure,
            prompt_disclosure_applied=prompt_disclosure,
            truthful_answer_applied=truthful,
            voice_applied=voice,
            detail=(
                "The voice platform accepted the change and is not running it: "
                + ", ".join(mismatched)
                + " did not read back as sent."
            ),
        )
    unread = [name for name, verdict in checked if verdict is None]
    if unread:
        return PublishVerification(
            state="unreadable",
            prompt_applied=prompt,
            disclosure_applied=disclosure,
            prompt_disclosure_applied=prompt_disclosure,
            truthful_answer_applied=truthful,
            voice_applied=voice,
            detail=(
                "The voice platform accepted the change; we could not confirm it is "
                "running it (" + ", ".join(unread) + " could not be read back)."
            ),
        )
    return PublishVerification(
        state="applied",
        prompt_applied=True,
        disclosure_applied=True,
        # NOT hard-coded True like its neighbours: this one is not in `checked`, so
        # reaching here says nothing about it. Writing True here would be the same
        # true-by-construction move that made the original verdict meaningless.
        prompt_disclosure_applied=prompt_disclosure,
        truthful_answer_applied=True,
        voice_applied=True,
        detail=(
            "The voice platform was read back and is holding the published script, "
            "the truthful-answer rule and the voice."
        ),
    )


async def verify_publish(
    engine: VoiceEngine, ref: EngineAgentRef, cfg: AgentConfig
) -> PublishVerification:
    """Read the agent back and score it. Never raises for a vendor-side failure.

    A read-back that raised would make the read-back itself a new way for a publish to
    fail, on a path where the write has already happened — so the failure is converted
    into the `unreachable` VERDICT and returned. The one thing this function must never
    do is return `applied` because it did not look.
    """
    # THE ONE EXCEPTION TO "NEVER RAISES", AND IT IS NOT A VENDOR FAILURE (D-281). An
    # engine whose agents are deployed elsewhere has no prompt to read back at all —
    # `get_agent` refuses by name — and swallowing that into `unreachable` would record
    # "the vendor did not answer" about a vendor that answered perfectly and was asked a
    # question its platform does not have. `unreachable` is a transient thing an operator
    # retries; this is permanent, and the retry is the cost of confusing them.
    #
    # No caller can reach this today: `publish_agent` asks the same capability before it
    # writes anything, and `engine_drift_for` short-circuits on an agent with no
    # `engine_agent_ref` — which is every agent on such an engine, because publishing
    # refuses. It is here so that a FUTURE caller which forgets gets the named refusal
    # rather than a verdict that reads like a blip.
    if not engine.capabilities.hosts_agents():
        raise engine_lacks("agent_hosting", engine=engine.name)
    try:
        snapshot = await engine.get_agent(ref)
    except ProblemError as exc:
        # `exc.code` is ours (the adapter normalizes), so this carries no vendor text.
        log.warning(
            "agent_publish_readback_failed",
            extra={"agent_id": cfg.agent_id, "engine": engine.name, "reason": exc.code},
        )
        return PublishVerification(
            state="unreachable",
            prompt_applied=None,
            disclosure_applied=None,
            prompt_disclosure_applied=None,
            truthful_answer_applied=None,
            voice_applied=None,
            detail=(
                "The voice platform accepted the change and did not answer a read-back, "
                "so we cannot confirm it is running it."
            ),
        )
    return judge(engine, cfg, snapshot)


@dataclass(frozen=True, slots=True)
class EngineDrift:
    """The reconciliation answer: what the ENGINE holds versus what our row claims.

    Distinct from `PublishVerification` because the questions are asked at different
    moments and one of them cannot assume a write just happened. This is the read that
    catches the two cases a publish-time check structurally cannot:

    * somebody edited the agent in the VENDOR'S OWN DASHBOARD, so nothing of ours ran;
    * a publish failed on OUR side after the vendor committed (a connection reset on the
      response), so our row rolled back to a script the engine is no longer running —
      the divergence points the other way and no amount of re-reading our own tables
      finds it.
    """

    agent_id: str
    engine: str
    engine_agent_ref: str | None
    #: False when the agent has never been published — there is nothing to reconcile.
    checked: bool
    state: VerifyState | Literal["not_published"]
    prompt_applied: bool | None
    #: The GREETING's disclosure, same meaning as on `PublishVerification` — this is the
    #: field an operator escalates on (OPERATIONS §7).
    disclosure_applied: bool | None
    #: The prompt's copy of the line. Carried here as well so the drift screen and the
    #: publish banner say the same thing about the same agent.
    prompt_disclosure_applied: bool | None
    #: The truthful-answer rule, read off the engine's live prompt (D-163). Carried on
    #: the DRIFT object as well as the publish one because this is the property most
    #: likely to be lost WITHOUT a publish: somebody edits the prompt in the vendor's own
    #: dashboard and pastes back the script without the block underneath it. The
    #: half-hourly sweep is the only thing that ever looks at that agent again.
    truthful_answer_applied: bool | None
    voice_applied: bool | None
    detail: str

    @property
    def in_sync(self) -> bool:
        return self.state == "applied"


__all__ = [
    "EngineDrift",
    "PublishVerification",
    "StoredVerifyState",
    "VerifyState",
    "judge",
    "verify_publish",
]
