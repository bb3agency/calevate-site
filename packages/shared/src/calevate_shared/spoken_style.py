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
#: What an opening is keyed by: the call direction, and `test_call`, the line an agent that
#: only answers calls opens with when it rings its owner on a free-trial test call (founder,
#: 23 Oct 2026), with `{name}` and `{business}` to fill. Each `_introduced` form is the same
#: line said right after the agent's AI notice has introduced it (D-865): no greeting, and
#: no name of the agent or the business, which the introduction has just said.
OPENING_KEYS: Final = (
    "inbound",
    "outbound",
    "test_call",
    "inbound_introduced",
    "outbound_introduced",
    "test_call_introduced",
)
INTRODUCED_SUFFIX: Final = "_introduced"

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
    #: Said while a reply is slow (the engine's filler line, `thinking_lines`), not only a
    #: word the writers may use.
    thinking: bool = False


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
    #: A web address spelled the way a caller following on a screen hears it (D-906): English
    #: letter names in this language's letters, a comma between. Read from the file alone,
    #: like `prompt_examples`, because it reaches the in-call prompt.
    spelled_address: str | None = None


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
            "thinking": bool(raw.get("thinking", False)),
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
        fillers=tuple(
            Filler(
                text=e.value["text"],
                use=e.value["use"],
                thinking=bool(e.value.get("thinking", False)),
            )
            for e in by_kind["filler"]
        ),
        number_rules=tuple(e.value["text"] for e in by_kind["number_rule"]),
        native_price_words=_native_price_words(tag, row),
        punctuation=tuple(e.value["text"] for e in by_kind["punctuation"]),
        reviewed_on=reviewed_on,
        prompt_examples=_prompt_examples(tag, row),
        spelled_address=row.get("spelled_address") or None,
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
    return _exchanges(tag, block)


def candidate_prompt_examples(tag: str | None) -> tuple[tuple[ExampleTurn, ...], ...]:
    """The language's drafted in-call examples awaiting the founder (`candidate_prompt_examples`
    in the file), for the register eval to measure (`scripts/register_eval`). No prompt reads
    them: an example reaches a live agent only by moving into `prompt_examples` once approved."""
    language = find_language(tag) if tag else None
    row = _raw()["languages"].get(language.bcp47 if language is not None else tag or "")
    block = row.get("candidate_prompt_examples") if row is not None else None
    return _exchanges(str(tag), block) if block else ()


def _exchanges(tag: str, block: Mapping[str, Any]) -> tuple[tuple[ExampleTurn, ...], ...]:
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


# --- language packs (D-830) ------------------------------------------------------------------
#
# A language pack is the one platform block that says how an agent speaks a language: how
# people talk on the phone in it, the words to say (the English loanwords included), the
# words not to say, example exchanges, and that a fact's English nouns stay English. The
# primary language gets the full pack; each extra language a compact one (its top words and
# `COMPACT_EXCHANGES` exchanges), so a caller who switches still hears everyday speech. The
# business's own content never goes in a pack.
#
# Packs are measured by `scripts/register_eval` before any of them ships. A pack reaches a
# live prompt only when its `review` is `founder_approved` AND its `ship` names the form the
# eval chose; until then `compose_engine_prompt` keeps the register section it had.

#: How a pack's instructions are written: `en`, English with the language's own examples;
#: `native`, in the everyday, code-mixed language itself.
PackForm = Literal["en", "native"]
PACK_FORMS: Final[tuple[PackForm, ...]] = get_args(PackForm)
#: How a pack names the words not to say: a plain list, each with what to say instead, or
#: not at all. A word named in a prompt can come back more often (Mann et al., Nov 2025,
#: arXiv:2511.12381); the founder asked for the list, so the eval decides.
AvoidForm = Literal["list", "pairs", "none"]
AVOID_FORMS: Final[tuple[AvoidForm, ...]] = get_args(AvoidForm)
#: What an extra language's compact pack carries.
COMPACT_SAY: Final = 8
COMPACT_AVOID: Final = 5
COMPACT_EXCHANGES: Final = 3
PACK_APPROVED: Final = "founder_approved"


@dataclass(frozen=True, slots=True)
class PackChoice:
    """Which form of a pack a prompt carries."""

    form: PackForm
    avoid: AvoidForm


@dataclass(frozen=True, slots=True)
class NativeLeads:
    """A pack's instruction sentences written in the language itself (the `native` form)."""

    talk: tuple[str, ...]
    say: str
    say_spoken: str
    avoid: str
    pairs: str
    leave_out: str
    facts: str
    examples: str
    you: str
    when_extra: str


@dataclass(frozen=True, slots=True)
class LanguagePack:
    tag: str
    review: str
    #: The form the founder approved from the eval; None until then.
    ship: PackChoice | None
    #: Concepts said as the English word, written in the language's own letters (D-861).
    say_english: tuple[str, ...]
    #: (what to say, its English meaning): the language's own spoken forms.
    say_spoken: tuple[tuple[str, str], ...]
    #: Formal words not to say, most frequent first; each is a `word_swaps` formal word.
    avoid: tuple[str, ...]
    exchanges: tuple[tuple[ExampleTurn, ...], ...]
    native: NativeLeads | None
    #: How the language is spoken, in English, for the `en` form; the register line without it.
    talk_en: str | None = None


