"""The extraction schema — one definition that drives six things (TRD §7).

From a single per-agent field list we get, with zero per-client code:
(a) the post-call extraction prompt, (b) validation of the model's structured output,
(c) the Leads table columns, (d) the filters, (e) CSV export, (f) hot-lead rules.

That is the product core, so the schema type lives in `shared`: `api` validates it on
write, `workers` render prompts from it, and the frontend reads the same shape through
the generated client. Three copies of "what a field is" would be three ways to drift.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

FieldType = Literal["text", "number", "bool", "enum", "date"]
OutcomeTag = Literal["resolved", "needs_follow_up", "transferred", "dropped"]
Sentiment = Literal["positive", "neutral", "negative"]

#: The speaker labels the pipeline actually writes — `TranscriptTurn.speaker` is
#: `Literal["agent", "caller"]` and `_persist_transcript` renders `f"{speaker}: {text}"`.
#: A model copying the transcript's own formatting into a value is a real failure mode,
#: and "caller" is a person nobody can ring.
SPEAKER_LABELS = frozenset({"agent", "caller", "assistant", "bot", "customer", "user", "speaker"})
_SPEAKER_PREFIX_RE = re.compile(rf"^\s*({'|'.join(sorted(SPEAKER_LABELS))})\s*:\s*", re.IGNORECASE)

#: What a model says when it will not say null. Stored literally these become callers
#: named "Unknown" and callback times of "N/A" — fabricated rows that read as captured,
#: which is worse than an empty column because the client acts on them.
_NULL_PLACEHOLDERS = frozenset(
    {
        "-",
        "--",
        "?",
        "n/a",
        "na",
        "n.a.",
        "nil",
        "none",
        "null",
        "nan",
        "tbd",
        "undefined",
        "unspecified",
        "unknown",
        "not applicable",
        "not available",
        "not given",
        "not mentioned",
        "not provided",
        "not specified",
        "not stated",
        "no value",
        # Telugu/Hindi for "not known" / "did not say" — the same refusal in the
        # language this product is actually spoken in.
        "teliyadu",
        "cheppaledu",
        "pata ledu",
        "maalum nahi",
    }
)

#: Ten or more digits, however the model chose to punctuate them (`+91 99999-99999`).
#: Below ten it is a party size, an age, a flat number; at ten it is somebody's phone.
_PHONE_SHAPED_RE = re.compile(r"\d(?:[\s\-().+]*\d){9,}")

#: Words in a field's key/label/description that mean "a phone number belongs here".
_PHONE_FIELD_HINTS = ("number", "phone", "mobile", "cell", "whatsapp", "contact")

#: A text answer longer than this is not an answer; it is the model pasting the call
#: back at us — unredacted transcript text heading for a CRM column (hard rule 5).
MAX_TEXT_LEN = 500


class ExtractionField(BaseModel):
    model_config = {"extra": "forbid"}

    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    label: str
    type: FieldType
    enum_values: list[str] | None = None
    # "What to listen for" — this text IS the instruction the model gets, so it is
    # product copy, not a comment.
    description: str = ""
    required: bool = False

    @field_validator("enum_values")
    @classmethod
    def _enum_needs_values(cls, v: list[str] | None, info: Any) -> list[str] | None:
        if info.data.get("type") == "enum" and not v:
            raise ValueError("enum fields must define enum_values")
        return v


class ExtractionSchemaSpec(BaseModel):
    """Ordered field list + the version it was published as. Leads render by the
    version active AT EXTRACTION TIME, so editing a schema never rewrites history."""

    model_config = {"extra": "forbid"}

    version: int = 1
    fields: list[ExtractionField]

    @field_validator("fields")
    @classmethod
    def _unique_keys(cls, v: list[ExtractionField]) -> list[ExtractionField]:
        keys = [f.key for f in v]
        if len(keys) != len(set(keys)):
            raise ValueError("field keys must be unique within a schema")
        return v

    def field_by_key(self, key: str) -> ExtractionField | None:
        return next((f for f in self.fields if f.key == key), None)


class ExtractionOutput(BaseModel):
    """What one extraction pass returns. The custom fields live in `data`; everything
    else is the fixed analysis every call gets regardless of schema (TRD §7)."""

    model_config = {"extra": "forbid"}

    data: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    sentiment: Sentiment = "neutral"
    outcome_tag: OutcomeTag = "resolved"
    out_of_scope: bool = False
    callback_requested: bool = False
    valid: bool = True
    errors: dict[str, str] = Field(default_factory=dict)


class ValidationOutcome(BaseModel):
    data: dict[str, Any]
    errors: dict[str, str]

    @property
    def valid(self) -> bool:
        return not self.errors


def _is_phone_field(field: ExtractionField) -> bool:
    """Does this field ASK for a phone number? Read from the schema the client wrote —
    key, label and the description that already doubles as the model's instruction."""
    haystack = f"{field.key} {field.label} {field.description}".lower()
    return any(hint in haystack for hint in _PHONE_FIELD_HINTS)


