"""The healer page's plain words (`apps/api/healer/wording.py`), without a database.

The catalogue must cover every code an incident can be opened with, so a new playbook
trigger or a new `open_incident` caller fails here until it has words.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from apps.api.healer import wording
from apps.api.healer.playbooks import PLAYBOOK_BY_KEY, PLAYBOOK_BY_TRIGGER, PLAYBOOKS, STATUS_POST

ROOT = Path(__file__).resolve().parents[1]


def _openable_codes() -> set[str]:
    return set(PLAYBOOK_BY_TRIGGER) | {STATUS_POST}


def test_every_openable_code_has_plain_words() -> None:
    missing = _openable_codes() - set(wording.INCIDENT_KINDS)
    assert not missing, f"no plain words for {sorted(missing)}: add them to healer/wording.py"


def test_the_catalogue_holds_nothing_the_healer_cannot_open() -> None:
    assert set(wording.INCIDENT_KINDS) == _openable_codes()


def _literal_trigger_codes() -> set[str]:
    """Every string literal passed as `trigger_code=` to `open_incident` anywhere in apps/."""
    found: set[str] = set()
    for path in (ROOT / "apps").rglob("*.py"):
        if "open_incident(" not in path.read_text(encoding="utf-8"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", getattr(node.func, "id", None))
            if name != "open_incident":
                continue
            for kw in node.keywords:
                if kw.arg == "trigger_code" and isinstance(kw.value, ast.Constant):
                    found.add(str(kw.value.value))
    return found


def test_no_incident_is_opened_with_a_code_outside_the_registry() -> None:
    """Callers name codes through the registry, so the equality above is the whole set."""
    assert _literal_trigger_codes() <= _openable_codes()


def test_every_kind_is_documented_in_the_alarm_index() -> None:
    """The lines restate the alarm index; a code it does not list has no source."""
    index = (ROOT / "runbooks" / "alarm-index.md").read_text(encoding="utf-8")
    for code in wording.INCIDENT_KINDS:
        assert f"| `{code}` |" in index, f"{code} has no row in runbooks/alarm-index.md"


@pytest.mark.parametrize("code", sorted(wording.INCIDENT_KINDS))
def test_kind_words_are_plain(code: str) -> None:
    kind = wording.INCIDENT_KINDS[code]
    for text in (kind.title, kind.meaning):
        assert "_" not in text, f"{code}: a code leaked into {text!r}"
        assert "—" not in text
    assert len(kind.title) <= 60
    assert not kind.title.endswith(".")
    assert kind.meaning.endswith(".") and kind.next_step.endswith(".")


def test_an_unknown_code_still_renders() -> None:
    kind = wording.incident_kind("some_new_code")
    assert kind.title == "Some new code"


def test_playbook_titles_are_plain() -> None:
    for playbook in PLAYBOOKS:
        assert "_" not in playbook.title
        assert playbook.title != playbook.key.replace("_", " ")


#: Every `last_outcome` `apps/workers/healer.py` writes, by the state it is written with.
_OUTCOMES = (
    (None, "open"),
    ("signal:short_calls", "open"),
    ("acted", "mitigated"),
    ("act_failed", "mitigated"),
    ("repaired", "mitigated"),
    ("held", "mitigated"),
    ("held:paused", "mitigated"),
    ("held:forwarded", "mitigated"),
    ("held:held", "mitigated"),
    ("held:unsupported", "mitigated"),
    ("probation", "mitigated"),
    ("paused", "mitigated"),
    ("escalated", "escalated"),
    ("held_for_person", "escalated"),
    ("verified", "resolved"),
    ("restored_by_person", "resolved"),
)


def test_the_worker_writes_no_outcome_this_test_does_not_know() -> None:
    source = (ROOT / "apps" / "workers" / "healer.py").read_text(encoding="utf-8")
    written = set(re.findall(r'outcome="([a-z_]+)"', source)) | set(
        re.findall(r"last_outcome = '([a-z_]+)'", source)
    )
    ledger_outcomes = {"ok", "failed", "skipped", "refused"}
    known = {o for o, _ in _OUTCOMES if o} | ledger_outcomes
    assert written <= known, f"progress() has no words for {sorted(written - known)}"


@pytest.mark.parametrize(("outcome", "state"), _OUTCOMES)
@pytest.mark.parametrize("playbook", sorted(PLAYBOOK_BY_KEY))
def test_progress_is_plain(outcome: str | None, state: str, playbook: str) -> None:
    line = wording.progress(
        playbook=playbook,
        automatic=PLAYBOOK_BY_KEY[playbook].automatic,
        state=state,
        attempts=2,
        last_outcome=outcome,
    )
    assert line and "_" not in line and "signal" not in line


def test_progress_reads_the_founders_examples() -> None:
    assert (
        wording.progress(
            playbook="money_review",
            automatic=False,
            state="escalated",
            attempts=0,
            last_outcome="escalated",
        )
        == "Not fixable automatically, handed to you"
    )
    assert (
        wording.progress(
            playbook="outbox_replay",
            automatic=True,
            state="resolved",
            attempts=3,
            last_outcome="verified",
        )
        == "Fixed automatically after 3 tries"
    )
