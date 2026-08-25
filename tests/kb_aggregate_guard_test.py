"""The aggregate must not be able to carry call content. This file is that claim.

The hazard is caller A's words reaching caller B on a live call, and the reason it needs
a test file of its own rather than a paragraph is that a leak here LOOKS LIKE A WORKING
FEATURE: an aggregate that quotes a caller reads as a richer aggregate. Nothing else in
the pipeline would report it.

So the tests below are written to fail when somebody WIDENS the aggregator, not only when
somebody breaks it. Three nets, in the order they would catch a change:

1. the admission door (`CallOutcome.admit`) — a model's free-text answer is dropped;
2. the wall (`patterns.assert_no_call_content`) — a batch naming an undeclared token is
   refused whole, however it was assembled;
3. the source inventory — the reader is asserted not to NAME the transcript columns, which
   catches a leak added to an existing query, where neither of the other two can see it.

The third is `tests/kb_tiers_test.py`'s technique, borrowed deliberately: a route or a
column that must never appear is checked by inventory rather than by behaviour, because
behaviour tests only cover the shapes somebody already imagined.
"""

from __future__ import annotations

import ast
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.kb import insights as insights_module
from apps.api.kb.patterns import (
    MIN_CALLS_PER_PATTERN,
    MIN_CALLS_PER_WINDOW,
    CallContentLeakError,
    CallOutcome,
    CallPattern,
    Vocabulary,
    answer_token,
    assert_no_call_content,
    assert_text_carries_no_call_content,
    distil,
    field_token,
    outcome_token,
)
from apps.workers import kb_aggregation, retention
from arq import Retry
from calevate_shared.extraction import ExtractionSchemaSpec
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[1]

#: A clinic's schema, as a client would type it into the console: one enum field naming
#: what the call was about, one required text field the agent is asked to capture.
SCHEMA = ExtractionSchemaSpec.model_validate(
    {
        "version": 3,
        "fields": [
            {
                "key": "reason_for_call",
                "label": "Reason for call",
                "type": "enum",
                "enum_values": ["appointment", "fees", "timings"],
            },
            {"key": "preferred_slot", "label": "Preferred slot", "type": "text", "required": True},
            {"key": "callback_number", "label": "Callback number", "type": "text"},
        ],
    }
)

#: What a caller actually said, in the shape an extractor hands it over. Every test that
#: needs "something that must never appear in an aggregate" uses these, so widening the
#: pipeline is caught by one edit rather than by remembering to add a case.
CALLER_WORDS = "my mother needs a root canal and we can only come after 6"
CALLER_NUMBER = "+919876543210"


def _vocabulary() -> Vocabulary:
    return Vocabulary.for_schema(SCHEMA)


# --- net 1: the admission door -------------------------------------------------------


def test_a_caller_utterance_never_becomes_a_token() -> None:
    """The extractor returned prose where the schema declared an enum. It is DROPPED.

    This is the single likeliest way call content enters an aggregate: an enum field whose
    model answer is not a declared member. `admit` tests membership rather than trusting
    the extractor, so what arrives is either a value the CLIENT typed into their schema or
    nothing at all.
    """
    vocabulary = _vocabulary()
    outcome = CallOutcome.admit(
        call_id=uuid7(),
        vocabulary=vocabulary,
        outcome_tag="resolved",
        sentiment="positive",
        extraction={
            "reason_for_call": CALLER_WORDS,
            "preferred_slot": "after 6pm on Thursday",
            "callback_number": CALLER_NUMBER,
        },
    )
    joined = " ".join(outcome.tokens)
    assert CALLER_WORDS not in joined
    assert CALLER_NUMBER not in joined
    assert "after 6pm" not in joined
    assert outcome.tokens == frozenset({outcome_token("resolved"), "sentiment:positive"})


def test_a_declared_enum_member_is_admitted_and_a_free_text_value_never_is() -> None:
    """The positive control for the test above — without it, "nothing gets through"
    would be satisfied by an admission door that admits nothing at all."""
    outcome = CallOutcome.admit(
        call_id=uuid7(),
        vocabulary=_vocabulary(),
        outcome_tag=None,
        sentiment=None,
        extraction={"reason_for_call": "fees", "preferred_slot": "any time tomorrow"},
    )
    assert answer_token("reason_for_call", "fees") in outcome.tokens
    assert not any("tomorrow" in token for token in outcome.tokens)


def test_a_required_field_the_agent_missed_is_counted_and_its_value_never_is() -> None:
    """The knowledge-gap signal: that the field came back EMPTY is publishable, because
    emptiness is not something a caller said."""
    missed = CallOutcome.admit(
        call_id=uuid7(),
        vocabulary=_vocabulary(),
        outcome_tag=None,
        sentiment=None,
        extraction={"preferred_slot": "   "},
    )
    assert field_token("preferred_slot") in missed.tokens

    captured = CallOutcome.admit(
        call_id=uuid7(),
        vocabulary=_vocabulary(),
        outcome_tag=None,
        sentiment=None,
        extraction={"preferred_slot": "Thursday 6pm"},
    )
    assert field_token("preferred_slot") not in captured.tokens
    assert not any("Thursday" in token for token in captured.tokens)


def test_a_captured_no_is_not_a_miss() -> None:
    """`False` and `0` are answers. Counting them as misses reports a working agent as
    a broken one, which is the failure mode that makes a gap report ignorable."""
    for value in (False, 0):
        outcome = CallOutcome.admit(
            call_id=uuid7(),
            vocabulary=_vocabulary(),
            outcome_tag=None,
            sentiment=None,
            extraction={"preferred_slot": value},
        )
        assert field_token("preferred_slot") not in outcome.tokens


def test_an_enum_member_cannot_collide_with_our_own_outcome_vocabulary() -> None:
    """A client is free to name an enum member `resolved`. Namespacing is what stops its
    count being added to `calls.outcome_tag`'s — two populations, one number."""
    spec = ExtractionSchemaSpec.model_validate(
        {
            "version": 1,
            "fields": [
                {
                    "key": "state",
                    "label": "State",
                    "type": "enum",
                    "enum_values": ["resolved", "open"],
                }
            ],
        }
    )
    vocabulary = Vocabulary.for_schema(spec)
    assert answer_token("state", "resolved") != outcome_token("resolved")
    assert {answer_token("state", "resolved"), outcome_token("resolved")} <= vocabulary.tokens


# --- net 2: the wall -----------------------------------------------------------------


def test_the_wall_refuses_a_pattern_naming_an_undeclared_token() -> None:
    """THE TEST THE WHOLE LANE IS FOR. A future aggregator assembles patterns some other
    way and puts a caller's sentence in one. The wall refuses the batch.

    Written against a hand-built `CallPattern` precisely BECAUSE no current code path can
    produce one: the point is to fail on the widening that has not been written yet.

    THE TOKEN IS NAMESPACED, and that detail is load-bearing. A bare sentence would also
    fail the KIND check below it — so this test passed a first sabotage run with the
    vocabulary check deleted, on the strength of a different check catching it. The token
    here is exactly what a widened admission door produces: `answer:{field}:{whatever the
    model said}`, which is in the right namespace for its kind and is refused only because
    the vocabulary does not declare it.
    """
    hostile = CallPattern(
        kind="asked_about",
        token=answer_token("reason_for_call", CALLER_WORDS),
        calls=9,
        of_calls=40,
    )
    with pytest.raises(CallContentLeakError):
        assert_no_call_content([hostile], vocabulary=_vocabulary())


def test_the_refusal_does_not_quote_what_it_refused() -> None:
    """An exception message reaches logs and traces. Quoting the token would write caller
    speech into both (hard rule 6) — the counts locate the defect instead."""
    hostile = CallPattern(
        kind="asked_about",
        token=answer_token("reason_for_call", CALLER_WORDS),
        calls=9,
        of_calls=40,
    )
    with pytest.raises(CallContentLeakError) as caught:
        assert_no_call_content([hostile], vocabulary=_vocabulary())
    message = str(caught.value)
    assert CALLER_WORDS not in message
    assert "root canal" not in message


def test_the_wall_refuses_a_kind_that_does_not_match_its_token() -> None:
    """`kind` selects the wording AND the arithmetic. A mismatch is a count taken over
    one population and rendered as another."""
    mislabelled = CallPattern(
        kind="not_captured", token=outcome_token("resolved"), calls=9, of_calls=40
    )
    with pytest.raises(CallContentLeakError):
        assert_no_call_content([mislabelled], vocabulary=_vocabulary())


