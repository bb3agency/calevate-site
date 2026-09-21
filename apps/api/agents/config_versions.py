"""THE WITNESS THAT REPLACES A VENDOR READ-BACK: config versions, and what a worker loaded.

D-592, `docs/PIPECAT-MIGRATION.md` §1.1, step 2 of its §6. Migration `d4e1c7a09b35`.

**THE PROBLEM THIS SOLVES.** Under a rented engine the vendor is an INDEPENDENT WITNESS:
`get_agent` asks it what it is running and it may disagree with us. On
`agent_hosting="owned_runtime"` there is no vendor, so a `get_agent` that read our own
tables would hand back the configuration `create_agent` had just written — *"it agrees
with the caller by construction"*, the defect `VoiceEngine.get_agent`'s own docstring
forbids (`packages/shared/src/calevate_shared/engine.py`). OPERATIONS §2 gate 2's property
(APPLIED, not merely ACCEPTED) would not go false; it would go UNFALSIFIABLE.

**THE REPLACEMENT.** Something else can disagree with us: the running worker, about what
it actually loaded. So there are two writers and they are never the same process:

* `mint_config_version` — the CONTROL PLANE, on create/publish. Immutable and
  content-addressed: the row IS its two digests.
* `record_attestation` — the WORKER, at session start, recomputing the prompt digest from
  the string in its own memory.

`latest_attestation` is what an `owned_runtime` adapter answers `get_agent` from. NOT the
config version — an adapter that answers from what it wrote has reintroduced the defect
under a different capability name.

WHAT IS IN EACH DIGEST, AND WHAT IS DELIBERATELY OUT
=====================================================
A hash the witness cannot reproduce byte-for-byte makes every attestation a false
mismatch, which is an incident that is not happening — the most expensive kind, because it
is indistinguishable from the real one until somebody reads the code. So the rule is:
**only what the worker can recompute from the config version it loaded.**

`prompt_sha256` — sha256 of `compose_engine_prompt(cfg)` encoded UTF-8. That is the ONE
composer (hard rule 5), so the digest covers the platform-rules preamble, the voice-style
block, the composed opening line, the client's fenced script and
`TRUTHFUL_ANSWER_DIRECTIVE` — everything the model is handed, in the order it is handed.

OUT of it, each because it is per-session or per-instant rather than per-configuration:

* **`caller_memory`** (`compose_engine_prompt(cfg, caller_memory=...)`) — facts about ONE
  caller, assembled per session. In the digest, every attestation would mismatch.
* **`AgentConfig.handoff`** — resolved from the roster AND A CLOCK at publish time
  (`agents/handoff.on_duty`), so it differs at 09:00 and at 21:00 for an unchanged agent.
  It is not in the composed prompt at all; it reaches the pipeline as a tool.
* **Dial-time `{{ }}` merge values** (`agents/service._call_prompt_for`) — substituted per
  contact, after composition.

`model_config_sha256` — sha256 of the resolved `ModelConfig` as canonical JSON: sorted
keys, no whitespace, `mode="json"`. Sorted rather than declaration-ordered so that
re-ordering fields in the type is not a schema-wide digest change. Every leg is in it —
STT, LLM (model, provider, base URL, traps) and TTS (provider, model, voice, label) —
because "which model answered" and "what it was told" fail for different reasons and an
operator has to be able to tell them apart.

There is no `model_config_sha256` on the attestation, and that is §1.1's shape rather than
an omission: a digest the worker recomputed over strings it holds in configuration would
be a claim about its config file, not about what it did with it. The honest witness for
the model leg is the metering (§1.3) and `LLMTokenUsage`, which say which model actually
answered.

WHY THE MINT IS IDEMPOTENT
==========================
Content-addressed means the same content on the same agent IS the same version, so a
publish that changes nothing mints nothing and an attestation quoting a version id always
resolves to exactly one content. The alternative — a row per press of the button — makes
"which version was this worker on" a question with a hundred identical answers.

`ON CONFLICT DO NOTHING` rather than `DO UPDATE`: the table is append-only (hard rule 4)
and `DO UPDATE` fires `calevate_forbid_mutation`, which is the same reasoning
`billing/platform_ai.py` and `billing/ai_quota.py` already record at their own upserts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from calevate_shared.engine import (
    AgentConfig,
    ModelConfig,
    carries_truthful_answer_floor,
    compose_engine_prompt,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7

log = get_logger(__name__)


def prompt_digest(cfg: AgentConfig) -> str:
    """The digest of the prompt this agent hands the model.

    `caller_memory` is omitted — see the module docstring for the whole in/out list. It is
    an argument to the composer rather than a field of `cfg`, so omitting it is what
    calling `compose_engine_prompt(cfg)` already does; it is stated here because a future
    caller with a `caller_memory` in hand would otherwise pass it and silently break every
    attestation in the fleet.
    """
    return hashlib.sha256(compose_engine_prompt(cfg).encode()).hexdigest()


def canonical_model_config(cfg: AgentConfig) -> str:
    """The resolved `ModelConfig` as the bytes `model_config_sha256` is taken over.

    Split out of `model_config_digest` so the digest and the STORED copy cannot drift: the
    version row carries this exact string (migration `e2f5a91c8d47`), and a second
    serialisation beside the digest's own would be two spellings of one fact — the defect
    `_engine_name` records at its own call site.
    """
    return json.dumps(cfg.models.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def model_config_digest(cfg: AgentConfig) -> str:
    """The digest of the resolved `ModelConfig`, as canonical JSON.

    `sort_keys` so the digest is a function of the VALUES rather than of the order the
    fields happen to be declared in, and the tightest separators so no formatting choice
    can reach it. `mode="json"` because the type holds tuples (`llm_traps`) and enums that
    have no stable `str()` of their own.
    """
    return hashlib.sha256(canonical_model_config(cfg).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ConfigVersion:
    """One `agent_config_versions` row, as the caller needs it."""

    id: UUID
    agent_id: UUID
    prompt_sha256: str
    model_config_sha256: str
    created_at: datetime
    #: False when an identical version already existed and was reused. Not an error and
    #: not a failure — it is the normal answer to re-publishing an unchanged agent — but
    #: the publish path wants to be able to say "nothing changed" rather than claim it
    #: wrote something.
    minted: bool


@dataclass(frozen=True, slots=True)
class Attestation:
    """What a worker last reported about what it loaded, and whether it agrees with us."""

    id: UUID
    agent_id: UUID
    agent_config_version_id: UUID
    #: The worker's OWN recomputation.
    prompt_sha256: str
    observed_at: datetime
    #: The digest on the version row the worker says it loaded.
    expected_prompt_sha256: str
    #: THE CONTENT OF THAT VERSION, so a caller can report WHAT the worker is running and
    #: not only whether it agrees. `None` on the object `record_attestation` returns: that
    #: function's caller already holds the config it just wrote, and fetching the row back
    #: to hand it its own bytes would be a round trip for nothing. `latest_attestation`
    #: — the read `get_agent` answers from — always populates all three.
    #:
    #: **THEY MAY ONLY BE REPORTED AS "WHAT THE ENGINE HOLDS" WHEN `matches` IS TRUE**, and
    #: that is the whole content-addressing argument rather than a caution: the digest the
    #: WORKER recomputed over its own memory equalling the digest of these bytes is what
    #: makes "the process is holding this text" an inference instead of an assumption. On a
    #: mismatch we know only that it is holding something else, and there is nothing here
    #: that describes it.
    composed_prompt: str | None = None
    opening_line: str | None = None
    models: ModelConfig | None = None

    @property
    def matches(self) -> bool:
        """Does the process agree with the control plane about what it is running?

        **A FALSE HERE IS A FINDING, NOT AN ERROR.** It is the one thing this whole
        arrangement exists to be able to say: a prompt truncated or re-encoded on the way
        into the process, a worker image serving a text of its own, a session served from
        somewhere other than the version row. A worker on a STALE DEPLOY is not among
        them and cannot be — it attests the version id it was served, and this compares
        against that version's own digest.

        Nothing in this module raises on it, because the row is evidence either way and
        suppressing the write would delete the evidence of the very condition the table
        was built to catch. `record_attestation` alarms on it; `PipecatEngine.get_agent`
        re-reads the same verdict to decide whether it may report what the worker holds.
        """
        return self.prompt_sha256 == self.expected_prompt_sha256


async def mint_config_version(
    session: AsyncSession, tenant_id: UUID, cfg: AgentConfig
) -> ConfigVersion:
    """Record what this agent is supposed to run, or return the identical row that exists.

    REFUSES A CONFIG WHOSE COMPOSED PROMPT DOES NOT CARRY THE TRUTHFUL-ANSWER FLOOR, and
    this is where hard rule 5 stops being VERIFIED against a vendor and starts being
    STRUCTURAL. On a rented engine the floor was proved by reading the agent back off the
    vendor; on `owned_runtime` the worker loads THIS row, so a version minted without the
    floor is an agent that can be scripted into claiming it is human and no later check
    can catch it — the version is immutable and the worker will attest to it faithfully.
    The composer puts the directive in unconditionally, so this can only fire if somebody
    hands us a prompt composed elsewhere, which is exactly the caller worth refusing.

    `session` is a tenant-scoped session (`db/session.tenant_session`): RLS is the control,
    and `tenant_id` here is the column value, not the isolation.
    """
    prompt_sha = prompt_digest(cfg)
    model_sha = model_config_digest(cfg)
    if not carries_truthful_answer_floor(compose_engine_prompt(cfg)):
        # Operator-facing, not client-facing: a client cannot cause this and cannot fix
        # it. No prompt text in the message or the log (hard rules 5 and 6).
        log.error(
            "agent_config_version_missing_truthful_floor",
            extra={"agent_id": cfg.agent_id, "tenant_id": cfg.tenant_id},
        )
        raise ProblemError(
            kind="internal",
            code="agent_config_floor_absent",
            title="This agent cannot be published",
            detail=(
                "The agent's script is not carrying the rules that make it answer "
                "truthfully about being an AI and about recording, so it was not saved."
            ),
            remediation="Contact us — this is a fault on our side, not something you can fix.",
        )

    agent_id = UUID(cfg.agent_id)
    params = {
        "id": uuid7(),
        "tid": tenant_id,
        "aid": agent_id,
        "prompt": prompt_sha,
        "model": model_sha,
        # THE CONTENT THE TWO DIGESTS ARE TAKEN OVER, so the row can be LOADED and not
        # only compared (migration `e2f5a91c8d47`). Every one of the three is a function
        # of the conflict key's inputs, which is what makes `DO NOTHING` safe: the row that
        # is kept describes the same content as the row that was refused.
        "composed": compose_engine_prompt(cfg),
        "opening": cfg.opening_line,
        "models": canonical_model_config(cfg),
    }
    # DO NOTHING, not DO UPDATE: the table is append-only and `DO UPDATE` fires
    # `calevate_forbid_mutation`. A conflict means the identical version already exists,
    # which is the answer, not a failure.
    row = (
        await session.execute(
            text(
                "INSERT INTO agent_config_versions "
                "(id, tenant_id, agent_id, prompt_sha256, model_config_sha256, "
                " composed_prompt, opening_line, model_config) "
                "VALUES (:id, :tid, :aid, :prompt, :model, :composed, :opening, "
                "        CAST(:models AS jsonb)) "
                "ON CONFLICT (agent_id, prompt_sha256, model_config_sha256) DO NOTHING "
                "RETURNING id, created_at"
            ),
            params,
        )
    ).first()
    if row is not None:
        log.info(
            "agent_config_version_minted",
            extra={"agent_id": str(agent_id), "config_version_id": str(row[0])},
        )
        return ConfigVersion(
            id=row[0],
            agent_id=agent_id,
            prompt_sha256=prompt_sha,
            model_config_sha256=model_sha,
            created_at=row[1],
            minted=True,
        )

    existing = (
        await session.execute(
            text(
                "SELECT id, created_at FROM agent_config_versions "
                "WHERE agent_id = :aid AND prompt_sha256 = :prompt "
                "  AND model_config_sha256 = :model"
            ),
            params,
        )
    ).first()
    # Not an `assert`: the only way to reach this is another tenant holding the conflicting
    # row, which RLS hides from this SELECT — i.e. an `agents.id` collision across
    # tenants. That is impossible with uuid_v7 and it is not a caller error, so it gets an
    # operator-readable failure rather than a traceback nobody can act on.
    if existing is None:
        log.error(
            "agent_config_version_conflict_invisible",
            extra={"agent_id": str(agent_id), "tenant_id": str(tenant_id)},
        )
        raise ProblemError(
            kind="internal",
            code="agent_config_version_unreadable",
            title="This agent could not be saved",
            detail="We could not record what this agent is running.",
            remediation="Try again. If it keeps failing, contact us.",
        )
    return ConfigVersion(
        id=existing[0],
        agent_id=agent_id,
        prompt_sha256=prompt_sha,
        model_config_sha256=model_sha,
        created_at=existing[1],
        minted=False,
    )


async def record_attestation(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    agent_id: UUID,
    agent_config_version_id: UUID,
    prompt_sha256: str,
    observed_at: datetime | None = None,
) -> Attestation:
    """Write what a worker says it loaded, and return the verdict against what we intended.

    `prompt_sha256` IS THE WORKER'S OWN RECOMPUTATION over the string in its memory. It is
    a parameter rather than something this function derives, and that is the entire design:
    a value computed here would make every comparison pass by construction, which is the
    `control_plane` defect wearing a different hat.

    `observed_at` defaults to now for a caller that has no clock reading of its own, but a
    worker SHOULD pass the instant it actually read its memory — the gap between loading a
    prompt and getting a write through a busy database is the difference between "a stale
    worker" and "a slow database", and only the first is a finding.

    Does not raise on a mismatch: see `Attestation.matches`.
    """
    version = (
        await session.execute(
            text(
                "SELECT prompt_sha256 FROM agent_config_versions "
                "WHERE id = :vid AND agent_id = :aid"
            ),
            {"vid": agent_config_version_id, "aid": agent_id},
        )
    ).first()
    if version is None:
        # The FK would refuse this insert anyway; refusing here names WHICH id was wrong
        # and keeps the transaction usable, rather than surfacing an IntegrityError from
        # three layers down.
        raise ProblemError(
            kind="validation",
            code="agent_config_version_unknown",
            title="Unknown agent configuration",
            detail="That configuration version does not belong to this agent.",
            remediation="Reload and try again.",
        )

    seen_at = observed_at or datetime.now(UTC)
    row = (
        await session.execute(
            text(
                "INSERT INTO agent_config_attestations "
                "(id, tenant_id, agent_id, agent_config_version_id, prompt_sha256, "
                " observed_at) "
                "VALUES (:id, :tid, :aid, :vid, :prompt, :seen) "
                "RETURNING id"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "aid": agent_id,
                "vid": agent_config_version_id,
                "prompt": prompt_sha256,
                "seen": seen_at,
            },
        )
    ).first()
    assert row is not None  # RETURNING on a single-row INSERT
    attestation = Attestation(
        id=row[0],
        agent_id=agent_id,
        agent_config_version_id=agent_config_version_id,
        prompt_sha256=prompt_sha256,
        observed_at=seen_at,
        expected_prompt_sha256=version[0],
    )
    if not attestation.matches:
        # ALARMED AT THE ONE PLACE THE VERDICT IS COMPUTED, rather than counted by a sweep
        # and alarmed above a threshold. A count would be the right instrument only if a
        # single mismatch could be benign, and on this wiring it cannot be: the session
        # read serves the version id and the prompt bytes from ONE row
        # (`worker/service._SESSION_SQL`), the worker digests exactly the string it was
        # served (`voice_worker/pipeline.recompute_prompt_sha256`), and the comparison
        # above is against the digest of THAT SAME version. A publish during the session
        # mints a different version and cannot move it, so a mismatch is never staleness —
        # it is evidence that a process on a live call holds a script this platform did
        # not compose, which is `engine_agent_drift_detected`'s condition on the owned
        # runtime and takes its rung.
        #
        # Repetition is the alert record's problem and not this call site's: one notice per
        # code per window, one email per episode, occurrence counts on `/admin/ops/alerts`
        # (`core/alerting.py`). What a batched sweep could not do is name the agent.
        alert(
            "CORE_LOGIC",
            "agent_config_attestation_mismatch",
            detail=(
                "a voice worker is running a prompt that is not the one minted for the "
                "configuration version it names, so what this agent says to a caller is "
                "not what was published"
            ),
            agent_id=str(agent_id),
            tenant_id=str(tenant_id),
            config_version_id=str(agent_config_version_id),
            attestation_id=str(attestation.id),
        )
    return attestation


async def latest_attestation(session: AsyncSession, agent_id: UUID) -> Attestation | None:
    """What the worker last said it was running, or None if no worker ever has.

    **THIS IS WHAT `get_agent` ANSWERS FROM ON AN `owned_runtime` ENGINE.** None is a real
    answer and not an absence to paper over: an agent that has been published and never
    dialled has no witness yet, and an adapter must report that as "nobody has confirmed
    this" rather than echo the config version — which is the whole point.

    Reads through `ix_agent_config_attestations_latest`. Ordered by `observed_at DESC, id
    DESC`, so two workers attesting in the same instant still resolve deterministically
    rather than by planner whim.
    """
    row = (
        await session.execute(
            text(
                "SELECT a.id, a.agent_config_version_id, a.prompt_sha256, a.observed_at, "
                "       v.prompt_sha256, v.composed_prompt, v.opening_line, v.model_config "
                "FROM agent_config_attestations a "
                "JOIN agent_config_versions v ON v.id = a.agent_config_version_id "
                "WHERE a.agent_id = :aid "
                "ORDER BY a.observed_at DESC, a.id DESC LIMIT 1"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        return None
    return Attestation(
        id=row[0],
        agent_id=agent_id,
        agent_config_version_id=row[1],
        prompt_sha256=row[2],
        observed_at=row[3],
        expected_prompt_sha256=row[4],
        composed_prompt=row[5],
        opening_line=row[6],
        # Validated rather than cast: the column is written from
        # `ModelConfig.model_dump(mode="json")` and read back by an adapter that puts it
        # in an `AgentSnapshot`, so a row written before a field moved must fail HERE,
        # where the agent id is in hand, rather than inside a Pydantic error three layers
        # up in a publish.
        models=ModelConfig.model_validate(row[7]),
    )
