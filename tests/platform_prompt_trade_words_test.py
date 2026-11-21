"""Platform prompts name no trade (research notes §4.1: business type goes in as data).

The text the platform writes into every agent's call prompt, the script writer's
instruction and Pip's system prompt reach every tenant: a clinic, a college, an NBFC desk,
a farmers' app. A trade word there (a chilli, a patient, a delivery) tells every one of
them that callers are that trade's callers. The business's own words reach a prompt only
as data from its rows: its script, its facts, its spoken examples keyed by business type.

`ALLOWED` holds the PHRASES, never bare words, in which a listed word is generic, each with
why; a phrase is taken out before the words are matched, so the same word anywhere else
still fails.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from apps.api.copilot.prompt import CLOSING_RULES, SYSTEM_PROMPT
from apps.workers.script_assist import _SYSTEM_INSTRUCTION
from calevate_shared.call_script import CODE_MIX_SENTENCES
from calevate_shared.engine import AgentConfig, ModelConfig, engine_prompt_layers
from calevate_shared.languages import built_language_tags

ROOT = Path(__file__).resolve().parents[1]
SPOKEN_STYLE = ROOT / "packages/shared/src/calevate_shared/spoken_style.json"

#: Words tied to one kind of business. Singular stems; `s`/`es` plurals match too.
TRADE_WORDS: tuple[str, ...] = (
    "clinic",
    "hospital",
    "patient",
    "doctor",
    "dentist",
    "symptom",
    "prescription",
    "medicine",
    "crop",
    "farmer",
    "farm",
    "seed",
    "fertiliser",
    "chilli",
    "kilo",
    "kg",
    "grocery",
    "groceries",
    "spice",
    "delivery",
    "order",
    "stock",
    "product",
    "shop",
    "shopkeeper",
    "property",
    "properties",
    "flat",
    "BHK",
    "plot",
    "site visit",
    "salon",
    "haircut",
    "student",
    "admission",
    "tuition",
    "loan",
    "EMI",
    "premium",
    "vehicle",
    "garage",
)
_TRADE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) + r"(?:e?s)?" for w in TRADE_WORDS) + r")\b",
    re.IGNORECASE,
)

_LIST_OF_FACTS = (
    "one item in a list of facts never to guess that spans every trade (a place, a project, "
    "a price, hours, anything medical, legal or financial), so it singles out none"
)
#: Phrase (matched case-insensitively) -> why the trade word inside it is generic there.
ALLOWED: dict[str, str] = {
    "in order": "sequence, not a purchase",
    "the order the call": "sequence of the call's stages",
    "sidebar order": "sequence of screens",
    "an order to follow": "a command, not a purchase",
    "order or booking": (
        "the two commitments a call can claim, named together so neither is claimed done; "
        "a business taking neither never reaches the rule"
    ),
    "stock or availability": _LIST_OF_FACTS,
    "what a product is": _LIST_OF_FACTS,
    "prices, stock, hours": _LIST_OF_FACTS,
    "calevate product": "our own software",
    "of that product": "our own software",
    "in the product": "our own software",
}
_ALLOWED = re.compile("|".join(re.escape(p) for p in ALLOWED), re.IGNORECASE)


def _neutral(language: str, direction: str) -> AgentConfig:
    return AgentConfig(
        tenant_id="0199a0b0-0000-7000-8000-000000000001",
        agent_id="0199a0b0-0000-7000-8000-000000000002",
        name="Front desk",
        direction=direction,  # type: ignore[arg-type]
        system_prompt="",
        opening_line="This is an AI assistant.",
        language_primary=language,
        models=ModelConfig(
            stt_provider="sarvam",
            stt_model="saaras:v3",
            llm_model="gemini-2.5-flash-lite",
            tts_provider="cartesia",
            tts_voice="ashutosh",
        ),
    )


def _platform_layers(language: str, direction: str) -> str:
    """Every layer of the call prompt except the client's own script."""
    layers = engine_prompt_layers(_neutral(language, direction))
    return "\n".join(text for name, text in layers if name != "client_script")


def _found(text: str) -> set[str]:
    return {m.group(0).lower() for m in _TRADE.finditer(_ALLOWED.sub(" ", text))}


def _checked() -> str:
    texts = [_SYSTEM_INSTRUCTION, SYSTEM_PROMPT, CLOSING_RULES, *CODE_MIX_SENTENCES.values()]
    texts += [
        _platform_layers(tag, direction)
        for tag in built_language_tags()
        for direction in ("inbound", "outbound")
    ]
    return "\n".join(texts)


@pytest.mark.parametrize("direction", ["inbound", "outbound"])
@pytest.mark.parametrize("language", built_language_tags())
def test_the_platform_layers_of_a_call_prompt_name_no_trade(language: str, direction: str) -> None:
    """FAILS IF: a layer we write, not the client, names a trade (an agent with no script,
    no facts and no business type, in each built language)."""
    platform = _platform_layers(language, direction)
    assert platform
    assert _found(platform) == set()


def test_the_script_writers_instruction_names_no_trade() -> None:
    assert _found(_SYSTEM_INSTRUCTION) == set()


def test_pips_system_prompt_names_no_trade() -> None:
    assert _found(SYSTEM_PROMPT + CLOSING_RULES) == set()


def test_every_code_mix_sentence_names_no_trade() -> None:
    for level, sentence in CODE_MIX_SENTENCES.items():
        assert _found(sentence) == set(), level


def test_every_register_and_language_pack_names_no_trade() -> None:
    """The register goes into every agent's call prompt in its language, and a language
    pack's English words will once a pack ships, whatever the business."""
    languages = json.loads(SPOKEN_STYLE.read_text(encoding="utf-8"))["languages"]
    found = [
        f"{tag}.{where}: {word}"
        for tag, style in languages.items()
        for where, text in (
            ("register", style.get("register") or ""),
            ("say_english", " ".join((style.get("language_pack") or {}).get("say_english", ()))),
        )
        for word in _found(text)
    ]
    assert found == []


def test_the_guard_catches_a_trade_word() -> None:
    """FAILS IF: the pattern stops matching, which would pass every test above vacuously."""
    assert _found("Ask which chilli and how many kilos for delivery") == {
        "chilli",
        "kilos",
        "delivery",
    }
    assert _found("Book the patient in order of arrival") == {"patient"}


def test_every_allowed_phrase_is_still_needed() -> None:
    """The list only shrinks: a phrase no checked prompt holds any more is removed."""
    checked = _checked().lower()
    assert [phrase for phrase in ALLOWED if phrase not in checked] == []
