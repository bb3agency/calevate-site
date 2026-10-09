"""Buying and releasing a number in a client's own ThinnestAI workspace (D-693).

Numbers are rented in the CLIENT's own customer workspace, so they are rented in its own
business name once its business details are approved (`thinnest-findings/mirror/snapshots/
2026-10-08/pages/api-reference/phone-numbers/rent-phone-number.md:7`). Not resale: the
client is the business the numbering authority sees. Who may buy is decided once, by
`purchase_readiness`, for the client app and the admin console alike:

1. the account is open;
2. its own workspace is active (`tenancy/engine_workspace`);
3. its KYC record is verified (D-692);
4. its business details are approved in that workspace (`accepted`, `canRent`);
5. a client monthly price is attested (OPERATIONS §2 gate 26) — the client pays THAT, never
   the vendor's `monthlyPrice`, which is our cost (hard rule 7).

THE MONEY ORDER. Every refusal that costs nothing, then the wallet check, then the vendor's
rent — which "charges the first month at once" to OUR balance and refuses "before anything is
bought or charged" (rent-phone-number.md:7) — then, in one transaction, the number recorded
and the client's first month collected by the one rental path every other number uses
(`engine_numbers.record_engine_number` → `billing/number_rental.collect_number_rental`,
D-665/D-691). A vendor refusal therefore charges the client nothing, and a client is charged
only for a number we hold.

ONE NUMBER PER CLICK. The request is keyed by the caller's idempotency key and committed as
`renting` BEFORE the vendor is asked, so a double-click, a retry or a lost response finds the
same row: a finished one answers the same number, a refused one the same refusal, and an
unfinished one is resolved by reading the number back from the vendor, never by renting
again. The vendor documents no idempotency key for this route, so none is sent.

RELEASE is `DELETE /phone-numbers/{n}?confirm=release`: permanent, the number goes back to
the pool, "this month's rent is not refunded" (release-phone-number.md:7). Our own rental
stops with `released_at`, and the client is not refunded the current period either; both
screens say so before the button.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final, Literal
from uuid import UUID

from calevate_shared.engine_scope import scope_of, scoped_handle
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.number_rental import RentalOutcome
from apps.api.campaigns.engine_numbers import (
    engine_number_provider,
    is_platform_held,
    record_engine_number,
    releasable_by,
)
from apps.api.campaigns.number_catalog import NumberDirection, assert_can_afford
from apps.api.campaigns.number_pricing import attested_price_inr, require_attested_price_inr
from apps.api.compliance.kyc import read_kyc
from apps.api.compliance.trial_access import ADD_CREDIT_STEP, TRIAL_REFUSALS, trial_blocker
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine.thinnest_numbers import digits, thinnest_numbers
from apps.api.engine.vendor_http import EngineRejectedError
from apps.api.tenancy.engine_workspace import read_workspace_state
from apps.api.tenancy.lifecycle import assert_account_open

log = get_logger(__name__)

#: The trial refusal's rule, as every number gate names it (D-697).
TRIAL_NUMBERS_RULE: Final = TRIAL_REFUSALS["numbers"][0]

PurchaseStep = Literal[
    "add_credit", "workspace", "verify_business", "business_details", "price", "ready"
]

#: Where the client stands, in the order the screen walks them through.
_BLOCKER_STEP: Final[dict[str, PurchaseStep]] = {
    TRIAL_NUMBERS_RULE: "add_credit",
    "engine_workspace_not_provisioned": "workspace",
    "kyc_not_verified": "verify_business",
    "business_details_not_approved": "business_details",
    "number_price_not_attested": "price",
}


@dataclass(frozen=True, slots=True)
class PurchaseReadiness:
    step: PurchaseStep
    #: The first thing that stops a purchase, as our code, or None when nothing does.
    blocker: str | None
    workspace_status: str
    kyc_status: str
    kyc_verified: bool
    business_status: str | None
    business_can_rent: bool
    business_review_note: str | None
    #: What the client pays a month for a number, when attested.
    client_inr_per_month: Decimal | None
    blockers: list[str] = field(default_factory=list)


async def purchase_readiness(session: AsyncSession, *, tenant_id: UUID) -> PurchaseReadiness:
    """Every gate a number purchase passes, read in the caller's tenant session."""
    state = await read_workspace_state(session, tenant_id)
    kyc = await read_kyc(session, tenant_id=tenant_id)
    price = await attested_price_inr(session)
    blockers: list[str] = []
    # A free-trial account buys no number until it pays (D-697); it is asked first because
    # every step after it opens only then.
    if await trial_blocker(session, tenant_id=tenant_id, locked="numbers") is not None:
        blockers.append(TRIAL_NUMBERS_RULE)
    if not state.active:
        blockers.append("engine_workspace_not_provisioned")
    if not kyc.is_verified:
        blockers.append("kyc_not_verified")
    if not (state.business_status == "accepted" and state.business_can_rent):
        blockers.append("business_details_not_approved")
    if price is None:
        blockers.append("number_price_not_attested")
    first = blockers[0] if blockers else None
    return PurchaseReadiness(
        step=_BLOCKER_STEP[first] if first else "ready",
        blocker=first,
        workspace_status=state.status,
        kyc_status=kyc.status or "not_started",
        kyc_verified=kyc.is_verified,
        business_status=state.business_status,
        business_can_rent=state.business_can_rent,
        business_review_note=state.business_review_note,
        client_inr_per_month=price.inr_per_month if price is not None else None,
        blockers=blockers,
    )


