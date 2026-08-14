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

from typing import cast
from uuid import UUID

from calevate_shared.engine import AgentConfig, CallContext, ModelConfig
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import assignment
from apps.api.agents.models import CALL_CAP_DEFAULT_S
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


async def _load_agent(session: AsyncSession, tenant_id: UUID, agent_id: UUID) -> dict[str, object]:
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


def _to_config(tenant_id: UUID, agent: dict[str, object]) -> AgentConfig:
    settings = get_settings()
    return AgentConfig(
        tenant_id=str(tenant_id),
        agent_id=str(agent["id"]),
        name=str(agent["name"]),
        direction=str(agent["direction"]),
        language_primary=str(agent["language_primary"]),
        system_prompt=str(agent["prompt"] or "You are a helpful receptionist."),
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


async def publish_agent(session: AsyncSession, *, tenant_id: UUID, agent_id: UUID) -> str:
    """Create or update the agent on the engine, then record the mapping.

    The routing row is written HERE, in the same transaction as `engine_agent_ref`,
    because the alternative — writing it from a webhook handler on first sight — means
    the first call for a new agent is the one that gets lost.
    """
    agent = await _load_agent(session, tenant_id, agent_id)
    engine = get_engine()
    config = _to_config(tenant_id, agent)

    existing_ref = agent["engine_agent_ref"]
    if isinstance(existing_ref, str) and existing_ref:
        await engine.update_agent(existing_ref, config)
        ref = existing_ref
    else:
        ref = await engine.create_agent(config)

    await session.execute(
        text(
            "UPDATE agents SET engine_agent_ref = :ref, engine = :engine, status = 'live', "
            "live_tts_voice = :live_voice, live_tts_provider = :live_provider, "
            "updated_at = now() WHERE id = :aid"
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
        },
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
    log.info("agent_published", extra={"agent_id": str(agent_id), "engine": engine.name})
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
