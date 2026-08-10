"""The extraction schema — one definition that drives six things (TRD §7).

From a single per-agent field list we get, with zero per-client code:
(a) the post-call extraction prompt, (b) validation of the model's structured output,
(c) the Leads table columns, (d) the filters, (e) CSV export, (f) hot-lead rules.

That is the product core, so the schema type lives in `shared`: `api` validates it on
write, `workers` render prompts from it, and the frontend reads the same shape through
the generated client. Three copies of "what a field is" would be three ways to drift.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

FieldType = Literal["text", "number", "bool", "enum", "date"]
OutcomeTag = Literal["resolved", "needs_follow_up", "transferred", "dropped"]
Sentiment = Literal["positive", "neutral", "negative"]


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


def coerce_value(field: ExtractionField, raw: Any) -> tuple[Any, str | None]:
    """Coerce one model-produced value to the field's type. Returns (value, error).

    A model asked for a number will happily answer "about 5000 rupees"; a client's
    Leads column has to hold a number. Coercion here beats a retry loop for the common
    cases and reports the rest as a field error instead of poisoning the column.
    """
    if raw is None or raw == "":
        return None, None
    try:
        if field.type == "text":
            return str(raw).strip(), None
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
The call is in Telugu, often code-mixed with English. Do not translate; extract.

Return ONLY a JSON object with these keys:

{chr(10).join(lines)}

Also include:
- "summary": two sentences, in English, of what the caller wanted and what happened.
- "sentiment": one of positive, neutral, negative.
- "outcome_tag": one of resolved, needs_follow_up, transferred, dropped.
- "out_of_scope": true if the caller asked about something the agent could not handle.
- "callback_requested": true if the caller asked to be called back.

Rules:
- If a value was not stated, use null. NEVER guess or infer a value that was not said.
- Do not include any key that is not listed above.

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
