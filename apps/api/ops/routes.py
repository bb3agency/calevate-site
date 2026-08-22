"""Operator endpoints — the big red switch, the outbox DLQ, the audit chain, Calevate's
own DLT telemarketer registration, and the spend-cap recompute.

The DLT registration is a legal fact rather than an operational lever, and it is here
because it has the same SHAPE as the levers: one value, global, true or false for every
tenant at the same instant. SEC-COMP §3's first bullet makes it the company-level campaign
blocker — while it is not `active`, `campaigns.service.launch_blockers` refuses every
tenant's launch with `tm_registration_missing`, however complete that client's own
Principal Entity registration is. A per-tenant copy of it would be N copies of one fact
that eventually disagree, so it lives in `platform_state` beside the halt.

Two properties hold for every route in this file:

1. **Never shed.** `/v1/ops` is in `ALWAYS_ALLOWED_PREFIXES`, so putting the platform
   into `maintenance` does not remove the ability to take it back out.
2. **Step-up confirmation on every WRITE** (BACKEND-PATTERNS §7). Halting all outbound
   calling, recording our telemarketer registration, recomputing a cap and replaying the
   dead-letter queue are actions a stolen session must not be able to perform, so each
   requires a fresh confirmation bound to the specific action. `GET /audit/verify` is the
   one route here without one, because it writes nothing — demanding a confirmation to
   run a read only teaches operators to type past confirmations.

Step-up is a required `X-Confirm-Action` header that must echo the action being taken.

**IT IS NOT THE SECOND FACTOR, AND IT IS NO LONGER STANDING IN FOR ONE.** Admin-realm
MFA is now enforced by the API itself: `core/auth.py::verify_token` refuses any
admin-realm session that never completed its second factor (`mfa_verified_at IS NULL`),
so every route in this file is already behind MFA before its dependency runs. This
header was written as an explicit stopgap for that; the stopgap's occasion has passed
and the header STAYS anyway, because it answers a different question:

* MFA answers **who is holding this session** — proved once, at sign-in, and good for
  the whole life of that session (`authn/sessions.REALM_TIMEOUTS`, SEC-COMP §5). THE
  CONSTANT, NOT A NUMBER: this said "for the next twelve hours", which is not the admin
  realm's window in either half — admin is 30 min idle / 8 h absolute, and twelve hours
  is the CLIENT realm's IDLE window. A restated lifetime on a security surface is the
  count-in-prose defect with a blast radius, and it cited §5 for a figure §5 contradicts.
* the confirmation answers **which act they meant, on which target** — proved per
  request, and unforgeable by anything that merely replays a live session: a tab left
  open on an unlocked laptop, a CSRF-shaped cross-origin POST, an operator one row off
  in a tenant list, or a curl copied from the wrong runbook section. A fully MFA'd
  session is exactly the session all four of those have.

REJECTED: deleting the header and letting MFA cover both. CLAUDE.md forbids two ways of
doing ONE thing, and these are two things — an authentication assertion about a session
and a consent assertion about an action. Removing it would leave the big red switch
reachable by a single POST from any live operator session, which is the property the
header was introduced to remove and which MFA does not restore. The strictly better
version — *reverification*, i.e. requiring the second factor to have been proved
within the last N minutes and binding that proof to the action — is a NAMED follow-up
in OPERATIONS §2, not something silently skipped: it needs a reverification flow in
`apps/web` to raise the prompt, and until that exists gating an incident lever on a
prompt nobody can answer would be a control that gets switched off at 3am.

**Every confirmation on this router is bound to the action AND its target**, which is
what §7 asks for and what the spend-cap recompute has always done (its string carries
the tenant id, so a header an operator sent for one client cannot be replayed against
another). `set_platform` used to be the exception: one string, `set_platform_state`,
covered both releasing a global outbound halt and a routine load-shed tweak, so a
header captured for the Tuesday change satisfied the switch. It now names the exact
transition — `halt_outbound`, `release_outbound`, `set_load_shed:<mode>`, and the two
joined for a request that does both — built in ONE place, `platform_confirmation`,
which the runbooks quote and a test pins.

A confirmation carries a `:<target>` suffix only where the target VARIES: the tenant on
the spend-cap recompute, the mode on the load-shed change, and now the `job` on the
dead-letter replay. `halt_outbound` names an action with exactly one possible target —
the platform — so a suffix there would bind nothing. What every string on this router
does have is uniqueness: no header accepted by one route is accepted by another, which is
what stops a confirmation captured for the smallest action authorising the largest.

That was a BREAKING change to an ops surface and was made deliberately rather than
grandfathered: the old string's whole problem was that it authorised more than the
operator meant, so keeping it accepted "for compatibility" would have kept the hole
open under a different name. Two callers moved with it — the admin console's
`useSetPlatformState` and `runbooks/campaign-stall.md` §1 — and the refusal names the
header to send in its `remediation`, so an operator with an old curl is one paste from
recovering rather than one grep.

Most routes here move ONE global row and take `global_db`. The spend-cap recompute is
the exception: it works on a named tenant's `spend_state`, which is RLS'd, so it names
its tenant in the path and enters that tenant's scope with `tenant_session` — the house
pattern for an admin-realm mutation (`route_shape_test`, `billing/credit_routes.py`).
An untenanted session would see zero rows there and report a cheerful nothing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin.service import tenant_exists
from apps.api.agents.reconciliation import read_engine_drift
from apps.api.billing.caps import read_caps, read_spend_counters, recompute_capped
from apps.api.billing.service import current_billing_month, to_paise
from apps.api.compliance.audit import verify_chain, write_audit
from apps.api.core.alerting import alert
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db, global_db
from apps.api.core.errors import ProblemError
from apps.api.core.loadshed import LoadShedMode, get_platform_status, set_platform_status
from apps.api.core.queue import enqueue
from apps.api.core.rbac import permission_meta
from apps.api.core.stepup import StepUpGate
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.kb.reconciliation import read_kb_drift
from apps.api.ops.engine_latency import (
    DEFAULT_WINDOW_DAYS,
    MAX_WINDOW_DAYS,
    EngineLatencyReport,
    engine_latency_report,
)
from apps.api.ops.service import (
    TmRegistration,
    read_halt_state,
    read_tm_registration,
    set_tm_registration,
)
from apps.api.reliability.service import read_dead_letter_queue, replay_dead_letters

router = APIRouter(prefix="/v1/ops", tags=["ops"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]
# THE TENANT-DIRECTORY SESSION, and the only route in this file that needs one. Every
# other lever here reads platform state; the latency report reads a TENANT-SCOPED table
# across every tenant on purpose — a pilot call placed under one client and its control
# under another must land in the same distribution. `admin_db` takes the admin principal
# as a dependency, so the widened policy is unreachable without a verified admin token.
AdminSession = Annotated[AsyncSession, Depends(admin_db)]

#: The ARQ function name of the recall arm of the big red switch (D-432), registered in
#: `apps/workers/settings.FUNCTIONS` as `recall_queued_dials`.
#:
#: Spelled here rather than imported from `apps/workers.dial_recall`, for
#: `compliance/deletion.DELETION_JOB`'s reason: the API has no business importing a worker
#: module — with its session factory and its sweep SQL — in order to say one name.
#: `scripts/check_job_wiring.py` is what pins the two spellings together, in both
#: directions, and it resolves only same-file constants.
DIAL_RECALL_JOB: Final = "recall_queued_dials"


class TmRegistrationOut(BaseModel):
    """Calevate's own telemarketer registration (SEC-COMP §3, company half).

    `is_live` is computed rather than left to the reader: "is `submitted` good enough"
    is exactly the question a console must not answer for itself, and the launch gate
    and this response must never disagree about it — both read
    `ops.service.TmRegistration.is_live`.
    """

    model_config = ConfigDict(extra="forbid")

    status: str
    tm_id: str | None
    registered_at: datetime | None
    verified_at: datetime | None
    is_live: bool


class DeadLetterJobOut(BaseModel):
    """One `job`'s share of the outbox DLQ.

    COUNTS AND JOB NAMES ONLY (hard rule 6). `outbox_messages.payload` is JSONB holding
    lead fields and phone numbers; `job` is an ARQ job name — a code identifier — and
    nothing derived from a payload reaches this model. See
    `reliability.service.DeadLetterQueue`, which is where that boundary is enforced.
    """

    model_config = ConfigDict(extra="forbid")

    job: str
    depth: int
    oldest_at: datetime


class DeadLetterQueueOut(BaseModel):
    """How much a replay would re-send, published so the confirmation can be informed.

    The console asks an operator to confirm `POST /outbox/replay`, whose effect is real
    HMAC-signed webhooks into clients' own systems for every tenant at once. Until this
    field existed the console said so in its own words: there was no count to show before
    the click, so the operator confirmed a redelivery of unknown size, tenancy and age.

    Three numbers rather than one, because a total does not tell an operator what they are
    about to do: 142 dead letters is a different act depending on whether it is 142 CRM
    webhooks or 142 hot-lead emails, and a different act again depending on whether the
    head of the queue is ten minutes or nine days old.

    **AND `deferred`, WHICH IS NOT A DEAD LETTER.** It rides this model rather than
    getting a field of its own on `PlatformStateOut` because it is only meaningful beside
    `depth`: the two are the outbox's two unhealthy states and an operator reads them as a
    pair. See `reliability.service.DeadLetterQueue.deferred` for what it counts and why
    the console was blind to it.
    """

    model_config = ConfigDict(extra="forbid")

    depth: int
    # Null exactly when `depth` is 0 — see `reliability.service.DeadLetterQueue` on why
    # this is not a sentinel timestamp.
    oldest_at: datetime | None
    # Sums to `depth` BY CONSTRUCTION: both come from one grouped aggregate at one
    # instant, so a dispatcher tick cannot land between a total and its parts.
    by_job: list[DeadLetterJobOut]
    # Messages waiting on a backoff — pending, with a lease into the future. NOT counted
    # in `depth` and NOT replayed by `POST /outbox/replay`, which acts on `failed` rows
    # only: these need nothing from an operator except that they be able to see them.
    # Zero on a healthy idle system; growing during a queue outage, which is the whole
    # window in which the console used to report "no dead letters" and mean it.
    deferred: int


class EngineDriftOut(BaseModel):
    """How far the platform's live agents have drifted from what we published (D-123).

    THE HALF-WIRED-FEATURE GUARD. `sweep_engine_drift` walks live agents through
    `engine_drift_for` every half hour and writes what the engine was observed to be
    holding. A job that writes a state nobody reads is the defect CLAUDE.md names, so the
    state rides the read the ops screen already makes — the same argument, and the same
    route-table argument, that put `outbox_dead_letters` here rather than on an endpoint
    of its own.

    THE ALARM IS `out_of_sync`, and `undetermined` is deliberately NOT folded into it.
    `agents/verification.py`'s whole doctrine is that "the engine is provably running
    something else" and "we could not read the answer" are different facts and only one is
    evidence; a console that added them would report a vendor having a slow afternoon as a
    fleet of agents speaking unapproved scripts, and an operator learns to ignore that
    number within a week.

    COUNTS AND TIMESTAMPS ONLY (hard rule 6). The per-agent sentence lives behind
    `GET /v1/agents/{agent_id}/engine-state`, which is tenant-scoped and permissioned;
    nothing derived from a prompt or a disclosure line reaches this model. See
    `agents/reconciliation.EngineDriftSummary`, which is where that boundary is enforced.
    """

    model_config = ConfigDict(extra="forbid")

    live_agents: int
    # Never swept. A distinct number from `in_sync` for `live_verify_state`'s reason: an
    # agent nobody has looked at must not be counted as one we looked at and liked.
    never_checked: int
    out_of_sync: int
    in_sync: int
    undetermined: int
    # Null exactly when `out_of_sync` is 0. Age is what separates a publish that raced a
    # sweep from a vendor-console edit nobody has noticed for a week.
    oldest_drift_at: datetime | None
    # THE SWEEP'S OWN PULSE, and the field that stops this panel lying by omission. If the
    # cron dies, every count above freezes at its last value and `out_of_sync: 0` reads as
    # "all clear" forever. A `oldest_checked_at` that stops moving is the only thing on
    # this payload that can say "nobody is watching". Null when nothing has been swept.
    oldest_checked_at: datetime | None


class KbDriftOut(BaseModel):
    """How far the KNOWLEDGE on the voice platform has drifted from what we approved
    (D-158) — the same measurement as `EngineDriftOut`, on the other object.

    WHY A SECOND FIELD AND NOT A SECOND ENDPOINT: `EngineDriftOut`'s argument exactly —
    one read, one permission, and no new entry in `ADMIN_CONSOLE_GETS` (a GET declaring
    `ops:manage` has to be allowlisted, and `tests/impersonation_reads_test.py` warns that
    entries are how that list "quietly becomes a hole").

    WHY A SECOND FIELD AND NOT MORE COLUMNS ON `EngineDriftOut`: the two sweeps run on
    different schedules over different objects and each `oldest_checked_at` is its OWN
    sweep's pulse. Folding them into one panel would let a healthy agent sweep's timestamp
    vouch for a KB sweep that had died — which is precisely the "lying by omission" the
    pulse field exists to prevent.

    THE ALARM IS `out_of_sync`, and `undetermined` is deliberately NOT folded into it. It
    carries more weight here than on the agent panel: an empty knowledge listing is
    ambiguous between "the documents are gone" and "the vendor's listing does not attribute
    rows to agents" (pilot gate 8, open), so a large `undetermined` is a real and
    actionable signal about the VENDOR rather than a count of drifted clients.

    COUNTS AND TIMESTAMPS ONLY (hard rule 6). No source name, no chunk, no engine handle.
    """

    model_config = ConfigDict(extra="forbid")

    live_agents: int
    # Never swept. Distinct from `in_sync` for `live_verify_state`'s reason: an agent
    # nobody has looked at must not be counted as one we looked at and liked.
    never_checked: int
    out_of_sync: int
    in_sync: int
    undetermined: int
    # Null exactly when `out_of_sync` is 0. Age is what separates a publish that raced a
    # sweep from a vendor-console edit nobody has noticed for a month.
    oldest_drift_at: datetime | None
    # THIS SWEEP'S OWN PULSE. If the cron dies every count above freezes and
    # `out_of_sync: 0` reads as "all clear" forever. Null when nothing has been swept.
    oldest_checked_at: datetime | None
    # WHETHER THERE IS ANYTHING HERE TO WATCH AT ALL, and without it the panel above was
    # permanently wrong on the engine we actually run.
    #
    # `sweep_kb_drift` returns `checked=0 drifted=0` on its first line when the engine has
    # no built-in knowledge base, deliberately — asking anyway would record `unreachable`
    # for every live agent and paint a console red about a capability the platform never
    # had. `BOLNA_CAPABILITIES.knowledge_base` is False (D-354 closed the plan that
    # assumed otherwise), so on the primary engine that early return is EVERY run.
    #
    # The console could not see that. It had counts and a null pulse, which is the same
    # shape a DEAD CRON produces, so it told an operator "if this persists past an hour the
    # knowledge reconciliation job is not running" — permanently, about a job running
    # hourly and behaving exactly as designed. A panel that cries wolf forever is one
    # nobody reads, which costs the alarm that matters. This field is what lets it say the
    # true thing instead.
    engine_supports_knowledge_base: bool


class PlatformStateOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    load_shed_mode: str
    outbound_halted: bool
    # WHY outbound is stopped, for the person who found it stopped. Null whenever
    # `outbound_halted` is false, and the pair always comes from one row read
    # (`ops.service.read_halt_state`) so the dashboard cannot show a halt from one
    # instant next to a reason from another.
    halt_reason: str | None
    # The third global switch on this row, and the only one that is a legal fact rather
    # than an operational one: when it is not live, no tenant may launch a campaign.
    tm_registration: TmRegistrationOut
    # NOT a switch, and the one field here that is not on `platform_state` at all.
    #
    # WHY IT RIDES THIS READ rather than getting a `GET /v1/ops/outbox/dead-letters` of
    # its own. The console's ops screen makes exactly one read, gates the whole page on
    # it, and polls it every 30s; a second endpoint would be a second request with the
    # same permission, for the same operator, at the same moment, and the depth it
    # returned would still be a different instant from everything beside it.
    #
    # The one-instant argument that put `halt_reason` here does NOT transfer, and saying
    # so is the honest half: nobody interprets the DLQ depth against the load-shed mode.
    # What must share an instant is the depth, the breakdown and the age — and that holds
    # inside `read_dead_letter_queue`'s single aggregate no matter which route carries it.
    #
    # The argument that DOES decide it is the route table. `ops:manage` is in
    # `MUTATING_PERMISSIONS`, so every new GET declaring it has to be written into
    # `ADMIN_CONSOLE_GETS` (tests/impersonation_reads_test.py) — an allowlist whose own
    # test warns that entries are how it "quietly becomes a hole". A field on a route
    # already exempt adds no entry to it.
    #
    # THE COST, stated because the console has to handle it: a failed platform read now
    # blinds the depth too. That costs a NUMBER, never the control — the replay button
    # stays gated on the permission alone, and the panel renders "we could not read the
    # depth" rather than a zero (BUILD-LOG §52: failure is a refusal, not an empty state).
    outbox_dead_letters: DeadLetterQueueOut
    # The second thing on this payload that is a MEASUREMENT rather than a switch, and it
    # rides here for the same three reasons `outbox_dead_letters` does: one read, one
    # permission, no new entry in `ADMIN_CONSOLE_GETS`. NO DEFAULT — a Pydantic field with
    # one generates an OPTIONAL TypeScript property, and a console that has to write
    # `state.engine_drift?.out_of_sync ?? 0` has a `0` for "the field is missing", which is
    # the exact conflation this whole panel exists to prevent.
    engine_drift: EngineDriftOut
    # The third measurement, and the answer to "is the agent SAYING what we approved" —
    # `engine_drift` above answers "is it CONFIGURED as we published". They are separate
    # objects at the vendor, read by separate sweeps, and an agent whose prompt is
    # perfectly in sync can still be answering questions from a knowledge base somebody
    # pasted into Bolna's console. NO DEFAULT, for `engine_drift`'s reason: a Pydantic
    # field with one generates an OPTIONAL TypeScript property, and `?? 0` for "the field
    # is missing" is the conflation this panel exists to prevent.
    kb_drift: KbDriftOut


class TmRegistrationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["not_registered", "submitted", "active", "suspended", "revoked"]
    # Required in practice for `active` (service + DB CHECK); optional in the schema
    # because the other four states legitimately have no number yet, or no longer do.
    tm_id: str | None = Field(default=None, max_length=120)
    registered_at: datetime | None = None
    # Same requirement as the load-shed switch: an operator changing a platform-wide
    # compliance fact says why, in the audit row, at the time.
    reason: str = Field(min_length=3, max_length=500)


class PlatformStateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    load_shed_mode: LoadShedMode | None = None
    outbound_halted: bool | None = None
    # REQUIRED, and required with content: a halt nobody explained is a halt nobody can
    # safely lift, and whoever finds it at 3am has to decide whether the condition still
    # holds. Same bounds as `TmRegistrationIn.reason` — one shape for one idea. When the
    # request halts, this string is what lands in `platform_state.halt_reason`.
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def _not_whitespace(cls, value: str) -> str:
        """`min_length` alone accepts `"   "`, which passes the check and answers
        nothing. Stripped here so the column holds the reason as it will be read."""
        stripped = value.strip()
        if len(stripped) < 3:
            raise ValueError("a reason is required — say what stopped, and why")
        return stripped


class ReplayOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replayed: int
    # The scope the run APPLIED, echoed back. Null means every job.
    #
    # It exists so `replayed: 0` is legible: a well-formed but misspelled job name is
    # accepted (the API cannot tell "no such job" from "that job's queue is empty"
    # without a second read of the queue, which would be racy and would be a second
    # definition of what is in it), so the answer prints the scope it actually used and
    # an operator can see their own typo instead of concluding the queue was empty.
    job: str | None


class ChainBreakOut(BaseModel):
    """One broken link, dated, and told apart from the other kind.

    `content` = the entry no longer hashes to its own recorded hash, i.e. its fields
    were edited. `link` = the entry is intact but names the wrong predecessor, i.e.
    something was deleted or reordered. The operator's next move is different for each,
    so the verdict carries which one it is rather than making them go and look.
    """

    model_config = ConfigDict(extra="forbid")

    entry_id: str
    at: datetime
    kind: Literal["link", "content"]


class ChainVerifyOut(BaseModel):
    """The verdict, the scope it is a verdict over, and EVERY break rather than one.

    `ok` alone is not an answer. The walk used to stop at the oldest 1,000 entries and
    still report a bare `ok: true`, so on any log longer than that the green box said
    nothing about recent activity while reading exactly like a full audit — the console
    could only compensate by hard-coding the limit in its own copy. The scope now
    travels with the verdict: how many entries were recomputed, the `at` range they
    span, and whether the walk reached the end of the log.

    It also used to stop AT the first break and report only that one. `audit_log` is
    append-only, so a break can never be repaired — meaning a single historical break
    would have pinned this endpoint to `ok: false` forever while leaving every entry
    after it unexamined, which is both a permanently red light nobody reads and a way
    for an attacker to switch off verification of the window they actually care about.
    The walk now re-anchors and continues; `breaks` names them all.
    """

    model_config = ConfigDict(extra="forbid")

    # NONE of the scope fields carry a default, so every one of them is REQUIRED on the
    # wire. That is the point: a default makes the field optional in the OpenAPI schema,
    # the generated client types it `| undefined`, and a console that has to write
    # `entries_checked ?? 0` is one keystroke from rendering an unknown scope as a
    # confident zero. The scope is not a footnote on the verdict, so it is not optional
    # on the verdict either. Nullable is different from absent and is used where the
    # answer genuinely has no value: no breaks means no first bad entry, an empty log
    # means no `at` range.
    ok: bool
    #: The FIRST break, kept as its own field because it is what the console names as
    #: evidence. Null when `ok`.
    first_bad_entry_id: str | None
    checked: Literal["audit_log"] = "audit_log"
    #: Every break found, oldest first. Capped, so read `breaks_found` for the total.
    breaks: list[ChainBreakOut]
    #: Total breaks; >= len(breaks) once the cap bites.
    breaks_found: int
    #: Entries recomputed. A break no longer truncates this.
    entries_checked: int
    #: True only when the walk covered the WHOLE log. False means the answer is about a
    #: subset, because the walk was bounded.
    complete: bool
    oldest_checked_at: datetime | None
    newest_checked_at: datetime | None
    #: Entries that verified under a RETIRED chain key rather than the active one.
    #:
    #: NOT a break and not a component of `ok`: these entries are intact. They are
    #: WEAKLY ATTESTED — on most deployments they are the era before AUDIT_CHAIN_SECRET
    #: was required, when the chain was signed with a constant printed in the source, so
    #: anyone who could read the repository could have produced them. An operator
    #: exporting this log as evidence has to know where that era ends, and a caveat that
    #: lives only in a runbook is a caveat that reaches nobody at the moment it counts.
    #: Zero on a deployment that has always been configured.
    entries_under_retired_key: int


class SpendCapRecomputeOut(BaseModel):
    """What the flag was, what it is now, and the numbers that decided it.

    An operator running this mid-incident needs to know not just whether the tenant is
    released but WHY — a recompute that leaves `capped` true has done its job and the
    ceiling is simply still below the spend. Reporting the counters and the effective
    ceiling next to the flag is what turns "it did not work" into "the ceiling is 2 and
    they have used 3".
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    # The IST billing month the recompute applied to (`spend_capped` reads this too).
    month: str
    # The flag as it stood when the request arrived, so the audit trail and the operator
    # can both see whether anything actually changed.
    capped_before: bool
    capped: bool
    # This month's metered counters — NOT written by this route, only read.
    minutes_used: str
    # THE CLIENT'S NUMBER (`spend_state.billed_inr`), because it is the one the verdict
    # above was reached from: `over_cap_sql` compares the ceiling against what the client
    # owes, not against what the engine charged us (P1.3). Reporting our supplier cost
    # beside `effective_cap_spend_inr` would show an operator a pair that does not
    # explain itself — the recompute would read as arbitrary at exactly the moment they
    # are checking whether it was right.
    spend_used_inr: str
    # The ceiling in force: LEAST(the plan's, the client's own). Money as an exact
    # decimal string, never a JSON float (hard rule 7).
    effective_cap_minutes: int | None
    effective_cap_spend_inr: str | None


