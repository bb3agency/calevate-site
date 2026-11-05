"""No Indian-language word is written in the call checks' code (L5-07, founder rule 2).

FAILS IF: a string in the code of a check that listens for words (the turn checks, the
knowledge-gap detector, the language pass, the caller-memory distiller, the do-not-call
detector, the opening's AI and recording words, the script checks, the teach and
practice-run detectors) holds a Telugu or Devanagari letter (comments and
docstrings may quote a real call); an emptied data entry matches everything instead of
nothing; or a key the code reads is missing from `call_words.json`.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest
from calevate_shared import call_words

ROOT = Path(__file__).resolve().parents[1]
CHECKED = (
    "apps/api/agents/turn_checks.py",
    "apps/api/insights/detection.py",
    "apps/workers/call_language.py",
    "apps/workers/caller_memory_distil.py",
    "apps/api/compliance/optout.py",
    "apps/api/agents/languages.py",
    "packages/shared/src/calevate_shared/opening_notices.py",
    "apps/api/agents/script_lint.py",
    "apps/api/teach/questions.py",
    "apps/api/agents/test_conversations.py",
    "apps/api/compliance/call_purpose.py",
    "packages/shared/src/calevate_shared/spoken_guard.py",
)
INDIC = re.compile("[ऀ-ॿఀ-౿]")
#: Unicode block ends and the danda: how a script or a sentence end is recognised, not words.
MECHANICS = set("ऀॿఀ౿ॣ।॥")


def _code_strings(path: Path) -> list[tuple[int, str]]:
    source = path.read_text(encoding="utf-8")
    docstrings = {
        node.value.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    found = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type not in (tokenize.STRING, tokenize.FSTRING_MIDDLE):
            continue
        if tok.start[0] in docstrings:
            continue
        letters = INDIC.findall(tok.string)
        if letters and not all(ch in MECHANICS for ch in letters):
            found.append((tok.start[0], tok.string[:40]))
    return found


@pytest.mark.parametrize("relative", CHECKED)
def test_no_indian_language_word_is_written_in_code(relative: str) -> None:
    assert _code_strings(ROOT / relative) == []


def test_every_key_the_code_reads_is_in_the_data() -> None:
    """Every literal key handed to a loader (`say`, `words`, `extend`, `table`, under the
    names the modules import them as) is in the file. Read from the syntax tree, because an
    `extend` call's English pattern spans lines and holds quotes."""
    readers = {"_say", "_words", "_word_list", "_extend", "table"}
    wanted: set[str] = set()
    for relative in (*CHECKED, "apps/workers/extraction.py"):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            key = node.args[-1]
            if name in readers and isinstance(key, ast.Constant) and isinstance(key.value, str):
                wanted.add(key.value)
    assert {"optout.patterns", "opening_notices.AI_WORDS", "script_lint._NEGATED"} <= wanted
    assert wanted - call_words.keys() == set()


def test_an_emptied_entry_finds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(call_words, "_entries", lambda: {"x.y": ""})
    assert re.search(call_words.say("x.y"), "anything at all") is None


def test_an_emptied_entry_keeps_the_english_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """`extend` keeps the alternatives written in code when the founder empties the entry,
    and adds the entry's alternatives after them when it holds some."""
    monkeypatch.setattr(call_words, "_entries", lambda: {"x.y": "", "x.z": "abc"})
    assert call_words.extend("record", "x.y") == "record"
    assert call_words.extend("record", "x.z") == "record|abc"


def test_detector_words_live_in_one_file() -> None:
    """The do-not-call phrases moved from the spoken-lines file unchanged: each language's
    rules, and the opening's AI and recording words in both Indian scripts."""
    from calevate_shared import spoken_lines
    from calevate_shared.opening_notices import says_ai, says_recorded

    assert {"te", "hi"} <= set(call_words.table("optout.patterns"))
    assert set(call_words.table("optout.not_now")) == {"te", "hi"}
    assert "optout.patterns" not in spoken_lines.entry_keys()
    for key in ("opening_notices.AI_WORDS", "opening_notices.RECORDING_WORDS"):
        assert INDIC.search(call_words.say(key))
    assert says_ai("I am an AI assistant")
    assert says_recorded("This call is recorded")


def test_the_promo_and_greeting_words_moved_unchanged_and_still_match() -> None:
    """G4-6: the launch gate's promotional words and the greeting detector read the founder's
    file, and still see what they saw when the words sat in code."""
    from apps.api.compliance.call_purpose import first_finding
    from calevate_shared.spoken_guard import opens_with_greeting, without_greeting

    rules = call_words.table("call_purpose.rules")
    assert {"te discount strong", "hi discount strong", "te urgency soft"} <= set(rules)
    for words in rules.values():
        word = words[0]
        found = first_finding(f"Today {word} for you")
        assert found is not None, word
    # A Hindi "not" after the word negates it.
    hindi = rules["hi discount strong"][0]
    negation = call_words.say("call_purpose._NEGATION_HI_BEFORE").split("|")[0]
    assert first_finding(f"{hindi} {negation}") is None
    greeting = call_words.say("spoken_guard._GREETING_HEAD.greetings").split("|")[0]
    honorific = call_words.say("spoken_guard._GREETING_HEAD.honorifics").split("|")[0]
    assert opens_with_greeting(f"{greeting} {honorific}, what next?")
    assert without_greeting(f"{greeting} {honorific}, what next?") == "what next?"
