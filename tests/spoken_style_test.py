"""The spoken-style table and its published layer (D-744), with no database.

Ranked by what a failure costs:

1. The spoken data must not contain its own formal words or the punctuation a voice
   stumbles on: every agent line, opening and filler is something an agent may copy.
2. The published layer must replace, retire, add and approve exactly as the founder did,
   and a language is `native_reviewed` only when every entry in force is approved.
3. The prompt carries only the short list; the writers get everything.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from calevate_shared import spoken_style
from calevate_shared.spoken_style import (
    PublishedEntry,
    PublishedLanguage,
    caller_guidance,
    default_entries,
    example_exchange,
    install_published,
    normalize_value,
    register_guidance,
    style_for,
    writer_guidance,
)

TE = "te-IN"

#: What a voice must never be handed in a line an agent may copy (founder, 11 Oct 2026).
#: Em dash, en dash, slash, brackets, ellipsis and the rupee sign; then "...", a spaced
#: hyphen, and a dotted abbreviation such as "Dr. ".
FORBIDDEN = re.compile("[\u2014\u2013/()\\[\\]\u2026\u20b9]" r"|\.\.\.|\s-\s|\b[A-Z][a-z]{0,3}\.\s")


@pytest.fixture(autouse=True)
def _no_layer() -> Iterator[None]:
    install_published(None)
    yield
    install_published(None)


def _spoken_lines(tag: str) -> list[str]:
    style = style_for(tag)
    assert style is not None
    lines = [t.text for turns in style.examples.values() for t in turns if t.speaker == "agent"]
    lines += list((style.openings or {}).values())
    lines += [f.text for f in style.fillers]
    lines += [spoken for _, spoken in style.word_swaps if not spoken.startswith("(")]
    return lines


def test_telugu_has_the_expanded_list() -> None:
    style = style_for(TE)
    assert style is not None
    assert len(style.word_swaps) >= 60
    formal = [f for f, _ in style.word_swaps]
    assert len(formal) == len(set(formal)), "a formal word is listed twice"
    # The founder's production line, 11 Oct 2026.
    for word in ("ధన్యవాదాలు", "మరియు", "కొనుగోలు", "సుమారు", "అవసరం", "సహజంగా పండించిన"):
        assert word in formal, word
    assert len(style.fillers) >= 10 and style.number_rules and style.punctuation
    for tag in ("అవునా", "కదా", "ఏంటి", "సరే అండి", "హా", "అంటే", "ఒక్క సెకండ్ అండి", "ఓకే"):
        assert any(f.text == tag for f in style.fillers), tag


@pytest.mark.parametrize("tag", [TE, "hi-IN"])
def test_spoken_lines_never_use_their_own_formal_words(tag: str) -> None:
    style = style_for(tag)
    assert style is not None
    for line in _spoken_lines(tag):
        for formal, _ in style.word_swaps:
            assert formal not in line, f"{formal!r} in {line!r}"


@pytest.mark.parametrize("tag", [TE, "hi-IN"])
def test_spoken_lines_are_written_for_a_voice(tag: str) -> None:
    for line in _spoken_lines(tag):
        assert not FORBIDDEN.search(line), line
    style = style_for(tag)
    assert style is not None
    for turns in style.examples.values():
        for turn in turns:
            if turn.speaker == "agent":
                # No digits from the agent: prices, quantities and times are said in words.
                assert not re.search(r"\d", turn.text), turn.text
                assert turn.text.rstrip()[-1] in ".?!।", turn.text


def test_every_business_type_has_a_telugu_example() -> None:
    from typing import get_args

    from apps.api.admin.routes import Vertical

    style = style_for(TE)
    assert style is not None
    for vertical in get_args(Vertical):
        assert example_exchange(TE, vertical), vertical
    # A custom business falls back to the neutral set.
    assert example_exchange(TE, "custom") == style.examples["_default"]


def test_everything_ships_unreviewed() -> None:
    for tag in spoken_style.languages():
        style = style_for(tag)
        assert style is not None and style.review == "needs_native_review", tag


def test_the_prompt_carries_only_the_short_list() -> None:
    style = style_for(TE)
    assert style is not None
    guidance = register_guidance(TE)
    assert guidance is not None
    assert 10 <= len(style.prompt_swaps) < len(style.word_swaps)
    assert '"thanks అండి"' in guidance
    # A swap that is not in the prompt list stays out of the prompt.
    left_out = next(f for f, _ in style.word_swaps if (f, _) not in style.prompt_swaps)
    assert f'"{left_out}"' not in guidance
    assert "అవునా" in guidance
    assert len(guidance) < 1_500


def test_the_writers_get_everything() -> None:
    guide = writer_guidance(TE, "retail")
    style = style_for(TE)
    assert style is not None
    for formal, spoken in style.word_swaps:
        assert f"{formal} -> {spoken}" in guide
    assert "one twenty rupees" in guide and "Writing for a voice" in guide
    # This business type's example first, then the neutral one: two or three in all.
    assert guide.index("(retail)") < guide.index("(any business)")
    assert guide.count("Agent:") >= 4
    callers = caller_guidance(TE, "retail")
    assert "ఎండు మిర్చి" in callers and "Numbers" in callers
    assert writer_guidance("xx-XX") == "" and caller_guidance("xx-XX") == ""


def test_the_published_layer_edits_retires_adds_and_stamps() -> None:
    file_swaps = dict(style_for(TE).word_swaps)  # type: ignore[union-attr]
    entries = {
        ("swap", "ధన్యవాదాలు"): PublishedEntry(
            value={"formal": "ధన్యవాదాలు", "spoken": "thank you అండి", "in_prompt": True},
            approved=True,
        ),
        ("swap", "ధర"): PublishedEntry(value=None, approved=True),
        ("filler", "added-1"): PublishedEntry(value={"text": "అబ్బా", "use": "x"}, approved=True),
    }
    install_published(
        {TE: PublishedLanguage(entries=entries, reviewed_by="Sri", reviewed_on="2026-10-11")}
    )
    style = style_for(TE)
    assert style is not None
    swaps = dict(style.word_swaps)
    assert swaps["ధన్యవాదాలు"] == "thank you అండి"
    assert "ధర" not in swaps and "ధర" in file_swaps
    assert style.fillers[-1].text == "అబ్బా"
    # Three approvals out of a hundred-odd entries: still awaiting review.
    assert style.review == "needs_native_review"
    assert '"thank you అండి"' in (register_guidance(TE) or "")


def test_a_language_is_reviewed_only_when_every_entry_in_force_is_approved() -> None:
    entries = {
        (e.kind, e.key): PublishedEntry(value=dict(e.value), approved=True)
        for e in default_entries(TE)
    }
    install_published(
        {TE: PublishedLanguage(entries=entries, reviewed_by="Sri", reviewed_on="2026-10-11")}
    )
    style = style_for(TE)
    assert style is not None
    assert (style.review, style.reviewed_by, style.reviewed_on) == (
        "native_reviewed",
        "Sri",
        "2026-10-11",
    )
    install_published(None)
    assert style_for(TE).review == "needs_native_review"  # type: ignore[union-attr]


def test_values_are_checked_before_they_are_stored() -> None:
    assert normalize_value("swap", "మరియు", {"formal": "మరియు", "spoken": " ఇంకా "}) == {
        "formal": "మరియు",
        "spoken": "ఇంకా",
        "in_prompt": False,
    }
    with pytest.raises(ValueError):
        normalize_value("swap", "మరియు", {"formal": "అవసరం", "spoken": "x"})
    with pytest.raises(ValueError):
        normalize_value("register", "other", {"text": "x"})
    with pytest.raises(ValueError):
        normalize_value("filler", "Bad Key!", {"text": "x"})
    with pytest.raises(ValueError):
        normalize_value("example", "retail", {"turns": [{"speaker": "bot", "text": "x"}]})
    with pytest.raises(ValueError):
        normalize_value("number_rule", "n1", {"text": "x" * 401})
    assert normalize_value(
        "example", "retail", {"turns": [{"speaker": "agent", "text": "సరే అండి."}]}
    ) == {"turns": [{"speaker": "agent", "text": "సరే అండి."}]}


def test_test_callers_are_written_in_the_caller_style() -> None:
    from apps.api.agents.test_conversations import AgentBrief
    from apps.workers.agent_test_ai import GENERATE_INSTRUCTION, brief_text

    brief = AgentBrief(
        business_name="Raghava Organics",
        business_type="retail",
        direction="inbound",
        language=TE,
        register="",
        word_swaps=(),
        steps=(),
        opening_line="",
        ending="",
        objections=(),
        pinned_facts=(),
        knowledge_titles=(),
        lead_fields=(),
        hand_over="off",
        call_backs=False,
    )
    text = brief_text(brief)
    assert "Tags and fillers callers use" in text and "కదా" in text
    assert "How callers sound" in text and "ఎండు మిర్చి" in text
    assert "Follow the spoken style in the brief" in GENERATE_INSTRUCTION