def platform_confirmation(*, outbound_halted: bool | None, load_shed_mode: str | None) -> str:
    """The step-up string for ONE state transition of the global row.

    A named function for the same reason `spend_cap_confirmation` is one: these strings
    are an ops PROCEDURE. `runbooks/calls-stopped.md` §1 and `runbooks/campaign-stall.md`
    §1 print what an operator types mid-incident, and `tests/platform_halt_test.py` pins
    every literal — so changing the shape has to be a deliberate edit that fails a test,
    not a quiet reformat that leaves both runbooks instructing operators to send a header
    the API refuses.

    WHY THREE STRINGS AND NOT ONE. §7 wants the confirmation bound to the specific
    action. Halting every tenant's outbound dialling, releasing that halt, and moving
    the load-shed mode are three different decisions with three different blast radii,
    and one shared string meant a header captured for the smallest authorised the
    largest. The load-shed string carries its TARGET MODE for the same reason the
    spend-cap string carries its tenant: `reduced` is a routine change and `maintenance`
    sheds reads, and consent to one is not consent to the other.

    A request that does both halves needs both halves confirmed, joined in a fixed order
    (the halt first — it is the half that must be read before it is sent). Joining
    rather than accepting either alone is the conservative reading: a combined request
    is strictly more dangerous than either part.
    """
    parts: list[str] = []
    if outbound_halted is not None:
        parts.append("halt_outbound" if outbound_halted else "release_outbound")
    if load_shed_mode is not None:
        parts.append(f"set_load_shed:{load_shed_mode}")
    if not parts:
        # No transition, so there is nothing for a confirmation to be bound to. This
        # body used to reach `set_platform_status`, change nothing and still write an
        # audit row — a recorded platform change nobody made.
        raise ProblemError(
            kind="validation",
            code="platform_state_no_change",
            title="Nothing to change",
            detail="This request changes neither the load-shed mode nor the outbound halt.",
            remediation="Send load_shed_mode, outbound_halted, or both.",
        )
    return "+".join(parts)