def test_the_wall_refuses_a_count_larger_than_its_window() -> None:
    impossible = CallPattern(kind="outcome", token=outcome_token("resolved"), calls=41, of_calls=40)
    with pytest.raises(CallContentLeakError):
        assert_no_call_content([impossible], vocabulary=_vocabulary())


def test_a_rendered_line_carrying_a_phone_number_is_refused() -> None:
    """The render is the last cheap place to catch a leak. It sees digit runs and says so
    (`patterns._DIGIT_RUN` documents what it cannot see)."""
    with pytest.raises(CallContentLeakError):
        assert_text_carries_no_call_content(f"Call back on {CALLER_NUMBER}")


def test_a_rendered_line_carrying_ordinary_counts_is_allowed() -> None:
    """The negative control: a guard that refused counts would refuse every digest, and
    would be turned off by the next person rather than fixed."""
    assert_text_carries_no_call_content("Preferred slot — missing on 41 of 1204 calls")


def test_a_clients_own_label_may_carry_digits() -> None:
    """The second negative control, and it is not hypothetical: a client is entitled to
    name a field "PIN code 500081". Their own wording is elided before the check, because
    this guard pages an operator and stops the whole sweep — an alarm that fires on
    ordinary configuration is one that gets muted rather than fixed."""
    assert_text_carries_no_call_content(
        "PIN code 500081 — missing on 41 of 120 calls", declared=["PIN code 500081"]
    )
    with pytest.raises(CallContentLeakError):
        # ...and eliding the label does not excuse a number beside it.
        assert_text_carries_no_call_content(
            f"PIN code 500081 — call back on {CALLER_NUMBER}", declared=["PIN code 500081"]
        )


def test_the_render_does_not_return_a_body_the_guard_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard must be CALLED, not merely present. A first sabotage run deleted the call
    from `render_digest` and every test in this file still passed — the guard was tested,
    the wiring was not, and an unwired guard is the most reassuring kind of nothing.
    """
    vocabulary = _vocabulary()
    insights = insights_module.AgentInsights(
        agent_id=uuid7(),
        calls=40,
        calls_with_details=40,
        patterns=[
            CallPattern(
                kind="asked_about",
                token=answer_token("reason_for_call", "fees"),
                calls=9,
                of_calls=40,
            )
        ],
        vocabulary=vocabulary,
    )
    assert insights_module.render_digest(insights, agent_name="Reception") is not None

    def _refuse(body: str, *, declared: Any = ()) -> None:
        raise CallContentLeakError("refused by the test")

    monkeypatch.setattr(insights_module, "assert_text_carries_no_call_content", _refuse)
    with pytest.raises(CallContentLeakError):
        insights_module.render_digest(insights, agent_name="Reception")


# --- the k-anonymity floors ----------------------------------------------------------


def _outcomes(count: int, tokens: frozenset[str]) -> list[CallOutcome]:
    return [CallOutcome(call_id=uuid7(), tokens=tokens) for _ in range(count)]


def test_the_privacy_floors_are_not_lowered_without_a_decision() -> None:
    """The VALUES, pinned. The two tests below prove the MECHANISM at whatever k is set
    to, and a first sabotage run showed why that is not enough: they derive their input
    from the constant (`MIN_CALLS_PER_PATTERN - 1`), so setting k to 1 makes them pass
    trivially while every pattern in the system becomes publishable at n=1.

    A k-anonymity floor is a privacy control, not a tuning knob. Lowering either number is
    a decision about what a business owner may learn about individual callers, and it
    should cost a failing test and a decision-log entry rather than a one-character diff.
    """
    assert MIN_CALLS_PER_PATTERN >= 5, (
        "k was lowered. At k=3 an owner who recognises two of three callers learns the "
        "third's answer by subtraction — see apps/api/kb/patterns.py"
    )
    assert MIN_CALLS_PER_WINDOW >= 20, (
        "the floor on the DENOMINATOR was lowered. Without it a six-call week can publish "
        "a pattern covering five of them: k is satisfied and most of one week's callers "
        "are described"
    )


def test_a_pattern_below_k_is_not_published() -> None:
    """A pattern describing k-1 calls is those calls, relabelled."""
    vocabulary = _vocabulary()
    rare = answer_token("reason_for_call", "timings")
    common = answer_token("reason_for_call", "appointment")
    outcomes = _outcomes(MIN_CALLS_PER_PATTERN - 1, frozenset({rare})) + _outcomes(
        MIN_CALLS_PER_WINDOW, frozenset({common})
    )

    published = {p.token for p in distil(outcomes, vocabulary=vocabulary)}
    assert common in published
    assert rare not in published


def test_a_window_below_the_floor_publishes_nothing() -> None:
    """The floor on the DENOMINATOR. Without it a six-call week could publish a pattern
    covering five of them — technically k=5, and a description of most of one week."""
    vocabulary = _vocabulary()
    token = answer_token("reason_for_call", "fees")
    outcomes = _outcomes(MIN_CALLS_PER_WINDOW - 1, frozenset({token}))
    assert distil(outcomes, vocabulary=vocabulary) == []


def test_the_same_call_counted_twice_does_not_clear_the_floor() -> None:
    """k is a floor on DISTINCT CALLS, not on rows. A join that fanned out would
    otherwise let one call reach the threshold on its own."""
    vocabulary = _vocabulary()
    token = answer_token("reason_for_call", "fees")
    one_call = uuid7()
    duplicated = [CallOutcome(call_id=one_call, tokens=frozenset({token}))] * 40
    padding = _outcomes(MIN_CALLS_PER_WINDOW, frozenset({outcome_token("resolved")}))
    published = {p.token for p in distil(duplicated + padding, vocabulary=vocabulary)}
    assert token not in published


def test_a_fanned_out_window_does_not_clear_the_denominator_floor() -> None:
    """THE DENOMINATOR FLOOR COUNTS DISTINCT CALLS TOO. Measured before it did:

        rows = 24  distinct calls = 6  MIN_CALLS_PER_WINDOW = 20
          PUBLISHED: asked_about answer:reason_for_call:fees 6/6

    Six real calls arriving as four rows each cleared a window floor of twenty, and a
    token on all six then cleared k=5 — publishing a pattern that describes EVERY caller
    of a six-call week. That is verbatim the disclosure `MIN_CALLS_PER_WINDOW`'s own
    comment exists to prevent, and the k floor cannot see it because six IS above five.

    `test_the_same_call_counted_twice_does_not_clear_the_floor` above is this test's twin
    on the NUMERATOR. Both are needed: they fail to different edits.
    """
    vocabulary = _vocabulary()
    token = answer_token("reason_for_call", "fees")
    ids = [uuid7() for _ in range(MIN_CALLS_PER_PATTERN + 1)]
    rows_per_call = -(-MIN_CALLS_PER_WINDOW // len(ids)) + 1
    fanned = [
        CallOutcome(call_id=call_id, tokens=frozenset({token}))
        for call_id in ids
        for _ in range(rows_per_call)
    ]
    assert len(fanned) >= MIN_CALLS_PER_WINDOW, "the fan-out must clear a ROW-counting floor"
    assert len(ids) < MIN_CALLS_PER_WINDOW, "...while the real week stays under it"
    assert distil(fanned, vocabulary=vocabulary) == [], (
        "a week of six calls published a pattern describing all six. The window floor is "
        "counting rows, so any fan-out — a join, a re-extraction, a second caller of "
        "`distil` — buys a publication the floor was built to refuse"
    )


def test_the_header_count_and_the_line_counts_are_one_number() -> None:
    """`AgentInsights.calls` is the digest's header ("Across N completed calls") and
    `CallPattern.of_calls` is the denominator of every line under it. When no extraction
    in the window has been scrubbed the two populations coincide, and then they must BE
    one number — `CallPattern`'s docstring argues exactly this for carrying the
    denominator, and the argument only holds if the header shares it. (When they do NOT
    coincide the digest says so in words; that is
    `test_a_scrubbed_extraction_is_not_counted_as_a_missed_field` below.)"""
    vocabulary = _vocabulary()
    token = answer_token("reason_for_call", "fees")
    outcomes = _outcomes(MIN_CALLS_PER_WINDOW + 3, frozenset({token}))
    insights = insights_module.AgentInsights(
        agent_id=uuid7(),
        calls=len({o.call_id for o in outcomes}),
        calls_with_details=len({o.call_id for o in outcomes if o.extraction_readable}),
        patterns=distil(outcomes, vocabulary=vocabulary),
        vocabulary=vocabulary,
    )
    body = insights_module.render_digest(insights, agent_name="Reception")
    assert body is not None
    for pattern in insights.patterns:
        assert pattern.of_calls == insights.calls
        assert f"{pattern.calls} of {pattern.of_calls} calls" in body
    assert f"Across {insights.calls} completed calls" in body


def test_the_order_is_total_so_two_runs_agree() -> None:
    """A digest that has not changed must not LOOK changed. Ties broken on the token."""
    vocabulary = _vocabulary()
    outcomes = _outcomes(
        MIN_CALLS_PER_WINDOW,
        frozenset({outcome_token("resolved"), answer_token("reason_for_call", "fees")}),
    )
    first = distil(outcomes, vocabulary=vocabulary)
    second = distil(list(reversed(outcomes)), vocabulary=vocabulary)
    assert [(p.token, p.calls) for p in first] == [(p.token, p.calls) for p in second]


# --- net 3: the source inventory -----------------------------------------------------

#: Columns and tables that hold what a caller said, or who they are. The aggregate reader
#: must not NAME any of them — a leak added to an existing SELECT changes no route, drops
#: through no door and is refused by no wall, because by the time it is a token it is
#: already inside the vocabulary check's blind spot only if somebody also widened the
#: vocabulary. This is the net for the change that does both.
FORBIDDEN_SOURCES = (
    "transcript_turns",
    "text_redacted",
    "summary",
    "from_e164",
    "to_e164",
    "moments",
)

#: `erased_subject_ref` is on the same list for the same reason — it NAMES A SUBJECT, and
#: a token carrying it would be a handle for one person riding an aggregate. But it is
#: also the only marker that says "this call belongs to somebody who was erased", and the
#: reader has to exclude those (`apps/api/kb/insights.py`'s module docstring measures what
#: counting them does). So the column is not forbidden outright: it is allowed in EXACTLY
#: one spelling, an `IS NULL` in a WHERE clause, and the test below asserts that every
#: occurrence of the identifier is part of one. `SELECT c.erased_subject_ref`,
#: `erased_subject_ref = :ref` and `erased_subject_ref IS NOT NULL` all still fail.
EXCLUSION_ONLY_SOURCE = "erased_subject_ref"
EXCLUSION_ONLY_SPELLING = "c.erased_subject_ref IS NULL"

#: Where that one spelling is allowed. Everywhere else the identifier is forbidden
#: outright — `patterns.py` holds no SQL at all and the worker reads no call rows.
EXCLUSION_READER = "insights.py"


def _executable_source(path: Path) -> str:
    """The module with its prose removed — comments and docstrings gone, every SQL string
    and every identifier kept.

    A plain substring scan of the FILE is what this test started as, and it failed on
    these very modules: they are required to EXPLAIN that they must not read `summary`,
    and a scan that cannot tell an explanation from a SELECT makes writing the explanation
    a test failure. That trains people to delete the explanation, which is the opposite of
    what the scan is for. `ast.unparse` drops comments; the docstring strip below drops the
    rest, and what is left is only what can run.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def test_the_aggregate_reader_never_names_a_transcript_column() -> None:
    """`calls.summary` is the near miss: it is a per-call AI summary sitting in the same
    row the reader already selects from, and it is exactly what somebody adding "top
    questions" would reach for. It is transcript-derived, so it is on the list."""
    for module in (
        REPO_ROOT / "apps" / "api" / "kb" / "patterns.py",
        REPO_ROOT / "apps" / "api" / "kb" / "insights.py",
        REPO_ROOT / "apps" / "workers" / "kb_aggregation.py",
    ):
        source = _executable_source(module)
        for token in FORBIDDEN_SOURCES:
            assert token not in source, (
                f"{module.name} names {token!r} in code: the weekly aggregate is counts "
                "over our closed enums and the client's own extraction schema, and nothing "
                "else. If this is a deliberate widening it needs the argument in "
                "apps/api/kb/patterns.py answered first."
            )
        mentions = source.count(EXCLUSION_ONLY_SOURCE)
        if module.name != EXCLUSION_READER:
            assert mentions == 0, (
                f"{module.name} names {EXCLUSION_ONLY_SOURCE!r} in code. Only the reader "
                "excludes erased calls; nothing else in this lane has any business "
                "naming a subject handle."
            )
            continue
        assert source.count(EXCLUSION_ONLY_SPELLING) == mentions, (
            f"{module.name} names {EXCLUSION_ONLY_SOURCE!r} outside the one allowed "
            f"spelling {EXCLUSION_ONLY_SPELLING!r}. The column is a handle for ONE PERSON: "
            "it may be tested for NULL to keep an erased caller out of the window, and it "
            "may never be selected, compared to a value, or carried into a token."
        )


