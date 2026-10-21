"""How often a Telugu agent's replies use textbook words, measured on ThinnestAI's own stack
through test chat, one temporary agent per prompt variant (D-837).

    uv run python -m scripts.register_chat_eval --agent <uuid> --dry-run
    uv run python -m scripts.register_chat_eval --agent <uuid> --spend --out /reg/chat.json
    uv run python -m scripts.register_chat_eval --agent <uuid> --spend --variants A,B --replies 40
    uv run python -m scripts.register_chat_eval --cleanup

`scripts/register_eval` sends OUR copy of the prompt straight to Gemini. A real conversation
runs ThinnestAI's composition instead: its own rules before our fenced instructions
(`docs/vendor/thinnest-replies-2026-10-12.md` §18), its model call, its history handling. This
measures there. For each variant it creates a copy of the named source agent in OUR DEVELOPER
workspace through the adapter's own `create_agent`, the path a free-trial agent is published
on (`trial_agent_in_developer_workspace`, D-697), so every field of the body is what a
publish sends and only the instructions differ; it gives the copy the source's [T0 FACTS]
block as its facts document; it plays the same Telugu practice callers to every copy through
`test_chat`; and it deletes every copy in a `finally`. `--cleanup` deletes any copy a killed
run left behind, found by `EVAL_PREFIX` and our name tag.

Nothing is written to the source agent's tenant: its row is read, never updated, and no
route, knowledge or action row is made for a copy.

Variants (`VARIANTS`), each a change to what the model reads and nothing else; the
confidentiality and truthful-answer blocks are never touched:

- A: the production prompt.
- B: no ban lists: the SPOKEN REGISTER `not "X" but "Y"` sentence and HOW TO SPEAK's "never
  formal or written-style words" clause are removed.
- C: one positive Tenglish line, its words read from `spoken_style.json`'s Telugu
  `word_swaps` spoken side (`allow_words`).
- D: two example calls in place of the script's [EXAMPLE CALL], every line taken from
  `spoken_style.json` (`EXAMPLE_CALLS`; DRAFT, founder and native review).
- E: B, C and D together.

Scoring: `spoken_guard.textbook_words(reply, "te-IN")`, the matcher the test loop uses. Per
variant: the share of replies with at least one textbook word and its 95% Wilson interval,
textbook words per reply, and the commonest words. A variant WINS only when its interval
lies wholly below the interval of A.

What test chat is not: it is the agent's website chat (`thinnest-findings/mirror/snapshots/
2026-10-18/pages/api-reference/agents/test-chat.md:7`), so ThinnestAI composes its chat
wrapper, not necessarily the call one, and "a chat reply keeps the model's default" thinking
level where a call sends minimal (§18, VENDOR-STATED). With the console switch
`thinnest_test_chat_call_mode` on, every reply asks Test Chat's call mode instead: the call
prompt, the call's model and, on our Gemini key, its thinking level, though not the voice or
the hearing (§21, VENDOR-STATED, D-847). It "needs calling set up on the agent", and a copy
holds no number, so a copy it refuses counts each reply as failed with
`engine_test_call_not_set_up`. The record names the mode. The copies hold no hand-over, no
in-call actions and the client's knowledge only as the [T0 FACTS] text.

It spends money: ₹0.02 a reply on an own-model agent (`TEST_CHAT_REPLY_INR`), plus the
Gemini tokens on our Google key, which this does not price. It prints the estimate and
refuses without `--spend`. Hard rule 6: the output and `--out` carry counts and list words,
never a reply's text.
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import math
import re
import sys
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Protocol

from apps.api.agents.test_conversations import standard_scenarios
from apps.api.engine.test_chat import TestChatTurn
from apps.api.engine.thinnest import INSTRUCTIONS_MAX_CHARS, ThinnestEngine
from apps.workers.agent_test_conversations import PAUSE_S
from calevate_shared.call_script import EXAMPLE_HEADER
from calevate_shared.engine import (
    CLIENT_SCRIPT_CLOSE,
    CLIENT_SCRIPT_OPEN,
    CONFIDENTIALITY_RULE,
    LAYER_SEPARATOR,
    AgentConfig,
    EngineAgentRef,
    KBSourceRef,
    PromptLayer,
    compose_engine_prompt,
    engine_prompt_layers,
    truthful_answer_directive,
)
from calevate_shared.spoken_guard import textbook_words
from calevate_shared.spoken_style import shipped_pack_choice, style_for

LANGUAGE: Final = "te-IN"
#: What every eval agent's name starts with; `--cleanup` deletes by it.
EVAL_PREFIX: Final = "TELUGUEVAL"
#: The tenant id an eval copy is named under, so its name tag can never be a real agent's.
EVAL_TENANT: Final = "register-chat-eval"
CANNOT_RUN: Final = 2
DEFAULT_REPLIES: Final = 60
#: ₹ per test-chat reply on an agent answering on our model key, `llm` or `llm_voice`
#: (VERIFIED-VENDOR-DOCS: snapshots/2026-10-18/pages/api-reference/agents/test-chat.md:174-190;
#: ThinnestAI email of 19 Oct 2026, docs/vendor/thinnest-replies-2026-10-12.md §18).
TEST_CHAT_REPLY_INR: Final = Decimal("0.02")
#: Wilson score interval at 95%.
Z: Final = 1.96
DRAFT_NOTE: Final = "DRAFT — founder/native review"


# --- variants -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Variant:
    key: str
    title: str
    no_bans: bool = False
    allow_list: bool = False
    examples: bool = False


VARIANTS: Final = {
    v.key: v
    for v in (
        Variant("A", "current production prompt"),
        Variant("B", "no ban lists", no_bans=True),
        Variant("C", "Tenglish allow-list", allow_list=True),
        Variant("D", "two example calls (DRAFT)", examples=True),
        Variant("E", "B+C+D", no_bans=True, allow_list=True, examples=True),
    )
}
BASELINE: Final = "A"

#: HOW TO SPEAK's register bullet starts with this; B keeps its language and "uhm" halves.
BAN_BULLET_START: Final = "- Match the caller's language and register;"
NO_BAN_BULLET: Final = '- Match the caller\'s language; never "uhm".'
#: The `not "X" but "Y"` sentence `spoken_style.register_guidance` writes into each language's
#: register line, up to the fillers sentence that follows it or the end of the line.
_SWAP_SENTENCE: Final = re.compile(r" ?Spoken words: .*?\.(?= Fillers, lightly:|$)", re.M)
_LATIN: Final = re.compile(r"[A-Za-z]+(?: [A-Za-z]+)*")

#: The two example calls of D, every line copied from `spoken_style.json`'s Telugu
#: `language_pack.exchanges` (tests/register_chat_eval_test.py proves each is there), none
#: of them a line the practice callers say.
EXAMPLE_CALLS: Final[tuple[tuple[tuple[str, str], ...], ...]] = (
    (
        ("caller", "మీ products గురించి details చెప్తారా?"),
        ("agent", "తప్పకుండా అండి, ఏ product గురించి కావాలి?"),
        ("caller", "దీని rate ఎంత అండి?"),
        ("agent", "ఒక్క సెకండ్ అండి, price చూసి చెప్తాను."),
        ("caller", "ఓకే, thanks అండి."),
        ("agent", "సరే అండి, ఇంకేమైనా కావాలంటే call చేయండి."),
    ),
    (
        ("caller", "quality ఎలా ఉంటుంది?"),
        ("agent", "ఏ item గురించి అడుగుతున్నారు అండి? దాని details చూసి చెప్తాను."),
        ("caller", "నాకు delivery కావాలి."),
        ("agent", "సరే అండి, మీది ఏ area?"),
    ),
)
#: The compiler's own lead for the section (`call_script._compile_v2`).
EXAMPLE_LEAD: Final = f"{EXAMPLE_HEADER} Copy the style, never the facts or the Caller lines."


def parse_variants(spec: str) -> list[Variant]:
    """A comma list of keys, A first whether named or not, each once; ValueError names an
    unknown key."""
    keys = [part.strip().upper() for part in spec.split(",") if part.strip()]
    unknown = sorted(set(keys) - set(VARIANTS))
    if unknown:
        raise ValueError(f"unknown variant(s) {unknown}; choose from {sorted(VARIANTS)}")
    return [VARIANTS[k] for k in dict.fromkeys([BASELINE, *keys])]


def allow_words(tag: str = LANGUAGE) -> tuple[list[str], list[str]]:
    """The spoken side of the language's `word_swaps`: the English words in it (in English
    letters, each once, in list order) and the forms written wholly in Telugu. An entry in
    brackets is an instruction ("(leave it out)"), not a word, and is skipped."""
    style = style_for(tag)
    english: list[str] = []
    native: list[str] = []
    for _formal, spoken in style.word_swaps if style is not None else ():
        if spoken.startswith("("):
            continue
        latin = _LATIN.findall(spoken)
        targets, words = (english, latin) if latin else (native, [spoken])
        targets.extend(w for w in words if w not in targets)
    return english, native


def allow_line(tag: str = LANGUAGE) -> str:
    english, native = allow_words(tag)
    return (
        "Telugu: talk the way callers do, mixing in the English words they use, written in "
        f"English letters inside Telugu sentences: {', '.join(english)}. Use the everyday "
        f"spoken forms: {', '.join(native)}."
    )


def _without_bans(layer: PromptLayer, text: str) -> str:
    if layer == "how_to_speak":
        return "\n".join(
            NO_BAN_BULLET if line.startswith(BAN_BULLET_START) else line
            for line in text.splitlines()
        )
    if layer == "spoken_register":
        return _SWAP_SENTENCE.sub("", text)
    return text


def with_example_calls(body: str) -> str:
    """`body` with its [EXAMPLE CALL] section replaced by `EXAMPLE_CALLS`, or with them added
    last, where the compiler puts the section, when it has none."""
    said = {"caller": "Caller", "agent": "You"}
    calls = "\n\n".join(
        "\n".join(f"{said[speaker]}: {text}" for speaker, text in call) for call in EXAMPLE_CALLS
    )
    section = f"{EXAMPLE_LEAD}\n{calls}".splitlines()
    lines = body.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(EXAMPLE_HEADER)), None)
    if start is None:
        return "\n\n".join(part for part in (body.strip(), "\n".join(section)) if part)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    tail = ["", *lines[end:]] if end < len(lines) else []
    return "\n".join([*lines[:start], *section, *tail])


def variant_instructions(cfg: AgentConfig, variant: Variant) -> str:
    """`compose_engine_prompt(cfg)` as `variant` changes it, over the same named layers."""
    if variant.examples:
        cfg = cfg.model_copy(update={"system_prompt": with_example_calls(cfg.system_prompt)})
    layers = list(engine_prompt_layers(cfg))
    if variant.no_bans:
        layers = [(name, _without_bans(name, text)) for name, text in layers]
    if variant.allow_list:
        names = [name for name, _text in layers]
        if "spoken_register" in names:
            at = names.index("spoken_register")
            layers[at] = ("spoken_register", f"{layers[at][1]}\n{allow_line(cfg.language_primary)}")
        else:
            at = names.index("business_facts")
            layers.insert(at, ("spoken_register", f"--- SPOKEN REGISTER ---\n{allow_line()}"))
    return LAYER_SEPARATOR.join(text for _name, text in layers if text)


def client_script_lines(prompt: str) -> set[str]:
    """The non-blank lines inside the client fence."""
    if CLIENT_SCRIPT_OPEN not in prompt:
        return set()
    inside = prompt.split(CLIENT_SCRIPT_OPEN, 1)[1].split(CLIENT_SCRIPT_CLOSE, 1)[0]
    return {line for line in inside.splitlines() if line.strip()}


def variant_diff(base: str, changed: str) -> list[str]:
    """The lines `changed` adds to or removes from `base`. A removed line of the client's
    script is counted, not printed: it is the owner's text."""
    owners = client_script_lines(base)
    out: list[str] = []
    withheld = 0
    for line in difflib.ndiff(base.splitlines(), changed.splitlines()):
        if line.startswith("- ") and line[2:] in owners:
            withheld += 1
        elif line.startswith(("- ", "+ ")):
            out.append(line)
    if withheld:
        out.append(f"- ({withheld} line(s) of the client's script, not shown)")
    return out


