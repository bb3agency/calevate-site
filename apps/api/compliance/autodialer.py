"""The client's declaration of the numbers its automated calls come from (D-941).

WHAT THE OBLIGATION IS, AND HOW SURE WE ARE OF IT
-------------------------------------------------
The TCCCPR amendment of 18 Sep 2026 replaces Regulation 4 with "Intimation regarding use of
A2P calls": a Sender declares its A2P calls (calls placed by software, "including ...
pre-recorded/artificial voice technologies", cl.2(ea)) to its Originating Access Provider in
advance, with the CLI ranges it will use, and "Any such call made by a Sender without prior
declaration to the OAP, shall be treated as Unsolicited commercial communication". It is a
60-day item, so it bites about 17 Nov 2026. Source: `docs/research/research_notes/Calevate
market and technology edge/india_regulation.md` lines 37-38 and 62 (read 30 Oct 2026,
rememory 8a05aded); the Gazette date is NOT verified, which is why the date the gate starts
refusing is the live setting `a2p_declaration_enforced_from`, not a constant.

**UNKNOWN, and the gate is built so neither answer breaks it:** who the Sender is when a
client calls from a number rented through us (the client, Calevate or the voice platform),
and the exact filing route (asked of the voice platform the week of 30 Oct 2026; OPERATIONS
§2 gate 59). The record is the client's own statement of which numbers it calls from and
when and how it declared them, with an attestation; if the answer turns out to be that we
file, the same record is what we would file from.

WHY A DATE GATES THE GATE
-------------------------
Before the rule bites nothing is refused: refusing early would stop clients' calling over a
duty that does not exist yet. The screens ask for the declaration from now on, and from the
enforcement date (IST) every outbound dial from an undeclared number is refused.

INBOUND IS UNTOUCHED
--------------------
An A2P call is one the platform PLACES. A receptionist answering a call the customer placed
places nothing, and no inbound path reaches `check_dispatch`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.plans import IST
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7

DeclarationState = Literal["notified", "withdrawn"]

#: Ours, not the regulator's: a small business presents a handful of numbers, and a list of
#: dozens is one somebody pasted by mistake.
MAX_DECLARED_CLIS: Final = 20
MAX_NOTICE_REFERENCE_CHARS: Final = 200

#: The attestation the person recording the declaration accepts, versioned like the pledge
#: (`outbound_pledge.py`): the row keeps the version and the SHA-256 of the exact text, and
#: a screen showing an older text is refused rather than recorded against the new one.
DECLARATION_VERSION: Final = 1
DECLARATION_TEXT: Final = (
    "On behalf of this business I confirm that the numbers listed are the numbers our "
    "automated calls come from, that we declared them in advance to the telephone company "
    "that provides them on the date shown, and that we will declare any new number before "
    "it places an automated call."
)
DECLARATION_TEXT_SHA256: Final = hashlib.sha256(DECLARATION_TEXT.encode("utf-8")).hexdigest()

A2P_DECLARATION_MISSING_RULE: Final = "a2p_declaration_missing"
A2P_DECLARATION_NOT_YET_EFFECTIVE_RULE: Final = "a2p_declaration_not_yet_effective"
A2P_NUMBER_UNDECLARED_RULE: Final = "a2p_number_undeclared"
A2P_TEST_CALL_OWN_NUMBER_RULE: Final = "a2p_test_call_own_number_only"

# Client-facing: short, the next action first, no provider named (D-679), and inbound said
# because "calls are paused" read alone sounds like the line is down.
A2P_DECLARATION_MISSING_REASON: Final = (
    "Declare your calling numbers to place calls. Incoming calls still work."
)
A2P_NUMBER_UNDECLARED_REASON: Final = (
    "This agent calls from a number you have not declared. Add it to your calling numbers. "
    "Incoming calls still work."
)
A2P_TEST_CALL_OWN_NUMBER_REASON: Final = (
    "Test calls can ring only your own phone. Tick that the number is your own to place it."
)


def a2p_declaration_not_yet_effective_reason(effective_on: date) -> str:
    """The wording when the declaration on file is dated in the future."""
    return (
        f"Your calling numbers count as declared from {effective_on.isoformat()}. Calls can "
        "start then. Incoming calls still work."
    )


def ist_today() -> date:
    return datetime.now(IST).date()


def enforced_from() -> date:
    """The first IST day the gate refuses (`a2p_declaration_enforced_from`, live)."""
    return get_settings().a2p_declaration_enforced_from


def enforcement_active(today: date | None = None) -> bool:
    return (today or ist_today()) >= enforced_from()


@dataclass(frozen=True, slots=True)
class Declaration:
    """The latest declaration a tenant recorded, read as an answer rather than a history.

    `recorded` is False for a tenant with no row, a different fact from a withdrawn one.
    `attested` is False for a row recorded before D-941 (the D-637 notice), which named a
    provider and an objective but carries no attestation of the current text: it does not
    cover a dial, and the client records the declaration once more.
    """

    recorded: bool
    state: DeclarationState | None
    notified_on: date | None
    notice_reference: str | None
    created_at: datetime | None
    declared_clis: tuple[str, ...] = ()
    attested: bool = False
    #: Which attestation text was accepted (`DECLARATION_VERSION` at the time).
    attested_version: int | None = None

    def is_effective(self, *, today: date | None = None) -> bool:
        if not self.recorded or self.state != "notified" or not self.attested:
            return False
        assert self.notified_on is not None  # NOT NULL in the table
        return self.notified_on <= (today or ist_today())


NOT_RECORDED: Final = Declaration(
    recorded=False, state=None, notified_on=None, notice_reference=None, created_at=None
)

# `id` after `created_at` because two rows in one transaction share `now()`; uuid7 is
# time-ordered, so the tiebreak is still chronological.
_LATEST_SQL = text(
    "SELECT state, notified_on, notice_reference, created_at, declared_clis, "
    "attestation_sha256, attestation_version FROM autodialer_notices WHERE tenant_id = :tid "
    "ORDER BY created_at DESC, id DESC LIMIT 1"
)


async def read_declaration(session: AsyncSession, *, tenant_id: UUID) -> Declaration:
    """This tenant's latest declaration, on the caller's RLS-scoped session."""
    row = (await session.execute(_LATEST_SQL, {"tid": tenant_id})).first()
    if row is None:
        return NOT_RECORDED
    return Declaration(
        recorded=True,
        state="withdrawn" if str(row[0]) == "withdrawn" else "notified",
        notified_on=row[1],
        notice_reference=row[2],
        created_at=row[3],
        declared_clis=tuple(row[4] or ()),
        attested=row[5] is not None,
        attested_version=row[6],
    )


async def agent_calling_numbers(session: AsyncSession, *, agent_id: UUID) -> list[str]:
    """Every number this agent's calls can present: each unreleased number bound to it.

    Every direction, not only the outbound-tagged ones `resolve_caller_id` picks from:
    when no number is chosen the voice platform rings from the agent's own line, which may
    be the number it answers on, so the only set that covers whichever one carries the call
    is all of them.
    """
    rows = await session.execute(
        text(
            "SELECT e164 FROM phone_numbers WHERE agent_id = :aid AND released_at IS NULL "
            "ORDER BY created_at, id"
        ),
        {"aid": agent_id},
    )
    return [str(row[0]) for row in rows]


async def tenant_rented_numbers(session: AsyncSession) -> list[str]:
    """Every unreleased number of the session's tenant: what the declaration is prefilled with."""
    rows = await session.execute(
        text("SELECT e164 FROM phone_numbers WHERE released_at IS NULL ORDER BY created_at, id")
    )
    return [str(row[0]) for row in rows]


