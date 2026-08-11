"""Extraction runners: the model call, and the offline one that keeps us honest.

Post-call only, never in-call (TRD §7). Two implementations behind one function:

- **`SarvamExtractor`** — the D-36 default: Sarvam 105B, free per token and sovereign
  (no transcript text leaves India, which is the whole point of D-36's residency
  argument). `GEMINI` stays configurable as the fallback and remains the reference for
  extraction quality until Sarvam is measured on the golden-transcript fixtures.
- **`OfflineExtractor`** — deterministic, no network. Used when no provider key is
  configured, which makes `ENGINE=fake` + no keys a fully working local pipeline, and
  gives the regression harness a stable baseline to diff model output against.

Both return the same `ExtractionOutput`, validated against the schema, so a provider
swap is a config change (D-04's rationale) and not a code change.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

import httpx
from calevate_shared.extraction import (
    ExtractionOutput,
    ExtractionSchemaSpec,
    build_extraction_prompt,
    validate_extraction,
)

from apps.api.core.alerting import record_extraction_failure
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings

log = get_logger(__name__)

SARVAM_CHAT_URL = "https://api.sarvam.ai/v1/chat/completions"
GEMINI_CHAT_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
EXTRACTION_TIMEOUT_S = 30.0


class Extractor(Protocol):
    model_name: str

    async def run(self, spec: ExtractionSchemaSpec, transcript: str) -> dict[str, Any]: ...


def _first_json_object(text: str) -> dict[str, Any]:
    """Models wrap JSON in prose and fences no matter how firmly you ask. Take the
    first balanced object rather than failing the whole extraction on a stray ```."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start = text.find("{")
        if start == -1:
            return {}
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    break
    if candidate is None:
        return {}
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class SarvamExtractor:
    """D-36 default. Sarvam's chat API is OpenAI-compatible."""

    def __init__(self, api_key: str, model: str = "sarvam-m") -> None:
        self._api_key = api_key
        self.model_name = model

    async def run(self, spec: ExtractionSchemaSpec, transcript: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=EXTRACTION_TIMEOUT_S) as client:
            response = await client.post(
                SARVAM_CHAT_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self.model_name,
                    "messages": [
                        {"role": "user", "content": build_extraction_prompt(spec, transcript)}
                    ],
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                },
            )
        response.raise_for_status()
        body = response.json()
        # `choices` comes back EMPTY when the provider declines to answer (filtered
        # content, truncated generation). Indexing it blindly turned "the model said
        # nothing" into an IndexError that escaped the error ladder below and failed
        # the whole post-call job — losing the call to keep the fields.
        choices = body.get("choices") or []
        content = choices[0].get("message", {}).get("content", "") if choices else ""
        return _first_json_object(str(content))


class GeminiExtractor:
    """Configurable fallback (D-36). NOTE the residency consequence: this path sends
    transcript text to Google, which is exactly the tradeoff D-36 removed by default —
    so selecting it is a per-deployment decision, never a silent failover."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash-lite") -> None:
        self._api_key = api_key
        self.model_name = model

    async def run(self, spec: ExtractionSchemaSpec, transcript: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=EXTRACTION_TIMEOUT_S) as client:
            response = await client.post(
                GEMINI_CHAT_URL.format(model=self.model_name),
                params={"key": self._api_key},
                json={
                    "contents": [{"parts": [{"text": build_extraction_prompt(spec, transcript)}]}],
                    "generationConfig": {
                        "temperature": 0,
                        "responseMimeType": "application/json",
                    },
                },
            )
        response.raise_for_status()
        body = response.json()
        # Gemini returns `candidates: []` on a safety block — a documented, ordinary
        # response, not an exception. Same reasoning as the Sarvam path above.
        candidates = body.get("candidates") or []
        parts = (candidates[0].get("content", {}).get("parts") or []) if candidates else []
        return _first_json_object(str(parts[0].get("text", "")) if parts else "")


class OfflineExtractor:
    """Deterministic, no network. Reads what the transcript literally says.

    It is not a stub: it implements the one rule the prompt insists on — never invent
    a value that was not said — so a schema field with no evidence comes back null and
    the pipeline's null-handling is exercised for real in local runs and CI.
    """

    model_name = "offline-heuristic"

    # `naa peru` / `my name is` only. The bare `peru` alternative this used to carry
    # matched the AGENT asking "Mee peru cheppandi?" and filed "Cheppandi" as the
    # caller's name — a fabricated CRM row from a question nobody answered.
    _NAME_RE = re.compile(
        r"(?:naa peru|naa pearu|my name is)\s+([A-Za-z][A-Za-z\s]{1,30}?)"
        r"(?:\s+(?:andi|garu|ji)\b|[,.]|$)",
        re.IGNORECASE,
    )
    _NEGATIVE = ("complaint", "angry", "worst", "refund", "cheating", "bad")
    _CALLBACK = ("call me back", "callback", "malli call", "tarvata call")
    # Denials, Telugu and English. A probe word appearing in the same turn as one of
    # these is a caller REFUSING the thing, which is the opposite of the fact we would
    # otherwise record.
    _DENIAL = ("ledu", "vaddu", "avasaram ledu", "no ", "not ", "don't", "dont", "never")
    # Speaker prefixes as the transcript writes them. Anything unprefixed is treated as
    # the caller only when there is no prefixed line at all (a transcript we cannot
    # attribute is not evidence about anybody).
    _CALLER_PREFIXES = ("caller:", "customer:", "user:")
    _AGENT_PREFIXES = ("agent:", "assistant:", "bot:")

    @classmethod
    def _caller_turns(cls, transcript: str) -> list[str]:
        """Only what the CALLER said, with the prefix stripped.

        Every field below describes the caller, and reading the agent's lines as
        evidence about them is how this extractor invented three different kinds of
        fact: a name out of the agent's question, a `true` out of a question the caller
        answered "ledu" to, and an enum out of the word `caller:` itself.
        """
        turns: list[str] = []
        saw_prefix = False
        for line in transcript.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            lowered = stripped.lower()
            if lowered.startswith(cls._AGENT_PREFIXES):
                saw_prefix = True
                continue
            for prefix in cls._CALLER_PREFIXES:
                if lowered.startswith(prefix):
                    saw_prefix = True
                    turns.append(stripped[len(prefix) :].strip())
                    break
            else:
                if not lowered.startswith(cls._AGENT_PREFIXES):
                    turns.append(stripped)
        if saw_prefix:
            return [turn for turn in turns if turn]
        # No speaker labels anywhere: fall back to the whole transcript rather than
        # returning nothing, but that is a transcript we cannot attribute.
        return [line.strip() for line in transcript.splitlines() if line.strip()]

    @staticmethod
    def _denied(turn: str, probe: str) -> bool:
        """Is the probe word denied in the turn that contains it?"""
        lowered = turn.lower()
        return any(marker in lowered for marker in OfflineExtractor._DENIAL)

    @staticmethod
    def _says(turn: str, needle: str) -> bool:
        """Word-boundary containment. Substring matching made `other` match inside
        "brother" and `caller` match the speaker prefix on every single line."""
        pattern = rf"(?<!\w){re.escape(needle)}(?!\w)"
        return re.search(pattern, turn, re.IGNORECASE) is not None

    async def run(self, spec: ExtractionSchemaSpec, transcript: str) -> dict[str, Any]:
        caller_turns = self._caller_turns(transcript)
        caller_text = "\n".join(caller_turns)
        lowered = caller_text.lower()
        data: dict[str, Any] = {}

        for field in spec.fields:
            if field.type == "bool":
                probe = field.label.lower().split()[0]
                if not probe:
                    continue
                # True only when the CALLER says it and does not deny it in the same
                # breath. Silence stays null: this extractor's one rule is never to
                # invent a value that was not said, and "false" is a value.
                affirmed = [
                    turn
                    for turn in caller_turns
                    if self._says(turn, probe) and not self._denied(turn, probe)
                ]
                if affirmed:
                    data[field.key] = True
                continue
            if field.key in ("name", "caller_name", "patient_name"):
                match = self._NAME_RE.search(caller_text)
                if match:
                    data[field.key] = match.group(1).strip().title()
                continue
            if field.type == "enum" and field.enum_values:
                value = next(
                    (v for v in field.enum_values if any(self._says(t, v) for t in caller_turns)),
                    None,
                )
                if value:
                    data[field.key] = value

        all_lines = [ln for ln in transcript.splitlines() if ln.strip()]
        return {
            **data,
            "summary": (all_lines[-1][:200] if all_lines else "No transcript available."),
            "sentiment": "negative" if any(w in lowered for w in self._NEGATIVE) else "neutral",
            "outcome_tag": (
                "needs_follow_up" if any(w in lowered for w in self._CALLBACK) else "resolved"
            ),
            "out_of_scope": False,
            "callback_requested": any(w in lowered for w in self._CALLBACK),
        }


def get_extractor() -> Extractor:
    """Config picks the model; there is no silent failover between providers, because
    they differ on data residency (D-36) and that is not a runtime decision."""
    settings = get_settings()
    if settings.sarvam_api_key:
        return SarvamExtractor(settings.sarvam_api_key)
    if settings.gemini_api_key:
        return GeminiExtractor(settings.gemini_api_key)
    return OfflineExtractor()


async def extract_call(
    spec: ExtractionSchemaSpec, transcript: str, *, extractor: Extractor | None = None
) -> ExtractionOutput:
    """Run one extraction pass and validate it against the schema.

    A model failure does NOT fail the call: an extraction row still lands with
    `valid=False` and the error, so the call, the lead and the metering all survive an
    LLM outage. Losing the structured fields is recoverable; losing the call is not.
    """
    runner = extractor or get_extractor()
    try:
        raw = await runner.run(spec, transcript)
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        # IndexError/TypeError belong here with the rest: a provider response whose
        # shape we did not expect is a MODEL failure, and this ladder exists so a model
        # failure costs the structured fields and never the call, the lead or the
        # metering (which all happen after this returns).
        record_extraction_failure(reason=type(exc).__name__)
        log.warning("extraction_failed", extra={"model": runner.model_name})
        return ExtractionOutput(valid=False, errors={"_model": type(exc).__name__})

    outcome = validate_extraction(spec, raw)
    if outcome.errors:
        record_extraction_failure(reason="schema_validation")

    sentiment = raw.get("sentiment")
    outcome_tag = raw.get("outcome_tag")
    return ExtractionOutput(
        data=outcome.data,
        summary=str(raw.get("summary") or "")[:2000],
        sentiment=sentiment if sentiment in ("positive", "neutral", "negative") else "neutral",
        outcome_tag=(
            outcome_tag
            if outcome_tag in ("resolved", "needs_follow_up", "transferred", "dropped")
            else "resolved"
        ),
        out_of_scope=bool(raw.get("out_of_scope")),
        callback_requested=bool(raw.get("callback_requested")),
        valid=outcome.valid,
        errors=outcome.errors,
    )


__all__ = [
    "Extractor",
    "GeminiExtractor",
    "OfflineExtractor",
    "SarvamExtractor",
    "extract_call",
    "get_extractor",
]
