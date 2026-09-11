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
number or a DLT status, all of which are `admin:tenants` — the permission D-587 withholds
from a view-as session precisely because acting on a client's record is an
operator-console act, so this is reached as ourselves and recorded as ourselves.

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

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin.service import tenant_exists
from apps.api.billing.credit_packs import PACK_CATALOGUE, CreditPack, pack_by_id
from apps.api.billing.lots import split_meta
from apps.api.billing.rates import voice_tier_label
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
    apply_credit_to_lots,
    credit_totals,
    find_entry_by_ref,
    find_topup,
    get_balance,
    grant_ref,
    lock_tenant_credits,
    lot_of_entry,
    lot_reprice_ref,
    rate_card_at,
    read_correctable_entry,
    read_recorded_payment,
    record_entry,
    recorded_payments,
    remove_credit_from_lots,
    reprice_lot,
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

#: THE LOT ITSELF, addressed by id — a second router because the object is different.
#:
#: Everything on `router` above is a write to the WALLET: an amount arrives, or is taken
#: back, and a lot is a consequence of it. The re-price below acts on ONE LOT that already
#: exists and moves no money at all, so `/credits/...` would name the wrong noun and the
#: path would have to carry the lot id in a query string to get at it. It is the path the
#: console already posts to (`apps/web/src/lib/api/creditLots.ts::lotOverridePath`).
lots_router = APIRouter(prefix="/v1/admin/tenants/{tenant_id}/credit-lots", tags=["admin"])

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