#: The English form's sentences. The native form's are the pack's `NativeLeads`.
_EN_SAY: Final = "Say as the English word, as callers do, in this language's letters: "
_EN_SAY_SPOKEN: Final = "and say "
_EN_AVOID: Final = "Never say: "
_EN_PAIRS: Final = "Never say these; say what follows each instead: "
#: Said once per prompt, after every language's lines.
PACK_FACTS_RULE: Final = (
    "Facts you are given in English keep their English nouns when you say them; never "
    "translate a noun."
)


def language_pack(tag: str | None) -> LanguagePack | None:
    """A language's pack as the file holds it, whatever its review, or None without one."""
    language = find_language(tag) if tag else None
    key = language.bcp47 if language is not None else tag or ""
    row = _raw()["languages"].get(key)
    block = row.get("language_pack") if row is not None else None
    if not block:
        return None
    ship = block.get("ship")
    native = block.get("native")
    return LanguagePack(
        tag=key,
        review=str(block["review"]),
        ship=PackChoice(form=ship["form"], avoid=ship["avoid"]) if ship else None,
        say_english=tuple(block.get("say_english", ())),
        say_spoken=tuple((said, meaning) for said, meaning in block.get("say_spoken", ())),
        avoid=tuple(block.get("avoid", ())),
        exchanges=_exchanges(key, block) if block.get("exchanges") else (),
        native=NativeLeads(**{**native, "talk": tuple(native["talk"])}) if native else None,
        talk_en=block.get("talk_en"),
    )


def shipped_pack_choice(tag: str | None) -> PackChoice | None:
    """The pack form live prompts carry for this primary language: only a founder-approved
    pack with its form chosen. Read from the file alone, like `prompt_examples`, so it changes
    only with a reviewed deploy, which moves the platform-prompt revision."""
    pack = language_pack(tag)
    if pack is None or pack.review != PACK_APPROVED:
        return None
    return pack.ship


def _with_meanings(pack: LanguagePack) -> str:
    return ", ".join(f"{said} ({meaning})" for said, meaning in pack.say_spoken)


def _pack_say(pack: LanguagePack, form: PackForm, compact: bool) -> str | None:
    english = pack.say_english[:COMPACT_SAY] if compact else pack.say_english
    leads = pack.native if form == "native" else None
    parts: list[str] = []
    if english:
        parts.append((leads.say if leads else _EN_SAY) + ", ".join(english))
    if pack.say_spoken and not compact:
        parts.append((leads.say_spoken if leads else _EN_SAY_SPOKEN) + _with_meanings(pack))
    return "; ".join(parts) + "." if parts else None


def _pack_avoid(pack: LanguagePack, choice: PackChoice, compact: bool) -> str | None:
    words = pack.avoid[:COMPACT_AVOID] if compact else pack.avoid
    if choice.avoid == "none" or not words:
        return None
    leads = pack.native if choice.form == "native" else None
    if choice.avoid == "list":
        return (leads.avoid if leads else _EN_AVOID) + ", ".join(words) + "."
    style = style_for(pack.tag)
    spoken = dict(style.word_swaps) if style is not None else {}
    leave_out = leads.leave_out if leads else "(leave it out)"

    def pair(word: str) -> str:
        said = spoken.get(word, "")
        if said and not said.startswith("("):
            return f"{word} ({said})"
        # An instruction such as "(join with ఇంకా, or leave it out)" is English; the
        # native form says only its own "leave it out".
        return f"{word} {said if said and leads is None else leave_out}"

    return (leads.pairs if leads else _EN_PAIRS) + ", ".join(map(pair, words)) + "."


def _pack_examples(pack: LanguagePack, form: PackForm, compact: bool) -> str | None:
    exchanges = pack.exchanges[:COMPACT_EXCHANGES] if compact else pack.exchanges
    if not exchanges:
        return None
    leads = pack.native if form == "native" else None
    if leads is None:
        return example_sentence(exchanges)
    who = {"caller": "caller", "agent": leads.you}
    said = "; ".join(
        ", ".join(f'{who[turn.speaker]} "{turn.text}"' for turn in exchange)
        for exchange in exchanges
    )
    return f"{leads.examples} {said}."


