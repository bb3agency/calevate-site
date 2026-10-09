"""Numbers on the voice platform: rent, record, attach, release, reconcile (D-691, D-693).

Each client has its own ThinnestAI customer workspace (D-693), and a client's numbers are
rented THERE, in the client's own business name, once its business details are approved.
Everything about a number happens in the workspace it lives in, and that workspace travels
in the number's handle (`phone_numbers.engine_number_ref`, `<digits>@<org_…>`). A number
rented in our developer workspace before D-693 has an unscoped handle: it is "held in the
platform account", may be recorded against a client for testing only, and can answer only
an agent that still lives in the developer workspace.

**WE ARE THE MASTER OF THE ATTACHMENT.** `phone_numbers.agent_id` says which agent a number
belongs to; the vendor's `agent` / `callingAgent` are made to agree with it, at the moment
a number is recorded or attached and again by the daily sweep, which repairs any drift. The
wanted state, from our rows:

* a released number, or one bound to no live published agent: nobody answers, nobody calls;
* an agent that answers (`inbound`, `both`): it is the number's line (`agent`). An agent can
  call out on its own line ("its own, or one lent to it", `calls/place-call.md:974`), so
  `callingAgent` is cleared rather than set to the same agent — which the vendor refuses
  (409, `phone-numbers/update-phone-number.md:401-405`);
* an outbound-only agent: lent the number to call out on (`callingAgent`), answering nothing;
* an agent in another workspace than the number's: nobody answers. The vendor could not
  find the agent there (`engine_number_other_workspace`).

**NOTHING IS ADOPTED AUTOMATICALLY.** A number the vendor holds that we have no record of is
alarmed, never recorded: which client it belongs to is an operator's decision.

**A RENTED NUMBER IS PRICED FOR THE CLIENT WHEN IT IS RECORDED** from the operator-attested
monthly rate (`number_pricing`, OPERATIONS §2 gate 26), never from the vendor's
`monthlyPrice`, and its first period is collected in the same transaction (D-665); the
renewal job bills it from then on. A purchase (`purchase_engine_number`) is this same
record step run straight after the rent, so it has no charge path of its own.

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
from calevate_shared.engine_scope import scope_of
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import service as agents_service
from apps.api.agents.models import series_for_e164
from apps.api.billing.number_rental import (
    RentalOutcome,
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
    AvailableCity,
    AvailablePage,
    BusinessDetails,
    digits,
    thinnest_numbers,
)
from apps.api.engine.thinnest_workspace import in_workspace, workspace_not_provisioned
from apps.api.tenancy.engine_workspace import (
    active_workspaces,
    resolve_workspace,
)

log = get_logger(__name__)

#: Business-details states in which the platform will not rent a new Indian number
#: (`phone-numbers/get-business-details.md:425-436`): each needs somebody to act.
LAPSED_BUSINESS_STATUSES: Final = frozenset({"rejected", "suspended", "expired"})

#: Numbers read back and, where needed, re-pointed per sweep. The estate is a handful per
#: client; the bound keeps one bad day from becoming a rate-limit incident.
ATTACHMENT_SWEEP_BUDGET: Final = 100

SyncOutcome = Literal[
    "not_applicable", "unchanged", "applied", "partial", "refused", "other_workspace"
]


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


def is_platform_held(engine_number_ref: str | None) -> bool:
    """A number in our developer workspace ("held in the platform account"): testing only."""
    return bool(engine_number_ref) and scope_of(engine_number_ref) is None


def releasable_by(engine_number_ref: str, *, own_workspace: str | None, by_admin: bool) -> bool:
    """May this number be released at the vendor by this caller? A platform-held number is
    an operator's to release; any other only from the client's own workspace, the one its
    handle names. The release route and the client's numbers list both ask this, so the
    list never offers a Release the route refuses."""
    if is_platform_held(engine_number_ref):
        return by_admin
    return own_workspace is not None and scope_of(engine_number_ref) == own_workspace


def answers_calls(
    *,
    engine_number_ref: str | None,
    agent_ref: str | None,
    agent_status: str | None,
    agent_direction: str | None,
    agent_deleted: bool,
) -> bool:
    """Does our record put an answering agent on this number? The vendor's `agent` is made
    to agree with exactly this (`wanted_attachment`, the crossed-workspace rule of
    `sync_number_attachment`), and the daily sweep repairs drift, so it stands in for the
    carrier binding the Pipecat engine records."""
    if not engine_number_ref:
        return False
    agent, _calling = wanted_attachment(
        released=False,
        direction=agent_direction,
        status=agent_status,
        engine_agent_ref=agent_ref,
        archived=agent_deleted,
    )
    return agent is not None and scope_of(agent) == scope_of(engine_number_ref)


# --- THE ONE SEAM to the vendor's numbers -----------------------------------------------
#
# Every call about a vendor number goes through the functions below. A number we hold
# names its own workspace in its handle; a tenant's workspace for a NEW number comes from
# `tenancy/engine_workspace.resolve_workspace`, which never falls back to the developer
# workspace.


async def vendor_numbers(workspace: str | None) -> list[ProvisionedNumber]:
    """Every number `workspace` holds (None: our developer workspace), as our model with
    handles scoped to it."""
    with in_workspace(workspace):
        return list(await get_engine().list_engine_numbers())


async def _attach(number_ref: str, *, agent: str | None, calling_agent: str | None) -> Attachment:
    return await thinnest_numbers().attach(number_ref, agent=agent, calling_agent=calling_agent)


async def held_number(e164: str, *, own_workspace: str | None) -> ProvisionedNumber:
    """The voice platform's own record of `e164`: in the tenant's own workspace first, then in
    our developer workspace (a platform-held number). Or the refusal that neither holds it.
    Asked of the vendor's list every time: a hand-typed number is exactly the value that
    must not be trusted."""
    wanted = digits(e164)
    places: list[str | None] = [own_workspace] if own_workspace is not None else []
    places.append(None)
    for workspace in places:
        for number in await vendor_numbers(workspace):
            if digits(number.engine_number_ref or number.e164) == wanted:
                return number
    raise ProblemError.business_rule(
        "engine_number_not_held",
        "The voice platform does not hold this number, so no call can be placed from it or "
        "answered on it.",
        remediation=(
            "Buy the number from the client's Numbers page, or check the digits, then record "
            "it again."
        ),
    )


async def _is_this_clients_agent(session: AsyncSession, engine_agent_ref: str) -> bool:
    """Is `engine_agent_ref` one of THIS client's agents? Asked under the tenant's own
    policy, in the caller's session."""
    found = (
        await session.execute(
            text("SELECT 1 FROM agents WHERE engine_agent_ref = :ref LIMIT 1"),
            {"ref": engine_agent_ref},
        )
    ).first()
    return found is not None


