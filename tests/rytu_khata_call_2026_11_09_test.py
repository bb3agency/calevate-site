"""The founder's Rytu Khata call of 9 Nov 2026, 20:32 (agent Varsha, outbound, Telugu).

The agent greeted and introduced itself a second time after the opening, because its first
step said to; spelled the app's web address letter by letter; wrote "Android" and "iPhone"
in English letters; opened reply after reply with the same reaction; and said four sentences
in one turn. Lines here are English, or taken from the repo's own spoken-style data: the
checks read English instructions or compare words, in any language.
"""

from __future__ import annotations

from apps.api.agents.call_mistakes import LESSONS, mistakes_in
from apps.api.agents.call_rules import SCRIPT_FLOW_RULE
from apps.api.agents.script_lint import (
    flow_problems,
    opening_redone_problems,
    same_opener_problems,
)
from calevate_shared.call_script import CallScript, ConversationStage
from calevate_shared.engine import (
    OPENING_CONTINUES_RULE,
    VOICE_STYLE_GUIDANCE,
    AgentConfig,
    compose_engine_prompt,
    screen_steps_bullet,
)

STEP_ONE = (
    "Greet the lead by name, identify yourself as Varsha from Rytu Khata, state that you are "
    "calling about their registration, and ask if they can talk now."
)


def _stage(sid: str, instruction: str, line: str) -> ConversationStage:
    return ConversationStage(id=sid, name=sid, instruction=instruction, sounds_like=line)


def _script(*stages: ConversationStage, opening: str = "Hello, can we talk now?") -> CallScript:
    return CallScript(schema_version=2, opening_line=opening, stages=list(stages))


# --- 1. the introduction said twice ------------------------------------------------------------


def test_a_step_that_greets_after_the_opening_is_found() -> None:
    script = _script(
        _stage("s1", STEP_ONE, "Is now a good time?"),
        _stage("s2", "Thank them and say goodbye.", "Thanks, goodbye."),
    )
    problems = opening_redone_problems(script)
    assert len(problems) == 1 and problems[0].startswith("stages.0.instruction: greets")
    assert problems[0] in flow_problems(script)
    assert opening_redone_problems(script.model_copy(update={"opening_line": ""})) == []


def test_a_step_starting_after_the_opening_passes() -> None:
    script = _script(
        _stage("s1", "Say why you are calling, then ask if they installed the app.", "Hi."),
    )
    assert opening_redone_problems(script) == []


def test_the_in_call_rule_beats_a_step_that_says_to_introduce() -> None:
    assert "A step says to greet, say who you are or ask if now suits? That is done" in (
        OPENING_CONTINUES_RULE
    )
    cfg = AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="Varsha",
        business="B",
        direction="outbound",
        language_primary="te-IN",
        system_prompt="[TASK FLOW]\nHelp them.",
        opening_line="Hello, can we talk now?",
        call_is_recorded=True,
    )
    assert OPENING_CONTINUES_RULE in compose_engine_prompt(cfg)


def test_the_writers_keep_the_opening_out_of_the_steps() -> None:
    assert "no stage does any of that again" in SCRIPT_FLOW_RULE
    assert "open or end with the same words" in SCRIPT_FLOW_RULE


def test_a_dropped_introduction_carries_the_name_and_a_title_only_before_a_break() -> None:
    from calevate_shared.engine import _without_introduction

    names = ("Varsha",)
    titled = _without_introduction("Hello {{lead_name}} sir, this is Varsha. Can we talk?", names)
    assert titled == "{{lead_name}} sir, Can we talk?"
    # The word after the field begins the sentence's own words, so it is not a title.
    bare = _without_introduction("Hello {{lead_name}} this is Varsha. Can we talk?", names)
    assert bare == "{{lead_name}}, Can we talk?"
    comma = _without_introduction("Hello {{lead_name}}, this is Varsha. Can we talk?", names)
    assert comma == "{{lead_name}}, Can we talk?"


# --- 2. the web address -----------------------------------------------------------------------


def test_a_web_address_is_said_as_it_reads_and_spelled_only_when_not_found() -> None:
    bullet = screen_steps_bullet("en-IN")
    assert "Say a web address once, as it reads, no www: a word as a word" in bullet
    assert "Spell a word by letters only if they cannot find it" in bullet
    assert "send the link if a tool can" in bullet
    assert "one letter at a time" not in bullet


# --- 4. the same reaction every turn ----------------------------------------------------------


def test_step_lines_opening_with_the_same_reaction_are_found() -> None:
    script = _script(
        _stage("s1", "Ask which phone they have.", "OK, which phone do you have?"),
        _stage("s2", "Ask if they installed it.", "OK, is it installed now?"),
        _stage("s3", "Thank them.", "Thanks, goodbye."),
    )
    problems = same_opener_problems(script)
    assert problems == [
        "stages.1.sounds_like: opens with the same words as step 1's line; the agent copies "
        "how lines open, so its replies would all begin alike. Open it with its own point."
    ]


def test_the_reaction_rule_holds_for_the_whole_call() -> None:
    assert "no two replies start or end alike." in VOICE_STYLE_GUIDANCE


def test_a_real_call_names_the_same_opening_and_a_long_turn() -> None:
    assert {"same_opening", "too_long"} <= set(LESSONS)

    class _T:
        def __init__(self, idx: int, speaker: str, text: str) -> None:
            self.idx, self.speaker, self.text = idx, speaker, text

    turns = [_T(0, "agent", "Hello, can we talk now?")]
    for i, line in enumerate(
        ("Yes.", "OK, which phone?", "Android.", "OK, is it installed?", "No.", "OK, open it.")
    ):
        turns.append(_T(i + 1, "caller" if i % 2 == 0 else "agent", line))
    turns.append(_T(7, "caller", "Done."))
    assert "same_opening" in mistakes_in(turns, language="en-IN")
