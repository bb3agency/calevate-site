"""Hear a work's first words without a phone (W1.3, UX P-01).

    GET  /v1/agents/{agent_id}/first-words      what callers hear first; can it be heard here
    POST /v1/agents/{agent_id}/first-words      the same, with its audio

The text is composed from our rows exactly as the holder's engine agent is configured
(`agents.service.held_greeting` over `line_config` / `campaign_config`, then
`compose_first_utterance`): the line's or campaign's opening with every notice its switches
turn on, said where `join_first_words` says it. It is never cut. The engine speaks at most
`voice_tuning.PREVIEW_TEXT_MAX_CHARS` characters per sample, so a longer text is spoken in
whole-sentence parts played one after another, and the parts joined are the text.

Only a Studio voice can be heard this way. The vendor speaks arbitrary text only in a voice
of our own voice key (`POST /byok/voices/preview`, mirror 2026-11-26
`pages/api-reference/bring-your-own-keys/preview-byok-voice.md`); its own catalogue voices,
which Clear agents speak in, have no such render there (`GET /voices` lists ids and names; a
clone carries one fixed `previewUrl` clip). A Clear agent gets the text with
`playable: false` and a reason, never a sample in another voice passed off as its own.

Cost: each part is a sample on our key, counted against the same per-account daily cap as the
voice-tuning samples (`voice_tuning.take_client_preview`), once per press that speaks
anything, and logged by character count only (hard rule 6: the words are never logged).
Spoken parts are kept in Redis for an hour by voice, settings, language and text, the
vendor's own cache horizon for this answer, so pressing play again costs nothing.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Annotated, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text

from apps.api.agents import voice_tuning
from apps.api.agents.hosted_voices import parse_hosted_voice_id
from apps.api.agents.service import _load_agent, held_greeting
from apps.api.agents.voice_tuning import VoiceTuningState
from apps.api.agents.voice_tuning_routes import _speaking_engine
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.core.redis import get_redis
from apps.api.db.session import tenant_session
from apps.api.engine.catalogue import PreviewAudio
from apps.api.engine.thinnest_workspace import in_workspace

log = get_logger(__name__)

Owner = Annotated[Principal, Depends(requires("org:manage"))]
Reader = Annotated[Principal, Depends(requires("agents:read"))]

router = APIRouter(tags=["agents"])

PART_MAX_CHARS: Final = voice_tuning.PREVIEW_TEXT_MAX_CHARS
#: The vendor marks this answer "cacheable privately for an hour" (preview-byok-voice.md).
CACHE_TTL_S: Final = 3600
_CACHE_PREFIX: Final = "calevate:first-words-audio:v1:"

NOT_STUDIO_RULE: Final = "first_words_needs_studio_voice"
NOT_STUDIO_REASON: Final = (
    "Hearing it here works with Studio voices. With this voice, ring your phone or type to it."
)
NO_WORDS_RULE: Final = "first_words_not_written"
NO_WORDS_REASON: Final = "It has nothing to say yet. Its script is still being written."

_SENTENCE_END: Final = re.compile(r"(?<=[.?!।])\s+")


class FirstWordsIn(BaseModel):
    """Which of the agent's works: its inbound line or its campaign."""

    model_config = ConfigDict(extra="forbid")

    line_id: UUID | None = None
    campaign_id: UUID | None = None

    @model_validator(mode="after")
    def _one_work(self) -> FirstWordsIn:
        if (self.line_id is None) == (self.campaign_id is None):
            raise ValueError("send `line_id` or `campaign_id`, one of them")
        return self


class FirstWordsPartOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The words this part says.
    text: str
    #: `audio/mpeg` or `audio/wav`.
    content_type: str
    #: The spoken part, base64.
    audio: str


class FirstWordsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: What a caller hears first, whole: the opening with the notices it carries. Null before
    #: the work has a script.
    text: str | None
    language: str
    playable: bool
    #: Why it cannot be heard here (`first_words_needs_studio_voice`,
    #: `first_words_not_written`); null when playable.
    unavailable_rule: Literal["first_words_needs_studio_voice", "first_words_not_written"] | None
    unavailable_reason: str | None
    #: The audio, in order. Played one after another they say `text`.
    parts: list[FirstWordsPartOut] = Field(default_factory=list)


