"""No business's words in shared code, and no hand-written Indian-language text (audit of
5 Nov 2026, G9-1).

`clinic_words_guard_test.py` kept clinic words out and nothing else, which is why a grocery
example ("two kilos of green chilli") sat in every call's extraction prompt and property
portals in every owner's lead-source drawer through three clean-up passes. Two guards here
read every string literal the backend can send to a person or a model (docstrings and
comments are not read):

* **Trade words.** Words that belong to one kind of business (a shop's kilos, a property
  office's BHK and site visits, a salon's bridal make-up, a farm's crops) fail anywhere
  except inside a dict entry keyed by that business type (the type's own rows, read only
  for that type) or a file in `TRADE_ALLOWED`. Clinic words are the other guard's.
* **Indian-language letters.** Telugu, Hindi and every other Indian script fail in a `.py`
  string except in the files in `INDIC_ALLOWED`: detectors whose lists are matched and never
  spoken, reference names, and files another fix lane owns that still hold some. Spoken
  lines live in the founder's data files (`calevate_shared/spoken_lines.json`,
  `spoken_style.json`). Punctuation such as the danda is not a letter and is not counted.

Each allowance is a file, the exact number of strings it holds and why. A count that grows
fails; a count that shrinks, or a file that no longer needs its allowance, fails as stale,
so the tables only shrink. Tests are not read.
"""

from __future__ import annotations

import ast
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOTS = (
    "apps/api",
    "apps/workers",
    "apps/voice-runtime",
    "packages/shared/src",
)

#: Words that name one kind of business's goods, units, places or services. Matched as
#: whole words, case-insensitively.
TRADE_WORDS = re.compile(
    r"\b(?:chill(?:i|ies)|kilos?|kgs?|groceries|grocery|kirana|"
    r"bhk|crores?|lakhs?|site\s+visits?|"
    r"haircuts?|bridal|salons?|"
    r"farmers?|crops?|"
    r"test\s+drives?|showrooms?)\b",
    re.IGNORECASE,
)

#: The business types whose own rows may hold their words (`scripts/seed.BUSINESS_TYPE_LABELS`).
BUSINESS_TYPES = frozenset(
    {
        "retail",
        "local_services",
        "automobile",
        "clinic",
        "real_estate",
        "insurance",
        "education",
        "custom",
    }
)

#: {file: (strings with trade words, why)}.
TRADE_ALLOWED: dict[str, tuple[int, str]] = {
    "apps/api/agents/retired_lines.py": (
        4,
        "retired lines kept only to find and remove them on live agents (D-962)",
    ),
    "apps/api/agents/turn_checks.py": (
        5,
        "practice-run reply checks (units said in digits): matched, never said; lane C",
    ),
    "apps/workers/caller_help.py": (1, "a model prompt's example caller noun; lane B"),
}

#: Indian scripts, by the Unicode name of their letters and marks.
_INDIC = (
    "DEVANAGARI",
    "BENGALI",
    "GURMUKHI",
    "GUJARATI",
    "ORIYA",
    "TAMIL",
    "TELUGU",
    "KANNADA",
    "MALAYALAM",
)

#: {file: (strings with Indian-language letters, why)}.
INDIC_ALLOWED: dict[str, tuple[int, str]] = {
    "packages/shared/src/calevate_shared/languages.py": (
        17,
        "each language's name in its own script (endonyms), reference data",
    ),
    "apps/api/compliance/call_purpose.py": (
        63,
        "promotional-wording detector lists: matched, never said or shown",
    ),
    "packages/shared/src/calevate_shared/spoken_guard.py": (
        2,
        "detector of textbook words in a spoken line: matched, never said",
    ),
    "packages/shared/src/calevate_shared/opening_notices.py": (
        2,
        "detector of the AI and recording sentences in a reply: matched, never said; lane B",
    ),
    "apps/api/agents/retired_lines.py": (
        117,
        "retired lines kept only to find and remove them on live agents (D-962)",
    ),
    "packages/shared/src/calevate_shared/call_script.py": (
        1,
        "the retired default don't-know line, kept only to recognise it (D-965)",
    ),
    "apps/api/copilot/identity.py": (
        6,
        "provider names in Indian scripts, detected so the assistant never says them; lane A",
    ),
    "apps/workers/caller_name.py": (
        1,
        "a Unicode range naming the Indic blocks, not words",
    ),
    "apps/workers/extraction.py": (
        12,
        "the offline extractor used only locally and in CI (`get_extractor`); lane C",
    ),
    "apps/api/agents/turn_checks.py": (
        244,
        "practice-run reply checks; to move to a founder-owned language pack; lane C",
    ),
    "apps/api/agents/script_lint.py": (7, "script detectors; lane B"),
    "apps/workers/script_assist.py": (1, "a prompt example (G3-4); lane B"),
    "apps/api/copilot/agent_setup_actions.py": (1, "a detector; lane A"),
    "apps/api/teach/questions.py": (2, "hours and address detectors (G5-6)"),
    "apps/api/agents/test_conversations.py": (
        2,
        "detectors of a price and of a hand-over said in a reply: matched, never said",
    ),
    "apps/api/agents/specimen_scenarios.py": (
        50,
        "per-type practice callers (G2-8): to move to the founder's data file",
    ),
}