def coerce_value(field: ExtractionField, raw: Any) -> tuple[Any, str | None]:
    """Coerce one model-produced value to the field's type. Returns (value, error).

    A model asked for a number will happily answer "about 5000 rupees"; a client's
    Leads column has to hold a number. Coercion here beats a retry loop for the common
    cases and reports the rest as a field error instead of poisoning the column.

    What this can and cannot check. It checks SHAPE and SAFETY: the type, the enum
    membership, that a value is a single scalar, that it is not a placeholder standing
    in for null, that it is not a speaker label, and that a phone number only lands in
    a field that asked for one. It deliberately does NOT check that the value appears
    in the transcript — on this product the correct answer usually does not appear
    verbatim (`party_size` 3 comes from "muggurum"; a callback number comes from
    "tommidi tommidi ..."), so a presence check would reject correct answers and
    downgrade them to a *waivable* missing field. Fabrication is gated by the prompt's
    speaker/denial/null rules and by `scripts/eval.py`, where inventing a field
    (`restraint`) or filing a wrong one (`capture_wrong`) is unwaivable on every model.
    """
    if raw is None or raw == "":
        return None, None
    # A list or an object is never a field value. `str()` turned `["book"]` into the
    # literal text "['book']" and `{"first": "Ravi"}` into Python source, both of which
    # a client then reads on their Leads screen.
    if isinstance(raw, (list, tuple, set, dict)):
        return None, f"expected a single value for {field.label}, got {type(raw).__name__}"
    if isinstance(raw, str):
        # Strip the transcript's own speaker prefix: "caller: Kiran" is the right answer
        # with the formatting stuck to it, and filing it raw shows `caller: Kiran`.
        stripped = _SPEAKER_PREFIX_RE.sub("", raw).strip()
        bare = stripped.lower().strip(" .-?")
        if stripped.lower() in _NULL_PLACEHOLDERS or bare in _NULL_PLACEHOLDERS or not bare:
            # The model saying "absent" in prose. That is null, not a validation
            # failure — and a required field still reports the miss downstream.
            return None, None
        if stripped.lower() in SPEAKER_LABELS:
            return None, f"{stripped!r} is a speaker label, not a value for {field.label}"
        if not stripped:
            return None, None
        raw = stripped
    try:
        if field.type == "text":
            if isinstance(raw, bool):
                return None, f"expected text for {field.label}, got a boolean"
            value = str(raw).strip()
            if len(value) > MAX_TEXT_LEN:
                return None, (
                    f"{field.label}: {len(value)} characters is a transcript, not a value"
                )
            if not _is_phone_field(field) and _PHONE_SHAPED_RE.search(value):
                # Right value, wrong column: a phone number in the name field is PII
                # nobody redacts and a name nobody has.
                return None, f"{field.label} does not hold phone numbers"
            return value, None
        if field.type == "number":
            if isinstance(raw, bool):
                return None, "expected a number, got a boolean"
            cleaned = str(raw).replace(",", "").strip()
            digits = "".join(c for c in cleaned if c.isdigit() or c in ".-")
            if not digits or digits in ("-", "."):
                return None, f"could not read a number from {field.label}"
            return float(digits) if "." in digits else int(digits), None
        if field.type == "bool":
            if isinstance(raw, bool):
                return raw, None
            token = str(raw).strip().lower()
            if token in ("true", "yes", "y", "1", "avunu", "ha"):
                return True, None
            if token in ("false", "no", "n", "0", "kadu", "ledu"):
                return False, None
            return None, f"could not read yes/no from {field.label}"
        if field.type == "enum":
            token = str(raw).strip()
            allowed = field.enum_values or []
            match = next((a for a in allowed if a.lower() == token.lower()), None)
            if match is None:
                return None, f"{token!r} is not one of {allowed}"
            return match, None
        if field.type == "date":
            parsed = date.fromisoformat(str(raw).strip()[:10])
            return parsed.isoformat(), None
    except (ValueError, TypeError) as exc:
        return None, f"{field.label}: {exc}"
    # No fallthrough: `FieldType` is a closed Literal and every member is handled
    # above, so mypy proves this point unreachable. Adding a member to `FieldType`
    # without handling it here is therefore a TYPE error, not a silent None.
    raise AssertionError(f"unhandled field type {field.type}")


def validate_extraction(spec: ExtractionSchemaSpec, raw: dict[str, Any]) -> ValidationOutcome:
    """Validate + coerce a model's output against the schema.

    Unknown keys are DROPPED rather than errored: a chatty model inventing a field must
    not fail an otherwise good extraction, and a dropped key is visible in the diff
    between prompt and output during regression runs.
    """
    data: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for field in spec.fields:
        value, error = coerce_value(field, raw.get(field.key))
        if error:
            errors[field.key] = error
            continue
        if value is None and field.required:
            errors[field.key] = f"{field.label} is required but was not captured"
            continue
        if value is not None:
            data[field.key] = value
    return ValidationOutcome(data=data, errors=errors)