def spoken_parts(words: str, limit: int = PART_MAX_CHARS) -> list[str]:
    """`words` in parts the engine will speak, each at most `limit` characters, cut between
    sentences where one fits and between words where a sentence does not. Nothing is dropped:
    the parts joined with single spaces are `words` with its spacing made single."""
    parts: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(" ".join(words.split())):
        for piece in _within(sentence, limit):
            joined = f"{current} {piece}" if current else piece
            if len(joined) <= limit:
                current = joined
            else:
                parts.append(current)
                current = piece
    if current:
        parts.append(current)
    return parts


def _within(sentence: str, limit: int) -> list[str]:
    """One sentence as pieces of at most `limit`, between words; a single word longer than
    `limit` (no spoken language has one) is cut where it must be."""
    if len(sentence) <= limit:
        return [sentence] if sentence else []
    pieces: list[str] = []
    current = ""
    for word in sentence.split(" "):
        while len(word) > limit:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(word[:limit])
            word = word[limit:]
        joined = f"{current} {word}" if current else word
        if len(joined) <= limit:
            current = joined
        else:
            pieces.append(current)
            current = word
    if current:
        pieces.append(current)
    return pieces


_HOLDER_AGENT_SQL: Final[dict[str, str]] = {
    "line": (
        "SELECT agent_id, NULL AS language FROM inbound_lines "
        "WHERE id = :hid AND archived_at IS NULL"
    ),
    # A campaign may speak another language than its agent (D-994), as its calls do.
    "campaign": (
        "SELECT agent_id, settings_overrides->>'language_primary' AS language FROM campaigns "
        "WHERE id = :hid"
    ),
}


_AGENT_SQL: Final = "SELECT 1 FROM agents WHERE id = :aid AND deleted_at IS NULL"


def _cache_key(*, voice: str, language: str, tuning: str, words: str) -> str:
    digest = hashlib.sha256("\x1f".join((voice, language, tuning, words)).encode()).hexdigest()
    return f"{_CACHE_PREFIX}{digest}"


async def _cached(key: str) -> FirstWordsPartOut | None:
    """A part spoken within the hour, or None. Redis down fails the press, as the daily
    counter beside it does (it fails closed: an unreadable counter is no bound)."""
    raw = await get_redis().get(key)
    return FirstWordsPartOut.model_validate(json.loads(raw)) if raw else None


async def _keep(key: str, part: FirstWordsPartOut) -> None:
    await get_redis().set(key, part.model_dump_json(), ex=CACHE_TTL_S)


@dataclass(frozen=True, slots=True)
class _Words:
    """A work's first words as its calls compose them, and the voice they are spoken in."""

    words: str | None
    language: str
    state: VoiceTuningState


async def _read(tenant_id: UUID, agent_id: UUID, work: FirstWordsIn) -> _Words:
    kind = "line" if work.line_id is not None else "campaign"
    # Read and released before any engine round trip: no transaction is held open across a
    # vendor call.
    async with tenant_session(tenant_id) as scoped:
        holder_id = work.line_id or work.campaign_id
        holder = (await scoped.execute(text(_HOLDER_AGENT_SQL[kind]), {"hid": holder_id})).first()
        if holder is None or UUID(str(holder.agent_id)) != agent_id:
            raise ProblemError.not_found("Inbound line" if kind == "line" else "Campaign")
        agent = await _load_agent(scoped, tenant_id, agent_id)
        words = await held_greeting(
            scoped,
            tenant_id=tenant_id,
            agent=agent,
            line_id=work.line_id,
            campaign_id=work.campaign_id,
        )
        state = await voice_tuning.read_voice_tuning(scoped, agent_id)
    return _Words(
        words=words, language=str(holder.language or agent["language_primary"]), state=state
    )


def _unheard(read: _Words) -> FirstWordsOut | None:
    """The answer for words that cannot be heard here, or None when they can."""
    if not read.words:
        return FirstWordsOut(
            text=None,
            language=read.language,
            playable=False,
            unavailable_rule=NO_WORDS_RULE,
            unavailable_reason=NO_WORDS_REASON,
        )
    if not read.state.studio or parse_hosted_voice_id(read.state.voice_id) is None:
        return FirstWordsOut(
            text=read.words,
            language=read.language,
            playable=False,
            unavailable_rule=NOT_STUDIO_RULE,
            unavailable_reason=NOT_STUDIO_REASON,
        )
    return None


_WHEN_UNHEARD: Final = (
    "A Clear voice answers `playable: false` with `first_words_needs_studio_voice`; a work "
    "with no script yet, `first_words_not_written`."
)