#: A rupee amount of nothing, at the wire's own scale. A named constant rather than
#: `Decimal("0.00")` at four call sites, so "no overdraft" and "no money" are one literal.
_ZERO = _paise(Decimal("0"))


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
    #: **SELL THIS PURCHASE'S CREDIT AT ANOTHER PACK'S RATES (D-547 Q6).** Absent for every
    #: ordinary payment, and absent is the default because a departure from the card must be
    #: an act somebody performed, never a shape a body can fall into.
    #:
    #: WHY IT IS APPLIED HERE AND NOT AFTERWARDS. A lot's two rates are FROZEN at creation —
    #: `credit_lots_terms_frozen` refuses any UPDATE that touches them, which is invariant 3
    #: and the promise the whole store exists to keep — so "sell it cheaper" is only
    #: expressible at the instant the credit is booked. There is no route that could edit it
    #: later, and there must not be one.
    #:
    #: It names a pack whose RATES are borrowed; the lot records that borrowing
    #: (`override_of_pack_id`) so a reader a year later can see the promise was deliberate
    #: and whose terms it copied. The founding-client promotion is the case this was built
    #: for ("the first pack of any size at the ₹25,000 pack's rates"), and any negotiated
    #: deal takes the same path.
    rates_of_pack_id: str | None = Field(default=None, max_length=64)
    #: WHY these rates, in the operator's own words. REQUIRED when `rates_of_pack_id` is
    #: set and refused otherwise — a departure from the published card with no stated ground
    #: is the row an auditor stops on, and an ordinary top-up has `note` for its remarks.
    override_reason: str | None = Field(default=None, min_length=3, max_length=500)

    @field_validator("override_reason")
    @classmethod
    def _reason_not_only_whitespace(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if len(trimmed) < 3:
            raise ValueError("say why this purchase is being sold at another pack's rates")
        return trimmed

    @model_validator(mode="after")
    def _override_is_all_or_nothing(self) -> TopUpIn:
        """The pack and the reason travel together, in both directions.

        A pack with no reason is an unexplained departure from the card; a reason with no
        pack is an operator who believes they applied one and did not — the second is the
        worse failure, because nothing on the resulting lot would ever say so.
        """
        if self.rates_of_pack_id is not None and self.override_reason is None:
            raise ValueError("override_reason is required when rates_of_pack_id is set")
        if self.rates_of_pack_id is None and self.override_reason is not None:
            raise ValueError("override_reason means nothing without rates_of_pack_id")
        return self

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
    #: THE LOT THIS PAYMENT OPENED, or `null` when it opened none — a payment wholly
    #: absorbed by an overdraft opens nothing, and that is the case an operator most needs
    #: to see, because the client's runway did not move by what they paid.
    lot: CreditLotOut | None


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
    #: WHAT THIS CORRECTION COULD NOT TAKE OFF A LOT, because the credit had already been
    #: spoken — it is wallet OVERDRAFT, and this is the operator's warning that they have
    #: created some. `0.00` on every correction that fitted, and on every credit-BACK
    #: (that direction adds credit and cannot overdraw).
    #:
    #: ⚠ **IT IS NOT `RestatementOut.lot_shortfall_inr`'s null.** That route restates a
    #: payment UPWARDS only, so its shortfall can never exist; this one is the downward
    #: direction, where it is computed and — until now — thrown away while the FULL
    #: correction was written to the ledger. The lots and the balance then disagreed for
    #: ever (`service.remove_credit_from_lots` carries the worked example). The lots are
    #: now drained to match, and this is what is left over when even that was not enough:
    #: the client's wallet is negative by this much and their outbound dialling has
    #: stopped, which `stops_dialling` above says in the other vocabulary.
    lot_shortfall_inr: Decimal
    #: THE LOT THIS CORRECTION OPENED, and only that (D-547). It is present exactly when
    #: the correction CREDITED the client back, because that direction opens a fresh lot at
    #: the list rates (a gift is spent at the standard price, plan §0 Q4). Taking credit
    #: AWAY opens nothing: it restates the corrected purchase's own lot downwards or is
    #: spent off the queue, and both are movements of lots that already exist — the wallet
    #: read below is what shows their new state. `null` on both of those and on a replay.
    lot: CreditLotOut | None


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


class CreditLotOut(Strict):
    """ONE LOT, as the admin wallet screen reads it (D-547).

    A lot is what one purchase, grant or migration created: credits, and the two per-minute
    rates FROZEN onto them at that instant. It is the object an operator is opening when
    they credit a wallet, which is why every write below returns the one it touched rather
    than leaving the console to guess which of five lots moved.

    **BOTH VENDOR SPELLINGS AND BOTH CLIENT LABELS.** `sarvam_inr_per_min` names the vendor
    because an operator has to connect a rate to the key they installed and the invoice they
    attested; `sarvam_label` is what the client reading their own screen calls it, so a
    support call is one vocabulary. Neither is composed in the browser.

    Money and rates are exact decimal STRINGS on the wire for hard rule 7's reason — a rate
    a browser parsed into a float and printed back is a rate nobody can reconcile. They are
    typed `Decimal` here and serialise as strings through the same JSON encoder every other
    money field on this router uses.
    """

    lot_id: UUID
    #: `topup` | `grant` | `bonus_legacy` | `migration` | `override` — as stored. A string
    #: rather than an enum on the wire: a lot written by an older build must still render.
    source: str
    #: The pack whose rates this lot carries, when a pack decided them.
    pack_id: str | None
    #: Set when an operator sold this lot at ANOTHER pack's rates (Q6, audited). It is the
    #: field that answers "why is this client's minute cheaper than the card" from the row
    #: itself rather than from an audit search.
    override_of_pack_id: str | None
    credits_total: Decimal
    credits_remaining: Decimal
    sarvam_inr_per_min: Decimal
    cartesia_inr_per_min: Decimal
    #: `billing/rates.VOICE_TIER_LABELS`, over the wire.
    sarvam_label: str
    cartesia_label: str
    opened_at: datetime
    #: When this lot was spent to nothing, or `null` while it still has credit on it. The
    #: queue read below returns OPEN lots only, so it is `null` on every row there; it is
    #: a real value on the lot a WRITE hands back, because a downward restatement can
    #: close the lot it corrects and the receipt has to say so rather than showing a lot
    #: with credit the client no longer has.
    closed_at: datetime | None


class OverridePackOut(Strict):
    """One pack an operator may sell a purchase at the rates of (Q6).

    Published by the wallet read rather than kept in the console, for the reason every
    other list here is: a pack ladder spelled twice is a ladder that drifts, and the rates
    shown beside each option have to be the ones the write will actually freeze.
    """

    pack_id: str
    amount_inr: Decimal
    sarvam_inr_per_min: Decimal
    cartesia_inr_per_min: Decimal


class LotRepriceIn(Strict):
    """Sell credit a client ALREADY HOLDS at another pack's rates (plan §0 Q6).

    **IT IS NOT `TopUpIn.rates_of_pack_id`, AND THE TWO ARE NOT ONE CAPABILITY.** That
    field prices credit AS IT ARRIVES: an operator recording a bank transfer says "open
    this at the ₹25,000 pack's rates", and the decision is made once, at the instant the
    money is booked — which is also the only instant it CAN be made there, because a lot's
    rates are frozen the moment it exists. This one CORRECTS a decision already made, on
    credit the client is holding: the promotion nobody applied at the till, the rate
    negotiated after the transfer landed, the founding-client deal agreed in week three.
    Two acts, two audiences, two audit actions, two step-up strings; neither is reachable
    from the other's surface and collapsing them would mean either re-opening a settled
    purchase or refusing to honour a promise already made.
    """

    #: WHOSE RATES. The choices are `CreditsOut.override_packs`, published by the wallet
    #: read, so the console never keeps a pack ladder of its own.
    pack_id: str = Field(min_length=1, max_length=64)
    #: The operator's own words, required for `AdjustmentIn.reason`'s reason and more so
    #: here: a below-card rate that appears on a client's lot with no explanation is
    #: exactly the row a later margin review stops on. It reaches the marker entry's
    #: `meta` and the audit row verbatim.
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def _not_only_whitespace(cls, value: str) -> str:
        trimmed = value.strip()
        if len(trimmed) < 3:
            raise ValueError("say why this credit is being re-priced")
        return trimmed


class LotRepriceOut(Strict):
    """What a re-price did. TWO lots, because it is a close-and-replace and not an edit."""

    tenant_id: UUID
    #: The lot that was CLOSED, at its own original terms. It stays on the table for ever
    #: as the truthful record of what was sold; `credit_lots_terms_frozen` is what makes
    #: that a fact rather than an intention.
    closed_lot_id: UUID
    #: THE LOT NOW CARRYING THE CREDIT, at the chosen pack's rates. It inherits the closed
    #: lot's `opened_at`, so the client's spend order does not move — read back from the
    #: row rather than assembled here, for `_read_lot`'s reason.
    lot: CreditLotOut
    #: The ZERO-DELTA marker entry the replacement names, and its ledger reference. No
    #: money moved in either direction; the row exists because `credit_lots.ledger_entry_id`
    #: is NOT NULL and a lot must name an entry.
    entry_id: UUID
    ref: str
    #: What moved across — the closed lot's remaining credit.
    credits_inr: Decimal
    #: False = this exact re-price was already on the ledger and nothing happened. 200
    #: either way, for the reason `TopUpOut.recorded` gives.
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
    #: THE LOT THE MONEY LANDED ON — the purchase's OWN lot, restated upwards, not a new
    #: one behind it. Its two rates are unchanged and are repeated here deliberately: "a
    #: restatement moves totals and never rates" is the promise the client was sold, and
    #: the receipt states it rather than leaving an operator to infer it from a table that
    #: happens not to have moved. `null` for a payment that predates lots and opened none.
    lot: CreditLotOut | None
    #: What a DOWNWARD restatement could not take off the lot because it was already spent
    #: (ADDENDUM 2 §2.2) — it becomes wallet overdraft, repaid by the next purchase before
    #: a new lot opens.
    #:
    #: ⚠ **ALWAYS `null` ON THIS ROUTE, AND THAT IS NOT A STUB.** This surface restates a
    #: payment UPWARDS only (`restatement_not_an_increase` refuses the other direction), and
    #: credit being ADDED to a lot can never fail to fit. The downward case is
    #: `/adjustments`, where the shortfall is computed inside
    #: `service.remove_credit_from_lots` and discarded rather than returned — publishing it
    #: there is a change to that function's return type, which is not this lane's file.
    #: The field is here because the console reads it on this response; it will be `null`
    #: until that handoff lands.
    lot_shortfall_inr: Decimal | None


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
    #: THE OPEN LOT QUEUE, oldest first — the order it will be spent in. Only OPEN lots:
    #: a closed one is spent history and is answered by the ledger entries above, and a
    #: list mixing the two would truncate the live queue at the page size. Bounded by the
    #: same `limit` as the entries.
    lots: list[CreditLotOut]
    #: The packs a purchase may be sold at the rates of (Q6) — the choices, with the rates
    #: each one would freeze, so the console renders no catalogue of its own.
    override_packs: list[OverridePackOut]
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


def lot_rate_override_confirmation(pack_id: str) -> str:
    """The step-up string for selling a purchase at ANOTHER pack's rates (Q6).

    A named function with a test pinning the literal, like every other confirmation here.
    Bound to the PACK whose rates are borrowed rather than to the tenant or the amount,
    because the pack is the whole content of the decision: a header captured while opening
    a lot at the ₹25,000 pack's rates must not be replayable to open one at the ₹50,000
    pack's, which is a cheaper minute again and for ever (the rates never change after the
    lot exists).

    It is deliberately NOT bound to the payment reference: an operator who mistypes the UTR
    and re-submits has changed nothing about the decision they confirmed, and forcing a
    second confirmation for a corrected typo trains people to click through them.
    """
    return f"override_lot_rates:{pack_id}"


def lot_reprice_confirmation(lot_id: UUID) -> str:
    """The step-up string for re-pricing credit a client ALREADY HOLDS (Q6).

    Bound to the LOT, which is the whole content of this decision: a header captured while
    looking at a ₹2,000 lot must not be replayable against the ₹50,000 one beside it, and
    the pack is chosen on the same screen and re-keyed with it.

    **IT SHARES A PREFIX WITH `lot_rate_override_confirmation` AND CANNOT COLLIDE WITH IT.**
    That one is bound to a PACK id (`starter`, `pro`) and gates the purchase-time override
    on the top-up route; this one is bound to a lot's UUID. No pack id is a UUID and no lot
    id is a pack name, so the two namespaces are disjoint by the shape of their values —
    and the prefix is shared deliberately, because an operator reading a rejected header in
    a console log is looking at the same class of act either way. `tests/` pins both
    literals, as it does for every confirmation here.
    """
    return f"override_lot_rates:{lot_id}"


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


def _override_pack(payload: TopUpIn) -> CreditPack | None:
    """The pack whose rates this top-up borrows, or `None` for an ordinary payment.

    Refuses an id this build does not offer, with the sentence rather than a `None` that
    would silently fall back to the free-amount rule and open the lot at the card price —
    a promise made to a client and quietly not kept, which is the failure this whole route
    is guarding against. `pack_by_id` is total by design (a historical id read back off a
    ledger row must resolve to "unknown" rather than raise), so the refusal is made HERE,
    where the id is an operator's live input rather than a stored fact.
    """
    if payload.rates_of_pack_id is None:
        return None
    pack = pack_by_id(payload.rates_of_pack_id)
    if pack is None:
        raise ProblemError(
            kind="not_found",
            code="unknown_credit_pack",
            title="No such credit pack",
            detail=f"{payload.rates_of_pack_id!r} is not a pack on the current rate card.",
            remediation=(
                "Rates can only be borrowed from a pack the card offers today. The pack "
                "list is at /v1/billing/topups/packs; send its `pack_id` exactly."
            ),
        )
    return pack


#: The lot columns this console renders, in one place so the by-id read and the queue read
#: cannot select different things. RLS scopes both: the policy is
#: `tenant_id = current_setting('app.tenant_id')::uuid` for every verb, so a lot belonging
#: to another tenant is not visible to ask about (`lots._SELECT_ONE_OPEN_LOT`'s argument).
_LOT_FIELDS = (
    "SELECT id, source, pack_id, override_of_pack_id, credits_total, credits_remaining, "
    "sarvam_inr_per_min, cartesia_inr_per_min, opened_at, closed_at FROM credit_lots "
)


def _lot_out(row: Any) -> CreditLotOut:
    """One row as the console reads it, with the two client labels attached.

    The labels come from `billing/rates.voice_tier_label` — the ONE definition — rather
    than from a literal here, so the day "Studio" is renamed the console follows without a
    second edit and no vendor name can leak onto a client's screen through a support call.
    """
    return CreditLotOut(
        lot_id=UUID(str(row[0])),
        source=str(row[1]),
        pack_id=None if row[2] is None else str(row[2]),
        override_of_pack_id=None if row[3] is None else str(row[3]),
        # `Decimal(str(...))` on every NUMERIC read, the convention this tree keeps: the day
        # a driver hands back a float, a frozen rate must not inherit the binary error.
        credits_total=Decimal(str(row[4])),
        credits_remaining=Decimal(str(row[5])),
        sarvam_inr_per_min=Decimal(str(row[6])),
        cartesia_inr_per_min=Decimal(str(row[7])),
        sarvam_label=voice_tier_label("sarvam"),
        cartesia_label=voice_tier_label("cartesia"),
        opened_at=row[8],
        closed_at=row[9],
    )


async def _lot_of_entry(session: AsyncSession, *, entry_id: UUID) -> CreditLotOut | None:
    """The lot ONE ledger row opened, if it opened one.

    `ledger_entry_id` is UNIQUE on `credit_lots`, so this is at most one row — the same
    fact `service.lot_of_entry` rests on. It is a second SELECT rather than a call to that
    function because that one answers "how big was this purchase" (two columns, for the
    correction ceiling) and this one renders a lot; asking it and then re-reading the row
    by id would be two round trips for one answer.
    """
    row = (
        await session.execute(
            text(f"{_LOT_FIELDS} WHERE ledger_entry_id = :eid"), {"eid": entry_id}
        )
    ).first()
    return None if row is None else _lot_out(row)


async def _read_lot(session: AsyncSession, *, lot_id: UUID | None) -> CreditLotOut | None:
    """The lot a write just touched, read back from the row rather than assembled here.

    Read back rather than composed from the arguments the caller passed, because what the
    console has to show is what the LOT says: a restatement lands on an existing lot whose
    rates are its own and are not the ones this request named, and an amount that repaid an
    overdraft never reached a lot at all (`lot_id` is `None`, and so is this).
    """
    if lot_id is None:
        return None
    row = (await session.execute(text(f"{_LOT_FIELDS} WHERE id = :id"), {"id": lot_id})).first()
    return None if row is None else _lot_out(row)


async def _open_lots(session: AsyncSession, *, tenant_id: UUID, limit: int) -> list[CreditLotOut]:
    """The wallet's OPEN lots, oldest first — the order `lots.consume` spends them in.

    `ORDER BY opened_at, id` is `lots._SELECT_OPEN_LOTS`' own ordering, spelled the same
    way so the queue an operator reads is the queue a call is charged from. `tenant_id` is
    in the predicate as well as in RLS for the reason every other read here carries it: it
    is what makes this the index scan the FIFO index was created for.
    """
    rows = (
        await session.execute(
            text(
                f"{_LOT_FIELDS} WHERE tenant_id = :tid AND closed_at IS NULL "
                "ORDER BY opened_at, id LIMIT :limit"
            ),
            {"tid": tenant_id, "limit": limit},
        )
    ).all()
    return [_lot_out(row) for row in rows]


async def _refuse_conflicting_override(
    session: AsyncSession, *, entry_id: UUID, override: CreditPack | None, payment_ref: str
) -> None:
    """Refuse a replay that asks for terms the existing lot does not carry.

    Only asked when the caller SENT an override: an ordinary re-post of a payment recorded
    at the card is the replay this route has always answered 200 to, and making it read the
    lot would put a query on the common path to serve the rare one.

    Read straight from `credit_lots` rather than through a service reader, for the reason
    the neighbouring reads here are raw SQL: `lot_of_entry` answers "which lot did this row
    open, and how big was it" and this needs a different column. RLS scopes it — the policy
    is `tenant_id = current_setting('app.tenant_id')::uuid` for every verb — so a lot of
    another tenant is not visible to ask about, exactly as `lots._SELECT_ONE_OPEN_LOT`
    argues.
    """
    if override is None:
        return
    row = (
        await session.execute(
            text("SELECT override_of_pack_id FROM credit_lots WHERE ledger_entry_id = :eid"),
            {"eid": entry_id},
        )
    ).first()
    carried = None if row is None else row[0]
    if carried == override.pack_id:
        return
    raise ProblemError.conflict(
        "topup_override_conflict",
        (
            f"That payment reference is already on this wallet, and the credit it opened "
            f"is priced at {carried or 'the standard card'} rates, not at "
            f"{override.pack_id!r}."
        ),
        remediation=(
            "A lot's rates are frozen when it opens, so they cannot be changed afterwards "
            "— that freeze is what makes the price a client was sold at durable. If this "
            "client was promised the cheaper rates, record the correction as a fresh "
            f"payment reference (never an annotation of {payment_ref!r}), or grant credit "
            "and say so in the reason."
        ),
    )


@router.post(
    "",
    response_model=TopUpOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Record a client payment onto the wallet — idempotent by the payment reference",
    description=(
        "Posting the same payment reference again returns the existing entry and "
        "credits nothing. The same reference with a DIFFERENT amount is a conflict, "
        "not a second payment.\n\n"
        "Send `rates_of_pack_id` (with `override_reason`) to open this purchase's credit "
        "at ANOTHER pack's per-minute rates — the founding-client promotion and any "
        "negotiated deal. It requires `X-Confirm-Action: override_lot_rates:<pack_id>`, "
        "records which pack's terms were borrowed on the lot itself, and is audited under "
        "its own action. Rates are frozen when the credit is booked, so this is the only "
        "moment they can be set; re-posting the same reference cannot change them."
    ),
)
async def record_topup(
    tenant_id: UUID,
    payload: TopUpIn,
    request: Request,
    principal: CreditsWrite,
    # Resolved BEFORE this handler body runs, so the session read cannot happen inside an
    # open transaction — `core/stepup.py` on `max_overflow=0`. Present on every call and
    # CONSULTED only when the body asks for a rate override: recording a bank transfer at
    # the published card is not a step-up act and never was, and making it one would put a
    # confirmation in front of the ordinary path to protect the rare one.
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
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

    # THE IMPOSSIBLE VALUES FIRST, THE STEP-UP SECOND — `grant_credits`' order and its
    # reason: an operator who named a pack that does not exist should be told that, not
    # told their confirmation header is wrong, which sends them to fix the header and
    # re-submit the same bad id.
    override = _override_pack(payload)
    if override is not None:
        step_up.require(x_confirm_action, lot_rate_override_confirmation(override.pack_id))

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
            # A REPLAY MAY NOT CHANGE THE TERMS. The lot this reference opened has its
            # rates frozen (invariant 3), so re-posting the same payment with a different
            # `rates_of_pack_id` cannot do what it asks — and returning 200 would tell an
            # operator that a promise they just made to a client is on the wallet when it
            # is not. Refused with the pack the lot actually carries, which is the fact
            # they need in order to decide what to do next.
            await _refuse_conflicting_override(
                scoped, entry_id=existing.entry_id, override=override, payment_ref=ref
            )
            balance = await get_balance(scoped, tenant_id=tenant_id)
            log.info(
                "credit_topup_replay",
                extra={"tenant_id": str(tenant_id), "entry_id": str(existing.entry_id)},
            )
            # THE LOT THAT REFERENCE ALREADY OPENED — a replay's receipt names the same
            # object the first call did, so a double-clicked Save cannot show one lot and
            # then none.
            replayed_lot = await _lot_of_entry(scoped, entry_id=existing.entry_id)
            return TopUpOut(
                tenant_id=tenant_id,
                entry_id=existing.entry_id,
                payment_ref=ref,
                lot=replayed_lot,
                # The reference's TOTAL, which for a payment that was never restated is
                # the anchor row's own amount — so nothing changes for the ordinary
                # replay, and a restated one answers with the figure it now credits.
                amount_inr=_paise(payment.credited_inr),
                balance_inr=_paise(balance.amount_inr),
                is_low=balance.is_low,
                recorded=False,
            )

        card = await rate_card_at(scoped, at=datetime.now(UTC))
        meta: dict[str, Any] = {"source": "admin_manual"}
        if principal.user_id:
            meta["recorded_by"] = str(principal.user_id)
        if payload.note:
            meta["note"] = payload.note
        if override is not None:
            # ON THE LEDGER ROW TOO, not only on the lot and the audit log. This is the row
            # a support conversation starts from, and "these credits were sold at the pro
            # pack's rates because <reason>" belongs beside the money it explains.
            meta["rates_of_pack_id"] = override.pack_id
            meta["override_reason"] = payload.override_reason
        balance = await record_entry(
            scoped,
            tenant_id=tenant_id,
            delta=amount,
            reason="topup",
            ref=ref,
            meta=meta,
            # A PAYMENT CANNOT BE REFUSED FOR INSUFFICIENT CREDIT, and it was.
            # `record_entry` refuses any entry that leaves the balance below zero
            # REGARDLESS OF THE DELTA'S SIGN, so recording a ₹100 bank transfer against a
            # wallet at minus ₹500 raised `insufficient_credits` — "This account does not have
            # enough credit for that" — about money that had already arrived, on the one
            # act that makes the shortfall smaller. An operator was told the client was
            # short of credit as the reason they could not record the client paying.
            #
            # A positive delta cannot make a balance worse, so the guard protects nothing
            # here; it exists for the debit path, where it is the whole point. The two
            # sibling credit-adding routes (an adjustment, a restatement) already say this.
            allow_negative=True,
        )
        written = await _find_topup(scoped, tenant_id=tenant_id, ref=ref)
        assert written is not None, "the row was inserted in this transaction"

        # THE LOT THIS PAYMENT OPENS (D-547). A manual top-up names no pack — an operator
        # is recording a bank transfer, not a checkout — so it takes the free-amount rule
        # (plan §0 Q3): the rates of the largest pack the amount would have bought. That
        # is the same answer the self-serve flow gives for the same rupees, which is the
        # property that matters: how the money arrived must not change what it buys.
        #
        # UNLESS AN OPERATOR SAID OTHERWISE (Q6). Then the lot takes the named pack's rates,
        # its `source` is `override` rather than `topup`, and `override_of_pack_id` records
        # WHICH pack's terms were borrowed — on the row, for ever, because "why is this
        # client's minute cheaper than the card" must be answerable from the lot itself and
        # not only from an audit search. `pack_id` stays NULL either way: the client did not
        # buy the pack whose rates they are getting, and stamping it there would report a
        # purchase that never happened.
        credited = await apply_credit_to_lots(
            scoped,
            tenant_id=tenant_id,
            credits_inr=amount,
            balance_after=balance.amount_inr,
            # OFF THE CARD IN FORCE NOW, not off the static catalogue (`RateCard`): a
            # card recorded in the ops console is what publishes a rate change, and until
            # this read existed nothing consulted it, so "raise prices later by recording a
            # new card" was a promise the lot openers could not keep. `at=now` because this
            # money is arriving now.
            rates=(card.for_amount(amount) if override is None else card.of_pack(override)),
            source="topup" if override is None else "override",
            pack_id=None,
            ledger_entry_id=written.entry_id,
            override_of_pack_id=None if override is None else override.pack_id,
        )

        # Same transaction as the insert: money never moves without its audit row.
        summary: dict[str, Any] = {
            "payment_ref": ref,
            "amount_inr": str(amount),
            "balance_after_inr": str(balance.amount_inr),
            # The lot this opened and what it had to repay first — the two facts a
            # later "why is the runway shorter than the payment" question asks.
            "lot_id": str(credited.lot_id) if credited.lot_id is not None else None,
            "repaid_overdraft_inr": str(credited.repaid_overdraft_inr),
        }
        if override is not None:
            # WHICH PACK'S RATES, WHAT THEY ARE, AND WHY — the three facts a review of a
            # below-card sale asks for. WHO chose them is the audit row's own `actor`,
            # which is why it is not repeated here. The two rates are written out rather
            # than left to be looked up from today's card: the card moves, this lot does
            # not, and an audit entry that has to be re-joined to a catalogue to be read
            # is one nobody reads.
            summary["rates_of_pack_id"] = override.pack_id
            summary["override_reason"] = payload.override_reason
            summary["sarvam_inr_per_min"] = str(override.sarvam_inr_per_min)
            summary["cartesia_inr_per_min"] = str(override.cartesia_inr_per_min)
        await write_audit(
            scoped,
            # ITS OWN ACTION NAME when the card was departed from, so the question "show
            # me every below-card sale" is one query rather than a scan of every top-up
            # looking for a key. `credit.grant` is separated from `credit.topup` for the
            # same reason and by the same rule: a different ACT, not a different field.
            action="credit.topup" if override is None else "credit.topup_rate_override",
            actor=principal,
            tenant_id=tenant_id,
            object_type="credit_ledger",
            object_id=str(written.entry_id),
            ip=client_request_ip(request),
            summary=summary,
        )
        # THE RECEIPT NAMES THE OBJECT THIS CLICK CREATED, read back inside the same
        # transaction: a list re-read a moment later cannot say which of five lots it was.
        opened_lot = await _read_lot(scoped, lot_id=credited.lot_id)

    return TopUpOut(
        tenant_id=tenant_id,
        entry_id=written.entry_id,
        payment_ref=ref,
        amount_inr=_paise(amount),
        balance_inr=_paise(balance.amount_inr),
        is_low=balance.is_low,
        recorded=True,
        lot=opened_lot,
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
                lot=None,
                corrects_entry_id=target.entry_id,
                ref=ref,
                delta_inr=_paise(existing.amount_inr),
                balance_inr=_paise(balance.amount_inr),
                is_low=balance.is_low,
                recorded=False,
                # A REPLAY MOVED NO LOTS, so it created no overdraft — and a replay's
                # receipt must not repeat a warning about one the FIRST call made, which
                # the wallet read already shows. `0.00`, like `lot` is `None` above and for
                # the same reason.
                lot_shortfall_inr=_ZERO,
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

        # WHAT THIS CORRECTION DOES TO THE LOTS (D-547), decided by its DIRECTION before
        # the ledger row is written, because the row carries the answer in `meta.lots`.
        #
        # * taking credit AWAY corrects an entry that ADDED it, so it restates that
        #   entry's own lot downwards (ADDENDUM 2 §2.2) — `credits_total` falls, the
        #   remainder floors at zero, and anything the lot had already spent becomes
        #   wallet overdraft, which the balance below is about to record anyway. An entry
        #   that opened no lot is spent off the queue at face value instead;
        # * crediting BACK corrects a `usage` row, and the minutes it charged for are
        #   gone. There is nothing to restate, so it opens a fresh lot at the LIST rates
        #   (plan §0 Q4 — a gift is spent at the standard price). It is `source='grant'`
        #   rather than a sixth source value: no bank moved money for it, which is
        #   exactly what that value means, and inventing a source would need the CHECK,
        #   the Literal in `billing/lots.py` and a migration to move together for a
        #   distinction the `corrects_entry_id` on the row already carries.
        overdraft = _ZERO
        if delta < 0:
            returned = await remove_credit_from_lots(
                scoped,
                tenant_id=tenant_id,
                corrected_entry_id=target.entry_id,
                amount_inr=amount,
            )
            overdraft = returned.overdraft_inr
            if returned.splits:
                meta["lots"] = split_meta(returned.splits)
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

        credited_lot: CreditLotOut | None = None
        if delta > 0:
            returned_credit = await apply_credit_to_lots(
                scoped,
                tenant_id=tenant_id,
                credits_inr=delta,
                balance_after=balance.amount_inr,
                rates=(await rate_card_at(scoped, at=datetime.now(UTC))).list_rates(),
                source="grant",
                pack_id=None,
                ledger_entry_id=written.entry_id,
            )
            # Read back rather than assembled from what was just passed in: a credit-back
            # that repaid an overdraft opened NO lot, and the receipt has to say so.
            credited_lot = await _read_lot(scoped, lot_id=returned_credit.lot_id)

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
        lot=credited_lot,
        lot_shortfall_inr=overdraft,
    )


@lots_router.post(
    "/{lot_id}/override",
    response_model=LotRepriceOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Re-price ONE lot at another pack's rates (close and replace)",
    description=(
        "Sell credit a client ALREADY HOLDS at another pack's per-minute rates — the "
        "promotion nobody applied at the till, the deal negotiated after the money "
        "landed. It is NOT an edit: a lot's terms are frozen for the life of its credit "
        "(`credit_lots_terms_frozen`), so the original lot is CLOSED at its own rates and "
        "a replacement opens carrying the same credit at the new ones, inheriting the "
        "original's place in the spend queue. No money moves in either direction; the "
        "ledger records a zero-delta `adjustment` marker so the new lot has an entry to "
        "name. Requires `X-Confirm-Action: override_lot_rates:<lot_id>`. Re-posting the "
        "same lot and pack returns the existing result and re-prices nothing. To price "
        "credit as it ARRIVES, use `rates_of_pack_id` on the top-up instead."
    ),
)
async def reprice_credit_lot(
    tenant_id: UUID,
    lot_id: UUID,
    payload: LotRepriceIn,
    request: Request,
    principal: CreditsWrite,
    # Resolved BEFORE the handler body, for `record_topup`'s reason. UNCONDITIONAL here,
    # unlike there: every call to this route departs from the card, which is the act the
    # step-up exists for. There is no ordinary path to keep out of its way.
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> LotRepriceOut:
    # THE IMPOSSIBLE VALUE FIRST, THE STEP-UP SECOND — `record_topup`'s order and its
    # reason: an operator who named a pack that does not exist should be told that rather
    # than told their header is wrong.
    pack = pack_by_id(payload.pack_id)
    if pack is None:
        raise ProblemError.business_rule(
            "unknown_credit_pack",
            f"There is no credit pack called {payload.pack_id!r}.",
            remediation=(
                "Choose one of the packs published on the wallet read "
                f"(/v1/admin/tenants/{tenant_id}/credits)."
            ),
        )
    step_up.require(x_confirm_action, lot_reprice_confirmation(lot_id))

    async with tenant_session(tenant_id) as scoped:
        await _assert_tenant_exists(scoped, tenant_id)
        repriced = await reprice_lot(
            scoped,
            tenant_id=tenant_id,
            lot_id=lot_id,
            pack=pack,
            reason=payload.reason,
            operator_id=principal.user_id,
        )
        ref = lot_reprice_ref(lot_id=lot_id, pack_id=pack.pack_id)
        if repriced is None:
            # A REPLAY. The marker is on the ledger, so the replacement it named is the
            # answer — found through the marker rather than remembered, which is what makes
            # a double-clicked Save return the same two lot ids as the first click.
            marker = await _find_entry_by_ref(
                scoped, tenant_id=tenant_id, reason="adjustment", ref=ref
            )
            assert marker is not None, "reprice_lot returned None because it found this row"
            replayed = await _lot_of_entry(scoped, entry_id=marker.entry_id)
            assert replayed is not None, "the marker's whole purpose is to name a lot"
            log.info(
                "credit_lot_reprice_replay",
                extra={"tenant_id": str(tenant_id), "lot_id": str(lot_id)},
            )
            return LotRepriceOut(
                tenant_id=tenant_id,
                closed_lot_id=lot_id,
                lot=replayed,
                entry_id=marker.entry_id,
                ref=ref,
                credits_inr=_paise(replayed.credits_total),
                recorded=False,
            )

        # Same transaction as the write: a term of a client's contract never moves
        # without its audit row. Its OWN action name, for `credit.topup_rate_override`'s
        # reason — "show me every below-card sale" must be one query, and this is a
        # different act from that one on a different object.
        await write_audit(
            scoped,
            action="credit.lot_rate_override",
            actor=principal,
            tenant_id=tenant_id,
            object_type="credit_lots",
            object_id=str(lot_id),
            ip=client_request_ip(request),
            summary={
                "replacement_lot_id": str(repriced.replacement_lot_id),
                "entry_id": str(repriced.ledger_entry_id),
                "credits_inr": str(_paise(repriced.credits_inr)),
                "rates_of_pack_id": pack.pack_id,
                # BOTH pairs, written out rather than left to be looked up from today's
                # card: the card moves, this decision does not, and an audit entry that has
                # to be re-joined to a catalogue to be read is one nobody reads.
                "previous_sarvam_inr_per_min": str(repriced.previous_rates.sarvam_inr_per_min),
                "previous_cartesia_inr_per_min": str(repriced.previous_rates.cartesia_inr_per_min),
                "sarvam_inr_per_min": str(repriced.rates.sarvam_inr_per_min),
                "cartesia_inr_per_min": str(repriced.rates.cartesia_inr_per_min),
                # The operator's own words — the field a later review of a below-card rate
                # is actually looking for.
                "reason": payload.reason,
            },
        )
        # Read back from the row for `_read_lot`'s reason: what the console must show is
        # what the LOT says, not what this request asked for.
        replacement = await _read_lot(scoped, lot_id=repriced.replacement_lot_id)
        assert replacement is not None, "the replacement was opened in this transaction"

    log.info(
        "credit_lot_repriced",
        extra={
            "tenant_id": str(tenant_id),
            "lot_id": str(lot_id),
            "replacement_lot_id": str(repriced.replacement_lot_id),
            "pack_id": pack.pack_id,
        },
    )
    return LotRepriceOut(
        tenant_id=tenant_id,
        closed_lot_id=repriced.closed_lot_id,
        lot=replacement,
        entry_id=repriced.ledger_entry_id,
        ref=ref,
        credits_inr=_paise(repriced.credits_inr),
        recorded=True,
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
                lot=await _lot_of_entry(scoped, entry_id=existing.entry_id),
                lot_shortfall_inr=None,
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

        # THE MONEY LANDS ON THE PURCHASE'S OWN LOT (D-547), not on a new one behind it.
        # A restatement is the same bank transfer stated correctly, so it was sold at the
        # rates that transfer was sold at; opening a second lot would price one payment
        # at two cards and put the client behind their own earlier purchases in the FIFO
        # queue for money that arrived first. `anchor` is the row this reference opened
        # with — a payment recorded before lots existed has none, and `apply_credit_to_lots`
        # opens one for the difference instead.
        anchor = await _find_topup(scoped, tenant_id=tenant_id, ref=ref)
        assert anchor is not None, "the anchor row was found before this write"
        restated = await apply_credit_to_lots(
            scoped,
            tenant_id=tenant_id,
            credits_inr=added,
            balance_after=balance.amount_inr,
            rates=(await rate_card_at(scoped, at=datetime.now(UTC))).for_amount(corrected),
            source="topup",
            pack_id=None,
            ledger_entry_id=written.entry_id,
            restate_lot_id=(
                anchor_lot.lot_id
                if (anchor_lot := await lot_of_entry(scoped, ledger_entry_id=anchor.entry_id))
                else None
            ),
        )

        # The lot the money landed on, read back inside the transaction — the rates on it
        # are the PURCHASE's, which are not the ones this request named.
        restated_lot = await _read_lot(scoped, lot_id=restated.lot_id)

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
        lot=restated_lot,
        # Upward only on this route — see the field. Never a zero, which would assert that
        # a shortfall was measured and came to nothing.
        lot_shortfall_inr=None,
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
        # A GIFT IS SPENT AT THE STANDARD PRICE (plan §0 Q4): the list card's rates, never
        # the deepest pack's. A ₹50,000 grant that bought a cheaper minute than a ₹50,000
        # purchase would make the card a suggestion.
        await apply_credit_to_lots(
            scoped,
            tenant_id=tenant_id,
            credits_inr=amount,
            balance_after=balance.amount_inr,
            rates=(await rate_card_at(scoped, at=datetime.now(UTC))).list_rates(),
            source="grant",
            pack_id=None,
            ledger_entry_id=written.entry_id,
        )
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
        # THE OPEN LOT QUEUE, on the same read and the same page size — a wallet is no
        # longer one balance with one price behind it, and an operator crediting it is
        # opening a priced object rather than adding to a pot.
        open_lots = await _open_lots(scoped, tenant_id=tenant_id, limit=limit)
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
        lots=open_lots,
        # STRAIGHT OFF THE CARD, in card order — the same tuple `RateCard.of_pack` reads
        # when the write freezes them, so what an operator is shown is what the write does.
        override_packs=[
            OverridePackOut(
                pack_id=pack.pack_id,
                amount_inr=pack.amount_inr,
                sarvam_inr_per_min=pack.sarvam_inr_per_min,
                cartesia_inr_per_min=pack.cartesia_inr_per_min,
            )
            for pack in PACK_CATALOGUE
        ],
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
