"""The call settings a client decides per agent or for the account, as endpoints (D-751, F3, F9).

    GET   /v1/agents/{agent_id}/call-handling                       one agent's, with sources
    PATCH /v1/agents/{agent_id}/call-handling                       set or inherit (owner)
    GET   /v1/organization/call-handling                            the account's defaults
    PUT   /v1/organization/call-handling                            set them (owner)
    POST  /v1/organization/call-handling/all-agents                 one value on every agent
    POST  /v1/agents/{agent_id}/call-handling/patient-caller        the "Give callers time" preset
    GET   /v1/admin/tenants/{tid}/agents/{aid}/call-handling        the operator's view
    PATCH /v1/admin/tenants/{tid}/agents/{aid}/call-handling        the operator's door
    POST  /v1/admin/tenants/{tid}/agents/{aid}/call-handling/patient-caller   the same preset
    GET   /v1/admin/organizations/{org_id}/call-handling            the operator's view
    PUT   /v1/admin/organizations/{org_id}/call-handling            the operator's door

The writes are `org:manage`, the owner's, as caller memory's are: switching the hang-up off
leaves a finished call billed until the caller puts the phone down, which is a decision about
the account's money. Both realms call one writer (`agents/call_handling`), which queues the
live apply in the saving transaction (D-720), so the next call uses the new value.

The account PUT names the pause and the hang-up, as it did before the F3 settings existed; the
F3 settings it leaves out are kept, so a caller written for the first two cannot clear the rest.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from calevate_shared.engine import TurnDetection
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import call_handling, patient_caller
from apps.api.agents.call_handling import (
    AMBIENCE_VOLUME_DEFAULT_PCT,
    END_AFTER_SILENCE_DEFAULT_S,
    END_CALL_ON_FINISH_DEFAULT,
    NUDGE_AFTER_DEFAULT_S,
    NUDGE_COUNT_DEFAULT,
    REASK_AFTER_DEFAULT_MS,
    TURN_SILENCE_DEFAULT_MS,
    AgentCallHandling,
    CallSettings,
    OrganizationCallHandling,
    SettingSource,
)
from apps.api.agents.models import (
    AMBIENCE_VOLUME_MAX_PCT,
    AMBIENCE_VOLUME_MIN_PCT,
    END_AFTER_SILENCE_MAX_S,
    END_AFTER_SILENCE_MIN_S,
    FILLER_LINE_MAX_CHARS,
    FILLER_LINES_MAX,
    NUDGE_AFTER_MAX_S,
    NUDGE_AFTER_MIN_S,
    NUDGE_COUNT_MAX,
    NUDGE_COUNT_MIN,
    NUDGE_PHRASE_MAX_CHARS,
    OPENING_WAIT_MAX_MS,
    OPENING_WAIT_MIN_MS,
    OPENING_WAIT_STEP_MS,
    REASK_AFTER_MAX_MS,
    REASK_AFTER_MIN_MS,
    REASK_AFTER_STEP_MS,
    TURN_SILENCE_MAX_MS,
    TURN_SILENCE_MIN_MS,
)
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session

Session = Annotated[AsyncSession, Depends(db)]
AgentReader = Annotated[Principal, Depends(requires("agents:read"))]
OrgReader = Annotated[Principal, Depends(requires("org:read"))]
Owner = Annotated[Principal, Depends(requires("org:manage"))]
AgentOperator = Annotated[Principal, Depends(requires("agents:write", realm="admin"))]
Operator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]

router = APIRouter(tags=["agents"])
admin_router = APIRouter(tags=["admin"])

Ambience = Literal["off", "office", "office-quiet"]

#: Bounds on the request body itself, far above any real value: the writer's range checks
#: answer an out-of-range value in plain words; these only stop an oversized body.
_TEXT_CAP = 1000
_LINES_CAP = 50


class CallHandlingBoundsOut(BaseModel):
    """What may be chosen and what Calevate's own defaults are."""

    model_config = ConfigDict(extra="forbid")

    turn_silence_min_ms: int
    turn_silence_max_ms: int
    platform_turn_silence_ms: int
    platform_end_call_on_finish: bool
    #: `nudge_after_seconds` 0 is "never ask".
    nudge_after_min_s: int
    nudge_after_max_s: int
    platform_nudge_after_seconds: int
    nudge_count_min: int
    nudge_count_max: int
    platform_nudge_count: int
    nudge_phrase_max_chars: int
    end_after_silence_min_s: int
    end_after_silence_max_s: int
    platform_end_after_silence_seconds: int
    filler_lines_max: int
    filler_line_max_chars: int
    ambiences: list[Ambience]
    platform_ambience: Ambience
    ambience_volume_min_pct: int
    ambience_volume_max_pct: int
    platform_ambience_volume_pct: int
    #: How long an opening that waits for hello waits through silence (D-901). Offered only
    #: while `opening_wait_available`; `platform_opening_wait_ms` null is the voice platform's
    #: own four seconds.
    opening_wait_available: bool
    opening_wait_min_ms: int
    opening_wait_max_ms: int
    opening_wait_step_ms: int
    platform_opening_wait_ms: int | None
    #: How long before an unanswered question is asked again (D-907); `reask_after_ms` 0 is
    #: never.
    reask_after_min_ms: int
    reask_after_max_ms: int
    reask_after_step_ms: int
    platform_reask_after_ms: int