# --- the practice callers -------------------------------------------------------------------

#: Probes left out: "stop calling" could put a number on the developer workspace's
#: do-not-call list through the platform's own tool, and the copies hold no hand-over.
SKIPPED_PROBES: Final = frozenset({"stop_calling", "person"})
#: Ordering and delivery turns, each line copied from `spoken_style.json`'s Telugu data.
EXTRA_CONVERSATIONS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("ordering", ("order ఇవ్వాలి.", "Powder. ఒక kg ఎంత?")),
    ("delivery", ("సరే. Home delivery ఉంటుందా?", "నా order ఇంకా రాలేదు.")),
)


def conversations() -> list[tuple[str, tuple[str, ...]]]:
    """The test loop's standard Telugu callers (product and price, the AI and recording
    probes, the turn-shape callers, not interested), then ordering and delivery."""
    standard = [
        (s.key, s.turns)
        for s in standard_scenarios(LANGUAGE, "both")
        if s.probe not in SKIPPED_PROBES
    ]
    return [*standard, *EXTRA_CONVERSATIONS]


# --- scoring --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Reply:
    """One reply, as counts and list words; never its text."""

    variant: str
    conversation: str
    turn: int
    words: tuple[str, ...] = ()
    cut_short: bool = False
    empty: bool = False
    error: str | None = None
    #: The mode the reply ran in (`TestChatTurn.mode`): `chat`, `call`, or None when call
    #: mode was asked for and not confirmed.
    mode: str | None = None


