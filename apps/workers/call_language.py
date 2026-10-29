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

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

import httpx
from calevate_shared.engine import SARVAM_DEFAULT_LLM
from calevate_shared.extraction import clip_headline
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
#: Off, because translating lines and restating a summary needs no thinking, and Sarvam's
#: default (`low`) bills its reasoning as completion tokens inside `MAX_TOKENS`: a 1.5-minute
#: Telugu call (production usage rows, 24 Oct 2026) paid 19.5k output tokens for 2.2k in,
#: and a second pass on it 16.0k for 1.7k. An answer that still comes back cut off or
#: unreadable takes the failure path in `run_language_pass`, which leaves the call `failed`
#: for "Try again" and the backfill rather than dropping its English.
REASONING_EFFORT: Final[chat.ReasoningEffort] = "off"
#: Seconds the whole pass may take, all chunks and splits together. It runs inside the
#: post-call job (`WorkerSettings.job_timeout`, 300 s) after extraction; a slow provider
#: answering chunk after chunk once ran past that limit, and arq's cancellation then cost
#: the call its summary, outcome, lead and metering, on every retry.
LANGUAGE_PASS_BUDGET_S: Final = 120.0
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


#: English function words: any English sentence of a summary's length carries several.
_ENGLISH_WORDS: Final = frozenset((
    "a", "an", "the", "to", "of", "and", "or", "but", "is", "are", "was", "were", "be",
    "been", "has", "have", "had", "will", "would", "can", "could", "for", "in", "on", "at",
    "by", "with", "from", "about", "after", "before", "that", "this", "it", "he", "she",
    "they", "them", "their", "his", "her", "who", "which", "what", "when", "if", "so",
    "not", "no", "as",
))  # fmt: skip
#: Telugu and Hindi grammar words as STT and models romanise them. None is an English word,
#: and nouns are left out on purpose: a code-mixed Indian summary is mostly English nouns.
_ROMANISED_WORDS: Final = frozenset((
    # Telugu
    "ani", "annaru", "annadu", "andi", "undi", "unnaru", "unnadu", "kavali", "kaavali",
    "chepparu", "cheppadu", "cheppindi", "cheppaaru", "adigaru", "adigadu", "ledu", "kaadu",
    "vaddu", "ki", "ku", "lo", "tho", "nunchi", "kosam", "garu", "chesaru", "cheyali",
    "vachi", "vacharu", "ayindi", "avutundi", "kuda", "inka",
    # Hindi
    "hai", "hain", "tha", "thi", "ke", "ka", "ko", "mein", "se", "aur", "bhi", "nahi",
    "chahiye", "chahte", "bola", "kaha", "raha", "rahe",
))  # fmt: skip


def reads_as_romanised(text: str) -> bool:
    """Is this Latin-letter text an Indian language rather than English?

    A summary has only two scripts to tell it apart by, and a romanised Telugu one ("Customer
    Badangpet lo 5-bedroom house kavali ani, budget 45 lakhs undi ani chepparu", production,
    25 Oct 2026) is all Latin letters. Grammar words decide it: English ones are in every
    English sentence and absent from romanised Telugu or Hindi, whose own grammar words are
    absent from English. Two of theirs outnumbering ours is the call; one stray "kavali"
    quoted inside an English summary is not.
    """
    if has_indic_script(text):
        return False
    words = [w.strip(".,;:!?'\"()").casefold() for w in text.split()]
    english = sum(1 for w in words if w in _ENGLISH_WORDS)
    romanised = sum(1 for w in words if w in _ROMANISED_WORDS)
    return romanised >= 2 and romanised > english


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


def _script_words(language: str, tag: str) -> str:
    """How the call-language summary must be written: in the language's own script, named
    by its endonym, because "natural spoken Telugu" alone came back in Latin letters."""
    found = find_language(tag)
    endonym = f" ({found.endonym})" if found is not None and found.endonym else ""
    return f"in the {language} script{endonym}, never in Latin letters"