def _bounds(own_turn_detection: TurnDetection | None = None) -> CallHandlingBoundsOut:
    return CallHandlingBoundsOut(
        turn_silence_min_ms=TURN_SILENCE_MIN_MS,
        turn_silence_max_ms=TURN_SILENCE_MAX_MS,
        platform_turn_silence_ms=call_handling.platform_turn_silence_ms(own_turn_detection),
        platform_end_call_on_finish=END_CALL_ON_FINISH_DEFAULT,
        nudge_after_min_s=NUDGE_AFTER_MIN_S,
        nudge_after_max_s=NUDGE_AFTER_MAX_S,
        platform_nudge_after_seconds=NUDGE_AFTER_DEFAULT_S,
        nudge_count_min=NUDGE_COUNT_MIN,
        nudge_count_max=NUDGE_COUNT_MAX,
        platform_nudge_count=NUDGE_COUNT_DEFAULT,
        nudge_phrase_max_chars=NUDGE_PHRASE_MAX_CHARS,
        end_after_silence_min_s=END_AFTER_SILENCE_MIN_S,
        end_after_silence_max_s=END_AFTER_SILENCE_MAX_S,
        platform_end_after_silence_seconds=END_AFTER_SILENCE_DEFAULT_S,
        filler_lines_max=FILLER_LINES_MAX,
        filler_line_max_chars=FILLER_LINE_MAX_CHARS,
        ambiences=["off", "office", "office-quiet"],
        platform_ambience="off",
        ambience_volume_min_pct=AMBIENCE_VOLUME_MIN_PCT,
        ambience_volume_max_pct=AMBIENCE_VOLUME_MAX_PCT,
        platform_ambience_volume_pct=AMBIENCE_VOLUME_DEFAULT_PCT,
        opening_wait_available=call_handling.opening_wait_available(),
        opening_wait_min_ms=OPENING_WAIT_MIN_MS,
        opening_wait_max_ms=OPENING_WAIT_MAX_MS,
        opening_wait_step_ms=OPENING_WAIT_STEP_MS,
        platform_opening_wait_ms=call_handling.platform_settings().opening_wait_ms,
        reask_after_min_ms=REASK_AFTER_MIN_MS,
        reask_after_max_ms=REASK_AFTER_MAX_MS,
        reask_after_step_ms=REASK_AFTER_STEP_MS,
        platform_reask_after_ms=REASK_AFTER_DEFAULT_MS,
    )


class PatientCallerOut(BaseModel):
    """The "Give callers time" preset (D-907) for this agent: what it sets and whether the
    settings in force match it."""

    model_config = ConfigDict(extra="forbid")

    #: The settings in force match the preset (its question aside, which is the owner's).
    applied: bool
    nudge_after_seconds: int
    nudge_count: int
    #: The question in the agent's main language; "" is the standard one.
    nudge_phrase: str
    end_after_silence_seconds: int
    #: 0: an unanswered question is not asked again on a timer.
    reask_after_ms: int
    #: The longest call the preset raises the agent's to, in seconds; a longer one is kept.
    call_cap_s: int


