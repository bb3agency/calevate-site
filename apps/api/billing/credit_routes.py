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
received payment is admin-realm support work of the same family as recording a client's
number or a DLT status, all of which are `admin:tenants`. It is also already in
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

## THE RESTATEMENT (`POST .../credits/restatements`) — D-89

The adjustment closes ONE of the two ways a recorded payment is wrong. UNDER-crediting
had no path at all: ₹5,000 recorded against a UTR the bank actually moved ₹50,000 on
could not be repaired by re-posting the reference (a 409, deliberately — that refusal is
what stops one transfer being credited twice) and could not be repaired by an adjustment
(which only ever takes credit AWAY, bounded by the named entry). The documented remedy
was a second top-up under an ANNOTATED reference, `UTR-123-part2`, which is a lie in the
ledger: the wallet then carries two payment references for one bank transfer, and
reconciliation keyed on the reference — the entire reason the reference is the
idempotency key — stops balancing without saying so.

This route appends a second `topup` row for the SAME transfer, and five decisions carry
it. Each is a departure from, or a deliberate copy of, the adjustment above.

- **THE OPERATOR STATES THE TOTAL, NEVER THE DIFFERENCE.** `corrected_amount_inr` is
  what the bank moved — the figure printed on the statement in front of them — and the
  route derives what to credit. The alternative ("add ₹45,000 to this UTR") asks a human
  to subtract at 2am, and gets a subtraction WRONG SILENTLY: nothing in the system knows
  what the right answer was, so a slip lands as a real credit that reads correct for
  ever. A total is transcribed, not computed; it can be checked against the statement by
  eye; and it makes the whole act CONVERGENT — two operators who both notice the same
  problem and both type ₹50,000 reach one state, where two operators both typing
  "+₹45,000" credit ₹90,000. The delta shape is refused at the boundary rather than
  merely undocumented: the field is named for a total, and a value at or below what the
  reference already credits is a business-rule refusal that names `/adjustments`.
- **The key is `restated:<payment_ref>:<total>`**, content-addressed and enforced by
  `ux_credit_ledger_tenant_reason_ref` (D-63), exactly the shape D-87 chose. Because it
  addresses a STATE rather than a MOVEMENT it costs nothing where D-87's cost something
  — `billing.service.restatement_ref` argues that in full.
- **It is bounded by its SHAPE, not by a number, and that is the honest answer.** A
  correction that can only go UP has no ceiling analogous to the adjustment's, because
  the only thing that could supply one is the bank statement and we hold no
  machine-readable copy of it. Every numeric ceiling on offer is invented: it would
  refuse the very failure this route exists for (a ₹500-for-₹500,000 decimal slip is the
  commonest under-credit there is) while stopping nobody, since the same operator can
  already credit any amount at all through `POST .../credits` under a fresh reference,
  with no step-up. Applying `MIN/MAX_TOPUP_INR` was considered and rejected on the same
  ground plus a second: `record_topup` does not apply them either, and two ways of
  bounding one act is the drift this repo treats as a defect. What IS bounded: the route
  can only name a reference ALREADY on this wallet (it cannot invent a payment), it can
  only raise the total, the end state is a function of the total asserted so repetition
  never compounds, and an over-shoot is itself correctable — the row it writes is an
  ordinary `topup` entry and `/adjustments` takes it back, bounded by its magnitude.
- **The ledger still reads as ONE payment**, which is the property the annotated
  reference destroyed. The restating row names the transfer in `meta.payment_ref` and
  visibly in its own `ref`, and `billing.service.PAYMENT_REF_SQL` is the ONE expression
  that says which transfer a row belongs to. `CreditsOut.payments` publishes the
  reconciliation view built on it: one line per bank transfer, with everything that
  transfer has credited summed across all its rows, so a person with a statement open
  compares one figure to one figure.
- **The step-up is UNCONDITIONAL here, and that is not a copy of D-87 — it is its
  argument applied and coming out the other way.** D-87 gates the direction that is
  dangerous *within a bounded act*: both of its directions are capped by the named
  entry, and crediting back a usage charge is ordinary support work. Neither is true
  here. This route has one direction, it is unbounded (above), it moves money TO the
  party who will not report an error in their favour, and an over-credit that gets spent
  is recoverable only into a negative balance the client may never repay. So
  `X-Confirm-Action: restate_topup:<payment_ref>:<total>` is required on every call —
  and it echoes the AMOUNT, unlike `adjust_credits:<entry_id>`, because here the danger
  scales with the number rather than with which row was named. That also makes it the
  last guard against the one mistake the total shape can still admit: an operator who
  types the difference has to type it into the header too, and the console double-keys
  it beside the figure the reference already credits.

`record_topup` learned one thing from this and no more: its replay comparison and its
409 now read the reference's TOTAL rather than the anchor row's own amount, so a
restated payment re-posted at the corrected figure is the replay it actually is, and the
409 an operator meets when they first notice the shortfall names the route that fixes
it. Teaching `record_topup` a supplementary MODE was rejected: `POST .../credits`
guarantees unconditionally that a reference already on the wallet never moves money, and
a flag in the body would make that guarantee conditional on a field a form bug or a
copy-pasted body can set.

## THE GRANT (`POST .../credits/grants`) — D-535

