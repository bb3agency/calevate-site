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
`AgentSnapshot` and `EngineCapabilities` and returns our own verdict.

HARD RULE 6. `detail` names fields and verdicts, never prompt bodies — the strings here
reach a log line and a banner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from calevate_shared.engine import AgentConfig, AgentSnapshot, EngineAgentRef, VoiceEngine

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

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
    disclosure_applied: bool | None
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
    """
    if not engine.capabilities.is_ours("tts"):
        return None
    return cfg.models.tts_voice or None


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
    """
    prompt = snapshot.carries_prompt_marker(cfg.system_prompt)
    disclosure = snapshot.carries_prompt_marker(cfg.disclosure_line)
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

    checked = (("script", prompt), ("disclosure line", disclosure), ("voice", voice))
    mismatched = [name for name, verdict in checked if verdict is False]
    if mismatched:
        return PublishVerification(
            state="not_applied",
            prompt_applied=prompt,
            disclosure_applied=disclosure,
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
        voice_applied=True,
        detail="The voice platform was read back and is holding the published script and voice.",
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
    disclosure_applied: bool | None
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
