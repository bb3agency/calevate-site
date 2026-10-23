"""How often the in-call model's replies break the speaking checks, offline (D-829, D-830).

    uv run python -m scripts.register_eval --dry-run                     # sizes and cost
    uv run python -m scripts.register_eval --spend --out /reg/run.json   # every variant
    uv run python -m scripts.register_eval --spend --variants current,pack-native \
        --language te-IN --no-cross --runs 3 --out /reg/small.json
    uv run python -m scripts.register_eval --compare /reg/base.json /reg/run.json

The agent test runs mix three things that make a before-and-after unreadable: the callers
change between runs, each line is tried once, and a reply fails on any one of a dozen checks.
This measures one thing, the speaking register, on a fixed set:

- the REAL in-call system prompt, `compose_engine_prompt` over the retail starter of a
  reference shop with its pinned facts (`scripts/fixtures/register_eval_callers.json`), one per
  language, followed by ThinnestAI's own speaking rules, which it reads to the model after
  our instructions (`docs/vendor/thinnest-speaking-rules-2026-10-18.md`, VENDOR-STATED);
- the agent's real first words, then one fixed caller line, each line asked `--runs` times;
- the cross-language cases of the fixture's `cross` section: a caller speaking another
  language than the agent's main one, with and without it among the agent's languages.
  Every agent follows the caller (founder, 19 Oct 2026), so the right reply is in the
  caller's language, and `wrong_language` there means a reply in any other;
- the in-call model (`Settings.thinnest_own_model_default`, or `--model`) on our Google key
  through the same OpenAI-compatible endpoint and transport the platform uses
  (`google_openai_compat_base_url`, `apps/workers/chat.complete`), with the agent's reply
  ceiling (`AgentConfig.max_reply_tokens`) and no temperature, as the engine is sent none;
- every reply scored by `agents/turn_checks.turn_problems`, the checks the test loop fails a
  reply on, so this harness and the product agree on what a problem is.

One invocation runs several variants (`--variants`, `current` always first) under one
`--max-inr` budget and prints one table per language case: each variant's share of replies
showing each kind of problem, its change against `current` with a 95% interval, and `WINS`
where the textbook-word interval is wholly below zero and neither the wrong-language nor the
too-long share went up. A variant is either a register candidate built here
(`VARIANT_FEATURES`, combined with `+`) or a language-pack form (`pack-en`, `pack-native`,
with `-pairs` or `-noavoid` for how the words not to say are named), composed by the same
`engine_prompt_layers` code that ships it (`spoken_style.language_pack`). The
confidentiality and truthful-answer layers are never touched. `--dry-run` prints each
variant's size against the platform budget and the run's estimated cost.

What it does not reproduce: the script's stages, which ThinnestAI holds as separate steps in a
form it does not publish, and its knowledge search (no tool is offered, so a question the
pinned facts do not answer is answered without one).

Hard rule 6: stdout and `--out` carry counts, check kinds, the spoken-style list words a
reply used and token counts, never a reply's text. `--out` belongs in a scratch directory.
It spends real money: it refuses without `--spend`, refuses when the estimate is over
`--max-inr`, and stops at `--max-inr`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import sys
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import httpx
from apps.api.agents.starters import starter_for
from apps.api.agents.turn_checks import formal_swaps, turn_problems
from apps.api.billing import rates
from apps.api.compliance.disclosure import ai_disclosure_for, recording_notice_for
from apps.workers.chat import ChatLeg, ChatMessage, ChatOutcome, TokenUsage, complete
from calevate_shared.call_script import (
    CallScript,
    CollectField,
    compile_call_script,
    native_steps,
    splice_quick_facts,
    without_outline,
)
from calevate_shared.engine import (
    LAYER_SEPARATOR,
    THINNEST_OWN_MODEL_DEFAULT,
    AgentConfig,
    DisclosurePosture,
    compose_first_utterance,
    engine_prompt_layers,
    google_openai_compat_base_url,
    introduction_salutation,
    notice_fields,
)
from calevate_shared.languages import find_language
from calevate_shared.spoken_style import (
    AVOID_FORMS,
    PACK_FORMS,
    PROMPT_FILLERS,
    LanguageStyle,
    PackChoice,
    candidate_prompt_examples,
    example_sentence,
    register_guidance,
    style_for,
)

ROOT: Final = Path(__file__).resolve().parent.parent
FIXTURE: Final = ROOT / "scripts" / "fixtures" / "register_eval_callers.json"
VENDOR_RULES: Final = ROOT / "docs" / "vendor" / "thinnest-speaking-rules-2026-10-18.md"

LANGUAGES: Final = ("te-IN", "hi-IN", "en-IN")
#: English replies were clean on production (19 Oct 2026), so it runs only when asked.
DEFAULT_LANGUAGES: Final = ("te-IN", "hi-IN")
CANNOT_RUN: Final = 2
#: The check kinds the report always lists, in this order; any other kind seen is added after.
REPORTED_KINDS: Final = (
    "formal_words",
    "spoken_number",
    "money_digits",
    "symbols",
    "brackets",
    "wrong_language",
    "too_long",
    "several_questions",
)
#: A variant WINS only if its textbook-word share falls and none of these rises.
MUST_NOT_RISE: Final = ("wrong_language", "too_long")
#: Concurrent requests: enough to finish a run in minutes, few enough not to meet a rate limit.
CONCURRENCY: Final = 4
TIMEOUT_S: Final = 30.0
RETRIES: Final = 3

#: What a candidate register layer may change, one switch each, combined with "+":
#: `positive` lists the words callers use instead of `not "X" but "Y"` pairs, so no textbook
#: word is quoted to the model (a forbidden word named in a prompt can come back more often,
#: Mann et al. 2025, arXiv:2511.12381); `persona` opens the section with how the staff talk;
#: `examples` adds the language's drafted examples awaiting the founder
#: (`spoken_style.candidate_prompt_examples`); `late` moves the section after the client's
#: script, the latest place it may sit: the confidentiality and truthful-answer blocks stay
#: last, and ThinnestAI's speaking rules follow everything we send.
VARIANT_FEATURES: Final = ("positive", "persona", "examples", "late")
CURRENT: Final = "current"
PACK_PREFIX: Final = "pack-"
#: The suffix that names each way of listing the words not to say; none means a plain list.
AVOID_SUFFIX: Final = {"list": "", "pairs": "-pairs", "none": "-noavoid"}
#: The founder's two questions (19 Oct 2026), crossed: which instruction language the model
#: follows, and whether naming the words not to say helps or primes them.
DEFAULT_VARIANTS: Final = (
    CURRENT,
    *(f"{PACK_PREFIX}{form}{AVOID_SUFFIX[avoid]}" for form in PACK_FORMS for avoid in AVOID_FORMS),
)
PERSONA_LINE: Final = (
    "Talk like the shop's own staff talking to a regular customer on the phone: the everyday "
    "words and English words callers use, never the written or newsreader form."
)
REGISTER_HEADER: Final = "--- SPOKEN REGISTER ---"

#: The cost estimate before a run (an ESTIMATE, not a price): characters per input token and
#: output tokens per reply, from the production run of 19 Oct 2026 (founder-relayed: a Telugu
#: request was about 2.2k tokens for 8.4k characters, and 300 replies cost about ₹17).
#: Rounded towards a higher estimate.
CHARS_PER_TOKEN: Final = Decimal("3.8")
OUTPUT_TOKENS_PER_REPLY: Final = 80


@dataclass(frozen=True, slots=True)
class CrossCase:
    primary: str
    extra: tuple[str, ...]
    callers: str
    lines: int


@dataclass(frozen=True, slots=True)
class Fixture:
    business: str
    collect: tuple[CollectField, ...]
    pinned: tuple[tuple[str, str], ...]
    positive_extra: Mapping[str, tuple[str, ...]]
    callers: Mapping[str, tuple[str, ...]]
    cross: tuple[CrossCase, ...] = ()


def load_fixture(path: Path = FIXTURE) -> Fixture:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Fixture(
        business=raw["business"],
        collect=tuple(CollectField(**row) for row in raw["collect"]),
        pinned=tuple((q, a) for q, a in raw["pinned"]),
        positive_extra={tag: tuple(words) for tag, words in raw["positive_extra"].items()},
        callers={tag: tuple(lines) for tag, lines in raw["callers"].items()},
        cross=tuple(
            CrossCase(c["primary"], tuple(c["extra"]), c["callers"], int(c["lines"]))
            for c in raw.get("cross", ())
        ),
    )


def vendor_rules(path: Path = VENDOR_RULES) -> str:
    """ThinnestAI's speaking rules, the quoted paragraph of the verbatim record."""
    quoted = [
        line[2:] for line in path.read_text(encoding="utf-8").splitlines() if line[:2] == "> "
    ]
    return " ".join(quoted).strip()