The two repairs above both correct something that already happened. Neither can do what the
founder asked for in as many words: *"the admin should be able to add any no.of credits
without any payments record to any client but it is audited"*. The adjustment must NAME a
wrong entry and is bounded by that entry's magnitude — that is what makes it a correction
rather than a gift — and `POST .../credits` would put a payment reference on the ledger for
a bank transfer that never happened, which is the lie D-39 declined to seed opening balances
over. So this is a new path rather than a new reason on an old one, and five things carry
it.

- **A SIXTH LEDGER REASON, `grant`.** `billing/models.CREDIT_REASONS` argues which of the
  five existing ones it is not and why each was rejected; the short version is that
  reconciliation reads every `topup` as part of a bank transfer, every `adjustment` as
  bounded by a named row, and every `bonus` as earned on a payment that can be refunded —
  and a goodwill grant is none of those things.
- **BOUGHT AND GIVEN NEVER BLUR, on any screen.** `service.credit_totals` is the one
  definition and both the operator's wallet read (`CreditsOut.paid_inr` / `granted_inr`) and
  the client's own statement (`billing/wallet.WalletSummary.totals`) publish it. That is the
  founder's first guardrail, and it is not only presentation: granted credit that read as
  paid would inflate the revenue side of our own margin figures.
- **A CEILING PER GRANT** (`service.MAX_GRANT_INR`, ₹50,000), so the founder's own example
  — ₹5,00,000 typed for ₹5,000 — is refused rather than posted. It is checked BEFORE the
  step-up, so an operator who typed the wrong number is told the number is wrong instead of
  being sent to fix a header and re-submit the typo.
- **THE STEP-UP IS UNCONDITIONAL AND CARRIES THE AMOUNT.** `X-Confirm-Action:
  grant_credits:<amount>` on every call, which is the restatement's shape rather than the
  adjustment's, and for the same argument: one direction, moving money towards the party who
  will not report an error in their favour, with the danger scaling by the figure rather
  than by which row was named. `credit_grant_confirmation` also records WHAT CONTROL THIS
  STANDS IN FOR — segregation of duties and a second approver, which the founder waived
  because they are the only operator today, and which returns the moment anyone else holds
  admin access.
- **THE AUDIT ROW COMMITS WITH THE MONEY.** "Audited" is the founder's own word and the one
  control here that no ceiling substitutes for: `audit_log` is append-only and hash-chained,
  `write_audit` appends in the ledger's own transaction, and the operator's `reason` goes in
  verbatim. A grant with no audit row is not a reachable state.

Idempotent on an operator-supplied `grant_ref` rather than a content address, which is the
one place this deliberately departs from `adjustment_ref` — `service.grant_ref` argues it:
two genuinely distinct gifts of ₹5,000 to one client two months apart are ordinary, and a
content address would report the second as a replay of the first.

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
    GRANT_META_KIND,
    LOW_BALANCE_INR,
    MAX_GRANT_INR,
    MIN_GRANT_INR,
    PAYMENT_REF_SQL,
    RESTATEMENT_META_KIND,
    CorrectableEntry,
    adjustment_ref,
    credit_totals,
    find_entry_by_ref,
    find_topup,
    get_balance,
    grant_ref,
    lock_tenant_credits,
    read_correctable_entry,
    read_recorded_payment,
    record_entry,
    recorded_payments,
    restatement_ref,
    reversed_amounts,
    to_paise,
)
from apps.api.compliance.audit import write_audit
from apps.api.compliance.service import credits_exhausted
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.core.stepup import StepUpGate
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


def refuse_json_float(value: Any) -> Any:
    """Hard rule 7 at the edge, in ONE function for every money field on this router.

    REFUSED rather than quietly rounded: `2500.10` parsed as a binary float and back is
    how a paise-level dispute starts. Send `"2500.10"` — which is also how every money
    field in our responses is serialized, so a client echoing our own shape is already
    correct.

    A module function rather than only a `MoneyIn` method, because the third write on
    this router names its amount for what it holds (`corrected_amount_inr` is a TOTAL,
    not a movement) and so cannot inherit the field. Sharing the refusal rather than the
    field name keeps one definition of the rule while letting each body say what its
    number means — the alternative was three surfaces spelling one amount `amount_inr`
    with three different meanings.
    """
    if isinstance(value, float):
        raise ValueError('money crosses the wire as a string ("2500.00"), never as a JSON float')
    return value


class MoneyIn(Strict):
    """A request body carrying one rupee amount, with hard rule 7 applied at the edge.

    Both the top-up and the adjustment take an amount TO MOVE and both must refuse a
    JSON float, so the refusal lives once. `max_digits`/`decimal_places` mirror the
    column — MONEY is NUMERIC(12,4), so eight integer digits is the ceiling and anything
    finer than a paisa is a typo.
    """

    amount_inr: Decimal = Field(max_digits=10, decimal_places=2)

    @field_validator("amount_inr", mode="before")
    @classmethod
    def _never_a_float(cls, value: Any) -> Any:
        return refuse_json_float(value)


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