def wilson(k: int, n: int) -> tuple[float, float]:
    """The 95% Wilson score interval for k of n; (0, 1) for no observations."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denominator = 1 + Z * Z / n
    centre = (p + Z * Z / (2 * n)) / denominator
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


@dataclass(slots=True)
class Tally:
    replies: int = 0
    with_textbook: int = 0
    textbook_words: int = 0
    errors: int = 0
    cut_short: int = 0
    empty: int = 0
    words: dict[str, int] = field(default_factory=dict)

    @property
    def share(self) -> float:
        return self.with_textbook / self.replies if self.replies else 0.0

    @property
    def per_reply(self) -> float:
        return self.textbook_words / self.replies if self.replies else 0.0

    @property
    def interval(self) -> tuple[float, float]:
        return wilson(self.with_textbook, self.replies)


def tally(replies: Sequence[Reply]) -> dict[str, Tally]:
    out: dict[str, Tally] = {}
    for reply in replies:
        t = out.setdefault(reply.variant, Tally())
        if reply.error is not None:
            t.errors += 1
            continue
        t.replies += 1
        t.cut_short += reply.cut_short
        t.empty += reply.empty
        t.with_textbook += bool(reply.words)
        t.textbook_words += len(reply.words)
        for word in reply.words:
            t.words[word] = t.words.get(word, 0) + 1
    return out


def wins(baseline: Tally, candidate: Tally) -> bool:
    """The candidate's interval lies wholly below the baseline's."""
    return candidate.replies > 0 and candidate.interval[1] < baseline.interval[0]


def render(record: dict[str, Any]) -> str:
    tallies = {v: Tally(**t) for v, t in record["tally"].items()}
    base = tallies.get(BASELINE)
    lines = [
        f"source agent {record['source_agent']} | model {record['model']} | "
        f"{record['replies_per_variant']} replies per variant | test chat mode "
        f"{record.get('test_chat_mode', 'chat')}",
        f"{'variant':<34} {'replies':>7} {'failed':>6} {'with textbook':>13} "
        f"{'95% Wilson':>15} {'words/reply':>11}",
    ]
    for key in record["variants"]:
        t = tallies[key]
        low, high = t.interval
        mark = "  WINS" if base is not None and key != BASELINE and wins(base, t) else ""
        title = f"{key} {VARIANTS[key].title}"
        lines.append(
            f"{title:<34} {t.replies:>7} {t.errors:>6} {t.share:>13.1%} "
            f"{f'[{low:.1%}, {high:.1%}]':>15} {t.per_reply:>11.2f}{mark}"
        )
    for key in record["variants"]:
        top = Counter(tallies[key].words).most_common(8)
        if top:
            lines.append(f"  {key} words: " + ", ".join(f"{w} {n}" for w, n in top))
    winners = [k for k in record["variants"] if k != BASELINE and base and wins(base, tallies[k])]
    lines.append(
        "verdict: "
        + (
            f"{', '.join(winners)} WIN(S) against A"
            if winners
            else "no variant's interval clears A's; no win"
        )
    )
    if "D" in record["variants"] or "E" in record["variants"]:
        lines.append(f"D and E carry example calls marked {DRAFT_NOTE}.")
    return "\n".join(lines)


# --- running --------------------------------------------------------------------------------


class EvalEngine(Protocol):
    """The adapter calls this eval makes, so a test can stand in for the vendor."""

    async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef: ...

    async def attach_kb(
        self, ref: EngineAgentRef, source: KBSourceRef, *, agent: AgentConfig | None = None
    ) -> str: ...

    async def test_chat(
        self,
        ref: EngineAgentRef,
        message: str,
        *,
        session: str | None = None,
        call_mode: bool = False,
    ) -> TestChatTurn: ...

    async def delete_agent(self, ref: EngineAgentRef) -> None: ...


@dataclass(frozen=True, slots=True)
class Source:
    """The agent the copies are made from: its config as a publish builds it, and the
    [T0 FACTS] block of its applied script (None without one)."""

    agent_id: str
    config: AgentConfig
    facts: str | None


def eval_config(source: AgentConfig, variant: Variant, run_tag: str) -> AgentConfig:
    """The copy of `source` for `variant`: in the developer workspace, with no number,
    hand-over or in-call actions, named `EVAL_PREFIX` and under `EVAL_TENANT`, so its name
    tag is its own."""
    return source.model_copy(
        update={
            "tenant_id": EVAL_TENANT,
            "agent_id": f"{run_tag}-{variant.key}",
            "name": f"{EVAL_PREFIX} {variant.key} {run_tag}",
            "engine_workspace": None,
            "has_phone_number": False,
            "handoff": None,
            "action_tools": (),
        }
    )


def refusal(source: AgentConfig) -> str | None:
    """Why `source` cannot be measured here, or None."""
    if source.language_primary != LANGUAGE:
        return f"CANNOT RUN: the source agent's main language is not {LANGUAGE}"
    if not source.engine_own_model:
        return "CANNOT RUN: the source agent does not answer on our own model"
    if shipped_pack_choice(LANGUAGE) is not None:
        return "CANNOT RUN: a Telugu language pack has shipped; B and C edit the register section"
    return None


Pause = Callable[[], Awaitable[None]]


async def _sleep() -> None:
    await asyncio.sleep(PAUSE_S)


def _code(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    return code if isinstance(code, str) else type(exc).__name__


async def converse(
    engine: EvalEngine,
    refs: dict[str, EngineAgentRef],
    *,
    replies: int,
    pause: Pause,
    say: Callable[[str], None] = print,
    call_mode: bool = False,
) -> list[Reply]:
    """`replies` replies from every variant's agent, one conversation at a time per variant in
    turn, so time-of-day drift falls on every variant alike. A failed turn ends that
    conversation and counts towards `replies`, so a dead agent cannot loop for ever. With
    `call_mode` every turn asks Test Chat's call mode (D-847)."""
    scripts = conversations()
    out: list[Reply] = []
    done = dict.fromkeys(refs, 0)
    index = 0
    while any(n < replies for n in done.values()):
        key, turns = scripts[index % len(scripts)]
        index += 1
        for variant, ref in refs.items():
            session: str | None = None
            for at, line in enumerate(turns):
                if done[variant] >= replies:
                    break
                await pause()
                done[variant] += 1
                try:
                    turn = await engine.test_chat(ref, line, session=session, call_mode=call_mode)
                except Exception as exc:  # a failed reply is a count, not the end of the run
                    out.append(Reply(variant, key, at, error=_code(exc)))
                    break
                session = turn.session or session
                out.append(
                    Reply(
                        variant,
                        key,
                        at,
                        words=tuple(w for w, _ in textbook_words(turn.reply, LANGUAGE)),
                        cut_short=turn.failed_part_way,
                        empty=not turn.reply.strip(),
                        mode=turn.mode,
                    )
                )
        say(f"{min(done.values())} of {replies} replies per variant")
    return out