async def outbound_agent_numbers(session: AsyncSession) -> list[str]:
    """The numbers bound to the tenant's agents that place calls: what readiness asks about.

    An agent that only answers is refused every dial but a test call to the owner, which
    the gate exempts, so its numbers need no declaration.
    """
    rows = await session.execute(
        text(
            "SELECT DISTINCT p.e164, min(p.created_at) FROM phone_numbers p "
            "JOIN agents a ON a.id = p.agent_id "
            "WHERE p.released_at IS NULL AND a.deleted_at IS NULL AND a.direction <> 'inbound' "
            "GROUP BY p.e164 ORDER BY min(p.created_at)"
        )
    )
    return [str(row[0]) for row in rows]


async def outbound_in_use(session: AsyncSession) -> bool:
    """Does the session's tenant have an agent that places calls?"""
    row = await session.execute(
        text("SELECT 1 FROM agents WHERE deleted_at IS NULL AND direction <> 'inbound' LIMIT 1")
    )
    return row.first() is not None


#: How far back `_still_declared` reads. A tenant re-declares a handful of times a year.
_HISTORY_LIMIT: Final = 50


async def _still_declared(
    session: AsyncSession, *, tenant_id: UUID, latest: Declaration, today: date | None
) -> frozenset[str]:
    """The numbers of a future-dated latest declaration that an earlier one already covers.

    A client adding a number it will declare next week records the whole list again with
    next week's date; the numbers it declared last month stay declared meanwhile. Only
    numbers BOTH rows list carry over (the newer list is the client's current statement),
    and nothing carries past a withdrawal.
    """
    rows = await session.execute(
        text(
            "SELECT state, notified_on, declared_clis, attestation_sha256 "
            "FROM autodialer_notices WHERE tenant_id = :tid "
            "ORDER BY created_at DESC, id DESC LIMIT :limit"
        ),
        {"tid": tenant_id, "limit": _HISTORY_LIMIT},
    )
    for state, notified_on, clis, attested in list(rows)[1:]:
        if str(state) == "withdrawn":
            return frozenset()
        if attested is not None and notified_on <= (today or ist_today()):
            return frozenset(clis or ()) & frozenset(latest.declared_clis)
    return frozenset()