def _other_workspace_refusal() -> ProblemError:
    return ProblemError.business_rule(
        "engine_number_other_workspace",
        "This number is held in the platform account and can only answer an agent that still "
        "lives there; this agent lives in the client's own workspace.",
        remediation=(
            "Buy a number for this client from its Numbers page, or keep this number for "
            "testing with an agent that has not been republished."
        ),
    )


async def assert_same_workspace(
    session: AsyncSession, *, number_ref: str, agent_id: UUID | None
) -> None:
    if agent_id is None:
        return
    ref = (
        await session.execute(
            text("SELECT engine_agent_ref FROM agents WHERE id = :aid AND deleted_at IS NULL"),
            {"aid": agent_id},
        )
    ).scalar()
    if isinstance(ref, str) and ref and scope_of(ref) != scope_of(number_ref):
        raise _other_workspace_refusal()


async def assert_number_can_answer(
    session: AsyncSession, *, number_id: UUID, agent_id: UUID | None
) -> None:
    """Refuse binding a voice-platform number to an agent in another workspace (D-693): the
    vendor could not find the agent there, so the binding would be ours alone."""
    if engine_number_provider() is None or agent_id is None:
        return
    ref = (
        await session.execute(
            text("SELECT engine_number_ref FROM phone_numbers WHERE id = :nid AND provider = :p"),
            {"nid": number_id, "p": engine_number_provider()},
        )
    ).scalar()
    if isinstance(ref, str) and ref:
        await assert_same_workspace(session, number_ref=ref, agent_id=agent_id)