class AgentCallHandlingOut(BaseModel):
    """One agent's settings: its own value (`null` inherits), the value in force and the level
    that chose it (`agent`, `organization` or `platform`)."""

    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    turn_silence_ms: int | None
    turn_silence_ms_effective: int
    turn_silence_source: SettingSource
    #: Whether the pause decides anything on this agent's calls: false while its turns end by
    #: real-time listening, where the pause is not used (D-903). Still stored and sent.
    turn_silence_applies: bool
    end_call_on_finish: bool | None
    end_call_on_finish_effective: bool
    end_call_on_finish_source: SettingSource
    #: Seconds of quiet before asking whether the caller is still there; 0 is never.
    nudge_after_seconds: int | None
    nudge_after_seconds_effective: int
    nudge_after_seconds_source: SettingSource
    nudge_count: int | None
    nudge_count_effective: int
    nudge_count_source: SettingSource
    #: The client's own question; "" is the standard one, in the caller's language.
    nudge_phrase: str | None
    nudge_phrase_effective: str
    nudge_phrase_source: SettingSource
    end_after_silence_seconds: int | None
    end_after_silence_seconds_effective: int
    end_after_silence_seconds_source: SettingSource
    #: The client's own lines while the agent looks something up; [] is the standard ones.
    filler_lines: list[str] | None
    filler_lines_effective: list[str]
    filler_lines_source: SettingSource
    ambience: Ambience | None
    ambience_effective: Ambience
    ambience_source: SettingSource
    ambience_volume_pct: int | None
    ambience_volume_pct_effective: int
    ambience_volume_pct_source: SettingSource
    #: Milliseconds of silence before an opening that waits for hello plays anyway (D-901);
    #: `_effective` null is the voice platform's own four seconds.
    opening_wait_ms: int | None
    opening_wait_ms_effective: int | None
    opening_wait_ms_source: SettingSource
    #: Milliseconds before an unanswered question is asked again; 0 is never (D-907).
    reask_after_ms: int | None
    reask_after_ms_effective: int
    reask_after_ms_source: SettingSource
    #: The opening waits for the person who picked up to speak (D-871). The agent's own,
    #: never inherited.
    opening_waits_for_caller: bool
    #: The account defaults an agent with no value of its own follows (`null`: Calevate's).
    organization_turn_silence_ms: int | None
    organization_end_call_on_finish: bool | None
    organization_nudge_after_seconds: int | None
    organization_nudge_count: int | None
    organization_nudge_phrase: str | None
    organization_end_after_silence_seconds: int | None
    organization_filler_lines: list[str] | None
    organization_ambience: Ambience | None
    organization_ambience_volume_pct: int | None
    organization_opening_wait_ms: int | None
    organization_reask_after_ms: int | None
    bounds: CallHandlingBoundsOut
    patient_caller: PatientCallerOut


class AgentCallHandlingIn(BaseModel):
    """Any of the settings. A field left out is untouched; `null` goes back to inheriting,
    except `opening_waits_for_caller`, which inherits nothing and takes only true or false."""

    model_config = ConfigDict(extra="forbid")

    # Optional in the schema like its siblings; the writer refuses an explicit null.
    opening_waits_for_caller: bool | None = Field(default=None)
    turn_silence_ms: int | None = Field(default=None)
    end_call_on_finish: bool | None = Field(default=None)
    nudge_after_seconds: int | None = Field(default=None)
    nudge_count: int | None = Field(default=None)
    nudge_phrase: str | None = Field(default=None, max_length=_TEXT_CAP)
    end_after_silence_seconds: int | None = Field(default=None)
    filler_lines: list[Annotated[str, Field(max_length=_TEXT_CAP)]] | None = Field(
        default=None, max_length=_LINES_CAP
    )
    ambience: Ambience | None = Field(default=None)
    ambience_volume_pct: int | None = Field(default=None)
    opening_wait_ms: int | None = Field(default=None)
    reask_after_ms: int | None = Field(default=None)


class AgentOwnCallHandlingOut(BaseModel):
    """One agent's own values (`null`: it follows the account default for that setting)."""

    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    name: str
    turn_silence_ms: int | None
    end_call_on_finish: bool | None
    nudge_after_seconds: int | None
    nudge_count: int | None
    nudge_phrase: str | None
    end_after_silence_seconds: int | None
    filler_lines: list[str] | None
    ambience: Ambience | None
    ambience_volume_pct: int | None
    opening_wait_ms: int | None
    reask_after_ms: int | None


class OrganizationCallHandlingOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The account's own choice; `null` follows Calevate's default.
    turn_silence_ms: int | None
    turn_silence_ms_effective: int
    end_call_on_finish: bool | None
    end_call_on_finish_effective: bool
    nudge_after_seconds: int | None
    nudge_after_seconds_effective: int
    nudge_count: int | None
    nudge_count_effective: int
    nudge_phrase: str | None
    nudge_phrase_effective: str
    end_after_silence_seconds: int | None
    end_after_silence_seconds_effective: int
    filler_lines: list[str] | None
    filler_lines_effective: list[str]
    ambience: Ambience | None
    ambience_effective: Ambience
    ambience_volume_pct: int | None
    ambience_volume_pct_effective: int
    opening_wait_ms: int | None
    opening_wait_ms_effective: int | None
    reask_after_ms: int | None
    reask_after_ms_effective: int
    #: The agents that set any value of their own, which these defaults do not reach for
    #: that value; at most `call_handling.AGENTS_WITH_OWN_MAX`, by name.
    agents_with_own: list[AgentOwnCallHandlingOut]
    #: How many agents set any value of their own, including any past the ones listed.
    agents_with_own_total: int
    bounds: CallHandlingBoundsOut