async def a2p_declaration_blocker(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    caller_ids: Sequence[str],
    today: date | None = None,
) -> tuple[str, str] | None:
    """`(rule, reason)` if the declaration does not cover `caller_ids`, else None.

    Asks only whether the declaration covers the numbers; whether the rule is in force yet
    is `a2p_dial_blocker`'s question. An empty `caller_ids` with a live declaration is
    refused as undeclared: a call whose number we cannot name is not one we can show was
    declared.
    """
    declaration = await read_declaration(session, tenant_id=tenant_id)
    if not declaration.recorded or declaration.state != "notified" or not declaration.attested:
        return (A2P_DECLARATION_MISSING_RULE, A2P_DECLARATION_MISSING_REASON)
    if not declaration.is_effective(today=today):
        assert declaration.notified_on is not None
        carried = await _still_declared(
            session, tenant_id=tenant_id, latest=declaration, today=today
        )
        if caller_ids and all(cli in carried for cli in caller_ids):
            return None
        return (
            A2P_DECLARATION_NOT_YET_EFFECTIVE_RULE,
            a2p_declaration_not_yet_effective_reason(declaration.notified_on),
        )
    if not caller_ids or any(cli not in declaration.declared_clis for cli in caller_ids):
        return (A2P_NUMBER_UNDECLARED_RULE, A2P_NUMBER_UNDECLARED_REASON)
    return None


async def a2p_dial_blocker(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    trial_call: bool,
    own_number_attested: bool,
) -> tuple[str, str] | None:
    """The dial gate's question: may this outbound call ring, under the declaration rule?

    * Before `a2p_declaration_enforced_from` (IST): always None.
    * A test call to a number the owner attested as their own is exempt. It rings the
      business itself at its own request, which is not a commercial communication to a
      subscriber, the same reasoning that lets it ring outside 09:00-21:00
      (`check_dispatch`). It may ring from our shared trial number, which no client can
      declare, so gating it would end test calling for every trial.
    * Any other test call rings someone else, often from that shared number, so it is
      refused rather than checked against the agent's numbers it may not use.
    * Every other call is checked against every number the agent can present.
    """
    if not enforcement_active():
        return None
    if trial_call:
        if own_number_attested:
            return None
        return (A2P_TEST_CALL_OWN_NUMBER_RULE, A2P_TEST_CALL_OWN_NUMBER_REASON)
    return await a2p_declaration_blocker(
        session,
        tenant_id=tenant_id,
        caller_ids=await agent_calling_numbers(session, agent_id=agent_id),
    )


def declared_cli(raw: str) -> str | None:
    """A number a client typed, in the form `phone_numbers.e164` stores it, or None.

    Everything `normalize_phone` accepts, plus a bare ten-digit 140- or 160-series header,
    which `normalize_phone` refuses because it only guesses the country for a mobile.
    """
    # Imported here: both reach modules that import the compliance package.
    from apps.api.agents.models import series_for_e164
    from apps.api.ingest.service import normalize_phone

    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) == 10 and not raw.strip().startswith("+"):
        header = "+91" + digits
        if series_for_e164(header) in {"140", "160"}:
            return header
    return normalize_phone(raw)