def test_the_reader_excludes_erased_callers_in_sql() -> None:
    """The exclusion is IN THE STATEMENT, not in a comprehension a later edit can reorder.

    Paired with `test_an_erased_callers_calls_leave_the_aggregate` below, which proves the
    behaviour against real rows. This one exists because the behavioural test needs a
    tenant, an agent, a schema and twenty-five calls to say what one substring says, and a
    reader that lost the predicate should fail in under a millisecond.
    """
    assert EXCLUSION_ONLY_SPELLING in insights_module._OUTCOMES_SQL, (
        "the aggregate reader no longer excludes erased callers. A DPDP erasure leaves "
        "the `calls` row in place — see apps/api/kb/insights.py for the three separate "
        "wrongs that counting it does."
    )


# --- the reader, against real rows ---------------------------------------------------

#: How far back `_agent_with_calls` dates the calls it seeds. Named once because the sweep
#: tests must fire a week AFTER these calls, not a week after "now" — see
#: `_sweep_fired_after_calls_week`.
_CALLS_ENDED_DAYS_AGO = 2


def _sweep_fired_after_calls_week() -> datetime:
    """The instant to fire `_sweep` at so the week it summarises is the one holding the
    calls `_agent_with_calls` seeds (`now - _CALLS_ENDED_DAYS_AGO` days).

    `_sweep` summarises the IST week that CLOSED before its firing instant (`closed_week`),
    so it must fire a week after the CALLS, not a week after `now`. Firing at `now + 7d`
    puts the window a fixed nine days past the calls, and nine days is more than a week:
    whenever the suite runs within two days of a Monday-00:00-IST boundary, `now + 7d`'s
    closed week is the one AFTER the calls' week and the calls fall outside it, so the sweep
    distils nothing and mails no one. That made these end-to-end tests fail on IST Monday
    and Tuesday and pass the rest of the week. Anchoring the firing instant to the calls'
    own age keeps the window on the calls' week for every weekday and time of day.
    """
    return datetime.now(UTC) - timedelta(days=_CALLS_ENDED_DAYS_AGO) + timedelta(days=7)


