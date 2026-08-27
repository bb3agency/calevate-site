"""Reading the client's own DLT Principal Entity registration (SEC-COMP §3).

The read half of a fact that only ops may write. `campaigns.service.record_dlt_registration`
records what the registrar says about a client's Principal Entity — deliberately with no
client-facing write route, because a client who could mark their own PE `active` would be
marking the launch gate green on a registration that does not exist. That reasoning covers
the WRITE and was silently applied to the read as well, which left the client with a launch
button disabled by `pe_registration_missing` / `pe_registration_not_active` and no page
anywhere that said what the registrar currently holds.

So: one function, on the caller's RLS-scoped session, returning the four facts a client is
entitled to about their own entity — what state it is in, which entity id it names, when it
was registered, and when WE last verified it — plus the PE→TM link, which fails separately
and sends the client to a different desk (`tm_link_not_active`).

**Absence is a value, not an exception.** Every tenant starts with no row, and a `None`
return would push each caller into inventing the same "not filed yet" shape. `recorded`
carries it explicitly so an empty registration and an unfiled one are one type.

**Hard rule 1.** The query carries `tenant_id` as a predicate AND runs under RLS. The
predicate is not the isolation — the GUC is — but a read whose predicate names the tenant
cannot silently start returning another tenant's row if a policy is ever loosened; it
returns zero rows twice over.

**Not the TM registration.** Calevate's own telemarketer registration is one global fact in
`platform_state`, read by `ops.service.read_tm_registration` and surfaced on
`GET /v1/ops/platform`. It is not per tenant and is not repeated here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.settings import get_settings
from apps.api.ops.service import TM_REGISTRATION_MISSING_REASON, read_tm_registration


@dataclass(frozen=True, slots=True)
class PeRegistration:
    """What the registrar says about THIS client, as the platform last verified it."""

    # False = no row at all, which is the normal state of a new account and a different
    # fact from `status='not_started'` ("we have begun and are nowhere"). The launch gate
    # already distinguishes them (`pe_registration_missing` vs `pe_registration_not_active`)
    # and a client-facing view that collapsed them would explain the wrong next action.
    recorded: bool
    status: str | None
    tm_link_status: str | None
    pe_id: str | None
    entity_name: str | None
    registered_at: datetime | None
    verified_at: datetime | None

    @property
    def is_active(self) -> bool:
        """The client half of SEC-COMP §3's first bullet, in one property.

        Both halves, because both are required and either one failing stops the dialling:
        an entity registration that never authorised Calevate as its telemarketer places
        no calls. Computed here rather than in the console so this and
        `campaigns.service.launch_blockers` can never answer the question differently.
        """
        return self.status == "active" and self.tm_link_status == "active"


# The client-facing wording of the two DLT-entity refusals that are fixed text. They
# used to live in `campaigns/service.py` beside the provenance reasons; they moved here
# with the predicate below, so the strings and the condition that emits them are one
# artefact rather than two that have to be kept in step by hand.
PE_MISSING_REASON = (
    "This business is not yet registered as a DLT Principal Entity. Outbound campaigns "
    "cannot launch until it is; answering inbound calls is unaffected."
)
TM_LINK_REASON = (
    "Your DLT Principal Entity has not authorised Calevate as its telemarketer. "
    "Outbound campaigns cannot launch until that link is active."
)
PE_VERIFICATION_STALE_REASON = (
    "This business's DLT Principal Entity registration has not been re-checked against "
    "the registrar recently enough. Ask Calevate to re-verify it before launching."
)


NOT_RECORDED = PeRegistration(
    recorded=False,
    status=None,
    tm_link_status=None,
    pe_id=None,
    entity_name=None,
    registered_at=None,
    verified_at=None,
)


async def read_pe_registration(session: AsyncSession, *, tenant_id: UUID) -> PeRegistration:
    """This tenant's PE registration, on the caller's RLS-scoped session.

    Returns `NOT_RECORDED` when there is no row — including for a session scoped to a
    different tenant, or one with no tenant GUC at all, both of which see zero rows by
    policy. That is the correct answer in every case: this session cannot see a
    registration, so as far as it is concerned there is none.
    """
    row = (
        await session.execute(
            text(
                "SELECT status, tm_link_status, pe_id, entity_name, registered_at, verified_at "
                "FROM dlt_registrations WHERE tenant_id = :tid"
            ),
            {"tid": tenant_id},
        )
    ).first()
    if row is None:
        return NOT_RECORDED
    return PeRegistration(
        recorded=True,
        status=str(row[0]),
        tm_link_status=str(row[1]),
        pe_id=row[2],
        entity_name=row[3],
        registered_at=row[4],
        verified_at=row[5],
    )


async def pe_registration_blocker(
    session: AsyncSession, *, tenant_id: UUID
) -> tuple[str, str] | None:
    """`(rule, reason)` if this client's DLT entity blocks their outbound, else None.

    SEC-COMP §3's first bullet, CLIENT half — the same shape `kyc_blocker` and
    `first_campaign_hold_blocker` return, so every caller composes them identically.

    It lives HERE rather than inside `campaigns.service._entity_blockers`, where it was
    written, because the condition is a fact about the TENANT and not about a campaign:
    the launch gate asks it, the dispatch tick asks it, and the operator console's health
    board asks it of a client with no campaign at all. `_entity_blockers` held its own
    `SELECT status, tm_link_status FROM dlt_registrations`, which was a SECOND spelling of
    the read `read_pe_registration` above already owned — two queries that had to be kept
    in step by hand for one condition. Moving the predicate collapses them: there is now
    one read of the table and one place the three rule names are decided.
    (`tests/consent_provenance_test.py` and `tests/tm_registration_test.py` pin all three
    names, so a mistake in this move is loud rather than silent.)

    Sequential, not exhaustive, and only for the TM link: a link to an entity that is not
    registered cannot be active either, and telling a client to chase an authorisation for
    a registration they do not yet have sends them to the wrong desk. A missing row and a
    pending one stay different blockers, because the registrar and the client are
    different next actions.

    **AND A VERIFICATION GOES STALE.** `verified_at` was selected, returned to the client
    screen and compared to nothing, so a PE verified once was verified forever — the one
    fact on this row that decays with time was the one nothing aged. Its two neighbours
    both already treat that as unacceptable: the national-DND scrub expires at midnight
    on the day it ran (`preference_scrub.scrub_expiry`, "a scrub is valid only to the end
    of the day it was produced") and `KYC_STATUSES` carries `expired`, both because a
    stale compliance verdict is worse than none — it is indistinguishable from a fresh
    one at the moment somebody relies on it. The window is `pe_verification_max_age_days`
    (config, default 365, OURS rather than a registrar's — see the field), and `0`
    disables the check.

    LAST, deliberately. "We have not re-checked this recently" is the weakest of the four
    and the only one whose next action is Calevate's rather than the client's, so it must
    not mask a registration the registrar has actually suspended.
    """
    registration = await read_pe_registration(session, tenant_id=tenant_id)
    if not registration.recorded:
        return ("pe_registration_missing", PE_MISSING_REASON)
    if registration.status != "active":
        return (
            "pe_registration_not_active",
            f"This business's DLT Principal Entity registration is "
            f"{str(registration.status).replace('_', ' ')}; only an active registration "
            "may place campaign calls. Inbound answering is unaffected.",
        )
    if registration.tm_link_status != "active":
        return ("tm_link_not_active", TM_LINK_REASON)
    if pe_verification_is_stale(registration.verified_at):
        return ("pe_verification_stale", PE_VERIFICATION_STALE_REASON)
    return None


def pe_verification_is_stale(verified_at: datetime | None, *, now: datetime | None = None) -> bool:
    """Has our own check of this registration aged out of `pe_verification_max_age_days`?

    NEVER VERIFIED COUNTS AS STALE, and that is the whole point rather than an edge case:
    an `active` row nobody ever checked against the registrar is precisely the state this
    blocker exists to catch — somebody typed `active` and the campaign gate believed it.

    A pure function beside the predicate so the client-facing registration screen can show
    "re-verification due" from the same rule the gate refuses on, instead of the two
    disagreeing on the day it matters.
    """
    max_age = get_settings().pe_verification_max_age_days
    if max_age <= 0:
        return False
    if verified_at is None:
        return True
    # `timestamptz` in, aware out — but a row written by a path that lost the tzinfo
    # would raise on the comparison rather than answer it, and a compliance predicate that
    # 500s is a launch gate that fails open on the operator's retry. UTC in the DB.
    if verified_at.tzinfo is None:
        verified_at = verified_at.replace(tzinfo=UTC)
    return verified_at + timedelta(days=max_age) <= (now or datetime.now(UTC))


async def outbound_entity_blockers(
    session: AsyncSession, *, tenant_id: UUID
) -> list[tuple[str, str]]:
    """WHO may place an outbound call: Calevate's TM registration live AND this client's
    DLT Principal Entity registration + TM link active.

    SEC-COMP §3's first bullet, both halves, and LEGAL-OPS-PLAYBOOK §10.8/§16-C's rule
    that ALL regulated outbound — a bulk campaign, a single "call this lead", an instant
    requested callback — is off until the TM-ID exists and that client's PE-TM chain is
    Active. It is the platform+tenant half of outbound eligibility and knows nothing
    about any campaign, so the ONE implementation is read by the campaign launch/dispatch
    gate (`campaigns.service._entity_blockers`) AND the per-dial gate
    (`compliance.service.check_dispatch`) for the single-lead/callback paths — the two
    gates cannot drift into asking it two different ways.

    Returns a LIST rather than short-circuiting because the campaign launch preview must
    be able to show BOTH that Calevate's TM registration is down (nothing to do at the
    client's end) AND that their own PE chain is incomplete: a client who fixes their PE
    during our TM outage should see that progress. `check_dispatch`, which renders a
    single disabled-button reason, takes the first. Ours comes first because it is not a
    fact about this client at all — one row in `platform_state`, false for everybody at
    once — and a call placed while it is down is Calevate dialling as an unregistered
    telemarketer, not a client with a paperwork gap.
    """
    blockers: list[tuple[str, str]] = []
    if not (await read_tm_registration(session)).is_live:
        blockers.append(("tm_registration_missing", TM_REGISTRATION_MISSING_REASON))
    pe = await pe_registration_blocker(session, tenant_id=tenant_id)
    if pe is not None:
        blockers.append(pe)
    return blockers


__all__ = [
    "NOT_RECORDED",
    "PE_MISSING_REASON",
    "PE_VERIFICATION_STALE_REASON",
    "TM_LINK_REASON",
    "PeRegistration",
    "outbound_entity_blockers",
    "pe_registration_blocker",
    "pe_verification_is_stale",
    "read_pe_registration",
]
