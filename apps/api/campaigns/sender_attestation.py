"""The client's recorded exception to the ordinary-DID refusal, and the gate that reads it.

TRAI direction RG-25/(18)/2023-QoS (E-10291), 18 Jun 2024: *"Senders shall not use any
other 10-digit fixed line/ mobile number for making Promotional/ Service/ Transactional
voice calls to their customers, either directly or through their employees or channel
partners, DSAs, BPO partner, in-house or outsourced Call Centre, etc."*

The direction binds the SENDER and names the delegation chain — employees, channel
partners, DSAs, BPO partner, outsourced call centre — so the obligation cannot be handed to
a vendor. Under Model B (D-474) the client holds the carrier account and is that sender.

**SO THE REFUSAL IS THE DEFAULT AND THIS IS THE CLIENT'S OWN EXCEPTION TO IT, NOT OURS.**
`SERIES_FOR_CLASSIFICATION` allows only 140 and 160. A `standard` number reaches the dial
path only where a named person at the client has been shown the obligation and accepted it,
and that acceptance is a row with their id and the wording they saw. The alternative
considered and rejected was simply restoring `standard` to the allowed list: that makes the
decision OURS, undocumented, on a surface where the penalty lands on a client who never saw
the rule.

**PROMOTIONAL IS NOT REACHABLE THROUGH THIS AND MUST NOT BECOME SO.** 140 is the only series
that may carry a promotional call. No client declaration makes a promotional call from an
ordinary number lawful, and `attested_series_for` refuses to widen that classification even
when an attestation exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7

#: The wording a client accepts, versioned. What the person agreed to is the sentence they
#: were shown, so the row records which one — and changing this string asks every client
#: again rather than letting an old click stand for new words. Same rule
#: `legal.service.record_acceptance` applies to a document version.
SENDER_STATEMENT_VERSION: Final[str] = "2026-09-20"

SENDER_STATEMENT: Final[str] = (
    "I confirm that my business is the sender of these calls, that I have been told TRAI "
    "requires promotional, service and transactional voice calls to be made only from a "
    "registered 140 or 160 series voice header, that this number is not one, and that my "
    "business accepts responsibility for calls made from it."
)

#: The classifications an attestation can open. Promotional is absent deliberately — see
#: this module's docstring.
ATTESTABLE_CLASSIFICATIONS: Final[frozenset[str]] = frozenset({"service", "transactional"})

ATTESTATION_RULE: Final[str] = "outbound_sender_not_attested"


def attestation_reason(series: str, classification: str) -> str:
    """The client-facing refusal. Says what to do, in both of the two ways out."""
    return (
        f"This campaign dials from a {series} number, and TRAI requires {classification} "
        "voice calls to come from a registered 140 or 160 series header. Either attach a "
        "140 or 160 number, or confirm on the number's settings page that your business is "
        "the sender and accepts responsibility for calls from this one."
    )


@dataclass(frozen=True, slots=True)
class AttestationState:
    """The latest row for one number, read as an answer rather than a history."""

    attested: bool
    statement_version: str | None

    @property
    def current(self) -> bool:
        """Attested AND against the wording we show today.

        A stale version is NOT attested for the gate's purposes: the client agreed to
        different words, and treating that as agreement to these would make the row
        evidence of something that did not happen.
        """
        return self.attested and self.statement_version == SENDER_STATEMENT_VERSION


_LATEST_SQL = text(
    "SELECT state, statement_version FROM outbound_sender_attestations "
    "WHERE phone_number_id = :number_id ORDER BY created_at DESC, id DESC LIMIT 1"
)


async def latest_attestation(session: AsyncSession, *, phone_number_id: UUID) -> AttestationState:
    """The current state of one number. Under RLS, so the tenant is implied.

    Ordered by `id` after `created_at` because two rows written inside one transaction share
    `now()`, and a withdrawal that sorted before the attestation it revokes would report the
    opposite of the truth. uuid7 is time-ordered, so the tiebreak is still chronological.
    """
    row = (await session.execute(_LATEST_SQL, {"number_id": phone_number_id})).first()
    if row is None:
        return AttestationState(attested=False, statement_version=None)
    return AttestationState(attested=row[0] == "attested", statement_version=row[1])


async def record_attestation(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    phone_number_id: UUID,
    user_id: UUID,
    statement_version: str,
    withdraw: bool = False,
) -> UUID:
    """Append one attestation or withdrawal. INSERT-only (hard rule 4).

    Refuses a stale statement version before the write, for `record_acceptance`'s reason:
    the wording the person ticked is half the evidence, so a console left open across a
    change must reload rather than have today's version recorded against yesterday's click.
    A WITHDRAWAL is exempt — refusing to let someone retract because their page is old would
    hold them to an obligation they are trying to step out of.
    """
    if not withdraw and statement_version != SENDER_STATEMENT_VERSION:
        raise ProblemError.business_rule(
            "sender_statement_not_current",
            "The confirmation on your screen is out of date.",
            remediation="Reload the page and read the confirmation again before accepting.",
        )
    row_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO outbound_sender_attestations "
            "(id, tenant_id, phone_number_id, state, statement_version, attested_by) "
            "VALUES (:id, :tid, :nid, :state, :sv, :uid)"
        ),
        {
            "id": row_id,
            "tid": tenant_id,
            "nid": phone_number_id,
            "state": "withdrawn" if withdraw else "attested",
            "sv": SENDER_STATEMENT_VERSION,
            "uid": user_id,
        },
    )
    return row_id


__all__ = [
    "ATTESTABLE_CLASSIFICATIONS",
    "ATTESTATION_RULE",
    "SENDER_STATEMENT",
    "SENDER_STATEMENT_VERSION",
    "AttestationState",
    "attestation_reason",
    "latest_attestation",
    "record_attestation",
]