async def _agent_with_calls(
    *,
    outcomes: list[dict[str, Any]],
    schema: ExtractionSchemaSpec = SCHEMA,
    tenant_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant, a live agent with a published extraction schema, and its calls.

    Built with raw INSERTs rather than through `admin.service.create_organization`
    deliberately: this suite is about what the aggregate READS, and routing it through the
    onboarding path would couple it to every default that path happens to set.

    `tenant_id` reuses an existing tenant instead of minting one. That is what makes the
    per-agent isolation test real: two agents in DIFFERENT tenants are separated by RLS
    before any code of ours runs, so a test built that way proves nothing about the
    `agent_id` predicate it claims to be about.
    """
    new_tenant = tenant_id is None
    tenant_id = tenant_id or uuid7()
    agent_id, schema_id = uuid7(), uuid7()
    slug = f"agg-{uuid.uuid4().hex[:10]}"
    async with tenant_session(tenant_id) as session:
        if new_tenant:
            await session.execute(
                text(
                    "INSERT INTO organizations (id, name, slug, status, billing_email, "
                    "created_at, updated_at) VALUES (:id, 'Aggregate Clinic', :slug, "
                    "'active', 'owner@example.test', now(), now())"
                ),
                {"id": tenant_id, "slug": slug},
            )
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, "
                "ai_disclosure_line, recording_notice_line, status, engine, engine_agent_ref, "
                "created_at, updated_at) VALUES (:id, :tid, 'Reception', 'inbound', "
                "'Idi AI assistant.', 'Idi AI assistant.', 'This call is being recorded.', "
                "'live', 'fake', :ref, now(), now())"
            ),
            {"id": agent_id, "tid": tenant_id, "ref": slug},
        )
        await session.execute(
            text(
                "INSERT INTO extraction_schemas (id, tenant_id, agent_id, version, fields, "
                "published_at, created_at, updated_at) VALUES (:id, :tid, :aid, :v, "
                "CAST(:fields AS jsonb), now(), now(), now())"
            ),
            {
                "id": schema_id,
                "tid": tenant_id,
                "aid": agent_id,
                "v": schema.version,
                "fields": schema.model_dump_json(include={"fields"}).split('"fields":', 1)[1][:-1],
            },
        )
        await session.execute(
            text("UPDATE agents SET extraction_schema_id = :sid WHERE id = :aid"),
            {"sid": schema_id, "aid": agent_id},
        )
        ended = datetime.now(UTC) - timedelta(days=_CALLS_ENDED_DAYS_AGO)
        for index, spec in enumerate(outcomes):
            call_id = uuid7()
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "status, ended_at, outcome_tag, sentiment, summary, to_e164, created_at, "
                    "updated_at) VALUES (:id, :tid, :aid, :ec, 'inbound', 'completed', :end, "
                    ":tag, :sent, :summary, :to, now(), now())"
                ),
                {
                    "id": call_id,
                    "tid": tenant_id,
                    "aid": agent_id,
                    "ec": f"{slug}-{index}",
                    "end": ended,
                    "tag": spec.get("outcome_tag"),
                    "sent": spec.get("sentiment"),
                    # Present on the row and never readable through the aggregate.
                    "summary": CALLER_WORDS,
                    "to": CALLER_NUMBER,
                },
            )
            if "data" in spec:
                await session.execute(
                    text(
                        "INSERT INTO call_extractions (id, tenant_id, call_id, schema_version, "
                        "data, created_at, updated_at) VALUES (:id, :tid, :cid, :v, "
                        "CAST(:data AS jsonb), now(), now())"
                    ),
                    {
                        "id": uuid7(),
                        "tid": tenant_id,
                        "cid": call_id,
                        "v": schema.version,
                        "data": spec["data"],
                    },
                )
    return tenant_id, agent_id


async def test_the_reader_publishes_counts_and_no_caller_content() -> None:
    """End to end over real rows whose `summary` and `to_e164` hold a caller's words and
    number. Neither reaches the patterns, and neither reaches the digest."""
    calls = [
        {
            "outcome_tag": "needs_follow_up",
            "sentiment": "neutral",
            "data": '{"reason_for_call": "appointment"}',
        }
        for _ in range(MIN_CALLS_PER_WINDOW + 5)
    ]
    tenant_id, agent_id = await _agent_with_calls(outcomes=calls)

    async with tenant_session(tenant_id) as session:
        result = await insights_module.insights_for_agent(
            session,
            agent_id=agent_id,
            since=datetime.now(UTC) - timedelta(days=7),
            until=datetime.now(UTC),
        )
    assert result is not None
    tokens = {p.token for p in result.patterns}
    assert answer_token("reason_for_call", "appointment") in tokens
    assert field_token("preferred_slot") in tokens, "the required field was never captured"
    assert outcome_token("needs_follow_up") in tokens

    body = insights_module.render_digest(result, agent_name="Reception")
    assert body is not None
    assert CALLER_WORDS not in body
    assert CALLER_NUMBER not in body
    assert "Reason for call: appointment" in body, "the CLIENT's own label is what renders"


async def test_one_agents_calls_never_reach_another_agents_aggregate() -> None:
    """Per-agent isolation, asserted rather than assumed. TWO LIVE AGENTS IN ONE TENANT —
    RLS cannot separate them, so the `agent_id` predicate is the whole boundary and it is
    worth a test that fails if somebody drops it.

    A tenant with a reception agent and a collections agent is the ordinary case, not a
    contrived one, and their callers ask about different things. Each digest must describe
    its own agent's callers.
    """
    reception = [
        {"outcome_tag": "resolved", "data": '{"reason_for_call": "fees"}'}
        for _ in range(MIN_CALLS_PER_WINDOW + 2)
    ]
    collections = [
        {"outcome_tag": "needs_follow_up", "data": '{"reason_for_call": "timings"}'}
        for _ in range(MIN_CALLS_PER_WINDOW + 2)
    ]
    tenant_id, first_agent = await _agent_with_calls(outcomes=reception)
    _, second_agent = await _agent_with_calls(outcomes=collections, tenant_id=tenant_id)

    window = {"since": datetime.now(UTC) - timedelta(days=7), "until": datetime.now(UTC)}
    async with tenant_session(tenant_id) as session:
        mine = await insights_module.insights_for_agent(session, agent_id=first_agent, **window)
        theirs = await insights_module.insights_for_agent(session, agent_id=second_agent, **window)
    assert mine is not None and theirs is not None
    assert mine.calls == len(reception), "another agent's calls entered the denominator"
    assert theirs.calls == len(collections)

    mine_tokens = {p.token for p in mine.patterns}
    theirs_tokens = {p.token for p in theirs.patterns}
    assert answer_token("reason_for_call", "fees") in mine_tokens
    assert answer_token("reason_for_call", "timings") not in mine_tokens
    assert answer_token("reason_for_call", "timings") in theirs_tokens
    assert answer_token("reason_for_call", "fees") not in theirs_tokens


async def test_a_call_outside_the_window_is_not_counted() -> None:
    calls = [{"outcome_tag": "resolved"} for _ in range(MIN_CALLS_PER_WINDOW + 2)]
    tenant_id, agent_id = await _agent_with_calls(outcomes=calls)
    async with tenant_session(tenant_id) as session:
        result = await insights_module.insights_for_agent(
            session,
            agent_id=agent_id,
            since=datetime.now(UTC) - timedelta(days=1),
            until=datetime.now(UTC),
        )
    assert result is not None
    assert result.calls == 0
    assert result.patterns == []


async def test_an_agent_with_no_extraction_schema_has_nothing_to_say() -> None:
    """None, not an empty digest: an agent with no client-authored vocabulary can only
    produce outcome counts with nothing to attach them to."""
    tenant_id = uuid7()
    agent_id = uuid7()
    slug = f"agg-{uuid.uuid4().hex[:10]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, created_at, updated_at) "
                "VALUES (:id, 'No Schema', :slug, 'active', now(), now())"
            ),
            {"id": tenant_id, "slug": slug},
        )
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, "
                "ai_disclosure_line, recording_notice_line, status, engine, created_at, "
                "updated_at) VALUES (:id, :tid, 'Bare', 'inbound', 'Idi AI assistant.', "
                "'Idi AI assistant.', 'This call is being recorded.', 'live', 'fake', "
                "now(), now())"
            ),
            {"id": agent_id, "tid": tenant_id},
        )
        result = await insights_module.insights_for_agent(
            session,
            agent_id=agent_id,
            since=datetime.now(UTC) - timedelta(days=7),
            until=datetime.now(UTC),
        )
    assert result is None


# --- the whole path, driven with a real extractor's output ---------------------------

#: EVERY field type the console offers, on one schema. The tests above use a two-field
#: clinic schema, which leaves four of the five `FieldType` members untested — and
#: `number` and `date` are the two whose values are the most obviously personal (an amount
#: owed, an appointment time) while looking the least like "text" to somebody widening
#: `CallOutcome.admit`. A door that grew an arm for "scalar values are safe to count"
#: would pass every other test in this file.
EVERY_TYPE_SCHEMA = ExtractionSchemaSpec.model_validate(
    {
        "version": 1,
        "fields": [
            {
                "key": "reason_for_call",
                "label": "Reason for call",
                "type": "enum",
                "enum_values": ["appointment", "billing", "complaint"],
                "required": True,
            },
            {"key": "caller_name", "label": "Caller name", "type": "text", "required": True},
            {"key": "address", "label": "Address", "type": "text", "required": True},
            {"key": "in_their_words", "label": "In their words", "type": "text"},
            {"key": "callback_number", "label": "Callback number", "type": "text"},
            {"key": "amount_due", "label": "Amount due", "type": "number"},
            {"key": "visit_date", "label": "Visit date", "type": "date", "required": True},
            {"key": "is_existing", "label": "Existing patient", "type": "bool"},
        ],
    }
)

#: What the extractor actually hands over after a real call, for every one of those
#: fields: a name, an address, a sentence in the caller's own words, their number, an
#: amount and a date. Only `reason_for_call` is a member of anything the client declared;
#: every other value here is something a person said out loud on a phone call.
TRANSCRIPT_DERIVED_ANSWERS: dict[str, Any] = {
    "reason_for_call": "complaint",
    "caller_name": "Lakshmi Venkataramanan",
    "address": "Plot 12 Kavuri Hills Madhapur Hyderabad 500081",
    "in_their_words": "naa thalli ki root canal kavali, saayantram tarvatha maatrame ravagalam",
    "callback_number": "+919876543210",
    "amount_due": 43750,
    "visit_date": "2026-09-14",
    "is_existing": True,
}


def _caller_words() -> frozenset[str]:
    """Every word a CALLER contributed, minus every word the CLIENT already owns.

    The subtraction is what keeps this honest in both directions. A client's own label
    ("Reason for call") and their own enum member ("complaint") are their wording and are
    published on purpose, so a word that appears in one is not evidence of a leak — and
    leaving it in would make this test fail on a correct digest, which is how a privacy
    assertion gets deleted. What is left is only what a person said.
    """
    declared = {
        word
        for field in EVERY_TYPE_SCHEMA.fields
        for source in [field.key, field.label, *(field.enum_values or [])]
        for word in re.split(r"[^0-9a-z]+", source.lower())
    }
    spoken = {
        word
        for key, value in TRANSCRIPT_DERIVED_ANSWERS.items()
        if key != "reason_for_call"
        for word in re.split(r"[^0-9a-z]+", str(value).lower())
        if len(word) >= 4
    }
    return frozenset(spoken - declared)


async def test_a_real_extractions_every_field_reaches_nothing_the_owner_can_read() -> None:
    """THE END-TO-END CLAIM, stated as an inventory rather than as three spot checks.

    Twenty-five calls whose extraction holds a name, an address, a sentence, a phone
    number, an amount and a date — the output of one real extraction pass, on a schema
    using every field type — go through the real reader, the real door, the real wall and
    the real render. Then EVERY WORD any caller contributed is asserted absent from the
    tokens and from the rendered digest.

    Spot-checking two known strings (`CALLER_WORDS`, `CALLER_NUMBER`) is what the other
    end-to-end test does and it is not enough on its own: it proves the two shapes
    somebody already thought of do not survive. This proves that NOTHING does, so widening
    the door to admit `number` or `date` values — the arm a reader is likeliest to think
    harmless, since neither is prose — fails here rather than in a digest.
    """
    forbidden = _caller_words()
    assert len(forbidden) >= 12, "the inventory went vacuous; it is proving nothing"

    calls = [
        {
            "outcome_tag": "needs_follow_up",
            "sentiment": "negative",
            "data": json.dumps(TRANSCRIPT_DERIVED_ANSWERS),
        }
        for _ in range(MIN_CALLS_PER_WINDOW + 5)
    ]
    tenant_id, agent_id = await _agent_with_calls(outcomes=calls, schema=EVERY_TYPE_SCHEMA)
    async with tenant_session(tenant_id) as session:
        result = await insights_module.insights_for_agent(
            session,
            agent_id=agent_id,
            since=datetime.now(UTC) - timedelta(days=7),
            until=datetime.now(UTC),
        )
    assert result is not None
    assert result.calls == len(calls)

    tokens = " ".join(p.token for p in result.patterns).lower()
    body = insights_module.render_digest(result, agent_name="Reception")
    assert body is not None
    for word in sorted(forbidden):
        assert word not in tokens, f"{word!r} — a caller's word — became part of a token"
        assert word.lower() not in body.lower(), f"{word!r} — a caller's word — reached the digest"

    # The positive control. Without it "nothing got through" is satisfied by a pipeline
    # that produced nothing at all, and every assertion above passes on an empty digest.
    assert answer_token("reason_for_call", "complaint") in {p.token for p in result.patterns}
    assert "Reason for call: complaint" in body


def test_the_wall_refuses_that_same_extraction_when_the_door_is_widened() -> None:
    """The same payload, against the WALL alone — which is what protects the pipeline
    somebody writes next year rather than the one running today.

    `CallOutcome` is constructed directly, so this is exactly the batch a widened
    admission door produces: the caller's sentence, in the right namespace for its kind,
    on enough distinct calls to clear both floors. Every check in
    `assert_no_call_content` except the vocabulary one passes it. Delete that check and
    this test is the one that goes red.
    """
    vocabulary = Vocabulary.for_schema(EVERY_TYPE_SCHEMA)
    spoken = str(TRANSCRIPT_DERIVED_ANSWERS["in_their_words"])
    widened = [
        CallOutcome(call_id=uuid7(), tokens=frozenset({answer_token("in_their_words", spoken)}))
        for _ in range(MIN_CALLS_PER_WINDOW)
    ]
    with pytest.raises(CallContentLeakError):
        distil(widened, vocabulary=vocabulary)


async def test_a_fanned_out_read_still_reports_one_call_per_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reader's own counting, driven through a real fan-out.

    `AgentInsights.calls` is the digest's header and `CallPattern.of_calls` is the
    denominator of every line under it; they describe one population and must BE one
    number. `call_extractions` is UNIQUE on `(tenant_id, call_id)` so today's statement
    cannot return two rows for one call — which is exactly why counting rows LOOKS
    correct here and would keep looking correct until somebody joins a table that can
    (`transcript_turns`, `lead_events`, a re-extraction history). The statement is
    swapped for one that fans out on purpose, which is the only way to make the reader
    answer the question rather than the schema.
    """
    fanned_sql = insights_module._OUTCOMES_SQL.replace(
        "LEFT JOIN call_extractions e ON e.call_id = c.id",
        "LEFT JOIN call_extractions e ON e.call_id = c.id CROSS JOIN generate_series(1, 3)",
    )
    assert "generate_series" in fanned_sql, "the reader's JOIN clause moved; re-point this test"

    calls = [
        {"outcome_tag": "resolved", "sentiment": "positive", "data": '{"reason_for_call": "fees"}'}
        for _ in range(MIN_CALLS_PER_WINDOW + 5)
    ]
    tenant_id, agent_id = await _agent_with_calls(outcomes=calls)
    monkeypatch.setattr(insights_module, "_OUTCOMES_SQL", fanned_sql)
    async with tenant_session(tenant_id) as session:
        result = await insights_module.insights_for_agent(
            session,
            agent_id=agent_id,
            since=datetime.now(UTC) - timedelta(days=7),
            until=datetime.now(UTC),
        )
    assert result is not None
    assert result.calls == len(calls), (
        f"the reader reported {result.calls} calls for a week that had {len(calls)} — it is "
        "counting ROWS, so the digest header and every denominator under it describe "
        "different populations the moment anything fans out"
    )
    body = insights_module.render_digest(result, agent_name="Reception")
    assert body is not None
    assert f"Across {len(calls)} completed calls" in body
    for pattern in result.patterns:
        assert pattern.of_calls == result.calls
        assert pattern.calls <= pattern.of_calls


# --- erasure: k-anonymity is a property of what is PUBLISHED -------------------------


async def _erase_subject(tenant_id: uuid.UUID, call_ids: list[uuid.UUID]) -> None:
    """Leave the row shape a DPDP subject erasure leaves behind.

    These are the statements `workers/retention.py` issues against `calls` and
    `call_extractions` when it executes a deletion request, reproduced rather than
    invoked: the real entry point needs a deletion request row, a consent record, an
    object store and a proof certificate, and none of those is what this test is about.
    What it IS about is that the call row SURVIVES an erasure — numbers and summary
    NULLed, `erased_subject_ref` stamped, extraction emptied, `outcome_tag` and
    `sentiment` untouched — and that is exactly what these two statements produce.
    """
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET from_e164 = NULL, to_e164 = NULL, recording_url = NULL, "
                "summary = NULL, erased_subject_ref = :ref, updated_at = now() "
                "WHERE id = ANY(:ids)"
            ),
            {"ids": call_ids, "ref": "erased-subject-handle"},
        )
        await session.execute(
            text(
                "UPDATE call_extractions SET data = '{}'::jsonb, moments = NULL, "
                "errors = NULL, updated_at = now() "
                "WHERE call_id = ANY(:ids) AND data <> '{}'::jsonb"
            ),
            {"ids": call_ids},
        )


