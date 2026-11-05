"""No Indian-language word is written in the call checks' code (L5-07, founder rule 2).

FAILS IF: a string in the code of the turn checks, the knowledge-gap detector, the language
pass or the caller-memory distiller holds a Telugu or Devanagari letter (comments and
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
    keys = call_words.keys()
    pattern = re.compile(r"_(?:say|words|word_list)\(\s*[\"']([^\"']+)[\"']")
    wanted = set()
    for relative in (*CHECKED, "apps/workers/extraction.py"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        wanted |= set(pattern.findall(source))
    assert wanted - keys == set()


def test_an_emptied_entry_finds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(call_words, "_entries", lambda: {"x.y": ""})
    assert re.search(call_words.say("x.y"), "anything at all") is None
