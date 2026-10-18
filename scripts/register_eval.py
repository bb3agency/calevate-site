"""How often the in-call model's replies break the speaking checks, offline (D-829).

    uv run python -m scripts.register_eval --dry-run                      # sizes only, no model
    uv run python -m scripts.register_eval --spend --out /ci/reg/base.json
    uv run python -m scripts.register_eval --spend --variant positive+late --language te-IN \
        --out /ci/reg/positive-late.json
    uv run python -m scripts.register_eval --compare /ci/reg/base.json /ci/reg/positive-late.json

The agent test runs mix three things that make a before-and-after unreadable: the callers
change between runs, each line is tried once, and a reply fails on any one of a dozen checks.
This measures one thing, the speaking register, on a fixed set:

- the REAL in-call system prompt, `compose_engine_prompt` over the retail starter of a
  reference shop with its pinned facts (`scripts/fixtures/register_eval_callers.json`), one per
  language, followed by ThinnestAI's own speaking rules, which it reads to the model after
  our instructions (`docs/vendor/thinnest-speaking-rules-2026-10-18.md`, VENDOR-STATED);
- the agent's real first words, then one fixed caller line, each line asked `--runs` times;
- the in-call model (`Settings.thinnest_own_model_default`, or `--model`) on our Google key
  through the same OpenAI-compatible endpoint and transport the platform uses
  (`google_openai_compat_base_url`, `apps/workers/chat.complete`), with the agent's reply
  ceiling (`AgentConfig.max_reply_tokens`) and no temperature, as the engine is sent none;
- every reply scored by `agents/turn_checks.turn_problems`, the checks the test loop fails a
  reply on, so this harness and the product agree on what a problem is.

It reports, per language, the share of replies showing each kind of problem. `--variant`
composes a candidate register layer instead of the shipped one (`VARIANT_FEATURES`); the
confidentiality and truthful-answer layers are never touched, and `--dry-run` prints each
variant's size against the platform budget so a candidate that does not fit is visible before
it costs anything.

What it does not reproduce: the script's stages, which ThinnestAI holds as separate steps in a
form it does not publish, and its knowledge search (no tool is offered, so a question the
pinned facts do not answer is answered without one).

Hard rule 6: stdout and `--out` carry counts, check kinds, the spoken-style list words a
reply used and token counts, never a reply's text. `--out` belongs in a scratch directory.
It spends real money: it refuses without `--spend` and stops at `--max-inr`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
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
    AgentConfig,
    DisclosurePosture,
    compose_first_utterance,
    compose_opening_line,
    engine_prompt_layers,
    google_openai_compat_base_url,
)
from calevate_shared.languages import find_language
from calevate_shared.spoken_style import (
    PROMPT_FILLERS,
    LanguageStyle,
    candidate_prompt_examples,
    example_sentence,
    register_guidance,
    style_for,
)

ROOT: Final = Path(__file__).resolve().parent.parent
FIXTURE: Final = ROOT / "scripts" / "fixtures" / "register_eval_callers.json"
VENDOR_RULES: Final = ROOT / "docs" / "vendor" / "thinnest-speaking-rules-2026-10-18.md"

LANGUAGES: Final = ("te-IN", "hi-IN", "en-IN")
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
PERSONA_LINE: Final = (
    "Talk like the shop's own staff talking to a regular customer on the phone: the everyday "
    "words and English words callers use, never the written or newsreader form."
)
REGISTER_HEADER: Final = "--- SPOKEN REGISTER ---"


@dataclass(frozen=True, slots=True)
class Fixture:
    business: str
    collect: tuple[CollectField, ...]
    pinned: tuple[tuple[str, str], ...]
    positive_extra: Mapping[str, tuple[str, ...]]
    callers: Mapping[str, tuple[str, ...]]


def load_fixture(path: Path = FIXTURE) -> Fixture:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Fixture(
        business=raw["business"],
        collect=tuple(CollectField(**row) for row in raw["collect"]),
        pinned=tuple((q, a) for q, a in raw["pinned"]),
        positive_extra={tag: tuple(words) for tag, words in raw["positive_extra"].items()},
        callers={tag: tuple(lines) for tag, lines in raw["callers"].items()},
    )


def vendor_rules(path: Path = VENDOR_RULES) -> str:
    """ThinnestAI's speaking rules, the quoted paragraph of the verbatim record."""
    quoted = [
        line[2:] for line in path.read_text(encoding="utf-8").splitlines() if line[:2] == "> "
    ]
    return " ".join(quoted).strip()


