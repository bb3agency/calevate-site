"""A fix of the lines a check named changes only those lines (A-02), whatever the model
returns: the healer's fix of a mistake on real calls is written this way (D-1005)."""

from __future__ import annotations

from apps.api.agents import script_proposals
from calevate_shared.call_script import CallScript


def test_a_fix_keeps_every_line_the_check_did_not_name() -> None:
    """A-02: whatever the model returns, only the flagged lines change and none is emptied."""
    from calevate_shared.call_script import ConversationStage, Objection

    base = CallScript(
        schema_version=2,
        opening_line="Hello, how can I help?",
        goal="Help callers with the app.",
        stages=[
            ConversationStage(id="a", name="Greet", instruction="Greet them.", sounds_like="Hi?"),
            ConversationStage(id="b", name="Help", instruction="Help them.", sounds_like="Ok"),
        ],
        objections=[Objection(objection="Busy", response="Call later.")],
    )
    written = CallScript(
        schema_version=2,
        opening_line="",
        goal="Sell them more.",
        stages=[
            ConversationStage(id="b", name="Help", instruction="Help.", sounds_like="Fixed line"),
        ],
        objections=[],
    )
    kept = script_proposals.kept_to_paths(written, base, ["stages.1.sounds_like"])
    assert kept.stages[1].sounds_like == "Fixed line"
    assert kept.stages[0] == base.stages[0]
    assert kept.stages[1].instruction == "Help them."
    assert (kept.goal, kept.opening_line, kept.objections) == (
        base.goal,
        base.opening_line,
        base.objections,
    )
    # A flagged line the model emptied stays as written.
    emptied = written.model_copy(
        update={"stages": [written.stages[0].model_copy(update={"sounds_like": ""})]}
    )
    assert script_proposals.kept_to_paths(emptied, base, ["stages.1.sounds_like"]) == base
