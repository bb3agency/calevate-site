"""Do-not-call management — the WRITE side of hard rule 5's live suppression list.

`compliance.service.add_to_dnc` has existed since the compliance gate shipped, and
until now nothing called it. The gate reads `dnc_list` live on every dispatch (never
cached, so "don't call me again" lands before the next tick) — but a list nobody can
write to makes that live read a promise about an empty table. SEC-COMP §3 names the
opt-out path; this module is it.

Four deliberate choices, each of which a reviewer should be able to check:

- **Counts, never numbers, come back from a bulk add.** It mirrors
  `campaigns.add_contacts` (added / already-suppressed / malformed as integers) rather
  than echoing a pasted list back, and the audit row records the same counts. A
  suppression list is the one place where "who asked us to stop calling them" is itself
  sensitive.
- **The list is masked** with `crm.service.mask_phone` — the same last-two-digits rule
  the leads list uses, because the DNC page is just as screenshotable.
- **A number that is already suppressed is not re-inserted**, including when the match
  is a GLOBAL entry. The unique constraint is `(tenant_id, phone_e164)`, so a tenant row
  shadowing a global one would not conflict — it would just be a second row saying the
  same thing, and a count of "added: 1" that means nothing changed.
- **Global entries are read-only to a tenant.** RLS already refuses the write; naming
  the refusal turns a silent zero-row DELETE into an explanation.

Normalization is `ingest.normalize_phone` — the same function the lead path uses, so a
number suppressed from a web form and the same number suppressed by hand produce the
same E.164 string, and the gate's equality check actually matches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm.service import mask_phone
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.ingest.service import normalize_phone

log = get_logger(__name__)

# Where a suppression came from. Free text in the column (no CHECK constraint), pinned
# here so the list stays answerable when someone asks "why is this number blocked".
SOURCES = ("customer_request", "call_optout", "manual", "regulator")

MAX_NUMBERS_PER_ADD = 2000
MAX_LIST = 500


@dataclass(frozen=True, slots=True)
class AddResult:
    added: int
    already_suppressed: int
    malformed: int


@dataclass(frozen=True, slots=True)
class DncEntryView:
    id: UUID
    phone_masked: str
    scope: str
    source: str | None
    added_at: Any
    removable: bool


@dataclass(frozen=True, slots=True)
class CheckResult:
    """`dialable` is the answer to the only question worth asking. `scope` says which
    list caught it, because "someone in your office added this" and "this number is
    nationally suppressed" have different remedies."""

    valid: bool
    suppressed: bool
    scope: str | None


async def add_numbers(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    raw_numbers: list[str],
    source: str,
) -> AddResult:
    """Bulk add, deduplicated against what is already suppressed for this tenant.

    Two round trips rather than one INSERT ... ON CONFLICT: the conflict target cannot
    see global rows, so only a read tells us whether a number is already blocked. The
    insert still carries ON CONFLICT DO NOTHING — between our read and our write another
    request may have added the same number, and a concurrent add must be a no-op, not a
    500. In that race `added` over-reports by one; the list is still correct.
    """
    if source not in SOURCES:
        raise ProblemError.business_rule(
            "dnc_unknown_source",
            "That is not a recognised reason for suppressing a number.",
            remediation=f"Use one of: {', '.join(SOURCES)}.",
        )

    normalized: list[str] = []
    malformed = 0
    for raw in raw_numbers:
        e164 = normalize_phone(raw)
        if e164 is None:
            malformed += 1
            continue
        normalized.append(e164)
    # Duplicates within the pasted list are not "already suppressed" — they are one
    # number typed twice, which should count once and surprise nobody.
    unique = list(dict.fromkeys(normalized))

    if not unique:
        return AddResult(added=0, already_suppressed=0, malformed=malformed)

    existing = {
        row[0]
        for row in (
            await session.execute(
                text(
                    "SELECT phone_e164 FROM dnc_list WHERE phone_e164 = ANY(:phones) "
                    "AND (tenant_id = :tid OR tenant_id IS NULL)"
                ),
                {"phones": unique, "tid": tenant_id},
            )
        ).all()
    }
    fresh = [phone for phone in unique if phone not in existing]

    if fresh:
        await session.execute(
            text(
                "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source, added_at, "
                "created_at) VALUES (:id, :tid, :phone, 'tenant', :source, now(), now()) "
                "ON CONFLICT (tenant_id, phone_e164) DO NOTHING"
            ),
            [
                {"id": uuid7(), "tid": tenant_id, "phone": phone, "source": source}
                for phone in fresh
            ],
        )

    # Counts only (hard rule 6): the numbers are the whole point of the request and
    # none of them belong in a log line.
    log.info(
        "dnc_added",
        extra={"tenant_id": str(tenant_id), "added": len(fresh), "source": source},
    )
    return AddResult(
        added=len(fresh),
        already_suppressed=len(unique) - len(fresh),
        malformed=malformed,
    )