class OrganizationCallHandlingIn(BaseModel):
    """The pause and the hang-up, required as before (`null` is "follow Calevate"). Every
    other setting is optional: named, it is set (`null` follows Calevate); left out, it is
    kept."""

    model_config = ConfigDict(extra="forbid")

    turn_silence_ms: int | None
    end_call_on_finish: bool | None
    nudge_after_seconds: int | None = Field(default=None)
    nudge_count: int | None = Field(default=None)
    nudge_phrase: str | None = Field(default=None, max_length=_TEXT_CAP)
    end_after_silence_seconds: int | None = Field(default=None)
    filler_lines: list[Annotated[str, Field(max_length=_TEXT_CAP)]] | None = Field(
        default=None, max_length=_LINES_CAP
    )
    ambience: Ambience | None = Field(default=None)
    ambience_volume_pct: int | None = Field(default=None)
    opening_wait_ms: int | None = Field(default=None)
    reask_after_ms: int | None = Field(default=None)


class AllAgentsCallHandlingIn(BaseModel):
    """The settings to use on every agent. A field left out is untouched; `null` follows
    Calevate's default. At least one is named."""

    model_config = ConfigDict(extra="forbid")

    turn_silence_ms: int | None = Field(default=None)
    end_call_on_finish: bool | None = Field(default=None)
    nudge_after_seconds: int | None = Field(default=None)
    nudge_count: int | None = Field(default=None)
    nudge_phrase: str | None = Field(default=None, max_length=_TEXT_CAP)
    end_after_silence_seconds: int | None = Field(default=None)
    filler_lines: list[Annotated[str, Field(max_length=_TEXT_CAP)]] | None = Field(
        default=None, max_length=_LINES_CAP
    )
    ambience: Ambience | None = Field(default=None)
    ambience_volume_pct: int | None = Field(default=None)
    opening_wait_ms: int | None = Field(default=None)
    reask_after_ms: int | None = Field(default=None)


class AllAgentsCallHandlingOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization: OrganizationCallHandlingOut
    #: How many agents had a value of their own for a named setting, now dropped.
    agents_reset: int


def _lines(value: tuple[str, ...] | None) -> list[str] | None:
    return None if value is None else list(value)


def _ambience(value: str | None) -> Ambience | None:
    if value is None:
        return None
    if value == "office":
        return "office"
    if value == "office-quiet":
        return "office-quiet"
    return "off"


def _effective(values: CallSettings) -> dict[str, object]:
    """The `*_effective` fields of a resolved `CallSettings` (every value is set)."""
    return {
        "turn_silence_ms_effective": values.turn_silence_ms,
        "end_call_on_finish_effective": values.end_call_on_finish,
        "nudge_after_seconds_effective": values.nudge_after_seconds,
        "nudge_count_effective": values.nudge_count,
        "nudge_phrase_effective": values.nudge_phrase,
        "end_after_silence_seconds_effective": values.end_after_silence_seconds,
        "filler_lines_effective": list(values.filler_lines or ()),
        "ambience_effective": _ambience(values.ambience) or "off",
        "ambience_volume_pct_effective": values.ambience_volume_pct,
        "opening_wait_ms_effective": values.opening_wait_ms,
        "reask_after_ms_effective": values.reask_after_ms,
    }


def _own(values: CallSettings, prefix: str = "") -> dict[str, object]:
    return {
        f"{prefix}turn_silence_ms": values.turn_silence_ms,
        f"{prefix}end_call_on_finish": values.end_call_on_finish,
        f"{prefix}nudge_after_seconds": values.nudge_after_seconds,
        f"{prefix}nudge_count": values.nudge_count,
        f"{prefix}nudge_phrase": values.nudge_phrase,
        f"{prefix}end_after_silence_seconds": values.end_after_silence_seconds,
        f"{prefix}filler_lines": _lines(values.filler_lines),
        f"{prefix}ambience": _ambience(values.ambience),
        f"{prefix}ambience_volume_pct": values.ambience_volume_pct,
        f"{prefix}opening_wait_ms": values.opening_wait_ms,
        f"{prefix}reask_after_ms": values.reask_after_ms,
    }


def _patient_out(preset: patient_caller.PatientCaller) -> PatientCallerOut:
    return PatientCallerOut(
        applied=preset.applied,
        nudge_after_seconds=patient_caller.NUDGE_AFTER_S,
        nudge_count=patient_caller.NUDGE_COUNT,
        nudge_phrase=preset.nudge_phrase,
        end_after_silence_seconds=patient_caller.END_AFTER_SILENCE_S,
        reask_after_ms=patient_caller.REASK_AFTER_MS,
        call_cap_s=preset.call_cap_s,
    )


async def _agent_response(session: AsyncSession, state: AgentCallHandling) -> AgentCallHandlingOut:
    """The agent's settings and its "Give callers time" preset, read in the same session."""
    return _agent_out(state, await patient_caller.read_patient_caller(session, state))


