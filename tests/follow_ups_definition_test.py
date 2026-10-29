"""A Follow-up's definition (D-940): the shape checks, step summaries and call-back keys,
with no database."""

from __future__ import annotations

import uuid

import pytest
from apps.api.follow_ups import definition as d
from apps.api.follow_ups import runner


def _steps(*raw: dict[str, object]) -> list[d.AnyStep]:
    return d.load_steps(list(raw))


def _codes(problems: list[d.Problem]) -> set[tuple[str | None, str]]:
    return {(p.step_id, p.code) for p in problems}


MANUAL = d.ManualTrigger(kind="manual")


def test_a_clean_definition_has_no_problems() -> None:
    steps = _steps(
        {"id": "s1", "kind": "call", "next": {"answered": "s2"}},
        {"id": "s2", "kind": "decide", "on": {"interested": "s3"}},
        {"id": "s3", "kind": "end", "goal": True},
    )
    assert d.shape_problems(MANUAL, steps, d.Settings(goal="interested")) == []


def test_steps_only_go_forward_and_every_exit_names_a_step() -> None:
    steps = _steps(
        {"id": "s1", "kind": "wait", "minutes": 5, "next": "s2"},
        {"id": "s2", "kind": "set_status", "status": "hot", "next": "s1"},
        {"id": "s3", "kind": "assign", "user_id": str(uuid.uuid4()), "next": "nope"},
    )
    assert _codes(d.shape_problems(MANUAL, steps, d.Settings())) == {
        ("s2", "step_goes_back"),
        ("s3", "step_missing"),
    }


def test_the_definition_level_problems() -> None:
    assert _codes(d.shape_problems(MANUAL, [], d.Settings())) == {(None, "no_steps")}
    repeated = _steps(
        {"id": "s1", "kind": "end"},
        {"id": "s1", "kind": "end"},
    )
    assert ("s1", "step_id_repeated") in _codes(d.shape_problems(MANUAL, repeated, d.Settings()))
    many = _steps(*({"id": f"s{i}", "kind": "end"} for i in range(d.MAX_STEPS + 1)))
    assert (None, "too_many_steps") in _codes(d.shape_problems(MANUAL, many, d.Settings()))
    unused_goal = d.shape_problems(
        MANUAL, _steps({"id": "s1", "kind": "end"}), d.Settings(goal="x")
    )
    assert _codes(unused_goal) == {(None, "goal_unused")}


def test_a_step_that_reads_a_call_needs_one_before_it() -> None:
    steps = _steps(
        {"id": "s1", "kind": "tell_team", "why": "Look", "next": "s2"},
        {"id": "s2", "kind": "decide", "on": {}},
        {"id": "s3", "kind": "action", "action_id": str(uuid.uuid4())},
    )
    found = _codes(d.shape_problems(MANUAL, steps, d.Settings()))
    assert {("s1", "needs_a_call"), ("s2", "needs_a_call"), ("s3", "needs_a_call")} <= found
    assert ("s2", "decide_empty") in found
    ended = d.CallEndedTrigger(kind="call_ended")
    assert not {
        p for p in d.shape_problems(ended, steps, d.Settings()) if p.code == "needs_a_call"
    }, "a call-ended Follow-up starts with its call"


def test_waits_and_message_values_must_be_clear() -> None:
    steps = _steps(
        {"id": "s1", "kind": "wait", "next": "s2"},
        {"id": "s2", "kind": "wait", "minutes": 1, "days": 1, "next": "s3"},
        {"id": "s3", "kind": "wait", "hours": 1, "at": "10:00", "next": "s4"},
        {
            "id": "s4",
            "kind": "whatsapp",
            "template_id": str(uuid.uuid4()),
            "values": [{"source": "lead_field"}, {"source": "text", "text": " "}],
        },
    )
    assert _codes(d.shape_problems(MANUAL, steps, d.Settings())) == {
        ("s1", "wait_unclear"),
        ("s2", "wait_unclear"),
        ("s3", "wait_unclear"),
        ("s4", "value_unclear"),
    }


def test_untyped_steps_come_back_as_problems_named_by_step() -> None:
    steps, problems = d.parse_steps(
        [{"id": "s1", "kind": "call", "retries": 9}, {"id": "s2", "kind": "nope"}]
    )
    assert steps == []
    assert {p.step_id for p in problems} >= {"s1"}
    assert all(p.code == "step_invalid" for p in problems)
    _none, unreadable = d.parse_steps("not a list")
    assert unreadable and unreadable[0].step_id is None
    ok, nothing = d.parse_steps([{"id": "s1", "kind": "end"}])
    assert len(ok) == 1 and nothing == []


