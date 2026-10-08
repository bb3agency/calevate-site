"""Numbers rented in the voice platform's own console: record, attach, reconcile (D-691).

On ThinnestAI a number is RENTED in its console (renting has no API) but everything after
that does: the workspace's numbers are listed, and who answers each and who calls out on each
is set with `PATCH /phone-numbers/{number}` (`engine/thinnest_numbers.py` cites the pages).
So the founder's flow is: rent in the console, then record the number here for the client it
belongs to, and from then on WE decide which agent answers it.

**WE ARE THE MASTER OF THE ATTACHMENT.** `phone_numbers.agent_id` says which agent a number
belongs to; the vendor's `agent` / `callingAgent` are made to agree with it, at the moment an
operator records or attaches a number and again by the daily sweep, which repairs any drift
(a console edit, an agent paused or archived since). The wanted state, from our rows:

* a released number, or one bound to no live published agent: nobody answers, nobody calls;
* an agent that answers (`inbound`, `both`): it is the number's line (`agent`). An agent can
  call out on its own line ("its own, or one lent to it", `calls/place-call.md:974`), so
  `callingAgent` is cleared rather than set to the same agent — which the vendor refuses
  (409, `phone-numbers/update-phone-number.md:401-405`);
* an outbound-only agent: lent the number to call out on (`callingAgent`), answering nothing.

**NOTHING IS ADOPTED AUTOMATICALLY.** A number the vendor holds that we have no record of is
alarmed, never recorded: which client it belongs to is an operator's decision.

**A RENTED NUMBER IS PRICED FOR THE CLIENT WHEN IT IS RECORDED** from the operator-attested
monthly rate (`number_pricing`, OPERATIONS §2 gate 26), never a constant, and its first period
is collected in the same transaction, exactly as a client purchase's is (D-665), so the
renewal job bills it from then on. A number brought on a carrier account is not priced: the
vendor bills nothing for it.

Ids and counts in every log line and alarm; never a phone number (hard rule 6).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Final, Literal
from uuid import UUID

from calevate_shared.carrier import ENGINE_NUMBER_PROVIDER
from calevate_shared.engine import ProvisionedNumber
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import service as agents_service
from apps.api.agents.models import series_for_e164
from apps.api.billing.number_rental import (
    collect_number_rental,
    ist_date,
    rental_period_start,
    today_ist,
)
from apps.api.campaigns.number_pricing import attested_price_inr, require_attested_price_inr
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.session import admin_session, tenant_session
from apps.api.engine import get_engine
from apps.api.engine.thinnest_numbers import (
    Attachment,
    BusinessDetails,
    ThinnestNumbers,
    digits,
    thinnest_numbers,
)

log = get_logger(__name__)

#: Business-details states in which the platform will not rent a new Indian number
#: (`phone-numbers/get-business-details.md:425-436`): each needs an operator to act.
LAPSED_BUSINESS_STATUSES: Final = frozenset({"rejected", "suspended", "expired"})

#: Numbers read back and, where needed, re-pointed per sweep. The estate is a handful per
#: client; the bound keeps one bad day from becoming a rate-limit incident.
ATTACHMENT_SWEEP_BUDGET: Final = 100

SyncOutcome = Literal["not_applicable", "unchanged", "applied", "partial", "refused"]


def engine_number_provider() -> str | None:
    """The provider a number on THIS deployment's engine is recorded under, or None where
    numbers are not the engine's (the carrier's own, on Pipecat)."""
    return ENGINE_NUMBER_PROVIDER.get(get_settings().engine)


def _refuse_off_engine() -> ProblemError:
    return ProblemError(
        kind="validation",
        code="number_provider_not_on_this_engine",
        title="That number provider is not used by this deployment",
        detail=(
            "Numbers rented on the voice platform can be recorded only while that voice "
            "platform is the one placing calls."
        ),
        remediation="Record the number under the carrier this deployment dials on.",
    )


# --- THE ONE SEAM to the vendor's numbers -----------------------------------------------
#
# Every call about a vendor number goes through the four functions below, and each takes
# the WORKSPACE the numbers live in. Today that is always our one developer workspace
# (`None`, D-688). The founder has decided each client will get its own ThinnestAI customer
# workspace (`Thinnest-Workspace` header), so its numbers and its business-details
# application are in its own name; when that lands, `number_workspace` answers per tenant
# and the client below sends the header — nothing else in this module changes.


def number_workspace(tenant_id: UUID | None) -> str | None:
    """The vendor workspace holding `tenant_id`'s numbers: the developer workspace today."""
    return None


