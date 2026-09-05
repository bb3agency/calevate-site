"""`calls.disclosure_played` — the compliance column nothing wrote (P3.3, part b).

The column has existed since the first migration. The client's call detail screen renders
it through `DisclosureNotice`, and the weekly QA compliance-review queue puts it in front
of a reviewer working OPERATIONS §5's "disclosure spoken" scenario. **No code in this
repository ever assigned it a value**, so all three surfaces rendered a permanently null
field and the product asked a human to certify a property it had never measured.

Two halves are tested here and they are separable on purpose:

* `compliance/disclosure.disclosure_spoken` — the deterministic match, unit-tested, no
  database. This is the half the red-team eval harness will reuse.
* the PIPELINE writing what that function returned, against a real call row. A matcher
  nobody called is the same defect in a new spelling.

The tri-state is the thing to get right. `None` must stay reachable — the screens already
render it as "unknown" and a `False` in its place reads to a client as a breach.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from apps.api.compliance.disclosure import disclosure_spoken
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.workers import pipeline
from apps.workers.pipeline import ingest_engine_event, run_post_call_pipeline
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant

DISCLOSURE = "Idi AI assistant. Ee call record avutundi."


@dataclass(frozen=True, slots=True)
class Turn:
    """The `SpokenTurn` protocol, minimally. Same shape `detect_opt_out`'s tests use."""

    speaker: str
    text: str


# ============================================================================
# The match
# ============================================================================


def test_the_agent_saying_the_line_is_the_evidence() -> None:
    turns = [
        Turn("agent", DISCLOSURE),
        Turn("caller", "Sare, cheppandi."),
    ]
    assert disclosure_spoken(turns, disclosure_line=DISCLOSURE) is True


def test_punctuation_and_case_do_not_decide_a_compliance_verdict() -> None:
    """`normalize_utterance` is shared with `detect_opt_out` rather than re-derived here.

    An engine's transcript is not a byte copy of what we configured — capitalisation,
    trailing punctuation and the STT's own formatting all move — and a verdict that
    flipped on a full stop would be a test of our string handling wearing a compliance
    field's name.
    """
    turns = [Turn("agent", "IDI AI ASSISTANT, EE CALL RECORD AVUTUNDI!!  Namaskaram.")]
    assert disclosure_spoken(turns, disclosure_line=DISCLOSURE) is True


def test_a_line_spoken_after_some_filler_still_counts() -> None:
    """ANY agent turn, not the first.

    Engines legitimately emit a connection-noise or filler turn ahead of the welcome
    message. Requiring index 0 would report a breach on a call where the greeting played
    exactly as configured — and "spoken FIRST" is verified where it can be verified
    properly, at publish time against the engine's greeting field
    (`verification.judge`), not inferred from a transcript.
    """
    turns = [
        Turn("agent", "Hello?"),
        Turn("caller", "Hello."),
        Turn("agent", DISCLOSURE),
    ]
    assert disclosure_spoken(turns, disclosure_line=DISCLOSURE) is True


def test_a_call_where_it_was_never_said_is_false_not_unknown() -> None:
    """There WERE agent turns, and the line was not among them. That is a finding."""
    turns = [
        Turn("agent", "Sunrise Clinic, cheppandi."),
        Turn("caller", "Appointment kavali."),
    ]
    assert disclosure_spoken(turns, disclosure_line=DISCLOSURE) is False


def test_the_caller_reading_it_back_does_not_satisfy_it() -> None:
    """Agent turns only, the mirror of `detect_opt_out`'s caller-turns-only rule.

    The disclosure is ours to speak. Counting a caller turn would let an STT pass that
    misattributed our own audio to the caller channel certify a call nobody disclosed on
    — and would make the verdict depend on diarisation quality rather than on what the
    agent said.
    """
    turns = [
        Turn("agent", "Sunrise Clinic."),
        Turn("caller", f"Meeru cheppindi — {DISCLOSURE}"),
    ]
    assert disclosure_spoken(turns, disclosure_line=DISCLOSURE) is False


# ============================================================================
# The tri-state — the part that must not collapse
# ============================================================================


def test_no_transcript_is_unknown_rather_than_a_breach() -> None:
    """`None`, and the screens already render it as "unknown".

    A call whose transcript the engine never returned, or where the caller hung up before
    a word, is a call we have no evidence about. Reporting `False` would put "disclosure
    not played" in a client's QA queue for every dropped connection, which is how a
    compliance signal becomes noise a reviewer clicks past.
    """
    assert disclosure_spoken([], disclosure_line=DISCLOSURE) is None