def _declared_clis(raw: Sequence[str], *, required: bool) -> list[str]:
    """Normalised, de-duplicated in the order given, and refused whole on any bad entry."""
    numbers: list[str] = []
    for entry in raw:
        if not entry.strip():
            continue
        number = declared_cli(entry)
        if number is None:
            raise ProblemError.business_rule(
                "a2p_declaration_number_invalid",
                f"'{entry.strip()[:32]}' is not a number your calls can come from.",
                remediation="Enter each number with its country code, like +91 98480 22338.",
            )
        if number not in numbers:
            numbers.append(number)
    if required and not numbers:
        raise ProblemError.business_rule(
            "a2p_declaration_numbers_missing",
            "Pick at least one calling number.",
            remediation="Tick the numbers your calls come from.",
        )
    if len(numbers) > MAX_DECLARED_CLIS:
        raise ProblemError.business_rule(
            "a2p_declaration_numbers_too_many",
            "That is more numbers than one declaration can hold.",
            remediation=f"Declare at most {MAX_DECLARED_CLIS} numbers.",
        )
    return numbers


async def record_declaration(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    notified_on: date,
    recorded_by: UUID,
    attestation_version: int,
    attestation_sha256: str,
    notice_reference: str | None = None,
    declared_clis: Sequence[str] = (),
    withdraw: bool = False,
) -> UUID:
    """Append one declaration or withdrawal. INSERT-only (hard rule 4).

    A future `notified_on` is accepted and the gate holds the calls until it arrives:
    refusing the write would push the client to record a date they did not write.
    A withdrawal need not list numbers, since it retracts the declaration whole.
    """
    if attestation_version != DECLARATION_VERSION or attestation_sha256 != DECLARATION_TEXT_SHA256:
        raise ProblemError.business_rule(
            "a2p_declaration_version_stale",
            "The confirmation on your screen has changed.",
            remediation="Reload the page, read the confirmation again and declare.",
        )
    reference = (notice_reference or "").strip() or None
    if reference is not None and len(reference) > MAX_NOTICE_REFERENCE_CHARS:
        raise ProblemError.business_rule(
            "a2p_declaration_reference_invalid",
            "That reference is too long.",
            remediation=f"Use at most {MAX_NOTICE_REFERENCE_CHARS} characters.",
        )
    numbers = _declared_clis(declared_clis, required=not withdraw)
    row_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO autodialer_notices "
            "(id, tenant_id, state, notified_on, notice_reference, declared_clis, "
            "recorded_by, attestation_version, attestation_sha256) "
            "VALUES (:id, :tid, :state, :on, :ref, :clis, :by, :version, :sha)"
        ),
        {
            "id": row_id,
            "tid": tenant_id,
            "state": "withdrawn" if withdraw else "notified",
            "on": notified_on,
            "ref": reference,
            "clis": numbers,
            "by": recorded_by,
            "version": attestation_version,
            "sha": attestation_sha256,
        },
    )
    return row_id


__all__ = [
    "A2P_DECLARATION_MISSING_REASON",
    "A2P_DECLARATION_MISSING_RULE",
    "A2P_DECLARATION_NOT_YET_EFFECTIVE_RULE",
    "A2P_NUMBER_UNDECLARED_REASON",
    "A2P_NUMBER_UNDECLARED_RULE",
    "A2P_TEST_CALL_OWN_NUMBER_REASON",
    "A2P_TEST_CALL_OWN_NUMBER_RULE",
    "DECLARATION_TEXT",
    "DECLARATION_TEXT_SHA256",
    "DECLARATION_VERSION",
    "MAX_DECLARED_CLIS",
    "MAX_NOTICE_REFERENCE_CHARS",
    "NOT_RECORDED",
    "Declaration",
    "DeclarationState",
    "a2p_declaration_blocker",
    "a2p_declaration_not_yet_effective_reason",
    "a2p_dial_blocker",
    "agent_calling_numbers",
    "declared_cli",
    "enforced_from",
    "enforcement_active",
    "ist_today",
    "outbound_agent_numbers",
    "outbound_in_use",
    "read_declaration",
    "record_declaration",
    "tenant_rented_numbers",
]
