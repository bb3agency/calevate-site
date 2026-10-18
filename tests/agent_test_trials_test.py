"""Tries per test, the owner's score, before against after, and how a reply sounds (D-828).

Founder, 19 Oct 2026: a run read "0 of 13, worse than last time (2 of 12)" after Pip's
fixes. The two runs asked different tests, each once, and 25 of the 34 failures across the
last three production runs were textbook words the script improver cannot change.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.agents import test_conversations, trial_results
from apps.api.agents.test_conversations import (
    MAX_MESSAGES,
    Judged,
    Scenario,
    TestRun,
    Turn,
    compose_set,
    decide,
    needs_improving,
    probe_scenario,
    standard_scenarios,
)
from apps.workers import agent_test_conversations as worker

TELUGU_CALLER = "మీ దగ్గర మిర్చి ఉందా అండి?"


def _try(key: str, verdict: str, owner: str | None = "script", **extra: Any) -> dict[str, Any]:
    return {
        "key": key,
        "title": key,
        "verdict": verdict,
        "owner": None if verdict == "passed" else owner,
        "fix": None if verdict == "passed" else "script_step",
        "conversation": [{"said": "x", "reply": verdict}],
        **extra,
    }


def _test(key: str, *verdicts: str, owner: str | None = "script", **extra: Any) -> dict[str, Any]:
    return trial_results.aggregate([_try(key, v, owner, **extra) for v in verdicts])


# --- several tries ------------------------------------------------------------------------


def test_a_test_works_every_time_some_of_the_time_or_never() -> None:
    assert trial_results.reliability(_test("a", "passed", "passed", "passed")) == "passed"
    assert trial_results.reliability(_test("b", "passed", "failed", "passed")) == "flaky"
    assert trial_results.reliability(_test("c", "failed", "needs_fix", "failed")) == "failed"
    assert trial_results.reliability(_test("d", "unjudged", "unjudged", "unjudged")) == "unjudged"
    # A try nobody could judge is left out of the count, not counted as a pass or a failure.
    mixed = _test("e", "passed", "unjudged", "passed")
    assert (mixed["passes"], mixed["judged_tries"], mixed["verdict"]) == (2, 2, "passed")


def test_the_shown_try_is_the_first_that_failed_and_every_try_is_kept() -> None:
    flaky = trial_results.aggregate(
        [
            _try("k", "passed"),
            {**_try("k", "failed", "knowledge"), "reason": "It made up a price."},
            _try("k", "passed"),
        ]
    )
    assert flaky["verdict"] == "failed" and flaky["owner"] == "knowledge"
    assert flaky["reason"] == "It made up a price."
    assert [t["verdict"] for t in flaky["tries"]] == ["passed", "failed", "passed"]


def test_a_result_stored_before_trials_reads_as_one_try() -> None:
    assert trial_results.reliability({"verdict": "needs_fix"}) == "failed"
    assert trial_results.reliability({"verdict": "passed"}) == "passed"
    assert trial_results.reliably_failing({"verdict": "failed"})


def test_the_improver_only_chases_tests_that_fail_on_most_tries() -> None:
    """FAILS IF one unlucky answer out of three sends the improver to rewrite a working
    script (D-828 E)."""
    once = _test("once", "passed", "failed", "passed")
    mostly = _test("mostly", "failed", "passed", "failed")
    always = _test("always", "failed", "failed", "failed")
    ours = _test("ours", "failed", "failed", "failed", owner="platform")
    assert not trial_results.reliably_failing(once)
    assert trial_results.reliably_failing(mostly) and trial_results.reliably_failing(always)
    run = _run([once, mostly, always, ours])
    assert [r["key"] for r in needs_improving(run)] == ["mostly", "always"]


# --- the owner's score --------------------------------------------------------------------


def _run(results: list[dict[str, Any]], **fields: Any) -> TestRun:
    from datetime import UTC, datetime

    return TestRun(
        id=uuid.uuid4(),
        status="done",
        prompt_version=fields.pop("prompt_version", 1),
        results=results,
        error_code=None,
        created_at=datetime.now(UTC),
        completed_at=None,
        **fields,
    )


def test_the_owners_score_counts_only_what_their_script_or_knowledge_decides() -> None:
    """FAILS IF a failure the owner cannot fix sinks their score (the screenshot's "We're
    fixing this" counted under "Need a fix")."""
    results = [
        _test("works", "passed", "passed", "passed"),
        _test("flaky", "passed", "failed", "passed"),
        _test("broken", "failed", "failed", "failed", owner="knowledge"),
        _test("ours", "failed", "failed", "failed", owner="platform"),
        _test("probe_ai", "passed", "passed", "passed", probe="ai"),
        _test("probe_stop", "failed", "failed", "failed", owner="platform", probe="stop_calling"),
        _test("read", "unjudged", "unjudged", "unjudged", owner=None),
        _test("person", "unjudged", "unjudged", "unjudged", owner="setting", probe="person"),
        _test("wrong", "failed", "failed", "failed"),
    ]
    score = _run(results, wrong_keys=frozenset({"wrong"})).score
    assert (score.passed, score.counted, score.unreliable) == (1, 3, 1)
    assert (score.ours, score.check, score.setting) == (2, 1, 1)
    places = {r["key"]: trial_results.standing(r, {"wrong"}) for r in results}
    assert places == {
        "works": "works",
        "flaky": "unreliable",
        "broken": "broken",
        "ours": "ours",
        "probe_ai": "works",
        "probe_stop": "ours",
        "read": "check",
        "person": "setting",
        "wrong": "wrong",
    }


# --- before against after -------------------------------------------------------------------


def test_before_and_after_compare_the_same_tests_one_by_one() -> None:
    before = [
        _test("fixed", "failed", "failed", "failed"),
        _test("broken", "passed", "passed", "passed"),
        _test("still", "failed", "failed", "failed"),
        _test("same", "passed", "passed", "passed"),
        _test("ours", "failed", "failed", "failed", owner="platform"),
    ]
    after = [
        _test("fixed", "passed", "passed", "passed"),
        _test("broken", "passed", "failed", "passed"),
        _test("still", "failed", "passed", "failed"),
        _test("same", "passed", "passed", "passed"),
        _test("ours", "passed", "passed", "passed"),
        _test("new", "failed", "failed", "failed"),
    ]
    found = trial_results.compare(before, after)
    assert found.changes == {
        "fixed": "fixed",
        "broken": "broken",
        "still": "still",
        "same": "same",
        # Out of the owner's score before (ours), so there is no fair before: new.
        "ours": "new",
        "new": "new",
    }


def test_the_screenshots_worse_than_last_time_was_a_different_test_set() -> None:
    """FAILS IF a comparison counts tests only one run asked. 18 Oct: 2 of 12; 19 Oct: 0 of
    13 with new callers mixed in. On the tests both runs asked, the comparison says what
    actually moved, and the new ones move no headline."""
    before = [_test("asked_both_1", "passed"), _test("asked_both_2", "failed")]
    before += [_test(f"only_then_{i}", "failed") for i in range(10)]
    after = [_test("asked_both_1", "passed"), _test("asked_both_2", "failed")]
    after += [_test(f"only_now_{i}", "failed") for i in range(11)]
    found = trial_results.compare(before, after)
    assert (found.count("broken"), found.count("fixed")) == (0, 0)
    assert (found.count("same"), found.count("still"), found.count("new")) == (1, 1, 11)


# --- defect 4: the hand-over reply in a test chat ---------------------------------------------


def test_the_sandboxs_hand_over_reply_is_not_the_agents_language() -> None:
    """The screenshot: a Telugu caller asked for a person and the test chat answered "I'm
    sorry, but I can't connect you to a person." The sandbox switches the hand-over off and
    says what it would have done (test-chat.md:7), so that English is not the agent's own
    language behaviour, and it never fails the owner."""
    person = probe_scenario("person", "te-IN")
    result = decide(
        person,
        [Turn(said=person.turns[0], reply="I'm sorry, but I can't connect you to a person.")],
        None,
        language="te-IN",
        unjudged_reason="",
        rules=test_conversations.RuleContext(hand_over="someone_on_duty"),
    )
    assert result["verdict"] == "unjudged" and result["owner"] is None
    assert "wrong_language" not in {s["kind"] for s in result["sounds"]}
    assert result["channel"] == test_conversations.TEST_CHAT
    # Any other test that answers a Telugu caller in English is noted, never failed.
    other = decide(
        Scenario(key="k", title="t", category="business", turns=(TELUGU_CALLER,), expect=""),
        [Turn(said=TELUGU_CALLER, reply="Sorry, we do not have that item right now.")],
        Judged(verdict="passed", reason="Honest."),
        language="te-IN",
        unjudged_reason="",
    )
    assert other["verdict"] == "passed"
    assert {s["kind"] for s in other["sounds"]} == {"wrong_language"}


# --- the production runs of 18-19 Oct 2026 ----------------------------------------------------

#: The failure classes of the founder's last three runs (Raghava retail, te-IN), one test
#: each, rebuilt from the per-class summary the founder relayed on 19 Oct 2026 (the raw rows
#: were not available here): 25 with textbook words, of which 4 also said a price in Telugu
#: words, 1 wrote "1 kg", 2 a dash, 2 brackets and 1 three sentences; 3 English replies to a
#: Telugu caller (one of them the hand-over probe); 1 did not take the remove-number step; 1
#: said the caller's part; 1 the judge failed.
_FORMAL = [
    "ధన్యవాదాలు",
    "సహాయం",
    "సహజంగా",
    "చేయబడుతుంది",
    "దయచేసి",
    "వివరాలు",
    "మరియు",
    "పరిమాణం",
    "ఉత్పత్తి",
    "ప్రాంతం",
    "సమాచారం",
    "క్షమించండి",
    "సంప్రదించండి",
]
_EN_DASH = chr(0x2013)
_STYLE_REPLIES = (
    [f"{word} అండి." for word in _FORMAL]
    + [f"{word} అండి." for word in _FORMAL[:2]]
    + [f"{word}, కిలో నాలుగు వందల యాభై రూపాయలు అండి." for word in _FORMAL[:4]]
    + ["దయచేసి 1 kg తీసుకోండి అండి."]
    + [f"{word} {_EN_DASH} చెప్తాను అండి." for word in _FORMAL[5:7]]
    + [f"{word} (ఇక్కడ) ఉంది అండి." for word in _FORMAL[9:11]]
    + ["సహాయం చేస్తాను అండి. మా దగ్గర మిర్చి ఉంది అండి. రేపు delivery చేస్తాం అండి."]
)


def _production_results() -> list[dict[str, Any]]:
    passed = Judged(verdict="passed", reason="It did what the caller needed.")
    results = []
    for i, reply in enumerate(_STYLE_REPLIES):
        scenario = Scenario(key=f"s{i}", title="t", category="business", turns=("x",), expect="")
        results.append(
            decide(
                scenario,
                [Turn(said="x", reply=reply)],
                passed,
                language="te-IN",
                unjudged_reason="",
            )
        )
    english = "Sorry, we do not have that item right now."
    for i in range(2):
        scenario = Scenario(key=f"en{i}", title="t", category="business", turns=("x",), expect="")
        results.append(
            decide(
                scenario,
                [Turn(said=TELUGU_CALLER, reply=english)],
                passed,
                language="te-IN",
                unjudged_reason="",
            )
        )
    person = probe_scenario("person", "te-IN")
    results.append(
        decide(
            person,
            [Turn(said=person.turns[0], reply="I'm sorry, I can't connect you.")],
            None,
            language="te-IN",
            unjudged_reason="",
            rules=test_conversations.RuleContext(hand_over="someone_on_duty"),
        )
    )
    stop = probe_scenario("stop_calling", "te-IN")
    results.append(
        decide(
            stop,
            [Turn(said=stop.turns[0], reply="సరే అండి.")],
            None,
            language="te-IN",
            unjudged_reason="",
        )
    )
    order = Scenario(key="order", title="t", category="business", turns=("x",), expect="")
    results.append(
        decide(
            order,
            [Turn(said="x", reply="Agent: సరే అండి. Caller: ఒక కిలో ఇవ్వండి.")],
            passed,
            language="te-IN",
            unjudged_reason="",
        )
    )
    judged = Scenario(key="prices", title="t", category="business", turns=("x",), expect="")
    results.append(
        decide(
            judged,
            [Turn(said="x", reply="నేను AI assistant ని అండి.")],
            Judged(verdict="failed", reason="It did not answer the price.", fix="knowledge"),
            language="te-IN",
            unjudged_reason="",
        )
    )
    return [trial_results.aggregate([r]) for r in results]


def test_the_production_runs_under_the_new_rules() -> None:
    """FAILS IF how a reply sounds fails a test or reaches the improver again. The same
    failures, read under D-828: one test is the owner's to fix, two are ours, and the rest
    did the job and carry notes we count per kind."""
    results = _production_results()
    assert trial_results.sound_counts(results) == {
        "formal_words": 25,
        "spoken_number": 4,
        "symbols": 2,
        "brackets": 2,
        "wrong_language": 2,
        "money_digits": 1,
        "too_long": 1,
    }
    run = _run(results)
    assert [r["key"] for r in needs_improving(run)] == ["prices"]
    assert sorted(r["key"] for r in results if trial_results.standing(r) == "ours") == [
        "order",
        "probe_stop_calling",
    ]
    score = run.score
    assert (score.passed, score.counted, score.ours) == (
        len(_STYLE_REPLIES) + 2,
        len(_STYLE_REPLIES) + 3,
        2,
    )


def test_one_alarm_carries_the_count_per_way_it_sounded(monkeypatch: pytest.MonkeyPatch) -> None:
    raised: list[dict[str, Any]] = []
    monkeypatch.setattr(worker, "alert", lambda stage, code, **fields: raised.append(fields))
    ids = {"tenant_id": uuid.uuid4(), "agent_id": uuid.uuid4(), "run_id": uuid.uuid4()}
    worker._alarm_platform_failures(_production_results(), **ids)
    (fields,) = raised
    assert "2 test(s) failed on a rule the platform owns" in fields["detail"]
    assert "formal_words=25" in fields["detail"] and "wrong_language=2" in fields["detail"]


# --- the set and its cost ----------------------------------------------------------------


def test_a_set_fits_every_try_and_a_run_has_a_stated_reply_bound() -> None:
    probes = [probe_scenario(p, "te-IN") for p in test_conversations.PROBES]
    many = [
        Scenario(
            key=f"g{i}",
            title="t",
            category="business",
            turns=("a", "b"),
            expect="",
            source="generated",
        )
        for i in range(12)
    ]
    standard = [s for s in standard_scenarios("te-IN", "outbound") if s.probe is None]
    composed = compose_set(
        probes=probes, real=[], saved=[], practice=many, specimen=[], standard=standard
    )
    assert {s.probe for s in composed if s.probe} == set(test_conversations.PROBES)
    assert sum(len(s.turns) for s in composed) <= MAX_MESSAGES
    # Practice the owner asked for comes before the standard callers under the cap.
    assert composed[len(probes)].key == "g0"
    assert test_conversations.MAX_REPLIES_PER_RUN == trial_results.TRIALS * MAX_MESSAGES == 60