# --- the reference agents -------------------------------------------------------------------


def reference_agent(language: str, fixture: Fixture, extra: Sequence[str] = ()) -> AgentConfig:
    """The retail inbound starter in `language`, as a shop would publish it on day one, with
    its pinned facts, both notices on, and `extra` as its other languages. Its opening line is
    the one said after the AI notice's introduction where the language has one (D-865)."""
    starter = starter_for("retail", "answer_calls")
    script: CallScript = starter.call_script(business=fixture.business, language=language)
    script = script.model_copy(
        update={
            "opening_line": starter.opening_for(
                fixture.business,
                language,
                introduced=introduction_salutation(language) is not None,
            )
        }
    )
    body = splice_quick_facts(compile_call_script(script, collect=fixture.collect), fixture.pinned)
    name = f"{fixture.business} receptionist"
    posture = DisclosurePosture(
        ai_disclosure_line=ai_disclosure_for(
            language=language, business=fixture.business, name=name
        ),
        ai_disclosure_enabled=True,
        recording_notice_line=recording_notice_for(language=language),
        recording_notice_enabled=True,
    )
    return AgentConfig(
        tenant_id="register-eval",
        agent_id=f"register-eval-{language}",
        name=name,
        business=fixture.business,
        direction="inbound",
        language_primary=language,
        languages_extra=list(extra),
        system_prompt=without_outline(body),
        **notice_fields(posture, call_is_recorded=True),
        call_is_recorded=True,
        facts_in_knowledge=True,
        knowledge_tool="search_knowledge",
        script_steps=native_steps(script),
    )