def _agent_out(
    state: AgentCallHandling, preset: patient_caller.PatientCaller
) -> AgentCallHandlingOut:
    sources = state.resolved.sources
    return AgentCallHandlingOut.model_validate(
        {
            "agent_id": state.agent_id,
            **_own(state.own),
            **_effective(state.resolved.values),
            "turn_silence_source": sources["turn_silence_ms"],
            "turn_silence_applies": state.turn_silence_applies,
            "end_call_on_finish_source": sources["end_call_on_finish"],
            **{
                f"{field}_source": sources[field]
                for field in call_handling.SETTING_FIELDS
                if field not in ("turn_silence_ms", "end_call_on_finish")
            },
            "opening_waits_for_caller": state.opening_waits_for_caller,
            **_own(state.organization, "organization_"),
            "bounds": _bounds(state.turn_detection),
            "patient_caller": _patient_out(preset),
        }
    )


def _org_out(state: OrganizationCallHandling) -> OrganizationCallHandlingOut:
    return OrganizationCallHandlingOut.model_validate(
        {
            **_own(state.own),
            **_effective(state.resolved.values),
            "agents_with_own": [
                {"agent_id": agent.agent_id, "name": agent.name, **_own(agent.own)}
                for agent in state.agents_with_own
            ],
            "agents_with_own_total": state.agents_with_own_total,
            "bounds": _bounds(),
        }
    )


def _changes(payload: BaseModel) -> dict[str, object]:
    return {
        f: getattr(payload, f)
        for f in (*call_handling.SETTING_FIELDS, *call_handling.AGENT_ONLY_FIELDS)
        if f in payload.model_fields_set
    }


def _org_changes(payload: OrganizationCallHandlingIn) -> dict[str, object]:
    """The two required settings always; the rest only when named."""
    return {
        **_changes(payload),
        "turn_silence_ms": payload.turn_silence_ms,
        "end_call_on_finish": payload.end_call_on_finish,
    }


def _audit_summary(changes: dict[str, object], moved: tuple[str, ...]) -> dict[str, object]:
    """What was asked and what moved. The client's own words (the question and the filler
    lines) are summarised by length, never copied into the audit trail."""
    summary: dict[str, object] = {
        key: value for key, value in changes.items() if key not in ("nudge_phrase", "filler_lines")
    }
    if "nudge_phrase" in changes:
        phrase = changes["nudge_phrase"]
        summary["nudge_phrase_chars"] = None if phrase is None else len(str(phrase))
    if "filler_lines" in changes:
        lines = changes["filler_lines"]
        summary["filler_lines_count"] = None if not isinstance(lines, list) else len(lines)
    summary["changed"] = list(moved)
    return summary


_AGENT_DESCRIPTION = (
    "`turn_silence_ms` is the quiet after the caller's last words that ends their turn, "
    f"{TURN_SILENCE_MIN_MS}-{TURN_SILENCE_MAX_MS} ms; longer suits callers reading out "
    "numbers, shorter answers sooner. It is used only while the agent's turns end by "
    "silence: `turn_silence_applies` is false when they end by real-time listening, where "
    "the value is kept but not used. `end_call_on_finish` releases the line when the agent "
    "has finished; with it off a finished call stays connected, and charged, until the caller "
    "hangs up.\n\n"
    "If the caller goes quiet: `nudge_after_seconds` "
    f"({NUDGE_AFTER_MIN_S}-{NUDGE_AFTER_MAX_S}, or 0 for never) is when the agent asks whether "
    f"they are still there, `nudge_count` ({NUDGE_COUNT_MIN}-{NUDGE_COUNT_MAX}) how many times, "
    f'`nudge_phrase` (up to {NUDGE_PHRASE_MAX_CHARS} characters, "" for the standard question '
    "in the caller's language) what it says, and `end_after_silence_seconds` "
    f"({END_AFTER_SILENCE_MIN_S}-{END_AFTER_SILENCE_MAX_S}) when it hangs up. `filler_lines` "
    f"(up to {FILLER_LINES_MAX} of {FILLER_LINE_MAX_CHARS} characters, [] for the standard "
    "ones) are said while the agent looks something up. `ambience` is a background sound "
    f"(`off`, `office`, `office-quiet`) at `ambience_volume_pct` "
    f"({AMBIENCE_VOLUME_MIN_PCT}-{AMBIENCE_VOLUME_MAX_PCT}).\n\n"
    "`opening_waits_for_caller` holds the agent's first words until the person who picked "
    "up speaks, or `opening_wait_ms` of silence; it is the agent's own (true or false, never "
    "inherited), on by default for an agent that only places calls. `opening_wait_ms` "
    f"({OPENING_WAIT_MIN_MS}-{OPENING_WAIT_MAX_MS} in steps of {OPENING_WAIT_STEP_MS}) "
    "inherits like the settings below; it may be set only while "
    "`bounds.opening_wait_available`, and an effective null is four seconds "
    "(`opening_wait_unavailable` otherwise).\n\n"
    "`reask_after_ms` is how long the agent waits, after a question it asked has had no "
    f"answer, before asking it again: {REASK_AFTER_MIN_MS}-{REASK_AFTER_MAX_MS} in steps of "
    f"{REASK_AFTER_STEP_MS}, or 0 for never.\n\n"
    "Each other setting resolves agent, then the account default, then Calevate's "
    f"(`bounds.platform_turn_silence_ms`, {TURN_SILENCE_DEFAULT_MS} ms on most agents, hang-up "
    f"on, ask once after {NUDGE_AFTER_DEFAULT_S} s, "
    f"hang up after {END_AFTER_SILENCE_DEFAULT_S} s, standard lines, no sound, ask again "
    f"after {REASK_AFTER_DEFAULT_MS / 1000:g} s); `*_source` "
    "names the level in force.\n\n"
    "A change reaches a live agent straight after the save and applies from its next call; "
    "a call in progress finishes as it started. Out-of-range values are refused with "
    "`turn_silence_out_of_range` or `call_setting_out_of_range`."
)
_ORG_DESCRIPTION = (
    "The account defaults every agent without a value of its own follows. `null` follows "
    "Calevate's. `turn_silence_ms` and `end_call_on_finish` are always stated; any other "
    "setting left out of a PUT is kept. A change reaches every live agent that inherits it, "
    "from its next call."
)