def _tm_out(registration: TmRegistration) -> TmRegistrationOut:
    return TmRegistrationOut(
        status=registration.status,
        tm_id=registration.tm_id,
        registered_at=registration.registered_at,
        verified_at=registration.verified_at,
        is_live=registration.is_live,
    )


async def _platform_out(session: AsyncSession, *, load_shed_mode: str) -> PlatformStateOut:
    """The whole ops payload, assembled in ONE place for the read and for the write.

    The read and the write used to build this response with two near-identical literals,
    which was survivable while it was three fields and is not now: a field added to one
    and forgotten on the other is a console that shows a stale dead-letter depth after
    every halt, and nothing would have failed.

    `load_shed_mode` is the caller's, because the two routes get it from different places
    on purpose — the read force-refreshes the cache, the write has the mode its own
    `set_platform_status` just returned — and re-reading it here would hand the writer a
    value from a later instant than the one it wrote.

    Everything else is read from Postgres on the caller's session, never from the
    load-shed cache: the TM registration is a compliance fact and a 15-second-stale copy
    of it is a campaign that launched after the registrar suspended us.
    """
    halt = await read_halt_state(session)
    dlq = await read_dead_letter_queue(session)
    # Scoped to the CONFIGURED engine, not to every route row: a leftover route from a
    # previous vendor is not something the sweep reads back, so counting it here would
    # report a permanent `never_checked` nothing can ever clear.
    drift = await read_engine_drift(session, engine=get_engine().name)
    # Scoped to the configured engine for the same reason and read on the same session, so
    # both drift panels describe the same instant as the halt and the dead-letter depth.
    kb_drift = await read_kb_drift(session, engine=get_engine().name)
    return PlatformStateOut(
        load_shed_mode=load_shed_mode,
        outbound_halted=halt.outbound_halted,
        halt_reason=halt.reason,
        tm_registration=_tm_out(await read_tm_registration(session)),
        outbox_dead_letters=DeadLetterQueueOut(
            depth=dlq.depth,
            oldest_at=dlq.oldest_created_at,
            by_job=[
                DeadLetterJobOut(
                    job=entry.job, depth=entry.depth, oldest_at=entry.oldest_created_at
                )
                for entry in dlq.by_job
            ],
            deferred=dlq.deferred,
        ),
        engine_drift=EngineDriftOut(
            live_agents=drift.live_agents,
            never_checked=drift.never_checked,
            out_of_sync=drift.out_of_sync,
            in_sync=drift.in_sync,
            undetermined=drift.undetermined,
            oldest_drift_at=drift.oldest_drift_at,
            oldest_checked_at=drift.oldest_checked_at,
        ),
        kb_drift=KbDriftOut(
            live_agents=kb_drift.live_agents,
            never_checked=kb_drift.never_checked,
            out_of_sync=kb_drift.out_of_sync,
            in_sync=kb_drift.in_sync,
            undetermined=kb_drift.undetermined,
            oldest_drift_at=kb_drift.oldest_drift_at,
            oldest_checked_at=kb_drift.oldest_checked_at,
            # Asked of the SAME engine the sweep asks (`get_engine()`), not of config, so
            # the panel and the job cannot disagree about which engine is running.
            engine_supports_knowledge_base=get_engine().capabilities.has("knowledge_base"),
        ),
    )


