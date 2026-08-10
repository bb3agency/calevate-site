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
        content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
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
        parts = body.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])
        return _first_json_object(str(parts[0].get("text", "")))


class OfflineExtractor:
    """Deterministic, no network. Reads what the transcript literally says.

    It is not a stub: it implements the one rule the prompt insists on — never invent
    a value that was not said — so a schema field with no evidence comes back null and
    the pipeline's null-handling is exercised for real in local runs and CI.
    """

    model_name = "offline-heuristic"

    _NAME_RE = re.compile(
        r"(?:naa peru|my name is|peru)\s+([A-Za-z][A-Za-z\s]{1,30}?)"
        r"(?:\s+(?:andi|garu|ji)\b|[,.]|$)",
        re.IGNORECASE,
    )
    _NEGATIVE = ("complaint", "angry", "worst", "refund", "cheating", "bad")
    _CALLBACK = ("call me back", "callback", "malli call", "tarvata call")

    async def run(self, spec: ExtractionSchemaSpec, transcript: str) -> dict[str, Any]:
        lowered = transcript.lower()
        data: dict[str, Any] = {}

        for field in spec.fields:
            if field.type == "bool":
                # Only claim true when the field's own words appear.
                probe = field.label.lower().split()[0]
                if probe and probe in lowered:
                    data[field.key] = True
                continue
            if field.key in ("name", "caller_name", "patient_name"):
                match = self._NAME_RE.search(transcript)
                if match:
                    data[field.key] = match.group(1).strip().title()
                continue
            if field.type == "enum" and field.enum_values:
                match = next((v for v in field.enum_values if v.lower() in lowered), None)
                if match:
                    data[field.key] = match

        agent_lines = [ln for ln in transcript.splitlines() if ln.strip()]
        return {
            **data,
            "summary": (agent_lines[-1][:200] if agent_lines else "No transcript available."),
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
    except (httpx.HTTPError, ValueError, KeyError) as exc:
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
