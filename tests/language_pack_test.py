"""Language packs (D-830): the one platform block for how an agent speaks a language.

The primary language gets its full pack and each extra language a compact one; the pack is
composed only for the register eval until the founder approves a form, and then by the same
code for every live agent (`spoken_style.shipped_pack_choice`).
"""

from __future__ import annotations

import copy
import re
from typing import Any

import pytest
from apps.api.agents.turn_checks import formal_swaps
from calevate_shared import engine, spoken_style
from calevate_shared.engine import AgentConfig, compose_engine_prompt, engine_prompt_layers
from calevate_shared.spoken_style import (
    AVOID_FORMS,
    COMPACT_AVOID,
    COMPACT_EXCHANGES,
    PACK_FORMS,
    PackChoice,
    language_pack,
    languages,
    shipped_pack_choice,
    style_for,
)

CHOICES = [PackChoice(form, avoid) for form in PACK_FORMS for avoid in AVOID_FORMS]
FULL = ("te-IN", "hi-IN", "en-IN")


def _agent(primary: str, extra: tuple[str, ...] = ()) -> AgentConfig:
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="A",
        business="Raghava Organics",
        direction="inbound",
        language_primary=primary,
        languages_extra=list(extra),
        system_prompt="",
        opening_line="",
        call_is_recorded=True,
        facts_in_knowledge=True,
        knowledge_tool="search_knowledge",
    )


def _register(cfg: AgentConfig, choice: PackChoice) -> str:
    return dict(engine_prompt_layers(cfg, pack=choice))["spoken_register"]


def test_every_language_has_a_pack_and_none_is_switched_on() -> None:
    for tag in languages():
        pack = language_pack(tag)
        assert pack is not None, tag
        assert pack.review == "needs_founder_review" and pack.ship is None
        assert shipped_pack_choice(tag) is None
        assert pack.say_english or tag == "en-IN", tag


@pytest.mark.parametrize("tag", FULL)
def test_a_full_pack_is_said_the_spoken_way(tag: str) -> None:
    pack = language_pack(tag)
    style = style_for(tag)
    assert pack is not None and style is not None
    assert 8 <= len(pack.exchanges) <= 10
    formal = dict(style.word_swaps)
    assert [w for w in pack.avoid if w not in formal] == [], "avoid names a list word"
    for exchange in pack.exchanges:
        for turn in exchange:
            assert formal_swaps(turn.text, tag) == [], turn.text
            if turn.speaker == "agent":
                assert not re.search(r"\d", turn.text), turn.text
                assert turn.text.rstrip()[-1] in ".?!।", turn.text


@pytest.mark.parametrize("choice", CHOICES, ids=lambda c: f"{c.form}-{c.avoid}")
def test_a_pack_names_a_textbook_word_only_in_its_avoid_line(choice: PackChoice) -> None:
    for primary, extra in (("te-IN", ("hi-IN",)), ("hi-IN", ("te-IN",)), ("te-IN", ())):
        section = _register(_agent(primary, extra), choice)
        for tag in (primary, *extra):
            pack = language_pack(tag)
            assert pack is not None
            named = {word for word, _ in formal_swaps(section, tag)}
            if choice.avoid == "none":
                assert named == set(), (tag, named)
            else:
                listed = pack.avoid if tag == primary else pack.avoid[:COMPACT_AVOID]
                # A list word can open with a shorter one (आवश्यकता, आवश्यक).
                allowed = {word for word, _ in formal_swaps(", ".join(listed), tag)}
                assert set(listed) <= allowed
                assert named == allowed, (tag, named ^ allowed)


def test_the_primary_gets_the_full_pack_and_an_extra_the_compact_one() -> None:
    choice = PackChoice("en", "list")
    section = _register(_agent("te-IN", ("hi-IN",)), choice)
    te, hi = language_pack("te-IN"), language_pack("hi-IN")
    assert te is not None and hi is not None
    assert section.index("Telugu:") < section.index("Hindi, when the caller speaks it:")
    for exchange in te.exchanges:
        assert f'"{exchange[0].text}"' in section
    shown = [e for e in hi.exchanges if f'"{e[0].text}"' in section]
    assert shown == list(hi.exchanges[:COMPACT_EXCHANGES])
    assert section.endswith(spoken_style.PACK_FACTS_RULE)
    assert section.count(spoken_style.PACK_FACTS_RULE) == 1


