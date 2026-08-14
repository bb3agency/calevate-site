"""OPERATIONS §2 gates 1, 2 and 6 — the API-executable trust gates, as code.

    uv run python -m scripts.pilot run --gates 1,2,6

These three are the gates that decide whether the machinery underneath the whole
product is real: can we drive Bolna entirely through our own adapter (2), can we trust
what arrives at our webhook (1), and when a delivery is lost — which, at an
at-most-once vendor, is a matter of when and not if — does the poller that D-31 calls
the *guarantee of record* actually recover it (6).

EVERYTHING RUNS THROUGH THE `VoiceEngine` ADAPTER, NEVER RAW HTTP.
Hard rule 2 is the stated reason and it is sufficient on its own, but there is a second
reason that matters more here: a pilot that curls `api.bolna.ai` verifies Bolna. It does
not verify the thing we will actually ship a client on, which is `apps/api/engine/
bolna.py` plus every hand-maintained field name in it. A green scorecard produced by
curl would tell us the vendor works and tell us nothing about whether we can talk to it.
Where a gate is genuinely about a RAW payload shape — capturing `latency_data`, pinning
the `rag_id` row shape — that is the fixture-recorder's job, and this module reports it
as a finding rather than reaching past the adapter itself.

WHAT THIS MODULE DELIBERATELY DOES NOT DO: score the vendor for something OUR code
cannot ask. Several sub-checks below come back `not_run` with a finding naming the gap
in our `VoiceEngine` contract. That is the most valuable output this slice produces —
`scheduled_at` and number attachment are in the gate's pass criteria and are not in our
adapter, and learning that from a script now is worth considerably more than learning
it from a founder holding a phone in three weeks' time.

Hard rule 6 governs every string that leaves here: field NAMES, execution ids and
counts. When the webhook and Get Execution disagree about `to_e164`, the finding is
that they disagree about `to_e164` — the two numbers are not evidence, they are a leak.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from apps.api.core.errors import ProblemError
from calevate_shared.config import Settings
from calevate_shared.engine import (
    AgentConfig,
    CallContext,
    ExecutionListing,
    ExecutionSnapshot,
    ModelConfig,
    NumberSpec,
    VoiceEngine,
)
from calevate_shared.events import CallEvent

from scripts.pilot.results import GateRun, SubCheck, failed, not_run, passed

# Bolna's documented egress (TRD §5, D-31). Written here as the value gate 1 TESTS
# rather than imported from the adapter on purpose: importing the constant would make
# the check tautological — "does the adapter accept the address the adapter allows" is
# a question with only one answer. The gate's real subject is whether deliveries in the
# wild come from THIS address, which is a fact about the vendor.
DOCUMENTED_EGRESS_IP = "13.203.39.153"

# An address that must never be accepted. RFC 5737 TEST-NET-1 — reserved for
# documentation, routable by nobody, so it can never collide with a real egress the
# vendor renumbers into.
HOSTILE_SOURCE_IP = "192.0.2.1"

#: The fields a webhook delivery and `GET /executions/{id}` both claim to carry, and
#: which gate 1 compares. Nothing derived and nothing we compute — comparing our own
#: arithmetic against itself would agree perfectly and prove nothing.
COMPARED_FIELDS: tuple[str, ...] = (
    "status",
    "raw_status",
    "direction",
    "from_e164",
    "to_e164",
    "recording_url",
)

#: The attestation vocabulary. A human observes these; the harness cannot. Fixed, so a
#: typo is a CLI error rather than a silently ignored claim.
ATTESTABLE: dict[str, str] = {
    "gate6.call_continued": "yes|no — the call kept running after the receiver was killed",
    "gate6.retries_observed": "integer — deliveries seen for one transition after the "
    "receiver came back up (TRD §5 says this is 0)",
    "gate6.executions_in_window": "integer — how many executions the account really has "
    "since the poller window opened, read off the Bolna dashboard. The ONE independent "
    "check on List-Executions truncation: our own listing cannot reveal what it omitted",
}


@dataclass(slots=True)
class GateContext:
    """Everything a gate may use, and nothing it may reach for on its own.

    THE ABSENCE HERE IS THE DESIGN. There is no database session and no tenant. This
    harness cannot enumerate contacts, cannot read a `leads` row and cannot discover a
    number it was not handed on the command line, so the worst outcome available to it
    is dialling the one number the operator typed. `tests/pilot_safety_test.py` asserts
    that absence against the module source, because it is a property that decays the
    first time somebody needs "just one lookup".
    """

    engine: VoiceEngine
    settings: Settings
    #: How many calls this run may still place. 0 in dry-run, which is the default.
    calls_remaining: int = 0
    #: The single destination, supplied explicitly. NEVER echoed into a result.
    to_e164: str | None = None
    #: Raw delivered webhook bodies the operator saved off the tunnel (gate 1).
    captured_webhooks: Sequence[Mapping[str, Any]] = ()
    #: Execution ids whose webhook was deliberately dropped (gate 6).
    missed_execution_ids: Sequence[str] = ()
    #: Human-observed facts, keyed by ATTESTABLE.
    attestations: Mapping[str, str] = field(default_factory=dict)
    #: Executions this run created, so gate 6 can ask the poller about them.
    created_executions: list[str] = field(default_factory=list)
    #: Poller window. Wide enough to cover the whole session, not just this second.
    since: datetime = field(default_factory=lambda: datetime.now(UTC) - timedelta(hours=6))

    def spend_a_call(self) -> bool:
        """Take one call from the budget, or refuse. The cap is enforced HERE, at the
        only place a call can be placed, rather than by the caller counting — a budget
        checked by whoever remembers to check it is not a budget."""
        if self.calls_remaining <= 0:
            return False
        self.calls_remaining -= 1
        return True


def _engine_error(exc: BaseException) -> str:
    """A failure string that is safe to commit. `ProblemError.detail` is user-safe by
    construction (`errors.py`); anything else contributes only its type name, because an
    arbitrary exception's `str()` on this path may well be an httpx object carrying the
    request URL and its query string."""
    if isinstance(exc, ProblemError):
        return f"{exc.code}: {exc.detail}"
    return f"unexpected {type(exc).__name__}"


# --- gate 2: full API provisioning -------------------------------------------


def _pilot_agent_config(settings: Settings, *, nonce: str, prompt_marker: str) -> AgentConfig:
    """The agent gate 2 creates. Deliberately a REAL config, not a minimal one.

    A stripped-down agent would provision fine and prove nothing: the thing gate 2 is
    actually asking is whether the object our `_agent_body` builds — BYOK model slots,
    the prepended disclosure line, the webhook url — is one Bolna accepts. So it carries
    the same shape a client's agent carries, with the models named from D-36's canonical
    stack.
    """
    return AgentConfig(
        tenant_id=f"pilot-{nonce}",
        agent_id=f"pilot-agent-{nonce}",
        name=f"calevate-pilot-{nonce}",
        direction="outbound",
        language_primary="te-IN",
        # Hard rule 5: never None, never empty — and the pilot agent is a real agent
        # that will really dial a real telephone, so this is not decoration.
        disclosure_line=("Namaskaram, idi Calevate pilot AI assistant. Ee call record avutundi."),
        system_prompt=(
            f"You are a pilot test agent. {prompt_marker} "
            "When the caller speaks, greet them and read back the context variable "
            "`pilot_nonce` exactly as given, then end the call."
        ),
        models=ModelConfig(
            stt_provider="sarvam",
            stt_model="saaras:v2.5",
            llm_model="sarvam-m",
            tts_provider="sarvam",
            tts_voice="bulbul:v3",
        ),
        webhook_url=f"{settings.webhook_base_url.rstrip('/')}/hooks/v1/engine/bolna",
    )


def _round_trip_nonce_seen(snapshot: ExecutionSnapshot, nonce: str) -> bool:
    """Did the per-call context actually reach the prompt?

    The ONLY observable proof available through our contract. There is no `get_agent` on
    `VoiceEngine`, so we cannot read the rendered prompt back; what we can do is put a
    nonce in `CallContext.fields`, instruct the agent to say it, and look for it in an
    AGENT turn of the transcript. Caller turns are excluded deliberately: a human on the
    pilot call reading the nonce aloud would otherwise pass this check for us.
    """
    return any(turn.speaker == "agent" and nonce in turn.text for turn in snapshot.transcript)


async def run_gate_2(ctx: GateContext) -> GateRun:
    """Gate 2 H — full API provisioning, via API only, no dashboard."""
    checks: list[SubCheck] = []
    findings: list[str] = []
    nonce = uuid.uuid4().hex[:12]

    cfg = _pilot_agent_config(ctx.settings, nonce=nonce, prompt_marker="rev-1")
    try:
        ref = await ctx.engine.create_agent(cfg)
    except Exception as exc:
        # Everything downstream needs the agent ref, so this one failure is the gate.
        return GateRun(
            number=2,
            title="Full API provisioning",
            checks=(failed("create_agent", f"create_agent failed: {_engine_error(exc)}"),),
            findings=tuple(findings),
        )
    checks.append(passed("create_agent", f"agent created (ref {ref})"))

    updated = cfg.model_copy(
        update={"system_prompt": cfg.system_prompt.replace("rev-1", f"rev-2 {nonce}")}
    )
    try:
        await ctx.engine.update_agent(ref, updated)
        checks.append(passed("update_prompt", "update_agent accepted a changed system prompt"))
    except Exception as exc:
        checks.append(failed("update_prompt", f"update_agent failed: {_engine_error(exc)}"))
    # Accepted ≠ applied, and our contract cannot tell the difference. This sub-check
    # therefore scores the vendor ACCEPTING the write, and nothing else — "we wrote it
    # and assumed it stuck" is exactly the class of claim a pilot exists to replace with
    # evidence, so it is written down here rather than left implied by a green tick.
    findings.append(
        "ADAPTER GAP — NO AGENT READ-BACK. `VoiceEngine` carries `create_agent` and "
        "`update_agent` and nothing that reads an agent's current config, so gate 2's "
        "'update prompt' step is confirmed only as ACCEPTED (the vendor took the PUT), "
        "never as APPLIED. The only end-to-end proof available through this contract is "
        "indirect: the prompt's effect on a live call, which is what the `user_data` "
        "round-trip check below actually measures. The same missing method is what makes "
        "D-41's second question unanswerable — does `DELETE /knowledgebase/{rag_id}` "
        "clear the agent's reference, or does a dangling `rag_id` remain? One `get_agent` "
        "would settle both, and it is deliberately NOT being added blind: its endpoint "
        "shape is a vendor claim, and vendor claims get verified, never assumed."
    )

    try:
        await ctx.engine.provision_number(NumberSpec(series="standard", purpose="pilot"))
        checks.append(passed("attach_number", "provision_number returned a number"))
    except ProblemError as exc:
        if exc.code == "engine_capability_unverified":
            checks.append(
                not_run(
                    "attach_number",
                    "the adapter refuses number provisioning "
                    f"(`{exc.code}`), so this step is a DASHBOARD action — which is "
                    "exactly what gate 2's 'via API only, no dashboard' forbids.",
                )
            )
            findings.append(
                "ADAPTER GAP: `BolnaEngine.provision_number` raises "
                "`engine_capability_unverified` (M1 defers it to the telephony provider), "
                "so gate 2's 'attach number' step cannot be executed through the adapter "
                "at all. The number must be attached by hand in the dashboard before the "
                "run, and gate 2 can never report a full PASS until either the adapter "
                "implements it or OPERATIONS §2 records that this step is out of scope "
                "for an API-only claim."
            )
        else:
            checks.append(failed("attach_number", f"provision_number failed: {_engine_error(exc)}"))
    except Exception as exc:
        checks.append(failed("attach_number", f"provision_number failed: {_engine_error(exc)}"))

    # --- POST /call -----------------------------------------------------------
    handle: str | None = None
    if ctx.to_e164 is None:
        checks.append(
            not_run("start_call", "no destination supplied (--to is required to place a call)")
        )
    elif not ctx.spend_a_call():
        checks.append(
            not_run(
                "start_call",
                "dry run: no call budget remains. Placing a call requires the explicit "
                "opt-in flag and --max-calls.",
            )
        )
    else:
        context = CallContext(
            lead_id=f"pilot-{nonce}",
            context_note="Calevate pilot gate 2 — API provisioning check.",
            fields={"pilot_nonce": nonce},
        )
        try:
            handle = await ctx.engine.start_outbound_call(ref, ctx.to_e164, context)
            ctx.created_executions.append(handle)
            checks.append(passed("start_call", f"POST /call returned execution {handle}"))
        except Exception as exc:
            checks.append(failed("start_call", f"start_outbound_call failed: {_engine_error(exc)}"))

    # --- GET /executions/{id} -------------------------------------------------
    snapshot: ExecutionSnapshot | None = None
    if handle is None:
        checks.append(not_run("get_execution", "no execution was placed, so there is none to read"))
    else:
        try:
            snapshot = await ctx.engine.get_execution(handle)
        except Exception as exc:
            checks.append(failed("get_execution", f"get_execution failed: {_engine_error(exc)}"))
        else:
            if snapshot.engine_call_id != handle:
                checks.append(
                    failed(
                        "get_execution",
                        "the snapshot's engine_call_id does not match the execution id "
                        "POST /call returned — every id we store would address the wrong call",
                    )
                )
            elif snapshot.engine_agent_ref is None:
                # Not cosmetic: the poller has no webhook to read the agent from, so a
                # snapshot without it makes every repaired call unmappable to a tenant.
                checks.append(
                    failed(
                        "get_execution",
                        "the snapshot carries no engine_agent_ref, so a reconciled call "
                        "cannot be mapped to a tenant (see ExecutionSnapshot's contract)",
                    )
                )
            else:
                checks.append(
                    passed(
                        "get_execution",
                        f"snapshot read back for {handle}",
                        raw_status=snapshot.raw_status,
                        terminal=int(snapshot.terminal),
                        billable_ready=int(snapshot.billable_ready),
                    )
                )

    # --- user_data round-trip -------------------------------------------------
    if snapshot is None:
        checks.append(
            not_run("user_data_round_trip", "no execution snapshot to look for the nonce in")
        )
    elif not snapshot.transcript:
        checks.append(
            not_run(
                "user_data_round_trip",
                "the snapshot carries no transcript yet — cost, recording and transcript "
                "populate only at `completed` (~2-3 min after disconnect). Re-run this "
                "gate against the same execution once it is billable_ready.",
            )
        )
    elif _round_trip_nonce_seen(snapshot, nonce):
        checks.append(
            passed("user_data_round_trip", "the CallContext nonce was spoken back by the agent")
        )
    else:
        checks.append(
            failed(
                "user_data_round_trip",
                "the CallContext nonce never appears in an agent turn — `user_data` did "
                "not reach the prompt, which breaks every lead-callback flow (D-21)",
            )
        )

    # --- scheduled_at ---------------------------------------------------------
    checks.append(
        not_run(
            "scheduled_at",
            "not expressible through our contract: `VoiceEngine.start_outbound_call` "
            "takes (ref, to, ctx) and the Bolna adapter's POST /call body carries no "
            "`scheduled_at`. Nothing this harness can call would exercise it.",
        )
    )
    findings.append(
        "ADAPTER GAP: `scheduled_at` is named in gate 2's pass criteria and in TRD §5 "
        "('scheduled_at ISO-8601+tz built in'), but neither `VoiceEngine.start_outbound_"
        "call` nor `BolnaEngine`'s POST /call body has any parameter for it. Gate 2 "
        "cannot pass as written until the contract grows one — and the campaign "
        "dispatcher is the caller that will want it."
    )

    return GateRun(
        number=2,
        title="Full API provisioning",
        checks=tuple(checks),
        findings=tuple(findings),
    )


# --- gate 1: webhook trust ----------------------------------------------------


def dedupe_key(event: CallEvent) -> str:
    """The key the receiver actually dedupes on.

    Mirrors `webhook_routes._claim_and_enqueue`'s `f"{execution_id}:{raw_status}"`, and
    the mirroring is the point: gate 1 asks whether the VENDOR's deliveries are
    dedupable under the rule our receiver already uses, not under a nicer rule invented
    for the pilot. The status half is load-bearing — Bolna fires one delivery per
    transition with the same execution id, so keying on the id alone would swallow
    `completed`, the only transition that carries cost, recording and transcript.
    """
    return f"{event.call_id}:{event.raw_status or 'unknown'}"


def compare_delivery(event: CallEvent, snapshot: ExecutionSnapshot) -> list[str]:
    """Field NAMES on which the webhook hint and the authenticated read disagree.

    Values are never returned. Two of these fields are phone numbers and one is a
    recording URL; a mismatch report that quoted them would put a caller's number into
    a committed evidence file, which is the exact thing hard rule 6 forbids and the
    exact thing an evidence artefact makes permanent.

    A field absent on BOTH sides agrees. That is not leniency: the webhook is documented
    to omit cost and recording before `completed`, so "both say nothing yet" is the
    expected healthy state and scoring it as a mismatch would make the gate red on every
    non-terminal transition.
    """
    differing: list[str] = []
    for name in COMPARED_FIELDS:
        left = getattr(event, name, None)
        right = getattr(snapshot, name, None)
        if left is None and right is None:
            continue
        if left != right:
            differing.append(name)
    return differing


async def run_gate_1(ctx: GateContext) -> GateRun:
    """Gate 1 H — webhook trust for an engine that signs nothing."""
    checks: list[SubCheck] = []
    findings: list[str] = []

    verdict = ctx.engine.verify_webhook({}, b"{}", DOCUMENTED_EGRESS_IP)
    if verdict.method == "none":
        # Not a failure — a statement about which engine is loaded. The `fake` adapter
        # accepts everything by design (that is how the pipeline runs offline), so
        # scoring its acceptance would report a green source-IP control that does not
        # exist. `method` is in the contract precisely so this is decidable.
        reason = (
            f"engine `{ctx.engine.name}` reports verification method `none` — it "
            "performs no source check, so there is nothing here to measure. Run with "
            "ENGINE=bolna."
        )
        checks.append(not_run("accepts_documented_egress", reason))
        checks.append(not_run("rejects_other_sources", reason))
    else:
        if verdict.ok:
            checks.append(
                passed(
                    "accepts_documented_egress",
                    f"a delivery from {DOCUMENTED_EGRESS_IP} is accepted "
                    f"(method `{verdict.method}`)",
                )
            )
        else:
            checks.append(
                failed(
                    "accepts_documented_egress",
                    "the documented egress address is NOT accepted — every real delivery "
                    "would 401 and every call would wait for the 10-minute poller",
                )
            )
        hostile = ctx.engine.verify_webhook({}, b"{}", HOSTILE_SOURCE_IP)
        if hostile.ok:
            checks.append(
                failed(
                    "rejects_other_sources",
                    "a delivery from a reserved documentation address was ACCEPTED — the "
                    "allowlist is not an allowlist, and an unsigned endpoint has no other "
                    "control",
                )
            )
        else:
            checks.append(passed("rejects_other_sources", "a non-allowlisted source is rejected"))
        findings.append(
            "ONE ALLOWLIST, TWO READERS — now genuinely one. `BolnaEngine.verify_webhook` "
            "and the receiver that actually answers deliveries "
            "(`apps/voice-runtime/engine_intake.verify_source`) both resolve "
            "`BOLNA_WEBHOOK_SOURCE_IPS` through `calevate_shared.config.bolna_source_ips`, "
            "so what this harness observes of the adapter is what the door does. (They "
            "used to be a module constant and a setting, agreeing only until an operator "
            "took the documented recovery path; `tests/engine_audit_test.py` §2e now fails "
            "if they part again.) STILL OUT OF SCOPE HERE: the deployed edge. nginx holds "
            "its own copy of this address in `/etc/nginx/snippets/` on the VPS — outside "
            "this repo, so nothing mechanical keeps it aligned — and proving it rejects a "
            "non-allowlisted host needs an HTTP POST from one, which is the human step in "
            "the preflight list."
        )

    # --- the load-bearing check: does the hint match the truth? ---------------
    if not ctx.captured_webhooks:
        checks.append(
            not_run(
                "payload_matches_get_execution",
                "no captured deliveries. Save the raw bodies your tunnel received and "
                "pass them with --webhook-capture <file.json> (repeatable).",
            )
        )
        checks.append(
            not_run(
                "execution_id_dedupe",
                "no captured deliveries to key — see --webhook-capture above.",
            )
        )
        return GateRun(
            number=1, title="Webhook trust", checks=tuple(checks), findings=tuple(findings)
        )

    events: list[CallEvent] = []
    unparseable = 0
    for payload in ctx.captured_webhooks:
        try:
            events.append(ctx.engine.parse_webhook(dict(payload)))
        except Exception:
            unparseable += 1

    compared = 0
    mismatched: dict[str, list[str]] = {}
    fetch_failures = 0
    for event in events:
        if not event.call_id:
            continue
        try:
            snapshot = await ctx.engine.get_execution(event.call_id)
        except Exception:
            fetch_failures += 1
            continue
        compared += 1
        differing = compare_delivery(event, snapshot)
        if differing:
            mismatched[event.call_id] = differing

    if compared == 0:
        checks.append(
            not_run(
                "payload_matches_get_execution",
                f"none of the {len(ctx.captured_webhooks)} captured deliveries could be "
                f"compared ({unparseable} unparseable, {fetch_failures} unfetchable)",
            )
        )
    elif mismatched:
        # A MISMATCH IS A RESULT, NOT AN ERROR. D-31 makes the poller the guarantee of
        # record because the webhook is a hint; this is the one moment we get to learn
        # whether the hint is even consistent with the truth. Reporting it as a first-
        # class red result — with the field names — is the whole value of the check.
        fields = sorted({name for names in mismatched.values() for name in names})
        checks.append(
            failed(
                "payload_matches_get_execution",
                "MISMATCH: the delivered payload disagrees with Get Execution on "
                f"{', '.join(fields)} (values withheld — hard rule 6). The webhook is a "
                "hint and the authenticated read is the truth, so this does not break the "
                "pipeline; it does mean any decision made from a hint field in this list "
                "is unsafe.",
                deliveries_compared=compared,
                deliveries_mismatched=len(mismatched),
            )
        )
        findings.append(
            "WEBHOOK/EXECUTION MISMATCH on: "
            + ", ".join(fields)
            + ". Record which transition each delivery was, and re-check TRD §5's claim "
            "that 'polling and webhooks share one shape'."
        )
    else:
        checks.append(
            passed(
                "payload_matches_get_execution",
                "every captured delivery agrees with Get Execution on all compared fields",
                deliveries_compared=compared,
                fields_compared=len(COMPARED_FIELDS),
            )
        )

    keys = [dedupe_key(e) for e in events if e.call_id]
    unkeyable = len(events) - len(keys) + unparseable
    if not keys:
        checks.append(
            not_run(
                "execution_id_dedupe",
                "no captured delivery carried an execution id we could key on",
            )
        )
    elif unkeyable:
        checks.append(
            failed(
                "execution_id_dedupe",
                f"{unkeyable} of {len(ctx.captured_webhooks)} deliveries carry no keyable "
                "execution id. An event we cannot key is an event we cannot dedupe, and "
                "at an at-most-once vendor it is also an event nobody will resend.",
                deliveries=len(ctx.captured_webhooks),
                unkeyable=unkeyable,
            )
        )
    else:
        # Stability is checked by re-parsing: a key that varies between two parses of
        # identical bytes would dedupe nothing at all, and it is exactly the kind of
        # defect (a timestamp or a uuid in the key) that only shows under repetition.
        reparsed = [dedupe_key(ctx.engine.parse_webhook(dict(p))) for p in ctx.captured_webhooks]
        stable = reparsed == [dedupe_key(e) for e in events]
        repeats = len(keys) - len(set(keys))
        if not stable:
            checks.append(
                failed(
                    "execution_id_dedupe",
                    "the dedupe key is not stable across two parses of identical bytes — "
                    "nothing would ever be recognised as a duplicate",
                )
            )
        else:
            checks.append(
                passed(
                    "execution_id_dedupe",
                    "every delivery yields a stable (execution_id, status) key; repeats "
                    "collapse onto an existing key",
                    deliveries=len(keys),
                    distinct_transitions=len(set(keys)),
                    repeat_deliveries=repeats,
                )
            )
            if repeats:
                findings.append(
                    f"{repeats} repeat deliveries of an already-seen transition were "
                    "captured. TRD §5 describes Bolna's delivery as at-most-once with no "
                    "retries; repeats mean either that claim is wrong or something else "
                    "is replaying into our endpoint. Worth chasing before gate 6."
                )

    return GateRun(number=1, title="Webhook trust", checks=tuple(checks), findings=tuple(findings))


# --- gate 6: webhook loss behaviour ------------------------------------------


def _attested_yes(value: str | None) -> bool | None:
    """Tri-state on purpose: True, False, or 'the operator did not say'."""
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("yes", "y", "true", "1"):
        return True
    if lowered in ("no", "n", "false", "0"):
        return False
    return None


def _executions_in_window(ctx: GateContext) -> int | None:
    """The operator's independent count, or None. Never inferred from our own listing."""
    raw = ctx.attestations.get("gate6.executions_in_window")
    if raw is None:
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def _listing_completeness_check(ctx: GateContext, listing: ExecutionListing) -> SubCheck:
    """Did List-Executions cover the whole window — and how would we know?

    WHAT IS NOW MEASURABLE: the adapter reports `ExecutionListing.complete`, so a listing
    it could not vouch for is a FAIL here instead of a silence. It reaches that verdict
    from the payload where the payload says anything (`has_more`, a `total` larger than
    the rows, a `next` it followed) and otherwise from the row count landing exactly on a
    conventional page size.

    WHAT IS STILL AN ASSUMPTION: whether Bolna paginates at all, at what size, and in
    what form. Nothing inside our process can settle that — a listing cannot report what
    it omitted — so the only independent evidence is the operator's own count from the
    dashboard (`--attest gate6.executions_in_window=<n>`). Without it a `complete=True`
    on a quiet pilot window is NOT RUN, not a pass: it would be our own adapter agreeing
    with itself, which is the mistake gate 7's currency row was rewritten to stop making.
    """
    rows = len(listing.snapshots)
    expected = _executions_in_window(ctx)
    measurements: dict[str, Any] = {
        "executions_listed": rows,
        "pages_fetched": listing.pages_fetched,
    }
    if expected is not None:
        measurements["executions_expected"] = expected

    if not listing.complete:
        return failed(
            "listing_covers_the_whole_window",
            f"the adapter could NOT vouch for this listing ({listing.incomplete_reason}). "
            "Under D-31 the poller is the guarantee of record, so an execution beyond the "
            "part we read has no webhook, no repair and no trace anywhere. Capture the "
            "response body and record the page size before the pilot closes.",
            **measurements,
        )
    if expected is not None and expected > rows:
        return failed(
            "listing_covers_the_whole_window",
            f"TRUNCATION CONFIRMED AND UNDETECTED: the dashboard shows {expected} "
            f"executions in this window and List-Executions returned {rows}. Bolna "
            "paginates, our page-size heuristic did not fire on it, and the poller has "
            "been reading a prefix of the truth. Record the exact page size and the "
            "continuation form — this is a code change, not a note.",
            **measurements,
        )
    if expected is not None:
        return passed(
            "listing_covers_the_whole_window",
            f"the operator's own count ({expected}) is covered by the {rows} executions "
            "List-Executions returned, and the adapter saw nothing suggesting another page",
            **measurements,
        )
    return not_run(
        "listing_covers_the_whole_window",
        "the adapter reports the listing as complete, but nothing independent has "
        "confirmed it: a listing cannot report what it left out, and a pilot window is "
        "far too quiet to reach any plausible page size. Count the account's executions "
        "since the window opened on the Bolna dashboard and record it with "
        "--attest gate6.executions_in_window=<n>.",
        **measurements,
    )