class GrantIn(MoneyIn):
    """Credit the founder is GIVING this client, out of nothing (D-535).

    The founder: *"the admin should be able to add any no.of credits without any payments
    record to any client but it is audited"*. Neither of the two writes above can do it —
    `/adjustments` must name a wrong entry and is bounded by that entry's magnitude, and
    `POST .../credits` would put a payment reference on the ledger for a bank transfer that
    never happened.
    """

    #: THE IDEMPOTENCY KEY, and it is the CALLER'S. A grant has no external identifier of
    #: its own — no UTR, no entry it corrects — and content-addressing it over (amount,
    #: reason) would collapse two GENUINELY DISTINCT gifts of ₹5,000 to one client two
    #: months apart onto one key and report the second as a replay of the first: a gift the
    #: client never received, reported as delivered. So the console mints one per opened
    #: form, which converges on a second CLICK and separates on a second DECISION — the
    #: shape `TopUpIn.payment_ref` already has. `billing.service.grant_ref` argues it in
    #: full.
    grant_ref: str = Field(min_length=3, max_length=120)
    #: The operator's own words, required for `AdjustmentIn.reason`'s reason and more so
    #: here: credit that appeared on a wallet with no payment behind it and no explanation
    #: is exactly the row an auditor stops on. It reaches `meta` and the audit summary
    #: verbatim.
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("grant_ref")
    @classmethod
    def _trimmed(cls, value: str) -> str:
        """`TopUpIn._trimmed`'s rule and its reason: a trailing space would make the SAME
        reference a DIFFERENT key and grant the credit twice."""
        trimmed = value.strip()
        if len(trimmed) < 3:
            raise ValueError("a grant reference is required")
        return trimmed

    @field_validator("reason")
    @classmethod
    def _not_only_whitespace(cls, value: str) -> str:
        trimmed = value.strip()
        if len(trimmed) < 3:
            raise ValueError("say why this credit is being granted")
        return trimmed


class GrantOut(Strict):
    tenant_id: UUID
    #: The `grant` entry that was appended (or the one that already existed).
    entry_id: UUID
    #: The reference the operator supplied.
    grant_ref: str
    #: The row's own ledger reference — `grant:<grant_ref>`.
    ref: str
    amount_inr: Decimal
    balance_inr: Decimal
    is_low: bool
    #: WHAT THIS WALLET HAS BEEN GIVEN IN TOTAL, and what it has been PAID for, lifetime.
    #: Published on the write as well as the read because the founder's guardrail is that
    #: the two never blur, and an operator granting the fifth ₹5,000 of the month should see
    #: the running figure at the moment they do it rather than on a screen they might not
    #: open. `granted_inr` includes pack bonuses, which are credit we fund too.
    paid_inr: Decimal
    granted_inr: Decimal
    #: False = this reference was already on the ledger and nothing moved. 200 either way,
    #: for the reason `TopUpOut.recorded` gives.
    recorded: bool


class RestatementIn(Strict):
    """A payment that credited LESS than the bank moved, described by the TRUE TOTAL.

    It does NOT inherit `MoneyIn`, and the field is not called `amount_inr`. The other
    two writes on this router take an amount to MOVE; this one takes the amount the
    payment WAS. One name for two meanings on one router is the confusion that would
    eventually be resolved at 2am by a tired operator, so the names differ and the
    shared part — the float refusal — is shared as a function.
    """

    #: The bank/UPI reference of the payment being restated. It must already be on this
    #: wallet: this route cannot create a payment, only correct what one credited.
    payment_ref: str = Field(min_length=3, max_length=120)
    #: THE TOTAL THE BANK ACTUALLY MOVED — not the difference. Read straight off the
    #: statement; the route works out what to credit and refuses a figure that is not an
    #: increase, which is also what catches an operator who typed the difference into a
    #: reference that has already been restated once.
    corrected_amount_inr: Decimal = Field(max_digits=10, decimal_places=2)
    #: The operator's own words, required for the reason `AdjustmentIn.reason` is: a
    #: credit that appears on a client's wallet without an explanation is the ticket
    #: nobody can close. It reaches the entry's `meta` and the audit row verbatim.
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("corrected_amount_inr", mode="before")
    @classmethod
    def _never_a_float(cls, value: Any) -> Any:
        return refuse_json_float(value)

    @field_validator("payment_ref")
    @classmethod
    def _trimmed(cls, value: str) -> str:
        """`TopUpIn._trimmed`'s rule, and it matters here for the mirror-image reason: a
        trailing space would make the SAME reference a DIFFERENT key, which on the
        top-up credits a payment twice and here restates a payment that does not exist
        (a 404 an operator cannot explain from a reference that is visibly on screen)."""
        trimmed = value.strip()
        if len(trimmed) < 3:
            raise ValueError("a payment reference is required")
        return trimmed

    @field_validator("reason")
    @classmethod
    def _not_only_whitespace(cls, value: str) -> str:
        trimmed = value.strip()
        if len(trimmed) < 3:
            raise ValueError("say why this payment is being restated")
        return trimmed


class RestatementOut(Strict):
    tenant_id: UUID
    #: The row that was appended (or the one that already existed).
    entry_id: UUID
    payment_ref: str
    #: The appended row's own ledger reference — `restated:<payment_ref>:<total>`.
    ref: str
    #: What THIS restatement credited: the corrected total less what the reference
    #: already credited. Always positive on a real write.
    added_inr: Decimal
    #: What the reference credits in TOTAL now, across every row that belongs to it.
    #: This is the figure that must equal the bank statement.
    credited_inr: Decimal
    balance_inr: Decimal
    is_low: bool
    #: False = this restatement was already on the ledger and nothing moved. 200 either
    #: way, for the reason `TopUpOut.recorded` gives.
    recorded: bool


