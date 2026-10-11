"""Two call settings a client decides per agent or for the whole account (D-751).

- **Pause before the agent replies**: how long the caller must be quiet before their turn is
  over and the agent answers. Too short and a caller reading out a phone number is answered
  half way through it; too long and every reply waits.
- **Hang up when the conversation ends**: the agent releases the line when it has finished,
  rather than leaving it open, and billed, until the caller puts the phone down.

Each resolves agent -> organisation -> Calevate, the order the language model already uses
(`agents/llm_models.resolve_llm_model`): NULL on `agents` inherits the account's value, NULL
on `organizations` inherits the platform constant here. The resolution is this module's and
nobody else's, so the publish path (`service._to_config`), the screens and the copilot read
one answer.

Milliseconds as a bounded integer, not seconds as NUMERIC: the value is a duration with a
vendor floor of 0.2 s and no stated step, never money and never summed, so an integer holds
every value a person can mean exactly and the CHECK states the vendor range in whole units.
The adapter divides by 1000 only at the wire.

A change reaches the phone line through the live apply (D-720), queued in the saving
transaction: one agent for an agent's own value, the client's agents for an account default
that a live agent inherits. A call in progress finishes as it started.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.live_apply import queue_live_apply
from apps.api.agents.models import TURN_SILENCE_MAX_MS, TURN_SILENCE_MIN_MS
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

#: Calevate's default: the vendor's own, "0.25 s on most lines" (same pages). Kept rather
#: than raised, D-751 gives the reason: the delay is paid on every reply of every call, while
#: the dictation case it would help is already handled by asking for numbers a few digits at a
#: time (D-749), and an agent that takes numbers can be given a longer pause of its own.
TURN_SILENCE_DEFAULT_MS: Final = 250
#: On: a finished call that stays open bills every minute until the caller hangs up, and a new
#: vendor agent starts with it off (D-749).
END_CALL_ON_FINISH_DEFAULT: Final = True

SettingSource = Literal["agent", "organization", "platform"]


@dataclass(frozen=True, slots=True)
class TurnSilence:
    ms: int
    source: SettingSource


@dataclass(frozen=True, slots=True)
class EndCallOnFinish:
    enabled: bool
    source: SettingSource


def resolve_turn_silence(agent_ms: int | None, organization_ms: int | None) -> TurnSilence:
    if agent_ms is not None:
        return TurnSilence(agent_ms, "agent")
    if organization_ms is not None:
        return TurnSilence(organization_ms, "organization")
    return TurnSilence(TURN_SILENCE_DEFAULT_MS, "platform")


def resolve_end_call_on_finish(agent: bool | None, organization: bool | None) -> EndCallOnFinish:
    if agent is not None:
        return EndCallOnFinish(agent, "agent")
    if organization is not None:
        return EndCallOnFinish(organization, "organization")
    return EndCallOnFinish(END_CALL_ON_FINISH_DEFAULT, "platform")


def refuse_turn_silence_out_of_range(ms: int | None, *, field: str) -> None:
    """The range check every writer runs: the CHECK is the floor, this is the sentence."""
    if ms is None or TURN_SILENCE_MIN_MS <= ms <= TURN_SILENCE_MAX_MS:
        return
    raise ProblemError(
        kind="validation",
        code="turn_silence_out_of_range",
        title="Pause before replying is out of range",
        detail=(
            f"The pause before the agent replies must be between "
            f"{TURN_SILENCE_MIN_MS / 1000:g} and {TURN_SILENCE_MAX_MS / 1000:g} seconds."
        ),
        remediation=(
            "Choose a pause in that range, or clear it to use the default "
            f"({TURN_SILENCE_DEFAULT_MS / 1000:g} seconds)."
        ),
        fields=[
            {
                "field": field,
                "rule": "out_of_range",
                "message": (
                    f"Must be {TURN_SILENCE_MIN_MS}-{TURN_SILENCE_MAX_MS} milliseconds, or "
                    "null to inherit."
                ),
            }
        ],
    )


@dataclass(frozen=True, slots=True)
class AgentCallHandling:
    agent_id: UUID
    #: The agent's own values; None inherits.
    turn_silence_ms: int | None
    end_call_on_finish: bool | None
    #: The account's values; None follows Calevate's.
    organization_turn_silence_ms: int | None
    organization_end_call_on_finish: bool | None
    turn_silence: TurnSilence
    end_call: EndCallOnFinish


@dataclass(frozen=True, slots=True)
class OrganizationCallHandling:
    turn_silence_ms: int | None
    end_call_on_finish: bool | None
    turn_silence: TurnSilence
    end_call: EndCallOnFinish


_AGENT_ROW = (
    "SELECT a.turn_silence_ms, a.end_call_on_finish, o.default_turn_silence_ms, "
    "o.default_end_call_on_finish, a.status, a.engine_agent_ref "
    "FROM agents a LEFT JOIN organizations o ON o.id = a.tenant_id "
    "WHERE a.id = :aid AND a.deleted_at IS NULL"
)
_ORG_ROW = (
    "SELECT default_turn_silence_ms, default_end_call_on_finish FROM organizations "
    "WHERE deleted_at IS NULL"
)


def _agent_state(agent_id: UUID, row: tuple[object, ...]) -> AgentCallHandling:
    own_ms, own_end, org_ms, org_end = (
        _int_or_none(row[0]),
        _bool_or_none(row[1]),
        _int_or_none(row[2]),
        _bool_or_none(row[3]),
    )
    return AgentCallHandling(
        agent_id=agent_id,
        turn_silence_ms=own_ms,
        end_call_on_finish=own_end,
        organization_turn_silence_ms=org_ms,
        organization_end_call_on_finish=org_end,
        turn_silence=resolve_turn_silence(own_ms, org_ms),
        end_call=resolve_end_call_on_finish(own_end, org_end),
    )


def _int_or_none(value: object) -> int | None:
    return None if value is None else int(str(value))


def _bool_or_none(value: object) -> bool | None:
    return None if value is None else bool(value)


async def read_agent_call_handling(session: AsyncSession, agent_id: UUID) -> AgentCallHandling:
    """One agent's two settings with where each comes from. RLS scopes the read, so another
    client's agent is a 404 exactly like a missing one."""
    row = (await session.execute(text(_AGENT_ROW), {"aid": agent_id})).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    return _agent_state(agent_id, tuple(row))


