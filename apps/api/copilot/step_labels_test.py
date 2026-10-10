"""Every tool the assistant is offered has words for the panel, so none reaches a client as a
machine name."""

from __future__ import annotations

from typing import Any

import pytest

from apps.api.copilot.service import _step_end, _step_start, tool_array
from apps.api.copilot.step_labels import STEP_LABELS, UNKNOWN, step_label


def _name(spec: dict[str, Any]) -> str:
    fn = spec.get("function")
    return str(fn["name"] if isinstance(fn, dict) else spec["name"])


@pytest.mark.parametrize("realm", ["client", "admin"])
def test_every_offered_tool_has_a_label(realm: str) -> None:
    missing = sorted({_name(spec) for spec in tool_array(realm)} - set(STEP_LABELS))  # type: ignore[arg-type]
    assert missing == [], f"add these to copilot/step_labels.STEP_LABELS: {missing}"


def test_labels_are_plain_words_not_identifiers() -> None:
    for name, label in STEP_LABELS.items():
        for text in label:
            assert "_" not in text, name
            assert text[:1].isupper(), name
        assert label.running.endswith("…"), name


def test_an_unknown_name_is_never_echoed() -> None:
    assert step_label("made_up_tool", running=False) == UNKNOWN.done


def test_step_frames_carry_the_label() -> None:
    class _Call:
        id = "c1"
        name = "search_calls"
        arguments = "{}"

    start = _step_start(_Call())  # type: ignore[arg-type]
    end = _step_end(_Call(), status="done", detail="none", started_at=None)  # type: ignore[arg-type]
    assert start.label == "Searching your calls…"
    assert end.label == "Searched your calls"
    assert end.tool == "search_calls"


def test_the_backup_disclosure_is_one_short_line_that_keeps_what_g6_requires() -> None:
    """D-127 G-6: a DIFFERENT model wrote it, and on the no-tools leg what it cannot do.
    The panel shows it as one line, so it stays short, and it names no vendor (D-679)."""
    from apps.api.copilot.service import FALLBACK_NO_TOOLS_NOTE, disclosure_for
    from apps.workers.extraction import (
        PROVIDER_UNAVAILABLE_REASON,
        QUOTA_EXHAUSTED_REASON,
        SARVAM_PROVIDER,
        AssistCapability,
    )

    for reason in (PROVIDER_UNAVAILABLE_REASON, QUOTA_EXHAUSTED_REASON):
        capability = AssistCapability(
            available=True, provider=SARVAM_PROVIDER, fallback_reason=reason
        )
        text = disclosure_for(capability)
        assert text is not None
        assert text.startswith("Answered by our backup model")
        assert text.endswith(FALLBACK_NO_TOOLS_NOTE)
        for capability_named in ("look things up", "change anything", "open another screen"):
            assert capability_named in text
        assert "sarvam" not in text.lower()
        assert len(text) <= 170, text