class PaymentOut(Strict):
    """One bank transfer, as the wallet holds it — the reconciliation view.

    Published because a correction that had to be spread over two ledger rows must still
    read as ONE payment to the person holding a bank statement. They compare
    `credited_inr` against the statement line; `entries` tells them how many rows it took
    to get there, which is the only place a restatement is visible as such.
    """

    payment_ref: str
    credited_inr: Decimal
    #: 1 = recorded once and never corrected. More = it has been restated.
    entries: int
    first_at: datetime


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
    #: BOUGHT versus GIVEN, lifetime (D-535). The founder's first guardrail on granting
    #: credit out of nothing: a statement must distinguish credit a client paid for from
    #: credit we gave them, and the same split keeps granted credit out of what looks like
    #: revenue in our own margin figures. `granted_inr` covers `grant` and `bonus` — both
    #: are credit WE fund — while `paid_inr` is `topup` alone. Neither counts an
    #: `adjustment`: a correction belongs to whichever entry it names, and letting it
    #: subtract here would understate what a client was actually given.
    paid_inr: Decimal
    granted_inr: Decimal
    entries: list[LedgerEntryOut]
    #: The bank transfers behind the `topup` entries on this page, one line each,
    #: newest first. A restated payment occupies two rows in `entries` and exactly one
    #: line here — which is the whole point, and the only thing that lets a console
    #: offer a restatement without doing decimal arithmetic on money in a browser.
    payments: list[PaymentOut]


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

# The restatement path's first read, bound for the same reason: it is the read the write
# depends on (the credited total is the check half of a check-then-write), so it is the
# call the concurrency test has to be able to hold open inside the critical section.
_read_recorded_payment = read_recorded_payment


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


def credit_grant_confirmation(amount_inr: Decimal) -> str:
    """The step-up string for CREATING CREDIT OUT OF NOTHING.

    A named function for `credit_adjustment_confirmation`'s reason: the value is part of an
    operator procedure and must change by a deliberate edit that fails a test, never by a
    reformat that leaves a console sending a header the API refuses.

    **IT IS BOUND TO THE AMOUNT AND IT IS UNCONDITIONAL**, which is `topup_restatement_
    confirmation`'s shape rather than the adjustment's, and for the same argument coming out
    the same way. The adjustment gates only its dangerous DIRECTION because both of its
    directions are capped by the entry it names; this route has one direction, it moves
    money TOWARDS the party who will not report an error in their favour, and the only thing
    bounding it is `MAX_GRANT_INR`. The danger therefore scales with the NUMBER, so the
    confirmation carries the number: a header captured while granting ₹5,000 cannot be
    replayed to grant ₹50,000, and an operator who changes the figure has to key it twice.

    **IT IS ALSO STANDING IN FOR A CONTROL WE DO NOT HAVE.** The accounting standard for
    issuing credit out of nothing is segregation of duties — the person who issues a credit
    memo is not the person who records it, and a non-standard credit needs a second,
    managerial approval which internal audit later verifies (accountingtools.com,
    "Accounts receivable controls", and gaviti.com's AR internal-controls checklist, read as
    web-search summaries 4 Sep 2026; both hosts are egress-blocked from this container, so
    the summaries are what was read). The founder is the only person who holds admin access
    today and explicitly waived a second approver, so the gap is REAL and is recorded rather
    than papered over: what we have instead is a per-grant ceiling, a mandatory reason, an
    unconditional re-keying of the amount, and an append-only hash-chained `audit_log` row
    written in the same transaction as the money. **THE MOMENT A SECOND PERSON HOLDS
    `admin:tenants`, THIS CONTROL RETURNS** — a `superadmin`-only step-up or a two-operator
    approval on the shape `ops/routes.py` already uses for the unbounded switches. Nothing
    about that is hard; it is waiting on a second operator existing, which is not an
    engineering task.

    Quantized through `to_paise` so the header matches for `5000.0` and `5000.00`, exactly
    as `topup_restatement_confirmation` does and for the same reason: a confirmation that
    disagreed with the request would refuse the calls it exists to permit.
    """
    return f"grant_credits:{to_paise(amount_inr)}"


