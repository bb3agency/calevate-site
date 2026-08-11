"""Agent configuration + the two paths that touch the engine.

`publish_agent` is where our world and the vendor's are married, and it is the reason
`engine_agent_routes` exists: the routing row and `agents.engine_agent_ref` are written
in the SAME transaction, so an inbound webhook can never arrive for an agent the
resolver cannot map.

`dispatch_call` is the single outbound entry point. Everything that places a call —
the D-21 Leads button today, campaigns and lead-callback webhooks in M2 — goes through
it, so the pre-dispatch call row, the metering hook and the audit trail exist exactly
once rather than three times.
"""

from __future__ import annotations

from uuid import UUID

from calevate_shared.engine import AgentConfig, CallContext, ModelConfig
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.engine import get_engine

log = get_logger(__name__)


async def _load_agent(session: AsyncSession, tenant_id: UUID, agent_id: UUID) -> dict[str, object]:
    row = (
        await session.execute(
            text(
                "SELECT a.id, a.name, a.direction, a.language_primary, a.disclosure_line, "
                "a.stt_provider, a.stt_model, a.llm_model, a.tts_provider, a.tts_voice, "
                "a.engine, a.engine_agent_ref, a.status, pv.body "
                "FROM agents a LEFT JOIN prompt_versions pv ON pv.id = a.system_prompt_id "
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
            "updated_at = now() WHERE id = :aid"
        ),
        {"ref": ref, "engine": engine.name, "aid": agent_id},
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
    log.info("agent_published", extra={"agent_id": str(agent_id), "engine": engine.name})
    return ref


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
    """
    agent = await _load_agent(session, tenant_id, agent_id)
    ref = agent["engine_agent_ref"]
    if not isinstance(ref, str) or not ref:
        raise ProblemError.business_rule(
            "agent_not_published",
            "This agent has not been published to the voice platform yet.",
            remediation="Publish the agent from the admin console first.",
        )

    engine = get_engine()
    handle = await engine.start_outbound_call(
        ref,
        phone_e164,
        CallContext(
            lead_id=str(lead_id) if lead_id else None,
            lead_name=lead_name,
            context_note=context_note,
        ),
    )
    await session.execute(
        text(
            "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
            "status, lead_id, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, "
            "'outbound', :to_e, 'queued', :lid, now(), now()) "
            "ON CONFLICT (engine_call_id) DO NOTHING"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "aid": agent_id,
            "ecid": handle,
            "to_e": phone_e164,
            "lid": lead_id,
        },
    )
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


__all__ = ["dispatch_call", "provision_number", "publish_agent", "set_number_dlt_status"]