def platform_only(language: str, extra: Sequence[str] = ()) -> AgentConfig:
    """The platform layers alone, as `tests/agent_prompt_budget_test.py` measures them."""
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="A",
        business="Raghava Organics",
        direction="inbound",
        language_primary=language,
        languages_extra=list(extra),
        system_prompt="",
        opening_line="",
        call_is_recorded=True,
        facts_in_knowledge=True,
        knowledge_tool="search_knowledge",
    )


# --- variants -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Variant:
    """`current`, a register candidate built from `features`, or a language-pack form."""

    name: str
    features: frozenset[str] = frozenset()
    pack: PackChoice | None = None


def parse_variant(spec: str) -> Variant:
    """`current`, `pack-<form>[-pairs|-noavoid]`, or features joined with `+`; ValueError
    names what is unknown."""
    spec = spec.strip()
    if spec == CURRENT:
        return Variant(CURRENT)
    if spec.startswith(PACK_PREFIX):
        for form in PACK_FORMS:
            for avoid, suffix in AVOID_SUFFIX.items():
                if spec == f"{PACK_PREFIX}{form}{suffix}":
                    return Variant(spec, pack=PackChoice(form=form, avoid=avoid))  # type: ignore[arg-type]
        raise ValueError(f"unknown pack variant {spec!r}; choose from {DEFAULT_VARIANTS[1:]}")
    features = frozenset(part.strip() for part in spec.split("+") if part.strip())
    unknown = sorted(features - set(VARIANT_FEATURES))
    if unknown or not features:
        raise ValueError(f"unknown variant feature(s) {unknown}; choose from {VARIANT_FEATURES}")
    return Variant(variant_name(features), features=features)


def parse_variants(spec: str) -> list[Variant]:
    """A comma list, `current` first whether named or not, each once."""
    variants = [parse_variant(part) for part in spec.split(",") if part.strip()]
    names: list[str] = []
    out: list[Variant] = [Variant(CURRENT)]
    for variant in variants:
        if variant.name != CURRENT and variant.name not in names:
            names.append(variant.name)
            out.append(variant)
    return out


def variant_name(features: Iterable[str]) -> str:
    chosen = [f for f in VARIANT_FEATURES if f in set(features)]
    return "+".join(chosen) or CURRENT


def spoken_words(style: LanguageStyle, extra: Sequence[str]) -> list[str]:
    """The spoken side of the prompt swaps and of `extra` (formal words in the list), in
    order, without duplicates or the bracketed instructions ("(leave it out)")."""
    by_formal = dict(style.word_swaps)
    pairs = [*style.prompt_swaps, *((f, by_formal[f]) for f in extra if f in by_formal)]
    seen: list[str] = []
    for _formal, spoken in pairs:
        if not spoken.startswith("(") and spoken not in seen:
            seen.append(spoken)
    return seen


def _language_guidance(tag: str, features: frozenset[str], fixture: Fixture) -> str | None:
    style = style_for(tag)
    if style is None:
        return None
    if "positive" not in features:
        return register_guidance(tag)
    parts = [style.register]
    words = spoken_words(style, fixture.positive_extra.get(style.tag, ()))
    if words:
        parts.append(f"Use the words callers use: {', '.join(words)}.")
    if style.fillers:
        parts.append(
            f"Fillers, lightly: {', '.join(f.text for f in style.fillers[:PROMPT_FILLERS])}."
        )
    return " ".join(parts)