async def test_an_erased_callers_calls_leave_the_aggregate() -> None:
    """THE READ-TIME HALF OF THE FLOOR. Clearing k at write time proves nothing about a
    read taken after the underlying set was rewritten, and an erasure rewrites it.

    Measured on this module before the predicate existed, over the same twenty-five calls
    this test builds — five of them then erased:

        BEFORE  answer:reason_for_call:appointment  25/25
        AFTER   answer:reason_for_call:appointment  20/25   <- the delta IS the erased five
        AFTER   outcome:resolved                    25/25   <- still counting them
        AFTER   field:preferred_slot                 5/25   <- a FALSE gap, about them

    Three distinct failures in one query. The third is the one that reads as a feature:
    the erasure empties `call_extractions.data`, the emptied row looks like a call the
    agent captured nothing on, and the digest gains "Preferred slot — missing on 5 of 25
    calls" — a sentence about a working agent and about precisely the people whose data
    was supposed to be gone.
    """
    captured = '{"reason_for_call": "appointment", "preferred_slot": "6pm Thursday"}'
    calls = [
        {"outcome_tag": "resolved", "sentiment": "positive", "data": captured}
        for _ in range(MIN_CALLS_PER_WINDOW + 5)
    ]
    tenant_id, agent_id = await _agent_with_calls(outcomes=calls)
    window = {"since": datetime.now(UTC) - timedelta(days=7), "until": datetime.now(UTC)}

    async with tenant_session(tenant_id) as session:
        before = await insights_module.insights_for_agent(session, agent_id=agent_id, **window)
        erased = [
            row[0]
            for row in (
                await session.execute(
                    text(
                        "SELECT id FROM calls WHERE agent_id = :aid "
                        "ORDER BY engine_call_id LIMIT :n"
                    ),
                    {"aid": agent_id, "n": MIN_CALLS_PER_PATTERN},
                )
            ).all()
        ]
    assert before is not None
    assert before.calls == len(calls)

    await _erase_subject(tenant_id, erased)

    async with tenant_session(tenant_id) as session:
        after = await insights_module.insights_for_agent(session, agent_id=agent_id, **window)
    assert after is not None

    assert after.calls == before.calls - len(erased), (
        "an erased caller is still in the denominator — so every count in the digest is "
        "a fraction of a population that includes people whose data was destroyed"
    )
    by_token = {p.token: p for p in after.patterns}
    for token in (outcome_token("resolved"), "sentiment:positive"):
        pattern = by_token.get(token)
        assert pattern is not None and pattern.calls == after.calls, (
            f"{token} still counts the erased calls: the erasure NULLs the numbers and the "
            "summary and leaves outcome_tag and sentiment alone, so the row keeps feeding "
            "a published statistic after the certificate said it was destroyed"
        )
    assert field_token("preferred_slot") not in by_token, (
        "the erasure manufactured a knowledge gap. `call_extractions.data` was emptied by "
        "the erasure, not by the agent, and reporting it as a miss is both false about the "
        "agent and a statement about exactly the callers who were erased"
    )
    body = insights_module.render_digest(after, agent_name="Reception")
    assert body is not None
    assert "missing on" not in body

    # THE DIFFERENCING ATTACK, stated as arithmetic. Two renders of ONE window, taken
    # either side of the erasure, must not subtract to the erased subject's answers.
    asked = answer_token("reason_for_call", "appointment")
    before_asked = next(p for p in before.patterns if p.token == asked)
    after_asked = by_token[asked]
    assert (before_asked.calls, before_asked.of_calls) != (after_asked.calls, len(calls)), (
        "the two renders share a denominator, so before-minus-after is the erased "
        "subject's answer, exactly"
    )
    assert after_asked.of_calls == after.calls


