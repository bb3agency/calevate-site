"""Turns an owner's short recording into words, for the screens that take a voice note.

Two callers: the teach box's voice note (`workers/kb_teach`) and the spoken brief of "Meet
your agent" (`workers/first_run`, D-855). One provider call and one meter, so the two cannot
drift apart on the model, the codec map or what a clip is charged at.

THE PROVIDER. Sarvam's REST speech-to-text (sarvamai 0.1.28, `speech_to_text/raw_client.py`:
POST `speech-to-text` on `https://api.sarvam.ai`, multipart `file`, form `model`/`mode`/
`language_code`/`input_audio_codec`, header `api-subscription-key`). Its reference
(docs.sarvam.ai/api-reference-docs/speech-to-text/transcribe, read 23 Oct 2026) says the REST
call is for audio under 30 seconds, so every recorder that feeds this stops at 30 s.

WHY `saaras:v3` AND NOT THE NEWER DEFAULT. The same page makes `saaras:v4` the default, but
documents `mode` as "only applicable when using saaras:v3" while v4's own line claims every
mode. `codemix` (English words in English, Indian-language words in their own script, the way
owners speak) is the behaviour both screens are built on, and only v3 is documented to honour
it without contradiction. Move to v4 when its reference stops contradicting itself.

What is heard is the owner's own words about their business, never a caller's, and it is
never logged (hard rule 6). The audio is deleted by the caller as soon as the words exist.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

import httpx

from apps.api.billing.ai_quota import new_assist_ref, record_absorbed_stt_usage
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session

SARVAM_STT_URL: Final = "https://api.sarvam.ai/speech-to-text"
STT_MODEL: Final = "saaras:v3"
STT_MODE: Final = "codemix"
STT_TIMEOUT_S: Final = 40.0
#: With no hint the provider detects the language itself.
UNKNOWN_LANGUAGE: Final = "unknown"
#: The tags the provider takes as a hint (same page). Anything else is sent as `unknown`.
HINTABLE_LANGUAGES: Final = frozenset(
    {"te-IN", "hi-IN", "en-IN", "ta-IN", "kn-IN", "ml-IN", "mr-IN"}
)

#: The browser codecs a recorder may hand us, and the name the provider takes for each.
CODECS: Final[dict[str, str]] = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "mp4",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/aac": "aac",
}

#: Every recorder stops at 30 seconds and the provider's answer carries no audio length, so
#: each clip is metered at that ceiling: our recorded cost can only be above what the vendor
#: bills, never below.
CLIP_CEILING_S: Final = 30


async def transcribe(data: bytes, content_type: str, *, language: str | None = None) -> str:
    """The words in one clip. Raises `httpx.HTTPError` when the provider fails and
    `RuntimeError` when no credential is installed."""
    settings = get_settings()
    if not settings.sarvam_api_key:
        raise RuntimeError("no speech-to-text credential")
    hint = language if language in HINTABLE_LANGUAGES else UNKNOWN_LANGUAGE
    form = {"model": STT_MODEL, "mode": STT_MODE, "language_code": hint}
    codec = CODECS.get(content_type.split(";")[0].strip().lower())
    if codec:
        form["input_audio_codec"] = codec
    async with httpx.AsyncClient(timeout=STT_TIMEOUT_S, follow_redirects=False) as client:
        response = await client.post(
            SARVAM_STT_URL,
            headers={"api-subscription-key": settings.sarvam_api_key},
            data=form,
            files={"file": ("voice-note", data, content_type)},
        )
        response.raise_for_status()
        body = response.json()
    transcript = body.get("transcript") if isinstance(body, dict) else None
    return str(transcript or "").strip()


async def meter_clip(tenant_id: UUID, *, feature: str) -> None:
    """One clip at our cost, under the feature that asked for it (absorbed: never the
    client's allowance or wallet)."""
    async with tenant_session(tenant_id) as session:
        await record_absorbed_stt_usage(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            audio_seconds=CLIP_CEILING_S,
            model=STT_MODEL,
            feature=feature,
            basis="recorder_ceiling",
        )


__all__ = [
    "CLIP_CEILING_S",
    "CODECS",
    "HINTABLE_LANGUAGES",
    "STT_MODEL",
    "meter_clip",
    "transcribe",
]