@dataclass(frozen=True, slots=True)
class RecordedEngineNumber:
    number_id: UUID
    e164: str
    series: str
    #: What the client pays a month; None for a number the vendor bills nothing for.
    client_inr_per_month: Decimal | None
    attachment: SyncOutcome
    #: Held in our developer workspace: assigned to this client for testing only.
    platform_held: bool = False
    #: What became of the client's first month (`billing/number_rental.RentalOutcome`):
    #: `charged`, `invoiced`, `trial` (free), `closed`, `replayed`, or None when the number
    #: is not priced. A screen words its sentence from this, never from the price alone.
    first_period: RentalOutcome | None = None


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
    if is_trial_number(e164) or is_trial_number(engine_number_ref):
        raise ProblemError.conflict(
            "engine_number_is_trial_number",
            "This number is the shared number free-trial test calls ring from, so it cannot "
            "be recorded against a client.",
            remediation="Record another number, or set a different shared trial number first.",
        )
    held = await held_number(e164, own_workspace=await resolve_workspace(session, tenant_id))
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
    # The agent it is LENT to for calling out counts too: recording it would hand that
    # agent's caller ID to this client. `callingAgent` is documented on the single read only
    # (`get-phone-number.md:405-418`; the list carries `agent` alone), so it is read here.
    calling = (
        held.calling_agent_ref or (await thinnest_numbers().get_number(vendor_ref)).calling_agent
    )
    if calling is not None and not await _is_this_clients_agent(session, calling):
        raise ProblemError.conflict(
            "engine_number_lent_to_other_client",
            "An agent that is not one of this client's calls out on this number on the voice "
            "platform.",
            remediation=(
                "Record it against the client whose agent calls out on it, or clear its "
                "Outbound agent in the voice platform's console first."
            ),
        )
    await assert_same_workspace(session, number_ref=vendor_ref, agent_id=agent_id)
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
    first_period: RentalOutcome | None = None
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
        first_period = await collect_number_rental(
            session,
            tenant_id=tenant_id,
            number_id=number_id,
            recorded_at=recorded_at,
            charged_from=None,
            period_start=ist_date(recorded_at),
            inr_per_month=price.inr_per_month,
        )
    attachment = await sync_number_attachment(session, number_id=number_id)
    platform_held = is_platform_held(vendor_ref)
    log.info(
        "engine_number_recorded",
        extra={
            "tenant_id": str(tenant_id),
            "number_id": str(number_id),
            "priced": price is not None,
            "attachment": attachment,
            "platform_held": platform_held,
        },
    )
    return RecordedEngineNumber(
        number_id=number_id,
        e164=held.e164,
        series=declared,
        client_inr_per_month=price.inr_per_month if price is not None else None,
        attachment=attachment,
        platform_held=platform_held,
        first_period=first_period,
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
    a number that is not on this deployment's engine or has no vendor handle;
    `other_workspace` for a platform-held number bound to an agent that now lives in the
    client's own workspace — nobody answers it, and the admin screen names why.
    """
    provider = engine_number_provider()
    row = (await session.execute(text(_ATTACHMENT_SQL), {"nid": number_id})).first()
    if provider is None or row is None or row[1] != provider or not row[0]:
        return "not_applicable"
    number_ref = str(row[0])
    agent, calling = wanted_attachment(
        released=row[2] is not None,
        direction=row[3],
        status=row[4],
        engine_agent_ref=row[5],
        archived=row[6] is not None,
    )
    crossed = any(
        handle is not None and scope_of(handle) != scope_of(number_ref)
        for handle in (agent, calling)
    )
    if crossed:
        agent = calling = None
    try:
        result = await _attach(number_ref, agent=agent, calling_agent=calling)
    except ProblemError as exc:
        _attachment_failed(number_id, outcome="refused", refusal=exc.code)
        return "refused"
    if result.outcome in ("partial", "refused"):
        _attachment_failed(number_id, outcome=result.outcome, refusal=result.refusal)
    log.info(
        "engine_number_attachment_synced",
        extra={"number_id": str(number_id), "outcome": result.outcome, "crossed": crossed},
    )
    if crossed and result.outcome in ("unchanged", "applied"):
        return "other_workspace"
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
    #: Workspaces listed: the developer workspace and every active customer workspace.
    workspaces: int = 0


def _key(workspace: str | None, number: str) -> tuple[str | None, str]:
    return workspace, digits(number)


async def reconcile_engine_number_attachments() -> NumberReconciliation:
    """Compare every workspace's numbers with ours, both ways, and put every attachment back
    to our binding. Alarms; adopts nothing; deletes nothing.

    PER WORKSPACE: the developer workspace (platform-held numbers) and each active customer
    workspace are listed once; each of our numbers is matched in the workspace its handle
    names. The directory is read under the admin role and nothing else is; each tenant's
    numbers are read, and re-pointed, in its own session.
    """
    provider = engine_number_provider()
    if provider is None:
        return NumberReconciliation(0, 0, 0, 0, 0, 0, 0)
    workspaces: list[str | None] = [None]
    workspaces.extend(row.workspace_id for row in await active_workspaces())
    listed: dict[tuple[str | None, str], ProvisionedNumber] = {}
    for workspace in workspaces:
        for number in await vendor_numbers(workspace):
            listed[_key(workspace, number.engine_number_ref or number.e164)] = number
    ours: dict[tuple[str | None, str], tuple[UUID, UUID]] = {}
    missing: set[tuple[str | None, str]] = set()
    for tenant_id in await live_tenants():
        async with tenant_session(tenant_id) as scoped:
            rows = (await scoped.execute(text(_ENGINE_ROWS), {"provider": provider})).all()
        for number_id, e164, ref in rows:
            handle = str(ref or e164)
            key = _key(scope_of(handle), handle)
            if scope_of(handle) is None and is_trial_number(handle):
                # The shared trial number is the platform's, lent per test call (D-697).
                # Recorded against a client, the sweep would re-point it under a live call.
                _alarm_trial_number_recorded(tenant_id)
                continue
            if key in listed:
                ours[key] = (tenant_id, UUID(str(number_id)))
            else:
                missing.add(key)
    unrecorded = set(listed) - set(ours)
    trial = trial_number_ref()
    if trial is not None:
        unrecorded.discard(_key(None, trial))
    repaired = failed = priced = 0
    both = sorted(ours, key=lambda k: (k[0] or "", k[1]))
    for key in both[:ATTACHMENT_SWEEP_BUDGET]:
        tenant_id, number_id = ours[key]
        async with tenant_session(tenant_id) as scoped:
            if listed[key].engine_owned:
                priced += await price_recorded_number(scoped, number_id=number_id)
            outcome = await sync_number_attachment(scoped, number_id=number_id)
        repaired += outcome == "applied"
        failed += outcome in ("partial", "refused")
    unchecked = max(len(both) - ATTACHMENT_SWEEP_BUDGET, 0)
    _alarm_reconciliation(unrecorded=len(unrecorded), missing=len(missing), repaired=repaired)
    summary = NumberReconciliation(
        vendor=len(listed),
        ours=len(ours) + len(missing),
        unrecorded=len(unrecorded),
        missing_at_vendor=len(missing),
        repaired=repaired,
        failed=failed,
        unchecked=unchecked,
        priced=priced,
        workspaces=len(workspaces),
    )
    log.info("engine_number_reconciliation", extra=asdict(summary))
    return summary


def _alarm_trial_number_recorded(tenant_id: UUID) -> None:
    alert(
        "CORE_LOGIC",
        "trial_number_recorded_to_client",
        detail=(
            "the number set as the shared trial number is also recorded against a client. "
            "The number sweep leaves it alone, because free-trial test calls lend it to a "
            "different agent for every call. Release that client's record of it, or set "
            "another number as the shared trial number."
        ),
        tenant_id=str(tenant_id),
    )


def _alarm_reconciliation(*, unrecorded: int, missing: int, repaired: int) -> None:
    if unrecorded:
        alert(
            "CORE_LOGIC",
            "engine_number_unrecorded",
            detail=(
                f"{unrecorded} number(s) are held on the voice platform with no record here. "
                "A rented one is charged to us every month and billed to nobody; none of them "
                "is attached to an agent by us. Record each against its client from that "
                "client's Numbers page (Record this number), or release it. Nothing is "
                "recorded automatically."
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
                "whether the rental lapsed or the number was released, then release our record "
                "or rent the number again."
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


# --- the shared trial number (D-697) -----------------------------------------------------


def trial_number_ref() -> str | None:
    """The shared trial number as our handle (its digits, unscoped: it is held in the
    developer workspace), or None while the console names none."""
    number = get_settings().trial_caller_number
    return digits(number) if number else None


def is_trial_number(e164_or_ref: str | None) -> bool:
    trial = trial_number_ref()
    return bool(trial and e164_or_ref) and digits(str(e164_or_ref)) == trial


async def lend_trial_line(agent_ref: str) -> bool:
    """Lend the shared trial number to `agent_ref` for one test call, and make sure nothing
    answers it. True once the platform holds exactly that.

    `callingAgent` "calls out on the number without answering it", and `agent: null` "makes
    nothing answer it" (`thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/
    phone-numbers/update-phone-number.md:451-470`), so an inbound call to the shared number
    can never reach a trial client's agent. A call's `from` must be one of the agent's
    numbers, "its own, or one lent to it" (`calls/place-call.md:430-433,971-977`), which is
    why the number is lent before each call. The caller holds the trial line
    (`agents.service._hold_trial_line`) from before this until the call ends: what
    re-pointing `callingAgent` does to a call already in progress is not documented.
    """
    number = trial_number_ref()
    if number is None:
        return False
    try:
        result = await _attach(number, agent=None, calling_agent=agent_ref)
    except ProblemError as exc:
        _trial_line_failed(outcome="refused", refusal=exc.code)
        return False
    if result.outcome in ("partial", "refused"):
        _trial_line_failed(outcome=result.outcome, refusal=result.refusal)
        return False
    return True


def _trial_line_failed(*, outcome: str, refusal: str | None) -> None:
    alert(
        "CORE_LOGIC",
        "trial_line_lend_failed",
        detail=(
            "a free-trial test call could not be placed because the voice platform did not "
            f"lend the shared trial number to the calling agent ({outcome}, "
            f"{refusal or 'no code'}). Check that the number set as the shared trial number "
            "is held in our developer workspace and that the agent is published with voice "
            "switched on."
        ),
    )


# --- business details --------------------------------------------------------------------


async def read_business_details(workspace: str | None = None) -> BusinessDetails | None:
    """`workspace`'s business-details application (the developer workspace by default), or
    None where numbers are not the engine's."""
    if engine_number_provider() is None:
        return None
    return await thinnest_numbers().business_details(workspace)


def alarm_lapsed_business_details(
    details: BusinessDetails, *, tenant_id: UUID | None = None
) -> bool:
    """Alarm when the application is rejected, suspended or expired. True when it did."""
    if details.status not in LAPSED_BUSINESS_STATUSES:
        return False
    alert(
        "CORE_LOGIC",
        "engine_business_details_lapsed",
        detail=(
            f"the voice platform's business-details application is {details.status}, so it "
            "will not rent a new Indian number for this workspace. A rejected one says what to "
            "correct on the client's admin page: the client fixes it under Verify your "
            "business and sends it again. An expired one is sent again automatically."
        ),
        status=details.status,
        tenant_id=str(tenant_id) if tenant_id is not None else "platform",
    )
    return True


# --- buying a number ----------------------------------------------------------------------


async def _own(session: AsyncSession, tenant_id: UUID) -> str:
    workspace = await resolve_workspace(session, tenant_id)
    if workspace is None:
        raise workspace_not_provisioned()
    return workspace


async def available_cities(session: AsyncSession, tenant_id: UUID) -> list[AvailableCity]:
    workspace = await _own(session, tenant_id)
    return await thinnest_numbers().cities(workspace)


async def search_available(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    city: str | None,
    pattern: str | None,
    cursor: str | None,
) -> AvailablePage:
    workspace = await _own(session, tenant_id)
    return await thinnest_numbers().search(workspace, city=city, pattern=pattern, cursor=cursor)


__all__ = [
    "ATTACHMENT_SWEEP_BUDGET",
    "LAPSED_BUSINESS_STATUSES",
    "NumberReconciliation",
    "RecordedEngineNumber",
    "SyncOutcome",
    "alarm_lapsed_business_details",
    "answers_calls",
    "assert_number_can_answer",
    "assert_same_workspace",
    "available_cities",
    "engine_number_provider",
    "held_number",
    "is_platform_held",
    "is_trial_number",
    "lend_trial_line",
    "live_tenants",
    "price_recorded_number",
    "read_business_details",
    "reconcile_engine_number_attachments",
    "record_engine_number",
    "releasable_by",
    "search_available",
    "sync_number_attachment",
    "trial_number_ref",
    "vendor_numbers",
    "wanted_attachment",
]