def build_extraction_prompt(spec: ExtractionSchemaSpec, transcript: str) -> str:
    """Generate the extraction instruction. Kept in `shared` so the regression harness
    scores the SAME prompt the pipeline uses (OPERATIONS §3)."""
    lines: list[str] = []
    for field in spec.fields:
        constraint = ""
        if field.type == "enum" and field.enum_values:
            constraint = f" (one of: {', '.join(field.enum_values)})"
        elif field.type == "date":
            constraint = " (ISO date, YYYY-MM-DD)"
        elif field.type == "bool":
            constraint = " (true or false)"
        elif field.type == "number":
            constraint = " (a number only)"
        requirement = "REQUIRED" if field.required else "optional"
        hint = f" — {field.description}" if field.description else ""
        lines.append(f'- "{field.key}": {field.label}{constraint} [{requirement}]{hint}')

    return f"""You are extracting structured data from a phone call transcript.
The call is in Telugu, often code-mixed with English or Hindi, and it may arrive in
native Telugu script. Do not translate; extract.

Return ONLY a JSON object with these keys:

{chr(10).join(lines)}

Also include:
- "summary": two sentences, in English, of what the caller wanted and what happened.
- "sentiment": one of positive, neutral, negative.
- "outcome_tag": one of resolved, needs_follow_up, transferred, dropped.
- "out_of_scope": true if the caller asked about something the agent could not handle.
- "callback_requested": true if the caller asked to be called back.

WHO SPOKE DECIDES WHAT IS A FACT.
The transcript is one turn per line, and every line is labelled with the speaker:
  "agent:"  — our AI receptionist, OUR side of the call.
  "caller:" — the human this record is about.
- Every field above is a fact about the CALLER, so only `caller:` lines are evidence.
- An `agent:` line is a question, an offer, a menu of options or a read-back, and none
  of those is an answer. "Mee peru cheppandi" is a question asking for a name; it is
  not an answer and there is no name in it. "Book cheyala leda cancel cheyala?" is the
  agent listing options; it is not the caller's intent.
- The agent repeating a value back does not confirm it. The caller must have said it.
- Never copy a speaker label ("caller", "agent") into a value.
- If the transcript has no speaker labels at all, answer only where the caller's own
  words are unmistakable.

A DENIAL IS NOT A CONFIRMATION.
- "ledu", "vaddu", "kaadu", "avasaram ledu", "nahi", "no", "don't" in answer to a
  question mean the caller REFUSED that thing.
- For a true/false field a denial is false — never true.
- For every other field a denial means there is no value: use null.
- A word that appears only inside a refusal is not the answer either.

ABSENT MEANS NULL.
- If a value was not stated, use null. NEVER guess, infer, assume or complete a value
  that was not said, however likely the rest of the call makes it.
- Never write "N/A", "unknown", "not provided", "none" or "-" as a value. That is null.
- A wrong-number call, an angry caller who states no details, and a silent call are
  almost entirely null. That is a CORRECT extraction, not a failed one.
- The business acts on this record instead of listening to the call, so an empty field
  is safe and a wrong field is not.

WHOSE IS IT.
- A name, number or detail belonging to somebody else — a relative, a family member, a
  colleague — is not the caller's own. Put it in the field that asks for it, and say
  whose it is only if the caller said whose it is.

VALUES, EXACTLY.
- Quote the caller. Keep a name in the script it was spoken in, and keep a relative
  time in the caller's own words ("kal subah", "repu udayam"). Do not resolve it into
  a date or a timestamp.
- A number read aloud as words — "tommidi tommidi ...", "nine eight seven ..." — is
  written as digits in the order spoken, nothing added and nothing dropped. If even one
  digit is unclear, use null: a phone number one digit wrong is the worst output this
  system can produce.
- Put a phone number only in a field that asks for a phone number.
- An enum field takes EXACTLY one of its listed values, copied verbatim, and only when
  the caller meant that value — not because the word appears inside another word ("other"
  inside "brother"). If none of them fits, use null.
- Numbers are bare numbers, true/false fields are true or false, dates are YYYY-MM-DD.
- Do not include any key that is not listed above, and return only the JSON object.

Transcript:
{transcript}
"""


__all__ = [
    "ExtractionField",
    "ExtractionOutput",
    "ExtractionSchemaSpec",
    "FieldType",
    "OutcomeTag",
    "Sentiment",
    "ValidationOutcome",
    "build_extraction_prompt",
    "coerce_value",
    "validate_extraction",
]
