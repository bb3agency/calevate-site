"""The first-campaign hold — R-11's last mitigation, and the only one with no code.

BRD §245 lists the controls the self-serve motion ships WITH, and ends the list with
"manual review of the first campaign for any self-serve account". FLOWS §2 says the same
("the **first campaign of every self-serve account is held for manual review**") and
D-34 makes the whole list non-negotiable. Five of the six held in code — platform-fixed
calling hours, DNC on every dispatch path, the NOT NULL disclosure line, the consent
ledger, the spend caps — and this one was prose in `tenancy/signup.py`. An account could
sign up, verify, top up and dial a list of strangers with no human ever having looked.

WHAT "FIRST" MEANS
------------------
**Not the first `campaigns` row.** A flag on that row is defeated two ways in a minute,
and neither is exotic:

* *launch a second campaign* — the flag is on #1, #2 dials, and the account's first calls
  were reviewed by nobody;
* *delete the flagged campaign* — the flag goes with the row, and whether the next one is
  "first" is then decided by a DELETE.

**First is the state of an account no human has cleared yet.** One decision per tenant,
in `first_campaign_reviews`, and the gate asks a question about the ACCOUNT rather than
about the campaign in front of it. Two consequences, both intended:

* while an account is held, *every* campaign is refused, not only its first. There is no
  ordering to game;
* once released, *no* campaign is refused on this rule again — which is the mitigation as
  written. It is a review of the first campaign, not a signature on every campaign
  forever, and the ordinary gates (template, header, PE registration, provenance, DNC,
  hours, wallet) carry the rest.

The campaign an operator actually read is recorded as `reviewed_campaign_id` — evidence,
not mechanism. It is `ON DELETE SET NULL` precisely so that deleting it cannot change
whether the account is cleared.

ABSENCE IS THE HELD STATE
-------------------------
There is no `pending` row and no request path. A tenant with no row has not been
reviewed; that is the state every self-serve account starts in, and `HELD` below is the
value that says so (the same "absence is a VALUE, not an exception" argument
`kyc.NOT_RECORDED` and `registration.NOT_RECORDED` make). Storing "pending" as a row
would add a second representation of one fact, writable on a path that is being refused
anyway, and every gate would still have to treat the two identically.

WHO IT APPLIES TO
-----------------
`compliance.service.SELF_SERVE_TIERS` — self-serve and trial — the same line the wallet
gate and the KYC dial gate draw, named once so three predicates cannot drift into
disagreeing about which motion a tenant is on. R-11's risk is an *anonymous* signup
dialling India's network: a managed client was onboarded by a person, their PE
registration was executed by us, and holding their campaigns would halt existing clients
over a control aimed at strangers.

THE RESIDUAL, STATED RATHER THAN HIDDEN
---------------------------------------
This gate is on the CAMPAIGN paths — `campaigns.service.launch_blockers` (the preview and
the launch refusal) and `campaigns.service.dispatch_blockers` (every dispatch tick, so a
withdrawn release stops a running campaign rather than letting it finish the list). It is
deliberately NOT in `compliance.service.check_dispatch`, which is also reached by the
D-21 "call this lead" button and the instant-callback webhook: those are one call at a
time to a lead who just raised their hand, they are not campaigns, and every document
that asks for this control scopes it to the first *campaign*. So a held self-serve
account can still place single manual calls, under KYC, wallet, hours, DNC and disclosure
— that is the residual, and widening this gate is not how it closes (an abusive account
placing calls one at a time is an AUP-enforcement question, BRD §245's last clause).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.models import FIRST_CAMPAIGN_REVIEW_APPROVED
from apps.api.db.base import uuid7

# The client-facing wording of the hold, defined ONCE and shared by the launch preview,
# the launch refusal, the dispatch tick and the client's own screen — the discipline
# `KYC_MISSING_REASON` and `SPEND_CAP_REASON` follow, so one condition is never explained
# four different ways on four screens.
FIRST_CAMPAIGN_REVIEW_PENDING_REASON = (
    "Your first campaign is held for review by Calevate's compliance team. We check the "
    "contact list, the script and the disclosure line before any new account starts "
    "dialling, and we release the account once. Answering inbound calls is unaffected."
)


def first_campaign_rejected_reason(note: str) -> str:
    """Names what the reviewer actually said, because that is the next action.

    A generic "your account was not released" is the support ticket nobody can close —
    the same argument `kyc_not_verified_reason` makes about interpolating the state.
    """
    return (
        f"Calevate's compliance team reviewed this account and did not release it for "
        f"campaign calling: {note.strip()}"
    )


@dataclass(frozen=True, slots=True)
class FirstCampaignReview:
    """What a human decided about this account, for whoever is asking.

    Absence is a VALUE: `reviewed=False` is the normal state of every new account, and a
    `None` return would push each caller into inventing the same "nobody has looked yet"
    shape.
    """

    # False = no row at all: no human has looked. The held state.
    reviewed: bool
    status: str | None
    decision_note: str | None
    reviewed_campaign_id: UUID | None
    decided_at: datetime | None

    @property
    def is_released(self) -> bool:
        """The single predicate every gate asks, computed here rather than in each
        caller so the launch preview, the dispatch tick and the client's own screen can
        never answer it differently."""
        return self.status == FIRST_CAMPAIGN_REVIEW_APPROVED


NOT_REVIEWED = FirstCampaignReview(
    reviewed=False,
    status=None,
    decision_note=None,
    reviewed_campaign_id=None,
    decided_at=None,
)

_SELECT = (
    "SELECT status, decision_note, reviewed_campaign_id, decided_at "
    "FROM first_campaign_reviews WHERE tenant_id = :tid"
)


async def read_first_campaign_review(
    session: AsyncSession, *, tenant_id: UUID
) -> FirstCampaignReview:
    """This account's review, on the caller's RLS-scoped session.

    Hard rule 1: `tenant_id` is a predicate AND the session runs under RLS. The predicate
    is not the isolation — the GUC is — but a read whose predicate names the tenant
    returns zero rows twice over if a policy is ever loosened. A session scoped elsewhere
    gets `NOT_REVIEWED`, which is the correct answer and the SAFE one: it fails closed to
    "held", never to "released".
    """
    row = (await session.execute(text(_SELECT), {"tid": tenant_id})).first()
    if row is None:
        return NOT_REVIEWED
    return FirstCampaignReview(
        reviewed=True,
        status=str(row[0]),
        decision_note=row[1],
        reviewed_campaign_id=row[2],
        decided_at=row[3],
    )


async def record_first_campaign_decision(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    status: str,
    note: str,
    decided_by_admin_id: UUID,
    reviewed_campaign_id: UUID | None = None,
) -> None:
    """Record what an operator decided. Upsert: a reversal replaces the CURRENT state.

    A withdrawn release and a re-release are ordinary — a list turns out to be bought, a
    script is fixed and re-read — so this is one mutable row per tenant, exactly like
    `kyc_records`. The history that must be immutable is `audit_log`, and the ops route
    writes an entry per decision (hard rule 4): reversing a decision adds a row there
    rather than editing one.

    `decided_at` is stamped by the DATABASE in the same statement, never passed in. An
    operator who could supply the date a review happened could supply any date, and the
    whole value of the column to an auditor is that it is the moment the system observed
    the decision (`kyc_records.verified_at` means the same thing for the same reason).

    `reviewed_campaign_id` is COALESCEd, not overwritten with NULL: a later reversal that
    names no campaign must not erase the record of what the first reviewer read.
    """
    await session.execute(
        text(
            "INSERT INTO first_campaign_reviews (id, tenant_id, status, reviewed_campaign_id, "
            "  decision_note, decision_source, decided_by_admin_id, decided_at, created_at, "
            "  updated_at) "
            "VALUES (:id, :tid, :status, :cid, :note, 'operator', :admin_id, now(), now(), now()) "
            "ON CONFLICT (tenant_id) DO UPDATE SET "
            "  status = EXCLUDED.status, "
            "  reviewed_campaign_id = COALESCE("
            "    EXCLUDED.reviewed_campaign_id, first_campaign_reviews.reviewed_campaign_id), "
            "  decision_note = EXCLUDED.decision_note, "
            "  decision_source = 'operator', "
            "  decided_by_admin_id = EXCLUDED.decided_by_admin_id, "
            "  decided_at = now(), "
            "  updated_at = now()"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "status": status,
            "cid": reviewed_campaign_id,
            "note": note.strip(),
            "admin_id": decided_by_admin_id,
        },
    )


__all__ = [
    "FIRST_CAMPAIGN_REVIEW_PENDING_REASON",
    "NOT_REVIEWED",
    "FirstCampaignReview",
    "first_campaign_rejected_reason",
    "read_first_campaign_review",
    "record_first_campaign_decision",
]