async def delete_all(engine: EvalEngine, refs: Sequence[EngineAgentRef]) -> list[str]:
    """Delete each copy; the refs that could not be deleted."""
    left: list[str] = []
    for ref in refs:
        try:
            await engine.delete_agent(ref)
        except Exception as exc:  # best effort: report it, keep deleting the rest
            print(f"could not delete eval agent {ref} ({_code(exc)}); run --cleanup")
            left.append(ref)
    return left


async def evaluate(
    engine: EvalEngine,
    source: Source,
    variants: Sequence[Variant],
    *,
    replies: int,
    run_tag: str,
    pause: Pause = _sleep,
    create_scope: Callable[[], AbstractContextManager[None]] = nullcontext,
    say: Callable[[str], None] = print,
    call_mode: bool = False,
) -> dict[str, Any]:
    """Create one copy per variant, talk to them, delete them whatever happens, and return
    the record. `create_scope` is the context the creates run in (the developer-workspace
    permission in production). `call_mode` asks Test Chat's call mode (D-847), and the record
    names the mode asked and the modes the replies ran in, so runs in different modes are
    never read as one series."""
    refs: dict[str, EngineAgentRef] = {}
    try:
        for variant in variants:
            cfg = eval_config(source.config, variant, run_tag)
            with create_scope():
                ref = await engine.create_agent(cfg)
            refs[variant.key] = ref
            if source.facts:
                await engine.attach_kb(
                    ref,
                    KBSourceRef(
                        kb_id=f"facts:{run_tag}:{variant.key}",
                        title="Business facts",
                        text=source.facts,
                        language=LANGUAGE,
                    ),
                )
            say(f"created {cfg.name}")
        got = await converse(
            engine, refs, replies=replies, pause=pause, say=say, call_mode=call_mode
        )
    finally:
        left = await delete_all(engine, list(refs.values()))
    tallies = tally(got)
    return {
        "eval": "register_chat_eval",
        "decision": "D-837",
        "source_agent": source.agent_id,
        "model": source.config.engine_own_model,
        "language": LANGUAGE,
        "replies_per_variant": replies,
        "test_chat_mode": "call" if call_mode else "chat",
        "modes_seen": sorted({str(r.mode) for r in got if r.error is None}),
        "variants": [v.key for v in variants],
        "variant_titles": {v.key: v.title for v in variants},
        "example_calls": DRAFT_NOTE,
        "tally": {v.key: asdict(tallies.get(v.key, Tally())) for v in variants},
        "replies": [asdict(r) for r in got],
        "not_deleted": left,
        "estimated_inr": str(estimate_inr(len(variants), replies)),
    }