def _listing_completeness_findings(ctx: GateContext, listing: ExecutionListing) -> list[str]:
    """The prose an operator acts on, separated from the verdict for the same reason
    gate 7 does it: a check says pass/fail, a finding says what to DO next."""
    rows = len(listing.snapshots)
    expected = _executions_in_window(ctx)
    if not listing.complete or (expected is not None and expected > rows):
        return [
            "PAGINATION IS REAL OR CANNOT BE RULED OUT, AND THE POLLER IS THE GUARANTEE "
            "OF RECORD. Capture one raw `GET /executions` body as a fixture (`scripts/"
            "pilot/record.py --gate 6`), and record three things from it: the number of "
            "rows a saturated request returns (the page size), whether the body carries "
            "any of `next`/`next_page_url`/`has_more`/`total`, and — if it carries a "
            "cursor rather than a link — the exact parameter name that consumes it. "
            "`BolnaEngine._next_link` already follows a self-describing link; a cursor "
            "whose parameter name we would have to guess is deliberately NOT followed, "
            "because a guessed parameter is ignored by the vendor and re-reads page one "
            "forever."
        ]
    if expected is None:
        return [
            "LIST-EXECUTIONS PAGINATION REMAINS AN ASSUMPTION, NOW A DECLARED ONE. The "
            "adapter no longer returns a page as if it were a window: it returns "
            "`ExecutionListing.complete`, and `reconcile_executions` alerts "
            "(`reconciliation_listing_incomplete`) and meters every tick it cannot vouch "
            "for. What is still unverified is the vendor's behaviour itself — Bolna "
            "publishes no OpenAPI spec and no pagination contract, and a pilot window "
            "holds too few executions to reach any page size, so `complete=True` here "
            "means 'nothing in the response suggested otherwise', not 'we saw the whole "
            "window'. Settling it needs exactly one thing this harness cannot fabricate: "
            "the account's own execution count for the same window, from the dashboard, "
            "via --attest gate6.executions_in_window=<n>. Until a saturated listing has "
            "been captured, the page-size heuristic in `bolna._LISTING_PAGE_SIZES` is "
            "the only thing standing between us and a silent gap, and it is a guess about "
            "round numbers, not knowledge."
        ]
    return []