@router.get(
    "/v1/agents/{agent_id}/call-handling",
    response_model=AgentCallHandlingOut,
    openapi_extra=permission_meta("agents:read"),
    summary="An agent's call settings, and where each comes from",
    description=_AGENT_DESCRIPTION,
)
async def get_agent_call_handling(
    agent_id: UUID, session: Session, _: AgentReader
) -> AgentCallHandlingOut:
    return await _agent_response(
        session, await call_handling.read_agent_call_handling(session, agent_id)
    )


@router.patch(
    "/v1/agents/{agent_id}/call-handling",
    response_model=AgentCallHandlingOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Set an agent's call settings, or let them inherit",
    description=_AGENT_DESCRIPTION,
)
async def set_agent_call_handling(
    agent_id: UUID,
    payload: AgentCallHandlingIn,
    session: Session,
    request: Request,
    principal: Owner,
) -> AgentCallHandlingOut:
    assert principal.tenant_id is not None  # client realm; `requires()` resolves it
    changes = _changes(payload)
    state, moved = await call_handling.set_agent_call_handling(
        session, tenant_id=principal.tenant_id, agent_id=agent_id, changes=changes
    )
    await write_audit(
        session,
        action="agent.call_handling_set",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
        summary=_audit_summary(changes, moved),
    )
    return await _agent_response(session, state)


_PATIENT_DESCRIPTION = (
    "One tap for a caller who follows the agent along on their own phone and goes quiet for "
    "long stretches: on this agent alone, ask whether they are still there after "
    f"{patient_caller.NUDGE_AFTER_S} s, up to {patient_caller.NUDGE_COUNT} times, in the "
    "agent's main language (`patient_caller.nudge_phrase` on the read), hang up after "
    f"{patient_caller.END_AFTER_SILENCE_S} s of silence, never repeat an unanswered question on "
    "a timer, and raise the longest call to `patient_caller.call_cap_s` (a longer one is "
    "kept). Each is an ordinary setting afterwards. Applies from the next call."
)


async def _apply_patient_caller(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    request: Request,
    principal: Principal,
    action: str,
) -> AgentCallHandlingOut:
    result = await patient_caller.apply_patient_caller(
        session, tenant_id=tenant_id, agent_id=agent_id
    )
    await write_audit(
        session,
        action=action,
        actor=principal,
        tenant_id=tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
        summary={
            "changed": list(result.moved),
            "cap_before_s": result.call_cap_before_s,
            "cap_after_s": result.call_cap_after_s,
        },
    )
    return await _agent_response(session, result.state)


@router.post(
    "/v1/agents/{agent_id}/call-handling/patient-caller",
    response_model=AgentCallHandlingOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Set an agent up for a caller who follows along on their phone",
    description=_PATIENT_DESCRIPTION,
)
async def apply_patient_caller(
    agent_id: UUID, session: Session, request: Request, principal: Owner
) -> AgentCallHandlingOut:
    assert principal.tenant_id is not None  # client realm; `requires()` resolves it
    return await _apply_patient_caller(
        session,
        tenant_id=principal.tenant_id,
        agent_id=agent_id,
        request=request,
        principal=principal,
        action="agent.patient_caller_applied",
    )


