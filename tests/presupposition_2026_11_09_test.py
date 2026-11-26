"""Nothing about the caller is taken as given: the founder's Rytu Khata call of 9 Nov 2026.

Agent Varsha (outbound, Telugu) asked a caller who had only registered "you already use the
app, right? what do you use it for most?". The line is a step's own example, which the
in-call model copies, and the script reached that step whatever the caller said about using
the app. Lines here are English: the checks read the English instructions and conditions, and
the practice check compares the script's own line with the reply, in any language.
"""

from __future__ import annotations

from apps.api.agents.call_rules import CALL_RULES
from apps.api.agents.script_lint import order_problems, presumed_lines
from apps.api.agents.test_conversations import RuleContext, Turn, hard_check, probe_scenario
from apps.api.agents.turn_checks import (
    JOB_KINDS,
    SCRIPT_KINDS,
    conversation_problems,
    said_presumed_line,
)
from apps.workers.opening_line import OPENING_WRITER_INSTRUCTION, PLACED_TASK
from calevate_shared.call_script import (
    CallScript,
    ConversationStage,
    StageBranch,
)
from calevate_shared.engine import CALL_REASON_RULE, AgentConfig, compose_engine_prompt
from calevate_shared.spoken_guard import WRITTEN_FORM_RULE

USED_LINE = "You already use the app, right? What do you use it for most?"


def _stage(
    sid: str, name: str, instruction: str, line: str = "", **kw: object
) -> ConversationStage:
    return ConversationStage(id=sid, name=name, instruction=instruction, sounds_like=line, **kw)  # type: ignore[arg-type]


def _script(*stages: ConversationStage) -> CallScript:
    return CallScript(schema_version=2, stages=list(stages))


CHECK = _stage("s1", "Check installation", "Ask if they installed the app.", "Is it on your phone?")
USAGE = _stage("s2", "Purpose of usage", "Ask what they use the app for most.", USED_LINE)
CLOSE = _stage("s3", "Close", "Thank them and say goodbye.", "Thanks, goodbye.")


# --- the script check -------------------------------------------------------------------------


def test_a_linear_script_reaching_a_usage_step_with_every_caller_is_found() -> None:
    # No step helps them set anything up, which is what the 6 Nov check needed to fire.
    problems = order_problems(_script(CHECK, USAGE, CLOSE))
    assert len(problems) == 1
    assert problems[0].startswith("stages.1.instruction: takes as given that the caller uses it")


def test_a_way_out_for_callers_who_only_installed_it_does_not_gate_the_usage_step() -> None:
    check = CHECK.model_copy(
        update={
            "branches": [StageBranch(when="they say they installed it", target="s2")],
            "otherwise": "s3",
        }
    )
    assert order_problems(_script(check, USAGE, CLOSE))


def test_a_question_then_a_way_out_for_callers_who_use_it_passes() -> None:
    ask = _stage(
        "s1",
        "Check usage",
        "Ask whether they have used the app yet.",
        "Have you used the app yet?",
        branches=[StageBranch(when="they say they use the app", target="s2")],
        otherwise="s3",
    )
    usage = USAGE.model_copy(update={"otherwise": "s3"})
    assert order_problems(_script(ask, usage, CLOSE)) == []
    assert presumed_lines(_script(ask, usage, CLOSE)) == ()


def test_a_condition_that_denies_use_does_not_gate() -> None:
    ask = _stage(
        "s1",
        "Check usage",
        "Ask whether they have used the app yet.",
        "Have you used the app yet?",
        branches=[StageBranch(when="they have not used it yet", target="s2")],
        otherwise="s3",
    )
    assert order_problems(_script(ask, USAGE.model_copy(update={"otherwise": "s3"}), CLOSE))


def test_a_step_that_asks_first_gates_itself_in_a_linear_script() -> None:
    usage = USAGE.model_copy(
        update={
            "instruction": "Ask whether they have used the app yet; if they have, ask what "
            "they use it for most."
        }
    )
    assert order_problems(_script(CHECK, usage, CLOSE)) == []
    only_users = USAGE.model_copy(
        update={"instruction": "If they said they use the app, ask what they use it for most."}
    )
    assert order_problems(_script(CHECK, only_users, CLOSE)) == []