# --- the worker --------------------------------------------------------------------


def test_the_window_is_the_week_that_closed_in_ist() -> None:
    """arq evaluates cron fields in the WORKER's clock, so the schedule cannot be what
    decides which seven days are summarised. `closed_week` is."""
    fired = datetime(2026, 8, 17, 1, 35, tzinfo=UTC)  # Monday 07:05 IST
    since, until = kb_aggregation.closed_week(fired)
    assert until - since == timedelta(days=7)
    assert until <= fired, "a digest never summarises a week that has not closed"
    # 00:00 IST on Monday 17 Aug is 18:30 UTC on Sunday 16 Aug.
    assert until == datetime(2026, 8, 16, 18, 30, tzinfo=UTC)


def _sweep_only(monkeypatch: pytest.MonkeyPatch, *tenant_ids: uuid.UUID) -> None:
    """Point `_sweep`'s enumeration at THESE tenants and nobody else.

    `_LIVE_AGENTS_SQL` reads every active row of `engine_agent_routes`, a deliberately
    GLOBAL table, and caps the tick at `KB_DIGEST_MAX_AGENTS` (1500) ordered by tenant.
    Tenant ids are uuid7, so they order by creation — which means that once a shared
    development database holds more than 1500 live routes, the rows a test just wrote are
    the ones past the cap, and the test fails with "nobody was mailed" for a reason that
    has nothing to do with the code under test. That is not hypothetical: this suite met
    it at 2088 live pairs.

    Scoping the enumeration is the fix rather than deleting other rows (four suites share
    this database) or raising the cap (the cap is the thing several of these tests are
    about). Everything below the enumeration is still the real thing — `_sweep`'s loop,
    `_digest_one`, the tenant session, RLS, the render and the transport.
    """
    scoped = _LIVE_AGENTS_SQL_SCOPED.format(
        tenants=", ".join(f"'{tenant_id}'::uuid" for tenant_id in tenant_ids)
    )
    monkeypatch.setattr(kb_aggregation, "_LIVE_AGENTS_SQL", scoped)


_LIVE_AGENTS_SQL_SCOPED = (
    "SELECT DISTINCT tenant_id, agent_id FROM engine_agent_routes "
    "WHERE active AND tenant_id IN ({tenants}) ORDER BY tenant_id, agent_id LIMIT :limit"
)


class _RecordingTransport:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        # `html` accepted because `transport.Transport` declares it (the branded
        # alternative, `workers/email_render`). A double whose signature has drifted from
        # the Protocol stops being evidence about the real call — which is what
        # `tests/auth_email_delivery_test` exists to catch.
        self.sent.append((to, subject, body))
        return True


async def test_the_sweep_mails_one_digest_per_agent_and_it_carries_no_call_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole loop, over rows whose transcript-derived columns are populated."""
    calls = [
        {
            "outcome_tag": "needs_follow_up",
            "sentiment": "negative",
            "data": '{"reason_for_call": "timings"}',
        }
        for _ in range(MIN_CALLS_PER_WINDOW + 3)
    ]
    # HOSTILE ROWS, and they are the reason this test is end-to-end rather than a render
    # check. The extractor returned a caller's sentence where the schema declared an enum,
    # which is the real shape of the failure — a model saying something the client never
    # typed. If the admission door ever stops testing membership, these become a token no
    # vocabulary declares, the wall refuses the batch, and the sweep raises here instead of
    # mailing a caller's words to a business owner.
    calls += [
        {"outcome_tag": "resolved", "data": json.dumps({"reason_for_call": CALLER_WORDS})}
        for _ in range(MIN_CALLS_PER_PATTERN + 1)
    ]
    tenant_id, agent_id = await _agent_with_calls(outcomes=calls)
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                "agent_id, active, created_at, updated_at) VALUES ('fake', :ref, :tid, :aid, "
                "true, now(), now())"
            ),
            {"ref": f"digest-{uuid.uuid4().hex[:10]}", "tid": tenant_id, "aid": agent_id},
        )

    recorder = _RecordingTransport()
    monkeypatch.setattr(kb_aggregation, "get_transport", lambda: recorder)
    _sweep_only(monkeypatch, tenant_id)
    await kb_aggregation._sweep(_sweep_fired_after_calls_week())

    mine = [sent for sent in recorder.sent if sent[0] == "owner@example.test"]
    assert mine, "the agent's owner received no digest"
    body = mine[0][2]
    assert CALLER_WORDS not in body
    assert CALLER_NUMBER not in body
    assert "Reason for call: timings" in body


# --- the tick's one invariant: never raise after something has been sent -------------


async def _live_agent_addressed(address: str) -> uuid.UUID:
    """One live agent with a route and enough calls to publish, reachable at `address`.

    A unique address per agent is what makes the assertions below countable. `_sweep`
    walks EVERY live route in the database, so a suite that shares `owner@example.test`
    can only ever assert "at least one" — and "was this client mailed TWICE" is the exact
    question these tests exist to ask.
    """
    calls = [
        {"outcome_tag": "resolved", "sentiment": "positive", "data": '{"reason_for_call": "fees"}'}
        for _ in range(MIN_CALLS_PER_WINDOW + 2)
    ]
    tenant_id, agent_id = await _agent_with_calls(outcomes=calls)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET billing_email = :email WHERE id = :id"),
            {"email": address, "id": tenant_id},
        )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                "agent_id, active, created_at, updated_at) VALUES ('fake', :ref, :tid, :aid, "
                "true, now(), now())"
            ),
            {"ref": f"digest-{uuid.uuid4().hex[:10]}", "tid": tenant_id, "aid": agent_id},
        )
    return tenant_id


class _FlakyTransport:
    """Raises for one address, records the rest. The transports in `workers/transport.py`
    return False for the failures they EXPECT — this is the class they do not: settings
    that will not resolve, an HTTP error the client did not classify, anything
    `asyncio.to_thread` re-raises from the worker thread."""

    def __init__(self, explodes_for: str) -> None:
        self.explodes_for = explodes_for
        self.sent: list[str] = []

    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        if to == self.explodes_for:
            raise RuntimeError("the mail host closed the connection")
        self.sent.append(to)
        return True


async def test_one_agents_send_blowing_up_never_re_mails_the_clients_already_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE IDEMPOTENCY QUESTION, in the only direction that costs anything here.

    Nothing is persisted, so a retry cannot double-count into a store and cannot lower a
    k-threshold. What it CAN do is mail the same window twice: the tick sits behind arq's
    retry ladder, so an exception escaping the per-agent guard takes the whole sweep down
    and the next attempt starts again from the top of the ordering — re-mailing every
    client already reached, up to `WORKER_MAX_TRIES` times, while the agent that threw
    still gets nothing.

    Two agents, two addresses; the second one's send raises. The first must be mailed
    exactly once and `_sweep` must return rather than raise.
    """
    good = f"good-{uuid.uuid4().hex[:8]}@example.test"
    bad = f"bad-{uuid.uuid4().hex[:8]}@example.test"
    good_tenant = await _live_agent_addressed(good)
    bad_tenant = await _live_agent_addressed(bad)

    transport = _FlakyTransport(explodes_for=bad)
    monkeypatch.setattr(kb_aggregation, "get_transport", lambda: transport)
    _sweep_only(monkeypatch, good_tenant, bad_tenant)
    summary = await kb_aggregation._sweep(_sweep_fired_after_calls_week())

    assert transport.sent.count(good) == 1, (
        "the reachable client was mailed a number of times other than once — a send that "
        "escapes `_digest_one` takes `_sweep` down and the retry ladder re-mails the "
        "whole prefix of the ordering"
    )
    assert "failed=" in summary and "failed=0" not in summary, (
        "the unreachable client was not counted as a failure, so the sweep would report "
        "a clean week"
    )