def test_a_call_with_only_caller_turns_is_unknown() -> None:
    """Nothing the agent said was recorded, so there is nothing to judge — as distinct
    from having looked at what it said and not found the line."""
    assert disclosure_spoken([Turn("caller", "Hello?")], disclosure_line=DISCLOSURE) is None


def test_an_empty_disclosure_line_certifies_nothing() -> None:
    """The empty string is contained in every transcript ever recorded.

    `agents.disclosure_line` is NOT NULL and the compliance gate refuses a blank one, so
    no tenant reaches this — but a fixture or a future importer can, and the failure
    would be silent and total: every call in the system reading `disclosure_played` true
    on no evidence at all.
    """
    assert disclosure_spoken([Turn("agent", "anything")], disclosure_line="") is None
    assert disclosure_spoken([Turn("agent", "anything")], disclosure_line="   ") is None


# ============================================================================
# Hard rule 6 — what this may not carry
# ============================================================================


def test_the_verdict_is_a_boolean_and_never_the_words() -> None:
    """A tri-state, by construction. This function's whole output surface is three
    values, so there is no path by which a transcript turn reaches a log line or an
    alert body through it — which is the property `optout.OptOutSignal` has to work for,
    since IT carries an evidence span and this deliberately does not.
    """
    verdict = disclosure_spoken([Turn("agent", DISCLOSURE)], disclosure_line=DISCLOSURE)
    assert verdict in (True, False, None)
    assert isinstance(verdict, bool)


def test_the_module_exports_no_second_way_to_decide_what_disclosed_means() -> None:
    """It used to export exactly one name, and the reason was right: a second export
    here would be the beginning of a second place that decides what "disclosed" MEANS —
    and this repo already has one of those, at publish time, against the engine.

    D-163 gave the module a second half — the product COPY an agent's two notices start
    from — and the rule survives the addition rather than being dropped for it: the thing
    that must stay unique is the JUDGEMENT. `disclosure_spoken` is still the only export
    that decides anything, and the composition of an opening lives one layer out, in
    `calevate_shared.engine.compose_opening_line`, so it cannot fork here either.
    """
    from apps.api.compliance import disclosure

    verdicts = [name for name in disclosure.__all__ if name.endswith("_spoken")]
    assert verdicts == ["disclosure_spoken"], disclosure.__all__
    assert not hasattr(disclosure, "compose_opening_line"), (
        "the opening composer has been re-exported here, so there are now two places to "
        "import it from and one of them will drift"
    )


# ============================================================================
# The pipeline actually writes it
# ============================================================================


@pytest.fixture(autouse=True)
def _stub_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """The recording copy needs a bucket; nothing here is about object storage."""

    async def _fake_copy(
        *, source_url: str, tenant_id: uuid.UUID, call_id: uuid.UUID, leg: str = "call"
    ) -> str:
        # `leg` NAMES WHICH OF A CALL'S TWO RECORDINGS (D-533): a call handed to a
        # person has a second one, and the two must not land on one key. Defaulted so
        # this stub reads the way the pipeline calls it for an ordinary call.
        suffix = "" if leg == "call" else "-transfer"
        return f"recordings/{tenant_id}/{call_id}{suffix}.wav"

    monkeypatch.setattr(pipeline, "copy_recording", _fake_copy)


async def _driven(*, disclosure_line: str | None = None) -> tuple[uuid.UUID, uuid.UUID]:
    """One completed call, taken all the way through the real pipeline.

    `disclosure_line` overrides what the agent is configured to say, which is how the two
    verdicts below are produced from the SAME canned transcript: the fake engine's
    `SAMPLE_TURNS` opens with a fixed agent greeting, so setting the agent's line to a
    phrase inside it yields `True` and leaving the default yields `False`. Driving both
    from one transcript is deliberate — if the two cases used different transcripts, a
    verdict hard-coded per fixture would pass just as well.
    """
    agent_ref = f"disclosure_{uuid.uuid4().hex[:10]}"
    tenant_id, agent_id = await _seed_tenant(agent_ref)
    if disclosure_line is not None:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE agents SET ai_disclosure_line = :line WHERE id = :aid"),
                {"line": disclosure_line, "aid": agent_id},
            )

    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    get_engine().seed_inbound_call(  # type: ignore[attr-defined]
        call_id=execution_id,
        agent_ref=agent_ref,
        from_e164=f"+9198{uuid.uuid4().int % 100000000:08d}",
        to_e164="+911140000000",
    )
    await ingest_engine_event(
        {}, {"engine": "fake", "execution_id": execution_id, "engine_agent_ref": agent_ref}
    )
    async with tenant_session(tenant_id) as session:
        call_id = (
            await session.execute(
                text("SELECT id FROM calls WHERE engine_call_id = :e"), {"e": execution_id}
            )
        ).scalar_one()
    await run_post_call_pipeline(
        {},
        {
            "tenant_id": str(tenant_id),
            "call_id": str(call_id),
            "engine": "fake",
            "execution_id": execution_id,
        },
    )
    return tenant_id, call_id