@router.get(
    "/v1/organization/call-handling",
    response_model=OrganizationCallHandlingOut,
    openapi_extra=permission_meta("org:read"),
    summary="This account's default call settings",
    description=_ORG_DESCRIPTION,
)
async def get_organization_call_handling(
    session: Session, _: OrgReader
) -> OrganizationCallHandlingOut:
    return _org_out(await call_handling.read_organization_call_handling(session))


@router.put(
    "/v1/organization/call-handling",
    response_model=OrganizationCallHandlingOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Set this account's default call settings",
    description=_ORG_DESCRIPTION,
)
async def set_organization_call_handling(
    payload: OrganizationCallHandlingIn,
    session: Session,
    request: Request,
    principal: Owner,
) -> OrganizationCallHandlingOut:
    assert principal.tenant_id is not None
    changes = _org_changes(payload)
    state, moved = await call_handling.set_organization_call_handling(
        session, tenant_id=principal.tenant_id, changes=changes
    )
    await write_audit(
        session,
        action="organization.call_handling_set",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="organization",
        object_id=str(principal.tenant_id),
        ip=client_request_ip(request),
        summary=_audit_summary(changes, moved),
    )
    return _org_out(state)


@router.post(
    "/v1/organization/call-handling/all-agents",
    response_model=AllAgentsCallHandlingOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Use call settings on every agent of this account",
    description=(
        "Each named setting becomes the account default (`null` follows Calevate's) and every "
        "agent's own value for it is dropped, so all agents, and any made later, use it. "
        "Settings left out are untouched. `agents_reset` counts the agents that had a value "
        "of their own. A change reaches every live agent it moves, from its next call."
    ),
)
async def set_call_handling_for_all_agents(
    payload: AllAgentsCallHandlingIn,
    session: Session,
    request: Request,
    principal: Owner,
) -> AllAgentsCallHandlingOut:
    assert principal.tenant_id is not None
    changes = _changes(payload)
    result = await call_handling.set_call_handling_for_all_agents(
        session, tenant_id=principal.tenant_id, changes=changes
    )
    await write_audit(
        session,
        action="organization.call_handling_set_for_all_agents",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="organization",
        object_id=str(principal.tenant_id),
        ip=client_request_ip(request),
        summary={
            **_audit_summary(changes, result.moved),
            "agents_reset": result.agents_reset,
        },
    )
    return AllAgentsCallHandlingOut(
        organization=_org_out(result.organization), agents_reset=result.agents_reset
    )


@admin_router.get(
    "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/call-handling",
    response_model=AgentCallHandlingOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="One client agent's call settings",
    description=_AGENT_DESCRIPTION,
)
async def admin_get_agent_call_handling(
    tenant_id: UUID, agent_id: UUID, request: Request, principal: Operator
) -> AgentCallHandlingOut:
    async with tenant_session(tenant_id) as scoped:
        state = await call_handling.read_agent_call_handling(scoped, agent_id)
        out = await _agent_response(scoped, state)
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=tenant_id
        )
    return out


@admin_router.patch(
    "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/call-handling",
    response_model=AgentCallHandlingOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Set one client agent's call settings",
    description=_AGENT_DESCRIPTION,
)
async def admin_set_agent_call_handling(
    tenant_id: UUID,
    agent_id: UUID,
    payload: AgentCallHandlingIn,
    request: Request,
    principal: AgentOperator,
) -> AgentCallHandlingOut:
    changes = _changes(payload)
    async with tenant_session(tenant_id) as scoped:
        state, moved = await call_handling.set_agent_call_handling(
            scoped, tenant_id=tenant_id, agent_id=agent_id, changes=changes
        )
        await write_audit(
            scoped,
            action="admin.agent_call_handling_set",
            actor=principal,
            tenant_id=tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            ip=client_request_ip(request),
            summary=_audit_summary(changes, moved),
        )
        out = await _agent_response(scoped, state)
    return out


@admin_router.post(
    "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/call-handling/patient-caller",
    response_model=AgentCallHandlingOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Set one client agent up for a caller who follows along on their phone",
    description=_PATIENT_DESCRIPTION,
)
async def admin_apply_patient_caller(
    tenant_id: UUID, agent_id: UUID, request: Request, principal: AgentOperator
) -> AgentCallHandlingOut:
    async with tenant_session(tenant_id) as scoped:
        out = await _apply_patient_caller(
            scoped,
            tenant_id=tenant_id,
            agent_id=agent_id,
            request=request,
            principal=principal,
            action="admin.agent_patient_caller_applied",
        )
    return out