def test_the_native_form_is_written_in_the_language() -> None:
    section = _register(_agent("te-IN", ("hi-IN",)), PackChoice("native", "list"))
    te, hi = language_pack("te-IN"), language_pack("hi-IN")
    assert te is not None and te.native is not None and hi is not None and hi.native is not None
    for line in te.native.talk:
        assert line in section
    assert hi.native.when_extra in section
    assert section.endswith(te.native.facts)
    assert "Never say" not in section and "How a turn sounds" not in section


def test_a_pack_moves_the_register_lines_into_one_place() -> None:
    cfg = _agent("te-IN")
    layers = dict(engine_prompt_layers(cfg, pack=PackChoice("en", "none")))
    assert "formal or written-style" not in layers["how_to_speak"]
    assert 'Never say "uhm".' in layers["how_to_speak"]
    assert "never translated" not in layers["business_facts"]
    assert layers["languages"].startswith("--- LANGUAGES ---\nReply in the language the caller")
    assert engine.PACK_OTHER_LANGUAGES in layers["languages"]
    assert "Spoken words: not" not in layers["spoken_register"]


def test_without_an_approved_pack_the_shipped_prompt_has_no_pack() -> None:
    for tag in FULL:
        cfg = _agent(tag)
        layers = dict(engine_prompt_layers(cfg))
        assert "languages" not in layers
        assert layers["how_to_speak"] == engine._how_to_speak(None, cfg)
        assert 'Never say "uhm".' not in layers["how_to_speak"]
        assert compose_engine_prompt(cfg) == engine.LAYER_SEPARATOR.join(layers.values())


def _approve(monkeypatch: pytest.MonkeyPatch, *tags: str, ship: dict[str, str]) -> None:
    raw: dict[str, Any] = copy.deepcopy(spoken_style._raw())
    for tag in tags:
        raw["languages"][tag]["language_pack"].update(review="founder_approved", ship=ship)
    monkeypatch.setattr(spoken_style, "_raw", lambda: raw)
    spoken_style._table.cache_clear()


def test_approving_a_pack_is_the_one_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _agent("te-IN", ("hi-IN",))
    candidate = engine.LAYER_SEPARATOR.join(
        text for _l, text in engine_prompt_layers(cfg, pack=PackChoice("native", "none"))
    )
    # Approved without a form chosen ships nothing.
    _approve(monkeypatch, "te-IN", "hi-IN", ship={})
    assert shipped_pack_choice("te-IN") is None
    _approve(monkeypatch, "te-IN", "hi-IN", ship={"form": "native", "avoid": "none"})
    try:
        assert shipped_pack_choice("te-IN") == PackChoice("native", "none")
        assert compose_engine_prompt(cfg) == candidate
    finally:
        spoken_style._table.cache_clear()


def test_an_extra_language_without_its_own_approval_keeps_its_register_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _approve(monkeypatch, "te-IN", ship={"form": "en", "avoid": "list"})
    try:
        section = dict(engine_prompt_layers(_agent("te-IN", ("hi-IN",))))["spoken_register"]
        assert f"Hindi: {spoken_style.register_guidance('hi-IN')}" in section
        assert "Hindi, when the caller speaks it:" not in section
    finally:
        spoken_style._table.cache_clear()


def test_every_agent_is_told_to_follow_the_caller() -> None:
    languages_layer = dict(engine_prompt_layers(_agent("te-IN", ("hi-IN", "en-IN"))))["languages"]
    assert (
        "Your main language is Telugu; you also speak Hindi and English (India)." in languages_layer
    )
    assert "offer" not in languages_layer
    # Without a pack, following the caller is HOW TO SPEAK's bullet (D-883); with one, HOW TO
    # SPEAK drops it and the LANGUAGES section says it.
    how_to_speak = dict(engine_prompt_layers(_agent("te-IN", ("hi-IN", "en-IN"))))["how_to_speak"]
    assert "Match the caller's language" in how_to_speak
    packed = dict(
        engine_prompt_layers(_agent("te-IN", ("hi-IN", "en-IN")), pack=PackChoice("en", "list"))
    )
    assert "Reply in the language the caller speaks and switch when they do." in packed["languages"]