def _python_files() -> list[Path]:
    out: list[Path] = []
    for root in ROOTS:
        for path in (ROOT / root).rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if rel.endswith("_test.py") or "/tests/" in f"/{rel}" or "/.venv/" in f"/{rel}":
                continue
            out.append(path)
    return out


def _docstrings(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def _type_owned(tree: ast.AST) -> set[int]:
    """Every node inside a dict value whose key is a business type."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and key.value in BUSINESS_TYPES:
                    ids.update(id(n) for n in ast.walk(value))
    return ids


def _strings(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _docstrings(tree) | _type_owned(tree)
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if id(node) not in skip and isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def indic(text: str) -> bool:
    """Whether `text` holds a letter or mark of an Indian script (punctuation does not count)."""
    return any(
        unicodedata.category(ch)[0] in "LM" and unicodedata.name(ch, "").startswith(_INDIC)
        for ch in text
        if not ch.isascii()
    )


def hits(path: Path) -> tuple[list[str], list[str]]:
    rel = path.relative_to(ROOT).as_posix()
    trade: list[str] = []
    found: list[str] = []
    for line, value in _strings(path):
        match = TRADE_WORDS.search(value)
        if match:
            trade.append(f"{rel}:{line} ({match.group(0)}) in: {value.strip()[:100]}")
        if indic(value):
            found.append(f"{rel}:{line} in: {value.strip()[:60]}")
    return trade, found


def _over(table: dict[str, tuple[int, str]], index: int) -> list[str]:
    found: list[str] = []
    for path in _python_files():
        rel = path.relative_to(ROOT).as_posix()
        held = hits(path)[index]
        if len(held) > table.get(rel, (0, ""))[0]:
            found += held
    return found


def test_reads_the_backend() -> None:
    assert len(_python_files()) > 400


def test_no_trade_words_outside_their_own_type() -> None:
    found = _over(TRADE_ALLOWED, 0)
    assert found == [], (
        "Words of one kind of business in shared text. Make it neutral, take it from the "
        "business's own data, or put it under a dict entry keyed by its business type:\n"
        + "\n".join(found)
    )


def test_no_hand_written_indian_language_text_in_code() -> None:
    found = _over(INDIC_ALLOWED, 1)
    assert found == [], (
        "Telugu, Hindi or other Indian-language text in code. Spoken lines are the founder's "
        "(calevate_shared/spoken_lines.json or spoken_style.json); a detector's list goes in "
        "INDIC_ALLOWED with its count and reason:\n" + "\n".join(found)
    )


def test_every_allowance_is_exact() -> None:
    """A count that shrank, or a file that no longer needs its allowance, is stale: the
    tables only shrink."""
    stale: list[str] = []
    for table, index in ((TRADE_ALLOWED, 0), (INDIC_ALLOWED, 1)):
        for file, (count, reason) in table.items():
            path = ROOT / file
            held = len(hits(path)[index]) if path.exists() else 0
            if held != count:
                stale.append(f"{file}: allowed {count}, holds {held} ({reason})")
    assert stale == [], "\n".join(stale)


def test_the_moved_lines_are_in_the_founders_data_file() -> None:
    from calevate_shared import spoken_lines

    for key in ("handover", "still_there", "disclosure.ai", "optout.patterns"):
        assert key in spoken_lines.entry_keys()
    assert any(indic(line) for line in spoken_lines.lines("disclosure.ai").values())


def test_the_guard_sees_what_it_guards() -> None:
    assert TRADE_WORDS.search("two kilos of green chilli")
    assert TRADE_WORDS.search("a 2 BHK site visit")
    assert not TRADE_WORDS.search("a call back on Saturday")
    assert indic("కాల్")
    assert not indic("।")
