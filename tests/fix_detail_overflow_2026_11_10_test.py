"""A fix ("Fix them first") that takes a step's reworded instruction but keeps its "sounds like"
line must not build a step over the 600-character step detail.

`kept_to_paths` takes only the lines the check named from the written script. A step's
instruction and its "sounds like" line share one budget (`ConversationStage._detail_fits_a_step`),
so a longer instruction (the usual way a fix asks one more question) beside the line it kept
from the owner's script failed validation: the job crashed after the model was paid, the
spend never reached the ledger (hard rule 7) and the owner's screen waited on "drafting" until
the ten-minute stale note."""

from __future__ import annotations

from calevate_shared.call_script import STAGE_DETAIL_MAX, CallScript, ConversationStage

LINE = "Signing up takes two minutes on the app, and the first season is free for every farmer."
#: Fits beside LINE (the owner's script), and does not once it is longer by the fix.
SHORT = "Explain how they can sign up. " * 15
LONG = "Explain how they can sign up and ask whether they use the app today. " * 8


def _script(instruction: str, line: str) -> CallScript:
    return CallScript(
        schema_version=2,
        stages=[
            ConversationStage(
                id="signup", name="Signup", instruction=instruction, sounds_like=line
            ),
            ConversationStage(id="close", name="Close", instruction="Thank them and end the call."),
        ],
    )


BASE = _script(SHORT.strip(), LINE)
WRITTEN = _script(LONG.strip(), "")


def test_the_fixture_is_the_overflow() -> None:
    assert len(LONG.strip()) + len(LINE) > STAGE_DETAIL_MAX - 20
    assert len(LONG.strip()) <= STAGE_DETAIL_MAX