@router.get(
    "/platform",
    response_model=PlatformStateOut,
    openapi_extra=permission_meta("ops:manage"),
)
async def read_platform(
    session: GlobalSession,
    _: Principal = Depends(requires("ops:manage", realm="admin")),
) -> PlatformStateOut:
    status = await get_platform_status(force_refresh=True)
    # The halt and its reason come from ONE row read for the same reason they are
    # written in one statement — this is the screen an operator reads mid-incident, and
    # "halted" beside a reason from a different instant is worse than either alone.
    # `_platform_out` holds that and the rest of the assembly.
    return await _platform_out(session, load_shed_mode=status.mode)


@router.post(
    "/platform",
    response_model=PlatformStateOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Load-shed mode and the big red switch (step-up confirmed, audited)",
)
async def set_platform(
    payload: PlatformStateIn,
    session: GlobalSession,
    request: Request,
    # Resolved BEFORE this handler body runs, so the session read cannot happen inside an
    # open transaction — `core/stepup.py` on `max_overflow=0`.
    step_up: StepUpGate,
    principal: Principal = Depends(requires("ops:manage", realm="admin")),
    x_confirm_action: str | None = Header(default=None),
) -> PlatformStateOut:
    """Bound to the transition, and the reason lands where the dashboard reads it.

    THE CONFIRMATION. `platform_confirmation` names the exact move being made — see its
    docstring for why one string across three moves was a hole rather than a
    convenience. This is a BREAKING change to an ops surface and is meant to be: the old
    `set_platform_state` header now authorises nothing, in either direction, and the
    refusal carries the header that would have worked.

    THE REASON. `halt_reason` is written in the same statement as `outbound_halted`
    (`core.loadshed.set_platform_status`) and cleared on release. Until now the reason
    went only into `write_audit`'s `summary` — and `audit_log` HAS NO SUMMARY COLUMN
    (`compliance/audit.py`: the sanitised summary goes to the log stream keyed by entry
    id), so the one question an operator asks first was answerable only by someone who
    knew to grep the right log stream. The column is the live answer; `audit_log`
    remains the history of who moved it and when.

    ONE AUDIT ROW PER TRANSITION. A request that halts AND sheds performed two actions,
    and one row named after the more dramatic of them would make "when did we last halt
    everyone" a full-text hunt through a generic action. The rows are written on
    `global_db`, which commits at the end of the request, so they land together.
    """
    confirmation = platform_confirmation(
        outbound_halted=payload.outbound_halted, load_shed_mode=payload.load_shed_mode
    )
    step_up.require(x_confirm_action, confirmation)

    status = await set_platform_status(
        mode=payload.load_shed_mode,
        outbound_halted=payload.outbound_halted,
        halt_reason=payload.reason,
        actor_id=str(principal.user_id) if principal.user_id else None,
    )
    halt = await read_halt_state(session)
    ip = client_request_ip(request)
    if payload.outbound_halted is not None:
        await write_audit(
            session,
            action="ops.halt_outbound" if payload.outbound_halted else "ops.release_outbound",
            actor=principal,
            object_type="platform_state",
            object_id="1",
            ip=ip,
            summary={"outbound_halted": halt.outbound_halted, "reason": payload.reason},
        )
    if payload.outbound_halted:
        # D-432, the recall arm of the switch. `payload.outbound_halted` rather than
        # `halt.outbound_halted` is deliberate and they are the same value here — this
        # arm must fire on an operator ASKING for a halt, including a re-post of one
        # already in force, because that is the only lever they have to run a second pass
        # after a capped or partly-refused recall (the job says so in its own alert).
        #
        # ENQUEUED DIRECTLY RATHER THAN THROUGH THE OUTBOX, which is this repo's default
        # and is the wrong tool here. The outbox exists so a side effect cannot outlive a
        # rolled-back write — but `set_platform_status` writes the halt on its OWN
        # connection and has already committed by this line, so there is no shared fate
        # left to preserve, and the outbox's 10-second dispatch tick would be ten seconds
        # of ringing bought for nothing.
        #
        # A FAILURE TO ENQUEUE IS ALARMED, NEVER RAISED. The halt itself has landed and
        # is the thing that matters; refusing the request now would tell an operator the
        # switch did not throw when it did, and their next move would be to throw it
        # again. `dial_recall_not_queued` is the row in `runbooks/alarm-index.md`.
        try:
            await enqueue(DIAL_RECALL_JOB)
        except Exception as exc:
            alert(
                "CORE_LOGIC",
                "dial_recall_not_queued",
                detail=(
                    f"outbound was halted but the recall job could not be queued "
                    f"({exc.__class__.__name__}); dials already accepted by the voice "
                    "platform will ring unless the halt is re-posted"
                ),
            )
    if payload.load_shed_mode is not None:
        await write_audit(
            session,
            action="ops.set_load_shed",
            actor=principal,
            object_type="platform_state",
            object_id="1",
            ip=ip,
            summary={"load_shed_mode": status.mode, "reason": payload.reason},
        )
    return await _platform_out(session, load_shed_mode=status.mode)


