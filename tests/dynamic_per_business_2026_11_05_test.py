"""Nothing hardcoded per business, and no hand-written Indian-language text (audit of 5 Nov 2026,
`docs/evidence/e2e-audit-2026-11-05/6-hardcoded-dynamic.md`, lane D)."""

from __future__ import annotations

import pytest
from calevate_shared import spoken_style
from calevate_shared.engine import (
    AgentConfig,
    compose_engine_prompt,
    engine_prompt_layers,
)

# --- F-5: words written joined, as native speakers write them -----------------------------

_WRITTEN_FORM = "Write as native speakers do: a suffix, particle or vowel joins its word."


def _cfg(language: str = "te-IN", direction: str = "outbound", **kw: object) -> AgentConfig:
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="A",
        business="B",
        direction=direction,
        language_primary=language,
        system_prompt="[TASK FLOW]\nHelp them.",
        opening_line="",
        call_is_recorded=True,
        **kw,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    "cfg",
    [
        _cfg("te-IN"),
        _cfg("hi-IN"),
        _cfg("en-IN"),
        _cfg("ta-IN"),
        _cfg("te-IN", caller_has_screen=True),
        _cfg("te-IN", languages_extra=["hi-IN"]),
        _cfg("te-IN", direction="inbound"),
    ],
)
def test_the_written_form_rule_reaches_every_composed_prompt(cfg: AgentConfig) -> None:
    prompt = compose_engine_prompt(cfg)
    assert _WRITTEN_FORM in prompt
    assert _WRITTEN_FORM in dict(engine_prompt_layers(cfg))["how_to_speak"]


def test_the_rule_names_no_language_and_quotes_the_founders_example_only_when_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    how = dict(engine_prompt_layers(_cfg()))["how_to_speak"]
    rule = next(line for line in how.splitlines() if _WRITTEN_FORM in line)
    assert rule.isascii()
    assert "Like:" not in rule

    monkeypatch.setattr(
        "calevate_shared.engine.written_form", lambda tag: "EXAMPLE" if tag == "te-IN" else None
    )
    how = dict(engine_prompt_layers(_cfg()))["how_to_speak"]
    assert 'vowel joins its word. Like: "EXAMPLE"\n' in how
    assert "Like:" not in dict(engine_prompt_layers(_cfg("hi-IN")))["how_to_speak"]


def test_every_language_row_has_an_empty_written_form_slot_for_the_founder() -> None:
    rows = spoken_style._raw()["languages"]
    for tag in spoken_style.languages():
        assert rows[tag]["written_form"] == "", tag
        assert spoken_style.written_form(tag) is None, tag
