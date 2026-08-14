"""Admin credit surface — putting a client's payment onto their wallet, and taking a
wrong entry back off it.

Two writes, and the second exists because the first cannot be undone.

`credit_ledger` shipped in M1 with a writer (`record_entry`) and a debiter
(`charge_for_call`) and nothing that credits, so a self-serve wallet could only ever
go down. An Indian SMB pays us by bank transfer; someone in ops reads the UTR off the
statement and records it. That is this surface.

Three things decide the shape of this file:

- **Idempotent by the PAYMENT REFERENCE, not by a header.** The generic
  `Idempotency-Key` machinery (`reliability.claim_idempotency`) expires after 24h and
  keys off a header the caller chooses; a bank reference is permanent and is the thing
  that must not be credited twice — a UTR re-entered next week is the same payment.
  So the ledger's own `ref` is the key, exactly as `charge_for_call` treats a call id.
  The check-then-write runs under `pg_advisory_xact_lock` on the SAME key
  `record_entry` takes (`credit:<tenant_id>`), acquired BEFORE the lookup: without
  that, two operators clicking at once both read "no such reference" and both insert,
  and the lock inside `record_entry` is far too late to help.
  `ux_credit_ledger_tenant_reason_ref` (migration f9c2b41a8e57) has since landed behind
  the lock as a backstop — but only a backstop: it is partial (post-cutoff rows only,
  because the pre-fix duplicates cannot be deleted) and a UNIQUE violation surfacing as
  a 500 on a valid payment is not the answer this route wants to give. The lock is
  still what makes the check-then-write correct.
- **Money is NUMERIC INR, never a float** (hard rule 7). A JSON float is REFUSED at
  the boundary rather than quietly rounded: `2500.10` parsed as a binary float and
  back is how a paise-level dispute starts. Send `"2500.10"` — which is also how every
  money field in our responses is serialized, so a client echoing our own shape is
  already correct.
- **The audit row commits with the money.** `write_audit` appends in the CALLER'S
  transaction, so it goes on the tenant-scoped session that carries the ledger insert
  (`audit_log` is not tenant-RLS'd — see migration 05bba2f3c19c). Either both rows
  land or neither does; a credit with no audit row is not a possible state.

Tenant scoping is the invoice route's mechanism, unchanged: the tenant is named in the
path and the work runs inside `tenant_session(tenant_id)`, so `credit_ledger`'s RLS
policy is what isolates it. `app.admin` opens the client DIRECTORY, never their data,
and nothing here uses the admin DB role.

Permission: `admin:tenants` for the writes and `billing:read` for the read. There is no
`billing:write` in the registry and this did not warrant inventing one — recording a
received payment is admin-realm support work of the same family as provisioning a
number or filing a DLT status, all of which are `admin:tenants`. It is also already in
`MUTATING_PERMISSIONS`, so an impersonating admin cannot reach it (D-22).

## THE ADJUSTMENT (`POST .../credits/adjustments`)

SURFACES §1 promises "credit adjustments (compensating entries, never edits)" and
nothing implemented it, so an operator who credited ₹50,000 to the wrong client had no
supported way to put it right: the ledger refuses UPDATE and DELETE (hard rule 4, a
database trigger), the top-up route refuses a negative amount, and
`scripts/reconcile_credit_ledger.py` only detects DUPLICATED entries — its key is a
fingerprint of the duplicate group, so a wrong tenant or a wrong amount is invisible to
it. This is that missing repair, and four decisions carry it:

- **It corrects a NAMED ENTRY, in whole or in part.** Not a free-form debit. That is
  what gives the operator's amount a ceiling (you can never take back more than a
  specific entry put in, less whatever has already been taken back), what makes the
  direction derivable rather than typed (`CorrectableEntry.compensating_delta`), and
  what gives the compensating row an idempotency key of its own.
- **Its key is content-addressed over (entry, amount)** and enforced by
  `ux_credit_ledger_tenant_reason_ref`, not by a reader's `if` (D-63). An adjustment
  has no UTR, and the failure it has to survive is a second CLICK — which a
  caller-minted key does not, because a second click mints a second key.
  `billing.service.adjustment_ref` argues the whole trade, including what it costs.
- **The balance MAY go negative, and that is the point.** A wrong credit that has
  already been partly spent cannot be fully reversed without going below zero, and
  refusing that would leave the ledger permanently claiming money the client never
  had. `record_entry(allow_negative=True)` — the same reason
  `scripts/reconcile_credit_ledger.py` passes it. What a negative balance DOES is a
  fact about the tenant, not a guess: `compliance.service.credits_exhausted` is the
  gate's own predicate (`balance <= 0`, self-serve/trial only), so a managed client is
  unaffected and a self-serve one stops dialling exactly as an empty wallet would. The
  response says which happened (`stops_dialling`) rather than leaving an operator to
  discover it from a client's phone call.
- **The dangerous DIRECTION needs a step-up, not the route.** Taking credit away
  (`delta < 0`) requires `X-Confirm-Action: adjust_credits:<entry_id>`; crediting back
  — reversing a usage charge — does not. The shape is `admin/routes.py::
  record_commercial_terms`, which gates a spend-ceiling LOOSENING rather than the
  endpoint that writes it. It stops there: `core/rbac.py` reserves superadmin for the
  unbounded switches (the big red switch, cap raises), and this one is bounded by an
  entry that already exists and reversible by a further compensating entry, so making
  the operator who made the mistake wait for a superadmin would keep a wrong ledger
  wrong for longer than the risk justifies.

Every adjustment carries the operator's own words. `reason` is required (there is no
"" path), it goes into `meta` and into the audit row verbatim, and the audit row is
written in the same transaction as the money — the top-up's rule, for the write where
it matters more.

NOT mounted here — the integrator wires this router into `main.py`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin.service import tenant_exists
from apps.api.billing.service import (
    ADJUSTMENT_META_KIND,
    LOW_BALANCE_INR,
    CorrectableEntry,
    adjustment_ref,
    find_entry_by_ref,
    find_topup,
    get_balance,
    lock_tenant_credits,
    read_correctable_entry,
    record_entry,
    reversed_amounts,
    to_paise,
)
from apps.api.compliance.audit import write_audit
from apps.api.compliance.service import credits_exhausted
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.core.stepup import require_step_up
from apps.api.db.session import tenant_session

log = get_logger(__name__)

router = APIRouter(prefix="/v1/admin/tenants/{tenant_id}/credits", tags=["admin"])

# Annotated dependencies rather than `Depends()` in a default: this file is not
# `routes.py`, so it is not covered by the B008 per-file ignore (same reason
# `agents/prompt_routes.py` is written this way).
CreditsWrite = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]
CreditsRead = Annotated[Principal, Depends(requires("billing:read", realm="admin"))]

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

# NUMERIC(12,4) is the storage precision; two decimals is what a rupee amount means to
# the person reading it. `billing.service.to_paise` is the ONE rounding function in the
# system (half-up, explicit) — this module re-exported a second, context-dependent copy
# of it, which is how two surfaces end up rounding the same rupee two ways.
_paise = to_paise


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MoneyIn(Strict):
    """A request body carrying one rupee amount, with hard rule 7 applied at the edge.

    Both writes on this router take an amount and both must refuse a JSON float, so the
    refusal lives once. `max_digits`/`decimal_places` mirror the column — MONEY is
    NUMERIC(12,4), so eight integer digits is the ceiling and anything finer than a
    paisa is a typo.
    """

    amount_inr: Decimal = Field(max_digits=10, decimal_places=2)

    @field_validator("amount_inr", mode="before")
    @classmethod
    def _never_a_float(cls, value: Any) -> Any:
        """REFUSED rather than quietly rounded: `2500.10` parsed as a binary float and
        back is how a paise-level dispute starts. Send `"2500.10"` — which is also how
        every money field in our responses is serialized, so a client echoing our own
        shape is already correct."""
        if isinstance(value, float):
            raise ValueError(
                'money crosses the wire as a string ("2500.00"), never as a JSON float'
            )
        return value


class TopUpIn(MoneyIn):
    # The bank/UPI reference (UTR, RRN, a Razorpay payment id). This is the
    # idempotency key, which is why it is required and never generated for the caller.
    payment_ref: str = Field(min_length=3, max_length=120)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("payment_ref")
    @classmethod
    def _trimmed(cls, value: str) -> str:
        """A trailing space would make the SAME reference a DIFFERENT key and credit
        the payment twice — the one normalization this endpoint cannot skip."""
        trimmed = value.strip()
        if len(trimmed) < 3:
            raise ValueError("a payment reference is required")
        return trimmed


class TopUpOut(Strict):
    tenant_id: UUID
    entry_id: UUID
    payment_ref: str
    amount_inr: Decimal
    balance_inr: Decimal
    is_low: bool
    # False = this reference was already on the ledger and nothing moved. The status
    # stays 200 either way: a 201 on a replay would claim a creation that never
    # happened, and the caller reads this flag to know which it got.
    recorded: bool


class AdjustmentIn(MoneyIn):
    """A compensating entry, described by what it corrects rather than by what it moves.

    `amount_inr` is a POSITIVE magnitude — how much of the named entry to take back. The
    direction is derived from that entry (`CorrectableEntry.compensating_delta`), so the
    one thing a form here cannot get wrong is the sign.
    """

    #: The `credit_ledger` row being corrected. It must belong to the tenant in the path.
    corrects_entry_id: UUID
    #: The operator's own words. Not `credit_ledger.reason` (which is the four-value
    #: enum, and is always `adjustment` here) — this is WHY, and it is required because
    #: an unexplained debit on a client's wallet is the ticket nobody can close. It
    #: reaches the entry's `meta` and the audit row verbatim, the shape
    #: `admin/routes.py::LifecycleIn.reason` established.
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def _not_only_whitespace(cls, value: str) -> str:
        """Trimmed and re-measured, so `"   "` is refused rather than stored as a reason
        that reads as blank to everyone who later opens the audit row."""
        trimmed = value.strip()
        if len(trimmed) < 3:
            raise ValueError("say why this entry is being corrected")
        return trimmed


class AdjustmentOut(Strict):
    tenant_id: UUID
    #: The COMPENSATING entry that was appended (or the one that already existed).
    entry_id: UUID
    corrects_entry_id: UUID
    ref: str
    #: SIGNED, unlike the request: negative when credit was taken back off the wallet.
    delta_inr: Decimal
    balance_inr: Decimal
    is_low: bool
    #: False = this correction was already on the ledger and nothing moved. 200 either
    #: way, for the reason `TopUpOut.recorded` gives.
    recorded: bool
    #: Whether outbound dialling is now blocked on this wallet — the DIAL GATE's own
    #: verdict (`compliance.service.credits_exhausted`), not a re-derivation. True only
    #: for a self-serve or trial tenant whose balance is at or below zero; a managed
    #: client is invoiced against a retainer and is never stopped by a wallet. Published
    #: because a correction that silently stops a client's calling is the one
    #: consequence an operator must not learn from the client.
    stops_dialling: bool


class LedgerEntryOut(Strict):
    id: UUID
    delta_inr: Decimal
    reason: str
    ref: str | None
    balance_after_inr: Decimal
    occurred_at: datetime
    #: How much of this entry can still be taken back by a compensating adjustment —
    #: its own magnitude less whatever adjustments already name it. Zero once it is
    #: fully reversed. Published so the console can offer a correction with a ceiling
    #: on it instead of letting an operator type a number the route will refuse.
    reversible_inr: Decimal


class CreditsOut(Strict):
    tenant_id: UUID
    balance_inr: Decimal
    is_low: bool
    low_balance_threshold_inr: Decimal
    entries: list[LedgerEntryOut]


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """A mistyped tenant id must be a 404, not an FK violation rendered as a 500 —
    and on a money route, not a silent zero-balance wallet that looks real.

    The predicate itself is `admin.service.tenant_exists`, shared with the Razorpay
    receiver and the ops spend-cap recompute: three surfaces that name a tenant in a
    path had three copies of one SELECT, which is three places for "soft-deleted counts
    as absent" to be fixed in."""
    if not await tenant_exists(session, tenant_id):
        raise ProblemError.not_found("Organization")


