"""Several tries of every test, the owner's score, and before against after (D-828).

An agent built on a language model does not answer the same caller the same way twice, so
one conversation per test proves nothing either way: tau-bench measures an agent by whether
it succeeds on every one of k tries (pass^k, arxiv.org/abs/2406.12045; GPT-4o falls to about
25% at k=8 on its retail tasks, sierra.ai/blog/benchmarking-ai-agents), and Anthropic's eval
guide runs "multiple trials to produce more consistent results" and uses pass^k for
customer-facing agents (anthropic.com/engineering/demystifying-evals-for-ai-agents). A test
here is therefore tried `TRIALS` times and reported as working every time, working some of
the time ("not reliable yet"), or not working.

A comparison is only fair on the same tests (Cekura, cekura.ai/discover/how-to-ab-test-
voice-agents: change one thing, keep the scenario set, judge the delta against the
baseline). "Test again" therefore asks exactly the tests of the run it repeats
(`test_conversations.request_run`), and `compare` reads before and after per test: fixed,
newly broken, still failing, still working, or new.

The OWNER'S SCORE counts only what the owner's script and knowledge decide. The four rule
checks every agent keeps, anything our platform owns, a test the owner marked wrong and a
test nobody could judge are left out of it and shown on their own, so fixing the script can
always move the score and nothing the owner cannot change can sink it.

Pure functions over stored result dicts; results stored before D-828 (one try, no `trials`)
read as a single try.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal, cast, get_args

#: Tries per test. Three is the smallest count that tells "works every time" from "works
#: sometimes" (Cekura recommends 3-5 runs per scenario, Vapi allows up to 5 attempts per test
#: case, docs.vapi.ai/test/test-suites) while a whole run stays bounded: every try is one
#: test-chat reply per caller line, so a run is at most `TRIALS * MAX_MESSAGES` replies, and
#: each try is its own worker job inside the 300 s job timeout.
TRIALS: Final = 3

Reliability = Literal["passed", "flaky", "failed", "unjudged"]
Change = Literal["fixed", "broken", "still", "same", "new"]
#: Where a result sits for the owner: `works` every time, `unreliable` some of the time,
#: `broken` never, `setting` (a setting decides it), `check` (nobody could judge it: read
#: it), `ours` (the platform's to fix), `wrong` (the owner marked the test wrong).
Standing = Literal["works", "unreliable", "broken", "setting", "check", "ours", "wrong"]

#: Who can fix a failure (D-823). `script` and `knowledge` go to the improver; `setting`
#: names the setting to open; `platform` is ours and raises an alarm; `test` is a test the
#: owner marked wrong.
Owner = Literal["script", "knowledge", "setting", "platform", "test"]
OWNERS: Final[tuple[str, ...]] = get_args(Owner)
#: Owners whose failures the owner's script or knowledge can fix.
OWNERS_SCRIPT: Final = frozenset({"script", "knowledge"})

#: Who fixes each kind of failure. `style` is a result stored before D-828, when how a reply
#: sounded failed the test: the platform prompt decides that, so it is ours, which also keeps
#: such a result out of the owner's score and out of any before-and-after.
_OWNER_OF_FIX: Final[dict[str, Owner]] = {
    "script_step": "script",
    "objection": "script",
    "style": "platform",
    "knowledge": "knowledge",
    "settings": "setting",
    "platform": "platform",
}
#: A failure whose kind of fix nobody named (a judge answering "none", a result stored before
#: D-823) is the script's, as it always was: the improver may still look at it.
_UNNAMED_OWNER: Final[dict[str, Owner]] = {"failed": "script", "needs_fix": "script"}

_FAILING: Final = frozenset({"failed", "needs_fix"})
_SEVERITY: Final[dict[str, int]] = {"passed": 0, "unjudged": 1, "needs_fix": 2, "failed": 3}


def owner_of(fix: str | None) -> Owner | None:
    return _OWNER_OF_FIX.get(fix or "")


def result_owner(raw: dict[str, Any]) -> Owner | None:
    """A stored result's owner. Results stored before D-823 carry only `fix`."""
    owner = raw.get("owner")
    if owner in OWNERS:
        return cast(Owner, owner)
    return owner_of(raw.get("fix")) or _UNNAMED_OWNER.get(str(raw.get("verdict")))


