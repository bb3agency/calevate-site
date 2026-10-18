"""How people speak on a call, per language and business type: the register line every agent
in that language carries, the formal-to-spoken word list, the tags and fillers, how numbers
and sentences are written for a voice, and example exchanges that seed new scripts (founder
decision 3, 10 Oct 2026, `docs/evidence/first-call-review-2026-10-10.md`; the spoken-style
rules of 11 Oct 2026, D-744).

The words live in `spoken_style.json` beside this module, not in code, so the founder can
correct them without touching a prompt builder. Every entry there is AI-drafted and
`needs_native_review`. The founder reviews them on the admin screen (Ops > Spoken style);
what they publish is stored by the API (`apps/api/ops/spoken_style_store.py`) and installed
here with `install_published`, layered over the file: an edited or added entry replaces or
joins the file's, a retired one is dropped, and an entry the founder approved is
`native_reviewed`. This package cannot import the API, so the published layer is pushed in
rather than read, the same way the API installs the attested prices into `billing.rates`.

Consumers, kept apart on purpose:

* `register_guidance` is PLATFORM text, composed into every agent's prompt by
  `engine.compose_engine_prompt`. It stays short (every character is read on every turn,
  `docs/PROMPT-GUIDE.md` §2), so it carries the register line, only the swaps named in
  `prompt_swaps` and the tags and fillers, and quotes no full sentence: platform text is
  instructions, not lines to recite.
* `prompt_example_line` is the one exception: the founder-approved `prompt_examples`
  (D-778), quoted after the primary language's register as how a turn sounds, never as
  words to copy.
* `writer_guidance` is the long form for the models that WRITE spoken lines (the script
  assistant, the test-caller writer): every swap, the number and punctuation rules and two
  or three example exchanges, because a writer copies examples far better than it follows
  an abstract rule about register.
* `example_exchange` and `opening_in` seed the CLIENT's script, where the client can edit
  or delete them and where the output guard knows they are spoken.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from types import MappingProxyType
from typing import Any, Final, Literal, get_args

from calevate_shared.languages import find_language

ReviewStatus = Literal["needs_native_review", "native_reviewed"]
Speaker = Literal["caller", "agent"]

#: What one reviewable entry is. `register` has the one key `line`; `opening` is keyed by
#: call direction; `example` by business type; `swap` by its formal word; the rest by id.
EntryKind = Literal[
    "register", "swap", "filler", "number_rule", "punctuation", "example", "opening"
]
ENTRY_KINDS: Final[tuple[EntryKind, ...]] = get_args(EntryKind)

#: The business-type key an unknown or custom business falls back to.
DEFAULT_EXAMPLES: Final = "_default"
#: The key of a language's one register line.
REGISTER_KEY: Final = "line"
#: The call directions an opening is keyed by.
OPENING_KEYS: Final = ("inbound", "outbound")

#: Bounds on what an edit may hold, so a typo cannot blow the prompt budget.
MAX_TEXT: Final = 600
MAX_SHORT: Final = 120
MAX_TURNS: Final = 10
#: Tags and fillers quoted in the prompt; the rest guide the writers only. Four since D-778,
#: whose in-call examples show the commonest tags, so the platform layers stay within cap.
PROMPT_FILLERS: Final = 4
#: Keys are short ids a URL can carry: letters, digits, `-` and `_`, or a swap's formal word.
_ID: Final = re.compile(r"^[a-z0-9_][a-z0-9_-]{0,47}$")


@dataclass(frozen=True, slots=True)
class ExampleTurn:
    speaker: Speaker
    text: str


@dataclass(frozen=True, slots=True)
class Filler:
    text: str
    #: When it is used, in English, for the writers.
    use: str = ""


@dataclass(frozen=True, slots=True)
class LanguageStyle:
    tag: str
    register_name: str
    register: str
    review: ReviewStatus
    reviewed_by: str | None
    examples: dict[str, tuple[ExampleTurn, ...]]
    #: (formal or written form, what people say instead): the whole list, for the writers
    #: and the test checks.
    word_swaps: tuple[tuple[str, str], ...] = ()
    #: A starter's greeting in this language, by direction, with `{business}` to fill.
    openings: dict[str, str] | None = None
    #: The swaps short enough and common enough to sit in every agent's prompt.
    prompt_swaps: tuple[tuple[str, str], ...] = ()
    fillers: tuple[Filler, ...] = ()
    number_rules: tuple[str, ...] = ()
    #: A price may be said in the language's own number words ("एक सौ बीस रुपये"), from the
    #: `words` of its `prices` number rule: `english` (Telugu: "one twenty rupees", D-744)
    #: forbids them, `native_or_english` allows them, and no rule forbids nothing. The reply
    #: check reads this (`agents/turn_checks`), so the check cannot drift from the rule.
    native_price_words: bool = True
    punctuation: tuple[str, ...] = ()
    #: The IST date the reviewed set was published, when it was.
    reviewed_on: str | None = None
    #: Short exchanges the in-call prompt quotes as how a turn sounds (D-778); only the
    #: founder-approved ones in the file, never the published layer (see `_prompt_examples`).
    prompt_examples: tuple[tuple[ExampleTurn, ...], ...] = ()


@dataclass(frozen=True, slots=True)
class StyleEntry:
    """One reviewable entry as the file holds it (`value` is `normalize_value`'s shape)."""

    kind: EntryKind
    key: str
    value: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PublishedEntry:
    """The founder's published word on one entry: its value (None = retired) and whether
    they approved it."""

    value: Mapping[str, Any] | None
    approved: bool


@dataclass(frozen=True, slots=True)
class PublishedLanguage:
    """One language's published layer: entries keyed by (kind, key), and who reviewed it."""

    entries: Mapping[tuple[str, str], PublishedEntry] = field(default_factory=dict)
    reviewed_by: str | None = None
    reviewed_on: str | None = None


# --- values ---------------------------------------------------------------------------------


def _text(
    raw: Mapping[str, Any], name: str, limit: int = MAX_TEXT, *, required: bool = True
) -> str:
    value = raw.get(name, "")
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    value = " ".join(value.split())
    if required and not value:
        raise ValueError(f"{name} is empty")
    if len(value) > limit:
        raise ValueError(f"{name} is longer than {limit} characters")
    return value


def normalize_value(kind: str, key: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    """An entry's value in its one shape, or ValueError naming what is wrong. Used for the
    file and for every edit the review screen sends, so both reach the prompt the same way."""
    if kind == "register":
        if key != REGISTER_KEY:
            raise ValueError(f"the register's key is {REGISTER_KEY!r}")
        return {"text": _text(raw, "text")}
    if kind == "swap":
        formal = _text(raw, "formal", MAX_SHORT)
        if formal != key:
            raise ValueError("a swap is keyed by its formal word; retire it and add a new one")
        return {
            "formal": formal,
            "spoken": _text(raw, "spoken", MAX_SHORT),
            "in_prompt": bool(raw.get("in_prompt", False)),
        }
    if kind == "opening":
        if key not in OPENING_KEYS:
            raise ValueError(f"an opening is keyed by {' or '.join(OPENING_KEYS)}")
        return {"text": _text(raw, "text", 300)}
    if not _ID.match(key):
        raise ValueError("key: lowercase letters, digits, - and _ only")
    if kind == "filler":
        return {
            "text": _text(raw, "text", MAX_SHORT),
            "use": _text(raw, "use", 300, required=False),
        }
    if kind in ("number_rule", "punctuation"):
        return {"text": _text(raw, "text", 400)}
    if kind == "example":
        turns = raw.get("turns")
        if not isinstance(turns, Sequence) or isinstance(turns, str) or not turns:
            raise ValueError("an example needs at least one turn")
        if len(turns) > MAX_TURNS:
            raise ValueError(f"an example has at most {MAX_TURNS} turns")
        out: list[dict[str, str]] = []
        for turn in turns:
            if not isinstance(turn, Mapping) or turn.get("speaker") not in ("caller", "agent"):
                raise ValueError("each turn has a speaker, caller or agent")
            out.append({"speaker": str(turn["speaker"]), "text": _text(turn, "text", 300)})
        return {"turns": out}
    raise ValueError(f"unknown entry kind {kind!r}")


# --- the file -------------------------------------------------------------------------------


@cache
def _raw() -> dict[str, Any]:
    raw: dict[str, Any] = json.loads(
        resources.files(__package__).joinpath("spoken_style.json").read_text(encoding="utf-8")
    )
    return raw


def languages() -> tuple[str, ...]:
    """Every language the file has a row for, in file order."""
    return tuple(_raw()["languages"])


def _file_entries(row: Mapping[str, Any]) -> list[StyleEntry]:
    entries: list[StyleEntry] = []

    def add(kind: EntryKind, key: str, raw: Mapping[str, Any]) -> None:
        entries.append(StyleEntry(kind=kind, key=key, value=normalize_value(kind, key, raw)))

    add("register", REGISTER_KEY, {"text": row["register"]})
    for direction, text in (row.get("openings") or {}).items():
        add("opening", direction, {"text": text})
    prompt_names = row.get("prompt_swaps")
    for formal, spoken in row.get("word_swaps", []):
        in_prompt = True if prompt_names is None else formal in prompt_names
        add("swap", formal, {"formal": formal, "spoken": spoken, "in_prompt": in_prompt})
    for item in row.get("fillers", []):
        add("filler", item["id"], item)
    for item in row.get("number_rules", []):
        add("number_rule", item["id"], item)
    for item in row.get("punctuation", []):
        add("punctuation", item["id"], item)
    for kind, turns in row["examples"].items():
        for speaker, _said in turns:
            if speaker not in ("caller", "agent"):
                raise ValueError(f"spoken_style.json: unknown speaker {speaker!r}")
        add("example", kind, {"turns": [{"speaker": s, "text": t} for s, t in turns]})
    return entries


def default_entries(tag: str) -> tuple[StyleEntry, ...]:
    """A language's entries as the file holds them, before any review. Empty for a
    language with no row."""
    row = _raw()["languages"].get(tag)
    return tuple(_file_entries(row)) if row is not None else ()


# --- the published layer --------------------------------------------------------------------

_published: Mapping[str, PublishedLanguage] = MappingProxyType({})


def install_published(layer: Mapping[str, PublishedLanguage] | None) -> None:
    """Install the founder's published layer for this process (None restores the file
    alone). Called by the API's snapshot refresher, and by tests."""
    global _published
    _published = MappingProxyType(dict(layer or {}))
    _table.cache_clear()


def merged_entries(tag: str) -> tuple[list[StyleEntry], set[tuple[str, str]]]:
    """The language's entries with the published layer applied, in file order then added
    order, and the (kind, key) pairs the founder approved."""
    layer = _published.get(tag)
    merged: dict[tuple[str, str], StyleEntry] = {(e.kind, e.key): e for e in default_entries(tag)}
    approved: set[tuple[str, str]] = set()
    if layer is not None:
        for (kind, key), published in layer.entries.items():
            if published.value is None:
                merged.pop((kind, key), None)
                continue
            merged[(kind, key)] = StyleEntry(kind=kind, key=key, value=published.value)  # type: ignore[arg-type]
            if published.approved:
                approved.add((kind, key))
    return list(merged.values()), approved


def _build(tag: str, row: Mapping[str, Any]) -> LanguageStyle:
    review = row["review"]
    if review not in ("needs_native_review", "native_reviewed"):
        raise ValueError(f"spoken_style.json: {tag} has review {review!r}")
    entries, approved = merged_entries(tag)
    by_kind: dict[str, list[StyleEntry]] = {kind: [] for kind in ENTRY_KINDS}
    for entry in entries:
        by_kind[entry.kind].append(entry)
    layer = _published.get(tag)
    reviewed_by = row.get("reviewed_by")
    reviewed_on: str | None = None
    if layer is not None and entries and all((e.kind, e.key) in approved for e in entries):
        review, reviewed_by, reviewed_on = "native_reviewed", layer.reviewed_by, layer.reviewed_on
    register = by_kind["register"][0].value["text"] if by_kind["register"] else row["register"]
    swaps = tuple((e.value["formal"], e.value["spoken"]) for e in by_kind["swap"])
    return LanguageStyle(
        tag=tag,
        register_name=str(row["register_name"]),
        register=str(register),
        review=review,
        reviewed_by=reviewed_by,
        examples={
            e.key: tuple(
                ExampleTurn(speaker=t["speaker"], text=t["text"]) for t in e.value["turns"]
            )
            for e in by_kind["example"]
        },
        word_swaps=swaps,
        openings={e.key: e.value["text"] for e in by_kind["opening"]} or None,
        prompt_swaps=tuple(
            (e.value["formal"], e.value["spoken"]) for e in by_kind["swap"] if e.value["in_prompt"]
        ),
        fillers=tuple(Filler(text=e.value["text"], use=e.value["use"]) for e in by_kind["filler"]),
        number_rules=tuple(e.value["text"] for e in by_kind["number_rule"]),
        native_price_words=_native_price_words(tag, row),
        punctuation=tuple(e.value["text"] for e in by_kind["punctuation"]),
        reviewed_on=reviewed_on,
        prompt_examples=_prompt_examples(tag, row),
    )


#: The `words` a `prices` number rule may name.
PRICE_WORDS: Final = ("english", "native_or_english")


def _native_price_words(tag: str, row: Mapping[str, Any]) -> bool:
    """Whether the language's `prices` rule lets a price be said in its own number words.
    Read from the file alone: the Ops screen's published layer reviews a rule's wording, not
    this switch, so it changes only with a reviewed deploy, like `prompt_examples`."""
    rule = next((r for r in row.get("number_rules", []) if r.get("id") == "prices"), None)
    if rule is None or "words" not in rule:
        return True
    words = rule["words"]
    if words not in PRICE_WORDS:
        raise ValueError(f"spoken_style.json: {tag} prices rule words {words!r}")
    return bool(words == "native_or_english")


#: The status a `prompt_examples` block must carry before any prompt quotes it.
PROMPT_EXAMPLES_APPROVED: Final = "founder_approved"


def _prompt_examples(tag: str, row: Mapping[str, Any]) -> tuple[tuple[ExampleTurn, ...], ...]:
    """The language's founder-approved in-call examples, or () while they are a draft.

    Read from the file alone rather than as a reviewable entry kind: they reach every live
    agent's prompt, so they change only with a reviewed deploy, which also moves the
    platform-prompt revision that re-applies live agents (`agents/live_apply`). The Ops
    screen's published layer does not cover them.
    """
    block = row.get("prompt_examples")
    if not block or block.get("review") != PROMPT_EXAMPLES_APPROVED:
        return ()
    exchanges: list[tuple[ExampleTurn, ...]] = []
    for exchange in block["exchanges"]:
        turns: list[ExampleTurn] = []
        for speaker, said in exchange:
            if speaker not in ("caller", "agent"):
                raise ValueError(f"spoken_style.json: {tag} prompt example speaker {speaker!r}")
            turns.append(
                ExampleTurn(speaker=speaker, text=_text({"text": said}, "text", MAX_SHORT))
            )
        exchanges.append(tuple(turns))
    return tuple(exchanges)


@cache
def _table() -> dict[str, LanguageStyle]:
    return {tag: _build(tag, row) for tag, row in _raw()["languages"].items()}


def style_for(tag: str | None) -> LanguageStyle | None:
    """The style row for a language, by any code `languages.find_language` accepts, with
    the founder's published layer applied."""
    if not tag:
        return None
    language = find_language(tag)
    key = language.bcp47 if language is not None else tag
    return _table().get(key)


# --- readers --------------------------------------------------------------------------------


def native_reviewed(tag: str | None) -> bool:
    """Has a native speaker reviewed this language's published set?"""
    style = style_for(tag)
    return style is not None and style.review == "native_reviewed"


def register_guidance(tag: str | None) -> str | None:
    """The register line, then the prompt's do/don't list as concrete pairs, then the tags
    and fillers. Concrete pairs because an open in-call model (GPT-OSS 120B, founder decision
    10 Oct 2026) follows a word it can copy far better than an abstract rule about register."""
    style = style_for(tag)
    if style is None:
        return None
    parts = [style.register]
    if style.prompt_swaps:
        swaps = "; ".join(_swap(formal, spoken) for formal, spoken in style.prompt_swaps)
        parts.append(f"Spoken words: {swaps}.")
    if style.fillers:
        said = ", ".join(f.text for f in style.fillers[:PROMPT_FILLERS])
        parts.append(f"Fillers, lightly: {said}.")
    return " ".join(parts)


#: How the example line names each side: the agent reading it is "you".
_WHO: Final[dict[str, str]] = {"caller": "caller", "agent": "you"}


def prompt_example_line(tag: str | None) -> str | None:
    """The language's approved in-call examples as one sentence, or None without any.

    Framed as how a turn sounds and never as words to copy, because a model repeats sample
    phrases verbatim unless told otherwise (OpenAI Realtime prompting guide, GPT-4.1 guide;
    `docs/evidence/prompting-practices-2026-10.md` S1, S15). The sides are named in line, in lower
    case, not as `Caller:` line labels a model could echo, which the test loop fails
    (`agents/turn_checks`, `speaker_labels`)."""
    style = style_for(tag)
    if style is None or not style.prompt_examples:
        return None
    said = "; ".join(
        ", ".join(f'{_WHO[turn.speaker]} "{turn.text}"' for turn in exchange)
        for exchange in style.prompt_examples
    )
    return f"How a turn sounds, never words to copy: {said}."


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


def _exchanges_for(style: LanguageStyle, business_type: str | None, count: int) -> list[str]:
    order = [business_type or "", DEFAULT_EXAMPLES, *style.examples]
    picked: list[str] = []
    for kind in order:
        if kind in style.examples and kind not in picked:
            picked.append(kind)
        if len(picked) == count:
            break
    return picked


def writer_guidance(tag: str | None, business_type: str | None = None, *, examples: int = 3) -> str:
    """Everything a model that WRITES spoken lines in this language needs, in English:
    the register, every formal-to-spoken swap, the tags and fillers, the number and
    punctuation rules, and up to `examples` example exchanges (this business type's first).
    Empty for a language with no style row."""
    style = style_for(tag)
    if style is None:
        return ""
    lines = [f"How people speak it on the phone ({style.register_name}): {style.register}"]
    if style.word_swaps:
        lines.append(
            "Formal words to avoid, with what people say instead: "
            + "; ".join(f"{formal} -> {spoken}" for formal, spoken in style.word_swaps)
            + "."
        )
    if style.fillers:
        lines.append(
            "Spoken tags and light fillers, used where they help and not in every line: "
            + "; ".join(f"{f.text} ({f.use})" if f.use else f.text for f in style.fillers)
        )
    if style.number_rules:
        lines.append("Numbers: " + " ".join(style.number_rules))
    if style.punctuation:
        lines.append("Writing for a voice: " + " ".join(style.punctuation))
    picked = _exchanges_for(style, business_type, examples)
    if picked:
        lines.append("Example exchanges, showing how it sounds, never facts to repeat:")
        for kind in picked:
            label = "any business" if kind == DEFAULT_EXAMPLES else kind.replace("_", " ")
            lines.append(f"({label})")
            lines += [f"{t.speaker.title()}: {t.text}" for t in style.examples[kind]]
    return "\n".join(lines)


def caller_guidance(tag: str | None, business_type: str | None = None) -> str:
    """How a CALLER sounds in this language, for the model that writes test callers: the
    tags and fillers, how numbers are said, and the caller's side of one example exchange.
    The swaps are not repeated here (the test brief already lists them). Empty for a
    language with no style row."""
    style = style_for(tag)
    if style is None:
        return ""
    lines: list[str] = []
    if style.fillers:
        lines.append("Tags and fillers callers use: " + ", ".join(f.text for f in style.fillers))
    if style.number_rules:
        lines.append("Numbers as people say them: " + " ".join(style.number_rules))
    picked = _exchanges_for(style, business_type, 1)
    if picked:
        said = [t.text for t in style.examples[picked[0]] if t.speaker == "caller"]
        if said:
            lines.append("How callers sound (style only): " + " / ".join(said))
    return "\n".join(lines)


__all__ = [
    "DEFAULT_EXAMPLES",
    "ENTRY_KINDS",
    "OPENING_KEYS",
    "PRICE_WORDS",
    "PROMPT_EXAMPLES_APPROVED",
    "REGISTER_KEY",
    "EntryKind",
    "ExampleTurn",
    "Filler",
    "LanguageStyle",
    "PublishedEntry",
    "PublishedLanguage",
    "ReviewStatus",
    "Speaker",
    "StyleEntry",
    "caller_guidance",
    "default_entries",
    "example_exchange",
    "install_published",
    "languages",
    "merged_entries",
    "native_reviewed",
    "normalize_value",
    "opening_in",
    "prompt_example_line",
    "register_guidance",
    "style_for",
    "writer_guidance",
]
