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
from collections.abc import Iterator
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


# ═══════════════ the console's edits reach a running check (G-C2) ═══════════════


@pytest.fixture
def _file_alone() -> Iterator[None]:
    call_words.install(None)
    yield
    call_words.install(None)


def test_an_installed_edit_rebuilds_the_pattern_without_a_restart(_file_alone: None) -> None:
    from calevate_shared.opening_notices import says_ai

    assert not says_ai("zzqmachine speaking")
    entry = call_words.shipped()["opening_notices.AI_WORDS"]
    call_words.install({"opening_notices.AI_WORDS": f"{entry}|zzqmachine"})
    assert says_ai("zzqmachine speaking")
    call_words.install(None)
    assert not says_ai("zzqmachine speaking")


def test_an_override_the_code_cannot_read_is_skipped(_file_alone: None) -> None:
    """A key a release removed, or a value in a shape the file no longer ships, stays out:
    the code reading the entry was written against the file."""
    call_words.install({"no.such_key": "x", "detection.stalls": ["a list"]})
    assert call_words.keys().isdisjoint({"no.such_key"})
    assert isinstance(call_words.say("detection.stalls"), str)


def test_a_rebuild_that_fails_keeps_the_last_good_value(
    _file_alone: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = call_words.LivePattern(lambda: call_words.say("detection.stalls") + "|zzq")
    assert live.search("zzq")
    # Past `install`'s checks on purpose: a value that slipped by the save.
    monkeypatch.setattr(
        call_words, "_installed", {**call_words.shipped(), "detection.stalls": "(unclosed"}
    )
    monkeypatch.setattr(call_words, "_generation", call_words.generation() + 1)
    assert live.search("zzq")


_READERS = frozenset({"say", "words", "extend", "table"})


def _module_level_reads(path: Path) -> list[int]:
    """Lines where `path` reads an entry outside any function or lambda: a value fixed at
    import, which an edit on the console would never reach."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    aliases = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "calevate_shared.call_words"
        for alias in node.names
        if alias.name in _READERS
    }
    found: list[int] = []

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            return
        if isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Name) and func.id in aliases) or (
                isinstance(func, ast.Attribute)
                and func.attr in _READERS
                and isinstance(func.value, ast.Name)
                and func.value.id == "call_words"
            ):
                found.append(node.lineno)
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return found


def test_no_check_fixes_its_words_at_import() -> None:
    """G-C2: every read of an entry happens inside a function, a lambda or a `Live`, so an
    edit on Ops > Call words reaches the check without a restart. A module that builds a
    pattern from the words at import must wrap it in `call_words.Live` / `LivePattern`."""
    offenders: dict[str, list[int]] = {}
    for root in ("apps", "packages/shared/src"):
        for path in sorted((ROOT / root).rglob("*.py")):
            if path.name == "call_words.py" or "call_words" not in path.read_text(encoding="utf-8"):
                continue
            lines = _module_level_reads(path)
            if lines:
                offenders[path.relative_to(ROOT).as_posix()] = lines
    assert offenders == {}


def test_every_shipped_entry_passes_the_editors_own_checks() -> None:
    """The save refuses what the file itself would fail, so the file must pass."""
    found = {k: call_words.problems(k, v) for k, v in call_words.shipped().items()}
    assert {k: v for k, v in found.items() if v} == {}


def test_the_editor_refuses_what_would_break_a_check() -> None:
    from apps.api.insights import detection

    assert detection._NONANSWER_RE.search("let me check")
    assert call_words.problems("detection.stalls", "(unclosed")
    assert call_words.problems("detection.stalls", ["a", "list"])
    assert call_words.problems("detection.stalls", "a|")  # matches every call
    assert call_words.problems("detection.topic.pricing", "a pattern")
    assert call_words.problems("no.such_key", "x")
    # A table keeps its rows' width and may gain a language.
    rule = [["rule_id", r"\bnahi\b"]]
    assert call_words.problems("optout.patterns", {"ta": rule}) == []
    assert call_words.problems("optout.patterns", {"ta": [["only_an_id"]]})
    assert call_words.problems("optout.patterns", {"Tamil": rule})
    assert call_words.trial("detection.stalls", "(?i)zzq").failures
    assert call_words.trial("detection.stalls", None).failures == ()