def _prompt(
    *,
    language: str,
    tag: str,
    turns: Sequence[tuple[int, str]],
    summary_en: str,
    summary_local: str,
    want_summaries: bool,
    summary_romanised: str = "",
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
    # A romanised summary is the source only when neither real one exists, and then both
    # are written from it.
    romanised = summary_romanised if not (summary_en or summary_local) else ""
    if want_summaries and (summary_en or romanised) and not summary_local:
        asks.append(
            f'"summary_local": the summary below, written in natural spoken {language} the '
            "way a person in India would say it, mixing in English words people actually "
            f"use, {_script_words(language, tag)}. Same facts, nothing added."
        )
    if want_summaries and (summary_local or romanised) and not summary_en:
        asks.append(
            '"summary_en": the summary below, in plain English: English words and English '
            "grammar. Same facts, nothing added."
        )
    summary_block = ""
    if want_summaries and (summary_en or summary_local or romanised):
        summary_block = f"\nSummary:\n{summary_en or summary_local or romanised}\n"
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
    summary_romanised: str = "",
) -> LanguagePass:
    """Translate `turns` (idx, REDACTED text) into English and fill whichever summary is
    missing; with only `summary_romanised` (the call's language in Latin letters, which is
    neither), both are written from it. A summary that comes back in the wrong form is
    dropped rather than stored as the other: an English one that `reads_as_romanised`, or a
    call-language one in Latin letters where the language has its own script. A provider
    failure returns `failed=True` with whatever earlier chunks produced; it never raises,
    because nothing here may cost the call its pipeline."""
    result = LanguagePass()
    leg = chat.ChatLeg(
        url=SARVAM_CHAT_URL, api_key=api_key, wire_model=SARVAM_DEFAULT_LLM, dialect="sarvam"
    )
    name = language_name(language)
    chunks = [turns[i : i + TURNS_PER_REQUEST] for i in range(0, len(turns), TURNS_PER_REQUEST)]
    if not chunks:
        chunks = [[]]
    wanted = {idx for idx, _ in turns}
    answered: list[TokenUsage | None] = []
    # (chunk, asks for the summaries), consumed from the front. A chunk cut off at
    # `MAX_TOKENS` is split in half and both halves go back to the front, in order: 4096 is
    # the highest cap Sarvam's lowest tier accepts, so raising the cap is not an option
    # (`extraction.EXTRACTION_MAX_TOKENS`).
    work: list[tuple[Sequence[tuple[int, str]], bool]] = [
        (chunk, number == 0 and not is_english(language)) for number, chunk in enumerate(chunks)
    ]
    try:
        async with asyncio.timeout(LANGUAGE_PASS_BUDGET_S):
            while work:
                chunk, want_summaries = work.pop(0)
                if not chunk and not want_summaries:
                    continue
                prompt = _prompt(
                    language=name,
                    tag=language,
                    turns=chunk,
                    summary_en=summary_en,
                    summary_local=summary_local,
                    want_summaries=want_summaries,
                    summary_romanised=summary_romanised,
                )
                try:
                    outcome = await chat.complete(
                        leg,
                        [{"role": "user", "content": prompt}],
                        timeout_s=EXTRACTION_TIMEOUT_S,
                        temperature=0,
                        response_format={"type": "json_object"},
                        max_tokens=MAX_TOKENS,
                        reasoning_effort=REASONING_EFFORT,
                    )
                except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
                    log.warning("call_language_pass_failed", extra={"error": type(exc).__name__})
                    result.failed = True
                    return result
                # Every answered chunk counts; one with no usage block marks the total incomplete
                # rather than vanishing from it (`chat.sum_usage`).
                answered.append(outcome.usage)
                result.usage = chat.sum_usage(answered)
                if outcome.finish_reason == "length":
                    log.warning(
                        "call_language_pass_truncated",
                        extra={"turns": len(chunk), "summaries": want_summaries},
                    )
                    if len(chunk) > 1:
                        half = len(chunk) // 2
                        work[:0] = [(chunk[:half], want_summaries), (chunk[half:], False)]
                        continue
                    result.failed = True
                body = _first_json_object(outcome.content)
                rows = body.get("turns")
                if chunk and not isinstance(rows, list):
                    # An answer with no readable lines is a failed chunk, not a call whose
                    # lines were all English already: `ready` here would hide the gap.
                    log.warning("call_language_pass_unreadable", extra={"turns": len(chunk)})
                    result.failed = True
                for row in rows if isinstance(rows, list) else []:
                    if not isinstance(row, dict):
                        continue
                    idx = row.get("i")
                    english = _clean(row.get("en"))
                    if isinstance(idx, int) and idx in wanted and english:
                        result.turns_en[idx] = english
                if want_summaries:
                    local = _clean(body.get("summary_local"))
                    english = _clean(body.get("summary_en"))
                    own_script = _script_tag_of_language(language) is not None
                    result.summary_local = (
                        local if not own_script or has_indic_script(local) else ""
                    )
                    result.summary_en = "" if reads_as_romanised(english) else english
    except TimeoutError:
        # Over budget: what the answered chunks gave is kept, and the call is left `failed`
        # for `call_translation`'s retry sweep rather than costing the rest of the pipeline.
        log.warning("call_language_pass_over_budget", extra={"turns": len(turns)})
        result.failed = True
    return result


def differs(original: str, english: str) -> bool:
    """Is `english` a translation rather than the same line handed back?"""
    return " ".join(original.split()).casefold() != " ".join(english.split()).casefold()


def untranslated_turns(
    turns: Sequence[tuple[int, str, str | None]], *, language: str
) -> list[tuple[int, str]]:
    """`(idx, redacted text)` of the turns that still need English: spoken words, no
    `text_en` yet, and either in an Indic script or on a call that was not in English."""
    return [
        (idx, body)
        for idx, body, english_text in turns
        if body.strip()
        and english_text is None
        and (has_indic_script(body) or not is_english(language))
    ]


def english_lines(pending: Sequence[tuple[int, str]], done: LanguagePass) -> dict[int, str]:
    """The pass's English for `pending`, minus the lines it handed back unchanged."""
    originals = dict(pending)
    return {
        idx: english
        for idx, english in done.turns_en.items()
        if differs(originals.get(idx, ""), english)
    }


def romanised_local(summary_local: str, *, language: str) -> bool:
    """Is the stored call-language summary the call's language in Latin letters?

    The pipeline files a romanised summary there while the language pass has not yet
    written the real two (D-931), so the screen shows the call's own words at once; the
    pass then takes it as the source of both and replaces it with the language's script.
    """
    return (
        bool(summary_local.strip())
        and not is_english(language)
        and _script_tag_of_language(language) is not None
        and not has_indic_script(summary_local)
    )


def headline_from_summary(summary: str) -> str | None:
    """The headline drawn from an English summary when the model wrote none: its first
    sentence, redacted, clipped to one line."""
    head = summary
    for mark in (". ", "? ", "! "):
        before, sep, _ = summary.partition(mark)
        if sep:
            head = before + mark.strip()
            break
    if not head.strip():
        return None
    return clip_headline(redact(head).text) or None


__all__ = [
    "MAX_TOKENS",
    "REASONING_EFFORT",
    "TURNS_PER_REQUEST",
    "LanguagePass",
    "call_language",
    "differs",
    "english_lines",
    "has_indic_script",
    "headline_from_summary",
    "is_english",
    "language_name",
    "reads_as_romanised",
    "romanised_local",
    "run_language_pass",
    "untranslated_turns",
]