async def _played(tenant_id: uuid.UUID, call_id: uuid.UUID) -> bool | None:
    async with tenant_session(tenant_id) as session:
        value = (
            await session.execute(
                text("SELECT disclosure_played FROM calls WHERE id = :c"), {"c": call_id}
            )
        ).scalar()
    return value


async def test_a_real_pipeline_run_writes_the_column_nothing_used_to_write() -> None:
    """THE HALF THAT WAS MISSING, and the only kind of test that could catch it.

    What failed in P3.3 was never the arithmetic — it was that no code path assigned the
    column at all. A unit test of the matcher passes with the pipeline untouched; only
    driving a real call and reading the row back tells the difference.
    """
    tenant_id, call_id = await _driven(disclosure_line="idi Sunrise Clinic AI assistant")

    assert await _played(tenant_id, call_id) is True


async def test_an_agent_whose_line_is_not_in_the_transcript_reads_false() -> None:
    """Same canned transcript, different configured line — so the verdict is provably
    computed from the agent's own disclosure rather than hard-coded per fixture."""
    tenant_id, call_id = await _driven(disclosure_line="Ee call ni AI teeskuntundi, ok na?")

    assert await _played(tenant_id, call_id) is False


async def test_a_rerun_that_sees_no_transcript_clears_a_previous_verdict() -> None:
    """The verdict must not RATCHET.

    The pipeline is re-runnable by design (TRD §8) and the reconciliation poller re-drives
    calls. If a second pass sees no transcript, the evidence behind the first pass's
    answer is gone too — a field that could only ever move towards `True` would be a
    compliance record that remembers a measurement it can no longer support.
    """
    tenant_id, call_id = await _driven(disclosure_line="idi Sunrise Clinic AI assistant")
    assert await _played(tenant_id, call_id) is True

    await pipeline._record_disclosure(tenant_id, call_id, None)

    assert await _played(tenant_id, call_id) is None


async def test_the_context_load_hands_back_the_agents_ai_disclosure_line() -> None:
    """The seam between the two halves, and the one a rename would break silently.

    `_load_call_context` grew a fifth (and now a sixth, the RECORDING notice) return value
    rather than gaining a second query, and nothing else in the pipeline reads the agent's
    disclosure. If that column is
    ever renamed or the join changes shape, this is what says so — the alternative is a
    matcher fed an empty string, which returns `None` for every call and looks exactly
    like a fleet with no transcripts.

    It is `ai_disclosure_line` since D-163, not the legacy bundle: the question the column
    answers is "did the agent say the AI disclosure", so scoring it against a string that
    also contains a recording notice the agent may have switched off would report a breach
    on every call of a lawfully configured agent.
    """
    tenant_id, call_id = await _driven(disclosure_line=DISCLOSURE)

    _spec, _version, agent_id, direction, line, _notice = await pipeline._load_call_context(
        tenant_id, call_id
    )

    assert line == DISCLOSURE
    assert isinstance(agent_id, uuid.UUID)
    assert direction == "inbound"


async def test_a_withdrawn_ai_notice_certifies_nothing_rather_than_reporting_a_breach() -> None:
    """D-163's effect on the EVIDENCE half, driven through the real pipeline.

    An agent whose owner has switched the AI notice off was never asked to say it. The
    honest verdict is `None` — the tri-state's "there was nothing to look at" — and NOT
    `False`, which the QA queue and the client's call detail both render as a compliance
    failure on every single call.
    """
    tenant_id, call_id = await _driven(disclosure_line="idi Sunrise Clinic AI assistant")
    assert await _played(tenant_id, call_id) is True

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET ai_disclosure_enabled = false WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
    _spec, _version, _agent_id, _direction, line, _notice = await pipeline._load_call_context(
        tenant_id, call_id
    )

    assert line == "", "the pipeline is still scoring a sentence the agent never volunteers"