def register_layer(cfg: AgentConfig, features: frozenset[str], fixture: Fixture) -> str:
    """The SPOKEN REGISTER section with `features`; with none, exactly the shipped one."""
    lines: list[str] = [PERSONA_LINE] if "persona" in features else []
    for tag in (cfg.language_primary, *cfg.languages_extra):
        guidance = _language_guidance(tag, features, fixture)
        if guidance:
            language = find_language(tag)
            lines.append(f"{language.english_name if language else tag}: {guidance}")
        if tag != cfg.language_primary:
            continue
        style = style_for(tag)
        exchanges = list(style.prompt_examples) if style is not None else []
        if "examples" in features:
            exchanges += candidate_prompt_examples(tag)
        if exchanges:
            lines.append(example_sentence(exchanges))
    if not lines:
        return ""
    return REGISTER_HEADER + "\n" + "\n".join(lines)


def _after_style(names: Sequence[str]) -> int:
    """Where the shipped composer puts the register: after the speaking and language layers."""
    style_layers = [
        i for i, name in enumerate(names) if name in ("preamble", "how_to_speak", "languages")
    ]
    return max(style_layers, default=-1) + 1


def compose_variant(cfg: AgentConfig, variant: Variant, fixture: Fixture) -> str:
    """`compose_engine_prompt(cfg)` as `variant` changes it. A pack form is composed by the
    shipping code itself; a register candidate replaces the register layer and, for `late`,
    moves it to just before the confidentiality block. Every other layer is the shipped
    text."""
    if variant.pack is not None:
        return LAYER_SEPARATOR.join(
            text for _l, text in engine_prompt_layers(cfg, pack=variant.pack)
        )
    layers = list(engine_prompt_layers(cfg))
    if not variant.features:
        return LAYER_SEPARATOR.join(text for _layer, text in layers)
    register = register_layer(cfg, variant.features, fixture)
    names = [name for name, _text in layers]
    at = names.index("spoken_register") if "spoken_register" in names else _after_style(names)
    layers = [(name, text) for name, text in layers if name != "spoken_register"]
    if "late" in variant.features:
        at = [name for name, _text in layers].index("confidentiality")
    if register:
        layers.insert(at, ("spoken_register", register))
    return LAYER_SEPARATOR.join(text for _layer, text in layers)


# --- the cases ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Case:
    """One set of caller lines played to one agent: the agent's own language, or a caller in
    another language (`cross`)."""

    id: str
    primary: str
    extra: tuple[str, ...]
    caller_language: str
    lines: tuple[str, ...]

    @property
    def cross(self) -> bool:
        return self.caller_language != self.primary or bool(self.extra)


def cases_for(fixture: Fixture, languages: Sequence[str], *, cross: bool) -> list[Case]:
    """One case per language, then the fixture's cross-language cases."""
    out = [Case(tag, tag, (), tag, fixture.callers[tag]) for tag in languages]
    if cross:
        for c in fixture.cross:
            with_extra = "+".join((c.primary, *c.extra))
            out.append(
                Case(
                    f"{with_extra}>{c.callers}",
                    c.primary,
                    c.extra,
                    c.callers,
                    fixture.callers[c.callers][: c.lines],
                )
            )
    return out


# --- scoring --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Reply:
    """One scored reply. No text: the kinds it showed and the list words it used."""

    variant: str
    case: str
    line: int
    run: int
    kinds: tuple[str, ...] = ()
    formal: tuple[str, ...] = ()
    finish_reason: str | None = None
    tokens_in: int = 0
    tokens_cached: int = 0
    tokens_out: int = 0
    error: str | None = None


_LETTERS: Final = {"te": re.compile("[ఀ-౿]"), "hi": re.compile("[ऀ-ॿ]")}


def reply_language(text: str) -> str:
    """The language a reply is in by its letters: Telugu or Devanagari script, whichever it
    has more of, else English. A code-mixed reply keeps its language's letters."""
    counts = {tag: len(pattern.findall(text)) for tag, pattern in _LETTERS.items()}
    tag, count = max(counts.items(), key=lambda kv: kv[1])
    return tag if count else "en"