async def test_a_refused_digest_stops_the_tick_instead_of_climbing_the_ladder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `CallContentLeakError` is a code defect, not a blip. Retrying it re-runs the same
    window against the same vocabulary and the same rows — it cannot succeed, and each
    attempt re-mails every client the sweep reached before the refusal. The alarm must not
    be the thing that triples the mailing."""

    async def _refuse(_now: datetime) -> str:
        raise CallContentLeakError("a token no vocabulary declares")

    monkeypatch.setattr(kb_aggregation, "_sweep", _refuse)
    with pytest.raises(CallContentLeakError):
        await kb_aggregation.send_agent_knowledge_digests({"job_try": 1})


async def test_an_ordinary_failure_still_climbs_the_ladder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The positive control for the test above. Without it, "a leak is not retried" is
    satisfied by a tick that retries nothing at all — and this job runs WEEKLY, so a tick
    finished by its first transient error is a week in which no client heard anything."""

    async def _blip(_now: datetime) -> str:
        raise TimeoutError("the database was not there")

    monkeypatch.setattr(kb_aggregation, "_sweep", _blip)
    with pytest.raises(Retry):
        await kb_aggregation.send_agent_knowledge_digests({"job_try": 1})


# --- hard rule 1: the new read path, across tenants ----------------------------------


async def test_another_tenants_agent_is_zero_rows_not_a_smaller_answer() -> None:
    """CROSS-TENANT ZERO ROWS. `insights_for_agent` filters on `agent_id` and NOTHING
    else — no `tenant_id` predicate, deliberately (a WHERE clause a caller can forget is
    what hard rule 1 refuses to rely on). RLS is therefore the entire boundary on this
    new read, and a boundary with no test is a boundary nobody will notice losing.

    An agent id is a uuid7 that appears in log lines and in a URL, so "somebody holds
    another tenant's agent id" is the ordinary case rather than the adversarial one.
    """
    calls = [
        {"outcome_tag": "resolved", "sentiment": "positive", "data": '{"reason_for_call": "fees"}'}
        for _ in range(MIN_CALLS_PER_WINDOW + 5)
    ]
    owner_tenant, agent_id = await _agent_with_calls(outcomes=calls)
    stranger_tenant, _ = await _agent_with_calls(outcomes=calls)
    assert owner_tenant != stranger_tenant

    window = {"since": datetime.now(UTC) - timedelta(days=7), "until": datetime.now(UTC)}
    async with tenant_session(stranger_tenant) as session:
        stolen = await insights_module.insights_for_agent(session, agent_id=agent_id, **window)
    # The schema read is the first statement and it is RLS'd too, so a stranger cannot
    # even learn the agent's VOCABULARY — which is the client's own business language.
    assert stolen is None, "another tenant's agent answered a read scoped to this one"

    async with tenant_session(owner_tenant) as session:
        mine = await insights_module.insights_for_agent(session, agent_id=agent_id, **window)
    assert mine is not None and mine.calls == len(calls), "the owner's own read broke"