# --- the reference agents -------------------------------------------------------------------


def reference_agent(language: str, fixture: Fixture) -> AgentConfig:
    """The retail inbound starter in `language`, as a shop would publish it on day one, with
    its pinned facts and both notices on."""
    script: CallScript = starter_for("retail", "answer_calls").call_script(
        business=fixture.business, language=language
    )
    body = splice_quick_facts(compile_call_script(script, collect=fixture.collect), fixture.pinned)
    posture = DisclosurePosture(
        ai_disclosure_line=ai_disclosure_for(language=language, business=fixture.business),
        ai_disclosure_enabled=True,
        recording_notice_line=recording_notice_for(language=language),
        recording_notice_enabled=True,
    )
    return AgentConfig(
        tenant_id="register-eval",
        agent_id=f"register-eval-{language}",
        name=f"{fixture.business} receptionist",
        business=fixture.business,
        direction="inbound",
        language_primary=language,
        system_prompt=without_outline(body),
        opening_line=compose_opening_line(posture, call_is_recorded=True),
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


def parse_variant(spec: str) -> frozenset[str]:
    """`current`, or features joined with `+`; ValueError names an unknown one."""
    if spec == CURRENT:
        return frozenset()
    features = frozenset(part.strip() for part in spec.split("+") if part.strip())
    unknown = sorted(features - set(VARIANT_FEATURES))
    if unknown or not features:
        raise ValueError(f"unknown variant feature(s) {unknown}; choose from {VARIANT_FEATURES}")
    return features


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


def compose_variant(cfg: AgentConfig, features: frozenset[str], fixture: Fixture) -> str:
    """`compose_engine_prompt(cfg)` with the register layer replaced and, for `late`, moved
    to just before the confidentiality block. Every other layer is the shipped text."""
    layers = list(engine_prompt_layers(cfg))
    if not features:
        return LAYER_SEPARATOR.join(text for _layer, text in layers)
    register = register_layer(cfg, features, fixture)
    names = [name for name, _text in layers]
    at = names.index("spoken_register") if "spoken_register" in names else _after_style(names)
    layers = [(name, text) for name, text in layers if name != "spoken_register"]
    if "late" in features:
        at = [name for name, _text in layers].index("confidentiality")
    if register:
        layers.insert(at, ("spoken_register", register))
    return LAYER_SEPARATOR.join(text for _layer, text in layers)


# --- scoring --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Reply:
    """One scored reply. No text: the kinds it showed and the list words it used."""

    language: str
    case: int
    run: int
    kinds: tuple[str, ...] = ()
    formal: tuple[str, ...] = ()
    finish_reason: str | None = None
    tokens_in: int = 0
    tokens_cached: int = 0
    tokens_out: int = 0
    error: str | None = None


def score_reply(
    text: str, *, caller_said: str, language: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The check kinds `text` shows (each once) and the spoken-style list words it used."""
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


def tally(replies: Iterable[Reply]) -> dict[str, Tally]:
    """Per language: replies scored, failed requests, replies cut at the ceiling, replies
    with no problem, and per kind and per list word the replies showing it."""
    out: dict[str, Tally] = {}
    for reply in replies:
        t = out.setdefault(reply.language, Tally())
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
    language: str
    system: str
    first_words: str
    max_tokens: int
    lines: tuple[str, ...]


def plan_for(
    language: str, features: frozenset[str], fixture: Fixture, *, with_vendor: bool
) -> Plan:
    cfg = reference_agent(language, fixture)
    system = compose_variant(cfg, features, fixture)
    if with_vendor:
        system = f"{system}{LAYER_SEPARATOR}{vendor_rules()}"
    return Plan(
        language=language,
        system=system,
        first_words=compose_first_utterance(cfg),
        max_tokens=cfg.max_reply_tokens,
        lines=fixture.callers[language],
    )


async def run(
    plans: Sequence[Plan], ask: Ask, *, runs: int, price: Price, max_inr: Decimal
) -> tuple[list[Reply], bool]:
    """Every line of every plan `runs` times; the second value is True when the budget
    stopped the run early."""
    gate = asyncio.Semaphore(CONCURRENCY)
    replies: list[Reply] = []
    stopped = False

    async def one(plan: Plan, case: int, attempt: int) -> None:
        nonlocal stopped
        async with gate:
            if cost_inr(replies, price) >= max_inr:
                stopped = True
                return
            line = plan.lines[case]
            messages = [
                {"role": "system", "content": plan.system},
                {"role": "assistant", "content": plan.first_words},
                {"role": "user", "content": line},
            ]
            try:
                outcome = await ask(messages, plan.max_tokens)
            except Exception as exc:  # one failed request is a count, not the end of the run
                replies.append(Reply(plan.language, case, attempt, error=type(exc).__name__))
                return
            kinds, formal = score_reply(outcome.content, caller_said=line, language=plan.language)
            usage = outcome.usage or TokenUsage(prompt_tokens=0, output_tokens=0)
            replies.append(
                Reply(
                    plan.language,
                    case,
                    attempt,
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
            one(plan, case, attempt)
            for attempt in range(runs)
            for plan in plans
            for case in range(len(plan.lines))
        )
    )
    return replies, stopped


# --- reports --------------------------------------------------------------------------------


def _kinds_seen(tallies: Iterable[Tally]) -> list[str]:
    seen = {kind for t in tallies for kind in t.kinds}
    return [*REPORTED_KINDS, *sorted(seen - set(REPORTED_KINDS))]


def render(record: Mapping[str, Any]) -> str:
    tallies = {lang: Tally(**t) for lang, t in record["tally"].items()}
    lines = [
        f"variant {record['variant']} | model {record['model']} | runs {record['runs']} | "
        f"vendor rules {'on' if record['vendor_rules'] else 'off'}"
    ]
    for lang, t in tallies.items():
        lines.append(
            f"{lang}: {t.replies} replies, {t.errors} failed, {t.cut_off} cut at the ceiling, "
            f"clean {rate(t.clean, t.replies):.0%}"
        )
        for kind in _kinds_seen([t]):
            count = t.kinds.get(kind, 0)
            lines.append(f"  {kind:<18} {count:>3}  {rate(count, t.replies):6.1%}")
        if t.formal_words:
            top = sorted(t.formal_words.items(), key=lambda kv: (-kv[1], kv[0]))
            lines.append("  list words: " + ", ".join(f"{w} {n}" for w, n in top))
    lines.append(
        f"tokens in {record['tokens_in']} (cached {record['tokens_cached']}), out "
        f"{record['tokens_out']}; cost ₹{record['cost_inr']} at the {record['price_basis']}"
        + ("; STOPPED AT THE BUDGET" if record["stopped_at_budget"] else "")
    )
    return "\n".join(lines)


def render_compare(before: Mapping[str, Any], after: Mapping[str, Any]) -> str:
    """Per language and kind: the two rates and the change with its 95% interval. A change
    whose whole interval is below zero is marked `down`, above zero `UP`."""
    lines = [f"{before['variant']} -> {after['variant']} (runs {before['runs']} / {after['runs']})"]
    for lang in sorted(set(before["tally"]) & set(after["tally"])):
        a, b = Tally(**before["tally"][lang]), Tally(**after["tally"][lang])
        lines.append(f"{lang}: {a.replies} -> {b.replies} replies")
        for kind in _kinds_seen([a, b]):
            ca, cb = a.kinds.get(kind, 0), b.kinds.get(kind, 0)
            diff, low, high = difference_interval(ca, a.replies, cb, b.replies)
            mark = "down" if high < 0 else "UP" if low > 0 else ""
            lines.append(
                f"  {kind:<18} {rate(ca, a.replies):6.1%} -> {rate(cb, b.replies):6.1%}  "
                f"{diff:+.1%} [{low:+.1%}, {high:+.1%}] {mark}"
            )
    return "\n".join(lines)


def record_of(
    replies: Sequence[Reply],
    *,
    variant: str,
    model: str,
    runs: int,
    vendor: bool,
    price: Price,
    stopped: bool,
) -> dict[str, Any]:
    return {
        "variant": variant,
        "model": model,
        "runs": runs,
        "vendor_rules": vendor,
        "tally": {lang: asdict(t) for lang, t in sorted(tally(replies).items())},
        "tokens_in": sum(r.tokens_in for r in replies),
        "tokens_cached": sum(r.tokens_cached for r in replies),
        "tokens_out": sum(r.tokens_out for r in replies),
        "cost_inr": str(cost_inr(replies, price).quantize(Decimal("0.01"))),
        "price_basis": price.basis,
        "stopped_at_budget": stopped,
        "replies": [asdict(r) for r in replies],
    }


def sizes(fixture: Fixture, variants: Sequence[frozenset[str]]) -> str:
    """Characters per variant: each reference agent, and the platform layers alone with one
    and three languages (the two budget guards)."""
    lines = ["variant | " + " | ".join(LANGUAGES) + " | platform te | platform te+hi+en"]
    for features in variants:
        agents = [
            len(compose_variant(reference_agent(t, fixture), features, fixture)) for t in LANGUAGES
        ]
        one = len(compose_variant(platform_only("te-IN"), features, fixture))
        three = len(compose_variant(platform_only("te-IN", ("hi-IN", "en-IN")), features, fixture))
        lines.append(
            f"{variant_name(features)} | " + " | ".join(map(str, agents)) + f" | {one} | {three}"
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.register_eval", description=__doc__)
    parser.add_argument(
        "--variant", default=CURRENT, help=f"{CURRENT} or {'+'.join(VARIANT_FEATURES)}"
    )
    parser.add_argument(
        "--language", action="append", choices=LANGUAGES, help="repeatable; default all"
    )
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--model", help="default: the console's in-call model")
    parser.add_argument("--no-vendor-rules", action="store_true")
    parser.add_argument("--spend", action="store_true", help="required: the run calls a paid model")
    parser.add_argument("--max-inr", type=Decimal, default=Decimal(20))
    parser.add_argument("--out", type=Path, help="write the record (counts only) here")
    parser.add_argument("--dry-run", action="store_true", help="print sizes per variant, no model")
    parser.add_argument("--compare", type=Path, nargs=2, help="two records side by side")
    args = parser.parse_args(argv)

    if args.compare is not None:
        before, after = (json.loads(p.read_text(encoding="utf-8")) for p in args.compare)
        print(render_compare(before, after))
        return 0
    try:
        features = parse_variant(args.variant)
    except ValueError as exc:
        print(exc)
        return CANNOT_RUN
    fixture = load_fixture()
    if args.dry_run:
        singles = [frozenset({f}) for f in VARIANT_FEATURES]
        print(sizes(fixture, [frozenset(), *singles, frozenset(VARIANT_FEATURES), features]))
        return 0
    if not args.spend:
        print("CANNOT RUN: every reply is a paid model call; add --spend")
        return CANNOT_RUN
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    vendor = not args.no_vendor_rules
    plans = [plan_for(t, features, fixture, with_vendor=vendor) for t in args.language or LANGUAGES]

    async def spend() -> dict[str, Any] | None:
        key, default_model = await _prepare()
        if key is None:
            return None
        model = args.model or default_model
        price = price_for(model)
        replies, stopped = await run(
            plans, google_ask(key, model), runs=args.runs, price=price, max_inr=args.max_inr
        )
        return record_of(
            replies,
            variant=variant_name(features),
            model=model,
            runs=args.runs,
            vendor=vendor,
            price=price,
            stopped=stopped,
        )

    record = asyncio.run(spend())
    if record is None:
        print("CANNOT RUN: no Google key in this environment or the ops console")
        return CANNOT_RUN
    print(render(record))
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", "utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