def pack_lines(tag: str, choice: PackChoice, *, compact: bool = False) -> list[str]:
    """One language's pack lines in `choice`'s form: the full pack, or the compact one an
    extra language gets. Empty for a language with no pack or style row. A pack without
    native leads is written in English whatever the form."""
    pack, style = language_pack(tag), style_for(tag)
    if pack is None or style is None:
        return []
    form: PackForm = choice.form if pack.native is not None else "en"
    choice = PackChoice(form=form, avoid=choice.avoid)
    name = _language_name(tag)
    leads = pack.native if form == "native" else None
    lines: list[str] = []
    if compact:
        when = leads.when_extra if leads else "when the caller speaks it:"
        words = [_pack_say(pack, form, compact=True), _pack_avoid(pack, choice, compact=True)]
        lines.append(" ".join([f"{name}, {when}", *(w for w in words if w)]))
    else:
        talk = " ".join(leads.talk) if leads else pack.talk_en or style.register
        lines.append(f"{name}: {talk}")
        for said in (
            _pack_say(pack, form, compact=False),
            _pack_avoid(pack, choice, compact=False),
        ):
            if said:
                lines.append(said)
    examples = _pack_examples(pack, form, compact)
    if examples:
        lines.append(examples)
    return lines


def pack_facts_rule(tag: str, choice: PackChoice) -> str:
    """The keep-English-nouns rule, once, in the primary pack's form."""
    pack = language_pack(tag)
    if choice.form == "native" and pack is not None and pack.native is not None:
        return pack.native.facts
    return PACK_FACTS_RULE


def _language_name(tag: str) -> str:
    language = find_language(tag)
    return language.english_name if language is not None else tag


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


def spelled_address(tag: str | None) -> str | None:
    """How a web address is spelled aloud in this language (D-906), or None without one."""
    style = style_for(tag)
    return style.spelled_address if style is not None else None


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
    return example_sentence(style.prompt_examples)


def example_sentence(exchanges: Sequence[Sequence[ExampleTurn]]) -> str:
    """Exchanges as the one sentence `prompt_example_line` composes."""
    said = "; ".join(
        ", ".join(f'{_WHO[turn.speaker]} "{turn.text}"' for turn in exchange)
        for exchange in exchanges
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


def thinking_lines(tags: Sequence[str]) -> tuple[str, ...]:
    """The fillers marked `thinking` for each language the agent speaks, in that order, each
    once: the platform's own lines an agent says while a reply is slow (founder, 23 Oct 2026).

    Every language's lines go together because the engine picks, per call, the lines written in
    the caller's script (`voice.thinkingLines`, `thinnest-findings/mirror/snapshots/2026-10-19/
    pages/api-reference/agents/create-agent.md:1446-1454`). A language with no such filler adds
    none, so an agent whose languages have none sends none and keeps the engine's own."""
    lines: list[str] = []
    for tag in tags:
        style = style_for(tag)
        for filler in style.fillers if style is not None else ():
            if filler.thinking and filler.text not in lines:
                lines.append(filler.text)
    return tuple(lines)


def trial_call_opening(
    tag: str | None, *, name: str, business: str, introduced: bool = False
) -> str | None:
    """The line an answer-only agent opens a free-trial test call with: who it is, from which
    business, why it rings (a test of the owner's new receptionist) and whether now suits;
    `introduced`, only why it rings and whether now suits (D-865). None where the language
    has no such line."""
    template = opening_in(tag, "test_call", introduced=introduced)
    if template is None:
        return None
    return " ".join(template.replace("{name}", name).replace("{business}", business).split())


def opening_in(tag: str | None, direction: str, *, introduced: bool = False) -> str | None:
    """A starter's opening line in the agent's language (`{business}` unfilled), or None
    where the table has none for it. `introduced` asks for the form said after the agent's
    introduction, and falls back to the plain one where the table has none."""
    style = style_for(tag)
    if style is None or not style.openings:
        return None
    if introduced and (line := style.openings.get(direction + INTRODUCED_SUFFIX)):
        return line
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
    "AVOID_FORMS",
    "COMPACT_AVOID",
    "COMPACT_EXCHANGES",
    "COMPACT_SAY",
    "DEFAULT_EXAMPLES",
    "ENTRY_KINDS",
    "OPENING_KEYS",
    "PACK_APPROVED",
    "PACK_FACTS_RULE",
    "PACK_FORMS",
    "PRICE_WORDS",
    "PROMPT_EXAMPLES_APPROVED",
    "REGISTER_KEY",
    "AvoidForm",
    "EntryKind",
    "ExampleTurn",
    "Filler",
    "LanguagePack",
    "LanguageStyle",
    "NativeLeads",
    "PackChoice",
    "PackForm",
    "PublishedEntry",
    "PublishedLanguage",
    "ReviewStatus",
    "Speaker",
    "StyleEntry",
    "caller_guidance",
    "candidate_prompt_examples",
    "default_entries",
    "example_exchange",
    "example_sentence",
    "install_published",
    "language_pack",
    "languages",
    "merged_entries",
    "native_reviewed",
    "normalize_value",
    "opening_in",
    "pack_facts_rule",
    "pack_lines",
    "prompt_example_line",
    "register_guidance",
    "shipped_pack_choice",
    "spelled_address",
    "style_for",
    "thinking_lines",
    "trial_call_opening",
    "writer_guidance",
]