@admin_router.get(
    "/v1/admin/organizations/{org_id}/call-handling",
    response_model=OrganizationCallHandlingOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="One client's default call settings",
    description=_ORG_DESCRIPTION,
)
async def admin_get_organization_call_handling(
    org_id: UUID, request: Request, principal: Operator
) -> OrganizationCallHandlingOut:
    async with tenant_session(org_id) as scoped:
        state = await call_handling.read_organization_call_handling(scoped)
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=org_id
        )
    return _org_out(state)


@admin_router.put(
    "/v1/admin/organizations/{org_id}/call-handling",
    response_model=OrganizationCallHandlingOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Set one client's default call settings",
    description=_ORG_DESCRIPTION,
)
async def admin_set_organization_call_handling(
    org_id: UUID,
    payload: OrganizationCallHandlingIn,
    request: Request,
    principal: Operator,
) -> OrganizationCallHandlingOut:
    changes = _org_changes(payload)
    async with tenant_session(org_id) as scoped:
        state, moved = await call_handling.set_organization_call_handling(
            scoped, tenant_id=org_id, changes=changes
        )
        await write_audit(
            scoped,
            action="admin.organization_call_handling_set",
            actor=principal,
            tenant_id=org_id,
            object_type="organization",
            object_id=str(org_id),
            ip=client_request_ip(request),
            summary=_audit_summary(changes, moved),
        )
    return _org_out(state)


class AgentTurnDetectionOut(BaseModel):
    """An agent's own turn detection (`null` follows the console's for every agent) and the
    mode its calls use."""

    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    turn_detection: TurnDetection | None
    turn_detection_effective: TurnDetection
    #: The console's `thinnest_turn_detection`, which `null` follows.
    console_turn_detection: TurnDetection
    #: The pause this agent's calls are sent, and the level that chose it. On an agent put
    #: on `timer` here with no pause of its own or its account's it is the console's
    #: `thinnest_timer_turn_silence_ms` (D-903).
    turn_silence_ms_effective: int
    turn_silence_source: SettingSource
    #: False under `ear`, where the pause is sent but not used.
    turn_silence_applies: bool


class AgentTurnDetectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_detection: TurnDetection | None


def _turn_out(handling: AgentCallHandling) -> AgentTurnDetectionOut:
    pause = handling.turn_silence
    return AgentTurnDetectionOut(
        agent_id=handling.agent_id,
        turn_detection=handling.turn_detection,
        turn_detection_effective=handling.turn_detection_effective,
        console_turn_detection=get_settings().thinnest_turn_detection,
        turn_silence_ms_effective=pause.ms,
        turn_silence_source=pause.source,
        turn_silence_applies=handling.turn_silence_applies,
    )


_TURN_DESCRIPTION = (
    "How this one agent decides the caller has finished: `timer`, `ear` or `smart`, or "
    "`null` to follow the console's mode for every agent. For trying a mode on one agent "
    "(D-901); operators only, never a client's setting. A change reaches a live agent "
    "straight after the save and applies from its next call."
)


@admin_router.get(
    "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/turn-detection",
    response_model=AgentTurnDetectionOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="One client agent's own turn detection",
    description=_TURN_DESCRIPTION,
)
async def admin_get_agent_turn_detection(
    tenant_id: UUID, agent_id: UUID, request: Request, principal: Operator
) -> AgentTurnDetectionOut:
    async with tenant_session(tenant_id) as scoped:
        state = await call_handling.read_agent_call_handling(scoped, agent_id)
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=tenant_id
        )
    return _turn_out(state)


@admin_router.put(
    "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/turn-detection",
    response_model=AgentTurnDetectionOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Put one client agent on its own turn detection",
    description=_TURN_DESCRIPTION,
)
async def admin_set_agent_turn_detection(
    tenant_id: UUID,
    agent_id: UUID,
    payload: AgentTurnDetectionIn,
    request: Request,
    principal: AgentOperator,
) -> AgentTurnDetectionOut:
    async with tenant_session(tenant_id) as scoped:
        state, moved = await call_handling.set_agent_turn_detection(
            scoped, tenant_id=tenant_id, agent_id=agent_id, mode=payload.turn_detection
        )
        await write_audit(
            scoped,
            action="admin.agent_turn_detection_set",
            actor=principal,
            tenant_id=tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            ip=client_request_ip(request),
            summary={"turn_detection": payload.turn_detection, "moved": moved},
        )
    return _turn_out(state)


__all__ = [
    "AgentCallHandlingIn",
    "AgentCallHandlingOut",
    "AgentTurnDetectionIn",
    "AgentTurnDetectionOut",
    "AllAgentsCallHandlingIn",
    "AllAgentsCallHandlingOut",
    "OrganizationCallHandlingIn",
    "OrganizationCallHandlingOut",
    "PatientCallerOut",
    "admin_router",
    "router",
]
