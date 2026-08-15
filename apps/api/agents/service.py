"""Agent configuration + the two paths that touch the engine.

`publish_agent` is where our world and the vendor's are married, and it is the reason
`engine_agent_routes` exists: the routing row and `agents.engine_agent_ref` are written
in the SAME transaction, so an inbound webhook can never arrive for an agent the
resolver cannot map.

`dispatch_call` is the single outbound entry point. Everything that places a call —
the D-21 Leads button today, campaigns and lead-callback webhooks in M2 — goes through
it, so the pre-dispatch call row, the metering hook and the audit trail exist exactly
once rather than three times.

WHICH PROMPT A PUBLISH SENDS (SURFACES §2b two-speed publishing)
---------------------------------------------------------------
`_load_agent` reads the APPLIED pointer, `COALESCE(live_prompt_id, system_prompt_id)`,
not the draft one. That single change is what makes a fast lane expressible at all:
this function sends ONE `AgentConfig` carrying script and voice and cap together, so
before `live_prompt_id` existed there was no way to push a voice change without also
pushing whatever unapproved script sat in `system_prompt_id`. It is exactly why
`voice_routes.py` refuses to publish and returns `republish_required` instead.

The COALESCE is safe rather than lenient, and the invariant that makes it safe lives
in `prompts.insert_prompt_version`: the one statement that can create a divergence
between the two pointers also materializes `live_prompt_id` in the same UPDATE. So
`live_prompt_id IS NULL` only ever means "the two pointers agree", never "the draft is
ahead" — which is also true of every row that predates the pointer (migration
a4e7b2c95d18 backfilled them) and of every row `admin/intake.py` writes.

WHAT "LIVE" IS ALLOWED TO MEAN (migration c1f6a94d2b07)
-------------------------------------------------------
`publish_agent` used to finish at "the vendor call returned without raising" and then
write four claims about the ENGINE — `status = 'live'`, `engine_agent_ref`,
`live_tts_voice`, and (through `apply_to_live`) `live_prompt_id`. All four were derived
from one fact about OURSELVES. D-64 put `VoiceEngine.get_agent` on the Protocol to close
exactly that, and nothing called it.

Now every publish reads the agent back and scores it (`agents/verification.py`). A PROVEN
mismatch is a refusal — the transaction rolls back, and nothing claims a script the
engine was observed not to be running. An UNPROVEN one (the adapter could not read the
field, or the read-back itself failed) is recorded in `live_verify_state` and rendered,
never rounded up. The four values and why `not_applied` is not one of them are in the
migration.

WHICH VOICE THE ENGINE IS HOLDING (migration c8b3f14e7a29)
----------------------------------------------------------
`publish_agent` is the ONLY place a voice reaches the engine, so it is the only place
that can say what the engine has. It records `agents.live_tts_voice` /
`live_tts_provider` from the `AgentConfig` it just sent, in the same UPDATE as
`engine_agent_ref`. `agents.tts_voice` stays the CONFIGURED voice, and the two are
allowed to differ because `voice_routes.set_agent_voice` writes the row without
publishing — so "does a republish change what callers hear?" is
`live_tts_voice IS DISTINCT FROM tts_voice`, which `agents/publishing.py` reads and
`GET /v1/agents/{agent_id}/pending` answers.

One known imprecision, in the safe direction: `publish_variant` sends the agent's
CONFIGURED voice to an experiment arm, and starting an experiment publishes arms
without publishing the agent. The arms can therefore be speaking the configured voice
while the agent's own engine object is not, and this mirror reports the agent — so the
answer is "republish required" when part of the traffic already moved. Over-reporting a
divergence costs one harmless publish; under-reporting one is a false claim about a live
phone line, which is the direction that must never happen.

THE CALL CAP (SURFACES §2b:107)
-------------------------------
`_to_config` fills `AgentConfig.max_call_duration_s` from the agent row. The field and
its vendor mapping already existed — `engine/bolna.py` renders it as the vendor's
`task_config.call_terminate` — and nothing filled it, so every agent on the platform
published the Pydantic default and no client could change it. Publish time is where
the guard is enforced because the engine is the only party that can hang up a call:
we are not in the audio path (hard rule 3), and an inbound runaway is never dispatched
by us at all, so a dispatch-side check would leave the receptionist motion unguarded.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from calevate_shared.engine import AgentConfig, CallContext, ModelConfig, VoiceEngine
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import assignment
from apps.api.agents.models import CALL_CAP_DEFAULT_S
from apps.api.agents.verification import verify_publish
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.engine import get_engine

log = get_logger(__name__)


def effective_call_cap(max_call_duration_s: int | None) -> int:
    """The cap an agent is actually published with.

    NULL on the column means "the platform default", NEVER "unlimited" — the whole
    point of the guard is that there is no way to express an uncapped agent. The
    resolution lives here, in one function, so that a second reader cannot decide the
    sentinel means something else.
    """
    return CALL_CAP_DEFAULT_S if max_call_duration_s is None else max_call_duration_s


async def _load_agent(
    session: AsyncSession, tenant_id: UUID, agent_id: UUID, *, for_update: bool = False
) -> dict[str, object]:
    """The agent as an `AgentConfig` needs it, optionally under a row lock.

    `for_update` is the publish path's, and only the publish path's. The read alone is a
    read-then-write over `engine_agent_ref` — read "no ref", call `create_agent`, write
    the ref back — and two publishes interleaving there produce TWO vendor-side agents
    for one row, of which we can record exactly one. The other is an orphan: an object we
    are billed for, cannot address, and have no record of. BACKEND-PATTERNS §5 wants CAS
    or a lock; a CAS cannot serve here because the value being decided (the vendor's id)
    does not exist until after the side effect, so the lock is the only instrument that
    covers the window.

    `FOR UPDATE` on `agents` only — not on the LEFT JOINed `prompt_versions`, which
    `agents/prompts.py` keeps immutable and which a lock would needlessly block a
    concurrent version WRITE against. `OF a` is what says so.

    Deliberately NOT the default: `dispatch_call` reads through here on the outbound hot
    path and takes no lock, because it decides nothing about the row — it reads a ref and
    dials it, and a publish landing mid-dial changes which script the NEXT call speaks,
    never this one.
    """
    row = (
        await session.execute(
            text(
                "SELECT a.id, a.name, a.direction, a.language_primary, a.disclosure_line, "
                "a.stt_provider, a.stt_model, a.llm_model, a.tts_provider, a.tts_voice, "
                "a.engine, a.engine_agent_ref, a.status, pv.body, a.max_call_duration_s "
                "FROM agents a LEFT JOIN prompt_versions pv "
                # The APPLIED pointer, not the draft one — see the module docstring.
                "ON pv.id = COALESCE(a.live_prompt_id, a.system_prompt_id) "
                "WHERE a.id = :aid AND a.deleted_at IS NULL"
                + (" FOR UPDATE OF a" if for_update else "")
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    return {
        "id": row[0],
        "name": row[1],
        "direction": row[2],
        "language_primary": row[3],
        "disclosure_line": row[4],
        "stt_provider": row[5],
        "stt_model": row[6],
        "llm_model": row[7],
        "tts_provider": row[8],
        "tts_voice": row[9],
        "engine": row[10],
        "engine_agent_ref": row[11],
        "status": row[12],
        "prompt": row[13],
        "max_call_duration_s": row[14],
    }


def _assert_has_a_script(agent: dict[str, object]) -> str:
    """The agent's applied script, or a refusal — never a stand-in.

    `_to_config` used to read `str(agent["prompt"] or "You are a helpful receptionist.")`,
    and that default is reachable in the ONE state the wizard leaves an agent in before
    step 3: `admin/service.create_organization` mints the receptionist row with no
    `prompt_versions` row at all. Pressing Publish there answered 200 `status: live`,
    wrote the routing row, and put a hardcoded ENGLISH sentence on a Telugu clinic's
    phone line — with no hours, no prices, no staff names and nothing to tell a caller
    which business they had reached. Every screen downstream then read `live`.

    A missing script is not a value to substitute. It is FLOWS §1's step-3-before-step-7
    ordering being skipped, and the honest answer is a refusal naming the step. The
    disclosure line gets this treatment already (non-null by schema, hard rule 5); the
    script had no equivalent guard because the default hid the case.

    NOT a check for a *good* script — that is step 7's test call, which is pilot-gated
    and outside this function. This is the floor: there is one, and it is the client's.
    """
    prompt = agent.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        return prompt
    raise ProblemError(
        kind="business_rule",
        code="agent_has_no_script",
        title="This agent has no script yet",
        detail=(
            "The agent has no prompt version, so there is nothing to publish. Publishing "
            "it would put a generic placeholder on the client's phone line."
        ),
        remediation=(
            "Complete the intake step for this client, or write a prompt version, then publish."
        ),
    )


def _to_config(tenant_id: UUID, agent: dict[str, object]) -> AgentConfig:
    settings = get_settings()
    return AgentConfig(
        tenant_id=str(tenant_id),
        agent_id=str(agent["id"]),
        name=str(agent["name"]),
        direction=str(agent["direction"]),
        language_primary=str(agent["language_primary"]),
        system_prompt=_assert_has_a_script(agent),
        # Never defaulted, never blank — the schema enforces it and so does the gate.
        disclosure_line=str(agent["disclosure_line"]),
        models=ModelConfig(
            stt_provider=agent["stt_provider"],
            stt_model=agent["stt_model"],
            llm_model=agent["llm_model"],
            tts_provider=agent["tts_provider"],
            tts_voice=agent["tts_voice"],
        ),
        webhook_url=f"{settings.webhook_base_url}/hooks/v1/engine/{settings.engine}",
        # The cost-runaway guard. Resolved here rather than defaulted in the model, so
        # an agent that has never been given a cap is still published with one.
        max_call_duration_s=effective_call_cap(
            cast(int | None, agent.get("max_call_duration_s")),
        ),
    )


async def _reclaim_orphan(engine: VoiceEngine, agent_id: UUID, ref: str, reason: str) -> None:
    """A vendor-side agent we created and then could not record. DELETE IT, or log it.

    THE SHAPE OF THE PROBLEM. `create_agent` is a side effect at a third party; our write
    of `engine_agent_ref` is a side effect in our database. There is no transaction
    spanning both, so a failure in the window between them — the read-back proving the
    engine is not running what we sent, the row being soft-deleted underneath us — rolls
    OUR half back and leaves theirs standing. The result is an agent object we are billed
    for and can never address again, because the only copy of its id was in the
    transaction that rolled back.

    **THE COMPENSATION, AND WHY IT IS INLINE.** `VoiceEngine.delete_agent` now exists, so
    the remedy is a call rather than a note. It happens HERE, synchronously, before the
    caller raises — NOT through the outbox and not through an arq enqueue — because the
    ref lives only in this frame. The outbox is transactional (BACKEND-PATTERNS §4) and
    this transaction is about to roll back, so an outbox row would roll back with it and
    take the only copy of the ref down; a direct enqueue would survive but adds a second
    thing that can fail while we are already holding the failure. One vendor round trip on
    a path that is already failing is a cost worth paying to not leak a billed object.

    **BEST-EFFORT, and the log line is still the floor.** If the delete raises — the
    vendor is the thing that was misbehaving a moment ago, so it might — we are exactly
    where we were before this function grew a remedy: an ERROR carrying the ref, which is
    the operator's copy. `ref` is a vendor-issued opaque id, not a phone number, not
    transcript text, not an extraction payload, so hard rule 6 permits it. Nothing is
    re-raised: this is compensation for a failure the caller is about to report, and
    failing the publish a second way would replace an actionable error with a confusing
    one.

    **`delete_agent` IS NOT CALLED ON A HUMAN'S SOFT-DELETE**, and that is deliberate.
    Bolna's delete destroys the agent's executions with it, and a soft-deleted agent's
    call history is a retention obligation of ours (SECURITY-COMPLIANCE §4). The subject
    here is an agent minted seconds ago that has never taken a call, which is the only
    population for which "remove it entirely" is the right answer.

    Why a `lock` makes this rare rather than routine: `_load_agent(for_update=True)`
    serializes publishes on one agent, so the common cause — two concurrent publishes
    both seeing "no ref" and both creating — cannot happen at all.
    """
    ids = {
        "agent_id": str(agent_id),
        "engine": engine.name,
        "engine_agent_ref": ref,
        "reason": reason,
    }
    try:
        await engine.delete_agent(ref)
    except Exception as exc:
        # Broad on purpose: the remedy must never become a new way for the publish to
        # fail. `exc.__class__.__name__` and nothing from the exception's text — an
        # adapter normalizes to `ProblemError`, but a transport error could arrive raw.
        log.error(
            "engine_agent_orphaned",
            extra={**ids, "reclaim_failed": exc.__class__.__name__},
        )
        return
    log.warning("engine_agent_orphan_reclaimed", extra=ids)


async def publish_agent(session: AsyncSession, *, tenant_id: UUID, agent_id: UUID) -> str:
    """Create or update the agent on the engine, VERIFY it, then record the mapping.

    The routing row is written HERE, in the same transaction as `engine_agent_ref`,
    because the alternative — writing it from a webhook handler on first sight — means
    the first call for a new agent is the one that gets lost.

    THE READ-BACK (D-64, `agents/verification.py`). This used to end at "the vendor call
    returned without raising", and then wrote `status = 'live'`, `engine_agent_ref` and
    the voice mirror — four claims about the ENGINE, all derived from one fact about
    OURSELVES. Now the agent is read back through `VoiceEngine.get_agent` and scored; a
    PROVEN mismatch is a refusal (the transaction rolls back and no column claims a
    script the engine was observed not to hold), and an unproven one is recorded as
    `live_verify_state` rather than rounded up to success.

    THE LOCK. `for_update=True` — see `_load_agent`. It closes the create/create race
    that manufactures orphans and it serializes a publish against a concurrent
    `set_call_cap`, `apply_to_live` or `set_agent_voice` republish, all of which reach
    this function and all of which read-then-write the same row.
    """
    agent = await _load_agent(session, tenant_id, agent_id, for_update=True)
    engine = get_engine()
    config = _to_config(tenant_id, agent)

    existing_ref = agent["engine_agent_ref"]
    created = not (isinstance(existing_ref, str) and existing_ref)
    if isinstance(existing_ref, str) and existing_ref:
        await engine.update_agent(existing_ref, config)
        ref = existing_ref
    else:
        ref = await engine.create_agent(config)

    # AFTER the write and BEFORE any column claims it landed. Never raises for a vendor
    # failure — an unreachable read-back is a verdict, not a second way to fail a publish
    # whose write has already happened.
    verdict = await verify_publish(engine, ref, config)
    if verdict.state == "not_applied":
        if created:
            await _reclaim_orphan(engine, agent_id, ref, "read_back_proved_not_applied")
        log.error(
            "agent_publish_not_applied",
            extra={
                "agent_id": str(agent_id),
                "engine": engine.name,
                "prompt_applied": verdict.prompt_applied,
                "disclosure_applied": verdict.disclosure_applied,
                "voice_applied": verdict.voice_applied,
            },
        )
        raise ProblemError(
            kind="dependency",
            code="engine_publish_not_applied",
            title="The voice platform is not running this change",
            detail=verdict.detail,
            remediation=(
                "Nothing was recorded as live. Try publishing again; if it keeps failing "
                "the agent may have been edited directly on the voice platform."
            ),
        )

    result = await session.execute(
        text(
            "UPDATE agents SET engine_agent_ref = :ref, engine = :engine, status = 'live', "
            "live_tts_voice = :live_voice, live_tts_provider = :live_provider, "
            "live_verify_state = :verify_state, live_verified_at = :verified_at, "
            # THE SOFT-DELETE GUARD, and it is not belt-and-braces. `_load_agent` filters
            # on `deleted_at IS NULL`, but this UPDATE used to name the id alone — so a
            # delete committed between the two would be silently undone here, resurrecting
            # a deleted agent to `status = 'live'` AND writing it a routing row that makes
            # the vendor's next inbound webhook resolve to it. The lock above makes the
            # window small; the predicate makes it closed. Zero rows is a refusal.
            "updated_at = now() WHERE id = :aid AND deleted_at IS NULL"
        ),
        {
            "ref": ref,
            "engine": engine.name,
            "aid": agent_id,
            # Read off the config we JUST handed the engine, not re-read from the row.
            # This statement is the only moment the two are provably equal, and a
            # re-read here would record whatever a concurrent `set_agent_voice`
            # committed in between — a mirror that claims the engine holds a voice it
            # was never sent. Written inside the same transaction as `engine_agent_ref`
            # and after the vendor call, so a vendor failure rolls the mirror back with
            # it and our row never over-promises (the `kb.publish_source` ordering).
            "live_voice": config.models.tts_voice,
            "live_provider": config.models.tts_provider,
            "verify_state": verdict.stored_state,
            # NULL unless something was actually proven. A timestamp on an `unreachable`
            # would let a screen render "confirmed just now" over an answer nobody read.
            "verified_at": datetime.now(UTC) if verdict.proven else None,
        },
    )
    if rowcount_of(result) == 0:
        if created:
            await _reclaim_orphan(engine, agent_id, ref, "agent_deleted_during_publish")
        raise ProblemError.conflict(
            "agent_deleted_during_publish",
            "This agent was deleted while it was being published.",
            remediation="Nothing was recorded as live. Recreate the agent if it is still needed.",
        )
    await session.execute(
        text(
            "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
            "active, created_at, updated_at) VALUES (:engine, :ref, :tid, :aid, true, now(), "
            "now()) ON CONFLICT (engine, engine_agent_ref) DO UPDATE SET "
            "tenant_id = EXCLUDED.tenant_id, agent_id = EXCLUDED.agent_id, active = true, "
            "updated_at = now()"
        ),
        {"engine": engine.name, "ref": ref, "tid": tenant_id, "aid": agent_id},
    )
    await republish_running_variants(session, tenant_id=tenant_id, agent_id=agent_id)
    log.info(
        "agent_published",
        extra={
            "agent_id": str(agent_id),
            "engine": engine.name,
            # The verdict, not the prompt. What an operator needs from this line is
            # whether "live" was CONFIRMED, and that is one word (hard rule 6).
            "verify_state": verdict.state,
        },
    )
    return ref


_VARIANT_CONFIG_SQL = (
    "SELECT v.id, v.label, v.disclosure_line, pv.body, v.engine_agent_ref "
    "FROM prompt_experiment_variants v "
    "JOIN prompt_experiments e ON e.id = v.experiment_id "
    "JOIN prompt_versions pv ON pv.id = v.prompt_version_id "
    "WHERE e.agent_id = :aid AND e.status = 'running' ORDER BY v.label"
)


def _variant_config(
    tenant_id: UUID,
    agent: dict[str, object],
    variant_id: UUID,
    label: str,
    body: str,
    disclosure: str,
) -> AgentConfig:
    """The agent's own config with the arm's identity, script and disclosure substituted.

    Built from `_to_config` rather than beside it, deliberately: an arm must differ from
    its agent in exactly the three fields below. If a future config field (a new model
    slot, a new cap) is added to `_to_config` and NOT to a hand-rolled variant builder,
    the arms silently run a different configuration from the agent and every measured
    difference is confounded by it — which is the one bug an A/B test cannot survive.

    `agent_id` becomes the VARIANT's id, and that is a statement of fact rather than a
    trick: on the engine, an arm IS its own agent object with its own ref and its own
    routing row, and the identity we hand the vendor has to be one-to-one with the thing
    it names. Neither adapter reads this field to correlate anything back to us —
    `bolna.py` never touches it, `fake.py` derives its deterministic ref from it — so
    passing the agent's id would give the fake ONE ref for both arms and silently publish
    the second script over the first. The bridge back to the real agent is
    `engine_agent_routes`, which is written below and is the only mapping any inbound
    path consults.
    """
    return _to_config(tenant_id, agent).model_copy(
        update={
            "agent_id": str(variant_id),
            "name": f"{agent['name']} [variant {label}]",
            "system_prompt": body,
            # Hard rule 5 travels WITH the arm. The column is NOT NULL and non-empty at
            # the schema, so there is no value of it that publishes an undisclosed agent.
            "disclosure_line": disclosure,
        }
    )


async def publish_variant(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    variant_id: UUID,
    label: str,
    body: str,
    disclosure_line: str,
    existing_ref: str | None,
) -> str:
    """Create or update the engine agent that speaks ONE arm.

    Why an engine agent per arm rather than a per-call prompt override: the portability
    contract carries the script on the AGENT (`AgentConfig.system_prompt`) and
    `start_outbound_call` takes a ref and a `CallContext` of variables — there is no
    prompt slot on a call, in our protocol or in Bolna's. Inventing one would mean
    widening `VoiceEngine` for a feature one adapter can serve, which is the vendor leak
    hard rule 2 exists to stop.

    The routing row is written here for the same reason `publish_agent` writes one: an
    inbound webhook naming the arm's ref must resolve to a tenant and an agent, or the
    reconciliation poller cannot map the call at all.
    """
    agent = await _load_agent(session, tenant_id, agent_id)
    engine = get_engine()
    config = _variant_config(tenant_id, agent, variant_id, label, body, disclosure_line)
    if existing_ref:
        await engine.update_agent(existing_ref, config)
        ref = existing_ref
    else:
        ref = await engine.create_agent(config)
    # An ARM answers real callers with its own script and its own disclosure line, so it
    # gets the same read-back as the agent — verifying the agent and trusting the arms
    # would leave the traffic actually under test as the one path nobody checked.
    verdict = await verify_publish(engine, ref, config)
    if verdict.state == "not_applied":
        if not existing_ref:
            await _reclaim_orphan(engine, agent_id, ref, "variant_read_back_proved_not_applied")
        log.error(
            "agent_variant_publish_not_applied",
            extra={
                "agent_id": str(agent_id),
                "variant_id": str(variant_id),
                "engine": engine.name,
                "prompt_applied": verdict.prompt_applied,
                "disclosure_applied": verdict.disclosure_applied,
            },
        )
        raise ProblemError(
            kind="dependency",
            code="engine_publish_not_applied",
            title="The voice platform is not running this change",
            detail=verdict.detail,
            remediation=(
                "Nothing was recorded as live for this experiment arm. Try publishing again."
            ),
        )
    await session.execute(
        text(
            "UPDATE prompt_experiment_variants SET engine_agent_ref = :ref, updated_at = now() "
            "WHERE id = :vid"
        ),
        {"ref": ref, "vid": variant_id},
    )
    await session.execute(
        text(
            "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
            "active, created_at, updated_at) VALUES (:engine, :ref, :tid, :aid, true, now(), "
            "now()) ON CONFLICT (engine, engine_agent_ref) DO UPDATE SET "
            "tenant_id = EXCLUDED.tenant_id, agent_id = EXCLUDED.agent_id, active = true, "
            "updated_at = now()"
        ),
        {"engine": engine.name, "ref": ref, "tid": tenant_id, "aid": agent_id},
    )
    log.info(
        "agent_variant_published",
        extra={"agent_id": str(agent_id), "variant_id": str(variant_id), "label": label},
    )
    return ref


async def republish_running_variants(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID
) -> int:
    """Push the agent's CURRENT configuration onto every running arm.

    Called from `publish_agent`, so the fast lane keeps working during an experiment.
    Without it, setting a call cap or a voice while a test runs updates the agent object
    the engine is no longer dialling and leaves both arms on the old config — a
    cost-runaway guard that silently stops guarding is the worst possible shape for that
    bug. Each arm keeps its OWN script and disclosure; everything else follows the agent.

    Returns the number of arms republished (0 when nothing is running), which is what
    the caller logs.
    """
    rows = (await session.execute(text(_VARIANT_CONFIG_SQL), {"aid": agent_id})).all()
    for row in rows:
        await publish_variant(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            variant_id=UUID(str(row[0])),
            label=str(row[1]),
            disclosure_line=str(row[2]),
            body=str(row[3]),
            existing_ref=row[4],
        )
    return len(rows)


async def dispatch_call(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    lead_id: UUID | None,
    phone_e164: str,
    lead_name: str | None = None,
    context_note: str | None = None,
) -> str:
    """Place ONE outbound call. The caller has already passed the compliance gate.

    A `queued` call row is written BEFORE the engine call returns, so a dispatch that
    succeeds at the vendor but fails on our side still shows up rather than becoming an
    invisible charge.

    A/B SCRIPT TESTING (ROADMAP M3) IS WIRED HERE, and here is the only place it could
    be. This function is the platform's single outbound entry point — the property
    `scripts/check_compliance_invariants` asserts in its first section — so an
    assignment made here covers the campaign dispatcher, the D-21 "call this lead"
    button and the callback path without any of them knowing an experiment exists.
    Nothing about the gate changes: the caller has already been refused or allowed
    before this line, and choosing WHICH published script to speak cannot un-refuse it.

    The arm decides which engine agent is dialled, and the assignment is written in the
    SAME transaction as the call row it describes.
    """
    agent = await _load_agent(session, tenant_id, agent_id)
    ref = agent["engine_agent_ref"]
    if not isinstance(ref, str) or not ref:
        raise ProblemError.business_rule(
            "agent_not_published",
            "This agent has not been published to the voice platform yet.",
            remediation="Publish the agent from the admin console first.",
        )

    # The stable unit: the lead when there is one, the destination otherwise. See
    # `agents/assignment.py` for why it is not the call id.
    arm = await assignment.assign(
        session, agent_id=agent_id, unit_key=str(lead_id) if lead_id else phone_e164
    )
    # An arm that has never been published has no engine agent to dial. Falling back to
    # the agent's own ref rather than failing: the client's call is the thing that
    # matters, and a call that ran the control is a call, whereas a refused dial is an
    # outage caused by an experiment. It is not recorded as assigned — see below.
    dial_ref = arm.arm.engine_agent_ref if arm and arm.arm.engine_agent_ref else ref

    engine = get_engine()
    handle = await engine.start_outbound_call(
        dial_ref,
        phone_e164,
        CallContext(
            lead_id=str(lead_id) if lead_id else None,
            lead_name=lead_name,
            context_note=context_note,
        ),
    )
    call_id = uuid7()
    inserted = (
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, lead_id, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, "
                "'outbound', :to_e, 'queued', :lid, now(), now()) "
                "ON CONFLICT (engine_call_id) DO NOTHING RETURNING id"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": handle,
                "to_e": phone_e164,
                "lid": lead_id,
            },
        )
    ).first()
    # No row back = this engine call id was already ours, so the call already carries
    # whatever arm it was first assigned. Re-recording would be the one way an
    # assignment could ever move, which is exactly what must not happen.
    if inserted is not None and arm is not None and arm.arm.engine_agent_ref:
        await assignment.record(session, tenant_id=tenant_id, call_id=call_id, assignment=arm)
    return handle


async def provision_number(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    e164: str,
    series: str,
    agent_id: UUID | None,
    provider: str | None,
    purpose: str | None,
) -> UUID:
    """Record a number the tenant may dial from (DATA-MODEL §6, admin-only).

    `series` is the load-bearing field: it is what the campaign launch gate matches
    against the campaign's classification, so getting it wrong here is a DLT violation
    later. `dlt_status` starts `pending` and is a separate deliberate step — a number
    is not registered because we typed it in.

    The number is globally unique (`phone_numbers.e164`), and the collision is caught
    from the UNIQUE INDEX rather than by probing first — deliberately. A probe runs
    under this tenant's RLS, which hides another tenant's rows, so it would report
    "available" for exactly the number that is not, and the insert would then surface
    as a 500. The index sees all tenants because it is the database's, not the
    session's. This is the one place where letting the constraint be the authority is
    the *only* correct answer short of widening RLS for a uniqueness question.
    """
    number_id = uuid7()
    try:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, provider, "
                "dlt_status, purpose, created_at, updated_at) VALUES (:id, :tid, :aid, :e, :s, "
                ":prov, 'pending', :purpose, now(), now())"
            ),
            {
                "id": number_id,
                "tid": tenant_id,
                "aid": agent_id,
                "e": e164,
                "s": series,
                "prov": provider,
                "purpose": purpose,
            },
        )
    except IntegrityError as exc:
        raise ProblemError.conflict(
            "number_taken",
            "This number is already provisioned.",
            remediation="It may belong to another account — check before reassigning it.",
        ) from exc
    return number_id


async def set_number_dlt_status(session: AsyncSession, *, number_id: UUID, dlt_status: str) -> None:
    result = await session.execute(
        text("UPDATE phone_numbers SET dlt_status = :st, updated_at = now() WHERE id = :id"),
        {"st": dlt_status, "id": number_id},
    )
    if rowcount_of(result) == 0:
        raise ProblemError.not_found("Number")


__all__ = [
    "dispatch_call",
    "effective_call_cap",
    "provision_number",
    "publish_agent",
    "publish_variant",
    "republish_running_variants",
    "set_number_dlt_status",
]
