"""The in-call register eval (`scripts/register_eval.py`, D-829, D-830), run offline.

No model is called: a fake `ask` stands in at the one seam the harness sends requests
through, so what is proven is the prompt it composes, the scoring, the budget and the
arithmetic. A model's rates come only from an operator run with a key.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict
from decimal import Decimal
from typing import Any

import pytest
from apps.workers.chat import ChatMessage, ChatOutcome, TokenUsage
from calevate_shared import engine
from calevate_shared.engine import (
    CONFIDENTIALITY_RULE,
    TRUTHFUL_ANSWER_MARKER,
    compose_engine_prompt,
    truthful_answer_directive,
    without_this_call,
)
from calevate_shared.spoken_style import candidate_prompt_examples, style_for
from scripts import register_eval as harness

FIXTURE = harness.load_fixture()
ALL = frozenset(harness.VARIANT_FEATURES)
CURRENT = harness.Variant(harness.CURRENT)
PACKS = [harness.parse_variant(name) for name in harness.DEFAULT_VARIANTS[1:]]
PRICE = harness.Price(Decimal("0.02"), Decimal("0.12"), Decimal("0.002"), "test")


def _configs() -> list[engine.AgentConfig]:
    return [
        *(harness.reference_agent(tag, FIXTURE) for tag in harness.LANGUAGES),
        harness.reference_agent("te-IN", FIXTURE, ("hi-IN",)),
        harness.reference_agent("hi-IN", FIXTURE, ("te-IN",)),
        harness.platform_only("te-IN"),
        harness.platform_only("te-IN", ("hi-IN", "en-IN")),
    ]


def _features(spec: str) -> harness.Variant:
    return harness.parse_variant(spec)


def test_the_current_variant_is_the_shipped_prompt() -> None:
    for cfg in _configs():
        assert harness.compose_variant(cfg, CURRENT, FIXTURE) == compose_engine_prompt(cfg)
        assert harness.register_layer(cfg, frozenset(), FIXTURE) == engine._register_section(cfg)


@pytest.mark.parametrize("variant", ["positive", "persona", "examples", "late", "+".join(ALL)])
def test_a_register_candidate_changes_only_the_register_layer(variant: str) -> None:
    chosen = _features(variant)
    for cfg in _configs():
        prompt = harness.compose_variant(cfg, chosen, FIXTURE)
        truthful = truthful_answer_directive(call_is_recorded=True)
        assert without_this_call(prompt).endswith(truthful)
        assert prompt.index(CONFIDENTIALITY_RULE) < prompt.index(TRUTHFUL_ANSWER_MARKER)
        assert prompt.startswith(engine.platform_rules_preamble(cfg))
        shipped = compose_engine_prompt(cfg).replace(engine._register_section(cfg), "")
        variant_register = harness.register_layer(cfg, chosen.features, FIXTURE)
        assert " ".join(prompt.replace(variant_register, "").split()) == " ".join(shipped.split())


#: The layers a language pack rewrites; every other one is the shipped text.
PACK_LAYERS = {"how_to_speak", "languages", "spoken_register", "business_facts"}


@pytest.mark.parametrize("variant", PACKS, ids=lambda v: v.name)
def test_a_pack_leaves_the_two_blocks_byte_identical_and_last(variant: harness.Variant) -> None:
    truthful = truthful_answer_directive(call_is_recorded=True)
    for cfg in _configs():
        prompt = harness.compose_variant(cfg, variant, FIXTURE)
        rules = without_this_call(prompt)
        assert rules.endswith(f"{CONFIDENTIALITY_RULE}{engine.LAYER_SEPARATOR}{truthful}")
        assert variant.pack is not None
        shipped = dict(engine.engine_prompt_layers(cfg))
        packed = dict(engine.engine_prompt_layers(cfg, pack=variant.pack))
        for layer in set(shipped) | set(packed):
            if layer not in PACK_LAYERS:
                assert packed.get(layer) == shipped.get(layer), layer


def test_late_puts_the_register_just_before_the_confidentiality_block() -> None:
    cfg = harness.reference_agent("te-IN", FIXTURE)
    prompt = harness.compose_variant(cfg, _features("late"), FIXTURE)
    register = engine._register_section(cfg)
    assert prompt.index(register) > prompt.index(engine.CLIENT_SCRIPT_CLOSE)
    assert prompt.index(f"{register}{engine.LAYER_SEPARATOR}{CONFIDENTIALITY_RULE}") > 0


def test_positive_names_the_spoken_words_and_quotes_no_textbook_one() -> None:
    cfg = harness.reference_agent("te-IN", FIXTURE)
    layer = harness.register_layer(cfg, frozenset({"positive"}), FIXTURE)
    style = style_for("te-IN")
    assert style is not None
    formal = [f for f, _ in style.prompt_swaps] + list(FIXTURE.positive_extra["te-IN"])
    assert [word for word in formal if word in layer] == []
    for spoken in ("థాంక్స్ అండి", "హెల్ప్", "డీటెయిల్స్", "ప్రొడక్ట్", "ఏరియా", "క్వాంటిటీ"):
        assert spoken in layer


def test_examples_adds_the_drafts_that_the_shipped_prompt_never_quotes() -> None:
    for tag in harness.LANGUAGES:
        drafts = candidate_prompt_examples(tag)
        assert len(drafts) == 4
        cfg = harness.reference_agent(tag, FIXTURE)
        layer = harness.register_layer(cfg, frozenset({"examples"}), FIXTURE)
        shipped = compose_engine_prompt(cfg)
        for exchange in drafts:
            for turn in exchange:
                assert f'"{turn.text}"' in layer
                assert f'"{turn.text}"' not in shipped


def test_variant_names_parse_and_current_always_runs_first() -> None:
    chosen = harness.parse_variants("pack-native-noavoid,current,pack-en-pairs,pack-en-pairs")
    assert [v.name for v in chosen] == ["current", "pack-native-noavoid", "pack-en-pairs"]
    assert chosen[1].pack is not None and (chosen[1].pack.form, chosen[1].pack.avoid) == (
        "native",
        "none",
    )
    assert harness.parse_variant("positive+late").features == {"positive", "late"}
    for bad in ("pack-fr", "louder"):
        with pytest.raises(ValueError):
            harness.parse_variant(bad)


def test_the_fixture_is_a_fixed_realistic_set() -> None:
    for tag in harness.LANGUAGES:
        lines = FIXTURE.callers[tag]
        assert 15 <= len(lines) <= 25
        assert len(set(lines)) == len(lines)
        style = style_for(tag)
        assert style is not None
        swaps = dict(style.word_swaps)
        assert [w for w in FIXTURE.positive_extra[tag] if w not in swaps] == []


def test_the_cross_cases_play_one_language_to_another_agent() -> None:
    cases = harness.cases_for(FIXTURE, ["te-IN"], cross=True)
    assert [c.id for c in cases] == [
        "te-IN",
        "te-IN+hi-IN>hi-IN",
        "te-IN>hi-IN",
        "hi-IN+te-IN>te-IN",
    ]
    assert [c.cross for c in cases] == [False, True, True, True]
    assert cases[2].extra == () and cases[2].lines == FIXTURE.callers["hi-IN"][:10]
    assert harness.cases_for(FIXTURE, ["hi-IN"], cross=False)[0].id == "hi-IN"


def test_the_vendor_rules_are_the_quoted_paragraph() -> None:
    rules = harness.vendor_rules()
    assert rules.startswith("You are speaking with this person on a phone call, out loud.")
    assert rules.endswith("unless they ask.")


def test_a_reply_is_scored_by_the_test_loop_checks() -> None:
    kinds, formal = harness.score_reply(
        "ధన్యవాదాలు అండి. ఒక kg ఆరు వందల రూపాయలు.", caller_said="rate ఎంత?", language="te-IN"
    )
    assert "formal_words" in kinds and "spoken_number" in kinds
    assert formal == ("ధన్యవాదాలు",)
    assert harness.score_reply("సరే అండి, మీది ఏ area?", caller_said="హలో", language="te-IN") == (
        (),
        (),
    )


def test_a_cross_reply_in_another_language_is_wrong_language_only() -> None:
    hindi_caller = "आपकी shop कहाँ है?"
    assert harness.score_reply(
        "మా shop Kukatpally లో ఉంది అండి.", caller_said=hindi_caller, language="hi-IN", cross=True
    ) == (("wrong_language",), ())
    kinds, formal = harness.score_reply(
        "जानकारी के लिए बताइए, आपको क्या चाहिए?",
        caller_said=hindi_caller,
        language="hi-IN",
        cross=True,
    )
    assert "formal_words" in kinds and formal == ("जानकारी",)
    assert [harness.reply_language(t) for t in ("Sure, which one?", "हाँ जी", "సరే")] == [
        "en",
        "hi",
        "te",
    ]


def _plan(case_id: str = "te-IN", lines: int = 3, runs: int = 2) -> harness.Plan:
    case = next(c for c in harness.cases_for(FIXTURE, ["te-IN"], cross=True) if c.id == case_id)
    case = harness.Case(case.id, case.primary, case.extra, case.caller_language, case.lines[:lines])
    return harness.plan_for(case, CURRENT, FIXTURE, with_vendor=True, runs=runs)


async def test_a_run_tallies_rates_tokens_and_cost() -> None:
    plan = _plan()
    assert plan.system.endswith(harness.vendor_rules())
    replies_by_line = {
        plan.case.lines[0]: ChatOutcome(
            content="ధన్యవాదాలు అండి, ఉంది.",
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=1000, output_tokens=20, cached_prompt_tokens=400),
        ),
        plan.case.lines[1]: ChatOutcome(
            content="సరే అండి, ఏది కావాలి?",
            finish_reason="length",
            usage=TokenUsage(prompt_tokens=1000, output_tokens=20),
        ),
    }
    seen: list[Sequence[ChatMessage]] = []

    async def ask(messages: Sequence[ChatMessage], max_tokens: int) -> ChatOutcome:
        seen.append(messages)
        assert max_tokens == plan.max_tokens
        line = messages[-1]["content"]
        if line not in replies_by_line:
            raise TimeoutError
        return replies_by_line[line]

    replies, stopped = await harness.run([plan], ask, price=PRICE, max_inr=Decimal(20))
    assert not stopped and len(replies) == 6 and len(seen) == 6
    assert [m["role"] for m in seen[0]] == ["system", "assistant", "user"]
    assert seen[0][1]["content"] == plan.first_words
    t = harness.tally(replies)["current"]["te-IN"]
    assert (t.replies, t.errors, t.cut_off, t.clean) == (4, 2, 2, 2)
    assert t.kinds == {"formal_words": 2}
    assert t.formal_words == {"ధన్యవాదాలు": 2}
    # 2 x (600 x 0.02 + 400 x 0.002 + 20 x 0.12) + 2 x (1000 x 0.02 + 20 x 0.12), per 1,000
    assert harness.cost_inr(replies, PRICE) == Decimal("0.0752")
    record = harness.record_of(
        replies, variants=["current"], model="m", runs=2, vendor=True, price=PRICE, stopped=False
    )
    assert "ధన్యవాదాలు అండి" not in json.dumps(record, ensure_ascii=False)
    assert "formal_words" in harness.render(record)


async def test_one_budget_covers_the_invocation() -> None:
    calls: list[int] = []

    async def ask(messages: Sequence[ChatMessage], max_tokens: int) -> ChatOutcome:
        calls.append(1)
        return ChatOutcome(
            content="Sure.", usage=TokenUsage(prompt_tokens=100_000, output_tokens=0)
        )

    plans = [_plan(lines=10, runs=3), _plan("te-IN>hi-IN", lines=10, runs=1)]
    said: list[str] = []
    estimate = harness.estimate_inr(plans, PRICE)
    refused = await harness.evaluate(
        plans, ask, price=PRICE, max_inr=estimate - 1, model="m", vendor=True, say=said.append
    )
    assert isinstance(refused, str) and "over --max-inr" in refused
    assert calls == [] and "40 replies" in said[0] and "ESTIMATE" in said[0]
    # Within the estimate, the spend itself still stops at the budget, cutting every plan.
    record = await harness.evaluate(
        plans, ask, price=PRICE, max_inr=estimate, model="m", vendor=True, say=said.append
    )
    assert isinstance(record, dict) and record["stopped_at_budget"]
    assert 0 < len(calls) < 40


def _tally(replies: int, **kinds: int) -> dict[str, Any]:
    return asdict(harness.Tally(replies=replies, clean=replies - sum(kinds.values()), kinds=kinds))


def test_the_multi_compare_marks_a_win_and_what_rose() -> None:
    record = {
        "variants": ["current", "pack-en", "pack-native"],
        "model": "m",
        "runs": 5,
        "vendor_rules": True,
        "tally": {
            "current": {"te-IN": _tally(100, formal_words=46, too_long=5)},
            "pack-en": {"te-IN": _tally(100, formal_words=20, too_long=6)},
            "pack-native": {"te-IN": _tally(100, formal_words=15, wrong_language=20)},
        },
    }
    text = harness.render(record)
    rows = text.splitlines()
    assert "== te-IN ==" in rows
    summary = {row.split()[0]: row for row in rows if "replies," in row}
    assert summary["pack-en"].endswith("WINS")
    assert not summary["pack-native"].endswith("WINS")  # wrong_language rose
    at = rows.index("  formal_words")
    assert rows[at + 1].split() == ["current", "46.0%"]
    assert "-26.0%" in rows[at + 2] and rows[at + 2].endswith("down")
    language = rows.index("  wrong_language")
    assert rows[language + 3].endswith("UP")


def test_compare_reads_a_d829_record_beside_a_new_one() -> None:
    legacy = {"variant": "current", "runs": 5, "tally": {"te-IN": _tally(100, formal_words=46)}}
    new = {
        "variants": ["current", "pack-en"],
        "runs": 5,
        "tally": {
            "current": {"te-IN": _tally(100, formal_words=40)},
            "pack-en": {"te-IN": _tally(100, formal_words=10)},
        },
    }
    merged = harness.merged([legacy, new])
    assert merged["variants"] == ["current", "current#2", "pack-en"]
    assert "pack-en" in harness.render(merged)


def test_it_refuses_to_spend_without_being_told_to(capsys: pytest.CaptureFixture[str]) -> None:
    assert harness.main(["--language", "te-IN"]) == harness.CANNOT_RUN
    assert "--spend" in capsys.readouterr().out
    assert harness.main(["--variants", "louder"]) == harness.CANNOT_RUN
    assert harness.main(["--language", "fr-FR"]) == harness.CANNOT_RUN
    assert harness.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "platform te+hi+en" in out and "pack-native-noavoid" in out and "estimated ₹" in out
