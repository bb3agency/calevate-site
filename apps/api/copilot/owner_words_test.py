"""Pip's own sentences to an owner name no machinery (`owner_words.py`).

The prompt tells the model not to talk about tools, functions or "the system"; this holds the
sentences WE write for the owner to the same standard, because the model paraphrases what it
is handed and the panel shows some of them as written.

What counts as an owner sentence, read from the source rather than listed:

* a string literal passed to a keyword the panel renders: an approval card's `title`,
  `summary`, `current`, `proposed`, `cost` and `reversal`, a receipt's `detail`, a refusal's
  `plain`, a problem's `title`/`detail`/`remediation`, and an action's `where`;
* a module constant whose name says it is shown (`*_PLAIN`, `*_MESSAGE`, `*_TITLE`,
  `*_DETAIL`, `*_REMEDIATION`, `*_DISCLOSURE`);
* every step label.

What only the MODEL reads (a refusal's `reason`, tool descriptions) names tools and arguments
on purpose: that is how it corrects a call. The admin modules (`admin_*`) speak to operators.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from apps.api.copilot.owner_words import machine_words
from apps.api.copilot.prompt import CLOSING_RULES, PLAIN_WORDS_RULE, SYSTEM_PROMPT
from apps.api.copilot.step_labels import STEP_LABELS

COPILOT = Path(__file__).resolve().parent
REPO_ROOT = COPILOT.parents[2]

SHOWN_KEYWORDS = frozenset(
    {
        "title",
        "summary",
        "current",
        "proposed",
        "cost",
        "reversal",
        "detail",
        "plain",
        "remediation",
        "where",
    }
)
SHOWN_CONSTANT = re.compile(r"(?:_PLAIN|_MESSAGE|_TITLE|_DETAIL|_REMEDIATION|_DISCLOSURE)$")

#: `(file, word, reason)`: one word in one file where it is the owner's own subject.
ALLOWED: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "apps/api/copilot/account_actions.py",
        re.compile(r"endpoint"),
        "the owner wires their own webhook endpoint on Integrations; it is their word there",
    ),
)


def _literal(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "{}"
            for v in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal(node.left), _literal(node.right)
        return left + right if left is not None and right is not None else None
    return None


def _owner_modules() -> list[Path]:
    return [
        path
        for path in sorted(COPILOT.glob("*.py"))
        if not path.name.endswith("_test.py") and not path.name.startswith("admin_")
    ]


def _shown_constant(node: ast.Assign | ast.AnnAssign) -> bool:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return any(isinstance(t, ast.Name) and SHOWN_CONSTANT.search(t.id) for t in targets)


def owner_sentences() -> list[tuple[str, int, str]]:
    """`(file, line, text)` for every owner sentence written as a literal in Pip's modules."""
    found: list[tuple[str, int, str]] = []
    for path in _owner_modules():
        where = path.relative_to(REPO_ROOT).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            texts: list[str | None] = []
            if isinstance(node, ast.Call):
                texts = [_literal(k.value) for k in node.keywords if k.arg in SHOWN_KEYWORDS]
            elif isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None:
                texts = [_literal(node.value)] if _shown_constant(node) else []
            else:
                continue
            found.extend((where, node.lineno, t) for t in texts if t and " " in t.strip())
    return found


def _allowed(file: str, offence: str) -> bool:
    return any(file == prefix and word.search(offence) for prefix, word, _ in ALLOWED)


def test_it_catches_the_sentence_it_exists_for() -> None:
    said = (
        "I cannot show you the full script, as the system does not provide a tool to print "
        "the entire multi-stage script at once."
    )
    assert machine_words(said)
    for leak in (
        "Take it from `agents_list`.",
        "The agent_id is missing.",
        "Gemini did not answer.",
        "The model's safety filter stopped the reply.",
        "I need the agent's id.",
    ):
        assert machine_words(leak), leak
    for fine in (
        "Varsha's script is on her Script tab, under Agents.",
        "Upload a photo of your ID.",
        "Connect your Google Calendar first.",
    ):
        assert not machine_words(fine), fine


def test_the_scan_finds_the_owner_sentences() -> None:
    """A scanner that stopped finding anything would pass forever."""
    found = owner_sentences()
    assert len(found) > 200
    assert any(text.startswith("I couldn't answer that one") for _f, _l, text in found)


def test_pips_owner_sentences_name_no_machinery() -> None:
    found = [
        f"{file}:{line} {text!r} -> {'; '.join(bad)}"
        for file, line, text in owner_sentences()
        if (bad := [o for o in machine_words(text) if not _allowed(file, o)])
    ]
    assert found == [], "\n".join(found)


def test_step_labels_name_no_machinery() -> None:
    found = [
        f"{name}: {text!r} -> {bad}"
        for name, label in STEP_LABELS.items()
        for text in label
        if (bad := machine_words(text))
    ]
    assert found == [], "\n".join(found)


def test_the_prompt_tells_pip_to_speak_plainly_in_the_prefix_and_at_the_end() -> None:
    assert PLAIN_WORDS_RULE in SYSTEM_PROMPT
    assert PLAIN_WORDS_RULE in CLOSING_RULES
    assert "print all of it" in SYSTEM_PROMPT