async def test_a_route_row_pointing_at_the_wrong_tenant_mails_nobody(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`engine_agent_routes` is the deliberately GLOBAL table the sweep enumerates, so it
    is the one place a (tenant, agent) pair arrives UNPROVEN — an untenanted read hands
    `_digest_one` whatever pair the row holds. If that pair is wrong, one client's weekly
    digest is addressed to another client's billing address.

    `_digest_one` opens `tenant_session(row.tenant_id)` and then looks the agent up
    INSIDE it, so a mismatched pair finds no agent and mails nobody.

    WHAT THIS TEST IS, PRECISELY: a pin, not a caught defect. Three tables on this path —
    `agents`, `extraction_schemas` and `calls` — each carry FORCE RLS with a policy that
    yields zero rows when `app.tenant_id` is unset, so every sabotage of this module that
    was actually tried (the lookup moved to `untenanted_session`; a recipient fallback
    reading the route's own tenant; both together) makes the sweep mail NOBODY rather than
    mailing the wrong client — loudly caught by the two tests above it. The disclosure this
    asserts against is unreachable from here as long as those three policies exist, which
    is the right answer and is worth a test that says so out loud: the day one of them is
    relaxed, this is the test that turns the relaxation into a mail delivery somebody has
    to explain.
    """
    calls = [
        {"outcome_tag": "resolved", "sentiment": "positive", "data": '{"reason_for_call": "fees"}'}
        for _ in range(MIN_CALLS_PER_WINDOW + 5)
    ]
    _, agent_id = await _agent_with_calls(outcomes=calls)
    stranger_address = f"stranger-{uuid.uuid4().hex[:8]}@example.test"
    stranger_tenant, _ = await _agent_with_calls(outcomes=[])
    async with tenant_session(stranger_tenant) as session:
        await session.execute(
            text("UPDATE organizations SET billing_email = :email WHERE id = :id"),
            {"email": stranger_address, "id": stranger_tenant},
        )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                "agent_id, active, created_at, updated_at) VALUES ('fake', :ref, :tid, :aid, "
                "true, now(), now())"
            ),
            {"ref": f"crossed-{uuid.uuid4().hex[:10]}", "tid": stranger_tenant, "aid": agent_id},
        )

    recorder = _RecordingTransport()
    monkeypatch.setattr(kb_aggregation, "get_transport", lambda: recorder)
    _sweep_only(monkeypatch, stranger_tenant)
    await kb_aggregation._sweep(_sweep_fired_after_calls_week())

    assert not [sent for sent in recorder.sent if sent[0] == stranger_address], (
        "a route row naming the wrong tenant mailed one client's aggregate to another"
    )


# --- a scrubbed extraction is not an empty one (D-433) -------------------------------


async def _age_and_scrub(tenant_id: uuid.UUID, call_ids: list[uuid.UUID]) -> int:
    """Run the REAL lead-clock retention sweep over these calls' extractions.

    Aged rather than mocked: `_EXTRACTION_SQL`'s predicate is `updated_at < cutoff`, so
    the only honest way to make the sweep select a row is to make the row old. What runs
    afterwards is `retention._apply_one` itself — the same function `apply_retention`
    calls for a `lead` policy — so this test fails if the scrubber stops stamping the
    marker, which no reader-side test could notice.
    """
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE call_extractions SET updated_at = now() - interval '400 days' "
                "WHERE call_id = ANY(:ids)"
            ),
            {"ids": call_ids},
        )
    async with tenant_session(tenant_id) as session:
        counts = await retention._apply_one(
            session, tenant_id=tenant_id, category="lead", ttl_days=1, action="anonymize"
        )
    return int(counts["extractions"])


async def _first_call_ids(tenant_id: uuid.UUID, agent_id: uuid.UUID, n: int) -> list[uuid.UUID]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT id FROM calls WHERE agent_id = :aid ORDER BY engine_call_id LIMIT :n"),
                {"aid": agent_id, "n": n},
            )
        ).all()
    return [row[0] for row in rows]


async def test_the_retention_scrub_records_that_it_scrubbed() -> None:
    """THE MARKER IS WRITTEN BY THE CODE THAT CREATES THE FACT, in the same UPDATE.

    `call_extractions.data = '{}'` is written both by an extraction that captured nothing
    and by the sweep that destroys one, and the two are opposites. Every derivation that
    would tell them apart afterwards is a heuristic — `updated_at` moved, `errors IS NULL`,
    `moments IS NULL` — so the sweep records it instead (migration f2a6d81b39c4).

    Asserted on BOTH sides: the scrubbed rows carry the stamp AND the untouched rows do
    not, because a marker that is always set is the same as no marker at all.
    """
    captured = '{"reason_for_call": "appointment", "preferred_slot": "6pm Thursday"}'
    calls = [{"outcome_tag": "resolved", "data": captured} for _ in range(10)]
    tenant_id, agent_id = await _agent_with_calls(outcomes=calls)
    scrubbed_ids = await _first_call_ids(tenant_id, agent_id, 4)

    assert await _age_and_scrub(tenant_id, scrubbed_ids) == len(scrubbed_ids)

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT c.id, e.data::text, e.scrubbed_at IS NOT NULL FROM calls c "
                    "JOIN call_extractions e ON e.call_id = c.id WHERE c.agent_id = :aid"
                ),
                {"aid": agent_id},
            )
        ).all()
    marked = {row[0] for row in rows if row[2]}
    assert marked == set(scrubbed_ids), (
        "the retention sweep emptied an extraction without recording that it did — the "
        "row is now indistinguishable from one where the agent captured nothing"
    )
    for call_id, data, was_marked in rows:
        assert (data == "{}") is was_marked, (
            f"call {call_id}: emptied and unmarked, or marked and still holding data — "
            "the stamp and the emptying must ride in one statement"
        )


async def test_a_scrubbed_extraction_is_not_counted_as_a_missed_field() -> None:
    """THE DEFECT THIS LANE CLOSES, end to end over real rows and the real sweep.

    Twenty-five calls on which the agent captured the required field EVERY TIME; the
    client's lead-retention policy then clears five of them. Before the marker existed the
    digest read:

        Details the agent was asked to capture and often did not:
          - Preferred slot — missing on 5 of 25 calls

    — a false accusation against a working agent, manufactured by our own retention
    policy and mailed to the business owner.

    A SCRUB IS NOT AN ERASURE, so the answer is not the erasure's. The scrub destroyed the
    EXTRACTION and nothing else: `outcome_tag` and `sentiment` live on `calls`, no sweep
    touches them, and they are still true — so those two families keep the full
    twenty-five and only the extraction families drop to twenty, numerator and denominator
    together. Getting that backwards would silently shrink a real statistic.
    """
    captured = '{"reason_for_call": "appointment", "preferred_slot": "6pm Thursday"}'
    calls = [
        {"outcome_tag": "resolved", "sentiment": "positive", "data": captured}
        for _ in range(MIN_CALLS_PER_WINDOW + 5)
    ]
    tenant_id, agent_id = await _agent_with_calls(outcomes=calls)
    scrubbed_ids = await _first_call_ids(tenant_id, agent_id, MIN_CALLS_PER_PATTERN)
    assert await _age_and_scrub(tenant_id, scrubbed_ids) == len(scrubbed_ids)

    async with tenant_session(tenant_id) as session:
        result = await insights_module.insights_for_agent(
            session,
            agent_id=agent_id,
            since=datetime.now(UTC) - timedelta(days=7),
            until=datetime.now(UTC),
        )
    assert result is not None
    assert result.calls == len(calls), "a scrubbed call is still a call that happened"
    assert result.calls_with_details == len(calls) - len(scrubbed_ids)

    by_token = {p.token: p for p in result.patterns}
    assert field_token("preferred_slot") not in by_token, (
        "the retention sweep manufactured a knowledge gap: it emptied `data`, the emptied "
        "row read as 'the agent captured nothing', and a working agent was reported as "
        "failing on exactly the calls the client's own policy cleared"
    )
    asked = by_token[answer_token("reason_for_call", "appointment")]
    assert (asked.calls, asked.of_calls) == (result.calls_with_details, result.calls_with_details)

    # THE OTHER DIRECTION, and it is the one that is easy to get wrong quietly.
    for token in (outcome_token("resolved"), "sentiment:positive"):
        pattern = by_token[token]
        assert (pattern.calls, pattern.of_calls) == (result.calls, result.calls), (
            f"{token} lost the scrubbed calls. A retention scrub destroys the EXTRACTION; "
            "outcome and sentiment are columns on `calls` that it never touches, so "
            "dropping them here shrinks a statistic that is still entirely true"
        )

    body = insights_module.render_digest(result, agent_name="Reception")
    assert body is not None
    assert "missing on" not in body
    assert f"Across {result.calls} completed calls" in body
    assert f"counted over {result.calls_with_details} of those {result.calls} calls" in body, (
        "the digest prints two different denominators and does not say why — a correct "
        "digest that does not add up gets reported as a bug"
    )


def test_a_scrubbed_call_keeps_its_outcome_and_loses_only_its_details() -> None:
    """The same split, at the `distil` boundary, where it is one assertion rather than a
    week of rows. Every call is scrubbed except enough to keep the extraction family
    alive, so the two denominators are provably different in one batch."""
    vocabulary = _vocabulary()
    answer = answer_token("reason_for_call", "fees")
    readable = [
        CallOutcome(call_id=uuid7(), tokens=frozenset({answer, outcome_token("resolved")}))
        for _ in range(MIN_CALLS_PER_WINDOW)
    ]
    scrubbed = [
        CallOutcome(
            call_id=uuid7(),
            tokens=frozenset({outcome_token("resolved")}),
            extraction_readable=False,
        )
        for _ in range(7)
    ]
    by_token = {p.token: p for p in distil(readable + scrubbed, vocabulary=vocabulary)}
    assert by_token[outcome_token("resolved")].of_calls == len(readable) + len(scrubbed)
    assert by_token[answer].of_calls == len(readable)
    assert by_token[answer].calls == len(readable)


def test_an_extraction_family_below_the_floor_publishes_nothing_while_outcomes_still_do() -> None:
    """THE K FLOOR BINDS ON WHATEVER DENOMINATOR A FAMILY IS COUNTED OVER — the safe
    direction, same as the erasure predicate.

    A busy week whose extractions have almost all been cleared leaves a handful of
    readable calls, and a pattern over those would be a statistic about a small,
    self-selected group wearing a busy week's authority. The extraction families publish
    NOTHING; the outcome family is untouched and still publishes, because its own
    population never shrank.
    """
    vocabulary = _vocabulary()
    answer = answer_token("reason_for_call", "fees")
    readable = [
        CallOutcome(call_id=uuid7(), tokens=frozenset({answer, outcome_token("resolved")}))
        for _ in range(MIN_CALLS_PER_PATTERN)
    ]
    scrubbed = [
        CallOutcome(
            call_id=uuid7(),
            tokens=frozenset({outcome_token("resolved")}),
            extraction_readable=False,
        )
        for _ in range(MIN_CALLS_PER_WINDOW)
    ]
    assert len(readable) >= MIN_CALLS_PER_PATTERN, "the pattern must clear k on its own"
    assert len(readable) < MIN_CALLS_PER_WINDOW, "...while its family's population does not"

    published = {p.token: p for p in distil(readable + scrubbed, vocabulary=vocabulary)}
    assert answer not in published, (
        "an extraction family published a statistic over a population below the window "
        "floor — k=5 was cleared on a denominator of five, which is the disclosure "
        "MIN_CALLS_PER_WINDOW exists to refuse"
    )
    assert published[outcome_token("resolved")].of_calls == len(readable) + len(scrubbed)
