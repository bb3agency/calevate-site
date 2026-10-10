"""After-call language work: which language a call was in, English for each turn, and the
summary in both English and the call's language (founder decisions 4 and 5, 10 Oct 2026).

ONE MODEL ROUND TRIP PER CALL in the common case, on the Sarvam chat leg the first
extraction pass already uses, made from REDACTED text only: `transcript_turns.
text_redacted` and the redacted English summary. So the English turns are redacted like
the originals by construction (they are a translation of the redacted words), and nothing
here widens what the first pass already sends. It runs in the post-call worker, never in a
request handler, and is metered at our cost under `ASSIST_FEATURE_CALL_LANGUAGE` by the
caller (hard rule 7).

The engine cannot be asked for its summary in a given language (ThinnestAI has no field for
it: create-agent.md:1024-1026, mirror 2026-10-08, and docs.thinnest.ai read 10 Oct 2026),
so whichever of the two summaries it did not write is produced here.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

import httpx
from calevate_shared.engine import SARVAM_DEFAULT_LLM
from calevate_shared.languages import find_language

from apps.api.core.logging import get_logger
from apps.workers import chat
from apps.workers.chat import TokenUsage
from apps.workers.extraction import (
    EXTRACTION_TIMEOUT_S,
    SARVAM_CHAT_URL,
    _first_json_object,
)
from apps.workers.redaction import redact

log = get_logger(__name__)

#: Unicode blocks of the Indic scripts a caller here writes in, and the language each one
#: stands for when the agent's own language does not already say. Devanagari is Hindi
#: unless the agent speaks Marathi.
_SCRIPT_BLOCKS: Final[tuple[tuple[int, int, str], ...]] = (
    (0x0900, 0x097F, "hi-IN"),
    (0x0980, 0x09FF, "bn-IN"),
    (0x0A80, 0x0AFF, "gu-IN"),
    (0x0B00, 0x0B7F, "od-IN"),
    (0x0B80, 0x0BFF, "ta-IN"),
    (0x0C00, 0x0C7F, "te-IN"),
    (0x0C80, 0x0CFF, "kn-IN"),
    (0x0D00, 0x0D7F, "ml-IN"),
)

#: Turns per request. A turn here is a sentence or two, so forty of them and their
#: translations stay well inside `MAX_TOKENS` while a long call costs a few requests.
TURNS_PER_REQUEST: Final = 40
MAX_TOKENS: Final = 4096
#: The longest English summary or call-language summary kept.
SUMMARY_MAX: Final = 2000


def _block_of(char: str) -> str | None:
    point = ord(char)
    for low, high, tag in _SCRIPT_BLOCKS:
        if low <= point <= high:
            return tag
    return None


def has_indic_script(text: str) -> bool:
    return any(_block_of(char) is not None for char in text)


def is_english(tag: str | None) -> bool:
    return bool(tag) and str(tag).lower().startswith("en")


def call_language(texts: Sequence[str], *, agent_language: str) -> str:
    """The call's language as a BCP-47 tag: the script most of the words were written in,
    or the agent's own language when the transcript is all Latin letters (English, or an
    Indian language the STT romanised)."""
    counts: dict[str, int] = {}
    for text in texts:
        for char in text:
            tag = _block_of(char)
            if tag is not None:
                counts[tag] = counts.get(tag, 0) + 1
    if not counts:
        return agent_language
    dominant = max(counts, key=lambda tag: counts[tag])
    # An agent speaking Marathi writes Devanagari too: the agent's tag wins when its script
    # is the one the call was written in.
    if _script_tag_of_language(agent_language) == dominant:
        return agent_language
    return dominant


def _script_tag_of_language(tag: str) -> str | None:
    """The `_SCRIPT_BLOCKS` tag whose script `tag` is written in, by its endonym."""
    language = find_language(tag)
    if language is None:
        return None
    for char in language.endonym:
        block = _block_of(char)
        if block is not None:
            return block
    return None


def language_name(tag: str) -> str:
    language = find_language(tag)
    return language.english_name if language is not None else tag


@dataclass(slots=True)
class LanguagePass:
    """What the pass produced. Every text is redacted; empty means "not produced"."""

    turns_en: dict[int, str] = field(default_factory=dict)
    summary_en: str = ""
    summary_local: str = ""
    usage: TokenUsage | None = None
    failed: bool = False


def _prompt(
    *,
    language: str,
    turns: Sequence[tuple[int, str]],
    summary_en: str,
    summary_local: str,
    want_summaries: bool,
) -> str:
    lines = "\n".join(
        json.dumps({"i": idx, "text": text}, ensure_ascii=False) for idx, text in turns
    )
    asks = [
        '"turns": a list of {"i": <the same i>, "en": "<the line in natural English>"} for '
        "every line below. Translate meaning, not word by word. Keep names as they are. "
        "Keep every bracketed placeholder exactly as written. If a "
        "line is already entirely English, return it unchanged."
    ]
    if want_summaries and summary_en and not summary_local:
        asks.append(
            f'"summary_local": the English summary below, written in natural spoken '
            f"{language} the way a person in India would say it, mixing in English words "
            "people actually use. Same facts, nothing added."
        )
    if want_summaries and summary_local and not summary_en:
        asks.append('"summary_en": the summary below, in plain English. Same facts, nothing added.')
    summary_block = ""
    if want_summaries and (summary_en or summary_local):
        summary_block = f"\nSummary:\n{summary_en or summary_local}\n"
    return (
        f"You are translating a phone call from {language} into English for a business owner."
        "\nReturn ONLY a JSON object with these keys:\n- "
        + "\n- ".join(asks)
        + f"\n{summary_block}\nLines (one JSON object per line):\n{lines}\n"
    )


def _clean(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return redact(value.strip()).text[:SUMMARY_MAX]


async def run_language_pass(
    *,
    api_key: str,
    language: str,
    turns: Sequence[tuple[int, str]],
    summary_en: str,
    summary_local: str,
) -> LanguagePass:
    """Translate `turns` (idx, REDACTED text) into English and fill whichever summary is
    missing. A provider failure returns `failed=True` with whatever earlier chunks
    produced; it never raises, because nothing here may cost the call its pipeline."""
    result = LanguagePass()
    leg = chat.ChatLeg(
        url=SARVAM_CHAT_URL, api_key=api_key, wire_model=SARVAM_DEFAULT_LLM, dialect="sarvam"
    )
    name = language_name(language)
    chunks = [turns[i : i + TURNS_PER_REQUEST] for i in range(0, len(turns), TURNS_PER_REQUEST)]
    if not chunks:
        chunks = [[]]
    wanted = {idx for idx, _ in turns}
    for number, chunk in enumerate(chunks):
        want_summaries = number == 0 and not is_english(language)
        if not chunk and not want_summaries:
            continue
        prompt = _prompt(
            language=name,
            turns=chunk,
            summary_en=summary_en,
            summary_local=summary_local,
            want_summaries=want_summaries,
        )
        try:
            outcome = await chat.complete(
                leg,
                [{"role": "user", "content": prompt}],
                timeout_s=EXTRACTION_TIMEOUT_S,
                temperature=0,
                response_format={"type": "json_object"},
                max_tokens=MAX_TOKENS,
            )
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            log.warning("call_language_pass_failed", extra={"error": type(exc).__name__})
            result.failed = True
            return result
        if outcome.usage is not None:
            result.usage = (
                outcome.usage if result.usage is None else result.usage.plus(outcome.usage)
            )
        if outcome.finish_reason == "length":
            result.failed = True
        body = _first_json_object(outcome.content)
        rows = body.get("turns")
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            idx = row.get("i")
            english = _clean(row.get("en"))
            if isinstance(idx, int) and idx in wanted and english:
                result.turns_en[idx] = english
        if want_summaries:
            result.summary_local = _clean(body.get("summary_local"))
            result.summary_en = _clean(body.get("summary_en"))
    return result


def differs(original: str, english: str) -> bool:
    """Is `english` a translation rather than the same line handed back?"""
    return " ".join(original.split()).casefold() != " ".join(english.split()).casefold()


__all__ = [
    "MAX_TOKENS",
    "TURNS_PER_REQUEST",
    "LanguagePass",
    "call_language",
    "differs",
    "has_indic_script",
    "is_english",
    "language_name",
    "run_language_pass",
]
