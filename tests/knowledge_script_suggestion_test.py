"""The writer's brief for a `knowledge` script suggestion (D-923), kept while suggestions
written before an agent lost its own script (D-997) are still drained by
`workers/script_proposal.draft_script_proposal`."""

from __future__ import annotations

from apps.workers import script_proposal as worker


def test_a_both_agent_is_asked_for_its_calling_opening_too() -> None:
    assert "the opening line when it calls" in worker.knowledge_change("x", both=True)
    assert "when it calls" not in worker.knowledge_change("x", both=False)