def estimate_inr(variants: int, replies: int) -> Decimal:
    """ThinnestAI's test-chat charge only; Gemini's tokens on our key are not priced here."""
    return TEST_CHAT_REPLY_INR * variants * replies


def estimate_line(variants: int, replies: int) -> str:
    return (
        f"{variants * replies} test-chat replies ({variants} variant(s) x {replies}): "
        f"₹{estimate_inr(variants, replies)} at ₹{TEST_CHAT_REPLY_INR} a reply, plus the "
        "Gemini tokens on our Google key, which this does not price"
    )


def dry_run_report(source: Source, variants: Sequence[Variant]) -> str:
    base = variant_instructions(source.config, VARIANTS[BASELINE])
    owner_textbook = sum(1 for line in client_script_lines(base) if textbook_words(line, LANGUAGE))
    lines = [
        f"instructions limit {INSTRUCTIONS_MAX_CHARS} characters; ThinnestAI adds its own "
        "text before them",
        f"client-script lines holding a textbook word (left as the owner wrote them): "
        f"{owner_textbook}",
    ]
    for variant in variants:
        text = variant_instructions(source.config, variant)
        kept = (
            CONFIDENTIALITY_RULE in text
            and truthful_answer_directive(call_is_recorded=source.config.call_is_recorded) in text
        )
        lines.append("")
        lines.append(
            f"== {variant.key} {variant.title}: {len(text)} characters "
            f"({len(text) - len(base):+d} against A), platform rules "
            f"{'kept' if kept else 'MISSING'}"
            + ("" if len(text) <= INSTRUCTIONS_MAX_CHARS else " OVER THE LIMIT")
        )
        lines += [f"  {line}" for line in variant_diff(base, text)]
    return "\n".join(lines)


