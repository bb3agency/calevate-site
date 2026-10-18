"""The in-call register eval (`scripts/register_eval.py`, D-829), run offline.

No model is called: a fake `ask` stands in at the one seam the harness sends requests
through, so what is proven is the prompt it composes, the scoring and the arithmetic. A
model's rates come only from an operator run with a key.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

import pytest
from apps.workers.chat import ChatMessage, ChatOutcome, TokenUsage
from calevate_shared import engine
from calevate_shared.engine import (
    CONFIDENTIALITY_RULE,
    TRUTHFUL_ANSWER_MARKER,
    compose_engine_prompt,
    truthful_answer_directive,
)
from calevate_shared.spoken_style import candidate_prompt_examples, style_for
from scripts import register_eval as harness

FIXTURE = harness.load_fixture()
ALL = frozenset(harness.VARIANT_FEATURES)


def _configs() -> list[engine.AgentConfig]:
    return [
        *(harness.reference_agent(tag, FIXTURE) for tag in harness.LANGUAGES),
        harness.platform_only("te-IN"),
        harness.platform_only("te-IN", ("hi-IN", "en-IN")),
    ]


def test_the_current_variant_is_the_shipped_prompt() -> None:
    for cfg in _configs():
        assert harness.compose_variant(cfg, frozenset(), FIXTURE) == compose_engine_prompt(cfg)
        assert harness.register_layer(cfg, frozenset(), FIXTURE) == engine._register_section(cfg)


@pytest.mark.parametrize("variant", ["positive", "persona", "examples", "late", "+".join(ALL)])
def test_a_variant_changes_only_the_register_layer(variant: str) -> None:
    features = harness.parse_variant(variant)
    for cfg in _configs():
        prompt = harness.compose_variant(cfg, features, FIXTURE)
        truthful = truthful_answer_directive(call_is_recorded=True)
        assert prompt.endswith(truthful)
        assert CONFIDENTIALITY_RULE in prompt
        assert prompt.index(CONFIDENTIALITY_RULE) < prompt.index(TRUTHFUL_ANSWER_MARKER)
        assert prompt.startswith(engine.platform_rules_preamble(cfg))
        shipped = compose_engine_prompt(cfg).replace(engine._register_section(cfg), "")
        variant_register = harness.register_layer(cfg, features, FIXTURE)
        assert " ".join(prompt.replace(variant_register, "").split()) == " ".join(shipped.split())


def test_late_puts_the_register_just_before_the_confidentiality_block() -> None:
    cfg = harness.reference_agent("te-IN", FIXTURE)
    prompt = harness.compose_variant(cfg, frozenset({"late"}), FIXTURE)
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
    for spoken in ("thanks అండి", "help", "details", "product", "area", "quantity"):
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


def test_the_fixture_is_a_fixed_realistic_set() -> None:
    for tag in harness.LANGUAGES:
        lines = FIXTURE.callers[tag]
        assert 15 <= len(lines) <= 25
        assert len(set(lines)) == len(lines)
        style = style_for(tag)
        assert style is not None
        swaps = dict(style.word_swaps)
        assert [w for w in FIXTURE.positive_extra[tag] if w not in swaps] == []


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


async def test_a_run_tallies_rates_tokens_and_cost() -> None:
    plan = harness.plan_for("te-IN", frozenset(), FIXTURE, with_vendor=True)
    assert plan.system.endswith(harness.vendor_rules())
    plan = harness.Plan(
        plan.language, plan.system, plan.first_words, plan.max_tokens, plan.lines[:3]
    )
    replies_by_line = {
        plan.lines[0]: ChatOutcome(
            content="ధన్యవాదాలు అండి, ఉంది.",
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=1000, output_tokens=20, cached_prompt_tokens=400),
        ),
        plan.lines[1]: ChatOutcome(
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

    price = harness.Price(Decimal("0.02"), Decimal("0.12"), Decimal("0.002"), "test")
    replies, stopped = await harness.run([plan], ask, runs=2, price=price, max_inr=Decimal(20))
    assert not stopped and len(replies) == 6 and len(seen) == 6
    assert [m["role"] for m in seen[0]] == ["system", "assistant", "user"]
    assert seen[0][1]["content"] == plan.first_words
    t = harness.tally(replies)["te-IN"]
    assert (t.replies, t.errors, t.cut_off, t.clean) == (4, 2, 2, 2)
    assert t.kinds == {"formal_words": 2}
    assert t.formal_words == {"ధన్యవాదాలు": 2}
    # 2 x (600 x 0.02 + 400 x 0.002 + 20 x 0.12) + 2 x (1000 x 0.02 + 20 x 0.12), per 1,000
    assert harness.cost_inr(replies, price) == Decimal("0.0752")
    record = harness.record_of(
        replies, variant="current", model="m", runs=2, vendor=True, price=price, stopped=False
    )
    assert "ధన్యవాదాలు అండి" not in json.dumps(record, ensure_ascii=False)
    assert "formal_words" in harness.render(record)


async def test_the_budget_stops_the_run() -> None:
    plan = harness.plan_for("en-IN", frozenset(), FIXTURE, with_vendor=False)

    async def ask(messages: Sequence[ChatMessage], max_tokens: int) -> ChatOutcome:
        return ChatOutcome(
            content="Sure.", usage=TokenUsage(prompt_tokens=100_000, output_tokens=0)
        )

    price = harness.Price(Decimal("1"), Decimal("1"), None, "test")
    replies, stopped = await harness.run([plan], ask, runs=3, price=price, max_inr=Decimal(150))
    assert stopped
    assert len(replies) < 3 * len(plan.lines)


def test_compare_marks_a_measured_drop(tmp_path: Path) -> None:
    def record(formal: int) -> dict[str, object]:
        t = harness.Tally(replies=60, clean=60 - formal, kinds={"formal_words": formal})
        return {"variant": "v", "runs": 3, "tally": {"te-IN": vars_of(t)}}

    def vars_of(t: harness.Tally) -> dict[str, object]:
        from dataclasses import asdict

        return asdict(t)

    text = harness.render_compare(record(27), record(6))
    line = next(row for row in text.splitlines() if "formal_words" in row)
    assert "45.0%" in line and "10.0%" in line and line.rstrip().endswith("down")
    diff, low, high = harness.difference_interval(27, 60, 25, 60)
    assert low < diff < high and low < 0 < high


def test_it_refuses_to_spend_without_being_told_to(capsys: pytest.CaptureFixture[str]) -> None:
    assert harness.main(["--language", "te-IN"]) == harness.CANNOT_RUN
    assert "--spend" in capsys.readouterr().out
    assert harness.main(["--variant", "louder"]) == harness.CANNOT_RUN
    assert harness.main(["--dry-run"]) == 0
    assert "platform te+hi+en" in capsys.readouterr().out