@router.post(
    "/platform/tm-registration",
    response_model=TmRegistrationOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Record Calevate's own DLT telemarketer registration (step-up confirmed, audited)",
    description=(
        "The company half of SEC-COMP §3's first bullet. While this is not `active`, "
        "NO tenant can launch an outbound campaign, however complete their own "
        "Principal Entity registration is. Inbound answering is unaffected."
    ),
)
async def set_tm_registration_route(
    payload: TmRegistrationIn,
    session: GlobalSession,
    request: Request,
    # Resolved BEFORE this handler body runs, so the session read cannot happen inside an
    # open transaction — `core/stepup.py` on `max_overflow=0`.
    step_up: StepUpGate,
    principal: Principal = Depends(requires("ops:manage", realm="admin")),
    x_confirm_action: str | None = Header(default=None),
) -> TmRegistrationOut:
    """Step-up confirmed in BOTH directions, with the action naming which one.

    Marking the registration active is the more dangerous write, not the less: it is
    the one that turns the platform-wide launch gate green, and a stolen admin session
    that could do it silently would have every tenant dialling on a registration that
    does not exist. Taking it away halts all outbound launching, which is the big red
    switch by another route. Neither belongs behind a single unconfirmed POST, so the
    confirmation is bound to the direction — `record_tm_registration` to make it live,
    `withdraw_tm_registration` to take it out of `active` — and an operator who meant
    one cannot perform the other by replaying a header.
    """
    action = "record_tm_registration" if payload.status == "active" else "withdraw_tm_registration"
    step_up.require(x_confirm_action, action)

    registration = await set_tm_registration(
        session,
        status=payload.status,
        tm_id=payload.tm_id,
        registered_at=payload.registered_at,
    )
    # Same transaction as the write (`global_db` commits at the end of the request):
    # the row is mutable by design, so `audit_log` is the only history of who changed
    # a platform-wide compliance fact and why.
    await write_audit(
        session,
        action=f"ops.{action}",
        actor=principal,
        object_type="platform_state",
        object_id="1",
        ip=client_request_ip(request),
        summary={
            "tm_registration_status": registration.status,
            "tm_id": registration.tm_id,
            "reason": payload.reason,
        },
    )
    return _tm_out(registration)


