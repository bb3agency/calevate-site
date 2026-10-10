"""The lead details every business gets, and how they combine with a business's own.

A lead's captured details come in two halves (founder decision 15, 10 Oct 2026):

* **The core** — a fixed set every business captures on every call, whatever it sells:
  who called, what they want, when, another number, the language and anything else worth
  a note. What happens next is not a field: the extraction pass writes it for every call
  as `ExtractionOutput.next_step`. The core is defined here, in code, and is never stored
  in an agent's schema, so no client edit, template or generated set can remove it.
* **The business fields** — what THIS business needs on top: a vertical's standard set,
  a set drafted once by AI for a custom business, or whatever the client has made of either
  since. These are the rows of `extraction_schemas.fields` and are versioned there.

The core is COMPOSED IN at read time (`with_core`) rather than written into every stored
version. Writing it would need a data migration over every agent and would make the core a
copy that a stored version could disagree with; composing it means every reader that builds
an extraction spec or a column list asks one function and gets the same answer. The cost is
that each reader must ask — `tests/lead_fields_test.py` pins the readers that build an
extraction spec or a column list.

The stored list of some older agents already holds `need` and `preferred_time` (the old
neutral set for a custom business). Those keys are core keys with the same meaning, so the
core definition wins and the stored copy is dropped on read; values captured under them
stay where they are and keep showing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Final

from calevate_shared.extraction import ExtractionField

#: The fixed core, in display order. Every `reason` is the instruction the extraction model
#: reads (`build_extraction_prompt`). None is required: a wrong-number or silent call
#: correctly captures nothing, and a required miss marks the extraction invalid.
#:
#: Only `other_number` may hold a phone number. `is_phone_field` decides that from the key,
#: label and reason, so the other reasons avoid the words "number", "phone", "mobile" and
#: "contact" on purpose.
CORE_LEAD_FIELDS: Final[tuple[ExtractionField, ...]] = (
    ExtractionField(
        key="name",
        label="Name",
        type="text",
        reason="The caller's own name, as they said it. Not a name the agent used.",
    ),
    ExtractionField(
        key="need",
        label="What they want",
        type="text",
        reason=(
            "What the caller wants or why they called, in a few words of their own "
            "(for example 'two kilos of green chilli', 'price of a service', 'reschedule')."
        ),
    ),
    ExtractionField(
        key="preferred_time",
        label="Preferred time",
        type="text",
        reason=(
            "When the caller wants to be called back, visit, collect or be served, in their "
            "own words. Leave empty if they named no time."
        ),
    ),
    ExtractionField(
        key="other_number",
        label="Other number",
        type="text",
        reason=(
            "A different phone number the caller asked to be reached on. Leave empty when "
            "they gave none or meant the number they called from."
        ),
    ),
    ExtractionField(
        key="language",
        label="Language",
        type="text",
        reason=(
            "The language the caller spoke, named in English: Telugu, Hindi, English, or "
            "two of them joined with 'and' when they mixed."
        ),
    ),
    ExtractionField(
        key="notes",
        label="Notes",
        type="text",
        reason=(
            "Anything else the business should know before calling back that no other "
            "field holds, in one short sentence. Never a copy of the conversation."
        ),
    ),
)

CORE_KEYS: Final[frozenset[str]] = frozenset(f.key for f in CORE_LEAD_FIELDS)

#: The keys the extraction pass answers for every call beside the fields
#: (`build_extraction_prompt`'s "Also include"). A field under one of them would be a
#: second, conflicting value for the same JSON key, so none may be a field key.
OUTPUT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "summary",
        "headline",
        "next_step",
        "sentiment",
        "outcome_tag",
        "out_of_scope",
        "callback_requested",
    }
)

#: The core field a screen shows as "what they want" — the one the leads table and the
#: call's captured panel lead with.
NEED_KEY: Final = "need"


def _as_field(field: ExtractionField | Mapping[str, Any]) -> ExtractionField:
    return field if isinstance(field, ExtractionField) else ExtractionField.model_validate(field)


def business_only(
    fields: Iterable[ExtractionField | Mapping[str, Any]] | None,
) -> list[ExtractionField]:
    """The stored list without any field whose key is a core key, in stored order."""
    return [f for f in (_as_field(raw) for raw in fields or ()) if f.key not in CORE_KEYS]


def with_core(
    fields: Iterable[ExtractionField | Mapping[str, Any]] | None,
) -> list[ExtractionField]:
    """The core, then the business fields: what an extraction captures and a lead shows."""
    return [*CORE_LEAD_FIELDS, *business_only(fields)]



__all__ = [
    "CORE_KEYS",
    "CORE_LEAD_FIELDS",
    "NEED_KEY",
    "OUTPUT_KEYS",
    "business_only",
    "with_core",
]
