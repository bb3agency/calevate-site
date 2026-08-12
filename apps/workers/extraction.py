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

**Scoring the model path.** The regression harness already runs against whatever
`get_extractor()` returns and keys its baseline by `model_name`, so scoring Sarvam or
Gemini against the golden transcripts needs no flag and no new mode — it is

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