def score_reply(
    text: str, *, caller_said: str, language: str, cross: bool = False
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The check kinds `text` shows (each once) and the spoken-style list words it used.

    `language` is the caller's. In a cross-language case a reply in another language is
    `wrong_language` and nothing else, because the other checks read the caller's word list
    and would find nothing to fault in a reply that is not in it."""
    if cross and reply_language(text) != language.split("-")[0]:
        return ("wrong_language",), ()
    kinds = sorted(
        {p.kind for p in turn_problems(text, caller_said=caller_said, language=language)}
    )
    formal = tuple(word for word, _spoken in formal_swaps(text, language))
    return tuple(kinds), formal


@dataclass(slots=True)
class Tally:
    replies: int = 0
    errors: int = 0
    cut_off: int = 0
    clean: int = 0
    kinds: dict[str, int] = field(default_factory=dict)
    formal_words: dict[str, int] = field(default_factory=dict)


def tally(replies: Iterable[Reply]) -> dict[str, dict[str, Tally]]:
    """Per variant and case: replies scored, failed requests, replies cut at the ceiling,
    replies with no problem, and per kind and per list word the replies showing it."""
    out: dict[str, dict[str, Tally]] = {}
    for reply in replies:
        t = out.setdefault(reply.variant, {}).setdefault(reply.case, Tally())
        if reply.error is not None:
            t.errors += 1
            continue
        t.replies += 1
        t.cut_off += reply.finish_reason == "length"
        t.clean += not reply.kinds
        for kind in reply.kinds:
            t.kinds[kind] = t.kinds.get(kind, 0) + 1
        for word in set(reply.formal):
            t.formal_words[word] = t.formal_words.get(word, 0) + 1
    return out


def rate(count: int, total: int) -> float:
    return count / total if total else 0.0


def difference_interval(a: int, n_a: int, b: int, n_b: int) -> tuple[float, float, float]:
    """b/n_b - a/n_a with its 95% normal-approximation interval (Wald, unpooled)."""
    p_a, p_b = rate(a, n_a), rate(b, n_b)
    if not n_a or not n_b:
        return p_b - p_a, -1.0, 1.0
    se = math.sqrt(p_a * (1 - p_a) / n_a + p_b * (1 - p_b) / n_b)
    diff = p_b - p_a
    return diff, diff - 1.96 * se, diff + 1.96 * se


# --- cost -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Price:
    """₹ per 1,000 tokens, and where the figure came from."""

    input: Decimal
    output: Decimal
    cached: Decimal | None
    basis: str


def price_for(model: str) -> Price:
    """The attested rate when an operator entered one, else the catalogue list price; the
    report names which, since only the first is a billed figure."""
    try:
        per_ktok = rates.llm_inr_per_ktok(model)
        basis = "attested"
    except ValueError:
        per_ktok = rates.own_model_reference_inr_per_ktok(model)
        basis = "catalogue list price (not attested)"
    cached_per_10k = rates.cached_input_rate_exact(model)
    cached = None if cached_per_10k is None else cached_per_10k / Decimal(10)
    return Price(per_ktok["in"], per_ktok["out"], cached, basis)


def cost_inr(replies: Iterable[Reply], price: Price) -> Decimal:
    """Uncached input at the input rate, cached input at the cached rate when one is attested
    (else at the input rate), output at the output rate."""
    total = Decimal(0)
    for r in replies:
        cached_rate = price.cached if price.cached is not None else price.input
        total += (
            Decimal(r.tokens_in - r.tokens_cached) * price.input
            + Decimal(r.tokens_cached) * cached_rate
            + Decimal(r.tokens_out) * price.output
        ) / Decimal(1000)
    return total


# --- running --------------------------------------------------------------------------------

Ask = Callable[[Sequence[ChatMessage], int], Awaitable[ChatOutcome]]


def google_ask(api_key: str, model: str) -> Ask:
    leg = ChatLeg(
        url=f"{google_openai_compat_base_url()}/chat/completions",
        api_key=api_key,
        wire_model=model,
        dialect="google",
    )

    async def ask(messages: Sequence[ChatMessage], max_tokens: int) -> ChatOutcome:
        for attempt in range(RETRIES):
            try:
                return await complete(leg, messages, timeout_s=TIMEOUT_S, max_tokens=max_tokens)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in (429, 500, 503) or attempt == RETRIES - 1:
                    raise
            await asyncio.sleep(2 ** (attempt + 1))
        raise RuntimeError("unreachable")

    return ask


@dataclass(frozen=True, slots=True)
class Plan:
    variant: str
    case: Case
    system: str
    first_words: str
    max_tokens: int
    #: How many times each line is asked.
    runs: int


def plan_for(
    case: Case, variant: Variant, fixture: Fixture, *, with_vendor: bool, runs: int
) -> Plan:
    cfg = reference_agent(case.primary, fixture, case.extra)
    system = compose_variant(cfg, variant, fixture)
    if with_vendor:
        system = f"{system}{LAYER_SEPARATOR}{vendor_rules()}"
    return Plan(
        variant=variant.name,
        case=case,
        system=system,
        first_words=compose_first_utterance(cfg),
        max_tokens=cfg.max_reply_tokens,
        runs=runs,
    )


def estimate_inr(plans: Sequence[Plan], price: Price) -> Decimal:
    """What the run should cost, from its prompts' sizes (an ESTIMATE: `CHARS_PER_TOKEN`,
    `OUTPUT_TOKENS_PER_REPLY`), at the uncached input rate."""
    total = Decimal(0)
    for plan in plans:
        for line in plan.case.lines:
            chars = len(plan.system) + len(plan.first_words) + len(line)
            tokens_in = Decimal(chars) / CHARS_PER_TOKEN
            per_reply = tokens_in * price.input + OUTPUT_TOKENS_PER_REPLY * price.output
            total += per_reply * plan.runs / Decimal(1000)
    return total


async def run(
    plans: Sequence[Plan], ask: Ask, *, price: Price, max_inr: Decimal
) -> tuple[list[Reply], bool]:
    """Every line of every plan its `runs` times, a whole run of every plan before the next,
    so a budget stop cuts every variant alike; the second value is True when it stopped."""
    gate = asyncio.Semaphore(CONCURRENCY)
    replies: list[Reply] = []
    stopped = False

    async def one(plan: Plan, line_at: int, attempt: int) -> None:
        nonlocal stopped
        async with gate:
            if cost_inr(replies, price) >= max_inr:
                stopped = True
                return
            line = plan.case.lines[line_at]
            messages = [
                {"role": "system", "content": plan.system},
                {"role": "assistant", "content": plan.first_words},
                {"role": "user", "content": line},
            ]
            reply = Reply(plan.variant, plan.case.id, line_at, attempt)
            try:
                outcome = await ask(messages, plan.max_tokens)
            except Exception as exc:  # one failed request is a count, not the end of the run
                replies.append(replace(reply, error=type(exc).__name__))
                return
            kinds, formal = score_reply(
                outcome.content,
                caller_said=line,
                language=plan.case.caller_language,
                cross=plan.case.cross,
            )
            usage = outcome.usage or TokenUsage(prompt_tokens=0, output_tokens=0)
            replies.append(
                replace(
                    reply,
                    kinds=kinds,
                    formal=formal,
                    finish_reason=outcome.finish_reason,
                    tokens_in=usage.prompt_tokens,
                    tokens_cached=usage.cached_prompt_tokens,
                    tokens_out=usage.output_tokens,
                )
            )

    await asyncio.gather(
        *(
            one(plan, line_at, attempt)
            for attempt in range(max((p.runs for p in plans), default=0))
            for plan in plans
            if attempt < plan.runs
            for line_at in range(len(plan.case.lines))
        )
    )
    return replies, stopped


# --- reports --------------------------------------------------------------------------------


def _kinds_seen(tallies: Iterable[Tally]) -> list[str]:
    seen = {kind for t in tallies for kind in t.kinds}
    return [*REPORTED_KINDS, *sorted(seen - set(REPORTED_KINDS))]


def wins(reference: Tally, candidate: Tally) -> bool:
    """The textbook-word share fell (its interval wholly below zero) and nothing in
    `MUST_NOT_RISE` rose (no interval wholly above zero)."""

    def interval(kind: str) -> tuple[float, float, float]:
        return difference_interval(
            reference.kinds.get(kind, 0),
            reference.replies,
            candidate.kinds.get(kind, 0),
            candidate.replies,
        )

    if interval("formal_words")[2] >= 0:
        return False
    return all(interval(kind)[1] <= 0 for kind in MUST_NOT_RISE)


def normalized(record: Mapping[str, Any]) -> dict[str, Any]:
    """A record as {variants, tally[variant][case]}; a D-829 record held one variant's
    tally keyed by language."""
    if "variants" in record:
        return dict(record)
    return {
        **record,
        "variants": [record["variant"]],
        "tally": {record["variant"]: record["tally"]},
    }


def render(record: Mapping[str, Any]) -> str:
    """One table per case: each kind, each variant's share, and every variant but the first
    against the first, with a 95% interval; `down`/`UP` where the interval excludes zero,
    and the variants that WIN."""
    record = normalized(record)
    variants: list[str] = list(record["variants"])
    tallies = {
        v: {case: Tally(**t) for case, t in record["tally"].get(v, {}).items()} for v in variants
    }
    cases: list[str] = []
    for v in variants:
        cases += [c for c in tallies[v] if c not in cases]
    lines = [
        f"model {record.get('model', '?')} | runs {record.get('runs', '?')} | vendor rules "
        f"{'on' if record.get('vendor_rules', True) else 'off'} | reference {variants[0]}"
    ]
    width = max(len(v) for v in variants) + 2
    for case in cases:
        present = [v for v in variants if case in tallies[v]]
        ref = tallies[variants[0]].get(case)
        lines.append("")
        lines.append(f"== {case} ==")
        for v in present:
            t = tallies[v][case]
            mark = "  WINS" if ref is not None and v != variants[0] and wins(ref, t) else ""
            lines.append(
                f"  {v:<{width}} {t.replies} replies, {t.errors} failed, {t.cut_off} cut, "
                f"clean {rate(t.clean, t.replies):.0%}{mark}"
            )
        for kind in _kinds_seen(tallies[v][case] for v in present):
            lines.append(f"  {kind}")
            for v in present:
                t = tallies[v][case]
                count = t.kinds.get(kind, 0)
                cell = f"    {v:<{width}} {rate(count, t.replies):6.1%}"
                if ref is not None and v != variants[0]:
                    diff, low, high = difference_interval(
                        ref.kinds.get(kind, 0), ref.replies, count, t.replies
                    )
                    flag = "down" if high < 0 else "UP" if low > 0 else ""
                    cell += f"  {diff:+.1%} [{low:+.1%}, {high:+.1%}] {flag}"
                lines.append(cell.rstrip())
        for v in present:
            words = tallies[v][case].formal_words
            if words:
                top = sorted(words.items(), key=lambda kv: (-kv[1], kv[0]))
                lines.append(f"  list words, {v}: " + ", ".join(f"{w} {n}" for w, n in top))
    if "cost_inr" in record:
        lines.append("")
        lines.append(
            f"tokens in {record['tokens_in']} (cached {record['tokens_cached']}), out "
            f"{record['tokens_out']}; cost ₹{record['cost_inr']} at the {record['price_basis']}"
            + ("; STOPPED AT THE BUDGET" if record["stopped_at_budget"] else "")
        )
    return "\n".join(lines)


def merged(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Several records as one, for `--compare`: variants in the order given, a later
    record's variant of the same name renamed with its file position."""
    out: dict[str, Any] = {"variants": [], "tally": {}}
    for at, record in enumerate(map(normalized, records)):
        for v in record["variants"]:
            name = v if v not in out["tally"] else f"{v}#{at + 1}"
            out["variants"].append(name)
            out["tally"][name] = record["tally"][v]
        out.setdefault("model", record.get("model"))
        out.setdefault("runs", record.get("runs"))
        out.setdefault("vendor_rules", record.get("vendor_rules", True))
    return out