def topup_restatement_confirmation(payment_ref: str, corrected_amount_inr: Decimal) -> str:
    """The step-up string for restating an under-credited payment UPWARDS.

    A named function for the reason `credit_adjustment_confirmation` is one: the value
    is part of an operator procedure and must change by a deliberate edit that fails a
    test, never by a reformat that leaves a console sending a header the API refuses.

    It carries the AMOUNT as well as the reference, which
    `credit_adjustment_confirmation` deliberately does not. The adjustment's danger is
    "which row did you name" and is bounded once the row is named; this route's danger
    is "how much", it has no ceiling but the operator's own reading of a bank statement,
    and the confirmation is therefore bound to the exact figure. A confirmation captured
    while restating a UTR to ₹50,000 cannot be replayed to restate it to ₹500,000, and
    an operator who changes the number has to confirm the new one.

    Quantized through `to_paise` so the header matches for `50000.0` and `50000.00` —
    the same normalization `restatement_ref` applies, because a confirmation that
    disagreed with the key would refuse exactly the requests the key would deduplicate.
    """
    return f"restate_topup:{payment_ref}:{to_paise(corrected_amount_inr)}"


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
            # WHAT THIS REFERENCE CREDITS, not what the anchor row happens to hold. A
            # payment restated from ₹5,000 to ₹50,000 (D-89) is TWO `topup` rows, and
            # comparing against the first of them would tell an operator who re-posts
            # the corrected figure that their own repair is a conflicting payment. The
            # reference's total is the only figure the bank statement can be compared
            # with, so it is the figure this route answers on and refuses on.
            payment = await _read_recorded_payment(scoped, tenant_id=tenant_id, payment_ref=ref)
            assert payment is not None, "the anchor row was just found under this reference"
            if payment.credited_inr != amount:
                # Reusing a reference for a second, different payment would silently
                # swallow real money. Refusing is the only way anyone finds out — and
                # this refusal is also where an operator DISCOVERS an under-credit, so
                # the remediation names the route that repairs one rather than leaving
                # them to invent `UTR-123-part2`. Which of the two they are looking at
                # is decided by the direction, because the remedies are different
                # surfaces and offering both would be offering neither.
                raise ProblemError.conflict(
                    "topup_reference_conflict",
                    (
                        f"That payment reference already credits ₹{_paise(payment.credited_inr)} "
                        f"on this wallet, and this records ₹{_paise(amount)}."
                    ),
                    remediation=(
                        (
                            "If the bank moved the larger amount, restate the payment at "
                            f"/v1/admin/tenants/{tenant_id}/credits/restatements — it credits "
                            "the difference against this same reference, so the wallet still "
                            "shows one bank transfer. Never record the difference under an "
                            "annotated reference."
                        )
                        if amount > payment.credited_inr
                        else (
                            "If we credited more than the bank moved, take the difference back "
                            f"at /v1/admin/tenants/{tenant_id}/credits/adjustments, naming the "
                            "entry that was wrong. A second, genuine payment needs its own "
                            "reference."
                        )
                    ),
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
                # The reference's TOTAL, which for a payment that was never restated is
                # the anchor row's own amount — so nothing changes for the ordinary
                # replay, and a restated one answers with the figure it now credits.
                amount_inr=_paise(payment.credited_inr),
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
            ip=client_request_ip(request),
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
    # Resolved BEFORE this handler body runs, so the session read cannot happen inside an
    # open transaction — `core/stepup.py` on `max_overflow=0`.
    step_up: StepUpGate,
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
            step_up.require(x_confirm_action, credit_adjustment_confirmation(target.entry_id))

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
            ip=client_request_ip(request),
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


@router.post(
    "/restatements",
    response_model=RestatementOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Restate an UNDER-credited payment to the amount the bank actually moved",
    description=(
        "For a payment recorded for less than the bank transferred. Send the payment's "
        "own reference and the TOTAL the bank moved — not the difference; the route "
        "credits what is missing as a second entry against the same reference, so the "
        "wallet still shows one bank transfer and reconciliation keeps balancing. "
        "Sending the same total again returns the entry that already exists and moves "
        "nothing. Every call needs the header "
        "`X-Confirm-Action: restate_topup:<payment_ref>:<corrected_amount_inr>`, which "
        "echoes the amount because this correction has no ceiling but the statement in "
        "front of you. A total at or below what the reference already credits is "
        "refused — crediting less is an adjustment against the entry that was wrong."
    ),
)
async def record_restatement(
    tenant_id: UUID,
    payload: RestatementIn,
    request: Request,
    principal: CreditsWrite,
    # Resolved BEFORE this handler body runs, so the session read cannot happen inside an
    # open transaction — `core/stepup.py` on `max_overflow=0`.
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> RestatementOut:
    """The under-credit repair D-87 left open, and the reasons for each refusal.

    The ORDER of the checks is load-bearing, in the two places it decides what an
    operator is told:

    **The step-up runs before every read.** Unlike `record_adjustment` — where the
    direction being gated is a property of the target entry, so the target has to be
    read first — this route's gate depends on nothing but the request. Checking it first
    is what keeps a refusal free of information: a caller without the header learns
    nothing about which payments exist on this wallet, because the 403 is identical
    whether the reference is real or invented.

    **The replay lookup runs BEFORE the not-an-increase check**, for the reason D-87's
    ordering exists. Once a restatement lands, the reference credits exactly the total
    that was asserted, so `corrected <= credited` is TRUE for the very request that just
    succeeded — a second click would be told "that is not an increase" (a 422 that reads
    like a refusal) instead of "already restated, nothing moved" (a 200 that reads like
    the truth). The second click is the failure this route is designed around and it
    must land on the friendliest correct answer.

    Audited on a REAL write only — the convention `record_adjustment`,
    `record_commercial_terms` and `approve_kb` share. A replay changed nothing, and an
    audit row per button press makes "who put ₹45,000 on this client" harder to answer.
    """
    corrected = payload.corrected_amount_inr
    ref = payload.payment_ref
    if corrected <= 0:
        raise ProblemError.business_rule(
            "invalid_restatement_amount",
            "A restatement is what the bank actually moved, so it is a positive amount.",
            remediation=(
                "Send the TOTAL the statement shows for this reference. To take credit "
                "back instead, name the entry that was wrong on "
                f"/v1/admin/tenants/{tenant_id}/credits/adjustments."
            ),
        )

    # Before any read, and before the tenant is even confirmed to exist: the string is a
    # function of the request alone, so refusing here leaks nothing and writes nothing.
    step_up.require(x_confirm_action, topup_restatement_confirmation(ref, corrected))

    async with tenant_session(tenant_id) as scoped:
        await _assert_tenant_exists(scoped, tenant_id)
        # Before the payment read, exactly as the other two writes take it before theirs:
        # the credited total this route decides on is a read the write depends on, and
        # two operators restating one payment at the same moment would otherwise both
        # measure the shortfall from the same starting total and both credit it.
        await lock_tenant_credits(scoped, tenant_id)

        payment = await _read_recorded_payment(scoped, tenant_id=tenant_id, payment_ref=ref)
        if payment is None:
            # This route CANNOT create a payment — that is one of the two things standing
            # in for a numeric ceiling. Under RLS "no such reference" and "another
            # tenant's reference" are the same answer, deliberately.
            raise ProblemError.not_found("Payment reference")

        entry_ref = restatement_ref(payment_ref=ref, credited_total_inr=corrected)
        # `reason='topup'` on both sides of this lookup, because the row it is looking
        # for IS a top-up: it is part of a bank transfer that arrived.
        existing = await _find_entry_by_ref(
            scoped, tenant_id=tenant_id, reason="topup", ref=entry_ref
        )
        if existing is not None:
            balance = await get_balance(scoped, tenant_id=tenant_id)
            log.info(
                "credit_restatement_replay",
                extra={"tenant_id": str(tenant_id), "entry_id": str(existing.entry_id)},
            )
            return RestatementOut(
                tenant_id=tenant_id,
                entry_id=existing.entry_id,
                payment_ref=ref,
                ref=entry_ref,
                added_inr=_paise(existing.amount_inr),
                credited_inr=_paise(payment.credited_inr),
                balance_inr=_paise(balance.amount_inr),
                is_low=balance.is_low,
                recorded=False,
            )

        if corrected <= payment.credited_inr:
            # The one shape refused at the boundary rather than absorbed: an operator who
            # typed the DIFFERENCE instead of the total, or who is trying to correct
            # downwards. Both are real intentions and neither belongs here — the first
            # would credit the wrong figure silently, and the second has its own surface
            # that bounds itself by the entry it names.
            raise ProblemError.business_rule(
                "restatement_not_an_increase",
                (
                    f"That reference already credits ₹{_paise(payment.credited_inr)}, and "
                    f"this restates it to ₹{_paise(corrected)}."
                ),
                remediation=(
                    "Send the TOTAL the bank moved, not the difference — the amount to "
                    "credit is worked out here. If we credited MORE than the bank moved, "
                    f"that is a correction at /v1/admin/tenants/{tenant_id}/credits/"
                    "adjustments, naming the entry that was wrong."
                ),
            )

        added = corrected - payment.credited_inr
        meta: dict[str, Any] = {
            "kind": RESTATEMENT_META_KIND,
            # The link back to the bank transfer. `payments_by_ref` groups on it, which is
            # what lets the wallet still read as ONE payment after a restatement.
            "payment_ref": ref,
            "reason": payload.reason,
            # A rupee amount that goes into JSON as a NUMBER comes back out of some
            # reader as a float (hard rule 7), so all three go in as strings. They record
            # the ASSERTION, which is the thing a later reader wants and cannot
            # reconstruct: what this reference credited before, and what it was said to
            # have moved.
            "credited_before_inr": str(_paise(payment.credited_inr)),
            "credited_after_inr": str(_paise(corrected)),
            "added_inr": str(_paise(added)),
        }
        if principal.user_id:
            meta["recorded_by"] = str(principal.user_id)

        balance = await record_entry(
            scoped,
            tenant_id=tenant_id,
            delta=added,
            reason="topup",
            ref=entry_ref,
            meta=meta,
            # The delta is positive, so this can only raise the balance — but
            # `record_entry` refuses any write that LEAVES it negative, not just one that
            # makes it so. A wallet already at -₹50,000 (a wrong credit reversed after it
            # was spent) would otherwise have a genuine ₹1,000 credit refused as
            # `insufficient_credits`, which is the accounting layer refusing to record
            # money that actually arrived.
            allow_negative=True,
        )
        written = await _find_entry_by_ref(
            scoped, tenant_id=tenant_id, reason="topup", ref=entry_ref
        )
        assert written is not None, "the row was inserted in this transaction"

        # Same transaction as the insert: money never moves without its audit row.
        await write_audit(
            scoped,
            action="credit.topup_restated",
            actor=principal,
            tenant_id=tenant_id,
            object_type="credit_ledger",
            object_id=str(written.entry_id),
            ip=client_request_ip(request),
            summary={
                "payment_ref": ref,
                # Quantized, like the adjustment's and unlike the top-up's: these land in
                # an incident channel beside the figures the console showed, and
                # `45000.0000` next to `₹45,000.00` reads as a second, different number.
                "added_inr": str(_paise(added)),
                "credited_before_inr": str(_paise(payment.credited_inr)),
                "credited_after_inr": str(_paise(corrected)),
                "balance_after_inr": str(_paise(balance.amount_inr)),
                # The operator's own words — the field a later review of an unexplained
                # credit on a client's wallet is actually looking for.
                "reason": payload.reason,
            },
        )

    log.info(
        "credit_restatement",
        extra={
            "tenant_id": str(tenant_id),
            "entry_id": str(written.entry_id),
            # The reference is a bank identifier, not PII (hard rule 6 covers phone
            # numbers, transcripts and extraction payloads); it is already logged by the
            # audit summary and it is what makes this line answerable.
            "payment_ref": ref,
        },
    )
    return RestatementOut(
        tenant_id=tenant_id,
        entry_id=written.entry_id,
        payment_ref=ref,
        ref=entry_ref,
        added_inr=_paise(added),
        credited_inr=_paise(corrected),
        balance_inr=_paise(balance.amount_inr),
        is_low=balance.is_low,
        recorded=True,
    )


@router.post(
    "/grants",
    response_model=GrantOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Grant credit out of nothing — no payment, audited, shown separately from paid",
    description=(
        "Puts goodwill credit on a client's wallet with no payment behind it. It is NOT a "
        "top-up (no bank moved money) and NOT an adjustment (it corrects no entry), so it "
        "lands under its own ledger reason and every statement reports it separately from "
        "credit the client bought. Requires the header "
        "`X-Confirm-Action: grant_credits:<amount_inr to two decimals>` on every call, and "
        "one grant is capped so a mistyped figure is refused rather than posted. Sending "
        "the same `grant_ref` again returns the existing entry and moves nothing; the same "
        "reference with a different amount is a conflict."
    ),
    status_code=201,
)
async def grant_credits(
    tenant_id: UUID,
    payload: GrantIn,
    request: Request,
    principal: CreditsWrite,
    # Resolved BEFORE this handler body runs, so the session read cannot happen inside an
    # open transaction — `core/stepup.py` on `max_overflow=0`.
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> GrantOut:
    amount = payload.amount_inr
    # THE CEILING FIRST, BEFORE THE STEP-UP IS EVEN CHECKED. An operator who typed
    # ₹5,00,000 should be told the number is impossible, not told their confirmation header
    # is wrong — the second reading sends them to fix the header and re-submit the typo.
    if amount < MIN_GRANT_INR or amount > MAX_GRANT_INR:
        raise ProblemError.business_rule(
            "invalid_grant_amount",
            (
                f"A grant is between ₹{MIN_GRANT_INR:,.0f} and ₹{MAX_GRANT_INR:,.0f}. "
                f"This asked for ₹{_paise(amount)}."
            ),
            remediation=(
                "Check the figure. If a larger gift really is intended, grant it in parts — "
                "each part is separately confirmed and separately audited, which is the "
                "trail a credit this size should leave anyway."
            ),
        )
    step_up.require(x_confirm_action, credit_grant_confirmation(amount))

    ref = grant_ref(reference=payload.grant_ref)
    async with tenant_session(tenant_id) as scoped:
        await _assert_tenant_exists(scoped, tenant_id)
        # BEFORE the lookup, through the same function every other credit writer uses: two
        # operators granting under one reference at the same moment would otherwise both
        # read "not present" and both insert. `ux_credit_ledger_grant_ref` is the backstop
        # behind it, never the primary guarantee (D-63).
        await lock_tenant_credits(scoped, tenant_id)

        existing = await _find_entry_by_ref(scoped, tenant_id=tenant_id, reason="grant", ref=ref)
        if existing is not None:
            if existing.amount_inr != amount:
                # The same reference for a DIFFERENT amount is not a replay — it is either a
                # second gift that needs its own reference or a corrected figure, and the two
                # have different remedies. Silently crediting the difference (or silently
                # ignoring it) would make a reference stop meaning one act.
                raise ProblemError.conflict(
                    "grant_reference_conflict",
                    (
                        f"That grant reference already credits ₹{_paise(existing.amount_inr)} "
                        f"on this wallet, and this asks for ₹{_paise(amount)}."
                    ),
                    remediation=(
                        "A second, genuine grant needs its own reference. To correct the "
                        f"amount of the one already there, post to /v1/admin/tenants/"
                        f"{tenant_id}/credits/adjustments naming that entry — the wrong row "
                        "stays on the ledger, because it is the evidence, and the new one "
                        "cancels it."
                    ),
                )
            balance = await get_balance(scoped, tenant_id=tenant_id)
            totals = await credit_totals(scoped, tenant_id=tenant_id)
            log.info(
                "credit_grant_replay",
                extra={"tenant_id": str(tenant_id), "entry_id": str(existing.entry_id)},
            )
            return GrantOut(
                tenant_id=tenant_id,
                entry_id=existing.entry_id,
                grant_ref=payload.grant_ref,
                ref=ref,
                amount_inr=_paise(existing.amount_inr),
                balance_inr=_paise(balance.amount_inr),
                is_low=balance.is_low,
                paid_inr=_paise(totals.paid_inr),
                granted_inr=_paise(totals.granted_inr),
                recorded=False,
            )

        meta: dict[str, Any] = {"kind": GRANT_META_KIND, "reason": payload.reason}
        if principal.user_id:
            meta["granted_by"] = str(principal.user_id)
        balance = await record_entry(
            scoped,
            tenant_id=tenant_id,
            delta=amount,
            reason="grant",
            ref=ref,
            meta=meta,
        )
        written = await _find_entry_by_ref(scoped, tenant_id=tenant_id, reason="grant", ref=ref)
        assert written is not None, "the row was inserted in this transaction"
        totals = await credit_totals(scoped, tenant_id=tenant_id)

        # THE AUDIT ROW COMMITS WITH THE MONEY. "Audited" is the founder's own word and the
        # one control this route has that no ceiling can substitute for: `audit_log` is
        # append-only and hash-chained, `write_audit` appends in THIS transaction, so a
        # grant with no audit row is not a reachable state. The operator's own words go in
        # verbatim — a later review of an unexplained credit is looking for exactly that
        # field.
        await write_audit(
            scoped,
            action="credit.grant",
            actor=principal,
            tenant_id=tenant_id,
            object_type="credit_ledger",
            object_id=str(written.entry_id),
            ip=client_request_ip(request),
            summary={
                "grant_ref": payload.grant_ref,
                # Quantized, like the adjustment's and the restatement's: these land in an
                # incident channel beside the figures the console showed, and `5000.0000`
                # next to `₹5,000.00` reads as a second, different number.
                "amount_inr": str(_paise(amount)),
                "balance_after_inr": str(_paise(balance.amount_inr)),
                "granted_total_inr": str(_paise(totals.granted_inr)),
                "reason": payload.reason,
            },
        )

    log.info(
        "credit_granted",
        extra={"tenant_id": str(tenant_id), "entry_id": str(written.entry_id)},
    )
    return GrantOut(
        tenant_id=tenant_id,
        entry_id=written.entry_id,
        grant_ref=payload.grant_ref,
        ref=ref,
        amount_inr=_paise(amount),
        balance_inr=_paise(balance.amount_inr),
        is_low=balance.is_low,
        paid_inr=_paise(totals.paid_inr),
        granted_inr=_paise(totals.granted_inr),
        recorded=True,
    )


@router.get(
    "",
    response_model=CreditsOut,
    openapi_extra=permission_meta("billing:read"),
    summary="Wallet balance plus the recent ledger entries, newest first",
)
async def read_credits(
    tenant_id: UUID,
    principal: CreditsRead,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> CreditsOut:
    async with tenant_session(tenant_id) as scoped:
        await _assert_tenant_exists(scoped, tenant_id)
        balance = await get_balance(scoped, tenant_id=tenant_id)
        # One extra aggregate over the whole wallet, deliberately NOT scoped to the page:
        # "how much of this did we fund" is a lifetime fact, and a figure that shrank as an
        # operator paged backwards would be worse than no figure at all.
        totals = await credit_totals(scoped, tenant_id=tenant_id)
        rows = (
            await scoped.execute(
                # RLS already scopes this; the predicate is what makes it an index
                # scan on ix_credit_ledger_tenant_recent. Same ordering as
                # `get_balance`, so entries[0].balance_after_inr IS the balance.
                text(
                    "SELECT id, delta, reason, ref, balance_after, occurred_at, "
                    # WHICH BANK TRANSFER this row belongs to — NULL for anything that is
                    # not a payment. Selected rather than derived here so the grouping
                    # below and the write path's guard read one definition
                    # (`billing.service.PAYMENT_REF_SQL`); a restatement's own `ref` is
                    # `restated:<payment_ref>:<total>`, so pairing it with its payment by
                    # string surgery in this file would be a second definition waiting to
                    # drift from the first.
                    f"{PAYMENT_REF_SQL} "
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
        # THE BANK TRANSFERS BEHIND THE PAGE, deduplicated. Each total is summed over ALL
        # of that payment's rows, not only the ones on this page — a payment restated
        # long ago whose anchor has scrolled off would otherwise be published at less
        # than it credits, which is the one kind of wrong this whole slice exists to end.
        payments = await recorded_payments(
            scoped,
            tenant_id=tenant_id,
            payment_refs=sorted({str(row[6]) for row in rows if row[6] is not None}),
        )
        # D-482 L-1: a direct-admin read of one client's wallet joins the audit trail.
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=tenant_id
        )

    return CreditsOut(
        tenant_id=tenant_id,
        balance_inr=_paise(balance.amount_inr),
        is_low=balance.is_low,
        low_balance_threshold_inr=_paise(LOW_BALANCE_INR),
        paid_inr=_paise(totals.paid_inr),
        granted_inr=_paise(totals.granted_inr),
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
        # Newest payment first, matching the ledger's own ordering, so the two panels on
        # one screen never disagree about which way round time runs. Sorted here rather
        # than in SQL because the grouped read answers a set of references, not a page.
        payments=[
            PaymentOut(
                payment_ref=payment.payment_ref,
                credited_inr=_paise(payment.credited_inr),
                entries=payment.rows,
                first_at=payment.first_at,
            )
            for payment in sorted(payments.values(), key=lambda p: p.first_at, reverse=True)
        ],
    )


__all__ = ["router"]