# The idempotency lookup lives in `billing/service.py`, next to `record_entry` and the
# lock it depends on — this route and the Razorpay receiver used to carry a copy each,
# which is two places for one invariant to be fixed in. It is bound to a module-local
# name (rather than called through the import) so this file's concurrency tests can
# instrument the exact call the route makes.
#
# Note the shared function takes `lock_tenant_credits` ITSELF before reading, so the
# check-then-write ordering cannot be lost by a caller that forgets it. The explicit
# lock in `record_topup` below is still the meaningful one: it is what covers the
# INSERT that follows the lookup, not just the lookup.
_find_topup = find_topup

# The adjustment path's two reads, bound to module-local names for the same reason
# `_find_topup` is: the concurrency tests instrument the exact call the route makes, and
# an import called through would leave them patching a name nothing here uses.
# `_read_correctable_entry` is the FIRST read the write depends on and the one that must
# be unreachable while another operator holds the lock; `_find_entry_by_ref` is the
# replay lookup that decides whether anything is written at all.
_read_correctable_entry = read_correctable_entry
_find_entry_by_ref = find_entry_by_ref


def credit_adjustment_confirmation(entry_id: UUID) -> str:
    """The step-up string for taking credit BACK off a wallet.

    A named function rather than an inline f-string, for the reason
    `ops/routes.py::spend_cap_confirmation` gives: the value is part of an operator
    procedure, so changing its shape has to be a deliberate edit that fails a test
    rather than a reformat that leaves a console sending a header the API refuses.

    Bound to the ENTRY, not to the tenant as `spend_ceiling_confirmation` is. A tenant
    has one spend ceiling and many ledger entries, so "confirm for this client" would
    let a confirmation captured while correcting a ₹500 usage charge be replayed
    against a ₹50,000 top-up on the same wallet. The entry names the act exactly, and it
    implies the tenant.
    """
    return f"adjust_credits:{entry_id}"


