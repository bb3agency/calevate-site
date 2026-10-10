"""How people speak on a call, per language and business type: the register line every agent
in that language carries, and example exchanges that seed new scripts (founder decision 3,
10 Oct 2026, `docs/evidence/first-call-review-2026-10-10.md`).

The words live in `spoken_style.json` beside this module, not in code, so the founder or a
native speaker can correct them without touching a prompt builder. Every entry carries a
`review` status; all of them are AI-drafted and `needs_native_review` until a native speaker
has read them, and the script builder says so to the client.

Two consumers, kept apart on purpose:

* `register_guidance` is PLATFORM text, composed into every agent's prompt by
  `engine.compose_engine_prompt`. It describes the register in English and quotes no full
  sentence, because platform text is part of what the owned runtime's output guard treats as
  instructions not to recite (`voice_worker/output_guard.py`).
* `example_exchange` seeds the CLIENT's script (`call_script.CallScript.example_exchange`),
  where the client can edit or delete it and where the output guard knows it is spoken.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any, Final, Literal

from calevate_shared.languages import find_language

ReviewStatus = Literal["needs_native_review", "native_reviewed"]
Speaker = Literal["caller", "agent"]

#: The business-type key an unknown or custom business falls back to.
DEFAULT_EXAMPLES: Final = "_default"


@dataclass(frozen=True, slots=True)
class ExampleTurn:
    speaker: Speaker
    text: str


@dataclass(frozen=True, slots=True)
class LanguageStyle:
    tag: str
    register_name: str
    register: str
    review: ReviewStatus
    reviewed_by: str | None
    examples: dict[str, tuple[ExampleTurn, ...]]
    #: (formal or written form, what people say instead), for the prompt's do/don't list.
    word_swaps: tuple[tuple[str, str], ...] = ()
    #: A starter's greeting in this language, by direction, with `{business}` to fill.
    openings: dict[str, str] | None = None


def _turns(raw: list[list[str]]) -> tuple[ExampleTurn, ...]:
    out: list[ExampleTurn] = []
    for speaker, text in raw:
        if speaker not in ("caller", "agent"):
            raise ValueError(f"spoken_style.json: unknown speaker {speaker!r}")
        out.append(ExampleTurn(speaker=speaker, text=text))  # type: ignore[arg-type]
    return tuple(out)


@cache
def _table() -> dict[str, LanguageStyle]:
    raw: dict[str, Any] = json.loads(
        resources.files(__package__).joinpath("spoken_style.json").read_text(encoding="utf-8")
    )
    table: dict[str, LanguageStyle] = {}
    for tag, row in raw["languages"].items():
        review = row["review"]
        if review not in ("needs_native_review", "native_reviewed"):
            raise ValueError(f"spoken_style.json: {tag} has review {review!r}")
        table[tag] = LanguageStyle(
            tag=tag,
            register_name=str(row["register_name"]),
            register=str(row["register"]),
            review=review,
            reviewed_by=row.get("reviewed_by"),
            examples={kind: _turns(turns) for kind, turns in row["examples"].items()},
            word_swaps=tuple((str(a), str(b)) for a, b in row.get("word_swaps", [])),
            openings=dict(row["openings"]) if "openings" in row else None,
        )
    return table


def style_for(tag: str | None) -> LanguageStyle | None:
    """The style row for a language, by any code `languages.find_language` accepts."""
    if not tag:
        return None
    language = find_language(tag)
    key = language.bcp47 if language is not None else tag
    return _table().get(key)


def register_guidance(tag: str | None) -> str | None:
    """The register line, then the do/don't list as concrete pairs. Concrete pairs because
    an open in-call model (GPT-OSS 120B, founder decision 10 Oct 2026) follows a word it can
    copy far better than an abstract rule about register."""
    style = style_for(tag)
    if style is None:
        return None
    if not style.word_swaps:
        return style.register
    swaps = "; ".join(_swap(formal, spoken) for formal, spoken in style.word_swaps)
    return f"{style.register} Say it the spoken way: {swaps}."


def _swap(formal: str, spoken: str) -> str:
    # "(leave it out)" is an instruction, not a word to say, so it is not quoted.
    said = spoken if spoken.startswith("(") else f'"{spoken}"'
    return f'not "{formal}" but {said}'


def example_exchange(tag: str | None, business_type: str | None) -> tuple[ExampleTurn, ...]:
    """Example turns for a language and business type, falling back to the language's own
    default set; empty for a language with no style row."""
    style = style_for(tag)
    if style is None:
        return ()
    return style.examples.get(business_type or "", style.examples.get(DEFAULT_EXAMPLES, ()))


def opening_in(tag: str | None, direction: str) -> str | None:
    """A starter's opening line in the agent's language (`{business}` unfilled), or None
    where the table has none for it."""
    style = style_for(tag)
    if style is None or not style.openings:
        return None
    return style.openings.get(direction)



__all__ = [
    "DEFAULT_EXAMPLES",
    "ExampleTurn",
    "LanguageStyle",
    "ReviewStatus",
    "Speaker",
    "example_exchange",
    "opening_in",
    "register_guidance",
    "style_for",
]