def record_of(
    replies: Sequence[Reply],
    *,
    variants: Sequence[str],
    model: str,
    runs: int,
    vendor: bool,
    price: Price,
    stopped: bool,
) -> dict[str, Any]:
    tallies = tally(replies)
    return {
        "variants": list(variants),
        "model": model,
        "runs": runs,
        "vendor_rules": vendor,
        "tally": {
            v: {case: asdict(t) for case, t in sorted(tallies.get(v, {}).items())} for v in variants
        },
        "tokens_in": sum(r.tokens_in for r in replies),
        "tokens_cached": sum(r.tokens_cached for r in replies),
        "tokens_out": sum(r.tokens_out for r in replies),
        "cost_inr": str(
            cost_inr(replies, price).quantize(Decimal("0.01"), rounding=rates.ROUNDING)
        ),
        "price_basis": price.basis,
        "stopped_at_budget": stopped,
        "replies": [asdict(r) for r in replies],
    }


def sizes(fixture: Fixture, variants: Sequence[Variant]) -> str:
    """Characters per variant: each reference agent, the Telugu agent with Hindi as an extra
    language, and the platform layers alone with one and three languages (the two budget
    guards)."""
    lines = [
        "variant | "
        + " | ".join(LANGUAGES)
        + " | te+hi | platform te | platform te+hi | platform te+hi+en"
    ]
    for variant in variants:
        agents = [
            len(compose_variant(reference_agent(t, fixture), variant, fixture)) for t in LANGUAGES
        ]
        with_hindi = len(
            compose_variant(reference_agent("te-IN", fixture, ("hi-IN",)), variant, fixture)
        )
        one = len(compose_variant(platform_only("te-IN"), variant, fixture))
        two = len(compose_variant(platform_only("te-IN", ("hi-IN",)), variant, fixture))
        three = len(compose_variant(platform_only("te-IN", ("hi-IN", "en-IN")), variant, fixture))
        lines.append(
            f"{variant.name} | "
            + " | ".join(map(str, agents))
            + f" | {with_hindi} | {one} | {two} | {three}"
        )
    return "\n".join(lines)


