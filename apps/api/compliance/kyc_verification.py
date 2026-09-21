"""Client-driven identity verification: start a run, and absorb its outcome (D-635).

D-47 recorded that a PERSON AT CALEVATE verified a business against a public registry.
That is evidence about an entity. What it cannot give is a named natural person who
personally stood behind the account — and on a self-serve motion that is the whole of the
liability question, because Telecommunications Act 2023 s.3(7) attaches three years and
₹50 lakh to obtaining a telecom identifier on someone else's identity, and "an operator
looked at a GST certificate" does not say who that operator was looking at.

WHAT CROSSES THE BOUNDARY, AND WHAT NEVER DOES
-----------------------------------------------
The client authenticates at the PROVIDER. We hold, per verification: whether it
succeeded, which provider, that provider's transaction reference, and the verified
holder's NAME. We hold no Aadhaar number, no PAN of a natural person, no document, no
scan and no reference to one. `/legal/privacy` states this to clients and cites Aadhaar
Act 2016 s.29 for why, so the absence is a published promise and not merely a preference;
every `kyc_records` column that names a reference or a person carries a CHECK refusing a
twelve-digit bare value, which is what makes the promise enforceable rather than
aspirational; `tests/kyc_provider_seam_test.py` asserts the set from the mapping so a new
column is covered the day it appears.

THE TENANT COMES FROM OUR ROW, NEVER FROM THE PAYLOAD
------------------------------------------------------
`resolve_request` is the only way a webhook learns which tenant an outcome belongs to,
and it looks the run up by `(provider, provider_ref)` — a pair the caller could only know
because we opened the run and were told the reference. A payload field naming its own
tenant would BE the forgery: an attacker who could name a tenant and pass a signature
check (or arrive before one existed) would mark any account on the platform verified.
This is the same discipline the Razorpay receiver follows in resolving a tenant from
order notes it wrote itself.

IDEMPOTENCY IS THE UNIQUE KEY, NOT A SECOND MECHANISM
------------------------------------------------------
`uq_kyc_verification_requests_provider_ref` makes `(provider, provider_ref)` unique, and
`apply_outcome` moves a run out of `created` under a CAS. A redelivery — every aggregator
retries — therefore finds a row that is already terminal, changes nothing, and is
reported as a replay. There is no `webhook_inbox_events` claim here on purpose: the inbox
exists to dedupe events that have no durable record of their own, and this one's record
IS the run. Two dedupe mechanisms over one key is the "two ways per problem" defect, and
the weaker one would be the one that could disagree.

HARD RULE 6. The verified NAME is personal data. It goes in the column and nowhere else —
not into a log line, not into an audit summary, not into a problem+json detail. What the
audit row carries is the provider, the reference, the branch and the boolean, which is
everything an auditor needs and nothing a log aggregator should hold.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.compliance.kyc import read_kyc, record_kyc
from apps.api.compliance.kyc_providers import VerificationOutcome, entity_branch
from apps.api.compliance.models import KYC_VERIFIED
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of

#: A run we opened and the client has not finished. The only state an outcome may be
#: applied to, which is what makes the webhook idempotent.
REQUEST_CREATED: Final = "created"

#: How long an open run may still absorb an outcome.
#:
#: A run is a CAPABILITY: its reference is the one thing that lets an unauthenticated
#: caller move a tenant's verification record, and a capability with no expiry is one a
#: leaked signing secret can still spend months after the client abandoned the tab. Seven
#: days is OURS and is not a vendor fact — no aggregator's consent-request validity is
#: readable from this environment (`kyc_providers/setu.py` records the measurement), so
#: the window is set from the shape of the flow instead: a browser redirect the client
#: either completes in that sitting or leaves, and a retry burst from any provider is
#: bounded in hours. It is deliberately generous in the direction that is safe to be
#: wrong in — a refused late outcome costs the client another run, and every one of them
#: is free, while an unbounded one costs a forged verification.
RUN_TTL: Final = timedelta(days=7)

#: What `apply_outcome` did, for the route to turn into an ack. `replay` is a SUCCESS —
#: the provider is retrying a delivery we already absorbed and must be told to stop.
#: `expired` is a REFUSAL that still acks, because the run really is over and a provider
#: retrying into a 500 forever helps nobody.
OutcomeResult = Literal["applied", "replay", "expired", "unknown_reference"]

#: Client-facing sentences for the states a verification run can end in. Defined here
#: beside the record they describe, for the same reason `KYC_MISSING_REASON` is:
#: one condition, one explanation, however many screens ask.
VERIFICATION_UNAVAILABLE_REASON = (
    "Self-service identity verification is not available on this deployment yet. Our "
    "operations team verifies businesses directly in the meantime — nothing about your "
    "account is blocked by this that was not already."
)

SIGNATORY_VERIFIED_REASON = (
    "Thank you — we have confirmed your identity as the authorised signatory. Because "
    "this account is registered as a company rather than a sole proprietorship, we also "
    "need to check the business itself against its public registry entry, which our "
    "operations team does. Nothing further is needed from you."
)


@dataclass(frozen=True, slots=True)
class VerificationRequest:
    """One run, as the webhook needs to see it: whose, which branch, and still open?"""

    id: UUID
    tenant_id: UUID
    entity_type: str
    status: str
    #: Computed by the DATABASE against `created_at`, not here: the row's age is measured
    #: on the clock that stamped it, so an app server whose time has drifted cannot expire
    #: a live run or revive a dead one.
    past_ttl: bool

    @property
    def is_open(self) -> bool:
        return self.status == REQUEST_CREATED and not self.past_ttl


async def open_request(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    provider: str,
    provider_ref: str,
    entity_type: str,
) -> UUID:
    """Record the run BEFORE the client is redirected.

    Ordering is load-bearing and is the reason this is its own function: an outcome that
    arrives for a reference we never wrote has no tenant and is refused. Writing the row
    after the redirect would leave a window in which a genuine, correctly-signed outcome
    is dropped because the client completed the flow faster than we committed.
    """
    request_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO kyc_verification_requests "
            "  (id, tenant_id, provider, provider_ref, status, entity_type, "
            "   created_at, updated_at) "
            "VALUES (:id, :tid, :provider, :ref, 'created', :entity_type, now(), now())"
        ),
        {
            "id": request_id,
            "tid": tenant_id,
            "provider": provider,
            "ref": provider_ref,
            "entity_type": entity_type,
        },
    )
    return request_id


async def resolve_request(
    session: AsyncSession, *, provider: str, provider_ref: str
) -> VerificationRequest | None:
    """Which tenant this outcome belongs to — from our own row, never from the payload.

    Called on an UNTENANTED session, necessarily: the caller has no tenant yet, which is
    exactly what it is asking. That is safe here and would not be in a request handler,
    because the lookup key is a reference the caller can only hold if we issued it, and
    because everything the answer is used for runs under `tenant_session(resolved)`.
    """
    row = (
        await session.execute(
            text(
                "SELECT id, tenant_id, entity_type, status, created_at < now() - :ttl "
                "FROM kyc_verification_requests "
                "WHERE provider = :provider AND provider_ref = :ref"
            ),
            {"provider": provider, "ref": provider_ref, "ttl": RUN_TTL},
        )
    ).first()
    if row is None:
        return None
    return VerificationRequest(
        id=row[0],
        tenant_id=row[1],
        entity_type=str(row[2]),
        status=str(row[3]),
        past_ttl=bool(row[4]),
    )


async def expire_stale_runs(session: AsyncSession, *, tenant_id: UUID) -> int:
    """Close this tenant's runs that are past `RUN_TTL`. Returns how many.

    Called when the client starts another run, which with the webhook's own check makes
    two writers of `expired` and no third state anybody has to schedule. A background
    sweep was the alternative and buys nothing here: the row has exactly two readers, both
    of them evaluate the age themselves, and a fleet-wide cron over a table whose stale
    rows nothing consults would be a deployable added for tidiness.
    """
    closed = await session.execute(
        text(
            "UPDATE kyc_verification_requests SET status = 'expired', completed_at = now(), "
            "  updated_at = now() "
            "WHERE tenant_id = :tid AND status = 'created' AND created_at < now() - :ttl"
        ),
        {"tid": tenant_id, "ttl": RUN_TTL},
    )
    return rowcount_of(closed)


async def apply_outcome(
    session: AsyncSession,
    *,
    request: VerificationRequest,
    provider: str,
    outcome: VerificationOutcome,
) -> OutcomeResult:
    """Close the run and write what it proved. ONE transaction, the caller's.

    The run's state and the verification record move together or neither moves: a
    committed `completed` run over an unwritten record would be a client who verified
    themselves, cannot do it again (the reference is spent), and is not verified.

    The CAS on `status = 'created'` is what makes a redelivery harmless. It is not
    optimistic locking against a concurrent operator — it is the provider's own retry,
    which is guaranteed rather than hypothetical.
    """
    if request.past_ttl:
        # The run outlived its window (`RUN_TTL`). Refused BEFORE the completion CAS, so a
        # late outcome cannot verify anybody — and stamped `expired` in the same breath,
        # because a row that refuses deliveries while still reading `created` is a state
        # nobody can act on.
        expired = await session.execute(
            text(
                "UPDATE kyc_verification_requests SET status = 'expired', "
                "  completed_at = now(), updated_at = now() "
                "WHERE id = :id AND status = 'created'"
            ),
            {"id": request.id},
        )
        if rowcount_of(expired) == 0:
            return "replay"
        await _audit(
            session,
            request=request,
            provider=provider,
            outcome=outcome,
            action="kyc.self_verification_expired",
        )
        return "expired"

    closed = await session.execute(
        text(
            "UPDATE kyc_verification_requests SET status = :status, failure_reason = :reason, "
            "  completed_at = now(), updated_at = now() "
            "WHERE id = :id AND status = 'created'"
        ),
        {
            "id": request.id,
            "status": "completed" if outcome.verified else "failed",
            "reason": None if outcome.verified else outcome.failure_reason,
        },
    )
    if rowcount_of(closed) == 0:
        # Already terminal. The provider is retrying something we absorbed; nothing to do
        # and nothing wrong. Reported rather than swallowed so the route can ack it as a
        # replay and an operator reading the logs can tell a retry from a first delivery.
        return "replay"

    if not outcome.verified:
        # A failed run leaves the RECORD untouched on purpose. The client may try again,
        # and moving `kyc_records` to `rejected` here would mean an abandoned browser tab
        # reads to an operator as a refused business — and `rejected` demands a reason a
        # provider's "user closed the flow" is not.
        await _audit(
            session,
            request=request,
            provider=provider,
            outcome=outcome,
            action="kyc.self_verification_failed",
        )
        return "applied"

    if (await read_kyc(session, tenant_id=request.tenant_id)).is_verified:
        # ALREADY VERIFIED, BY WHATEVER ROUTE — so this outcome may not touch the record.
        # `record_kyc` takes `status` from EXCLUDED outright and re-stamps `verified_at`,
        # which on the signatory branch below means a company's completed run would move a
        # verified account back to `submitted` and stop its dialling. The start route's
        # "already verified" refusal cannot cover this: the run was opened BEFORE the
        # verification existed. The run itself still closes — it genuinely completed at the
        # provider — and the audit row says an attestation arrived for an account that had
        # one already, which is what an auditor needs to see.
        await _audit(
            session,
            request=request,
            provider=provider,
            outcome=outcome,
            action="kyc.self_verification_superseded",
        )
        return "applied"

    branch = entity_branch(request.entity_type)
    # A SOLE PROPRIETOR **IS** THE ENTITY, so verifying the person verifies the
    # subscriber. Every other entity type verifies the authorised SIGNATORY, which is
    # necessary and not sufficient: the business still has to be checked against its
    # public registry entry, and only an operator does that. Writing `verified` for a
    # company here would mark a business verified on one individual's personal
    # authentication — the precise outcome this design exists to avoid.
    status = KYC_VERIFIED if branch == "proprietor_is_the_entity" else "submitted"
    await record_kyc(
        session,
        tenant_id=request.tenant_id,
        status=status,
        entity_type=request.entity_type,
        verification_source="aggregator",
        verification_provider=provider,
        verification_reference=outcome.provider_ref,
        verified_name=outcome.verified_name,
    )
    # `signatory_name` is deliberately NOT written from `verified_name`. They are
    # different claims — one is what an operator recorded about who signs for the entity,
    # the other is what a licensed intermediary attested about a person's identity — and
    # collapsing them would leave no way to tell an attested name from a typed one.
    await _audit(
        session,
        request=request,
        provider=provider,
        outcome=outcome,
        action="kyc.self_verified",
    )
    return "applied"


async def _audit(
    session: AsyncSession,
    *,
    request: VerificationRequest,
    provider: str,
    outcome: VerificationOutcome,
    action: str,
) -> None:
    """The liability record, in the caller's transaction.

    HARD RULE 6: `outcome.verified_name` is absent from this summary and from every log
    line in this module. It is personal data, it is already in the column, and an audit
    chain is not where a person's name should be duplicated. What is here is what an
    auditor actually needs — which provider attested it, under which reference, on which
    branch — and each of those is a business fact about a run, not about a person.
    """
    await write_audit(
        session,
        action=action,
        actor_type="system",
        tenant_id=request.tenant_id,
        object_type="kyc_verification_request",
        object_id=str(request.id),
        summary={
            "provider": provider,
            "provider_ref": outcome.provider_ref,
            "verified": outcome.verified,
            "entity_branch": entity_branch(request.entity_type),
            "failure_reason": outcome.failure_reason,
        },
    )


__all__ = [
    "REQUEST_CREATED",
    "RUN_TTL",
    "SIGNATORY_VERIFIED_REASON",
    "VERIFICATION_UNAVAILABLE_REASON",
    "OutcomeResult",
    "VerificationRequest",
    "apply_outcome",
    "expire_stale_runs",
    "open_request",
    "resolve_request",
]