@router.post(
    "",
    response_model=TopUpOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Record a client payment onto the wallet — idempotent by the payment reference",
    description=(
        "Posting the same payment reference again returns the existing entry and "
        "credits nothing. The same reference with a DIFFERENT amount is a conflict, "
        "not a second payment."
    ),
)
async def record_topup(
    tenant_id: UUID,
    payload: TopUpIn,
    request: Request,
    principal: CreditsWrite,
) -> TopUpOut:
    amount = payload.amount_inr
    if amount <= 0:
        # `record_entry` would happily append a negative delta — that is how usage is
        # recorded. A top-up that takes credit away is an operator error, and the
        # correction for a mis-keyed payment is a compensating `adjustment` entry
        # (hard rule 4), never a negative "top-up".
        #
        # The remediation names the ROUTE that does it. It used to say "record a
        # compensating adjustment instead" while no such surface existed anywhere in the
        # system — a refusal pointing at a thing that did not exist, which is worse than
        # no remediation at all because it reads as a supported path.
        raise ProblemError.business_rule(
            "invalid_topup_amount",
            "A top-up must be a positive rupee amount.",
            remediation=(
                "To take credit back, post the compensating adjustment to "
                f"/v1/admin/tenants/{tenant_id}/credits/adjustments, naming the entry "
                "it corrects. The wrong entry stays on the ledger; the new one cancels it."
            ),
        )

    ref = payload.payment_ref
    async with tenant_session(tenant_id) as scoped:
        await _assert_tenant_exists(scoped, tenant_id)
        # Serialize check-then-write against every other credit write for this tenant,
        # through the SAME function `record_entry` and `charge_for_call` use — one
        # definition of the lock key, so no writer can be accidentally left outside it.
        # Acquired BEFORE the lookup: two operators recording one UTR at the same
        # moment would otherwise both read "not present" and both insert. Released at
        # transaction end.
        await lock_tenant_credits(scoped, tenant_id)

        existing = await _find_topup(scoped, tenant_id=tenant_id, ref=ref)
        if existing is not None:
            if existing.amount_inr != amount:
                # Reusing a reference for a second, different payment would silently
                # swallow real money. Refusing is the only way anyone finds out.
                raise ProblemError.conflict(
                    "topup_reference_conflict",
                    "That payment reference is already on this wallet for a different amount.",
                    remediation="Check the statement; a second payment needs its own reference.",
                )
            balance = await get_balance(scoped, tenant_id=tenant_id)
            log.info(
                "credit_topup_replay",
                extra={"tenant_id": str(tenant_id), "entry_id": str(existing.entry_id)},
            )
            return TopUpOut(
                tenant_id=tenant_id,
                entry_id=existing.entry_id,
                payment_ref=ref,
                amount_inr=_paise(existing.amount_inr),
                balance_inr=_paise(balance.amount_inr),
                is_low=balance.is_low,
                recorded=False,
            )

        meta: dict[str, Any] = {"source": "admin_manual"}
        if principal.user_id:
            meta["recorded_by"] = str(principal.user_id)
        if payload.note:
            meta["note"] = payload.note
        balance = await record_entry(
            scoped,
            tenant_id=tenant_id,
            delta=amount,
            reason="topup",
            ref=ref,
            meta=meta,
        )
        written = await _find_topup(scoped, tenant_id=tenant_id, ref=ref)
        assert written is not None, "the row was inserted in this transaction"

        # Same transaction as the insert: money never moves without its audit row.
        await write_audit(
            scoped,
            action="credit.topup",
            actor=principal,
            tenant_id=tenant_id,
            object_type="credit_ledger",
            object_id=str(written.entry_id),
            ip=request.client.host if request.client else None,
            summary={
                "payment_ref": ref,
                "amount_inr": str(amount),
                "balance_after_inr": str(balance.amount_inr),
            },
        )

    return TopUpOut(
        tenant_id=tenant_id,
        entry_id=written.entry_id,
        payment_ref=ref,
        amount_inr=_paise(amount),
        balance_inr=_paise(balance.amount_inr),
        is_low=balance.is_low,
        recorded=True,
    )


