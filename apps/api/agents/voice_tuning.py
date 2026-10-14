"""How a Studio voice sounds on one agent: speed, volume, emotion, the voice model and a
pronunciation dictionary (operators only, founder decision 13 Oct 2026).

A Studio agent speaks a voice of our own Cartesia key through ThinnestAI, and each agent can
carry its own settings for that voice (`PUT /agents/{id}/byok-voice`, snapshots/2026-10-13/
pages/api-reference/bring-your-own-keys.md:362-407, agents/set-agent-byok-voice.md:425-440,
:587-627). They are stored on the agent, refused here as the platform refuses them, sent on
every publish of a Studio agent (`engine/thinnest.ThinnestEngine._apply_own_key_voice`), read
back by the settings sweep (`voice_tuning`), and reach a live agent through the live apply
(D-720) in the saving transaction.

What the platform refuses, refused first here with our own codes:

* a value outside its range (speed 0.6-1.5, volume 0.5-2.0), an emotion or model it does not
  list, a dictionary id of the wrong shape;
* speed, volume or emotion with the agent's own model `sonic-2` (they need Sonic 3);
* any setting on an agent whose voice is not a Studio one (the settings belong to a voice of
  our own key, and the platform refuses them before one is chosen).

Speed on a Professional Voice Clone is refused by the platform alone, at publish or preview:
`GET /byok/voices` does not say which voices are such clones (list-byok-voices.md), so we
cannot know beforehand. The adapter turns that refusal into `voice_speed_not_for_this_voice`.

The emotion list is the eight the docs name as examples ("such as", bring-your-own-keys.md:
384); Cartesia may accept more, and a value outside these is refused rather than guessed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import Final
from uuid import UUID

from calevate_shared.engine import ByokVoiceTuning
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.hosted_voices import parse_hosted_voice_id
from apps.api.agents.live_apply import queue_live_apply
from apps.api.agents.models import (
    STUDIO_VOICE_DICTIONARY_ID_PATTERN,
    STUDIO_VOICE_EMOTIONS,
    STUDIO_VOICE_MODELS,
    STUDIO_VOICE_OLD_MODEL,
    STUDIO_VOICE_SPEED_MAX,
    STUDIO_VOICE_SPEED_MIN,
    STUDIO_VOICE_VOLUME_MAX,
    STUDIO_VOICE_VOLUME_MIN,
)
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

SPEED_MIN: Final = STUDIO_VOICE_SPEED_MIN
SPEED_MAX: Final = STUDIO_VOICE_SPEED_MAX
VOLUME_MIN: Final = STUDIO_VOICE_VOLUME_MIN
VOLUME_MAX: Final = STUDIO_VOICE_VOLUME_MAX
EMOTIONS: Final = STUDIO_VOICE_EMOTIONS
VOICE_MODELS: Final = STUDIO_VOICE_MODELS
OLD_VOICE_MODEL: Final = STUDIO_VOICE_OLD_MODEL
DICTIONARY_ID_PATTERN: Final = STUDIO_VOICE_DICTIONARY_ID_PATTERN
_DICTIONARY_ID: Final = re.compile(DICTIONARY_ID_PATTERN)
#: Speed and volume are set in hundredths, the precision of their NUMERIC(3,2) columns.
_HUNDREDTH: Final = Decimal("0.01")

#: The writable fields, in the order the columns are read.
FIELDS: Final[tuple[str, ...]] = ("speed", "volume", "emotion", "model", "dictionary_id")
#: The fields the old model refuses.
_NEEDS_NEWER_MODEL: Final = ("speed", "volume", "emotion")

TUNING_COLUMNS: Final = (
    "a.studio_voice_speed, a.studio_voice_volume, a.studio_voice_emotion, "
    "a.studio_voice_model, a.studio_voice_dictionary_id"
)
_READ_SQL: Final = (
    f"SELECT {TUNING_COLUMNS}, a.engine_voice_id, a.status, a.engine_agent_ref "
    "FROM agents a WHERE a.id = :aid AND a.deleted_at IS NULL"
)
_UPDATE_SQL: Final = (
    "UPDATE agents SET studio_voice_speed = :speed, studio_voice_volume = :volume, "
    "studio_voice_emotion = :emotion, studio_voice_model = :model, "
    "studio_voice_dictionary_id = :dictionary_id, updated_at = now() WHERE id = :aid"
)


@dataclass(frozen=True, slots=True)
class VoiceTuningState:
    agent_id: UUID
    tuning: ByokVoiceTuning
    #: The agent's configured voice is a Studio one, so the settings apply.
    studio: bool
    #: Our catalogue id of the configured voice, for a preview.
    voice_id: str | None


def tuning_from_row(row: Sequence[object]) -> ByokVoiceTuning:
    """The five tuning columns, in `TUNING_COLUMNS` order."""
    speed, volume, emotion, model, dictionary_id = row[:5]
    return ByokVoiceTuning(
        speed=_decimal(speed),
        volume=_decimal(volume),
        emotion=str(emotion) if emotion is not None else None,
        model=str(model) if model is not None else None,
        dictionary_id=str(dictionary_id) if dictionary_id is not None else None,
    )


def _decimal(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def is_studio_voice(engine_voice_id: object) -> bool:
    ref = parse_hosted_voice_id(engine_voice_id if isinstance(engine_voice_id, str) else None)
    return ref is not None and ref.source == "byok"


def _refuse(code: str, title: str, detail: str, remediation: str) -> ProblemError:
    return ProblemError(
        kind="business_rule",
        code=code,
        title=title,
        detail=detail,
        remediation=remediation,
    )


def _within(value: Decimal | None, low: Decimal, high: Decimal) -> bool:
    return value is None or (low <= value <= high and value % _HUNDREDTH == 0)


def refuse_invalid_tuning(tuning: ByokVoiceTuning) -> None:
    """Refuse what the platform would refuse, in words an operator can act on."""
    if not _within(tuning.speed, SPEED_MIN, SPEED_MAX):
        raise _refuse(
            "voice_speed_out_of_range",
            "This speed is out of range",
            f"The voice's speed must be between {SPEED_MIN} and {SPEED_MAX}, in hundredths; "
            "1 is the voice's own pace.",
            "Choose a speed in that range, or clear it.",
        )
    if not _within(tuning.volume, VOLUME_MIN, VOLUME_MAX):
        raise _refuse(
            "voice_volume_out_of_range",
            "This volume is out of range",
            f"The voice's volume must be between {VOLUME_MIN} and {VOLUME_MAX}, in hundredths; "
            "1 is the voice's own loudness.",
            "Choose a volume in that range, or clear it.",
        )
    if tuning.emotion is not None and tuning.emotion not in EMOTIONS:
        raise _refuse(
            "voice_emotion_unknown",
            "This emotion is not offered",
            f"The emotion must be one of: {', '.join(EMOTIONS)}.",
            "Choose one of those, or clear it to let the words decide.",
        )
    if tuning.model is not None and tuning.model not in VOICE_MODELS:
        raise _refuse(
            "voice_model_unknown",
            "This voice model is not offered",
            f"The voice model must be one of: {', '.join(VOICE_MODELS)}.",
            "Choose one of those, or clear it to use the key's own model.",
        )
    if tuning.dictionary_id is not None and not _DICTIONARY_ID.fullmatch(tuning.dictionary_id):
        raise _refuse(
            "voice_dictionary_id_invalid",
            "This pronunciation dictionary id is not valid",
            "A pronunciation dictionary id is 3 to 80 letters, digits, '-' or '_', starting "
            "with a letter or digit, as the voice provider's account shows it.",
            "Copy the id again from the voice provider's account, or clear it.",
        )
    if tuning.model == OLD_VOICE_MODEL:
        set_fields = [f for f in _NEEDS_NEWER_MODEL if getattr(tuning, f) is not None]
        if set_fields:
            raise _refuse(
                "voice_tuning_needs_newer_model",
                "This voice model takes no speed, volume or emotion",
                f"The older voice model {OLD_VOICE_MODEL} ignores speed, volume and emotion, "
                f"and the voice platform refuses them with it ({', '.join(set_fields)} set).",
                "Clear those settings, or choose a newer voice model.",
            )


def tuning_of(values: Mapping[str, object]) -> ByokVoiceTuning:
    """A `ByokVoiceTuning` from request values; a number that is not one is refused."""
    out: dict[str, object] = {}
    for name in FIELDS:
        value = values.get(name)
        if name in ("speed", "volume") and value is not None:
            try:
                value = Decimal(str(value))
            except InvalidOperation as exc:
                raise _refuse(
                    f"voice_{name}_out_of_range",
                    f"This {name} is not a number",
                    f"The voice's {name} must be a number.",
                    "Enter a number, or clear it.",
                ) from exc
        elif isinstance(value, str):
            value = value.strip() or None
        out[name] = value
    return ByokVoiceTuning.model_validate(out)


def config_tuning(row: Sequence[object], *, byok_voice_id: str | None) -> ByokVoiceTuning | None:
    """The tuning a publish sends: only with a voice of our own key, and None when nothing
    is set, so an agent nobody tuned publishes exactly as before."""
    if not byok_voice_id:
        return None
    tuning = tuning_from_row(row)
    return None if tuning.is_empty else tuning


async def read_voice_tuning(session: AsyncSession, agent_id: UUID) -> VoiceTuningState:
    row = (await session.execute(text(_READ_SQL), {"aid": agent_id})).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    voice_id = row[5]
    return VoiceTuningState(
        agent_id=agent_id,
        tuning=tuning_from_row(tuple(row)),
        studio=is_studio_voice(voice_id),
        voice_id=str(voice_id) if voice_id else None,
    )


def _refuse_on_a_voice_not_studio(state: VoiceTuningState, wanted: ByokVoiceTuning) -> None:
    if not state.studio and not wanted.is_empty:
        raise _refuse(
            "voice_tuning_needs_studio_voice",
            "These settings are for Studio voices",
            "Speed, volume, emotion, voice model and pronunciation dictionary apply to a "
            "Studio voice only, and this agent's voice is not one.",
            "Choose a Studio voice for the agent first, or clear the settings.",
        )


async def set_voice_tuning(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    changes: Mapping[str, object],
) -> tuple[VoiceTuningState, tuple[str, ...]]:
    """Write the named fields (None clears one; a field left out is kept) and queue the
    agent's live apply when it is live. The row is locked first, so the comparison and the
    write are one step and a repeat of the held values writes and queues nothing. Answers
    the new state and the fields that moved."""
    unknown = set(changes) - set(FIELDS)
    if unknown:
        raise ValueError(f"not a voice tuning field: {sorted(unknown)}")
    row = (await session.execute(text(_READ_SQL + " FOR UPDATE OF a"), {"aid": agent_id})).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    current = tuning_from_row(tuple(row))
    named = tuning_of(changes)
    wanted = replace_fields(current, {f: getattr(named, f) for f in FIELDS if f in changes})
    refuse_invalid_tuning(wanted)
    state = VoiceTuningState(
        agent_id=agent_id,
        tuning=current,
        studio=is_studio_voice(row[5]),
        voice_id=str(row[5]) if row[5] else None,
    )
    _refuse_on_a_voice_not_studio(state, wanted)
    moved = tuple(f for f in FIELDS if getattr(wanted, f) != getattr(current, f))
    if moved:
        await session.execute(
            text(_UPDATE_SQL), {**{f: getattr(wanted, f) for f in FIELDS}, "aid": agent_id}
        )
        status, ref = row[6], row[7]
        if str(status) == "live" and ref and state.studio:
            await queue_live_apply(
                session,
                scope="agent",
                tenant_id=tenant_id,
                agent_id=agent_id,
                reason="voice_tuning",
            )
    log.info("agent_voice_tuning_set", extra={"agent_id": str(agent_id), "changed": list(moved)})
    return replace(state, tuning=wanted), moved


def replace_fields(tuning: ByokVoiceTuning, values: Mapping[str, object]) -> ByokVoiceTuning:
    return tuning.model_copy(update=dict(values))


__all__ = [
    "DICTIONARY_ID_PATTERN",
    "EMOTIONS",
    "FIELDS",
    "OLD_VOICE_MODEL",
    "SPEED_MAX",
    "SPEED_MIN",
    "TUNING_COLUMNS",
    "VOICE_MODELS",
    "VOLUME_MAX",
    "VOLUME_MIN",
    "VoiceTuningState",
    "config_tuning",
    "is_studio_voice",
    "read_voice_tuning",
    "refuse_invalid_tuning",
    "set_voice_tuning",
    "tuning_from_row",
    "tuning_of",
]