#: What one try keeps besides the scenario: enough to read that try on its own.
_TRY_FIELDS: Final = (
    "verdict",
    "reason",
    "fix",
    "owner",
    "setting",
    "step_id",
    "limit",
    "conversation",
    "sounds",
    "judge",
)


def aggregate(tries: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """One test's tries as one result. The shown conversation, reason and owner are the
    first failing try's (the one to read and fix), else the first try's."""
    first = tries[0]
    verdicts = [str(t.get("verdict") or "unjudged") for t in tries]
    judged = [v for v in verdicts if v != "unjudged"]
    passes = sum(1 for v in judged if v == "passed")
    failing = [t for t in tries if t.get("verdict") in _FAILING]
    # A try that broke a platform rule decides who owns the test even when an earlier try
    # was put down to the script: a script edit cannot fix what the platform rule owns, and
    # the improver would otherwise rewrite the script to chase it.
    shown = next(
        (t for t in failing if result_owner(t) == "platform"),
        failing[0] if failing else first,
    )
    sounds: dict[str, dict[str, Any]] = {}
    for t in tries:
        for note in t.get("sounds") or []:
            kind = str(note.get("kind"))
            entry = sounds.setdefault(
                kind, {"kind": kind, "reason": note.get("reason"), "tries": 0}
            )
            entry["tries"] += 1
    words: list[str] = list(
        dict.fromkeys(str(w) for t in tries for w in t.get("formal_words") or [])
    )
    out: dict[str, Any] = {
        **{k: v for k, v in first.items() if k not in _TRY_FIELDS},
        **{k: shown.get(k) for k in _TRY_FIELDS if k in shown},
        "passes": passes,
        "judged_tries": len(judged),
        "tries": [{k: t.get(k) for k in _TRY_FIELDS if k in t} for t in tries],
        "sounds": list(sounds.values()),
        "formal_words": words,
    }
    if judged and passes == len(judged):
        out.update(verdict="passed", fix=None, owner=None, step_id=None)
    elif not judged:
        out["verdict"] = "unjudged"
    return out


def aggregate_run(tries: Sequence[Sequence[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Every test's tries, in the first try's order. A test missing from a later try (the
    owner marked it wrong part-way) is aggregated over the tries it has."""
    by_key: dict[str, list[dict[str, Any]]] = {}
    for one in tries:
        for result in one:
            by_key.setdefault(str(result.get("key")), []).append(result)
    return [aggregate(rows) for rows in by_key.values()]


def reliability(result: dict[str, Any]) -> Reliability:
    """Works every time, some of the time, never, or nobody could judge it."""
    if "judged_tries" not in result:
        verdict = str(result.get("verdict") or "unjudged")
        if verdict == "passed":
            return "passed"
        return "failed" if verdict in _FAILING else "unjudged"
    judged = int(result.get("judged_tries") or 0)
    passes = int(result.get("passes") or 0)
    if judged == 0:
        return "unjudged"
    if passes == judged:
        return "passed"
    return "failed" if passes == 0 else "flaky"


def reliably_failing(result: dict[str, Any]) -> bool:
    """Failed on most of its judged tries: the only failures worth an edit. A test that
    works on most tries and fails on one is noise to an improver, which would rewrite a
    working script to chase it."""
    rel = reliability(result)
    if rel == "failed":
        return True
    if rel != "flaky":
        return False
    return int(result.get("passes") or 0) * 2 < int(result.get("judged_tries") or 0)


def in_owner_score(result: dict[str, Any], wrong_keys: Iterable[str] = ()) -> bool:
    """Counted in the owner's score: a test their script or knowledge decides."""
    if str(result.get("key")) in set(wrong_keys) or result.get("probe"):
        return False
    rel = reliability(result)
    if rel == "unjudged":
        return False
    return rel == "passed" or result_owner(result) in OWNERS_SCRIPT


def standing(result: dict[str, Any], wrong_keys: Iterable[str] = ()) -> Standing:
    if str(result.get("key")) in set(wrong_keys):
        return "wrong"
    rel = reliability(result)
    owner = result_owner(result)
    if rel == "passed":
        return "works"
    if owner == "setting":
        return "setting"
    if rel == "unjudged":
        return "check"
    if owner not in OWNERS_SCRIPT:
        return "ours"
    return "broken" if rel == "failed" else "unreliable"


@dataclass(frozen=True, slots=True)
class OwnerScore:
    #: Tests in the owner's score that worked on every try.
    passed: int
    #: Tests in the owner's score.
    counted: int
    #: Of `counted`, working on some tries but not all.
    unreliable: int
    #: Tests outside the score because they are ours to fix.
    ours: int
    #: Tests nobody could judge, to read.
    check: int
    #: Tests a setting decides.
    setting: int


def owner_score(results: Sequence[dict[str, Any]], wrong_keys: Iterable[str] = ()) -> OwnerScore:
    wrong = set(wrong_keys)
    places = Counter(standing(r, wrong) for r in results)
    counted = [r for r in results if in_owner_score(r, wrong)]
    return OwnerScore(
        passed=sum(1 for r in counted if reliability(r) == "passed"),
        counted=len(counted),
        unreliable=places["unreliable"],
        ours=places["ours"],
        check=places["check"],
        setting=places["setting"],
    )


@dataclass(frozen=True, slots=True)
class Comparison:
    """Before against after, per test of the owner's score, on the same tests."""

    changes: dict[str, Change] = field(default_factory=dict)

    def keys(self, change: Change) -> list[str]:
        return [k for k, c in self.changes.items() if c == change]

    def count(self, change: Change) -> int:
        return len(self.keys(change))


def _channel(result: dict[str, Any]) -> str:
    """Where a result was produced; a result stored before D-847 is the test chat."""
    return str(result.get("channel") or "test_chat")


def compare(
    before: Sequence[dict[str, Any]],
    after: Sequence[dict[str, Any]],
    *,
    wrong_keys: Iterable[str] = (),
    before_wrong_keys: Iterable[str] = (),
) -> Comparison:
    """Each test of the owner's score in `after`, against the same test in `before`. A test
    with no counted result before (new to the set, or nobody could judge it then) is `new`
    and moves no headline, and so is a test asked in the chat before and in call mode now, or
    the other way round (D-847): a reply under the call prompt is a different measurement."""
    wrong = set(wrong_keys)
    then = {
        str(r.get("key")): r for r in before if in_owner_score(r, set(before_wrong_keys) | wrong)
    }
    changes: dict[str, Change] = {}
    for result in after:
        key = str(result.get("key"))
        if not in_owner_score(result, wrong):
            continue
        earlier = then.get(key)
        if earlier is None or _channel(earlier) != _channel(result):
            changes[key] = "new"
            continue
        was = reliability(earlier) == "passed"
        now = reliability(result) == "passed"
        changes[key] = ("same" if now else "broken") if was else ("fixed" if now else "still")
    return Comparison(changes=changes)


def sound_counts(
    results: Sequence[dict[str, Any]], wrong_keys: Iterable[str] = ()
) -> dict[str, int]:
    """How many tests sounded wrong in each way, on any try, most frequent first."""
    wrong = set(wrong_keys)
    counts: Counter[str] = Counter()
    for result in results:
        if str(result.get("key")) in wrong:
            continue
        counts.update({str(n.get("kind")) for n in result.get("sounds") or []})
    return dict(counts.most_common())


def worst_first(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = {"broken": 0, "unreliable": 1, "setting": 2, "ours": 3, "check": 4, "works": 5}
    return sorted(
        results,
        key=lambda r: (order.get(standing(r), 6), -_SEVERITY.get(str(r.get("verdict")), 1)),
    )


__all__ = [
    "OWNERS",
    "OWNERS_SCRIPT",
    "TRIALS",
    "Change",
    "Comparison",
    "Owner",
    "OwnerScore",
    "Reliability",
    "Standing",
    "aggregate",
    "aggregate_run",
    "compare",
    "in_owner_score",
    "owner_of",
    "owner_score",
    "reliability",
    "reliably_failing",
    "result_owner",
    "sound_counts",
    "standing",
    "worst_first",
]
