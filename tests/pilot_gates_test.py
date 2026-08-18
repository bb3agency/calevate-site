"""Gates 1, 2 and 6 executed end to end — including every failure path.

WHY THIS FILE IS THE POINT OF THE SLICE. A pilot harness that has never run is exactly
as unverified as the vendor it exists to verify, and it gets exactly one chance, on a
day when a founder is holding a phone and burning PSTN credit. So every branch of every
gate runs here against `fake` and against small doubles built on top of it: the pass, the
fail, and the not-run.

WHY DOUBLES AND NOT JUST `FakeEngine`. `fake` is a conformance control, not a Bolna
simulator, and it deliberately does not model three things these gates turn on: it
performs no source-IP check (`method="none"`), it does not echo `user_data` into a
transcript, and it provisions numbers happily where the real adapter refuses. Each
double adds exactly ONE of those behaviours, so the test says which vendor property it
is standing in for instead of a general-purpose mock saying nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from apps.api.core.errors import ProblemError
from apps.api.engine.fake import EXTERNAL_DEPLOYMENT_CAPABILITIES, FakeEngine
from calevate_shared.config import Settings
from calevate_shared.engine import (
    AgentSnapshot,
    EngineAgentRef,
    ExecutionListing,
    ExecutionSnapshot,
    NumberSpec,
    ProvisionedNumber,
    WebhookVerdict,
)
from calevate_shared.events import TranscriptTurn
from scripts.pilot.gates_api import (
    DOCUMENTED_EGRESS_IP,
    GateContext,
    compare_delivery,
    run_gate_1,
    run_gate_2,
    run_gate_6,
)


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        app_env="local",
        database_url="postgresql+psycopg://u:p@localhost:5432/x",
        redis_url="redis://localhost:6379/0",
        object_store_endpoint="http://localhost:9000",
        object_store_bucket="calevate",
        webhook_base_url="https://pilot.example.com",
        engine="fake",
    )


def _ctx(engine: Any, **overrides: Any) -> GateContext:
    return GateContext(engine=engine, settings=_settings(), **overrides)


def _check(result: Any, name: str) -> Any:
    matches = [c for c in result.checks if c.name == name]
    assert matches, f"no sub-check named {name!r} in gate {result.number}"
    return matches[0]


# --- doubles ------------------------------------------------------------------


class SourceIpEngine(FakeEngine):
    """`fake` plus the one property gate 1 measures: a source-IP allowlist.

    Stands in for `BolnaEngine.verify_webhook`, which is the only adapter that has one.
    """

    def verify_webhook(
        self, headers: dict[str, str], body: bytes, source_ip: str
    ) -> WebhookVerdict:
        if source_ip == DOCUMENTED_EGRESS_IP:
            return WebhookVerdict(ok=True, method="source_ip")
        return WebhookVerdict(ok=False, method="source_ip", reason="not allowlisted")


class OpenAllowlistEngine(SourceIpEngine):
    """An allowlist that is not one — the defect gate 1 exists to catch."""

    def verify_webhook(
        self, headers: dict[str, str], body: bytes, source_ip: str
    ) -> WebhookVerdict:
        return WebhookVerdict(ok=True, method="source_ip")


class EchoingEngine(FakeEngine):
    """`fake` plus `user_data` round-tripping into the prompt (gate 2's real question).

    The shipped fake stores the CallContext and never surfaces it, so the round-trip
    check has no positive path against it. This double closes that by having the agent
    speak the nonce back, which is exactly what the pilot instructs the live agent to do.
    """

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        snapshot = await super().get_execution(call_id)
        call = self._calls.get(call_id) or {}
        nonce = (call.get("context") or {}).get("fields", {}).get("pilot_nonce")
        if not nonce:
            return snapshot
        spoken = TranscriptTurn(
            call_id=call_id,
            idx=len(snapshot.transcript),
            speaker="agent",
            text=f"Mee reference {nonce}.",
        )
        return snapshot.model_copy(update={"transcript": [*snapshot.transcript, spoken]})


class CallerEchoEngine(EchoingEngine):
    """The nonce comes back in a CALLER turn only.

    A human on a pilot call reading the reference aloud must not pass a check about
    whether the ENGINE rendered it into the prompt.
    """

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        snapshot = await super().get_execution(call_id)
        last = len(snapshot.transcript) - 1
        turns = [
            t.model_copy(update={"speaker": "caller"}) if t.idx == last else t
            for t in snapshot.transcript
        ]
        return snapshot.model_copy(update={"transcript": turns})


class SilentlyDroppedUpdateEngine(EchoingEngine):
    """Takes the PUT with a 2xx and goes on serving the ORIGINAL prompt.

    The vendor behaviour gate 2 was blind to until `get_agent` existed: every screen we
    own says the prompt changed, and the caller hears the old one — including the old
    disclosure line, which is the part a client is legally answerable for.
    """

    async def update_agent(self, ref: EngineAgentRef, cfg: Any) -> None:
        return None


class UnreadablePromptEngine(EchoingEngine):
    """A read-back that succeeds and carries no prompt — the honest "cannot tell".

    Stands in for `bolna._agent_system_prompt` failing to find the field, which is a
    live possibility: their agent shape is hand-maintained, not specified.
    """

    async def get_agent(self, ref: EngineAgentRef) -> AgentSnapshot:
        snapshot = await super().get_agent(ref)
        return snapshot.model_copy(update={"system_prompt": None, "system_prompt_readable": False})


class NoReadBackEngine(EchoingEngine):
    """The read-back endpoint answers 404 — our path is wrong, not the vendor's memory."""

    async def get_agent(self, ref: EngineAgentRef) -> AgentSnapshot:
        raise ProblemError(
            kind="dependency",
            code="engine_rejected",
            title="Voice engine rejected the request",
            detail="The voice platform could not complete this operation.",
        )


class NoNumberEngine(EchoingEngine):
    """Mirrors `BolnaEngine.provision_number`, which refuses (M1 defers it)."""

    async def provision_number(self, spec: NumberSpec) -> ProvisionedNumber:
        raise ProblemError(
            kind="dependency",
            code="engine_capability_unverified",
            title="Number provisioning is not automated yet",
            detail="Numbers are provisioned with the telephony provider directly (M1).",
        )


class BrokenAgentEngine(FakeEngine):
    async def create_agent(self, cfg: Any) -> EngineAgentRef:
        raise ProblemError(
            kind="dependency",
            code="engine_rejected",
            title="Voice engine rejected the request",
            detail="The voice platform could not complete this operation.",
        )


class RefRewritingEngine(EchoingEngine):
    """Returns a snapshot for a DIFFERENT execution than the one asked for."""

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        snapshot = await super().get_execution(call_id)
        return snapshot.model_copy(update={"engine_call_id": "some-other-execution"})


class UnmappableEngine(EchoingEngine):
    """A snapshot with no agent ref — every reconciled call becomes unmappable."""

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        snapshot = await super().get_execution(call_id)
        return snapshot.model_copy(update={"engine_agent_ref": None})


class NotYetBillableEngine(FakeEngine):
    async def list_executions(self, *, since: datetime) -> ExecutionListing:
        listing = await super().list_executions(since=since)
        return listing.model_copy(
            update={
                "snapshots": [
                    s.model_copy(update={"billable_ready": False}) for s in listing.snapshots
                ]
            }
        )


class TruncatedListingEngine(FakeEngine):
    """An adapter that returns rows it cannot vouch for — what any adapter must do when
    the vendor's response could be page one of several."""

    async def list_executions(self, *, since: datetime) -> ExecutionListing:
        listing = await super().list_executions(since=since)
        return listing.model_copy(
            update={"complete": False, "incomplete_reason": "full_page_suspected"}
        )


class DeadPollerEngine(FakeEngine):
    async def list_executions(self, *, since: datetime) -> ExecutionListing:
        raise ProblemError(
            kind="dependency",
            code="engine_unreachable",
            title="Voice engine unreachable",
            detail="The voice platform did not respond.",
        )


# --- gate 2 -------------------------------------------------------------------


async def test_gate_2_cannot_pass_because_scheduled_at_is_not_in_our_contract() -> None:
    """The headline finding: even with a perfect vendor, gate 2 is NOT RUN as written."""
    engine = EchoingEngine()
    result = await run_gate_2(_ctx(engine, calls_remaining=1, to_e164="+919000000001"))
    assert _check(result, "create_agent").status == "pass"
    assert _check(result, "update_prompt").status == "pass"
    assert _check(result, "start_call").status == "pass"
    assert _check(result, "get_execution").status == "pass"
    assert _check(result, "user_data_round_trip").status == "pass"
    assert _check(result, "scheduled_at").status == "not_run"
    assert result.status == "not_run"
    assert any("scheduled_at" in f for f in result.findings)


async def test_gate_2_reports_the_prompt_as_applied_not_merely_accepted() -> None:
    """The gap this slice closed. `update_agent` returning cleanly says the vendor took
    the write; the read-back says the agent is holding it, and the prompt is where the
    compliance disclosure lives."""
    result = await run_gate_2(_ctx(EchoingEngine(), calls_remaining=1, to_e164="+919000000001"))
    applied = _check(result, "update_prompt_applied")
    assert applied.status == "pass"
    assert "APPLIED" in applied.detail


async def test_gate_2_catches_a_write_the_engine_accepted_and_did_not_apply() -> None:
    """The whole reason the read-back exists: a 2xx on the PUT that changed nothing.

    Without `get_agent` this run scored a green `update_prompt` and stopped there, so a
    vendor that silently dropped every prompt change — including the disclosure line —
    was indistinguishable from one that applied them.
    """
    result = await run_gate_2(
        _ctx(SilentlyDroppedUpdateEngine(), calls_remaining=1, to_e164="+919000000001")
    )
    assert _check(result, "update_prompt").status == "pass"
    applied = _check(result, "update_prompt_applied")
    assert applied.status == "fail"
    assert "ACCEPTED BUT NOT APPLIED" in applied.detail
    assert result.status == "fail"


async def test_gate_2_scores_an_unreadable_prompt_as_not_run_rather_than_applied() -> None:
    """An adapter that cannot find the prompt in the vendor's answer must leave the row
    unrun. Reading `None` as "no marker" would report the honest adapter as a vendor
    failure; reading it as a pass would report a measurement nobody made."""
    result = await run_gate_2(
        _ctx(UnreadablePromptEngine(), calls_remaining=1, to_e164="+919000000001")
    )
    applied = _check(result, "update_prompt_applied")
    assert applied.status == "not_run"
    assert "ACCEPTED only" in applied.detail


async def test_gate_2_does_not_score_an_engine_that_hosts_no_agents_as_a_failure() -> None:
    """D-280. An absent capability is not a vendor defect, and gate 2 must not print one.

    An engine declaring `agent_hosting="external_deployment"` has no create endpoint at
    all — its agents are programs deployed to it from elsewhere — so `create_agent` refuses
    by name before a request is built. Reporting that as a FAILED provisioning gate would
    put a red row in the pilot register describing our vendor as broken, and send an
    operator hunting a 4xx that never happened. `not_run` is the same distinction this file
    already makes for `update_prompt_applied` between an unreadable prompt and a dropped
    one, applied one step earlier.

    A REAL create failure must still be red — asserted below, because a `not_run` that
    swallowed both would be worse than the failure it replaced.
    """
    hosted = _ctx(FakeEngine(), calls_remaining=1, to_e164="+919000000001")
    deployed = _ctx(
        FakeEngine(capabilities=EXTERNAL_DEPLOYMENT_CAPABILITIES),
        calls_remaining=1,
        to_e164="+919000000001",
    )

    result = await run_gate_2(deployed)
    created = _check(result, "create_agent")
    assert created.status == "not_run", (
        "gate 2 scored a platform that does not host agents as a create FAILURE, which "
        "reads in the register as a vendor defect rather than as an inapplicable gate"
    )
    assert "19(a)" in created.detail, "the row does not name the gate that DOES apply"

    # The control: an engine that hosts agents still runs the gate for real.
    assert _check(await run_gate_2(hosted), "create_agent").status == "pass"


async def test_gate_2_reports_a_failed_read_back_without_blaming_the_vendor() -> None:
    """`GET /v2/agent/{id}` is an unverified vendor claim. If it 404s, the finding is
    that our path is wrong — not that the prompt was dropped."""
    result = await run_gate_2(_ctx(NoReadBackEngine(), calls_remaining=1, to_e164="+919000000001"))
    applied = _check(result, "update_prompt_applied")
    assert applied.status == "fail"
    assert "read-back endpoint" in applied.detail
    assert any("UNVERIFIED VENDOR CLAIM" in f for f in result.findings)


async def test_gate_2_reports_number_attachment_as_a_dashboard_step() -> None:
    result = await run_gate_2(_ctx(NoNumberEngine(), calls_remaining=1, to_e164="+919000000001"))
    attach = _check(result, "attach_number")
    assert attach.status == "not_run"
    assert "dashboard" in attach.detail
    assert any("provision_number" in f for f in result.findings)


async def test_gate_2_settles_the_delete_agent_assumption_on_a_throwaway_agent() -> None:
    """The gate that makes `delete_agent`'s MARKED ASSUMPTION falsifiable (D-123).

    Both real adapters assume a vendor answers 404 for an id it does not hold and fold
    that into the Protocol's idempotent success. Nothing published says so. This is where
    that gets measured — and it must not touch the gate's own agent, whose executions the
    vendor's delete would destroy along with the re-run procedure gate 2 documents.
    """
    engine = EchoingEngine()
    result = await run_gate_2(_ctx(engine, calls_remaining=1, to_e164="+919000000001"))
    assert _check(result, "delete_agent").status == "pass"
    assert _check(result, "delete_agent_removed").status == "pass"
    assert _check(result, "delete_agent_is_idempotent").status == "pass"
    # THE GATE'S OWN AGENT SURVIVED. `get_execution` and the `user_data` round trip read
    # against it, and gate 2 tells an operator to re-run once the execution is billable.
    started = _check(result, "start_call")
    assert started.status == "pass"


async def test_gate_2_reports_a_vendor_whose_repeat_delete_refuses() -> None:
    """The falsifier, in the shape the pilot would actually meet it: the first delete
    lands and the second is refused. That is the adapter's assumption being wrong, not the
    vendor being broken, and the finding has to say which."""

    class RefusesRepeatDeleteEngine(EchoingEngine):
        def __init__(self) -> None:
            super().__init__()
            self._deleted: set[str] = set()

        async def delete_agent(self, ref: str) -> None:
            if ref in self._deleted:
                raise ProblemError(
                    kind="dependency",
                    code="engine_rejected",
                    title="Voice engine rejected the request",
                    detail="The voice platform could not complete this operation.",
                )
            self._deleted.add(ref)
            await super().delete_agent(ref)

    result = await run_gate_2(
        _ctx(RefusesRepeatDeleteEngine(), calls_remaining=1, to_e164="+919000000001")
    )
    assert _check(result, "delete_agent").status == "pass"
    idempotent = _check(result, "delete_agent_is_idempotent")
    assert idempotent.status == "fail"
    assert "absent_is_success" in idempotent.detail, (
        "the failure must name the branch to narrow, or it is a red row with no next step"
    )
    assert result.status == "fail"


async def test_gate_2_says_the_agent_was_not_deleted_when_the_delete_is_refused() -> None:
    """A delete that failed leaves an object the pilot account is billed for, and the one
    thing the operator needs is to be told so — the same reason `_reclaim_orphan` still
    logs the ref when its own delete fails."""

    class UndeletableEngine(EchoingEngine):
        async def delete_agent(self, ref: str) -> None:
            raise ProblemError(
                kind="dependency",
                code="engine_rejected",
                title="Voice engine rejected the request",
                detail="The voice platform could not complete this operation.",
            )

    result = await run_gate_2(_ctx(UndeletableEngine(), calls_remaining=1, to_e164="+919000000001"))
    deleted = _check(result, "delete_agent")
    assert deleted.status == "fail"
    assert "THE AGENT WAS NOT DELETED" in deleted.detail
    assert "_reclaim_orphan" in deleted.detail


async def test_gate_2_dry_run_places_no_call() -> None:
    ctx = _ctx(EchoingEngine(), calls_remaining=0, to_e164="+919000000001")
    result = await run_gate_2(ctx)
    assert _check(result, "start_call").status == "not_run"
    assert "dry run" in _check(result, "start_call").detail
    assert ctx.created_executions == []


async def test_gate_2_fails_loudly_when_the_agent_cannot_be_created() -> None:
    result = await run_gate_2(_ctx(BrokenAgentEngine(), calls_remaining=1, to_e164="+91900000001"))
    assert result.status == "fail"
    assert _check(result, "create_agent").status == "fail"


async def test_gate_2_fails_when_user_data_never_reaches_the_prompt() -> None:
    """The shipped `fake` does not echo `user_data`, so this is also the honest answer
    for a vendor that silently drops it — the failure that breaks every D-21 callback."""
    result = await run_gate_2(_ctx(FakeEngine(), calls_remaining=1, to_e164="+919000000001"))
    round_trip = _check(result, "user_data_round_trip")
    assert round_trip.status == "fail"
    assert result.status == "fail"


async def test_gate_2_does_not_accept_the_caller_saying_the_nonce() -> None:
    result = await run_gate_2(_ctx(CallerEchoEngine(), calls_remaining=1, to_e164="+919000000001"))
    assert _check(result, "user_data_round_trip").status == "fail"


async def test_gate_2_fails_when_the_snapshot_names_another_execution() -> None:
    result = await run_gate_2(
        _ctx(RefRewritingEngine(), calls_remaining=1, to_e164="+919000000001")
    )
    assert _check(result, "get_execution").status == "fail"


async def test_gate_2_fails_when_a_snapshot_cannot_be_mapped_to_a_tenant() -> None:
    result = await run_gate_2(_ctx(UnmappableEngine(), calls_remaining=1, to_e164="+919000000001"))
    fetched = _check(result, "get_execution")
    assert fetched.status == "fail"
    assert "engine_agent_ref" in fetched.detail


async def test_gate_2_never_writes_the_destination_number_anywhere() -> None:
    """Layer one of hard rule 6: the gate does not produce PII, so the scrubber has
    nothing to catch. Asserted on the RAW result, before any scrubbing runs."""
    number = "+919876543210"
    result = await run_gate_2(_ctx(EchoingEngine(), calls_remaining=1, to_e164=number))
    serialized = repr(result.as_dict())
    assert number not in serialized
    assert "9876543210" not in serialized


# --- gate 1 -------------------------------------------------------------------


def _delivery(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "exec-1",
        "status": "completed",
        "agent_id": "agent-1",
        "direction": "inbound",
        "from_number": "+911140000000",
        "to_number": "+919876543210",
        "recording_url": "https://fake-engine.local/recordings/exec-1.wav",
    }
    payload.update(overrides)
    return payload


def _seeded(engine: FakeEngine, call_id: str = "exec-1") -> FakeEngine:
    engine.seed_inbound_call(
        call_id=call_id,
        agent_ref="agent-1",
        from_e164="+911140000000",
        to_e164="+919876543210",
    )
    return engine


async def test_gate_1_passes_when_the_hint_agrees_with_the_truth() -> None:
    engine = _seeded(SourceIpEngine())
    result = await run_gate_1(_ctx(engine, captured_webhooks=[_delivery()]))
    assert _check(result, "accepts_documented_egress").status == "pass"
    assert _check(result, "rejects_other_sources").status == "pass"
    assert _check(result, "payload_matches_get_execution").status == "pass"
    assert _check(result, "execution_id_dedupe").status == "pass"
    assert result.status == "pass"


async def test_gate_1_reports_a_mismatch_as_a_result_and_names_no_numbers() -> None:
    """D-31 makes the poller the guarantee of record because the webhook is a hint. This
    is the one moment we learn whether the hint agrees with the truth at all — and the
    finding is the FIELD NAME, never the two values."""
    engine = _seeded(SourceIpEngine())
    result = await run_gate_1(
        _ctx(engine, captured_webhooks=[_delivery(to_number="+919111111111")])
    )
    mismatch = _check(result, "payload_matches_get_execution")
    assert mismatch.status == "fail"
    assert "to_e164" in mismatch.detail
    assert "9111111111" not in repr(result.as_dict())
    assert result.status == "fail"


async def test_gate_1_catches_an_allowlist_that_accepts_everyone() -> None:
    engine = _seeded(OpenAllowlistEngine())
    result = await run_gate_1(_ctx(engine, captured_webhooks=[_delivery()]))
    rejected = _check(result, "rejects_other_sources")
    assert rejected.status == "fail"
    assert result.status == "fail"


async def test_gate_1_does_not_score_an_engine_that_verifies_nothing() -> None:
    """`fake` accepts every source by design. Scoring that acceptance would report a
    green source-IP control that does not exist — `method` is in the contract so this
    is decidable rather than guessed."""
    engine = _seeded(FakeEngine())
    result = await run_gate_1(_ctx(engine, captured_webhooks=[_delivery()]))
    assert _check(result, "accepts_documented_egress").status == "not_run"
    assert _check(result, "rejects_other_sources").status == "not_run"
    # The payload comparison is engine-independent and still runs.
    assert _check(result, "payload_matches_get_execution").status == "pass"
    assert result.status == "not_run"


async def test_gate_1_without_captures_is_not_run_not_pass() -> None:
    result = await run_gate_1(_ctx(_seeded(SourceIpEngine())))
    assert _check(result, "payload_matches_get_execution").status == "not_run"
    assert _check(result, "execution_id_dedupe").status == "not_run"
    assert result.status == "not_run"


async def test_gate_1_refuses_to_key_a_delivery_with_no_execution_id() -> None:
    engine = _seeded(SourceIpEngine())
    result = await run_gate_1(_ctx(engine, captured_webhooks=[_delivery(), {"status": "queued"}]))
    dedupe = _check(result, "execution_id_dedupe")
    assert dedupe.status == "fail"
    assert dedupe.measurements["unkeyable"] == 1


async def test_gate_1_counts_repeat_deliveries_of_one_transition() -> None:
    """TRD §5 says at-most-once. A repeat is not a failure of dedupe — it is evidence
    against a documented claim, and the finding says so."""
    engine = _seeded(SourceIpEngine())
    result = await run_gate_1(_ctx(engine, captured_webhooks=[_delivery(), _delivery()]))
    dedupe = _check(result, "execution_id_dedupe")
    assert dedupe.status == "pass"
    assert dedupe.measurements["deliveries"] == 2
    assert dedupe.measurements["distinct_transitions"] == 1
    assert dedupe.measurements["repeat_deliveries"] == 1
    assert any("at-most-once" in f for f in result.findings)


def test_the_dedupe_key_separates_transitions_of_one_execution() -> None:
    """Keying on the execution id alone swallowed `completed` — the only transition that
    carries cost, recording and transcript. The receiver keys on the pair; so does this."""
    engine = FakeEngine()
    queued = engine.parse_webhook(_delivery(status="queued"))
    completed = engine.parse_webhook(_delivery(status="completed"))
    from scripts.pilot.gates_api import dedupe_key

    assert dedupe_key(queued) != dedupe_key(completed)
    assert dedupe_key(completed) == dedupe_key(engine.parse_webhook(_delivery()))


def test_fields_absent_on_both_sides_agree() -> None:
    engine = FakeEngine()
    event = engine.parse_webhook({"id": "x", "status": "queued"})
    snapshot = ExecutionSnapshot(
        engine_call_id="x",
        status="queued",
        raw_status="queued",
        terminal=False,
        billable_ready=False,
        direction="outbound",
    )
    assert compare_delivery(event, snapshot) == []


# --- gate 6 -------------------------------------------------------------------


async def test_gate_6_proves_the_poller_recovers_every_missed_execution() -> None:
    engine = FakeEngine()
    _seeded(engine, "exec-a")
    _seeded(engine, "exec-b")
    result = await run_gate_6(
        _ctx(
            engine,
            missed_execution_ids=["exec-a", "exec-b"],
            attestations={
                "gate6.call_continued": "yes",
                "gate6.retries_observed": "0",
                # The operator's own count from the dashboard. Without it the pagination
                # row is NOT RUN (see the next test) and the gate cannot report a pass:
                # our listing cannot testify about what it left out.
                "gate6.executions_in_window": "2",
            },
            since=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    assert _check(result, "poller_lists_missed_executions").status == "pass"
    assert _check(result, "poller_recovers_billable_data").status == "pass"
    assert _check(result, "call_continues_without_receiver").status == "pass"
    assert _check(result, "no_retry_as_documented").status == "pass"
    assert _check(result, "listing_covers_the_whole_window").status == "pass"
    assert result.status == "pass"


async def test_gate_6_will_not_call_pagination_verified_on_our_own_word() -> None:
    """`ExecutionListing.complete` is OUR adapter's verdict, and on a pilot-sized window
    it is trivially true — the listing holds two executions and no plausible page size is
    anywhere near. Scoring that as a pass would be the harness agreeing with itself, the
    same mistake gate 7's currency row was rewritten to stop making. It is NOT RUN, and
    the finding says exactly which number settles it."""
    engine = FakeEngine()
    _seeded(engine, "exec-a")
    result = await run_gate_6(
        _ctx(
            engine,
            missed_execution_ids=["exec-a"],
            since=datetime.now(UTC) - timedelta(hours=1),
        )
    )

    assert _check(result, "listing_covers_the_whole_window").status == "not_run"
    assert any("gate6.executions_in_window" in f for f in result.findings)


async def test_gate_6_fails_when_the_dashboard_holds_more_executions_than_we_listed() -> None:
    """The only independent check that exists. If Bolna's account shows nine executions
    in the window and List-Executions handed us one, the guarantee of record has been
    reading a prefix of the truth and nothing inside our process could have noticed."""
    engine = FakeEngine()
    _seeded(engine, "exec-a")
    result = await run_gate_6(
        _ctx(
            engine,
            missed_execution_ids=["exec-a"],
            attestations={"gate6.executions_in_window": "9"},
            since=datetime.now(UTC) - timedelta(hours=1),
        )
    )

    listing_check = _check(result, "listing_covers_the_whole_window")
    assert listing_check.status == "fail"
    assert listing_check.measurements["executions_expected"] == 9
    assert result.status == "fail"


async def test_gate_6_fails_when_the_adapter_cannot_vouch_for_the_listing() -> None:
    """The adapter's own alarm, scored. A listing it will not vouch for means executions
    may lie beyond the part we read — and those have no webhook (at-most-once, D-31), no
    repair and no trace anywhere."""
    engine = TruncatedListingEngine()
    _seeded(engine, "exec-a")
    result = await run_gate_6(
        _ctx(
            engine,
            missed_execution_ids=["exec-a"],
            since=datetime.now(UTC) - timedelta(hours=1),
        )
    )

    assert _check(result, "listing_covers_the_whole_window").status == "fail"
    assert any("PAGINATION IS REAL OR CANNOT BE RULED OUT" in f for f in result.findings)


async def test_gate_6_fails_when_the_poller_cannot_see_a_lost_execution() -> None:
    """The guarantee of record failing is the worst result in the whole scorecard: a
    call that is simply gone — no lead, no usage event, no recording."""
    engine = FakeEngine()
    _seeded(engine, "exec-a")
    result = await run_gate_6(
        _ctx(
            engine,
            missed_execution_ids=["exec-a", "exec-never-listed"],
            since=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    listed = _check(result, "poller_lists_missed_executions")
    assert listed.status == "fail"
    assert listed.measurements["recovered"] == 1
    # Payload completeness is unjudgeable when the execution is missing entirely.
    assert _check(result, "poller_recovers_billable_data").status == "not_run"
    assert result.status == "fail"


async def test_gate_6_flags_a_recovery_that_carries_no_billable_data() -> None:
    engine = NotYetBillableEngine()
    _seeded(engine, "exec-a")
    result = await run_gate_6(
        _ctx(
            engine,
            missed_execution_ids=["exec-a"],
            since=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    assert _check(result, "poller_lists_missed_executions").status == "pass"
    assert _check(result, "poller_recovers_billable_data").status == "fail"


async def test_gate_6_fails_when_the_poller_itself_is_unreachable() -> None:
    engine = DeadPollerEngine()
    _seeded(engine, "exec-a")
    result = await run_gate_6(
        _ctx(engine, missed_execution_ids=["exec-a"], since=datetime.now(UTC) - timedelta(hours=1))
    )
    assert _check(result, "poller_lists_missed_executions").status == "fail"
    assert result.status == "fail"


async def test_gate_6_treats_an_unexpected_retry_as_a_contradicted_document() -> None:
    engine = FakeEngine()
    _seeded(engine, "exec-a")
    result = await run_gate_6(
        _ctx(
            engine,
            missed_execution_ids=["exec-a"],
            attestations={"gate6.call_continued": "yes", "gate6.retries_observed": "3"},
            since=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    retry = _check(result, "no_retry_as_documented")
    assert retry.status == "fail"
    assert retry.measurements["retries_observed"] == 3
    assert any("TRD §5 CONTRADICTED" in f for f in result.findings)


async def test_gate_6_without_attestations_is_not_run_not_pass() -> None:
    engine = FakeEngine()
    _seeded(engine, "exec-a")
    result = await run_gate_6(
        _ctx(engine, missed_execution_ids=["exec-a"], since=datetime.now(UTC) - timedelta(hours=1))
    )
    assert _check(result, "call_continues_without_receiver").status == "not_run"
    assert _check(result, "no_retry_as_documented").status == "not_run"
    assert result.status == "not_run"


async def test_gate_6_records_a_dropped_call_as_a_failure() -> None:
    engine = FakeEngine()
    _seeded(engine, "exec-a")
    result = await run_gate_6(
        _ctx(
            engine,
            missed_execution_ids=["exec-a"],
            attestations={"gate6.call_continued": "no", "gate6.retries_observed": "0"},
            since=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    continued = _check(result, "call_continues_without_receiver")
    assert continued.status == "fail"
    assert continued.attested is True


async def test_gate_6_uses_the_executions_gate_2_created() -> None:
    """The two gates share one run: the executions gate 2 placed are the ones whose
    webhooks gate 6 drops, so an operator does not have to copy ids by hand."""
    engine = EchoingEngine()
    ctx = _ctx(
        engine,
        calls_remaining=1,
        to_e164="+919000000001",
        since=datetime.now(UTC) - timedelta(hours=1),
    )
    await run_gate_2(ctx)
    assert ctx.created_executions
    result = await run_gate_6(ctx)
    assert _check(result, "poller_lists_missed_executions").status == "pass"


async def test_a_bad_attestation_value_is_not_silently_treated_as_no() -> None:
    engine = FakeEngine()
    _seeded(engine, "exec-a")
    result = await run_gate_6(
        _ctx(
            engine,
            missed_execution_ids=["exec-a"],
            attestations={"gate6.retries_observed": "none"},
            since=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    assert _check(result, "no_retry_as_documented").status == "not_run"


def test_start_outbound_call_still_has_no_scheduled_at_parameter() -> None:
    """The finding, pinned. If the contract grows `scheduled_at`, this test fails and
    whoever added it is told to promote gate 2's sub-check from NOT RUN to a real check
    — which is the only way that stops being a permanent hole in the scorecard."""
    import inspect

    from calevate_shared.engine import VoiceEngine

    signature = inspect.signature(VoiceEngine.start_outbound_call)
    assert set(signature.parameters) == {"self", "ref", "to", "ctx"}
    assert "scheduled_at" not in signature.parameters


def test_the_context_carries_no_way_to_find_a_number_it_was_not_given() -> None:
    ctx = GateContext(engine=FakeEngine(), settings=_settings())
    assert ctx.to_e164 is None
    assert not hasattr(ctx, "session")
    assert not hasattr(ctx, "tenant_id")