def _numbers_client(workspace: str | None) -> ThinnestNumbers:
    return thinnest_numbers()


async def vendor_numbers(workspace: str | None) -> list[ProvisionedNumber]:
    """Every number `workspace` holds, as our model. Through the adapter's listing, which
    the admin numbers screen also reads by this function."""
    return list(await get_engine().list_engine_numbers())


async def _attach(
    workspace: str | None, number: str, *, agent: str | None, calling_agent: str | None
) -> Attachment:
    return await _numbers_client(workspace).attach(number, agent=agent, calling_agent=calling_agent)


async def held_number(e164: str, *, tenant_id: UUID | None) -> ProvisionedNumber:
    """The voice platform's own record of `e164`, or the refusal that it holds no such
    number. Asked of the vendor's list every time: a hand-typed number is exactly the
    value that must not be trusted."""
    wanted = digits(e164)
    for number in await vendor_numbers(number_workspace(tenant_id)):
        if digits(number.engine_number_ref or number.e164) == wanted:
            return number
    raise ProblemError.business_rule(
        "engine_number_not_held",
        "The voice platform does not hold this number, so no call can be placed from it or "
        "answered on it.",
        remediation=(
            "Rent the number in the voice platform's console first, or check the digits, "
            "then record it again."
        ),
    )


async def _is_this_clients_agent(session: AsyncSession, engine_agent_ref: str) -> bool:
    """Is `engine_agent_ref` one of THIS client's agents? Asked under the tenant's own
    policy, in the caller's session: any other agent — another client's, or one we never
    published — is not this client's line to take."""
    found = (
        await session.execute(
            text("SELECT 1 FROM agents WHERE engine_agent_ref = :ref LIMIT 1"),
            {"ref": engine_agent_ref},
        )
    ).first()
    return found is not None


@dataclass(frozen=True, slots=True)
class RecordedEngineNumber:
    number_id: UUID
    e164: str
    series: str
    #: What the client pays a month; None for a number the vendor bills nothing for.
    client_inr_per_month: Decimal | None
    attachment: SyncOutcome


async def record_engine_number(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    e164: str,
    direction: str,
    agent_id: UUID | None,
    purpose: str | None,
    series: str | None = None,
    engine_number_ref: str | None = None,
) -> RecordedEngineNumber:
    """Record a number the voice platform holds against `tenant_id`, price it, attach it.

    Validated against the vendor's list, not against what was typed: the number must be
    held, a typed handle must be the vendor's own, and a number another client's agent
    answers is refused — taking it would move that client's line. In the tenant's session;
    the caller writes the audit row.
    """
    provider = engine_number_provider()
    if provider is None:
        raise _refuse_off_engine()
    held = await held_number(e164, tenant_id=tenant_id)
    vendor_ref = held.engine_number_ref or held.e164
    if engine_number_ref is not None and digits(engine_number_ref) != digits(vendor_ref):
        raise ProblemError.business_rule(
            "engine_number_ref_mismatch",
            "The handle typed for this number is not the one the voice platform holds it under.",
            remediation="Leave the handle blank; it is read from the voice platform.",
        )
    answering = held.answering_agent_ref
    if answering is not None and not await _is_this_clients_agent(session, answering):
        raise ProblemError.conflict(
            "engine_number_answered_by_other_client",
            "An agent that is not one of this client's answers this number on the voice platform.",
            remediation=(
                "Record it against the client whose agent answers it, or clear its Inbound "
                "agent in the voice platform's console first."
            ),
        )
    price = await require_attested_price_inr(session) if held.engine_owned else None
    declared = series or series_for_e164(held.e164) or "standard"
    number_id = await agents_service.provision_number(
        session,
        tenant_id=tenant_id,
        e164=held.e164,
        series=declared,
        agent_id=agent_id,
        provider=provider,
        direction=direction,
        purpose=purpose,
        engine_number_ref=vendor_ref,
        engine_owned=bool(held.engine_owned),
    )
    if price is not None:
        recorded_at = (
            await session.execute(
                text(
                    "UPDATE phone_numbers SET client_inr_per_month = :inr, updated_at = now() "
                    "WHERE id = :id RETURNING created_at"
                ),
                {"inr": price.inr_per_month, "id": number_id},
            )
        ).scalar_one()
        # THE FIRST PERIOD, in this transaction (D-665), anchored on the recording: the
        # renewal job computes its periods from the same `created_at`.
        await collect_number_rental(
            session,
            tenant_id=tenant_id,
            number_id=number_id,
            recorded_at=recorded_at,
            charged_from=None,
            period_start=ist_date(recorded_at),
            inr_per_month=price.inr_per_month,
        )
    attachment = await sync_number_attachment(session, number_id=number_id)
    log.info(
        "engine_number_recorded",
        extra={
            "tenant_id": str(tenant_id),
            "number_id": str(number_id),
            "priced": price is not None,
            "attachment": attachment,
        },
    )
    return RecordedEngineNumber(
        number_id=number_id,
        e164=held.e164,
        series=declared,
        client_inr_per_month=price.inr_per_month if price is not None else None,
        attachment=attachment,
    )


