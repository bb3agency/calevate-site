"""Admin credit top-ups — putting a client's NEFT/UPI payment onto their wallet.

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
  and the lock inside `record_entry` is far too late to help. There is no unique index
  on `credit_ledger.ref` to fall back on, and adding one is a migration this change
  does not carry.
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

Permission: `admin:tenants` for the write and `billing:read` for the read. There is no
`billing:write` in the registry and this did not warrant inventing one — recording a
received payment is admin-realm support work of the same family as provisioning a
number or filing a DLT status, all of which are `admin:tenants`. It is also already in
`MUTATING_PERMISSIONS`, so an impersonating admin cannot reach it (D-22).

NOT mounted here — the integrator wires this router into `main.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.service import LOW_BALANCE_INR, get_balance, record_entry
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session

log = get_logger(__name__)

router = APIRouter(prefix="/v1/admin/tenants/{tenant_id}/credits", tags=["admin"])

# Annotated dependencies rather than `Depends()` in a default: this file is not
# `routes.py`, so it is not covered by the B008 per-file ignore (same reason
# `agents/prompt_routes.py` is written this way).
CreditsWrite = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]
CreditsRead = Annotated[Principal, Depends(requires("billing:read", realm="admin"))]

PAISE = Decimal("0.01")
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _paise(value: Decimal) -> Decimal:
    """NUMERIC(12,4) is the storage precision; two decimals is what a rupee amount
    means to the person reading it. Quantize at the boundary only (billing.service)."""
    return value.quantize(PAISE)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TopUpIn(Strict):
    # max_digits/decimal_places mirror the column: MONEY is NUMERIC(12,4), so eight
    # integer digits is the ceiling and anything finer than a paisa is a typo.
    amount_inr: Decimal = Field(max_digits=10, decimal_places=2)
    # The bank/UPI reference (UTR, RRN, a Razorpay payment id). This is the
    # idempotency key, which is why it is required and never generated for the caller.
    payment_ref: str = Field(min_length=3, max_length=120)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("amount_inr", mode="before")
    @classmethod
    def _never_a_float(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError(
                'money crosses the wire as a string ("2500.00"), never as a JSON float'
            )
        return value

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


class LedgerEntryOut(Strict):
    id: UUID
    delta_inr: Decimal
    reason: str
    ref: str | None
    balance_after_inr: Decimal
    occurred_at: datetime


class CreditsOut(Strict):
    tenant_id: UUID
    balance_inr: Decimal
    is_low: bool
    low_balance_threshold_inr: Decimal
    entries: list[LedgerEntryOut]


@dataclass(frozen=True, slots=True)
class _ExistingTopUp:
    id: UUID
    amount_inr: Decimal


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """A mistyped tenant id must be a 404, not an FK violation rendered as a 500 —
    and on a money route, not a silent zero-balance wallet that looks real."""
    found = (
        await session.execute(
            text("SELECT 1 FROM organizations WHERE id = :tid AND deleted_at IS NULL"),
            {"tid": tenant_id},
        )
    ).first()
    if found is None:
        raise ProblemError.not_found("Organization")


async def _find_topup(session: AsyncSession, *, tenant_id: UUID, ref: str) -> _ExistingTopUp | None:
    """The idempotency lookup. Scoped to `reason = 'topup'` so a payment reference can
    never collide with the call id a usage row carries in the same column."""
    row = (
        await session.execute(
            text(
                "SELECT id, delta FROM credit_ledger WHERE tenant_id = :tid "
                "AND reason = 'topup' AND ref = :ref ORDER BY occurred_at DESC, id DESC LIMIT 1"
            ),
            {"tid": tenant_id, "ref": ref},
        )
    ).first()
    if row is None:
        return None
    return _ExistingTopUp(id=UUID(str(row[0])), amount_inr=Decimal(str(row[1])))


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
        raise ProblemError.business_rule(
            "invalid_topup_amount",
            "A top-up must be a positive rupee amount.",
            remediation="To take credit back, record a compensating adjustment instead.",
        )

    ref = payload.payment_ref
    async with tenant_session(tenant_id) as scoped:
        await _assert_tenant_exists(scoped, tenant_id)
        # Serialize check-then-write against every other credit write for this tenant,
        # on the SAME key `record_entry` uses. Acquired BEFORE the lookup: two
        # operators recording one UTR at the same moment would otherwise both read
        # "not present" and both insert. Released at transaction end.
        await scoped.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"credit:{tenant_id}"},
        )

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
                extra={"tenant_id": str(tenant_id), "entry_id": str(existing.id)},
            )
            return TopUpOut(
                tenant_id=tenant_id,
                entry_id=existing.id,
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
            object_id=str(written.id),
            ip=request.client.host if request.client else None,
            summary={
                "payment_ref": ref,
                "amount_inr": str(amount),
                "balance_after_inr": str(balance.amount_inr),
            },
        )

    return TopUpOut(
        tenant_id=tenant_id,
        entry_id=written.id,
        payment_ref=ref,
        amount_inr=_paise(amount),
        balance_inr=_paise(balance.amount_inr),
        is_low=balance.is_low,
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
            )
            for row in rows
        ],
    )


__all__ = ["router"]
