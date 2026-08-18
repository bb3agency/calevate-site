"""The CLIENT's WhatsApp opt-in — may WE alert this person from the Calevate WABA?

The gap this closes: `workers/whatsapp.notify_hot_lead_whatsapp` has refused every
hot-lead alert since it shipped, because `resolve_destination` had nowhere to read an
opt-in from and returned `opt_in_at=None` unconditionally. FLOWS §6 promises the client
owner a WhatsApp+email alert within two minutes of a hot lead; only the email half has
ever been deliverable. Migration `e6b2d94f31a7` makes the record exist; this module is
the one place a row gets into it or comes back out.

It lives in `compliance/` next to `consent.py` for the reason every other rule does: one
implementation of "may we message this person", so the worker and the console can never
disagree about the answer on the day it matters.

--------------------------------------------------------------------------------
WHICH REGIME BITES, AND WHICH DOES NOT
--------------------------------------------------------------------------------

This message goes to OUR CLIENT about their own lead — not to a consumer. That single
fact decides everything about the shape below, and it is worth stating because the
neighbouring module answers the same-sounding question completely differently:

* **NOT TRAI/DLT.** TCCCPR governs commercial telecom traffic to a subscriber. A service
  notification to a paying customer about activity on their own account is not that, so
  there is no DLT header, no content template, no Consent Registrar and no 140/160-series
  question here. `check_dispatch` is deliberately NOT called on this path (it IS called
  on the campaign escalation, which is the opposite case).
* **NOT `consent_ledger`.** Every row in that ledger is a CONSUMER's statement, and its
  `messaging` purpose is keyed to (tenant, phone) meaning "this client may message this
  stranger". Overloading it would make one client's WABA relationship with US
  indistinguishable from their permission to message a customer.
* **Meta's opt-in policy DOES bite**, because the message is business-initiated from our
  WABA and the recipient is a person. So does **DPDP**: the owner's phone number is
  personal data we process for a stated purpose.

--------------------------------------------------------------------------------
WHAT MAKES A ROW EVIDENCE (researched 2026-08-14 — SECONDARY SOURCES, marked)
--------------------------------------------------------------------------------

`developers.facebook.com` and `graph.facebook.com` are both blocked by this build
environment's egress proxy (403 at the gateway on every attempt), so Meta's own pages
could not be read directly. Everything below is sourced from secondary summaries of them
and is marked the way `apps/api/ingest/meta.py` marks its Meta sources — consistent
across every source read, and consistent with the Nov-2024 policy update
`compliance/consent.py` already cites.

* Opt-in must precede any business-initiated message. Since the November 2024 Business
  Messaging Policy update it may be collected on any channel and need not name WhatsApp,
  but it must be an AFFIRMATIVE act — a pre-ticked box does not qualify — and it must
  state that the person will receive messages, and from whom.
* Per contact, a business is expected to be able to produce THREE things when a number is
  challenged: the **timestamp**, the **source/channel**, and the **consent text shown**.
  "An opt-in you can't evidence is an opt-in you don't have."
  — blueticks.co/blog/whatsapp-opt-in-compliance-requirements (SECONDARY)
  — wetarseel.ai/whatsapp-business-api-opt-in-rules/ (SECONDARY)
  — cm.com/blog/whatsapp-opt-in/ (SECONDARY)
  all summarising developers.facebook.com "Get opt-in for WhatsApp" + the Nov-2024
  policy update, which are EGRESS-BLOCKED here and still owed a first-party read.
* DPDP §6: consent must be free, specific, informed, unconditional and unambiguous, by
  clear affirmative action, limited to the stated purpose, and withdrawable as easily as
  given.

`ALERT_NOTICE_VERSION` below is the "informed" half made checkable, and the reason the
notice text lives in THIS file rather than in the screen that renders it: a version
string in a database row is only evidence if the wording it names can still be produced.

--------------------------------------------------------------------------------
DECISIONS
--------------------------------------------------------------------------------

**No expiry window, deliberately — see the migration for the full argument.** The
consumer ledger next door time-boxes an opt-in at 365 days because TRAI refuses
indefinite consent and the relationship behind it is unobservable. Neither premise holds
here, and the expiry is structural instead: the row names the `user_id` and the
`phone_e164` it was given for, and `read_alert_optin` is asked about a specific pair, so
an owner handover or a changed number produces "no opt-in" with no clock involved. A
timer would silently switch a client's hot-lead alerts off on a day nobody is watching.

**Withdrawal is a new row** (hard rule 4, DPDP §6(6)). `record_alert_optin` never
updates; the read takes the latest row, so a withdrawal supersedes the grant before it
and a later re-grant supersedes the withdrawal.

**Hard rule 6.** Nothing here logs a number. Refusals log the tenant, the channel and the
rule.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.models import (
    ALERT_OPTIN_CHANNELS,
    ALERT_OPTIN_OPERATOR,
    ALERT_OPTIN_SELF_SERVE,
    ALERT_OPTIN_STATUSES,
)
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7

log = get_logger(__name__)

# The exact wording a client sees beside the unticked box, and the version a granted row
# records. It lives HERE rather than in the screen because a `notice_version` in a
# database row is only evidence if the wording it names can be reproduced years later,
# and a string that lives only in a React component cannot be.
#
# Bump the version WITH the text, never separately: two deployments whose
# `whatsapp-alerts-v1` says different things is the one failure this column exists to
# prevent. Rows recorded under an old version keep naming it, which is the point — they
# evidence what that person actually saw.
ALERT_NOTICE_VERSION = "whatsapp-alerts-v1"
ALERT_NOTICE_TEXT = (
    "I agree that Calevate may send WhatsApp messages to this number to alert me about "
    "activity in my own account, such as a hot lead. I can withdraw this at any time "
    "from this screen."
)

# What a caller may record. There is no `declined` member: nobody asks a client on our
# behalf and writes down the no — an owner who has not opted in simply has no row, and
# absence is the default of the world. (`consent_ledger` needs `declined` because there
# a HUMAN did the asking and "was anyone ever asked?" is an audit question.)
RECORDABLE_STATUSES = ALERT_OPTIN_STATUSES


@dataclass(frozen=True, slots=True)
class AlertOptIn:
    """The current state of one (tenant, user, phone) for WhatsApp alerts.

    `status = "none"` is the default of the world — this person has never been asked.
    It is a state, not an error: the hot-lead job records `recipient_not_opted_in` and
    moves on.
    """

    status: str
    channel: str | None = None
    captured_at: datetime | None = None
    notice_version: str | None = None

    @property
    def messageable(self) -> bool:
        """Granted, full stop.

        Deliberately NOT `granted AND not stale`, which is what the consumer twin
        computes. There is no staleness leg here because there is no expiry column, and
        the reason is argued in the module docstring and the migration: the freshness
        this would be standing in for is checked structurally by the CALLER, which asks
        about a specific live (user, phone) pair.
        """
        return self.status == "granted"


NO_OPT_IN = AlertOptIn(status="none")


async def read_alert_optin(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID, phone_e164: str
) -> AlertOptIn:
    """Latest row wins, so a withdrawal supersedes the grant before it.

    Asked about a SPECIFIC (user, phone) pair rather than about a tenant, and that is the
    load-bearing part: an opt-in belongs to the person who gave it, for the number they
    gave it on. An owner handover finds no row for the new person, and a changed number
    finds no row for the new number — both fail closed with no clock involved, which is
    what lets this ledger carry no expiry column at all.

    Ordered by `(captured_at DESC, created_at DESC)` and served by
    `ix_whatsapp_alert_optin_current`, which carries `status` as an INCLUDE column so the
    read is index-only: this runs on the hot-lead path, which is racing a two-minute SLO.
    `captured_at` is when the person AGREED and `created_at` is when we wrote it down;
    they differ whenever an operator records an onboarding form later, and two rows
    captured in the same instant are broken by insertion order so the answer is
    deterministic rather than whichever the planner happened to return.
    """
    row = (
        await session.execute(
            text(
                "SELECT status, channel, captured_at, notice_version "
                "FROM whatsapp_alert_optin_ledger "
                "WHERE tenant_id = :tid AND user_id = :uid AND phone_e164 = :phone "
                "ORDER BY captured_at DESC, created_at DESC LIMIT 1"
            ),
            {"tid": tenant_id, "uid": user_id, "phone": phone_e164},
        )
    ).first()
    if row is None:
        return NO_OPT_IN
    return AlertOptIn(
        status=str(row[0]),
        channel=str(row[1]),
        captured_at=row[2],
        notice_version=str(row[3]) if row[3] is not None else None,
    )


async def record_alert_optin(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    phone_e164: str,
    status: str,
    channel: str,
    recorded_by_user_id: UUID | None = None,
    recorded_by_admin_id: UUID | None = None,
    evidence: dict[str, str] | None = None,
) -> AlertOptIn:
    """Append one row. Never updates, never deletes (hard rule 4).

    The number is taken as already-normalised E.164 — it comes from `users.phone`, which
    the invitation flow writes, not from a form field. That is deliberate and it is the
    other half of why this ledger needs no separate `notify_whatsapp_e164`: the opt-in is
    recorded against the number the alert would actually be sent to, read from the same
    row `resolve_destination` reads, so the consent key and the delivery key cannot
    drift. A consent record whose key does not match the delivery key is worse than no
    record: it looks like protection and grants nothing.

    Validation happens here AND in the database. The CHECKs are the guarantee; these
    raises are the interface — a 422 naming the missing piece is something a client or an
    operator can act on, where an IntegrityError is a 500 nobody can.
    """
    if status not in RECORDABLE_STATUSES:
        raise ProblemError.business_rule(
            "alert_optin_unknown_status",
            "That is not something a person can say about being alerted.",
            remediation=f"Use one of: {', '.join(RECORDABLE_STATUSES)}.",
        )
    if channel not in ALERT_OPTIN_CHANNELS:
        raise ProblemError.business_rule(
            "alert_optin_unknown_channel",
            "That is not a recognised way of capturing an opt-in.",
            remediation=f"Use one of: {', '.join(ALERT_OPTIN_CHANNELS)}.",
        )
    if not phone_e164:
        # Reachable when an owner has no number on their profile. A refusal a person can
        # act on, rather than a NOT NULL violation nobody can read.
        raise ProblemError.business_rule(
            "alert_optin_needs_a_number",
            "There is no mobile number on this account to send alerts to.",
            remediation="Add a mobile number to the profile first, then opt in.",
        )
    notice_version = ALERT_NOTICE_VERSION if status == "granted" else None
    if status == "granted":
        _assert_grant_is_evidenced(
            channel=channel,
            user_id=user_id,
            recorded_by_user_id=recorded_by_user_id,
            recorded_by_admin_id=recorded_by_admin_id,
            evidence=evidence,
        )
    if (recorded_by_user_id is None) == (recorded_by_admin_id is None):
        # Mirrors `ck_..._names_one_recorder`. Reachable only from a caller that names
        # neither or both, which is a programming error rather than a user one — but a
        # 422 that says so beats an IntegrityError that does not.
        raise ProblemError.business_rule(
            "alert_optin_needs_one_recorder",
            "An opt-in record has to say who recorded it.",
            remediation="Record it as the account owner, or as an operator — not both.",
        )

    captured_at = datetime.now(tz=UTC)
    await session.execute(
        text(
            "INSERT INTO whatsapp_alert_optin_ledger (id, tenant_id, user_id, phone_e164, "
            "status, channel, notice_version, captured_at, recorded_by_user_id, "
            "recorded_by_admin_id, evidence, created_at) VALUES (:id, :tid, :uid, :phone, "
            ":status, :channel, :notice, :captured, :by_user, :by_admin, "
            "CAST(:evidence AS jsonb), now())"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "uid": user_id,
            "phone": phone_e164,
            "status": status,
            "channel": channel,
            "notice": notice_version,
            "captured": captured_at,
            "by_user": recorded_by_user_id,
            "by_admin": recorded_by_admin_id,
            "evidence": json.dumps(evidence) if evidence else None,
        },
    )
    # Ids, a status and a channel. Never the number (hard rule 6).
    log.info(
        "whatsapp_alert_optin_recorded",
        extra={"tenant_id": str(tenant_id), "status": status, "channel": channel},
    )
    return AlertOptIn(
        status=status,
        channel=channel,
        captured_at=captured_at,
        notice_version=notice_version,
    )


def _assert_grant_is_evidenced(
    *,
    channel: str,
    user_id: UUID,
    recorded_by_user_id: UUID | None,
    recorded_by_admin_id: UUID | None,
    evidence: dict[str, str] | None,
) -> None:
    """The rules that make "assumed opt-in" unrepresentable, as messages a caller can act
    on. `ck_whatsapp_alert_optin_ledger_granted_optin_is_evidenced` says the same thing
    to anyone who bypasses this function.

    The split is by CHANNEL because the two channels evidence themselves differently: a
    self-serve grant IS its own evidence (the subject authenticated and clicked), so it
    needs no document but must have been recorded by that same subject; an operator's
    grant is a claim about somebody else, so it needs a document reference and a named
    operator.
    """
    if channel == ALERT_OPTIN_SELF_SERVE and recorded_by_user_id != user_id:
        raise ProblemError.business_rule(
            "alert_optin_self_serve_is_first_person",
            "An opt-in recorded on the settings screen has to be the account holder's own.",
            remediation=(
                "Ask the account holder to opt in from their own login, or record it as "
                "an operator with the document they agreed on."
            ),
        )
    if channel == ALERT_OPTIN_OPERATOR:
        if recorded_by_admin_id is None:
            raise ProblemError.business_rule(
                "alert_optin_operator_grant_needs_operator",
                "An opt-in recorded on a client's behalf has to name the operator.",
                remediation="Record it from the admin console, signed in as yourself.",
            )
        if not evidence:
            raise ProblemError.business_rule(
                "alert_optin_operator_grant_needs_evidence",
                "An opt-in recorded on a client's behalf has to record what it rests on.",
                remediation=(
                    "Include the onboarding document reference or the ticket where the "
                    "client agreed."
                ),
            )


__all__ = [
    "ALERT_NOTICE_TEXT",
    "ALERT_NOTICE_VERSION",
    "NO_OPT_IN",
    "RECORDABLE_STATUSES",
    "AlertOptIn",
    "read_alert_optin",
    "record_alert_optin",
]