@pytest.mark.parametrize(
    ("raw", "line"),
    [
        (
            {"id": "s1", "kind": "call", "retries": 2, "retry_minutes": 60},
            "Call with their agent straight away, try 3 times, an hour apart",
        ),
        (
            {"id": "s1", "kind": "call", "wait_seconds": 45},
            "Call with their agent after 45 seconds",
        ),
        ({"id": "s1", "kind": "call", "wait_minutes": 1440}, "Call with their agent after a day"),
        ({"id": "s1", "kind": "decide", "on": {"a": None}}, "Check how the call went"),
        ({"id": "s1", "kind": "wait", "days": 2}, "Wait 2 days"),
        ({"id": "s1", "kind": "wait", "minutes": 1}, "Wait a minute"),
        ({"id": "s1", "kind": "wait", "minutes": 7}, "Wait 7 minutes"),
        (
            {"id": "s1", "kind": "wait", "until_field": "visit_date", "offset_days": -1},
            "Wait until 1 day(s) before the lead's visit date",
        ),
        (
            {"id": "s1", "kind": "wait", "until_field": "visit_date"},
            "Wait until the lead's visit date",
        ),
        ({"id": "s1", "kind": "set_status", "status": "won"}, "Mark the lead won"),
        ({"id": "s1", "kind": "tell_team", "why": "Hot one"}, "Tell the team: Hot one"),
        ({"id": "s1", "kind": "end", "goal": True}, "Finish (goal reached)"),
        ({"id": "s1", "kind": "end"}, "Finish"),
    ],
)
def test_every_step_reads_as_one_plain_line(raw: dict[str, object], line: str) -> None:
    names = d.Names(agents={}, templates={}, users={}, actions={})
    assert d.summary(d.load_steps([raw])[0], names) == line


def test_names_fill_the_summaries() -> None:
    agent, template, user, action = (uuid.uuid4() for _ in range(4))
    names = d.Names(
        agents={agent: "Riya"},
        templates={template: "Reminder"},
        users={user: "Asha"},
        actions={action: "CRM"},
    )
    steps = _steps(
        {"id": "s1", "kind": "call", "agent_id": str(agent)},
        {"id": "s2", "kind": "whatsapp", "template_id": str(template)},
        {"id": "s3", "kind": "assign", "user_id": str(user)},
        {"id": "s4", "kind": "action", "action_id": str(action)},
    )
    assert [d.summary(s, names) for s in steps] == [
        "Call with Riya straight away",
        'Send the WhatsApp "Reminder"',
        "Give the lead to Asha",
        'Run "CRM"',
    ]


def test_the_exits_of_each_kind() -> None:
    steps = _steps(
        {"id": "s1", "kind": "call", "next": {"answered": "s2"}},
        {"id": "s2", "kind": "decide", "on": {"x": "s3"}, "other": None},
        {"id": "s3", "kind": "end"},
    )
    assert d.exits_of(steps[0]) == {"answered": "s2", "not_reached": None}
    assert d.exits_of(steps[1]) == {"x": "s3", "other": None}
    assert d.exits_of(steps[2]) == {}
    assert d.step_by_id(steps, "zz") is None and d.first_step([]) is None


def test_a_call_back_key_round_trips_and_nothing_else_parses() -> None:
    run_id = uuid.uuid4()
    key = runner.callback_key(run_id, "s2", 3)
    assert runner.parse_callback_key(key) == runner.CallbackRef(run_id, "s2", 3)
    tagged = runner.callback_key(run_id, "s2", 0, tag="ab12")
    assert runner.parse_callback_key(tagged) == runner.CallbackRef(run_id, "s2", 0)
    for other in (
        None,
        "",
        "lead-retry:1:x",
        "follow-up:nope:s1:0",
        "follow-up:x",
        (f"follow-up:{run_id}:s1:z"),
    ):
        assert runner.parse_callback_key(other) is None


def test_a_refusal_for_good_names_why_the_run_ended() -> None:
    assert runner.end_reason_for_refusal("dnc") == "do_not_call"
    assert runner.end_reason_for_refusal("engine_recipient_opted_out") == "do_not_call"
    assert runner.end_reason_for_refusal("trial_ended") == "refused:trial_ended"