_UNPRICED_SQL: Final = (
    "SELECT created_at FROM phone_numbers WHERE id = :id AND client_inr_per_month IS NULL "
    "AND released_at IS NULL FOR UPDATE"
)


def _next_renewal(anchor: date, today: date) -> date:
    """The first renewal date of a number anchored on `anchor` that is after `today`."""
    current = rental_period_start(anchor, today)
    day = today
    while rental_period_start(anchor, day) == current:
        day += timedelta(days=1)
    return day


async def price_recorded_number(session: AsyncSession, *, number_id: UUID) -> bool:
    """Price a RENTED number that was recorded before recording priced it. True if priced.

    The period already under way is not charged: `rental_charged_from` is set to the next
    renewal date, the rule D-665 applied to numbers recorded before client rental existed,
    so a client is never back-charged for a month nobody quoted them. Unpriced while no
    rate is attested — the attestation is the only source a client price may come from.
    """
    recorded_at = (await session.execute(text(_UNPRICED_SQL), {"id": number_id})).scalar()
    if recorded_at is None:
        return False
    price = await attested_price_inr(session)
    if price is None:
        return False
    starts = _next_renewal(ist_date(recorded_at), today_ist())
    await session.execute(
        text(
            "UPDATE phone_numbers SET client_inr_per_month = :inr, engine_owned = true, "
            "rental_charged_from = :starts, updated_at = now() WHERE id = :id"
        ),
        {"inr": price.inr_per_month, "starts": starts, "id": number_id},
    )
    log.info(
        "engine_number_priced",
        extra={"number_id": str(number_id), "charged_from": starts.isoformat()},
    )
    return True


_ATTACHMENT_SQL: Final = (
    "SELECT n.engine_number_ref, n.provider, n.released_at, a.direction, a.status, "
    "a.engine_agent_ref, a.deleted_at, n.tenant_id FROM phone_numbers n "
    "LEFT JOIN agents a ON a.id = n.agent_id WHERE n.id = :nid"
)


def wanted_attachment(
    *,
    released: bool,
    direction: str | None,
    status: str | None,
    engine_agent_ref: str | None,
    archived: bool,
) -> tuple[str | None, str | None]:
    """`(agent, callingAgent)` as our rows say they should be. See the module docstring."""
    if released or archived or not engine_agent_ref or status != "live" or direction is None:
        return None, None
    if direction in ("inbound", "both"):
        return engine_agent_ref, None
    return None, engine_agent_ref