async def _prepare() -> tuple[str | None, str]:
    """The console's settings and attested prices, as a publish reads them; the Google key
    and the in-call model."""
    from apps.api.core.platform_config import refresh
    from apps.api.core.settings import get_settings
    from apps.api.ops.pricing_snapshot import install_pricing_readers, refresh_pricing_snapshot

    await refresh(force=True)
    install_pricing_readers()
    await refresh_pricing_snapshot()
    settings = get_settings()
    return settings.gemini_api_key or None, settings.thinnest_own_model_default


def _languages(values: Sequence[str] | None) -> list[str]:
    chosen = [t.strip() for v in values or () for t in v.split(",") if t.strip()]
    unknown = sorted(set(chosen) - set(LANGUAGES))
    if unknown:
        raise ValueError(f"unknown language(s) {unknown}; choose from {LANGUAGES}")
    return list(dict.fromkeys(chosen)) or list(DEFAULT_LANGUAGES)


def _estimate_line(plans: Sequence[Plan], price: Price) -> str:
    replies = sum(p.runs * len(p.case.lines) for p in plans)
    estimate = estimate_inr(plans, price).quantize(Decimal("0.01"), rates.ROUNDING)
    return (
        f"{replies} replies over {len({p.variant for p in plans})} variant(s) and "
        f"{len({p.case.id for p in plans})} case(s); estimated ₹{estimate} at the "
        f"{price.basis} (ESTIMATE)"
    )