@router.post(
    "/adjustments",
    response_model=AdjustmentOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Correct a wrong ledger entry by APPENDING a compensating adjustment",
    description=(
        "The ledger is append-only, so a wrong entry is never edited or removed — it "
        "stays where it is, because it is the evidence, and a new entry with the "
        "opposite sign cancels it. Name the entry to correct and how much of it to take "
        "back (a positive amount; the direction is derived from that entry). Sending the "
        "same correction again returns the entry that already exists and moves nothing. "
        "Taking credit AWAY additionally needs the header "
        "`X-Confirm-Action: adjust_credits:<corrects_entry_id>`; crediting back does "
        "not. The balance MAY go negative — a wrong credit that was partly spent cannot "
        "be fully reversed otherwise — and `stops_dialling` says whether that has "
        "blocked this client's outbound calling."
    ),
)
async def record_adjustment(
    tenant_id: UUID,
    payload: AdjustmentIn,
    request: Request,
    principal: CreditsWrite,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> AdjustmentOut:
    """The compensating entry SURFACES §1 promises, and the reasons for each refusal.

    The ORDER of the checks below is load-bearing, and one pair in particular:

    **The replay lookup runs BEFORE the remaining-reversible check.** After a correction
    lands, the entry it corrected has that much less left to give — so an operator whose
    first click succeeded and who clicks again would otherwise be told "that entry only
    has ₹0.00 left" (a 422 that reads like a refusal) instead of "already recorded,
    nothing moved" (a 200 that reads like the truth). The second click is the failure
    this route is designed around; it must land on the friendliest answer, not the
    strictest.

    **The step-up runs before either, but after the target is read**, because the
    direction it gates is a property of the entry rather than of the request: reversing
    a top-up takes money off the wallet and reversing a usage charge puts it back, and
    only the first is dangerous. Nothing has been written when it refuses.

    Audited on a REAL write only — the convention `record_commercial_terms`,
    `approve_kb` and `integrations.deactivate_endpoint` share. A replay changed nothing,
    and an audit row per button press makes "who took ₹50,000 off this client" harder to
    answer rather than easier.
    """
    amount = payload.amount_inr
    if amount <= 0:
        raise ProblemError.business_rule(
            "invalid_adjustment_amount",
            "An adjustment is how much of an entry to take back, so it is always positive.",
            remediation=(
                "Send a positive amount and name the entry in `corrects_entry_id` — the "
                "direction is derived from that entry, never from the sign you send."
            ),
        )

    async with tenant_session(tenant_id) as scoped:
        await _assert_tenant_exists(scoped, tenant_id)
        # Before the target read, exactly as `record_topup` takes it before its lookup:
        # the remaining-reversible figure this route decides on is a read the write
        # depends on, and two operators correcting one entry at the same moment would
        # otherwise both see the whole entry as reversible and both append.
        await lock_tenant_credits(scoped, tenant_id)

        target = await _read_correctable_entry(
            scoped, tenant_id=tenant_id, entry_id=payload.corrects_entry_id
        )
        if target is None:
            # RLS makes "no such entry" and "another tenant's entry" the same answer,
            # deliberately (`ProblemError.not_found` says so). Either way this operator
            # is correcting something that is not on this wallet.
            raise ProblemError.not_found("Ledger entry")
        if target.delta == 0:
            # `record_entry` returns early on a zero delta so nothing here writes one,
            # but a row that moved nothing has no direction to derive and nothing to
            # take back. Refuse rather than pick a sign.
            raise ProblemError.business_rule(
                "entry_moved_nothing",
                "That entry did not move any credit, so there is nothing to take back.",
                remediation="Correct the entry that actually moved the money.",
            )

        delta = target.compensating_delta(amount)
        if delta < 0:
            # Bound to the DIRECTION, not to the route (`record_commercial_terms`):
            # crediting a client back is ordinary support work, taking their credit away
            # is the dangerous half and the only one that needs the second key.
            require_step_up(x_confirm_action, credit_adjustment_confirmation(target.entry_id))

        ref = adjustment_ref(entry_id=target.entry_id, amount_inr=amount)
        existing = await _find_entry_by_ref(
            scoped, tenant_id=tenant_id, reason="adjustment", ref=ref
        )
        if existing is not None:
            balance = await get_balance(scoped, tenant_id=tenant_id)
            log.info(
                "credit_adjustment_replay",
                extra={"tenant_id": str(tenant_id), "entry_id": str(existing.entry_id)},
            )
            return AdjustmentOut(
                tenant_id=tenant_id,
                entry_id=existing.entry_id,
                corrects_entry_id=target.entry_id,
                ref=ref,
                delta_inr=_paise(existing.amount_inr),
                balance_inr=_paise(balance.amount_inr),
                is_low=balance.is_low,
                recorded=False,
                stops_dialling=await credits_exhausted(scoped, tenant_id=tenant_id),
            )

        if amount > target.reversible_inr:
            # A correction that takes back more than the entry put in is not a
            # correction of that entry — it is a second mistake wearing the first one's
            # name. The ceiling is cumulative, so two partial corrections cannot add up
            # past the whole.
            raise ProblemError.business_rule(
                "adjustment_exceeds_entry",
                (
                    f"That entry has ₹{_paise(target.reversible_inr)} left to take back, "
                    f"and this asks for ₹{_paise(amount)}."
                ),
                remediation=(
                    "Correct at most what is left of the entry. If more than one entry "
                    "is wrong, each is corrected against itself."
                ),
            )

        meta: dict[str, Any] = {
            "kind": ADJUSTMENT_META_KIND,
            # The one field `reversed_amounts` groups on — this is what makes the
            # ceiling above cumulative rather than per-click.
            "corrects_entry_id": str(target.entry_id),
            "corrects_reason": target.reason,
            "reason": payload.reason,
            # A rupee amount that goes into JSON as a NUMBER comes back out of some
            # reader as a float (hard rule 7), so it goes in as a string — the
            # reconciler's rule, for the same column.
            "amount_inr": str(_paise(amount)),
        }
        if principal.user_id:
            meta["recorded_by"] = str(principal.user_id)

        balance = await record_entry(
            scoped,
            tenant_id=tenant_id,
            delta=delta,
            reason="adjustment",
            ref=ref,
            meta=meta,
            # The wrong credit may already be spent. A wallet that reads richer than it
            # is, is the condition this route exists to end, so the correction lands and
            # the balance says what it says. What that COSTS the client is answered by
            # `stops_dialling` below rather than by refusing to record the truth.
            allow_negative=True,
        )
        written = await _find_entry_by_ref(
            scoped, tenant_id=tenant_id, reason="adjustment", ref=ref
        )
        assert written is not None, "the row was inserted in this transaction"

        # Same transaction as the insert: money never moves without its audit row.
        await write_audit(
            scoped,
            action="credit.adjustment",
            actor=principal,
            tenant_id=tenant_id,
            object_type="credit_ledger",
            object_id=str(written.entry_id),
            ip=request.client.host if request.client else None,
            summary={
                "corrects_entry_id": str(target.entry_id),
                "corrects_reason": target.reason,
                # Quantized, unlike the top-up's summary, which stringifies whatever
                # arrived. These two land in an incident channel next to the figure the
                # console showed, and `-50000.0000` beside `₹-50,000.00` reads as a
                # second, different number to the person comparing them.
                "delta_inr": str(_paise(delta)),
                "balance_after_inr": str(_paise(balance.amount_inr)),
                # The operator's own words. This is the field a later review of a debit
                # on a client's wallet is actually looking for.
                "reason": payload.reason,
            },
        )
        # The DIAL GATE's own predicate, asked inside this transaction so it sees the
        # balance this write just produced. Not re-derived from `balance.amount_inr`:
        # whether an empty wallet stops calling depends on the tenant's plan tier, and a
        # second copy of that rule here is how the console and the gate end up telling a
        # client two different stories.
        stops_dialling = await credits_exhausted(scoped, tenant_id=tenant_id)

    log.info(
        "credit_adjustment",
        extra={
            "tenant_id": str(tenant_id),
            "entry_id": str(written.entry_id),
            "corrects_entry_id": str(target.entry_id),
            "stops_dialling": stops_dialling,
        },
    )
    return AdjustmentOut(
        tenant_id=tenant_id,
        entry_id=written.entry_id,
        corrects_entry_id=target.entry_id,
        ref=ref,
        delta_inr=_paise(delta),
        balance_inr=_paise(balance.amount_inr),
        is_low=balance.is_low,
        recorded=True,
        stops_dialling=stops_dialling,
    )


@router.get(
    "",
    response_model=CreditsOut,
    openapi_extra=permission_meta("billing:read"),
    summary="Wallet balance plus the recent ledger entries, newest first",
)
async def read_credits(
    tenant_id: UUID,
    _: CreditsRead,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> CreditsOut:
    async with tenant_session(tenant_id) as scoped:
        await _assert_tenant_exists(scoped, tenant_id)
        balance = await get_balance(scoped, tenant_id=tenant_id)
        rows = (
            await scoped.execute(
                # RLS already scopes this; the predicate is what makes it an index
                # scan on ix_credit_ledger_tenant_recent. Same ordering as
                # `get_balance`, so entries[0].balance_after_inr IS the balance.
                text(
                    "SELECT id, delta, reason, ref, balance_after, occurred_at "
                    "FROM credit_ledger WHERE tenant_id = :tid "
                    "ORDER BY occurred_at DESC, id DESC LIMIT :limit"
                ),
                {"tid": tenant_id, "limit": limit},
            )
        ).all()
        # ONE grouped read for the whole page rather than one per row — and scoped to
        # the ids on the page, so a wallet with years of history does not pay for a
        # figure the caller can only see fifty of.
        reversed_by_entry = await reversed_amounts(
            scoped, tenant_id=tenant_id, entry_ids=[UUID(str(row[0])) for row in rows]
        )

    return CreditsOut(
        tenant_id=tenant_id,
        balance_inr=_paise(balance.amount_inr),
        is_low=balance.is_low,
        low_balance_threshold_inr=_paise(LOW_BALANCE_INR),
        entries=[
            LedgerEntryOut(
                id=UUID(str(row[0])),
                delta_inr=_paise(Decimal(str(row[1]))),
                reason=str(row[2]),
                ref=str(row[3]) if row[3] is not None else None,
                balance_after_inr=_paise(Decimal(str(row[4]))),
                occurred_at=row[5],
                # Computed through the SAME dataclass the write path decides on, so the
                # number the console offers and the ceiling the route enforces cannot
                # drift by a paisa.
                reversible_inr=_paise(
                    CorrectableEntry(
                        entry_id=UUID(str(row[0])),
                        delta=Decimal(str(row[1])),
                        reason=str(row[2]),
                        reversed_inr=reversed_by_entry.get(UUID(str(row[0])), Decimal("0")),
                    ).reversible_inr
                ),
            )
            for row in rows
        ],
    )


__all__ = ["router"]
