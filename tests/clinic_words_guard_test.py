"""Clinic words live only in the clinic business type's own definitions (D-722).

Calevate serves shops, salons, garages, property offices, schools and "something else";
a clinic is one business type among eight. The founder found a chilli shop's calls
capturing "Preferred doctor" because a default picked the clinic, and asked that it be
made hard to regress. This guard reads every string literal the backend can send to a
person or a model (docstrings and comments are not read) and fails on a clinic word
anywhere except:

* **a dict entry keyed `"clinic"`** — the clinic type's own lead fields, label, starter
  words and spoken examples, used only when the account's type is clinic;
* **the allowlist below**, each entry a file, the words it may hold, and why.

Tests are not read: their fixtures are deliberately clinic-flavoured to exercise the clinic
type. The web has its own guard (`apps/web/tests/genericCopyGuard.test.ts`).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from apps.api.tenancy.business_copy import CLINIC_WORDS

ROOT = Path(__file__).resolve().parents[1]
ROOTS = (
    "apps/api",
    "apps/workers",
    "apps/voice-runtime",
    "apps/voice-worker",
    "packages/shared/src",
    "scripts",
)


#: `CLINIC_WORDS` is the pattern the AI-written examples are checked against at runtime
#: (`tenancy/business_copy`), so this guard and that check cannot drift.
#: (file, words it may hold, reason). `words` is matched against the clinic word found.
ALLOWED: tuple[tuple[str, frozenset[str], str], ...] = (
    (
        "apps/workers/caller_memory_distil.py",
        frozenset({"symptom", "prescription", "patient", "doctor", "hospital", "medical"}),
        "the sensitive-word filter that keeps health details out of caller memory",
    ),
    (
        "apps/api/retrieval/routing.py",
        frozenset({"doctor", "dentist", "which doctor", "appointment"}),
        "multi-trade vocabulary that routes a caller's question to the business's own facts",
    ),
    (
        "apps/api/insights/detection.py",
        frozenset({"appointment"}),
        "words that DETECT a booking topic in any trade's calls; the label shown is 'Bookings'",
    ),
    (
        "apps/api/agents/fix_guard.py",
        frozenset({"appointment"}),
        "words that DETECT a calendar action in any trade's test notes (a salon or a "
        "garage takes appointments too); matched, never spoken or shown",
    ),
    (
        "apps/api/engine/fake.py",
        frozenset({"clinic", "appointment", "doctor"}),
        "ENGINE=fake, the test-only engine; its sample call is a clinic booking the "
        "pipeline tests classify, never a production default",
    ),
    (
        "scripts/spike/kb_pgvector_latency.py",
        frozenset({"clinic", "appointment", "dentist", "doctor", "prescription"}),
        "a one-off latency spike's synthetic corpus, never run by the product",
    ),
    (
        "apps/api/agents/publishing.py",
        frozenset({"clinic"}),
        "the caller-memory refusal names why a clinic is refused",
    ),
    (
        "apps/api/legal/catalogue.py",
        frozenset({"symptom", "appointment"}),
        "revision notes that record which clinic-only examples a legal revision removed; "
        "the published text itself is business-neutral",
    ),
    (
        "scripts/check_deploy_env.py",
        frozenset({"symptom"}),
        "'symptom' of a misconfigured deploy, not a health word",
    ),
    (
        "apps/api/tenancy/business_copy.py",
        frozenset(
            {
                "clinics",
                "hospitals",
                "patients",
                "doctors",
                "dentists",
                "dental",
                "appointments",
                "symptoms",
                "prescriptions",
                "healthcare",
                "opd",
            }
        ),
        "the pattern itself (`CLINIC_WORDS`, which this guard imports), refusing those words "
        "in a non-clinic account's AI-written examples (D-827)",
    ),
)

#: The spoken examples, keyed by language then business type (`spoken_style.json`).
SPOKEN_STYLE = ROOT / "packages/shared/src/calevate_shared/spoken_style.json"


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


def _clinic_owned(tree: ast.AST) -> set[int]:
    """Every node inside a dict value whose key is the clinic type."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and key.value == "clinic":
                    ids.update(id(n) for n in ast.walk(value))
    return ids


def _hits(path: Path) -> list[tuple[int, str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _docstrings(tree) | _clinic_owned(tree)
    found: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if id(node) in skip or not isinstance(node, ast.Constant):
            continue
        if not isinstance(node.value, str) or node.value.strip().lower() == "clinic":
            # The type's own identifier (a Literal member, a dict key, `CLINIC = "clinic"`)
            # names the type; it says nothing to a business that is not one.
            continue
        for match in CLINIC_WORDS.finditer(node.value):
            found.append((node.lineno, match.group(0).lower(), node.value.strip()[:120]))
    return found


def _allowed(rel: str, word: str) -> bool:
    return any(rel == file and word in words for file, words, _ in ALLOWED)


def test_reads_the_backend() -> None:
    files = _python_files()
    assert len(files) > 400
    assert any(p.name == "starters.py" for p in files)


def test_no_clinic_words_outside_the_clinic_type() -> None:
    found: list[str] = []
    for path in _python_files():
        rel = path.relative_to(ROOT).as_posix()
        for line, word, text in _hits(path):
            if not _allowed(rel, word):
                found.append(f"{rel}:{line} ({word}) in: {text}")
    assert found == [], (
        "Clinic words outside the clinic business type. Make the text neutral, drive it from "
        "the account's business type, or put it under a dict entry keyed 'clinic':\n"
        + "\n".join(found)
    )


def test_every_allowlist_entry_is_still_needed() -> None:
    """An entry whose file no longer holds its words is removed, so the list only shrinks."""
    stale: list[str] = []
    for file, words, reason in ALLOWED:
        path = ROOT / file
        held = {word for _, word, _ in _hits(path)} if path.exists() else set()
        if not held & words:
            stale.append(f"{file}: {sorted(words)} ({reason})")
    assert stale == [], "\n".join(stale)


def test_spoken_examples_of_other_types_carry_no_clinic_words() -> None:
    styles = json.loads(SPOKEN_STYLE.read_text(encoding="utf-8"))
    checked = 0
    found: list[str] = []

    def walk(node: object, path: str) -> None:
        nonlocal checked
        if isinstance(node, dict):
            for key, value in node.items():
                if key != "clinic":
                    walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")
        elif isinstance(node, str):
            checked += 1
            match = CLINIC_WORDS.search(node)
            if match:
                found.append(f"{path}: {match.group(0)} in {node[:80]}")

    walk(styles, "spoken_style")
    assert checked > 50
    assert found == []
