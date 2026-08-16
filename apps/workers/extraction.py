"""Extraction runners: the model calls, the offline one that keeps us honest, and the
ONE place that decides what happens when a provider cannot serve.

Post-call only, never in-call (TRD §7). Three implementations behind two selectors, and
the split between the selectors is the whole of D-127's G-2/G-7:

- **`SarvamExtractor`** — Sarvam 105B, free per token and sovereign. It is what
  `get_extractor()` returns, and after D-127 it is the ONLY thing `get_extractor()` can
  return besides the offline baseline.
- **`VertexGeminiExtractor`** — Gemini through Vertex AI `asia-south1` (D-127 G-1). It
  serves the USER-TRIGGERED work — re-summarise, reshape, ask-about — over the REDACTED
  copy of a call, and it is reached only through `run_assist()`.
- **`OfflineExtractor`** — deterministic, no network. Used when no provider key is
  configured, which makes `ENGINE=fake` + no keys a fully working local pipeline, and
  gives the regression harness a stable baseline to diff model output against.

All three return the same `ExtractionOutput`, validated against the schema, so a
provider swap is a config change (D-04's rationale) and not a code change.

--------------------------------------------------------------------------------------
WHY GEMINI IS NOT REACHABLE FROM `get_extractor()` ANY MORE (D-127 G-2 + G-7)
--------------------------------------------------------------------------------------
It used to be: Sarvam if a Sarvam key was configured, Gemini if only a Gemini key was.
That ladder was written before there was a rule about WHOSE DATA each provider sees, and
it does not survive the rule.

`workers/pipeline.py` computes `redacted = redact(turn.text)` and then appends
`turn.text` — the RAW turn, one line later, deliberately — to the string it hands
`extract_call`, because a CRM "callback number" field needs the actual digits and an
extractor reading `[REDACTED]` returns nothing worth storing. So the first post-call
extraction is THE raw-PII pass, and G-2 says the Google leg never sees raw PII. A
config-reachable branch in which it does is not a fallback, it is a residency inversion
one absent environment variable away — the exact shape `check_model_residency` exists to
make impossible in URLs, applied to the selector instead.

**`GEMINI_EXTRACTION_DEFAULT is False`**, permanently, and the constant below is the
greppable form of that sentence so `check_docs_drift` §5 can catch the next document
that says otherwise. G-7 is not a compromise reached on cost or quality: it is the only
split under which both halves of D-127 are true at once.

--------------------------------------------------------------------------------------
AVAILABILITY IS DECIDED ONCE (D-127 G-6, PLAN Part 15)
--------------------------------------------------------------------------------------
`assist_capability()` is the only place that answers "what happens when Gemini is
unconfigured, over quota, or down", and it gives one of two answers: fall back to Sarvam
and SAY SO, or refuse with a message and a remediation. A silent fallback quietly
changes output quality with nobody told, which is the one outcome G-6 rules out — so the
disclosure travels on the capability object rather than being left to each surface to
remember. The shape is `billing/payments.PaymentCapability`'s, deliberately: one lookup,
one object, authored reason codes that name OUR configuration state and never a vendor's
error string.

**Scoring the model path.** The regression harness already runs against whatever
`get_extractor()` returns and keys its baseline by `model_name`, so scoring Sarvam
against the golden transcripts needs no flag and no new mode — it is

    SARVAM_API_KEY=... uv run python -m scripts.eval --client=<slug> --update-baseline

on a machine that holds a key, and the per-model baseline is the reviewable diff. A
credentialed mode was deliberately NOT added to CI: CI has no key, and giving it one
would ship committed transcripts to a provider on every push for a non-deterministic,
rate-limited, chargeable result that could not gate a merge anyway. What CI can gate
without credentials is the two ARTEFACTS this path is made of — the prompt's rules and
the validator's rejections — and that is `tests/extraction_prompt_test.py`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Final, Protocol

import httpx
from calevate_shared.engine import (
    GEMINI_DEFAULT_LLM,
    GEMINI_MODEL_CONFIRMED_IN_REGION,
    SARVAM_DEFAULT_LLM,
    VERTEX_LOCATION,
)
from calevate_shared.extraction import (
    ExtractionField,
    ExtractionOutput,
    ExtractionSchemaSpec,
    build_extraction_prompt,
    validate_extraction,
)

from apps.api.core.alerting import record_extraction_failure
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.workers.google_oauth import ServiceAccount, access_token, parse_service_account
from apps.workers.redaction import redact

log = get_logger(__name__)

SARVAM_CHAT_URL = "https://api.sarvam.ai/v1/chat/completions"
EXTRACTION_TIMEOUT_S = 30.0

#: Does the FIRST post-call extraction run on Gemini? No, and D-127 G-7 says never.
#:
#: A greppable boolean rather than a paragraph, which is this repo's honesty device
#: (`PROVIDER_CREATES_ORDERS`, `ENGINE_REPORTS_TTS_MODEL`, `PROVISIONING_IMPLEMENTED`).
#: It exists because twenty-four `file:line` locations across the doc set stated Gemini's
#: role in prose that bound nothing, so `check_docs_drift` §5 could not see them drift —
#: and they had all drifted. Prose that quotes this name by value is now machine-checked
#: against the tree.
#:
#: Flipping it to True would require raw caller PII to reach a second processor, so it is
#: not a knob: it is a fact about which pass reads `turn.text`.
GEMINI_EXTRACTION_DEFAULT: Final = False

#: The OAuth2 scope a Vertex bearer needs. `cloud-platform` is the only scope Vertex
#: publishes for `generateContent`; there is no narrower model-inference scope to ask for.
VERTEX_SCOPE: Final = "https://www.googleapis.com/auth/cloud-platform"


def vertex_generate_url(project: str, model: str) -> str:
    """The Vertex `generateContent` endpoint for one project and model, pinned to Mumbai.

    THE REGION APPEARS TWICE — in the host and in the `locations/` path segment — and the
    two can disagree: a host pinned to `asia-south1` with `locations/global` in the path
    is the global endpoint wearing a regional host, on which Google states the caller
    cannot control which region processes the request. One `Final` constant
    (`calevate_shared.engine.VERTEX_LOCATION`) fills both, which is what makes them unable
    to disagree, and `scripts/check_model_residency.py` reads this f-string's AST to prove
    it — a plain `.format()` template would say `{loc}` and nothing about where `loc` came
    from, which is why this is a function over an f-string and not a module constant with
    three holes in it.

    The project is interpolated rather than validated here; `Settings.gcp_project_id`
    carries GCP's own 6-30 character pattern, so a value that reaches this point is
    already the right shape.
    """
    return (
        f"https://{VERTEX_LOCATION}-aiplatform.googleapis.com/v1/projects/{project}"
        f"/locations/{VERTEX_LOCATION}/publishers/google/models/{model}:generateContent"
    )


class Extractor(Protocol):
    model_name: str

    async def run(self, spec: ExtractionSchemaSpec, transcript: str) -> dict[str, Any]: ...


def _first_json_object(text: str) -> dict[str, Any]:
    """Models wrap JSON in prose and fences no matter how firmly you ask. Take the
    first balanced object rather than failing the whole extraction on a stray ```.

    A RECOVERY, and a recovery is strictly weaker than a constraint — which is why the
    Vertex path does not use it: `build_vertex_response_schema` makes valid JSON a
    model-side guarantee there. It stays for Sarvam, whose chat API publishes
    `response_format: {"type": "json_object"}` but no per-request schema, and for the
    offline runner. Deleting it here to "finish the migration" would trade a working
    recovery for a provider that cannot make the stronger promise."""
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

    def __init__(self, api_key: str, model: str = SARVAM_DEFAULT_LLM) -> None:
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


#: How each schema field type is spelled in a Vertex `responseSchema`. Vertex takes a
#: SUBSET of OpenAPI 3.0 Schema with UPPER-CASE type names, and supports `nullable`,
#: `required` and `propertyOrdering` on an OBJECT (searched 15 Aug 2026; REPORTED, NOT
#: READ — `docs.cloud.google.com` is refused by this environment's egress proxy).
#:
#: `date` is STRING and not `format: "date"` on purpose. The prompt tells the model to
#: keep a relative time in the caller's own words ("repu udayam") and `coerce_value`
#: parses ISO where it can; a schema-level date format would make the model INVENT a
#: calendar date for "tomorrow morning" to satisfy the type, which is the one thing this
#: whole path is built not to do.
_VERTEX_TYPES: Final[dict[str, str]] = {
    "text": "STRING",
    "number": "NUMBER",
    "bool": "BOOLEAN",
    "enum": "STRING",
    "date": "STRING",
}

#: The five keys every extraction returns regardless of schema (TRD §7). Spelled here in
#: Vertex's dialect so the response schema and `build_extraction_prompt` cannot disagree
#: about what a complete answer is.
_VERTEX_FIXED_PROPERTIES: Final[dict[str, dict[str, Any]]] = {
    "summary": {"type": "STRING"},
    "sentiment": {"type": "STRING", "enum": ["positive", "neutral", "negative"]},
    "outcome_tag": {
        "type": "STRING",
        "enum": ["resolved", "needs_follow_up", "transferred", "dropped"],
    },
    "out_of_scope": {"type": "BOOLEAN"},
    "callback_requested": {"type": "BOOLEAN"},
}


def _vertex_property(field: ExtractionField) -> dict[str, Any]:
    """One schema field as a Vertex property. Nullable, always."""
    prop: dict[str, Any] = {"type": _VERTEX_TYPES[field.type], "nullable": True}
    if field.type == "enum" and field.enum_values:
        prop["enum"] = list(field.enum_values)
    if field.description:
        prop["description"] = field.description
    return prop


def build_vertex_response_schema(spec: ExtractionSchemaSpec) -> dict[str, Any]:
    """The `responseSchema` that makes valid JSON a model-side guarantee.

    WHY THIS REPLACES THE PARSER ON THIS PATH AND ONLY THIS PATH. `_first_json_object`
    exists because models wrap JSON in prose and fences however firmly you ask; it is a
    recovery, and a recovery is strictly weaker than a constraint. Vertex will not emit a
    document that violates this schema, so on this path the fence-stripping has nothing
    left to do. It stays for Sarvam, which publishes `response_format: json_object` but
    no schema — deleting it there would trade a working recovery for a provider that
    cannot make the stronger promise.

    WHAT IS AND IS NOT `required`. Only the five fixed keys are, because they are the
    ones `ExtractionOutput` always carries and a model omitting them is a malformed
    answer. Every SCHEMA field is optional and nullable, which is the prompt's own rule
    ("ABSENT MEANS NULL") expressed in a place the model cannot argue with: forcing a
    client's `callback_number` to be present would push the model to invent one, and a
    phone number one digit wrong is the worst output this system can produce.

    `propertyOrdering` puts the schema fields first. Generation is left-to-right, so the
    model reads the transcript for facts before it writes the summary that would
    otherwise anchor them.

    A SCHEMA FIELD MAY COLLIDE WITH A FIXED ONE, and `ExtractionField.key`'s pattern
    (`^[a-z][a-z0-9_]{0,39}$`) permits every one of the five — "Summary of complaint" is
    an ordinary column for a client to author, and `summary` is the obvious key for it.
    `properties` already resolved that the right way, because `.update()` lets the fixed
    definition win and the five fixed keys are what `ExtractionOutput` promises. What it
    did NOT resolve was the ORDER list, which listed the colliding key twice — a
    `propertyOrdering` naming one property two times is a malformed OpenAPI object, so
    one client's field name turned every assist for that tenant into a 400 the error
    ladder could only report as `HTTPStatusError`. The fixed keys stay last: they are the
    summary-and-judgement half, and reading the transcript for facts first is the whole
    reason this list exists.

    ⚠ THE SCHEMA IS INPUT. It is serialised into the request and counted against the
    input token budget — a 30-field schema with descriptions is not free, which is why
    `VertexGeminiExtractor` reads Vertex's own `usageMetadata` back rather than counting
    the prompt: `ai_assist_ktok_in` (D-137) has to be what the vendor charged for, and
    the schema is the part of that number nobody would have thought to add up.
    """
    properties: dict[str, Any] = {field.key: _vertex_property(field) for field in spec.fields}
    properties.update(_VERTEX_FIXED_PROPERTIES)
    return {
        "type": "OBJECT",
        "properties": properties,
        "required": list(_VERTEX_FIXED_PROPERTIES),
        "propertyOrdering": [
            *(field.key for field in spec.fields if field.key not in _VERTEX_FIXED_PROPERTIES),
            *_VERTEX_FIXED_PROPERTIES,
        ],
    }


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """What one model call cost, in the vendor's own count.

    Tokens, not thousands: `billing/ai_quota.ktok()` converts, once, where the money is,
    because `qty` is `NUMERIC` and a division done here would arrive as a float.
    """

    prompt_tokens: int
    output_tokens: int


def _vertex_usage(body: dict[str, Any]) -> TokenUsage | None:
    """Vertex's `usageMetadata` as our own record, or None if it did not send one.

    NONE IS NOT ZERO and the difference is a billing one: a missing block means we do not
    know what this call cost, and metering it as zero would quietly give one tenant a
    free assist and move the platform brake by nothing. `record_ai_assist_usage` is
    therefore never called on a None, and that is the caller's rule to keep.

    `thoughtsTokenCount` is folded into OUTPUT. Every Gemini generation this repo has
    shipped bills thinking tokens at the output rate — 2.5 Flash (`GEMINI_DEFAULT_LLM`
    since the founder's `asia-south1` decision) as much as the 3.x tier it replaced — and
    a reasoning model asked for structured JSON spends most of its budget there, so
    counting only `candidatesTokenCount` would under-meter the very calls that cost the
    most. It is added rather than replaced because Google reports the two separately and
    `candidatesTokenCount` does not include it.
    """
    raw = body.get("usageMetadata")
    if not isinstance(raw, dict):
        return None

    def _count(key: str) -> int:
        value = raw.get(key)
        return value if isinstance(value, int) and value >= 0 else 0

    total_in = _count("promptTokenCount")
    total_out = _count("candidatesTokenCount") + _count("thoughtsTokenCount")
    if total_in == 0 and total_out == 0:
        return None
    return TokenUsage(prompt_tokens=total_in, output_tokens=total_out)


class VertexGeminiExtractor:
    """Gemini through Vertex AI `asia-south1` (D-127 G-1). NEVER the AI Studio API.

    THE ENDPOINT IS THE DECISION. `generativelanguage.googleapis.com` — what this class
    reached before PLAN Part 13 — is a global host with no region anywhere in the URL,
    and on the free tier Google states it uses submitted prompts and responses to improve
    its products with human reviewers able to read them. For a Processor holding an Indian
    SMB's callers' transcripts that is not a tradeoff, it is a disclosure we could not
    make. Vertex `asia-south1` processes and stores in-region for GA generative features
    and does not train on paid usage, so D-36's guarantee survives even though D-36's
    ARGUMENT ("Sarvam is sovereign") does not.

    AUTH IS AN OAUTH2 BEARER, NOT AN API KEY, and that is not a preference either: Vertex
    does not accept `?key=` at all. The bearer is minted from a service-account key
    through `google_oauth` (RFC 7523 JWT-bearer, one shared implementation with the Sheets
    adapter) and expires in about an hour, so it is fetched per run through a cache that
    refreshes five minutes before expiry rather than captured once for the life of a
    worker — a worker process here outlives an hour routinely.

    WHAT IT IS ALLOWED TO SEE: redacted call data and tenant-authored config (G-2).
    `run_assist()` is the only caller and enforces that; this class does not re-check,
    because a guard in two places is a guard whose two halves eventually disagree about
    which one is authoritative.
    """

    def __init__(
        self,
        account: ServiceAccount,
        project: str,
        model: str = GEMINI_DEFAULT_LLM,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._account = account
        self._project = project
        self.model_name = model
        # Same injection seam, and the same ownership rule, as `GoogleSheetsTransport`: a
        # caller-supplied client is the caller's to close. It exists so tests drive this
        # adapter through httpx's real request plumbing (`httpx.MockTransport`) rather
        # than a hand-written stand-in that cannot get a URL wrong.
        self._client = client
        #: What the LAST `run()` cost, as Vertex counted it — never as we counted it.
        #:
        #: MUTABLE STATE ON AN ADAPTER, deliberately, and the bound is what makes it
        #: safe: `run_assist()` constructs one of these per assist and reads this
        #: attribute in the next statement, so there is never a second `run()` to race
        #: with. The rejected alternative was widening the `Extractor` Protocol to return
        #: usage — which would make `OfflineExtractor` and `SarvamExtractor` answer a
        #: question one of them cannot (no network) and the other need not (D-36 prices
        #: the Sarvam leg at zero), i.e. two implementations forced to state a number
        #: nobody meters. `record_ai_assist_usage` (D-137) meters GEMINI, because Gemini
        #: is the leg that costs Calevate rupees.
        self.last_usage: TokenUsage | None = None

    def _log_refusal(self, status: int) -> None:
        """The one place a Vertex non-2xx becomes something an operator can act on.

        WHY THIS EXISTS AT ALL. `extract_call`'s ladder records `type(exc).__name__`, so
        every failure on this path reached the log as the single word `HTTPStatusError` —
        401 (the key), 403 (the IAM grant), 404 (the region does not serve this model),
        429 (quota) and 503 (Google) all indistinguishable, on a path where the ONE
        vendor fact D-127 could not verify from this repository is exactly the one a 404
        answers. The status is the whole diagnosis and it was being thrown away.

        THE BODY IS NEVER LOGGED (hard rule 6). Google's error bodies quote the request,
        and the request on this path is a call transcript — redacted, but redacted text
        is still transcript-derived and does not belong in a log line.
        """
        if status == 404:
            # THE GATE, at the only moment anyone is looking. `check_model_residency`
            # can prove the URL is regional; nothing in this repository can prove the
            # region serves the model, and a 404 from a host that unambiguously belongs
            # to our project is that proof arriving. Named so an operator greps it, and
            # spelling the alternative out because the wrong fix is the tempting one.
            log.error(
                "vertex_model_not_served_in_region",
                extra={
                    "region": VERTEX_LOCATION,
                    "model": self.model_name,
                    "project": self._project,
                    # READ, not quoted. The flag and the 404 that settles it belong in
                    # one line, and a string naming the constant would drift off it.
                    "confirmed_in_region": GEMINI_MODEL_CONFIRMED_IN_REGION,
                    "remedy": (
                        "Change GEMINI_DEFAULT_LLM to a model this region serves, then "
                        "set GEMINI_MODEL_CONFIRMED_IN_REGION. Do NOT widen the region "
                        "and do NOT use locations/global — D-127 disqualifies both, and "
                        "check_model_residency will refuse the commit."
                    ),
                },
            )
            return
        log.warning(
            "vertex_request_refused",
            extra={"status": status, "model": self.model_name, "project": self._project},
        )

    async def run(self, spec: ExtractionSchemaSpec, transcript: str) -> dict[str, Any]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=EXTRACTION_TIMEOUT_S, follow_redirects=False
        )
        try:
            token = await access_token(client, self._account, scope=VERTEX_SCOPE)
            if token is None:
                # `google_oauth` already logged the status without the body. Raising a
                # ValueError puts this on `extract_call`'s error ladder, where a model
                # failure costs the structured fields and never the call — and keeps the
                # credential out of the traceback, which is the whole reason
                # `access_token` returns None instead of raising.
                raise ValueError("vertex_token_unavailable")
            response = await client.post(
                vertex_generate_url(self._project, self.model_name),
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "contents": [
                        {
                            "role": "user",
                            "parts": [{"text": build_extraction_prompt(spec, transcript)}],
                        }
                    ],
                    "generationConfig": {
                        "temperature": 0,
                        "responseMimeType": "application/json",
                        "responseSchema": build_vertex_response_schema(spec),
                    },
                },
            )
        finally:
            if owns_client:
                await client.aclose()
        if response.is_error:
            self._log_refusal(response.status_code)
        response.raise_for_status()
        body = response.json()
        self.last_usage = _vertex_usage(body)
        # Gemini returns `candidates: []` on a safety block — a documented, ordinary
        # response, not an exception. Same reasoning as the Sarvam path above.
        candidates = body.get("candidates") or []
        parts = (candidates[0].get("content", {}).get("parts") or []) if candidates else []
        text = str(parts[0].get("text", "")) if parts else ""
        # The response schema guarantees a JSON object, so this is `json.loads` and not
        # the fence-stripper. It still cannot be a bare `json.loads`: a safety block
        # produces no parts at all, and an empty string is not a document.
        if not text.strip():
            return {}
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}


@dataclass(frozen=True)
class _Mention:
    """One place the caller names a candidate value, and whether they stood by it.

    `order` is (turn, clause, offset within the clause) — the position of the words in
    the call. It is what turns "the caller's LAST word on it" into a comparison rather
    than a guess, and it is why a mention is a record and not a boolean.
    """

    order: tuple[int, int, int]
    value: str
    asserted: bool


#: Words in a field LABEL that describe the column rather than the thing the caller
#: talks about. "Callback requested" is a column; what a caller says is "callback".
#: Stripping them is what lets the probe be the WHOLE subject ("site visit") instead of
#: its first word ("site") — see `_subject_pattern`.
_LABEL_STATE_WORDS = frozenset(
    {
        "a",
        "agreed",
        "an",
        "booked",
        "concern",
        "confirmed",
        "consent",
        "flag",
        "given",
        "interest",
        "interested",
        "is",
        "needed",
        "preference",
        "raised",
        "request",
        "requested",
        "required",
        "status",
        "the",
        "want",
        "wanted",
        "wants",
        "was",
        "yes",
    }
)


def _always(value: str) -> Callable[[re.Match[str]], str]:
    """A `value_of` for the fields whose candidate value is fixed by the pattern that
    found it — an enum member, or the single subject of a bool."""
    return lambda _match: value


@lru_cache(maxsize=512)
def _word_pattern(phrase: str) -> re.Pattern[str]:
    """`phrase` as whole words, whitespace-flexible.

    Word boundaries, not substrings: substring matching made the enum value `other`
    match inside "brother" and `caller` match the speaker prefix on every line. `\\b`
    is avoided because enum values legitimately end in punctuation ("4BHK+"), where it
    would flip meaning; the explicit lookarounds do not.
    """
    words = phrase.split()
    joined = r"\s+".join(re.escape(word) for word in words)
    return re.compile(rf"(?<!\w){joined}(?!\w)", re.IGNORECASE)


@lru_cache(maxsize=512)
def _subject_pattern(label: str) -> re.Pattern[str] | None:
    """What a caller has to say for this bool field's SUBJECT to have been mentioned.

    The label is a column name of the shape "<subject> <state>": strip the state words
    and the whole remainder must be spoken. "Site visit" keeps both words, so "mee site
    address cheppandi" — a caller asking where the site is — no longer sets
    `site_visit_interest`; "Callback requested" keeps "callback", so the caller saying
    "callback kavali" still does.

    LIMIT, stated rather than hidden: a client whose label carries subject words the
    caller never speaks ("Site visit kavala") now captures nothing where the old
    first-word probe captured something. That direction is deliberate — a miss is
    `capture_miss` (waivable, a weaker reader), a wrong `true` is `restraint`/
    `capture_wrong` (never waivable, and it sends a sales team to meet nobody).
    """
    words = [w for w in re.findall(r"[\w']+", label.lower()) if w not in _LABEL_STATE_WORDS]
    if not words:
        # A label that is nothing but state words ("Interested?"). Fall back to its
        # first word rather than probing on the empty string, which would match every
        # turn ever spoken.
        words = re.findall(r"[\w']+", label.lower())[:1]
    if not words:
        return None
    return _word_pattern(" ".join(words))


class OfflineExtractor:
    """Deterministic, no network. Reads what the transcript literally says.

    It is not a stub: it implements the one rule the prompt insists on — never invent
    a value that was not said — so a schema field with no evidence comes back null and
    the pipeline's null-handling is exercised for real in local runs and CI.

    **Every field is decided by one scan** (`_mentions` + `_settled`), whatever its
    type: find each place the caller names a candidate value, drop the ones a negation
    or an enquiry in the same clause disqualifies, and let the caller's LAST word on
    each value decide whether it stands. Four separate defects — a denied enum filed
    anyway, a superseded requirement beating the one the caller settled on, a
    self-corrected name kept in its first version, a topic word read as a consent —
    were four faces of "the first thing that matched wins, and nothing later can
    revoke it". They are fixed once, here, so a fifth field type cannot reintroduce it
    by taking its own shortcut.

    **What this cannot see**, stated because an honest limit beats a claim of
    comprehension, and because the next reader will otherwise assume the scan
    understands more than it does:

    - a negation more than one clause away from what it negates ("3BHK kavali. Antha
      budget ledu andi." does not retract the size, and a bare "kaadu kaadu" clause
      retracts nothing by itself — `_settled`'s last-word rule covers the common
      correction shape instead);
    - irony, sarcasm, and a hypothetical ("2BHK aithe baagundedi");
    - a correction the caller makes in a LATER CALL — every scan here is one
      transcript, and reconciling a lead across calls is the CRM's job, not this one's;
    - a value the caller never speaks in the words the schema uses (Telugu numerals, a
      budget said as "yabhai lakshalu"), which stays a miss, as it was before;
    - the pronoun a correction hangs on: "adi kaadu, rendodi" ("not that one, the
      second") names no value this scan can match.
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
    # Negation triggers, Telugu · Hindi · English, word-bounded. A candidate value named
    # inside a clause that carries one of these is a caller REFUSING or RETRACTING the
    # thing, which is the opposite of the fact we would otherwise record.
    #
    # Word boundaries, not the substring test this list used to carry (which is why it
    # needed the trailing spaces in "no " and "not "): `no` sits inside half the English
    # lexicon and `not` inside "note", and a false negation DISCARDS a fact the caller
    # really stated.
    #
    # The cost of that choice, stated: Telugu also fuses negation into the verb
    # ("konaledu" = did not buy, "raledu" = did not come), and only the standalone forms
    # below are caught. A fused negation reads as an assertion of whatever else is in
    # the clause — which is why the list carries the standalone words a caller uses to
    # REFUSE or RETRACT, the two cases that put a wrong value in a client's CRM.
    _NEGATION_RE = re.compile(
        r"(?<!\w)(?:"
        r"ledu|ledhu|leedu|"  # "there is none" / "did not" — "avasaram ledu"
        r"vaddu|vaddhu|vaddandi|voddu|"  # "I don't want it"
        r"kaadu|kaadhu|kadu|"  # "it is not that" — the Telugu self-correction marker
        r"saripodu|saripodhu|saripoledu|"  # "that will not do"
        r"nahi|nahin|mat|"  # Hindi
        r"no|not|never|"
        r"don'?t|doesn'?t|didn'?t|won'?t|can'?t|cannot"
        r")(?!\w)"
        # The Telugu PROHIBITIVE is a suffix, not a word: "cheyakandi" (do not do it),
        # "ravaddu" (do not come), "cheyyoddu". Without this, "appointment cancel
        # cheyakandi" reads as a cancellation — the most expensive false positive in
        # the clinic vertical.
        r"|(?<!\w)\w+(?:akandi|akande|avaddu|oddu)(?!\w)",
        re.IGNORECASE,
    )
    # Clause boundaries — NegEx's "termination terms", as punctuation plus the two
    # contrastive conjunctions this product's transcripts actually use.
    # (dashes as escapes: a literal em/en dash in source is a lint-flagged homoglyph)
    _CLAUSE_SPLIT_RE = re.compile(
        "[,;.!?\u2026\u2014\u2013]+|\\s+(?:--|kaani|kani|but|however)\\s+", re.IGNORECASE
    )
    # "Did my booking get cancelled?" is not a cancellation. A caller who rings to ASK
    # about something says its name just as plainly as one who did it, so the word alone
    # cannot separate them — but the ASKING can be recognised, and that is a different
    # question with a real answer. The Telugu verb "to ask" is the `adag-`/`adug-` stem
    # (`adagataniki` = "in order to ask"), `telusuko-` is "to find out", and the English
    # equivalents follow.
    #
    # Deliberately verbs and not question marks: a transcript comes from an STT engine
    # that does not punctuate reliably, so a rule resting on "?" would work on the
    # fixtures and fail on production audio. Deliberately narrow, too — bare "check" is
    # left out because "I want to check in" is not an enquiry, and a false enquiry
    # DISCARDS a fact the caller really did state.
    _ASKING_RE = re.compile(
        r"(?<!\w)(?:adag\w*|adug\w*|telusuko\w*|ask\w*|enquir\w*|inquir\w*|wanted to know)(?!\w)",
        re.IGNORECASE,
    )
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

    @classmethod
    def _clauses(cls, turn: str) -> list[str]:
        """One turn split into the units a negation can reach across.

        This is the scope rule, and it is the one place worth departing from the
        established approach. NegEx (Chapman et al. 2001, and ConText after it) scopes a
        trigger over a fixed window — the current version, to the end of the SENTENCE
        unless a termination term ("but", "however") cuts it short — and its documented
        weakness is exactly that: with several candidate values inside one window it
        negates them all. That failure is not hypothetical here. "Manaki 3BHK ne kavali,
        2BHK saripodu" is one sentence holding both the requirement and its rejected
        alternative, and a sentence-wide scope files neither.

        So the scope is the CLAUSE: punctuation and a contrastive conjunction terminate
        it, as in NegEx, but they also START the next scope rather than merely ending
        the trigger's reach. What the departure buys is the clause above — the shape
        Telugu callers state a correction in — and it costs the ability to see a
        negation that sits in a clause of its own ("Iddaru... kaadu kaadu, muggurum"),
        which the last-word-wins rule in `_settled` covers instead.
        """
        return [clause.strip() for clause in cls._CLAUSE_SPLIT_RE.split(turn) if clause.strip()]

    @classmethod
    def _negated(cls, clause: str) -> bool:
        """Does this clause carry a negation trigger?

        Direction-blind, unlike NegEx's pre/post-trigger split, because this product is
        code-mixed: Telugu and Hindi are verb-final and negate AFTER the thing ("site
        visit vaddu", "2BHK saripodu"), English negates before it ("don't send"), and
        one clause here routinely holds both languages. Within a clause this short the
        direction carries no information the clause boundary does not already carry.
        """
        return cls._NEGATION_RE.search(clause) is not None

    @staticmethod
    def _asked_about(clause: str) -> bool:
        """Is this clause the caller ENQUIRING rather than stating?

        Clause-level, like `_negated`: the evidence and its qualifier live in one
        breath. "Naa booking cancel aipoyinda ani adagataniki call chesanu" is one
        clause — the matrix verb "adagataniki chesanu" governs the embedded complement
        inside it — so the word `cancel` never stands alone as a fact.

        It was turn-level until the scan below became the one path every field takes,
        and a turn-wide enquiry frame then swallowed the name in "Naa peru Naresh,
        doctor timings adagataniki chesanu": the caller enquired about the timings and
        STATED their name in the same turn. Both readings cannot be right, and the
        clause is the unit the qualifier actually attaches to.

        LIMIT: an enquiry frame that reaches across a comma into a later clause is not
        seen.
        """
        return OfflineExtractor._ASKING_RE.search(clause) is not None

    @classmethod
    def _mentions(
        cls,
        caller_turns: list[str],
        pattern: re.Pattern[str],
        value_of: Callable[[re.Match[str]], str],
    ) -> list[_Mention]:
        """Every place the caller names a candidate value, in the order they said it.

        The one scan behind every field type. `pattern` says what a mention looks like
        and `value_of` says which value that mention is about — a name, an enum member,
        or the single subject of a bool. Whether the caller MEANT it is decided here and
        only here: an enquiry in the clause means nothing in it was asserted at all, a
        negation in the clause means the value was asserted and then refused.

        The difference matters for `_settled`: an enquiry is not evidence either way, so
        it is skipped rather than recorded as a retraction — asking about a site visit
        neither books one nor cancels the one you agreed to a moment ago.
        """
        found: list[_Mention] = []
        for turn_index, turn in enumerate(caller_turns):
            for clause_index, clause in enumerate(cls._clauses(turn)):
                if cls._asked_about(clause):
                    continue
                asserted = not cls._negated(clause)
                for match in pattern.finditer(clause):
                    found.append(
                        _Mention(
                            order=(turn_index, clause_index, match.start()),
                            value=value_of(match),
                            asserted=asserted,
                        )
                    )
        return found

    @staticmethod
    def _settled(mentions: list[_Mention]) -> str | None:
        """The value the caller left standing, or None if they left none.

        THE property this extractor was missing, in four lines: for each candidate
        value the caller's LAST word on it decides whether it stands, and the field
        takes the last value still standing. Per-VALUE, deliberately — a caller
        rejecting 2BHK has not withdrawn the 3BHK they asked for in the same breath,
        while a caller who says "vaddu" about the one subject a bool field has really
        has withdrawn it.

        Nothing here can invent: with no mentions, or none that survived, the field is
        absent exactly as before.
        """
        latest: dict[str, _Mention] = {}
        for mention in sorted(mentions, key=lambda m: m.order):
            latest[mention.value] = mention
        standing = [m for m in latest.values() if m.asserted]
        return max(standing, key=lambda m: m.order).value if standing else None

    async def run(self, spec: ExtractionSchemaSpec, transcript: str) -> dict[str, Any]:
        caller_turns = self._caller_turns(transcript)
        caller_text = "\n".join(caller_turns)
        lowered = caller_text.lower()
        data: dict[str, Any] = {}

        for field in spec.fields:
            if field.type == "bool":
                probe = _subject_pattern(field.label)
                if probe is None:
                    continue
                # A bool has ONE candidate value, so every mention is about the same
                # thing and the caller's last word on it decides. True only when they
                # said it and left it standing; silence and a refusal both stay null,
                # because this extractor never invents a value that was not said and
                # "false" is a value.
                if self._settled(self._mentions(caller_turns, probe, _always("affirmed"))):
                    data[field.key] = True
                continue
            if field.key in ("name", "caller_name", "patient_name"):
                # Each spoken name is its own candidate value, so a caller who corrects
                # themselves ("naa peru Ravi, kaadu kaadu — naa peru Raviteja") is filed
                # under the correction rather than against it.
                name = self._settled(
                    self._mentions(
                        caller_turns, self._NAME_RE, lambda m: m.group(1).strip().title()
                    )
                )
                if name:
                    data[field.key] = name
                continue
            if field.type == "enum" and field.enum_values:
                mentions = [
                    mention
                    for enum_value in field.enum_values
                    for mention in self._mentions(
                        caller_turns, _word_pattern(enum_value), _always(enum_value)
                    )
                ]
                value = self._settled(mentions)
                if value:
                    data[field.key] = value

        all_lines = [ln for ln in transcript.splitlines() if ln.strip()]
        return {
            **data,
            # A TRANSCRIPT LINE, VERBATIM — speaker prefix and all. That is honest for a
            # deterministic baseline ("reads what the transcript literally says") and it
            # is why `calls.summary` is treated as transcript-derived text on every exit
            # rather than as a safely abstracted field: the API read path redacts it
            # (`crm.service.redacted_summary`), the outbound webhook redacts it
            # (`workers/pipeline`), the hot-lead notification redacts it
            # (`notifications._compose`) and the DPDP export masks foreign numbers out of
            # it (`compliance/export`). Making this abstractive would NOT retire any of
            # those: the model path writes free prose that can quote a number the caller
            # read out, and every summary already stored would keep whatever it holds.
            "summary": (all_lines[-1][:200] if all_lines else "No transcript available."),
            "sentiment": "negative" if any(w in lowered for w in self._NEGATIVE) else "neutral",
            "outcome_tag": (
                "needs_follow_up" if any(w in lowered for w in self._CALLBACK) else "resolved"
            ),
            "out_of_scope": False,
            "callback_requested": any(w in lowered for w in self._CALLBACK),
        }


def get_extractor() -> Extractor:
    """The FIRST post-call extraction's runner. Sarvam, or the offline baseline.

    There is no silent failover between providers, because they differ on data residency
    and that is not a runtime decision — the principle this docstring has always stated,
    now with the branch that contradicted it removed.

    GEMINI IS NOT REACHABLE FROM HERE (D-127 G-2/G-7). This function used to return
    `GeminiExtractor` when a Gemini key was configured and a Sarvam key was not. The
    caller is `workers/pipeline.py`, which hands over the RAW transcript because a
    "callback number" field needs the actual digits — so that branch sent raw caller PII
    to Google whenever one environment variable was absent. `GEMINI_EXTRACTION_DEFAULT is
    False` is that decision as a fact the tree can be asked about; `run_assist()` is where
    Gemini serves, over the redacted copy, at a user's request.

    THE CONSEQUENCE, STATED RATHER THAN DISCOVERED: a deployment holding only a Google
    credential now extracts with `OfflineExtractor` instead of Gemini. That is the
    intended direction — a deterministic reader that files what the transcript literally
    says is a smaller loss than a residency inversion — and it is not a state any
    environment is in: `runtime_config_missing_keys` has required `SARVAM_API_KEY`
    outside `local` since before D-127, so `/healthz/ready` is already red there.
    """
    settings = get_settings()
    if settings.sarvam_api_key:
        return SarvamExtractor(settings.sarvam_api_key)
    return OfflineExtractor()


# --- G-6: one place decides what happens when Gemini cannot serve -----------------
#
# PLAN Part 15. Every reason code below is AUTHORED — it names OUR configuration state,
# never a vendor's error string, because these reach an alert, a client's screen and a
# support conversation.

#: No Google credential on this deployment: no project id, no service-account key, or a
#: key that does not parse. The ordinary state today — no GCP project exists yet.
NO_CREDENTIAL_REASON: Final = "no_credential"
#: The tenant is past its included monthly assist quota and has not accepted the charge
#: (G-5). Supplied BY THE CALLER — see `assist_capability`.
QUOTA_EXHAUSTED_REASON: Final = "quota_exhausted"
#: Vertex answered badly, or did not answer. Discovered by trying, so also supplied by
#: the caller after a failed attempt.
PROVIDER_UNAVAILABLE_REASON: Final = "provider_unavailable"
#: A deployment that installed `GEMINI_API_KEY` and expected dashboard AI to work. D-127
#: disqualified the door that key opens, so this is `no_credential` with the sentence the
#: operator actually needs instead of the one that would send them to check their typing.
AI_STUDIO_KEY_REASON: Final = "ai_studio_key_disqualified"

#: Provider names as they appear in a disclosure and in a log line.
GEMINI_PROVIDER: Final = "gemini"
SARVAM_PROVIDER: Final = "sarvam"

#: Is a per-tenant assist quota enforced on a path a client can reach? YES, since D-146.
#:
#: This constant spent its whole life False and the paragraph under it moved twice, which
#: is the argument for having minted it. D-137 built the ceiling (`require_ai_assist`),
#: the idempotent writer (`record_ai_assist_usage`), the brake on our own key
#: (`platform_ai_spend`) and the audited acceptance (`POST /v1/billing/ai-quota/extra`);
#: D-142 added this module's two ends of the wire, `run_assist(quota_exhausted=…)` and
#: `AssistResult.usage`. Every piece worked and nothing was enforced, because no route
#: joined them — the state a greppable boolean exists to stop a document describing as
#: "quota enforcement".
#:
#: `POST /v1/calls/{call_id}/assist` (`apps/api/crm/routes.py::assist_call`) is the middle.
#: It calls `require_ai_assist` BEFORE the provider is paid, hands the verdict to
#: `run_assist`, and meters `AssistResult.usage` back through `crm/assist.py::meter_assist`
#: — the three lines this comment named as its own closing condition, in that order.
#:
#: What True does NOT claim, because the next reader will ask: an assist whose token count
#: Vertex did not return is money spent that no ceiling can see. It is refused a ledger row
#: rather than given a fabricated one, and it fires `ai_assist_unmeterable` so an operator
#: learns the meter stopped. Enforcement is real; it is not omniscient.
ASSIST_QUOTA_ENFORCED: Final = True

#: What each fallback reason means, in the words the client reads. One sentence per code,
#: written once: a disclosure composed at each surface is a disclosure that eventually
#: says something different on two screens about the same event.
_FALLBACK_DISCLOSURE: Final[dict[str, str]] = {
    NO_CREDENTIAL_REASON: (
        "This was written by Sarvam, not the assistant model, because no Google Cloud "
        "credential is configured on this deployment."
    ),
    AI_STUDIO_KEY_REASON: (
        "This was written by Sarvam, not the assistant model, because this deployment's "
        "Google credential is not one the assistant can use."
    ),
    QUOTA_EXHAUSTED_REASON: (
        "This was written by Sarvam, not the assistant model, because this month's "
        "included assistant usage is used up."
    ),
    PROVIDER_UNAVAILABLE_REASON: (
        "This was written by Sarvam, not the assistant model, because the assistant model "
        "did not answer."
    ),
}


@dataclass(frozen=True, slots=True)
class AssistCapability:
    """What this deployment can actually do about user-triggered AI, as one answer.

    `PaymentCapability`'s shape, for `PaymentCapability`'s reason: a caller must not be
    able to conclude "the assistant works" and then separately assume "so it is Gemini
    answering". Both facts are one lookup and one object.

    `reason` is non-None exactly when `available` is False. `fallback_reason` is non-None
    exactly when `provider` is not the preferred one — and when it is set, `disclosure`
    is the sentence that MUST travel with the answer, in the response and on the screen
    (G-6). A fallback nobody is told about silently changes output quality, which is the
    single outcome that decision rules out.
    """

    available: bool
    provider: str | None = None
    reason: str | None = None
    fallback_reason: str | None = None

    @property
    def disclosure(self) -> str | None:
        """The sentence to show beside a fallback answer, or None when there was none."""
        if self.fallback_reason is None:
            return None
        return _FALLBACK_DISCLOSURE.get(self.fallback_reason)


def vertex_credentials() -> tuple[ServiceAccount, str] | None:
    """The service account and project for Vertex, or None if this deployment has neither.

    THE ONLY read of `gcp_service_account_json`. The key is parsed here, once, so a
    malformed one is a named refusal on the screen that asked rather than a parse failure
    inside a request whose next log line would print it (`parse_service_account` returns
    None rather than raising for that reason).
    """
    settings = get_settings()
    project = (settings.gcp_project_id or "").strip()
    raw = settings.gcp_service_account_json or ""
    if not project or not raw:
        return None
    account = parse_service_account(raw)
    if account is None:
        # Present but unreadable is an operator error and must not be reported as
        # "unconfigured", which would send them to install a key they already installed.
        log.error("vertex_credential_unparseable", extra={"project": project})
        return None
    return account, project


def vertex_extractor(model: str = GEMINI_DEFAULT_LLM) -> VertexGeminiExtractor | None:
    """A ready Vertex extractor for this deployment, or None if it holds no credential.

    ONE constructor, so nothing outside this module has to know that "the Vertex client"
    is two configuration values rather than one. `scripts/eval.py`'s provider table wants
    exactly this: every other provider it scores is built from a single credential string,
    and Vertex is not — a project id and a service-account key, neither of which is
    optional. A caller that assembled them itself would be the second place that decides
    what "configured" means, and the first place is `vertex_credentials()`.
    """
    credentials = vertex_credentials()
    if credentials is None:
        return None
    account, project = credentials
    return VertexGeminiExtractor(account, project, model)


def assist_capability(
    *, quota_exhausted: bool = False, provider_unavailable: bool = False
) -> AssistCapability:
    """THE selector (D-127 G-6). Every user-triggered AI surface asks this and nothing
    re-reads settings for itself.

    THE LADDER, and each rung is a decision rather than a check:

    1. **Gemini serves it** when a credential resolves, the tenant is inside its quota and
       the provider has not just failed. This is the preferred answer and carries no
       disclosure, because nothing was substituted.
    2. **Sarvam serves it, disclosed**, when Gemini cannot. A fallback is honest here:
       both are instruction-following LLMs over the same redacted text, and the difference
       is quality, not correctness — so the answer stands and the client is told whose it
       is. `OfflineExtractor` is deliberately NOT in this ladder: it is a deterministic
       reader of literal transcript text, and offering its output as "your re-summarised
       call" would be substituting a different KIND of thing while claiming to substitute
       a model.
    3. **Refuse**, with the reason that stopped Gemini, when there is no Sarvam key
       either. `assist_unavailable()` turns that into a message with a remediation.

    `quota_exhausted` and `provider_unavailable` are ARGUMENTS rather than reads. Neither
    is knowable from configuration: the first is a per-tenant month-to-date sum that
    `usage_events` owns (`require_ai_assist`, reached through `crm/routes.py::assist_call`),
    and the second is only knowable by having just tried. Passing them in keeps this
    function a pure function of its inputs, which is what lets one test drive all six
    states without a database.
    """
    settings = get_settings()
    credentials = vertex_credentials()

    blocked: str | None = None
    if quota_exhausted:
        # Checked FIRST, and before credentials, because it is the one a user can act on:
        # a client at their ceiling needs the modal (G-5), not "no credential configured".
        blocked = QUOTA_EXHAUSTED_REASON
    elif provider_unavailable:
        blocked = PROVIDER_UNAVAILABLE_REASON
    elif credentials is None:
        blocked = AI_STUDIO_KEY_REASON if settings.gemini_api_key else NO_CREDENTIAL_REASON

    if blocked is None:
        return AssistCapability(available=True, provider=GEMINI_PROVIDER)
    if settings.sarvam_api_key:
        return AssistCapability(available=True, provider=SARVAM_PROVIDER, fallback_reason=blocked)
    return AssistCapability(available=False, reason=blocked)


def assist_unavailable(capability: AssistCapability) -> ProblemError:
    """The refusal a user meets when nothing can serve. Never a bare 500, never a spinner.

    `remediation` is what SEC-COMP calls the actionable half and what `ProblemNotice`
    renders verbatim on the screen, so it is written for the person who will read it:
    a client can act on "top up" and cannot act on "configure a service account", so the
    two reasons get different sentences even though both are the same HTTP status.
    """
    reason = capability.reason or NO_CREDENTIAL_REASON
    remediation = {
        QUOTA_EXHAUSTED_REASON: (
            "This month's included AI assistance is used up. Add credit, or wait for the "
            "next billing month."
        ),
        PROVIDER_UNAVAILABLE_REASON: (
            "The assistant model did not answer and this deployment has no second model "
            "configured. Try again in a few minutes; if it persists, contact support."
        ),
        AI_STUDIO_KEY_REASON: (
            "This deployment has a Gemini API key, which reaches the AI Studio Developer "
            "API — an endpoint D-127 disqualifies because it offers no India data "
            "residency. Install GCP_PROJECT_ID and GCP_SERVICE_ACCOUNT_JSON for Vertex AI "
            "asia-south1 instead (DEV-SETUP §4)."
        ),
    }.get(
        reason,
        "No AI provider is configured on this deployment. Install a Vertex AI service "
        "account (GCP_PROJECT_ID + GCP_SERVICE_ACCOUNT_JSON) or a Sarvam API key "
        "(DEV-SETUP §4).",
    )
    return ProblemError(
        kind="dependency",
        code=f"assist_{reason}",
        title="AI assistance is not available",
        detail="This deployment cannot run the AI assistant right now.",
        remediation=remediation,
    )


@dataclass(frozen=True, slots=True)
class AssistResult:
    """One user-triggered assist: what came back, who wrote it, and what it cost.

    `usage` is non-None only for a GEMINI answer that Vertex counted — the leg that
    spends Calevate's rupees and the only one `record_ai_assist_usage` (D-137) has units
    for. A Sarvam fallback leaves it None because D-36 prices that leg at zero, and a
    Gemini answer whose `usageMetadata` did not arrive leaves it None because "we do not
    know" and "it was free" must not meter the same.
    """

    output: ExtractionOutput
    capability: AssistCapability
    usage: TokenUsage | None = None


async def run_assist(
    spec: ExtractionSchemaSpec, redacted_transcript: str, *, quota_exhausted: bool = False
) -> AssistResult:
    """Run ONE user-triggered assist over REDACTED call text (D-127 G-2, G-6, G-7).

    THE INPUT GUARD IS THE POINT, and it is structural rather than documentary. G-2 says
    this leg never sees raw PII; a parameter named `redacted_transcript` is a promise, and
    a promise is what `pipeline.py:750` broke by accident the last time two nearly
    identical strings sat one line apart. So the text is re-run through `redact()` and
    REFUSED if that pass still finds something — the caller must hand over
    `transcript_turns.text_redacted`, not `text`. This costs one regex sweep per assist
    and removes the whole class.

    THE REFUSAL WAS UNREACHABLE UNTIL D-146, and the paragraph that said so is worth
    keeping in its corrected form rather than deleting. This guard was written BEFORE any
    caller existed, for `check_model_residency`'s reason — the mistake it catches is one
    line of a route handler that nobody would re-read, and the moment to make it
    impossible is before the handler exists rather than after it ships.

    That bet paid immediately. `crm/routes.py::assist_call` is now the caller, and the
    sabotage that swaps `text_redacted` for `text` in `crm/assist.py`'s one SQL string
    does not first fail an assertion about bytes — it fails HERE, with
    `assist_input_not_redacted`, from inside the function the route calls. The guard
    catches the exact mistake its author predicted, in the exact place predicted.

    THE FALLBACK IS DISCLOSED, NEVER SILENT. Gemini failing mid-flight re-asks the ONE
    selector with `provider_unavailable=True` rather than deciding locally, so a surface
    can never grow its own idea of what a failure means; the answer that comes back
    carries `capability.disclosure`, which the response and the screen must show.

    IT STILL DOES NOT METER OR CHARGE — `billing/ai_quota.py` owns both (D-137) — but it
    is now WIRED to the half that decides. `quota_exhausted` is the verdict of
    `require_ai_assist`, passed IN rather than read here, because the answer needs a
    session and a tenant and this module has neither; without the parameter the ceiling
    D-137 built could not reach the one function that runs an assist, which is a gate
    with no door. What it returns is the other half: `AssistResult.usage` is what
    `record_ai_assist_usage` needs for `tokens_in`/`tokens_out`, in Vertex's own count.
    Money stays outside a model adapter; the numbers money is computed from come from it,
    because nowhere else can see them.
    """
    if redact(redacted_transcript).changed:
        # An authored refusal, not an assertion: this is reachable by a caller mistake and
        # a caller mistake deserves a message. Nothing about the text is logged.
        raise ProblemError(
            kind="validation",
            code="assist_input_not_redacted",
            title="This text has not been redacted",
            detail="AI assistance runs on redacted call text only.",
            remediation=(
                "Pass `transcript_turns.text_redacted` (or `calls.summary` after "
                "`crm.service.redacted_summary`), never the raw turn text."
            ),
        )

    capability = assist_capability(quota_exhausted=quota_exhausted)
    if not capability.available:
        raise assist_unavailable(capability)

    if capability.provider == GEMINI_PROVIDER:
        credentials = vertex_credentials()
        if credentials is not None:
            account, project = credentials
            extractor = VertexGeminiExtractor(account, project)
            output = await extract_call(spec, redacted_transcript, extractor=extractor)
            failure = output.errors.get("_model")
            if failure is None:
                # A schema-invalid FIELD is still an answer (`valid=False`, per-field
                # errors) and belongs to the client to see. Only `_model` — the ladder's
                # code for "the provider did not give us anything" — is a provider event.
                return AssistResult(
                    output=output, capability=capability, usage=extractor.last_usage
                )
            # `extract_call` swallows a provider failure into `errors["_model"]` so a
            # post-call pipeline never loses a call over one. Here the user is waiting
            # and the answer is empty, so the same event means something different: ask
            # the ONE selector again, with the fact we now have, rather than deciding
            # locally what a Gemini outage means.
            log.warning(
                "assist_provider_failed",
                extra={"model": extractor.model_name, "error": failure},
            )
        # `quota_exhausted` is re-stated rather than dropped: it cannot be True here
        # today (the ladder blocks on it first, so this branch is unreachable with it
        # set), and a re-ask that silently forgot an input would become wrong the moment
        # somebody reorders those rungs.
        capability = assist_capability(quota_exhausted=quota_exhausted, provider_unavailable=True)
        if not capability.available:
            raise assist_unavailable(capability)

    settings = get_settings()
    # Reachable only with `sarvam_api_key` set — `assist_capability` returns
    # `provider="sarvam"` on no other condition — but mypy cannot see that through the
    # capability object, and an `assert` here would be a crash where a refusal belongs.
    if not settings.sarvam_api_key:  # pragma: no cover - unreachable via the selector
        raise assist_unavailable(AssistCapability(available=False, reason=NO_CREDENTIAL_REASON))
    output = await extract_call(
        spec, redacted_transcript, extractor=SarvamExtractor(settings.sarvam_api_key)
    )
    return AssistResult(output=output, capability=capability)


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
    "AI_STUDIO_KEY_REASON",
    "ASSIST_QUOTA_ENFORCED",
    "GEMINI_EXTRACTION_DEFAULT",
    "GEMINI_PROVIDER",
    "NO_CREDENTIAL_REASON",
    "PROVIDER_UNAVAILABLE_REASON",
    "QUOTA_EXHAUSTED_REASON",
    "SARVAM_PROVIDER",
    "VERTEX_SCOPE",
    "AssistCapability",
    "AssistResult",
    "Extractor",
    "OfflineExtractor",
    "SarvamExtractor",
    "TokenUsage",
    "VertexGeminiExtractor",
    "assist_capability",
    "assist_unavailable",
    "build_vertex_response_schema",
    "extract_call",
    "get_extractor",
    "run_assist",
    "vertex_credentials",
    "vertex_extractor",
    "vertex_generate_url",
]