#: The fields a PATCH may name. A field left out is untouched; null inherits.
AGENT_FIELDS: Final = ("turn_silence_ms", "end_call_on_finish")


async def set_agent_call_handling(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    changes: dict[str, int | bool | None],
) -> tuple[AgentCallHandling, tuple[str, ...]]:
    """Write the named fields on one agent and queue its live apply when it is live.

    The row is locked first so "did this change?" and the write are one step, and a repeat
    of the value already held writes nothing and queues nothing. Answers the new state and the
    fields that moved."""
    unknown = set(changes) - set(AGENT_FIELDS)
    if unknown:
        raise ValueError(f"not a call handling field: {sorted(unknown)}")
    if "turn_silence_ms" in changes:
        ms = changes["turn_silence_ms"]
        refuse_turn_silence_out_of_range(None if ms is None else int(ms), field="turn_silence_ms")
    row = (
        await session.execute(
            text(
                "SELECT turn_silence_ms, end_call_on_finish, status, engine_agent_ref "
                "FROM agents WHERE id = :aid AND deleted_at IS NULL FOR UPDATE"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    current: dict[str, int | bool | None] = {
        "turn_silence_ms": _int_or_none(row[0]),
        "end_call_on_finish": _bool_or_none(row[1]),
    }
    moved = tuple(f for f in AGENT_FIELDS if f in changes and changes[f] != current[f])
    if moved:
        wanted: dict[str, int | bool | None] = {**current, **{f: changes[f] for f in moved}}
        await session.execute(
            text(
                "UPDATE agents SET turn_silence_ms = :ms, end_call_on_finish = :end, "
                "updated_at = now() WHERE id = :aid"
            ),
            {
                "ms": wanted["turn_silence_ms"],
                "end": wanted["end_call_on_finish"],
                "aid": agent_id,
            },
        )
        if str(row[2]) == "live" and row[3]:
            await queue_live_apply(
                session,
                scope="agent",
                tenant_id=tenant_id,
                agent_id=agent_id,
                reason="call_handling",
            )
    log.info(
        "agent_call_handling_set",
        extra={"agent_id": str(agent_id), "changed": list(moved)},
    )
    return await read_agent_call_handling(session, agent_id), moved


async def read_organization_call_handling(session: AsyncSession) -> OrganizationCallHandling:
    row = (await session.execute(text(_ORG_ROW))).first()
    if row is None:
        raise ProblemError.not_found("Organization")
    ms, end = _int_or_none(row[0]), _bool_or_none(row[1])
    return OrganizationCallHandling(
        turn_silence_ms=ms,
        end_call_on_finish=end,
        turn_silence=resolve_turn_silence(None, ms),
        end_call=resolve_end_call_on_finish(None, end),
    )


_LIVE_AGENT = (
    "SELECT 1 FROM agents WHERE deleted_at IS NULL AND status = 'live' "
    "AND engine_agent_ref IS NOT NULL AND "
)
#: Per field: a live agent that inherits the account value, so changing it moves a line.
_INHERITING_LIVE_AGENT: Final = {
    "turn_silence_ms": _LIVE_AGENT + "turn_silence_ms IS NULL LIMIT 1",
    "end_call_on_finish": _LIVE_AGENT + "end_call_on_finish IS NULL LIMIT 1",
}


async def set_organization_call_handling(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    turn_silence_ms: int | None,
    end_call_on_finish: bool | None,
) -> tuple[OrganizationCallHandling, tuple[str, ...]]:
    """Replace the account's two defaults (null follows Calevate's) and queue the client's
    live apply when a live agent inherits a value that moved."""
    refuse_turn_silence_out_of_range(turn_silence_ms, field="turn_silence_ms")
    row = (
        await session.execute(
            text(
                "SELECT default_turn_silence_ms, default_end_call_on_finish "
                "FROM organizations WHERE deleted_at IS NULL FOR UPDATE"
            )
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Organization")
    current = {
        "turn_silence_ms": _int_or_none(row[0]),
        "end_call_on_finish": _bool_or_none(row[1]),
    }
    wanted: dict[str, int | bool | None] = {
        "turn_silence_ms": turn_silence_ms,
        "end_call_on_finish": end_call_on_finish,
    }
    moved = tuple(f for f in AGENT_FIELDS if wanted[f] != current[f])
    if moved:
        await session.execute(
            text(
                "UPDATE organizations SET default_turn_silence_ms = :ms, "
                "default_end_call_on_finish = :end, updated_at = now() "
                "WHERE deleted_at IS NULL"
            ),
            {"ms": turn_silence_ms, "end": end_call_on_finish},
        )
        for field in moved:
            sql = _INHERITING_LIVE_AGENT[field]
            if (await session.execute(text(sql))).first() is not None:
                await queue_live_apply(
                    session, scope="tenant", tenant_id=tenant_id, reason="call_handling"
                )
                break
    log.info(
        "organization_call_handling_set",
        extra={"tenant_id": str(tenant_id), "changed": list(moved)},
    )
    return await read_organization_call_handling(session), moved


__all__ = [
    "AGENT_FIELDS",
    "END_CALL_ON_FINISH_DEFAULT",
    "TURN_SILENCE_DEFAULT_MS",
    "TURN_SILENCE_MAX_MS",
    "TURN_SILENCE_MIN_MS",
    "AgentCallHandling",
    "EndCallOnFinish",
    "OrganizationCallHandling",
    "SettingSource",
    "TurnSilence",
    "read_agent_call_handling",
    "read_organization_call_handling",
    "refuse_turn_silence_out_of_range",
    "resolve_end_call_on_finish",
    "resolve_turn_silence",
    "set_agent_call_handling",
    "set_organization_call_handling",
]