def spend_cap_confirmation(tenant_id: UUID) -> str:
    """The step-up string for one tenant's recompute.

    A named function rather than an f-string inline, because this value is part of an
    ops PROCEDURE — `runbooks/calls-stopped.md` §2 prints the header an operator types
    mid-incident, and `tests/ops_spend_cap_recompute_test.py` pins the literal. Changing
    the shape has to be a deliberate edit here that fails that test, not a quiet
    reformat that leaves the runbook telling operators to send a header the API refuses.
    """
    return f"recompute_spend_cap:{tenant_id}"


@router.post(
    "/tenants/{tenant_id}/spend-cap/recompute",
    response_model=SpendCapRecomputeOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Re-derive a tenant's spend cap flag from their counters (step-up confirmed, audited)",
    description=(
        "Recomputes `spend_state.capped` from the minutes and spend ALREADY metered "
        "this month against the ceiling now in force. Use it after raising "
        "`plans.hard_cap_min` / `hard_cap_spend` for a capped client: the flag is a "
        "derived column and raising the ceiling does not by itself release the gate. "
        "It never sets the flag directly and never moves a counter, so a tenant still "
        "over their ceiling stays capped. Inbound calling is unaffected either way."
    ),
)
async def recompute_spend_cap(
    tenant_id: UUID,
    request: Request,
    # Resolved BEFORE this handler body runs, so the session read cannot happen inside an
    # open transaction — `core/stepup.py` on `max_overflow=0`.
    step_up: StepUpGate,
    principal: Principal = Depends(requires("ops:manage", realm="admin")),
    x_confirm_action: str | None = Header(default=None),
) -> SpendCapRecomputeOut:
    """The third writer of `spend_state.capped`, and the only one ops can reach.

    THE DEAD END IT CLOSES (`runbooks/calls-stopped.md` §2). The gate reads the flag,
    not the ceilings. The meter arms it and a capped tenant meters nothing, so the meter
    can never clear it; the client's `PUT /v1/billing/caps` clears it but needs
    `org:manage`, which is in `MUTATING_PERMISSIONS`, so an impersonating admin (D-22)
    cannot do it for them. An outbound-only client whose ceiling ops had just raised
    therefore stayed stopped until they acted themselves or the IST month rolled over.

    IT RECOMPUTES; IT DOES NOT UN-CAP. The work is `caps.recompute_capped`, the same
    function the client's route calls, reading the same `over_cap_sql` the post-call
    meter uses. An ops button that wrote `capped = false` would be the third DEFINITION
    rather than the third caller, and the first incident it caused would be a tenant
    dialling past a ceiling with the meter re-arming the flag behind it.

    Scoping is the house pattern for an admin-realm mutation: the tenant is named in the
    path (an admin principal has no tenant of its own — `route_shape_test`) and the work
    runs inside `tenant_session`, so `spend_state`'s RLS policy is what isolates it.
    The audit row is written on the SAME session, so the flag and the record of who
    moved it commit together or not at all.
    """
    # Bound to the tenant, not just to the verb: a confirmation captured for one client
    # cannot be replayed against another. See the module docstring on why the big red
    # switch's generic string is not the standard to copy.
    step_up.require(x_confirm_action, spend_cap_confirmation(tenant_id))

    async with tenant_session(tenant_id) as session:
        if not await tenant_exists(session, tenant_id):
            # A mistyped uuid must not answer 200 with a cheerful "not capped" — read
            # mid-incident that says "fixed" while the real client is still stopped.
            raise ProblemError.not_found("Organization")

        before = await read_spend_counters(session, tenant_id=tenant_id)
        # `None` means there is no row for the CURRENT month — nothing metered yet, or a
        # row still stamped with a closed one. Both are "no cap in force" and both are
        # left alone: `compliance.spend_capped` already reads the month, so rewriting a
        # stale row would evaluate last month's counters against this month's ceiling.
        recomputed = await recompute_capped(session, tenant_id=tenant_id)
        capped = bool(recomputed)
        caps = await read_caps(session, tenant_id=tenant_id)

        await write_audit(
            session,
            action="ops.recompute_spend_cap",
            actor=principal,
            tenant_id=tenant_id,
            object_type="spend_state",
            object_id=str(tenant_id),
            ip=client_request_ip(request),
            # Ids, ceilings and two booleans. No phone number, transcript or extraction
            # exists anywhere on this path (hard rule 6).
            summary={
                "month": current_billing_month(),
                "capped_before": before.capped,
                "capped_after": capped,
                "row_present_for_month": recomputed is not None,
                "effective_cap_minutes": caps.effective_cap_min,
                "effective_cap_spend_inr": (
                    str(to_paise(caps.effective_cap_spend))
                    if caps.effective_cap_spend is not None
                    else None
                ),
            },
        )

    return SpendCapRecomputeOut(
        tenant_id=str(tenant_id),
        month=current_billing_month(),
        capped_before=before.capped,
        capped=capped,
        minutes_used=str(to_paise(before.minutes_used)),
        spend_used_inr=str(to_paise(before.billed_inr)),
        effective_cap_minutes=caps.effective_cap_min,
        effective_cap_spend_inr=(
            str(to_paise(caps.effective_cap_spend))
            if caps.effective_cap_spend is not None
            else None
        ),
    )