async def list_entries(session: AsyncSession, *, limit: int = 100) -> list[DncEntryView]:
    """Newest first. RLS hands back this tenant's rows plus the global ones, which is
    exactly what a client needs to see: a number they cannot un-suppress is still a
    number they should know is suppressed."""
    rows = (
        await session.execute(
            text(
                "SELECT id, phone_e164, scope, source, added_at FROM dnc_list "
                "ORDER BY added_at DESC, id DESC LIMIT :n"
            ),
            {"n": min(limit, MAX_LIST)},
        )
    ).all()
    return [
        DncEntryView(
            id=row[0],
            phone_masked=mask_phone(row[1]) or "",
            scope=row[2],
            source=row[3],
            added_at=row[4],
            removable=is_removable(scope=row[2], source=row[3]),
        )
        for row in rows
    ]


async def check_number(session: AsyncSession, *, tenant_id: UUID, raw: str) -> CheckResult:
    """ "Is this number suppressed?" — the question the masked list cannot answer.

    Deliberately mirrors the gate's own query (`compliance.service.check_dispatch`)
    rather than approximating it: a check that disagrees with the gate is worse than no
    check, because it teaches someone to trust the wrong answer.
    """
    e164 = normalize_phone(raw)
    if e164 is None:
        return CheckResult(valid=False, suppressed=False, scope=None)
    row = (
        await session.execute(
            text(
                "SELECT scope FROM dnc_list WHERE phone_e164 = :phone "
                "AND (tenant_id = :tid OR tenant_id IS NULL) "
                # A global entry outranks a tenant one in the answer: it is the stronger
                # statement and the one the client cannot act on.
                "ORDER BY (scope = 'global') DESC LIMIT 1"
            ),
            {"phone": e164, "tid": tenant_id},
        )
    ).first()
    if row is None:
        return CheckResult(valid=True, suppressed=False, scope=None)
    return CheckResult(valid=True, suppressed=True, scope=row[0])


# A suppression a HUMAN AT THE CLIENT typed in is theirs to undo — a wrong digit in a
# pasted list must be fixable. A suppression that records a CONSUMER's request is not:
# "don't call me again" is the caller's decision, and an account that can delete it can
# un-hear it. So removal is scoped to the one source that means "we typed this".
REMOVABLE_SOURCES = ("manual",)


def is_removable(*, scope: str, source: str | None) -> bool:
    """The ONE definition of "may this be undone here". `list_entries` renders it as a
    flag and `remove_entry` enforces it; if the two computed it separately, the list
    would eventually offer a button the endpoint refuses — which is how a UI teaches
    someone that our compliance rules are a bug."""
    return scope != "global" and source in REMOVABLE_SOURCES


async def remove_entry(session: AsyncSession, *, entry_id: UUID) -> str:
    """Delete one hand-added tenant entry. Returns its source, for the audit row.

    Deliberately NOT an admin-realm route. It cannot be one: `admin:tenants` is a
    MUTATING permission, and D-22 refuses mutating permissions while impersonating —
    so an admin-realm principal reaching a tenant's suppression list has either no
    tenant GUC (RLS: zero rows) or a read-only one. A route only ops could call would
    be a route nobody could call.
    """
    row = (
        await session.execute(
            text("SELECT scope, source FROM dnc_list WHERE id = :id"), {"id": entry_id}
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("DNC entry")
    scope, source = row[0], row[1]
    # Two named refusals rather than one `is_removable` check, because the two have
    # different remedies and a client deserves to be told which wall they hit.
    if scope == "global":
        raise ProblemError.business_rule(
            "dnc_global_entry",
            "This number is suppressed nationally, not by this account.",
            remediation="Global suppressions are removed by operations, not from here.",
        )
    if source not in REMOVABLE_SOURCES:
        raise ProblemError.business_rule(
            "dnc_consumer_optout",
            "This number asked not to be called. That request cannot be undone here.",
            remediation="If this entry is a mistake, contact support with the details.",
        )
    result = await session.execute(text("DELETE FROM dnc_list WHERE id = :id"), {"id": entry_id})
    if rowcount_of(result) != 1:
        # RLS refusing the write looks exactly like this. Do not report success.
        raise ProblemError.not_found("DNC entry")
    return str(source)


__all__ = [
    "MAX_LIST",
    "MAX_NUMBERS_PER_ADD",
    "REMOVABLE_SOURCES",
    "SOURCES",
    "AddResult",
    "CheckResult",
    "DncEntryView",
    "add_numbers",
    "check_number",
    "is_removable",
    "list_entries",
    "remove_entry",
]