def test_an_instruction_taking_use_as_given_is_found_too() -> None:
    confirm = _stage("s2", "Confirm", "Confirm they are already using the app daily.", "Daily?")
    assert order_problems(_script(CHECK, confirm, CLOSE))


def test_the_line_of_a_found_step_is_what_the_practice_check_looks_for() -> None:
    assert presumed_lines(_script(CHECK, USAGE, CLOSE)) == (USED_LINE,)


# --- the writers ------------------------------------------------------------------------------


def test_the_opening_writers_never_say_the_person_has_or_uses_something() -> None:
    assert "already has or uses something" in OPENING_WRITER_INSTRUCTION
    assert "has or uses something" in PLACED_TASK


def test_the_judge_fails_a_reply_that_takes_the_callers_use_as_given() -> None:
    facts = next(rule for rule in CALL_RULES if rule.key == "facts")
    assert "never takes as given what the caller did, has or uses" in facts.judge


# --- the in-call prompt -----------------------------------------------------------------------


def _placed() -> AgentConfig:
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="Varsha",
        business="B",
        direction="outbound",
        language_primary="te-IN",
        system_prompt="[TASK FLOW]\nHelp them.",
        opening_line="Hello, is now a good time?",
        call_is_recorded=True,
    )


def test_a_placed_call_never_takes_what_the_person_has_or_uses_from_a_steps_line() -> None:
    assert "have or use something unless they said so on this call or THIS CALL says so" in (
        CALL_REASON_RULE
    )
    assert "a step's lines are only examples" in CALL_REASON_RULE
    assert CALL_REASON_RULE in compose_engine_prompt(_placed())
    inbound = _placed().model_copy(update={"direction": "inbound"})
    assert CALL_REASON_RULE not in compose_engine_prompt(inbound)


def test_the_written_form_rule_joins_only_where_the_languages_print_does() -> None:
    # Telugu print joins a case marker to a loanword; standard Hindi writes it apart from a
    # noun, which "always joins" contradicted.
    assert WRITTEN_FORM_RULE.endswith("as the language's print does.")
    assert WRITTEN_FORM_RULE.isascii()


# --- the practice check -----------------------------------------------------------------------


class _Ex:
    def __init__(self, said: str, reply: str) -> None:
        self.said, self.reply, self.tools = said, reply, ()


def test_a_reply_saying_a_presumed_steps_line_is_the_scripts_failure() -> None:
    assert "presumed_state" in JOB_KINDS and "presumed_state" in SCRIPT_KINDS
    exchanges = [
        _Ex("Hello.", "Hello, is now a good time?"),
        _Ex("I only remember registering.", USED_LINE),
    ]
    kinds = {p.kind for p in conversation_problems(exchanges, presumed=(USED_LINE,))}
    assert "presumed_state" in kinds
    assert "presumed_state" not in {p.kind for p in conversation_problems(exchanges)}


def test_a_reply_close_to_the_line_counts_and_another_does_not() -> None:
    assert said_presumed_line("Okay. You already use the app, right? What for most?", [USED_LINE])
    assert said_presumed_line("Have you used the app yet?", [USED_LINE]) is None
    # A line too short to recognise is never matched.
    assert said_presumed_line("Daily?", ["Daily?"]) is None


def test_the_hard_check_sends_it_to_the_script_not_to_us() -> None:
    turns = [Turn("I only registered.", USED_LINE)]
    verdict = hard_check(
        probe_scenario("ai", "en-IN"), turns, rules=RuleContext(presumed=(USED_LINE,))
    )
    assert verdict.verdict == "failed" and verdict.fix == "script_step"
    mixed = [Turn("Hello.", "You enquired with us last week. " + USED_LINE)]
    both = hard_check(
        probe_scenario("ai", "en-IN"), mixed, rules=RuleContext(presumed=(USED_LINE,))
    )
    assert both.fix == "platform"