# --- the operator's entry points ------------------------------------------------------------


async def load_source(agent_id: uuid.UUID) -> Source:
    """The source agent's config as a publish builds it, after the console settings and the
    published spoken style are loaded, read in its tenant and never written."""
    from apps.api.agents.service import _load_agent, _to_config
    from apps.api.agents.t0_block import block_of
    from apps.api.core.platform_config import refresh
    from apps.api.db.session import tenant_session
    from apps.api.engine import get_engine
    from apps.api.ops.spoken_style_store import refresh_spoken_style

    from scripts.prompt_size import tenant_of

    await refresh(force=True)
    await refresh_spoken_style()
    tenant_id = await tenant_of(agent_id)
    if tenant_id is None:
        raise LookupError("agent not found")
    async with tenant_session(tenant_id) as session:
        row = await _load_agent(session, tenant_id, agent_id)
        config = _to_config(tenant_id, row, engine=get_engine(), handoff=None)
    return Source(agent_id=str(agent_id), config=config, facts=block_of(row["prompt"]))


def instructions_by_copy(variants: Sequence[Variant], run_tag: str) -> Callable[[AgentConfig], str]:
    """The adapter's instruction composer for this run: a copy's variant, found by the
    `agent_id` `eval_config` gives it; any other agent exactly as production composes it."""
    variant_of = {f"{run_tag}-{v.key}": v for v in variants}

    def compose(cfg: AgentConfig) -> str:
        chosen = variant_of.get(cfg.agent_id)
        return compose_engine_prompt(cfg) if chosen is None else variant_instructions(cfg, chosen)

    return compose


