"""How an agent's voice sounds: its speed on any voice, and for a Studio voice also volume,
emotion, the voice model and a pronunciation dictionary.

Speed is the agent's own on both rungs (D-884), held in the one `studio_voice_speed` column:
on a Studio voice it is the byok-voice speed below (0.6-1.5, hundredths); on a Clear voice,
one ThinnestAI hosts, clones included, it is the agent's `voice.speakingSpeed` (0.7-1.3 in
steps of 0.05; docs.thinnest.ai/api-reference/agents/update-agent, read 25 Oct 2026). One
column rather than one per rung because it means the same on both ("a multiple of the
voice's own pace", 1 being that pace), so a person who made the agent a little faster keeps
it a little faster on a new voice; a voice change fits the value to the new rung's range
(`fit_speed`). Volume, emotion, model and dictionary stay Studio-only.

Who sets what (D-843, founder 21 Oct 2026, superseding the 13 Oct operators-only decision):
a client sets speed, loudness (volume) and emotion on its own Studio agents and hears them
on a capped sample (`voice_tuning_routes.router`); the voice model and the pronunciation
dictionary stay with operators (`voice_tuning_routes.admin_router`). One service serves both
doors, and the client route refuses the operator-only fields by its schema.

A Studio agent speaks a voice of our own Cartesia key through ThinnestAI, and each agent can
carry its own settings for that voice (`PUT /agents/{id}/byok-voice`, snapshots/2026-10-19/
pages/api-reference/agents/set-agent-byok-voice.md, bring-your-own-keys.md:380-425). They are
stored on the agent, refused here as the platform refuses them, sent on every publish of a
Studio agent (`engine/thinnest.ThinnestEngine._apply_own_key_voice`), read back by the
settings sweep (`voice_tuning`), and reach a live agent through the live apply (D-720) in the
saving transaction.

What the platform refuses, refused first here with our own codes:

* a value outside its range (speed 0.6-1.5, volume 0.5-2.0), an emotion or model it does not
  list, a dictionary id of the wrong shape;
* speed, volume or emotion with the agent's own model `sonic-2` (they need Sonic 3);
* any setting but speed on an agent whose voice is not a Studio one (the settings belong to
  a voice of our own key, and the platform refuses them before one is chosen);
* on a Clear voice, a speed outside 0.7-1.3 or off the 0.05 step.

Speed on a Professional Voice Clone is refused by the platform alone, at publish or preview:
`GET /byok/voices` does not say which voices are such clones (list-byok-voices.md), so we
cannot know beforehand. The adapter turns that refusal into `voice_speed_not_for_this_voice`.

The emotion list is the eight the docs name as examples ("such as", bring-your-own-keys.md:
400); Cartesia may accept more, and a value outside these is refused rather than guessed. The
Cartesia playground offers emotion for Telugu on Sonic 3.6 (founder, 21 Oct 2026), and the
written docs page still says English-only (:415). Emotion is offered on every Studio agent in
every language (D-843), and nothing here refuses it by language.

An agent whose voice becomes a Studio one with no emotion set starts on
`DEFAULT_STUDIO_EMOTION` (`lifecycle.update_agent`, the one writer of an agent's voice).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Final, Literal
from uuid import UUID

from calevate_shared.engine import ByokVoiceTuning
from calevate_shared.spoken_style import opening_in
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.hosted_voices import parse_hosted_voice_id
from apps.api.agents.live_apply import queue_live_apply
from apps.api.agents.models import (
    CLEAR_VOICE_SPEED_MAX,
    CLEAR_VOICE_SPEED_MIN,
    CLEAR_VOICE_SPEED_STEP,
    STUDIO_VOICE_DICTIONARY_ID_PATTERN,
    STUDIO_VOICE_EMOTIONS,
    STUDIO_VOICE_MODELS,
    STUDIO_VOICE_OLD_MODEL,
    STUDIO_VOICE_SPEED_MAX,
    STUDIO_VOICE_SPEED_MIN,
    STUDIO_VOICE_VOLUME_MAX,
    STUDIO_VOICE_VOLUME_MIN,
    is_published,
)
from apps.api.billing.plans import IST
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis

log = get_logger(__name__)

#: Who is asking: an operator reads the ground they can fix (the voice model by name); a
#: client reads the one action they have, with no provider or model named (D-679).
Audience = Literal["operator", "client"]

SPEED_MIN: Final = STUDIO_VOICE_SPEED_MIN
SPEED_MAX: Final = STUDIO_VOICE_SPEED_MAX
CLEAR_SPEED_MIN: Final = CLEAR_VOICE_SPEED_MIN
CLEAR_SPEED_MAX: Final = CLEAR_VOICE_SPEED_MAX
CLEAR_SPEED_STEP: Final = CLEAR_VOICE_SPEED_STEP
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
#: The fields a client sets (D-843); the model and dictionary stay with operators.
CLIENT_FIELDS: Final[tuple[str, ...]] = ("speed", "volume", "emotion")
#: The one field that applies on a Clear voice too (D-884).
ANY_VOICE_FIELDS: Final[tuple[str, ...]] = ("speed",)
#: The emotion an agent starts on when its voice becomes a Studio one with none set
#: (founder decision 21 Oct 2026, D-843). Never written over an emotion a person set.
DEFAULT_STUDIO_EMOTION: Final = "calm"
#: Samples a client account may hear per IST day (D-843). Each is spoken on our voice key and
#: charged to us per character, so the cap bounds what we absorb.
CLIENT_PREVIEWS_PER_DAY: Final = 20
#: The counter outlives its IST day by an hour, so no key is immortal and none expires early.
_PREVIEW_COUNTER_TTL_S: Final = 25 * 3600
_PREVIEW_COUNTER_PREFIX: Final = "calevate:voice-preview"
#: The engine caps a spoken preview line (the adapter refuses longer).
PREVIEW_TEXT_MAX_CHARS: Final = 200
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


def _within(value: Decimal | None, low: Decimal, high: Decimal, step: Decimal = _HUNDREDTH) -> bool:
    return value is None or (low <= value <= high and value % step == 0)


def speed_range(*, studio: bool) -> tuple[Decimal, Decimal, Decimal]:
    """`(min, max, step)` of the speed on a Studio or a Clear voice."""
    if studio:
        return SPEED_MIN, SPEED_MAX, _HUNDREDTH
    return CLEAR_SPEED_MIN, CLEAR_SPEED_MAX, CLEAR_SPEED_STEP


def fit_speed(speed: Decimal | None, *, studio: bool) -> Decimal | None:
    """`speed` moved to the nearest value the rung takes: clamped to its range and rounded
    to its step. A voice change uses it, so a Studio agent at 1.45 becomes a Clear one at
    1.3 rather than a publish the platform refuses."""
    if speed is None:
        return None
    low, high, step = speed_range(studio=studio)
    snapped = (min(max(speed, low), high) / step).quantize(
        Decimal(1), rounding=ROUND_HALF_UP
    ) * step
    return snapped.quantize(_HUNDREDTH, rounding=ROUND_HALF_UP)


def refuse_invalid_tuning(
    tuning: ByokVoiceTuning, *, audience: Audience = "operator", studio: bool = True
) -> None:
    """Refuse what the platform would refuse, in words the reader can act on. `studio` is
    the rung of the agent's voice, which decides the speed's range."""
    low, high, step = speed_range(studio=studio)
    if not _within(tuning.speed, low, high, step):
        unit = "in hundredths" if studio else f"in steps of {step}"
        raise _refuse(
            "voice_speed_out_of_range",
            "This speed is out of range",
            f"The voice's speed must be between {low} and {high}, {unit}; "
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
        if set_fields and audience == "client":
            raise _refuse(
                "voice_tuning_needs_newer_model",
                "This voice takes no speed, loudness or emotion",
                "This agent's voice is set up in a way that does not take speed, loudness or "
                "emotion settings.",
                "Clear those settings, or contact us to change how the voice is set up.",
            )
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


def config_speaking_speed(row: Sequence[object], *, byok_voice_id: str | None) -> Decimal | None:
    """The speed a publish sends as the agent's own (`voice.speakingSpeed`): the agent's
    speed on a Clear voice, None on a Studio one, whose speed travels with the byok-voice
    settings and is used instead (update-agent, read 25 Oct 2026). Fitted to the Clear range
    for a row a voice change before D-884 left on a Studio value."""
    if byok_voice_id:
        return None
    return fit_speed(tuning_from_row(row).speed, studio=False)


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


def refuse_on_a_voice_not_studio(
    state: VoiceTuningState, setting: Sequence[str], *, audience: Audience = "operator"
) -> None:
    """Refuse `setting`, the Studio-only fields a write gives a value, on a Clear voice.
    Clearing one is allowed: it leaves nothing the voice could not take."""
    if state.studio or not setting:
        return
    if audience == "client":
        raise _refuse(
            "voice_tuning_needs_studio_voice",
            "Loudness and emotion are for Studio voices",
            "Loudness and emotion apply to a Studio voice only, and this agent's voice is not "
            "one. Speed can be set on any voice.",
            "Change only the speed, or choose a Studio voice for the agent first.",
        )
    raise _refuse(
        "voice_tuning_needs_studio_voice",
        "These settings are for Studio voices",
        "Volume, emotion, voice model and pronunciation dictionary apply to a Studio voice "
        "only, and this agent's voice is not one. Speed applies to any voice.",
        "Choose a Studio voice for the agent first, or set only the speed.",
    )


async def set_voice_tuning(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    changes: Mapping[str, object],
    audience: Audience = "operator",
) -> tuple[VoiceTuningState, tuple[str, ...]]:
    """Write the named fields (None clears one; a field left out is kept) and queue the
    agent's live apply when the engine holds it (live or ready). The row is locked first, so
    the comparison and the write are one step and a repeat of the held values writes and
    queues nothing. Answers the new state and the fields that moved. A client may name only
    `CLIENT_FIELDS`."""
    unknown = set(changes) - set(FIELDS if audience == "operator" else CLIENT_FIELDS)
    if unknown:
        raise ValueError(f"not a voice tuning field: {sorted(unknown)}")
    row = (await session.execute(text(_READ_SQL + " FOR UPDATE OF a"), {"aid": agent_id})).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    current = tuning_from_row(tuple(row))
    named = tuning_of(changes)
    wanted = replace_fields(current, {f: getattr(named, f) for f in FIELDS if f in changes})
    state = VoiceTuningState(
        agent_id=agent_id,
        tuning=current,
        studio=is_studio_voice(row[5]),
        voice_id=str(row[5]) if row[5] else None,
    )
    moved = tuple(f for f in FIELDS if getattr(wanted, f) != getattr(current, f))
    # A Clear agent may still hold Studio settings from an earlier voice: they are kept and
    # never sent, so only the speed is judged there, beside a held older voice model, whose
    # column CHECK refuses any speed (an operator clears that model first).
    refuse_invalid_tuning(
        wanted if state.studio else ByokVoiceTuning(speed=wanted.speed, model=wanted.model),
        audience=audience,
        studio=state.studio,
    )
    refuse_on_a_voice_not_studio(
        state,
        [f for f in moved if f not in ANY_VOICE_FIELDS and getattr(wanted, f) is not None],
        audience=audience,
    )
    if moved:
        await session.execute(
            text(_UPDATE_SQL), {**{f: getattr(wanted, f) for f in FIELDS}, "aid": agent_id}
        )
        status, ref = row[6], row[7]
        if is_published(status, ref) and (state.studio or "speed" in moved):
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


def sample_line(*, language: str | None, direction: str, business: str) -> str | None:
    """The fixed line a client's sample speaks: the starter greeting in the agent's main
    language, with the account's own name (`spoken_style.opening_in`). Never caller data.
    None where the table has no greeting for the language or the line would be too long;
    the engine then speaks its own short greeting in that language
    (snapshots/2026-10-19/pages/api-reference/bring-your-own-keys/preview-byok-voice.md:7)."""
    template = opening_in(language, "outbound" if direction == "outbound" else "inbound")
    if template is None:
        return None
    line = template.replace("{business}", business).strip()
    return line if line and len(line) <= PREVIEW_TEXT_MAX_CHARS else None


def _preview_key(tenant_id: UUID, now: datetime | None) -> str:
    day = (now or datetime.now(UTC)).astimezone(IST).date()
    return f"{_PREVIEW_COUNTER_PREFIX}:{tenant_id}:{day.isoformat()}"


async def client_previews_left(tenant_id: UUID, *, now: datetime | None = None) -> int | None:
    """Samples the account may still hear today (IST), or None when the counter is
    unreadable (the take then refuses, so the screen says nothing it cannot back)."""
    try:
        raw = await get_redis().get(_preview_key(tenant_id, now))
    except Exception as exc:
        log.warning("voice_preview_counter_unreadable", extra={"error": type(exc).__name__})
        return None
    return max(0, CLIENT_PREVIEWS_PER_DAY - int(raw or 0))


async def take_client_preview(tenant_id: UUID, *, now: datetime | None = None) -> None:
    """Count one sample against the account's IST day and refuse past the cap.

    INCR and EXPIRE NX in one round trip, `core/ratelimit.consume`'s shape, so no failure
    between them can leave a counter with no expiry. It fails CLOSED, unlike request limiting:
    each sample is spoken on our key at our cost, and an unreadable counter is no bound."""
    key = _preview_key(tenant_id, now)
    try:
        pipe = get_redis().pipeline()
        pipe.incr(key)
        pipe.expire(key, _PREVIEW_COUNTER_TTL_S, nx=True)
        count = int((await pipe.execute())[0])
    except Exception as exc:
        log.warning("voice_preview_counter_unreadable", extra={"error": type(exc).__name__})
        raise ProblemError(
            kind="transient",
            code="voice_preview_unavailable",
            title="Samples cannot be played right now",
            detail="We could not play a sample just now.",
            remediation="Try again in a few minutes.",
            status=503,
            headers={"Retry-After": "60"},
        ) from exc
    if count > CLIENT_PREVIEWS_PER_DAY:
        raise ProblemError(
            kind="business_rule",
            code="voice_preview_daily_cap",
            title=f"You have heard {CLIENT_PREVIEWS_PER_DAY} samples today",
            detail=f"Each account can hear {CLIENT_PREVIEWS_PER_DAY} samples a day. Your saved "
            "settings still apply to calls.",
            remediation="Try again tomorrow.",
            status=429,
        )


async def refund_client_preview(tenant_id: UUID, *, now: datetime | None = None) -> None:
    """Give back a sample the engine did not speak, so a refusal (a voice that keeps its own
    pace) does not use up the day. Best effort: a failed refund only costs the account one."""
    try:
        await get_redis().decr(_preview_key(tenant_id, now))
    except Exception as exc:
        log.warning("voice_preview_refund_failed", extra={"error": type(exc).__name__})


__all__ = [
    "ANY_VOICE_FIELDS",
    "CLEAR_SPEED_MAX",
    "CLEAR_SPEED_MIN",
    "CLEAR_SPEED_STEP",
    "CLIENT_FIELDS",
    "CLIENT_PREVIEWS_PER_DAY",
    "DEFAULT_STUDIO_EMOTION",
    "DICTIONARY_ID_PATTERN",
    "EMOTIONS",
    "FIELDS",
    "OLD_VOICE_MODEL",
    "PREVIEW_TEXT_MAX_CHARS",
    "SPEED_MAX",
    "SPEED_MIN",
    "TUNING_COLUMNS",
    "VOICE_MODELS",
    "VOLUME_MAX",
    "VOLUME_MIN",
    "Audience",
    "VoiceTuningState",
    "client_previews_left",
    "config_speaking_speed",
    "config_tuning",
    "fit_speed",
    "is_studio_voice",
    "read_voice_tuning",
    "refund_client_preview",
    "refuse_invalid_tuning",
    "refuse_on_a_voice_not_studio",
    "sample_line",
    "set_voice_tuning",
    "speed_range",
    "take_client_preview",
    "tuning_from_row",
    "tuning_of",
]