async def sync_number_attachment(session: AsyncSession, *, number_id: UUID) -> SyncOutcome:
    """Make the vendor's attachment of one of our numbers agree with our row.

    A refusal or a partial apply ALARMS and does not raise: the record is ours and correct,
    the operator's request succeeded, and the daily sweep tries again. `not_applicable` for
    a number that is not on this deployment's engine or has no vendor handle.
    """
    provider = engine_number_provider()
    row = (await session.execute(text(_ATTACHMENT_SQL), {"nid": number_id})).first()
    if provider is None or row is None or row[1] != provider or not row[0]:
        return "not_applicable"
    agent, calling = wanted_attachment(
        released=row[2] is not None,
        direction=row[3],
        status=row[4],
        engine_agent_ref=row[5],
        archived=row[6] is not None,
    )
    try:
        result = await _attach(
            number_workspace(row[7]), str(row[0]), agent=agent, calling_agent=calling
        )
    except ProblemError as exc:
        _attachment_failed(number_id, outcome="refused", refusal=exc.code)
        return "refused"
    if result.outcome in ("partial", "refused"):
        _attachment_failed(number_id, outcome=result.outcome, refusal=result.refusal)
    log.info(
        "engine_number_attachment_synced",
        extra={"number_id": str(number_id), "outcome": result.outcome},
    )
    return result.outcome


def _attachment_failed(number_id: UUID, *, outcome: str, refusal: str | None) -> None:
    alert(
        "CORE_LOGIC",
        "engine_number_attachment_failed",
        detail=(
            "the voice platform did not take which agent answers this number and which calls "
            f"out on it ({outcome}, {refusal or 'no code'}). Until it does, an incoming call "
            "reaches whatever the platform last held, and an outbound call from it may be "
            "refused. The daily number sweep retries; check the agent is published with voice "
            "switched on."
        ),
        number_id=str(number_id),
    )


_DIRECTORY: Final = "SELECT id FROM organizations WHERE deleted_at IS NULL ORDER BY id"
_ENGINE_ROWS: Final = (
    "SELECT id, e164, engine_number_ref FROM phone_numbers "
    "WHERE provider = :provider AND released_at IS NULL ORDER BY created_at, id"
)


async def live_tenants() -> list[UUID]:
    """The directory: the one read under the admin role."""
    async with admin_session() as directory:
        return [UUID(str(t)) for t in (await directory.execute(text(_DIRECTORY))).scalars()]


@dataclass(frozen=True, slots=True)
class NumberReconciliation:
    vendor: int
    ours: int
    unrecorded: int
    missing_at_vendor: int
    repaired: int
    failed: int
    unchecked: int
    #: Rented numbers recorded before they were priced, priced now from the next renewal.
    priced: int = 0


async def reconcile_engine_number_attachments() -> NumberReconciliation:
    """Compare the vendor's numbers with ours, both ways, and put every attachment back to
    our binding. Alarms; adopts nothing; deletes nothing.

    The directory is read under the admin role and nothing else is (`workers/number_rental`
    argues the shape); each tenant's numbers are read, and re-pointed, in its own session.
    """
    provider = engine_number_provider()
    if provider is None:
        return NumberReconciliation(0, 0, 0, 0, 0, 0, 0)
    # PER TENANT, against the list of the workspace that tenant's numbers live in; each
    # workspace is listed once. Unrecorded is per workspace: what it holds that none of the
    # tenants in it has recorded.
    listed: dict[str | None, dict[str, ProvisionedNumber]] = {}
    recorded: dict[str | None, set[str]] = {}
    held: dict[str, ProvisionedNumber] = {}
    ours: dict[str, tuple[UUID, UUID]] = {}
    missing: set[str] = set()
    for tenant_id in await live_tenants():
        workspace = number_workspace(tenant_id)
        if workspace not in listed:
            listed[workspace] = {
                digits(n.engine_number_ref or n.e164): n for n in await vendor_numbers(workspace)
            }
        async with tenant_session(tenant_id) as scoped:
            rows = (await scoped.execute(text(_ENGINE_ROWS), {"provider": provider})).all()
        for number_id, e164, ref in rows:
            key = digits(str(ref or e164))
            recorded.setdefault(workspace, set()).add(key)
            if key in listed[workspace]:
                ours[key] = (tenant_id, UUID(str(number_id)))
                held[key] = listed[workspace][key]
            else:
                missing.add(key)
    unrecorded = {
        key
        for workspace, numbers in listed.items()
        for key in numbers.keys() - recorded.get(workspace, set())
    }
    repaired = failed = priced = 0
    both = sorted(ours)
    for key in both[:ATTACHMENT_SWEEP_BUDGET]:
        tenant_id, number_id = ours[key]
        async with tenant_session(tenant_id) as scoped:
            if held[key].engine_owned:
                priced += await price_recorded_number(scoped, number_id=number_id)
            outcome = await sync_number_attachment(scoped, number_id=number_id)
        repaired += outcome == "applied"
        failed += outcome in ("partial", "refused")
    unchecked = max(len(both) - ATTACHMENT_SWEEP_BUDGET, 0)
    _alarm_reconciliation(unrecorded=len(unrecorded), missing=len(missing), repaired=repaired)
    summary = NumberReconciliation(
        vendor=sum(len(numbers) for numbers in listed.values()),
        ours=len(ours) + len(missing),
        unrecorded=len(unrecorded),
        missing_at_vendor=len(missing),
        repaired=repaired,
        failed=failed,
        unchecked=unchecked,
        priced=priced,
    )
    log.info("engine_number_reconciliation", extra=asdict(summary))
    return summary