class VariantThinnestEngine(ThinnestEngine):
    """The production adapter with one difference: `instructions` come from `compose`.

    A subclass here rather than a composer parameter on `ThinnestEngine`, so the adapter
    every client path runs has no way to send a prompt `compose_engine_prompt` did not
    build (hard rule 5; `scripts/check_compliance_invariants`). Every other field of the
    body is exactly what a publish sends."""

    def __init__(self, *, compose: Callable[[AgentConfig], str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._eval_compose = compose

    def _agent_body(self, cfg: AgentConfig) -> dict[str, Any]:
        body = super()._agent_body(cfg)
        instructions = self._eval_compose(cfg)
        if len(instructions) > INSTRUCTIONS_MAX_CHARS:
            raise ValueError(f"variant instructions exceed {INSTRUCTIONS_MAX_CHARS} characters")
        body["instructions"] = instructions
        return body


def _thinnest(compose: Callable[[AgentConfig], str] = compose_engine_prompt) -> ThinnestEngine:
    """The production adapter, credentials from the settings, instructions from `compose`."""
    from apps.api.core.settings import get_settings

    settings = get_settings()
    return VariantThinnestEngine(
        api_key=settings.thinnest_api_key,
        base_url=settings.thinnest_api_base_url,
        compose=compose,
    )


async def cleanup() -> int:
    engine = _thinnest()
    refs = await engine.developer_agents_named(EVAL_PREFIX)
    left = await delete_all(engine, refs)
    print(f"{len(refs) - len(left)} eval agent(s) deleted, {len(left)} left")
    return 0 if not left else CANNOT_RUN


async def spend(
    agent_id: uuid.UUID, variants: Sequence[Variant], replies: int
) -> dict[str, Any] | str:
    from apps.api.core.settings import get_settings
    from apps.api.engine.thinnest_workspace import trial_agent_in_developer_workspace

    if get_settings().engine != "thinnest":
        return "CANNOT RUN: this deployment's engine is not ThinnestAI"
    source = await load_source(agent_id)
    refused = refusal(source.config)
    if refused is not None:
        return refused
    run_tag = uuid.uuid4().hex[:8]
    return await evaluate(
        _thinnest(instructions_by_copy(variants, run_tag)),
        source,
        variants,
        replies=replies,
        run_tag=run_tag,
        create_scope=trial_agent_in_developer_workspace,
        call_mode=get_settings().thinnest_test_chat_call_mode,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.register_chat_eval", description=__doc__)
    parser.add_argument("--agent", type=uuid.UUID, help="the Telugu source agent's id")
    parser.add_argument("--variants", default=",".join(VARIANTS), help="comma list of A-E")
    parser.add_argument("--replies", type=int, default=DEFAULT_REPLIES, help="per variant")
    parser.add_argument("--spend", action="store_true", help="required: every reply is billed")
    parser.add_argument("--dry-run", action="store_true", help="sizes and diffs, no vendor call")
    parser.add_argument("--cleanup", action="store_true", help="delete left-over eval agents")
    parser.add_argument("--out", type=Path, help="write the record (counts only) here")
    args = parser.parse_args(argv)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    if args.cleanup:
        return asyncio.run(cleanup())
    try:
        variants = parse_variants(args.variants)
    except ValueError as exc:
        print(exc)
        return CANNOT_RUN
    if args.agent is None or args.replies < 1:
        print("CANNOT RUN: name the source agent with --agent and at least one reply")
        return CANNOT_RUN
    if args.dry_run:
        source = asyncio.run(load_source(args.agent))
        print(refusal(source.config) or "source agent: measurable")
        print(dry_run_report(source, variants))
        print(estimate_line(len(variants), args.replies))
        return 0
    print(estimate_line(len(variants), args.replies))
    if not args.spend:
        print("CANNOT RUN: every reply is a billed test chat; add --spend")
        return CANNOT_RUN
    record = asyncio.run(spend(args.agent, variants, args.replies))
    if isinstance(record, str):
        print(record)
        return CANNOT_RUN
    print(render(record))
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", "utf-8")
    return 0 if not record["not_deleted"] else CANNOT_RUN


if __name__ == "__main__":
    sys.exit(main())