_REFUSALS: Final[dict[str, tuple[str, str]]] = {
    TRIAL_NUMBERS_RULE: (TRIAL_REFUSALS["numbers"][1], ADD_CREDIT_STEP),
    "engine_workspace_not_provisioned": (
        "No number can be bought until this account is set up for calls.",
        "If you have just set it up, try again in a few minutes. Otherwise your Calevate "
        "contact can finish the setup.",
    ),
    "kyc_not_verified": (
        "Your business has to be verified before a number can be bought in its name.",
        "Finish Verify your business, then come back.",
    ),
    "business_details_not_approved": (
        "Your business details have not been approved for phone numbers yet.",
        "Wait for the approval shown on this page, or fix and resend them if they were rejected.",
    ),
    "number_price_not_attested": (
        "Numbers are not on sale yet.",
        "Contact us.",
    ),
}


def _refuse(code: str) -> ProblemError:
    detail, remediation = _REFUSALS[code]
    return ProblemError.business_rule(code, detail, remediation=remediation)


@dataclass(frozen=True, slots=True)
class PurchasedEngineNumber:
    number_id: UUID
    e164: str
    client_inr_per_month: Decimal | None
    attachment: str
    #: True when this request found a purchase an earlier click already finished.
    replayed: bool = False
    #: What became of the client's first month (`RentalOutcome`): `replayed` when an earlier
    #: request already bought it, None when the number is not priced.
    first_period: RentalOutcome | None = None


_PURCHASE_ROW: Final = (
    "SELECT id, status, number_id, refusal_code, vendor_number, workspace_id "
    "FROM engine_number_purchases WHERE tenant_id = :tid AND idempotency_key = :key FOR UPDATE"
)


def _vendor_refusal(exc: EngineRejectedError) -> ProblemError:
    """A rent the vendor refused, in the client's words. Nothing was bought or charged."""
    if exc.vendor_status == 409:
        return ProblemError.business_rule(
            "engine_number_unavailable",
            "That number could not be bought: somebody else holds it now, or your business "
            "details are still being checked. Nothing was charged.",
            remediation="Search again and pick another number.",
        )
    if exc.vendor_status == 402:
        alert(
            "CORE_LOGIC",
            "engine_number_rent_unfunded",
            detail=(
                "a client's number purchase was refused because the voice platform balance "
                "cannot pay a month's rent. Nothing was charged to the client. Top up the "
                "voice platform balance."
            ),
        )
        return ProblemError.business_rule(
            "engine_number_purchase_unavailable",
            "Numbers cannot be bought just now. Nothing was charged.",
            remediation="Try again later. We have been told.",
        )
    return ProblemError.business_rule(
        "engine_number_purchase_refused",
        "The number could not be bought. Nothing was charged.",
        remediation="Search again and pick another number. If it keeps failing, contact us.",
    )


