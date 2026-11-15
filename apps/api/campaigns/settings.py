"""A campaign's own settings on top of its agent's defaults (D-994, founder 15 Nov 2026: "The
agent will ... only hold basics default settings such as speed, language etc. Those defaults
should be editable and overridable here in the campaign as well").

The agent keeps its defaults (its own columns, unchanged by any campaign). A campaign stores
only the keys it overrides (`campaigns.settings_overrides`). The overrides of the campaign that
most recently put its script on the agent (`campaigns.agent_held_at`, set by Start, Schedule
and Test call) are laid over the agent's row wherever an engine config is built
(`agents.service._load_agent`), so a publish, the settings drift sweep and a dial all agree,
and the next campaign on that agent brings its own.

Why at publish rather than per call: the platform takes only voice, language, call length and
call instructions per call (place-call.md `overrides`, 6 Oct 2026 mirror); speed and the
silence handling are agent settings. A voice speaks one campaign at a time already (D-992).

The voice itself is NOT overridable here: a voice decides the rung a call is billed at and,
for Studio, the workspace key it needs, which the agent's own voice change handles.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal, InvalidOperation
from typing import Any, Final
from uuid import UUID

from calevate_shared.languages import LANGUAGES
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.call_handling import CallSettings, refuse_invalid_settings, settings_of
from apps.api.agents.languages import MAX_REPLY_LANGUAGES, client_language_tags
from apps.api.agents.models import CALL_CAP_MAX_S, CALL_CAP_MIN_S
from apps.api.agents.voice_tuning import SPEED_MAX, SPEED_MIN
from apps.api.core.errors import ProblemError

#: The call-handling settings a campaign may set, a subset of the agent's `SETTING_FIELDS`.
CALL_SETTING_KEYS: Final = (
    "nudge_after_seconds",
    "end_after_silence_seconds",
    "filler_lines",
    "ambience",
    "ambience_volume_pct",
    "reask_after_ms",
)
OVERRIDE_KEYS: Final = (
    "language_primary",
    "languages_extra",
    "speaking_speed",
    "max_call_duration_s",
    *CALL_SETTING_KEYS,
)


def _invalid(detail: str) -> ProblemError:
    return ProblemError(
        kind="validation",
        code="campaign_setting_invalid",
        title="Check this setting",
        detail=detail,
    )


def clean_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    """The overrides as stored: only known keys, null meaning "use the agent's", each value
    held to the same limits the agent's own setting is held to."""
    unknown = sorted(set(raw) - set(OVERRIDE_KEYS))
    if unknown:
        raise _invalid(f"These cannot be set on a campaign: {', '.join(unknown)}.")
    out: dict[str, Any] = {}
    language = raw.get("language_primary")
    if language is not None:
        if str(language) not in LANGUAGES:
            raise _invalid("Choose one of the languages offered.")
        out["language_primary"] = str(language)
    extra = raw.get("languages_extra")
    if extra is not None:
        tags = [str(tag) for tag in extra]
        allowed = client_language_tags()
        if any(tag not in allowed for tag in tags):
            raise _invalid("Choose only the languages offered.")
        if len(set(tags)) != len(tags):
            raise _invalid("Each language can be chosen only once.")
        if out.get("language_primary") in tags:
            raise _invalid("The main language is already spoken; pick the others.")
        if len(tags) > MAX_REPLY_LANGUAGES - 1:
            raise _invalid(f"An agent speaks at most {MAX_REPLY_LANGUAGES} languages.")
        out["languages_extra"] = tags
    speed = raw.get("speaking_speed")
    if speed is not None:
        try:
            value = Decimal(str(speed))
        except InvalidOperation as exc:
            raise _invalid("Speaking speed must be a number.") from exc
        if not SPEED_MIN <= value <= SPEED_MAX:
            raise _invalid(f"Speaking speed must be between {SPEED_MIN} and {SPEED_MAX}.")
        out["speaking_speed"] = str(value)
    cap = raw.get("max_call_duration_s")
    if cap is not None:
        seconds = int(cap)
        if not CALL_CAP_MIN_S <= seconds <= CALL_CAP_MAX_S:
            raise _invalid(
                f"The longest call must be between {CALL_CAP_MIN_S // 60} and "
                f"{CALL_CAP_MAX_S // 60} minutes."
            )
        out["max_call_duration_s"] = seconds
    call = {k: raw[k] for k in CALL_SETTING_KEYS if raw.get(k) is not None}
    if call:
        values = settings_of(call)
        refuse_invalid_settings(values)
        out.update({k: v for k, v in dataclasses.asdict(values).items() if k in call})
        if "filler_lines" in out:
            out["filler_lines"] = list(out["filler_lines"])
    return out


def apply_overrides(agent: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
    """The agent row as an `AgentConfig` is built from, with a campaign's overrides laid on.
    Pure: the agent's stored defaults are never written."""
    if not overrides:
        return agent
    row = dict(agent)
    if "language_primary" in overrides:
        row["language_primary"] = overrides["language_primary"]
    if "languages_extra" in overrides:
        row["languages_extra"] = list(overrides["languages_extra"])
    if "max_call_duration_s" in overrides:
        row["max_call_duration_s"] = overrides["max_call_duration_s"]
    if "speaking_speed" in overrides:
        tuning = tuple(row.get("voice_tuning") or (None,) * 5)
        row["voice_tuning"] = (Decimal(str(overrides["speaking_speed"])), *tuning[1:])
    call = {k: overrides[k] for k in CALL_SETTING_KEYS if k in overrides}
    if call:
        own: CallSettings = row.get("call_settings") or CallSettings()
        if "filler_lines" in call:
            call["filler_lines"] = tuple(call["filler_lines"])
        row["call_settings"] = dataclasses.replace(own, **call)
    row["campaign_overrides"] = overrides
    return row


async def held_overrides(session: AsyncSession, agent_id: UUID) -> dict[str, Any] | None:
    """The overrides of the campaign that most recently put its script on this agent."""
    return (
        await session.execute(
            text(
                "SELECT settings_overrides FROM campaigns WHERE agent_id = :a "
                "AND archived_at IS NULL AND agent_held_at IS NOT NULL "
                "ORDER BY agent_held_at DESC LIMIT 1"
            ),
            {"a": agent_id},
        )
    ).scalar_one_or_none()


__all__ = [
    "CALL_SETTING_KEYS",
    "OVERRIDE_KEYS",
    "apply_overrides",
    "clean_overrides",
    "held_overrides",
]