def _alarm_reconciliation(*, unrecorded: int, missing: int, repaired: int) -> None:
    if unrecorded:
        alert(
            "CORE_LOGIC",
            "engine_number_unrecorded",
            detail=(
                f"{unrecorded} number(s) are held on the voice platform with no record here. "
                "A rented one is charged to us every month and billed to nobody; none of them "
                "is attached to an agent by us. Record each against its client from that "
                "client's Numbers page (Record this number), or release it in the voice "
                "platform's console. Nothing is recorded automatically."
            ),
            count=str(unrecorded),
        )
    if missing:
        alert(
            "CORE_LOGIC",
            "engine_number_missing_at_vendor",
            detail=(
                f"{missing} number(s) recorded here are not held on the voice platform, so the "
                "agents bound to them answer nothing on them and cannot call from them. Check "
                "whether the rental lapsed or the number was released in the console, then "
                "release our record or rent the number again."
            ),
            count=str(missing),
        )
    if repaired:
        alert(
            "CORE_LOGIC",
            "engine_number_attachment_repaired",
            detail=(
                f"{repaired} number(s) were answered by, or lent to, a different agent on the "
                "voice platform than our records say, and have been put back. Somebody may be "
                "changing attachments in the platform's console; make changes on the client's "
                "Numbers page instead, or they will be undone."
            ),
            count=str(repaired),
        )


async def read_business_details(workspace: str | None = None) -> BusinessDetails | None:
    """`workspace`'s business-details application (the developer workspace by default), or
    None where numbers are not the engine's."""
    if engine_number_provider() is None:
        return None
    return await _numbers_client(workspace).business_details()


def alarm_lapsed_business_details(details: BusinessDetails) -> bool:
    """Alarm when the application is rejected, suspended or expired. True when it did."""
    if details.status not in LAPSED_BUSINESS_STATUSES:
        return False
    alert(
        "CORE_LOGIC",
        "engine_business_details_lapsed",
        detail=(
            f"the voice platform's business-details application is {details.status}, so it "
            "will not rent a new Indian number for this workspace. Open the Phone Numbers "
            "KYC tab in the platform's console, correct what the review asks for and send "
            "the details again."
        ),
        status=details.status,
    )
    return True


__all__ = [
    "ATTACHMENT_SWEEP_BUDGET",
    "LAPSED_BUSINESS_STATUSES",
    "NumberReconciliation",
    "RecordedEngineNumber",
    "SyncOutcome",
    "alarm_lapsed_business_details",
    "engine_number_provider",
    "held_number",
    "live_tenants",
    "number_workspace",
    "price_recorded_number",
    "read_business_details",
    "reconcile_engine_number_attachments",
    "record_engine_number",
    "sync_number_attachment",
    "vendor_numbers",
    "wanted_attachment",
]
