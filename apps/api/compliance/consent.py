"""Messaging consent — may we send this person a business-initiated message?

The gap this closes: `workers/whatsapp.escalate_campaign_contact` has refused every
campaign follow-up since it shipped, because it asks `consent_ledger` for a `messaging`
purpose the CHECK constraint did not permit. Migration `c2f7a91b4e63` makes the purpose
exist; this module is how a row gets into it, and the single place that reads one back.

It lives in `compliance/` rather than in the worker for the reason every other rule
does: `check_dispatch` is the one gate every dial passes, and a second consent read
growing its own semantics inside a worker is how two answers to one question appear.

--------------------------------------------------------------------------------
WHAT THE LAW AND THE PLATFORM ACTUALLY REQUIRE (researched 2026-08-12)
--------------------------------------------------------------------------------

* **Meta / WhatsApp Business Messaging Policy.** A business must obtain opt-in before
  sending business-initiated messages. The opt-in may be collected on any channel and
  need not be WhatsApp-specific, but it must (a) state that the person is opting in to
  receive messages and (b) name the business they will come from, and it must be an
  affirmative act — a pre-ticked box does not qualify. Meta expects the business to be
  able to produce, per contact, the TIMESTAMP of the opt-in and the SOURCE/channel it
  came from; "we cannot show the opt-in" is no defence when a number is challenged.
  (developers.facebook.com "Get opt-in for WhatsApp"; Meta's Nov-2024 policy update, as
  summarised by infobip.com/docs/whatsapp/compliance/user-opt-ins and
  blueticks.co/blog/whatsapp-opt-in-compliance-requirements.)
* **TRAI TCCCPR 2018 as amended (Second Amendment, 12 Feb 2025).** Explicit consent
  under Reg. 2(y) is consent "verified directly from the Recipient in a robust and
  verifiable manner and recorded by Consent Registrar" — i.e. on the DLT platform via
  Digital Consent Acquisition, which is a registrar function we cannot perform. The
  2025 amendment tightened validity in both directions that matter to us: consent tied
  to an ongoing transaction is limited to seven days, and INFERRED consent lasts only
  as long as the contractual relationship it was inferred from. Revocation ("STOP")
  propagates through the DLT ledger in real time and is universally honoured.
* **DPDP Act 2023 §6.** Consent must be free, specific, informed, unconditional and
  unambiguous, by clear affirmative action, limited to the stated purpose, and
  withdrawable as easily as it was given.

Two conclusions the code below is built on:

1. **What we store is OUR evidence, not registrar-grade explicit consent.** We are not
   a Consent Registrar and cannot write to DLT. So this ledger is what we can show —
   which is why every row must carry a source and a grant must carry evidence. It does
   not substitute for DNC scrubbing, and it is not consulted INSTEAD of the dispatch
   gate: `_send_escalation` calls `check_dispatch` first and this second.
2. **Consent goes stale.** Meta publishes no expiry, but TRAI's amendment set the
   direction of travel (nothing indefinite; inferred consent dies with the relationship)
   and DPDP's purpose limitation points the same way; the widely-given practical
   guidance is to re-confirm contacts dormant for 6-12 months. So the read applies
   `MESSAGING_CONSENT_VALIDITY_DAYS` and a five-year-old opt-in is not current.

--------------------------------------------------------------------------------
DECISIONS
--------------------------------------------------------------------------------

**Does an inbound caller who asks for a callback thereby opt in to messaging? NO.**
It is worth arguing, because the case for yes is not silly: the person initiated
contact, handed over their number for the express purpose of being contacted back, and
under TCCCPR that relationship is the classic basis for INFERRED consent — the same
reasoning D-38 uses to call inbound "consent-clean". And `consent_ledger` already has a
`callback` purpose, so the row often exists.

It still fails, on the channel and on the regime that binds hardest:

  * Meta's requirement is an opt-in that names the business AND states the person is
    opting in to receive MESSAGES. "Call me back tomorrow" states neither. Our WABA is
    not a party the caller has heard of, and the escalation is sent from it.
  * TCCCPR's inferred consent is exactly what the 2025 amendment time-boxed, and it is
    inferred by the ACCESS PROVIDER against a contractual relationship — not something
    a telemarketer's own database may assert about a stranger's enquiry.
  * DPDP §6's purpose limitation forbids reusing consent given for one purpose for
    another. Callback and messaging are two purposes; that is the entire reason
    `purpose` is a column.

So `callback` never satisfies `read_messaging_consent`, and there is no code path that
converts one into the other. What DOES work is the honest version of the same moment:
the agent asks "shall I WhatsApp you the details?", the caller says yes, and that lands
as `inbound_call_verbal` with the call id and the transcript span — a separate,
affirmative, evidenced statement about a named channel.

**Withdrawal is a new row.** Hard rule 4, and also DPDP §6(6): withdrawal must be as
easy as consent. `record_messaging_consent` never updates; the read takes the latest
row per (tenant, phone, purpose), so a withdrawal supersedes the grant before it and a
later re-grant supersedes the withdrawal. Recording a withdrawal has no evidence
requirement at all — consent must be evidenced, a refusal must never be obstructed.

**Hard rule 6.** Nothing here logs a number. Refusals log the tenant, the source and
the rule.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.models import (
    CONSENT_SOURCES,
    MESSAGING_PURPOSE,
    WITHDRAWAL_ONLY_CONSENT_SOURCES,
)
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.ownership import assert_visible
from apps.api.ingest.service import normalize_phone

log = get_logger(__name__)

# How long a messaging opt-in stays current. See the research note above: Meta sets no
# expiry, TRAI's 2025 amendment refuses indefinite consent, DPDP §6 binds consent to a
# stated purpose, and the practical guidance is to re-confirm dormant contacts within
# 6-12 months. A year is the outer edge of that range rather than the middle, because
# the alternative to messaging is not messaging a lead the client paid for — but it is
# an edge, not an absence: a 2021 opt-in does not authorise a 2026 message.
MESSAGING_CONSENT_VALIDITY_DAYS = 365

# The statuses this surface may record. `declined` is the live "no thanks" of a caller
# who was asked during a call and said no; `withdrawn` is a later retraction of a yes.
# They are kept apart because they answer different questions in an audit ("did anyone
# ever ask?" vs "did they change their mind?"), and both read as not-messageable.
RECORDABLE_STATUSES = ("granted", "declined", "withdrawn")

# Sources that can only ever carry a NO. Mirrors the CHECK; the constraint is the
# backstop, this is the actionable refusal.
GRANT_CAPABLE_SOURCES = tuple(
    source for source in CONSENT_SOURCES if source not in WITHDRAWAL_ONLY_CONSENT_SOURCES
)


@dataclass(frozen=True, slots=True)
class MessagingConsent:
    """The current state of one (tenant, phone) for the `messaging` purpose.

    `status = "none"` is the default of the world — nobody has ever asked this person.
    It is a state, not an error: the campaign escalation records `recipient_not_opted_in`
    and moves on, which is why it is not paged (see `whatsapp._is_operational`).
    """

    status: str
    source: str | None = None
    captured_at: datetime | None = None
    expires_at: datetime | None = None

    @property
    def messageable(self) -> bool:
        """Granted, and not stale. Both halves, always — a `granted` row on its own is
        the thing a five-year-old opt-in would also produce."""
        if self.status != "granted" or self.expires_at is None:
            return False
        return self.expires_at > datetime.now(UTC)


NO_CONSENT = MessagingConsent(status="none")


async def read_messaging_consent(
    session: AsyncSession, *, tenant_id: UUID, phone_e164: str
) -> MessagingConsent:
    """Latest row wins, so a withdrawal supersedes the grant before it.

    Ordered by `(captured_at DESC, created_at DESC)` and served by the partial index
    `ix_consent_ledger_messaging_lookup`, which carries all four columns: `captured_at`
    is when the person SPOKE and `created_at` is when we wrote it down, and they differ
    whenever a form submission is imported later. Two rows captured in the same instant
    (a bulk import declaring one per row) are broken by insertion order, so the answer
    is deterministic rather than whichever the planner happened to return.
    """
    row = (
        await session.execute(
            text(
                "SELECT status, consent_source, captured_at FROM consent_ledger "
                "WHERE tenant_id = :tid AND phone_e164 = :phone AND purpose = :purpose "
                "ORDER BY captured_at DESC, created_at DESC LIMIT 1"
            ),
            {"tid": tenant_id, "phone": phone_e164, "purpose": MESSAGING_PURPOSE},
        )
    ).first()
    if row is None:
        return NO_CONSENT
    captured_at: datetime = row[2]
    return MessagingConsent(
        status=str(row[0]),
        source=str(row[1]) if row[1] is not None else None,
        captured_at=captured_at,
        expires_at=captured_at + timedelta(days=MESSAGING_CONSENT_VALIDITY_DAYS),
    )


async def record_messaging_consent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    raw_phone: str,
    status: str,
    source: str,
    call_id: UUID | None = None,
    evidence: dict[str, str] | None = None,
) -> MessagingConsent:
    """Append one row. Never updates, never deletes (hard rule 4).

    The number is normalised with `ingest.normalize_phone` — the same function the lead
    path, the DNC list and the campaign contact list use — so an opt-in typed as
    `98765 43210` and a campaign contact loaded as `+919876543210` are the same person
    to the read above. A consent record whose key does not match the dispatch key is
    worse than no record: it looks like protection and grants nothing.

    Validation happens here AND in the database. The CHECKs are the guarantee; these
    raises are the interface — a 422 that says which piece of evidence is missing is
    something a client can act on, where an IntegrityError is a 500 nobody can.
    """
    phone_e164 = normalize_phone(raw_phone)
    if phone_e164 is None:
        raise ProblemError.business_rule(
            "consent_phone_invalid",
            "That does not look like a valid Indian phone number.",
            remediation="Use a 10-digit mobile number or its +91 form.",
        )
    if status not in RECORDABLE_STATUSES:
        raise ProblemError.business_rule(
            "consent_unknown_status",
            "That is not something a person can say about being messaged.",
            remediation=f"Use one of: {', '.join(RECORDABLE_STATUSES)}.",
        )
    if source not in CONSENT_SOURCES:
        raise ProblemError.business_rule(
            "consent_unknown_source",
            "That is not a recognised way of capturing consent.",
            remediation=f"Use one of: {', '.join(CONSENT_SOURCES)}.",
        )
    if status == "granted":
        _assert_grant_is_evidenced(source=source, call_id=call_id, evidence=evidence)

    # The cited conversation must be one THIS tenant had. `consent_ledger.call_id` is a
    # foreign key and PostgreSQL checks those with row security bypassed, so without this
    # a client can file an opt-in evidenced by a call they were never party to — and
    # `consent_ledger` is in `APPEND_ONLY_TABLES` (hard rule 4), so that row is a legal
    # record under DPDP that can never be corrected, only compensated. Checked after the
    # evidence rule so "you did not say what this rests on" still outranks "that is not
    # your call", and before the INSERT so nothing is written either way.
    await assert_visible(session, "call", call_id)

    captured_at = datetime.now(UTC)
    await session.execute(
        text(
            "INSERT INTO consent_ledger (id, tenant_id, call_id, phone_e164, purpose, status, "
            "consent_source, captured_at, evidence, created_at) VALUES (:id, :tid, :call, "
            ":phone, :purpose, :status, :source, :captured, CAST(:evidence AS jsonb), now())"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "call": call_id,
            "phone": phone_e164,
            "purpose": MESSAGING_PURPOSE,
            "status": status,
            "source": source,
            "captured": captured_at,
            "evidence": json.dumps(evidence) if evidence else None,
        },
    )
    # Ids, a status and a source. Never the number (hard rule 6).
    log.info(
        "messaging_consent_recorded",
        extra={"tenant_id": str(tenant_id), "status": status, "source": source},
    )
    return MessagingConsent(
        status=status,
        source=source,
        captured_at=captured_at,
        expires_at=captured_at + timedelta(days=MESSAGING_CONSENT_VALIDITY_DAYS),
    )


def _assert_grant_is_evidenced(
    *, source: str, call_id: UUID | None, evidence: dict[str, str] | None
) -> None:
    """The three rules that make "assumed consent" unrepresentable, as messages a
    client can act on. The CHECK `ck_consent_ledger_granted_consent_carries_evidence`
    says the same thing to anyone who bypasses this function."""
    if source in WITHDRAWAL_ONLY_CONSENT_SOURCES:
        raise ProblemError.business_rule(
            "consent_source_cannot_grant",
            "Your team cannot record an opt-in on a customer's behalf — only an opt-out.",
            remediation=(
                "Capture the opt-in where the customer gave it: on a call, on your "
                f"form, or in WhatsApp itself ({', '.join(GRANT_CAPABLE_SOURCES)})."
            ),
        )
    if not evidence:
        raise ProblemError.business_rule(
            "consent_grant_needs_evidence",
            "An opt-in has to record what it rests on.",
            remediation=(
                "Include the form and notice version, the document reference, or the "
                "message id the customer's agreement came from."
            ),
        )
    if source == "inbound_call_verbal" and call_id is None:
        raise ProblemError.business_rule(
            "consent_verbal_grant_needs_call",
            "A spoken opt-in has to name the call it was spoken on.",
            remediation="Send the call_id of the conversation the customer agreed in.",
        )


__all__ = [
    "GRANT_CAPABLE_SOURCES",
    "MESSAGING_CONSENT_VALIDITY_DAYS",
    "NO_CONSENT",
    "RECORDABLE_STATUSES",
    "MessagingConsent",
    "read_messaging_consent",
    "record_messaging_consent",
]