@router.get(
    "/v1/agents/{agent_id}/first-words",
    response_model=FirstWordsOut,
    openapi_extra=permission_meta("agents:read"),
    summary="What callers hear first on one of this agent's works, and whether it can be heard",
    description=(
        "The first words of the agent's inbound line or campaign (send one of `line_id`, "
        "`campaign_id`), composed as its calls compose them: the opening with the notices it "
        "carries, whole. Speaks nothing and counts nothing, so a screen offers the play "
        f"button only where a press can play. {_WHEN_UNHEARD}"
    ),
)
async def read_first_words(
    agent_id: UUID,
    principal: Reader,
    line_id: UUID | None = None,
    campaign_id: UUID | None = None,
) -> FirstWordsOut:
    assert principal.tenant_id is not None  # client realm; `requires()` resolves it
    # The agent first, so a neighbour's id is not found before anything else is said of it.
    async with tenant_session(principal.tenant_id) as scoped:
        if (await scoped.execute(text(_AGENT_SQL), {"aid": agent_id})).first() is None:
            raise ProblemError.not_found("Agent")
    try:
        work = FirstWordsIn(line_id=line_id, campaign_id=campaign_id)
    except ValueError as exc:
        raise ProblemError(
            kind="validation",
            code="first_words_one_work",
            title="Name one work",
            detail="Send `line_id` or `campaign_id`, one of them.",
        ) from exc
    read = await _read(principal.tenant_id, agent_id, work)
    return _unheard(read) or FirstWordsOut(
        text=read.words,
        language=read.language,
        playable=True,
        unavailable_rule=None,
        unavailable_reason=None,
    )


@router.post(
    "/v1/agents/{agent_id}/first-words",
    response_model=FirstWordsOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Hear what callers hear first on one of this agent's works, without a call",
    description=(
        "The words `GET` reads, with the audio in the agent's Studio voice and its saved "
        f"settings: one part per {PART_MAX_CHARS} characters at most, cut between sentences, "
        "to be played in order. Counts as one sample against the "
        f"{voice_tuning.CLIENT_PREVIEWS_PER_DAY} a day the voice samples share, only when "
        f"something new is spoken. {_WHEN_UNHEARD}"
    ),
)
async def hear_first_words(
    agent_id: UUID, payload: FirstWordsIn, principal: Owner
) -> FirstWordsOut:
    tenant_id = principal.tenant_id
    assert tenant_id is not None  # client realm; `requires()` resolves it
    read = await _read(tenant_id, agent_id, payload)
    unheard = _unheard(read)
    if unheard is not None:
        return unheard
    words, language, state = read.words, read.language, read.state
    assert words is not None
    ref = parse_hosted_voice_id(state.voice_id)
    assert ref is not None
    pieces = spoken_parts(words)
    tuning = state.tuning.model_dump_json()
    keys = [
        _cache_key(voice=ref.vendor_id, language=language, tuning=tuning, words=piece)
        for piece in pieces
    ]
    held = [await _cached(key) for key in keys]
    missing = [index for index, part in enumerate(held) if part is None]
    if missing:
        engine, workspace = await _speaking_engine("client")
        counted = await voice_tuning.take_client_preview(tenant_id)

        async def speak(piece: str) -> PreviewAudio:
            with in_workspace(workspace):
                return await engine.preview_own_key_voice(
                    voice_id=ref.vendor_id, text=piece, language=language, tuning=state.tuning
                )

        try:
            spoken = await asyncio.gather(*(speak(pieces[index]) for index in missing))
        except Exception:
            await voice_tuning.refund_client_preview(counted)
            raise
        for index, audio in zip(missing, spoken, strict=True):
            part = FirstWordsPartOut(
                text=pieces[index],
                content_type=audio.content_type,
                audio=base64.b64encode(audio.data).decode(),
            )
            held[index] = part
            await _keep(keys[index], part)
        log.info(
            "client_first_words_spoken",
            extra={
                "tenant_id": str(tenant_id),
                "agent_id": str(agent_id),
                "parts": len(missing),
                "characters": sum(len(pieces[index]) for index in missing),
            },
        )
    return FirstWordsOut(
        text=words,
        language=language,
        playable=True,
        unavailable_rule=None,
        unavailable_reason=None,
        parts=[part for part in held if part is not None],
    )


__all__ = ["FirstWordsOut", "router", "spoken_parts"]