# The step-up string for an UNSCOPED dead-letter replay — every job, every tenant.
#
# It matches `reliability.service.replay_dead_letters` and the console's button label on
# purpose: an operator types what they were told they are doing. It is also the literal
# `runbooks/webhook-delivery-failures.md` §3 prints for the curl fallback, which is why it
# stays exactly this string and why `outbox_replay_confirmation(None)` returns it rather
# than a new spelling of the same act.
OUTBOX_REPLAY_CONFIRMATION = "replay_dead_letters"

# A job name is an ARQ identifier written by `enqueue_outbox` (`deliver_outbound_webhook`,
# `send_hot_lead_email`, ...). Bounded here because it is interpolated into a step-up
# string and written into an audit summary, and a query parameter is attacker-controlled
# on any surface: whatever the router does with it, it is [a-z0-9_] and short. The bound
# is NOT an allow-list of known jobs — the API has no registry of ARQ job names (they live
# in `apps/workers`, which nothing here may import), and inventing one here would be a
# second definition of what can be in the queue.
JobScope = Annotated[str | None, Query(max_length=64, pattern=r"^[a-z][a-z0-9_]*$")]


def outbox_replay_confirmation(job: str | None) -> str:
    """The step-up string for ONE dead-letter replay, bound to the scope it will use.

    WHY THIS GREW A SUFFIX. It was a bare constant an hour ago, on the argument that
    nothing about the action varied — there is exactly one global dead-letter queue, so
    there was no target for a `:<suffix>` to bind. The replay now takes an optional `job`
    scope, so that argument is simply no longer true, and the string has to move with it:
    a header reading `replay_dead_letters` on a request that replays only the CRM webhooks
    — or, far worse, a header captured for one job authorising a redelivery of everything
    — is a confirmation that describes an action other than the one being performed, which
    is worse than no confirmation because an operator believes it.

    So `None` (every job) keeps the unsuffixed literal and every scope names itself, the
    same shape `spend_cap_confirmation` has for the same reason: the suffix carries the
    part of the action an operator could get wrong by replaying a header they already had.

    `replay_dead_letters:all` is NOT this function's output for the unscoped case, and
    `tests/ops_outbox_replay_test.py` pins it as a string that must be REFUSED. That is
    not arbitrary: it was already refused before scoping existed, and a job would have to
    be literally named `all` for this function to ever produce it.
    """
    return OUTBOX_REPLAY_CONFIRMATION if job is None else f"{OUTBOX_REPLAY_CONFIRMATION}:{job}"