async def _assert_agent_can_take_it(
    session: AsyncSession, *, agent_id: UUID | None, workspace: str
) -> None:
    """Refuse BEFORE renting a number for an agent it could not answer for: one of another
    client (RLS hides it), an archived one, or one still published in the platform account
    (its next publish moves it into this workspace). After the rent it would be a number we
    pay for and cannot record."""
    if agent_id is None:
        return
    row = (
        await session.execute(
            text(
                "SELECT engine_agent_ref, status FROM agents WHERE id = :aid AND deleted_at IS NULL"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None or row[1] == "archived":
        raise ProblemError.not_found("Agent")
    ref = row[0]
    if isinstance(ref, str) and ref and scope_of(ref) != workspace:
        raise ProblemError.business_rule(
            "engine_number_agent_not_moved",
            "This agent has not been republished since your account got its own voice "
            "workspace, so a new number cannot be attached to it yet.",
            remediation="Publish the agent, then buy the number.",
        )


async def _settle(
    tenant_id: UUID, purchase_id: UUID, *, status: str, code: str | None = None
) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE engine_number_purchases SET status = :status, refusal_code = :code, "
                "updated_at = now() WHERE id = :id"
            ),
            {"status": status, "code": code, "id": purchase_id},
        )


async def purchase_engine_number(
    *,
    tenant_id: UUID,
    number: str,
    agent_id: UUID | None,
    direction: NumberDirection,
    idempotency_key: str,
    requested_by: Literal["client", "admin"],
) -> PurchasedEngineNumber:
    """Rent `number` in the client's own workspace, record it, charge the client's first
    month, attach it. Opens its own sessions; holds none across the vendor call."""
    wanted = digits(number)
    async with tenant_session(tenant_id) as session:
        await assert_account_open(session, tenant_id=tenant_id)
        row = (
            await session.execute(text(_PURCHASE_ROW), {"tid": tenant_id, "key": idempotency_key})
        ).first()
        if row is not None:
            purchase_id, status, number_id, refusal = UUID(str(row[0])), row[1], row[2], row[3]
            if status == "recorded" and number_id is not None:
                e164 = (
                    await session.execute(
                        text("SELECT e164, client_inr_per_month FROM phone_numbers WHERE id = :id"),
                        {"id": number_id},
                    )
                ).first()
                return PurchasedEngineNumber(
                    number_id=UUID(str(number_id)),
                    e164=str(e164[0]) if e164 else f"+{row[4]}",
                    client_inr_per_month=e164[1] if e164 else None,
                    attachment="unchanged",
                    replayed=True,
                    first_period="replayed",
                )
            if status in ("refused", "failed"):
                raise ProblemError.business_rule(
                    str(refusal or "engine_number_purchase_refused"),
                    "This purchase was already refused. Nothing was charged.",
                    remediation="Search again and pick another number.",
                )
            if str(row[4]) != wanted:
                raise ProblemError.conflict(
                    "idempotency_key_reused",
                    "This request key was used for a different number.",
                    remediation="Reload the page and try again.",
                )
            workspace = str(row[5])
            resumed = True
        else:
            readiness = await purchase_readiness(session, tenant_id=tenant_id)
            if readiness.blocker is not None:
                raise _refuse(readiness.blocker)
            state = await read_workspace_state(session, tenant_id)
            assert state.workspace_id is not None
            workspace = state.workspace_id
            await _assert_agent_can_take_it(session, agent_id=agent_id, workspace=workspace)
            price = await require_attested_price_inr(session)
            await assert_can_afford(session, tenant_id=tenant_id, amount=price.inr_per_month)
            purchase_id = uuid7()
            await session.execute(
                text(
                    "INSERT INTO engine_number_purchases (id, tenant_id, idempotency_key, "
                    "vendor_number, workspace_id, agent_id, direction, status, requested_by, "
                    "created_at, updated_at) VALUES (:id, :tid, :key, :num, :ws, :aid, :dir, "
                    "'renting', :by, now(), now())"
                ),
                {
                    "id": purchase_id,
                    "tid": tenant_id,
                    "key": idempotency_key,
                    "num": wanted,
                    "ws": workspace,
                    "aid": agent_id,
                    "dir": direction,
                    "by": requested_by,
                },
            )
            resumed = False

    numbers = thinnest_numbers()
    handle = scoped_handle(wanted, workspace)
    try:
        held = False
        if resumed:
            try:
                held = (await numbers.get_number(handle)).rented
            except EngineRejectedError as exc:
                if exc.vendor_status != 404:
                    raise
        if not held:
            await numbers.rent(workspace, wanted)
    except EngineRejectedError as exc:
        if exc.request_refused or exc.vendor_status in (402, 409):
            refusal = _vendor_refusal(exc)
            await _settle(tenant_id, purchase_id, status="refused", code=refusal.code)
            log.info(
                "engine_number_purchase_refused",
                extra={"tenant_id": str(tenant_id), "status": exc.vendor_status},
            )
            raise refusal from exc
        raise _unconfirmed() from exc
    except ProblemError as exc:
        raise _unconfirmed() from exc

    async with tenant_session(tenant_id) as session:
        recorded = await record_engine_number(
            session,
            tenant_id=tenant_id,
            e164=f"+{wanted}",
            direction=direction,
            agent_id=agent_id,
            purpose=None,
        )
        await session.execute(
            text(
                "UPDATE engine_number_purchases SET status = 'recorded', number_id = :nid, "
                "updated_at = now() WHERE id = :id"
            ),
            {"nid": recorded.number_id, "id": purchase_id},
        )
    log.info(
        "engine_number_purchased",
        extra={
            "tenant_id": str(tenant_id),
            "number_id": str(recorded.number_id),
            "requested_by": requested_by,
        },
    )
    return PurchasedEngineNumber(
        number_id=recorded.number_id,
        e164=recorded.e164,
        client_inr_per_month=recorded.client_inr_per_month,
        attachment=recorded.attachment,
        first_period=recorded.first_period,
    )


def _unconfirmed() -> ProblemError:
    return ProblemError(
        kind="dependency",
        code="engine_number_purchase_unconfirmed",
        title="We could not confirm the purchase",
        detail=(
            "The voice platform did not answer clearly. Nothing has been charged to you. "
            "Press Buy again: the same request will finish the purchase or tell you it did "
            "not happen, and never buys a second number."
        ),
        remediation="Press Buy again.",
    )


_RELEASE_ROW: Final = (
    "SELECT engine_number_ref, provider, released_at FROM phone_numbers WHERE id = :id FOR UPDATE"
)


async def release_engine_number(
    session: AsyncSession, *, tenant_id: UUID, number_id: UUID, by_admin: bool
) -> bool:
    """Give a number in the client's own workspace back for good, and stop our rental. True
    when it was released now, False when it already was. A number held in the platform
    account is released by an admin only. In the caller's tenant session."""
    row = (await session.execute(text(_RELEASE_ROW), {"id": number_id})).first()
    if row is None or row[1] != engine_number_provider() or not row[0]:
        raise ProblemError.not_found("Number")
    ref, _provider, released_at = str(row[0]), row[1], row[2]
    if released_at is not None:
        return False
    own = (await read_workspace_state(session, tenant_id)).workspace_id
    if not releasable_by(ref, own_workspace=own, by_admin=by_admin):
        raise ProblemError.not_found("Number")
    await thinnest_numbers().release(ref)
    await session.execute(
        text(
            "UPDATE phone_numbers SET released_at = now(), agent_id = NULL, updated_at = now() "
            "WHERE id = :id AND released_at IS NULL"
        ),
        {"id": number_id},
    )
    log.info(
        "engine_number_released", extra={"tenant_id": str(tenant_id), "number_id": str(number_id)}
    )
    return True


async def forget_engine_number(session: AsyncSession, *, tenant_id: UUID, number_id: UUID) -> bool:
    """Stop OUR record and billing of a number without releasing it at the vendor. True when
    released now, False when it already was. In the caller's tenant session; admin only.

    For the two cases a release cannot serve: a number the vendor no longer holds (what
    `engine_number_missing_at_vendor` asks an operator to clean up), and a number held in the
    platform account that was recorded for this client for testing and is being taken back
    (it is detached from the client's agents and stays ours). A number the client's own
    workspace still holds is refused: releasing it is the act that stops the vendor's rent.
    """
    row = (await session.execute(text(_RELEASE_ROW), {"id": number_id})).first()
    if row is None or row[1] != engine_number_provider() or not row[0]:
        raise ProblemError.not_found("Number")
    ref, released_at = str(row[0]), row[2]
    if released_at is not None:
        return False
    numbers = thinnest_numbers()
    try:
        held = await numbers.get_number(ref)
    except EngineRejectedError as exc:
        if exc.vendor_status != 404:
            raise
        held = None
    if held is not None and not is_platform_held(ref):
        raise ProblemError.business_rule(
            "engine_number_still_held",
            "The client's voice workspace still holds this number, so forgetting our record "
            "would leave it rented and charged to us.",
            remediation="Release the number instead.",
        )
    if held is not None:
        await numbers.attach(ref, agent=None, calling_agent=None)
    await session.execute(
        text(
            "UPDATE phone_numbers SET released_at = now(), agent_id = NULL, updated_at = now() "
            "WHERE id = :id AND released_at IS NULL"
        ),
        {"id": number_id},
    )
    log.info(
        "engine_number_record_released",
        extra={
            "tenant_id": str(tenant_id),
            "number_id": str(number_id),
            "held_at_vendor": held is not None,
        },
    )
    return True


__all__ = [
    "PurchaseReadiness",
    "PurchaseStep",
    "PurchasedEngineNumber",
    "forget_engine_number",
    "purchase_engine_number",
    "purchase_readiness",
    "release_engine_number",
]