async def run_gate_6(ctx: GateContext) -> GateRun:
    """Gate 6 H — kill the receiver mid-call; prove the poller recovers.

    The four claims are graded very differently and that is deliberate:

    * the call surviving a dead receiver is a HUMAN observation (nothing in-process can
      see it), so it is an attestation and is labelled as one;
    * whether a retry arrives is also human-observed, but its EXPECTED value is written
      down in TRD §5 ('no retry, no timeout, errors swallowed', verified in their OSS
      code), so an observed retry contradicts a documented claim and must be loud;
    * poller recovery is MEASURED here, through `list_executions`, because it is the
      guarantee of record for the entire product and an attestation is not good enough
      for that;
    * whether the listing COVERED the window is measured as far as our side can measure
      it (`ExecutionListing.complete`) and is otherwise NOT RUN. Recovery and coverage
      are different questions: an execution can be recovered perfectly and still sit on
      page one of a listing whose page two we never read, and the calls on page two are
      the ones nothing else will ever mention.
    """
    checks: list[SubCheck] = []
    findings: list[str] = []

    continued = _attested_yes(ctx.attestations.get("gate6.call_continued"))
    if continued is None:
        checks.append(
            not_run(
                "call_continues_without_receiver",
                "not observed. Kill the receiver mid-call, then record what happened with "
                "--attest gate6.call_continued=yes|no.",
            )
        )
    elif continued:
        checks.append(
            SubCheck(
                name="call_continues_without_receiver",
                status="pass",
                detail="operator observed the call continuing after the receiver was killed",
                attested=True,
            )
        )
    else:
        checks.append(
            SubCheck(
                name="call_continues_without_receiver",
                status="fail",
                detail=(
                    "operator observed the call DROPPING when the receiver died — the "
                    "vendor treats our webhook as part of the call path, which makes our "
                    "own deploys audible to callers"
                ),
                attested=True,
            )
        )

    raw_retries = ctx.attestations.get("gate6.retries_observed")
    if raw_retries is None:
        checks.append(
            not_run(
                "no_retry_as_documented",
                "not observed. Count deliveries for one transition after the receiver "
                "restarts and record it with --attest gate6.retries_observed=<n>.",
            )
        )
    else:
        try:
            retries = int(raw_retries.strip())
        except ValueError:
            checks.append(
                not_run(
                    "no_retry_as_documented",
                    f"gate6.retries_observed={raw_retries!r} is not an integer",
                )
            )
        else:
            if retries == 0:
                checks.append(
                    SubCheck(
                        name="no_retry_as_documented",
                        status="pass",
                        detail="no retry arrived, as TRD §5 and their OSS delivery code claim",
                        measurements={"retries_observed": retries},
                        attested=True,
                    )
                )
            else:
                checks.append(
                    SubCheck(
                        name="no_retry_as_documented",
                        status="fail",
                        detail=(
                            "RETRIES ARRIVED. TRD §5 states Bolna delivers at most once with "
                            "no retry; that assumption is wrong and every design resting on "
                            "it needs re-reading"
                        ),
                        measurements={"retries_observed": retries},
                        attested=True,
                    )
                )
                findings.append(
                    f"TRD §5 CONTRADICTED: {retries} retry deliveries observed for a single "
                    "transition. At-most-once is claimed in the doc AND read out of their "
                    "OSS delivery code, so either the code changed or the delivery path is "
                    "not the one we read. Capture the deliveries and update TRD §5 — note "
                    "this makes the receiver's dedupe load-bearing rather than defensive."
                )

    # --- the measured half ----------------------------------------------------
    missed = list(dict.fromkeys([*ctx.missed_execution_ids, *ctx.created_executions]))
    if not missed:
        checks.append(
            not_run(
                "poller_lists_missed_executions",
                "no execution ids to recover. Pass the ids whose webhook you dropped with "
                "--missed-execution <id> (repeatable).",
            )
        )
        checks.append(
            not_run("poller_recovers_billable_data", "no execution ids to recover — see above.")
        )
        checks.append(
            not_run(
                "listing_covers_the_whole_window",
                "the poller listing was never read on this run — see above.",
            )
        )
        return GateRun(
            number=6,
            title="Webhook loss behaviour",
            checks=tuple(checks),
            findings=tuple(findings),
        )

    try:
        listing = await ctx.engine.list_executions(since=ctx.since)
    except Exception as exc:
        checks.append(
            failed(
                "poller_lists_missed_executions",
                f"list_executions failed: {_engine_error(exc)} — the guarantee of record "
                "is unavailable, which is worse than a lost webhook",
            )
        )
        checks.append(
            not_run("poller_recovers_billable_data", "the execution listing could not be read")
        )
        checks.append(
            not_run(
                "listing_covers_the_whole_window",
                "the execution listing could not be read, so its coverage is unknowable",
            )
        )
        return GateRun(
            number=6,
            title="Webhook loss behaviour",
            checks=tuple(checks),
            findings=tuple(findings),
        )

    listed = {s.engine_call_id: s for s in listing.snapshots}
    absent = [eid for eid in missed if eid not in listed]
    if absent:
        checks.append(
            failed(
                "poller_lists_missed_executions",
                f"{len(absent)} of {len(missed)} executions whose webhook was lost do NOT "
                "appear in List-Executions. D-31 makes this poller the guarantee of "
                "record; an execution it cannot see is a call that is gone — no lead, no "
                "usage event, no recording.",
                missed=len(missed),
                recovered=len(missed) - len(absent),
            )
        )
    else:
        checks.append(
            passed(
                "poller_lists_missed_executions",
                "every execution whose webhook was lost appears in List-Executions",
                missed=len(missed),
                recovered=len(missed),
                window_hours=round((datetime.now(UTC) - ctx.since).total_seconds() / 3600, 2),
            )
        )
    checks.append(_listing_completeness_check(ctx, listing))
    findings.extend(_listing_completeness_findings(ctx, listing))

    incomplete = [eid for eid in missed if eid in listed and not listed[eid].billable_ready]
    if absent:
        checks.append(
            not_run(
                "poller_recovers_billable_data",
                "some executions are missing from the listing entirely, so there is nothing "
                "to judge their payload completeness by",
            )
        )
    elif incomplete:
        checks.append(
            failed(
                "poller_recovers_billable_data",
                f"{len(incomplete)} recovered executions are listed but not "
                "billable_ready — cost, recording and transcript are still absent. If this "
                "persists past ~3 minutes the poller recovers the EXISTENCE of a call and "
                "not its content, and the post-call pipeline has nothing to run on.",
                listed=len(missed),
                billable_ready=len(missed) - len(incomplete),
            )
        )
    else:
        checks.append(
            passed(
                "poller_recovers_billable_data",
                "every recovered execution carries billable_ready data (cost, recording, "
                "transcript)",
                listed=len(missed),
                billable_ready=len(missed),
            )
        )

    return GateRun(
        number=6, title="Webhook loss behaviour", checks=tuple(checks), findings=tuple(findings)
    )


#: Gate number → coroutine. The runner reads this rather than a chain of ifs, so a gate
#: this module does not own is absent rather than silently green.
GATES = {1: run_gate_1, 2: run_gate_2, 6: run_gate_6}

__all__ = [
    "ATTESTABLE",
    "COMPARED_FIELDS",
    "DOCUMENTED_EGRESS_IP",
    "GATES",
    "HOSTILE_SOURCE_IP",
    "GateContext",
    "compare_delivery",
    "dedupe_key",
    "run_gate_1",
    "run_gate_2",
    "run_gate_6",
]