@router.post(
    "/outbox/replay",
    response_model=ReplayOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Flip dead-lettered outbox messages back to pending (step-up confirmed, audited)",
    description=(
        "Moves up to 100 of the OLDEST dead-lettered outbox messages back to `pending` "
        "with a fresh attempt budget, for every tenant at once. The next dispatch tick "
        "re-sends them: HMAC-signed webhooks to clients' own systems, Google Sheets "
        "appends, notification emails. A message can dead-letter AFTER its side effect "
        "landed, so the outcome to be sure of before sending this is a second delivery, "
        "not a flag in a row. `job` scopes the run to one kind of side effect and MUST be "
        "echoed in the confirmation header (`replay_dead_letters:<job>`); omit it to "
        "replay every job, which is `X-Confirm-Action: replay_dead_letters`. Read the "
        "depth and the per-job breakdown from `GET /v1/ops/platform` first — "
        "`outbox_dead_letters` is published so this confirmation can be an informed one."
    ),
)
async def replay_outbox(
    session: GlobalSession,
    request: Request,
    # Resolved BEFORE this handler body runs, so the session read cannot happen inside an
    # open transaction — `core/stepup.py` on `max_overflow=0`.
    step_up: StepUpGate,
    job: JobScope = None,
    principal: Principal = Depends(requires("ops:manage", realm="admin")),
    x_confirm_action: str | None = Header(default=None),
) -> ReplayOut:
    """The most outward-facing write on this router, and the last one to get a step-up.

    WHY IT NEEDS ONE AT ALL, given it moves no switch. `replay_dead_letters` selects on
    `status = 'failed'` with NO tenant predicate — `outbox_messages` is an infra table
    and carries no `tenant_id` column to have one with — so a single POST reaches every
    client's parked messages. And the flip is not the blast radius: the next dispatch
    tick DELIVERS them, so the effect is other people's customer data arriving a second
    time in other people's systems, which is not undoable from here and is visible to the
    client. Halting outbound calling is loud, reversible and ours; this is quiet,
    irreversible and theirs. It was the only write here reachable by one unconfirmed POST.

    NO REASON FIELD, deliberately, and this is the one place this router is asymmetric.
    `set_platform` and the TM registration both require one because they leave a STATE
    behind that somebody finds later and has to decide whether to lift — `halt_reason`
    exists for the person who arrives at 3am. A replay leaves no state: it is an
    instantaneous act whose record is the audit row (who, when, how many) and whose
    "why" is the incident that is already open in `runbooks/webhook-delivery-failures.md`.
    Adding a required body here would break the console's form and the runbook's curl to
    buy a free-text field nobody reads back.

    THE SCOPE IS A QUERY PARAMETER, not a body field, and the reason is that it is part of
    this request's IDENTITY rather than its content: it is interpolated into the step-up
    confirmation, so the access log, the console's URL, the runbook's curl and the audit
    row all show the same string. A body would hide the scope from every log we keep, and
    would turn the runbook's bodyless `curl -X POST` into one that needs a `-d`.

    WHY SCOPE AT ALL, given `outbox_messages` has no `tenant_id` to scope by. Per-tenant
    is impossible without a migration (the ids live inside the JSONB payload), so `job` is
    the only bound available — and it is not a consolation prize. The run takes the 100
    OLDEST rows, so an operator recovering a client's CRM webhooks out of a queue full of
    dead-lettered emails replays 100 emails, reads `replayed: 100` as success, and leaves
    every webhook parked. Scoping is what makes "replay the thing I am here about"
    reachable in one act.
    """
    # Bound to the action AND to the scope it will use, checked BEFORE any row moves.
    # See `outbox_replay_confirmation` for why the string grew a suffix.
    step_up.require(x_confirm_action, outbox_replay_confirmation(job))

    count = await replay_dead_letters(session, job=job)
    # BACKEND-PATTERNS §4 requires the replay to carry an audit note — a message that
    # was delivered twice needs a record of who asked for the second attempt. The scope
    # goes in it too: "who replayed 100 messages" and "which 100" are different questions
    # and only one of them was answerable.
    await write_audit(
        session,
        action="ops.outbox_replay",
        actor=principal,
        object_type="outbox_messages",
        ip=client_request_ip(request),
        summary={"replayed": count, "job": job},
    )
    return ReplayOut(replayed=count, job=job)


@router.get(
    "/audit/verify",
    response_model=ChainVerifyOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Recompute the audit hash chain and report every broken link",
)
async def verify_audit_chain(
    session: GlobalSession,
    _: Principal = Depends(requires("ops:manage", realm="admin")),
) -> ChainVerifyOut:
    # No bound. An operator runs this because they need to know whether the ledger is
    # the one we wrote, and a bounded walk answers a smaller question while looking
    # identical (see `ChainVerifyOut`). The cost is one HMAC per entry — tens of
    # milliseconds per 10k — and this route is admin-only (`ops:manage`), so the walk
    # is not reachable by anyone who could turn it into load.
    result = await verify_chain(session)
    return ChainVerifyOut(
        ok=result.ok,
        first_bad_entry_id=result.first_bad_entry_id,
        breaks=[ChainBreakOut(entry_id=b.entry_id, at=b.at, kind=b.kind) for b in result.breaks],
        breaks_found=result.breaks_found,
        entries_checked=result.entries_checked,
        complete=result.complete,
        oldest_checked_at=result.oldest_checked_at,
        newest_checked_at=result.newest_checked_at,
        entries_under_retired_key=result.entries_under_retired_key,
    )


@router.get(
    "/engine-latency",
    response_model=EngineLatencyReport,
    openapi_extra=permission_meta("ops:manage"),
    summary="What the voice engine reported its own pipeline cost, by region (gate 4)",
)
async def read_engine_latency(
    session: AdminSession,
    days: int = Query(
        DEFAULT_WINDOW_DAYS,
        ge=1,
        le=MAX_WINDOW_DAYS,
        description="How many days of calls to include.",
    ),
    _: Principal = Depends(requires("ops:manage", realm="admin")),
) -> EngineLatencyReport:
    """The LLM time-to-first-token distribution per (engine, region).

    **NO STEP-UP CONFIRMATION**, for this file's stated reason: it writes nothing, and
    demanding a confirmation to run a read teaches operators to type past confirmations.

    **NO AUDIT ROW.** The payload is milliseconds, counts and a region code — nothing from
    any call and nothing about any person — and it is a page an operator refreshes while
    watching a pilot. An audit chain that grows a row per refresh stops being readable,
    which is the argument `quality/routes.py` and `holds_routes.py` both make.

    **WHY IT IS ADMIN AND NOT CLIENT.** It is a question about OUR infrastructure choices
    across every tenant — specifically what the model deployment's geography costs the
    caller, which is what D-449 traded the India residency claim away to improve and what
    nobody has yet measured (OPERATIONS §2 gate 4). A client's own screen has
    nothing to do with it, and `flags.registry.call_timing_breakdown` is where the
    per-client version waits with its blocker written down.
    """
    return await engine_latency_report(session, days=days)


__all__ = [
    "OUTBOX_REPLAY_CONFIRMATION",
    "outbox_replay_confirmation",
    "platform_confirmation",
    "router",
    "spend_cap_confirmation",
]
