"""Reads and writes over `legal_acceptances`, and the ONE predicate every gate asks.

`agreements_blocker` is the whole point of this module: the campaign launch preview, the
dispatch tick, the per-dial gate and the agent publish path must all refuse an
organisation that has not accepted its agreements, and they must refuse it under ONE rule
name with ONE sentence. That is the shape `compliance.registration.outbound_entity_blockers`
already has, and the reason it has it — two gates that explain the same condition
differently are two gates disagreeing in front of a client.

Nothing here imports `apps.api.compliance`: the audit write belongs to the ROUTE (which is
where the principal and the caller's IP are), so this module can be imported by
`compliance.service` without closing a cycle.

Hard rule 6: no log line here carries a person's name or email. Ids, slugs and versions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.legal import catalogue, statements

log = get_logger(__name__)

#: The rule name the gates emit. Named once, here, so SEC-COMP §3, the screens, the tests
#: and four call sites cite the same string (`scripts/check_docs_drift.unknown_rule_names`
#: is the check that keeps that promise honest).
AGREEMENTS_RULE = "agreements_not_accepted"

AGREEMENTS_REASON = (
    "This account has not accepted its agreements yet. Only the account owner can do it, "
    "on the Agreements & readiness screen."
)


@dataclass(frozen=True, slots=True)
class Acceptance:
    """The latest acceptance of one document by one organisation."""

    document_slug: str
    document_version: str
    statement_version: str
    accepted_at: datetime
    accepted_by_user_id: UUID
    #: The accepting person's display name, or None when their profile carries none.
    #: Resolved here rather than by the screen so "who agreed to this" is answered by the
    #: same read that answers "when" — a console that joined it separately could show one
    #: without the other on a slow day.
    accepted_by_name: str | None


async def latest_acceptances(session: AsyncSession, *, tenant_id: UUID) -> dict[str, Acceptance]:
    """The newest acceptance per document for this organisation, keyed by slug.

    ONE query with `DISTINCT ON` rather than one per document: the readiness screen asks
    about eight documents and every outbound gate asks about four, so a per-document read
    would be four extra round trips on the dial path.

    `ORDER BY accepted_at DESC, created_at DESC` is exactly the index
    (`ix_legal_acceptances_current`) and exactly the tie-break `catalogue` reasoning
    assumes: two rows written in the same instant must resolve deterministically.
    """
    rows = (
        await session.execute(
            text(
                "SELECT DISTINCT ON (la.document_slug) la.document_slug, "
                "la.document_version, la.statement_version, la.accepted_at, "
                "la.accepted_by_user_id, u.name "
                "FROM legal_acceptances la "
                "LEFT JOIN users u ON u.id = la.accepted_by_user_id "
                "WHERE la.tenant_id = :tid "
                "ORDER BY la.document_slug, la.accepted_at DESC, la.created_at DESC"
            ),
            {"tid": tenant_id},
        )
    ).all()
    return {
        str(row[0]): Acceptance(
            document_slug=str(row[0]),
            document_version=str(row[1]),
            statement_version=str(row[2]),
            accepted_at=row[3],
            accepted_by_user_id=UUID(str(row[4])),
            accepted_by_name=str(row[5]) if row[5] else None,
        )
        for row in rows
    }


def outstanding_slugs(accepted: dict[str, Acceptance]) -> list[str]:
    """Which BLOCKING documents still need accepting, in catalogue order.

    Pure, so the gate and the screen share it and the tests can drive it without a
    database. The catalogue decides materiality; this decides nothing.
    """
    return [
        spec.slug
        for spec in catalogue.DOCUMENTS
        if spec.blocking
        and catalogue.reacceptance_required(
            spec, accepted[spec.slug].document_version if spec.slug in accepted else None
        )
    ]


async def agreements_blocker(session: AsyncSession, *, tenant_id: UUID) -> tuple[str, str] | None:
    """`(rule, reason)` if unaccepted agreements stop this organisation's outbound, else None.

    Returns the PAIR rather than a bool for the reason `kyc_blocker` and
    `first_campaign_hold_blocker` do: the launch preview, the dispatch tick and the dial
    gate must name the condition identically. There is only ONE failure here — some
    blocking document has not been accepted at its current version — because the client's
    next action is the same whichever document it is, and the screen that lists them by
    name is one click away.

    ONE indexed read (`ix_legal_acceptances_current`), on a row set that is at most four
    per tenant.
    """
    accepted = await latest_acceptances(session, tenant_id=tenant_id)
    if not outstanding_slugs(accepted):
        return None
    return (AGREEMENTS_RULE, AGREEMENTS_REASON)


async def assert_agreements_accepted(session: AsyncSession, *, tenant_id: UUID) -> None:
    """Refuse to PUBLISH an agent for an organisation that has not accepted its agreements.

    The launch/dispatch gates return a blocker because they render a to-do list; publish
    raises, because it is a single action with a single answer — the shape
    `tenancy.lifecycle.assert_account_open` uses, called from the same place in
    `agents.service.publish_agent` and for a related reason. Putting an agent on the phone
    under a Data Processing Addendum nobody has agreed to is us processing a client's
    callers' personal data with no instrument covering it.

    `conflict`, not `permission`: the caller may well hold every permission there is (an
    operator publishes on the client's behalf). The ACCOUNT is in the wrong state, and the
    remediation names whose move it is.
    """
    blocker = await agreements_blocker(session, tenant_id=tenant_id)
    if blocker is None:
        return
    raise ProblemError.conflict(
        blocker[0],
        "This account has not accepted its agreements, so its agents cannot be published.",
        remediation=(
            "The account owner accepts them on the Agreements & readiness screen in their "
            "own console. Nobody else can accept on their behalf."
        ),
    )


async def record_acceptance(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    slug: str,
    version: str,
    statement_version: str,
    user_id: UUID,
) -> Acceptance:
    """Append one acceptance. INSERT-only (hard rule 4) — a re-acceptance is a new row.

    Three refusals before the write, each of which is a state a real client reaches:

    * **An unknown or non-acceptable document.** The four blocking documents are the only
      ones a row may name; the other four are notices we owe the client, not promises they
      make us, and a signature on the sub-processor list would make every vendor change a
      consent event for every tenant.
    * **A version that is not the current one.** A console left open across a publication
      would otherwise record an agreement to text nobody is showing any more — a row that
      evidences something that did not happen, which is worse than no row. The same
      refusal `whatsapp_optin_routes.record` makes about a stale notice version, for the
      same reason.
    * **A stale acceptance statement.** Same argument, one level down: the wording the
      person ticked is half the evidence, so a client whose browser is showing last
      quarter's sentence must reload rather than have this quarter's version recorded
      against their click.

    THE WRITE IS UNCONDITIONAL AND THERE IS NO UPSERT. A second click by the same owner
    appends a second row for the same version, and that is correct rather than tolerated:
    the table is append-only, a duplicate acceptance changes no answer any gate gives
    (`latest_acceptances` takes the newest), and the alternative — a unique constraint on
    (tenant, slug, version) — would make a legitimate re-acceptance after a rollback
    impossible. The double-click cost is one row, not a charge and not a side effect,
    which is the whole reason this route does not carry an `Idempotency-Key`; the argument
    is in `routes.accept`.
    """
    spec = catalogue.document(slug)
    if spec is None or slug not in catalogue.ACCEPTABLE_SLUGS:
        raise ProblemError(
            kind="validation",
            code="legal_document_not_acceptable",
            title="That document is not one this account accepts",
            detail="Only the agreements listed on the readiness screen can be accepted.",
            remediation="Reload the page and accept one of the documents it lists.",
        )
    if version != spec.current_version:
        raise ProblemError.business_rule(
            "legal_version_not_current",
            "The version of this document on your screen is out of date.",
            remediation=(
                "Reload the page and read it again — the document has changed since it loaded."
            ),
        )
    if statement_version != statements.statement_version():
        raise ProblemError.business_rule(
            "legal_statement_not_current",
            "The wording you are agreeing to is out of date.",
            remediation="Reload the page and confirm again — the text has changed since it loaded.",
        )

    row = (
        await session.execute(
            text(
                "INSERT INTO legal_acceptances (id, tenant_id, document_slug, "
                "document_version, statement_version, accepted_by_user_id) "
                "VALUES (:id, :tid, :slug, :version, :statement, :uid) "
                "RETURNING accepted_at"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "slug": slug,
                "version": version,
                "statement": statement_version,
                "uid": user_id,
            },
        )
    ).first()
    assert row is not None  # RETURNING on a single-row INSERT
    log.info(
        "legal_acceptance_recorded",
        extra={
            "tenant_id": str(tenant_id),
            "document_slug": slug,
            "document_version": version,
            "statement_version": statement_version,
        },
    )
    name = (
        await session.execute(text("SELECT name FROM users WHERE id = :uid"), {"uid": user_id})
    ).scalar()
    return Acceptance(
        document_slug=slug,
        document_version=version,
        statement_version=statement_version,
        accepted_at=row[0],
        accepted_by_user_id=user_id,
        accepted_by_name=str(name) if name else None,
    )


__all__ = [
    "AGREEMENTS_REASON",
    "AGREEMENTS_RULE",
    "Acceptance",
    "agreements_blocker",
    "assert_agreements_accepted",
    "latest_acceptances",
    "outstanding_slugs",
    "record_acceptance",
]