async def evaluate(
    plans: Sequence[Plan],
    ask: Ask,
    *,
    price: Price,
    max_inr: Decimal,
    model: str,
    vendor: bool,
    say: Callable[[str], None] = print,
) -> dict[str, Any] | str:
    """The whole invocation under one budget: the estimate first, a refusal when it is over
    `max_inr`, else every plan and the record of what came back."""
    say(_estimate_line(plans, price))
    if estimate_inr(plans, price) > max_inr:
        return f"CANNOT RUN: the estimate is over --max-inr {max_inr}"
    replies, stopped = await run(plans, ask, price=price, max_inr=max_inr)
    return record_of(
        replies,
        variants=list(dict.fromkeys(p.variant for p in plans)),
        model=model,
        runs=max((p.runs for p in plans), default=0),
        vendor=vendor,
        price=price,
        stopped=stopped,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.register_eval", description=__doc__)
    parser.add_argument(
        "--variants",
        default=",".join(DEFAULT_VARIANTS),
        help="comma list; current is always run first",
    )
    parser.add_argument(
        "--language",
        action="append",
        help=f"comma list or repeatable, from {LANGUAGES}; default {','.join(DEFAULT_LANGUAGES)}",
    )
    parser.add_argument("--no-cross", action="store_true", help="skip the cross-language cases")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--cross-runs", type=int, default=2, help="runs of each cross case")
    parser.add_argument("--model", help="default: the console's in-call model")
    parser.add_argument("--no-vendor-rules", action="store_true")
    parser.add_argument("--spend", action="store_true", help="required: the run calls a paid model")
    parser.add_argument("--max-inr", type=Decimal, default=Decimal(80))
    parser.add_argument("--out", type=Path, help="write the record (counts only) here")
    parser.add_argument("--dry-run", action="store_true", help="sizes and the estimate, no model")
    parser.add_argument("--compare", type=Path, nargs="+", help="records side by side")
    args = parser.parse_args(argv)

    if args.compare is not None:
        records = [json.loads(p.read_text(encoding="utf-8")) for p in args.compare]
        print(render(merged(records)))
        return 0
    try:
        variants = parse_variants(args.variants)
        languages = _languages(args.language)
    except ValueError as exc:
        print(exc)
        return CANNOT_RUN
    fixture = load_fixture()
    vendor = not args.no_vendor_rules
    plans = [
        plan_for(
            case,
            variant,
            fixture,
            with_vendor=vendor,
            runs=args.cross_runs if case.cross else args.runs,
        )
        for variant in variants
        for case in cases_for(fixture, languages, cross=not args.no_cross)
    ]
    if args.dry_run:
        print(sizes(fixture, variants))
        print(_estimate_line(plans, price_for(args.model or THINNEST_OWN_MODEL_DEFAULT)))
        return 0
    if not args.spend:
        print("CANNOT RUN: every reply is a paid model call; add --spend")
        return CANNOT_RUN
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    async def spend() -> dict[str, Any] | str:
        key, default_model = await _prepare()
        if key is None:
            return "CANNOT RUN: no Google key in this environment or the ops console"
        model = args.model or default_model
        return await evaluate(
            plans,
            google_ask(key, model),
            price=price_for(model),
            max_inr=args.max_inr,
            model=model,
            vendor=vendor,
        )

    record = asyncio.run(spend())
    if isinstance(record, str):
        print(record)
        return CANNOT_RUN
    print(render(record))
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", "utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
