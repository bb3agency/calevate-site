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
- **The list shows numbers in full**, like every other contact surface (D-436). It used
  to be dotted "because the DNC page is screenshotable", which is an argument against
  every screen in the product; what it actually cost was the ability to check that the
  number an angry caller is quoting is the one on the list.
- **A number that is already suppressed is not re-inserted**, including when the match
  is a GLOBAL entry. The unique constraint is `(tenant_id, phone_e164)`, so a tenant row
  shadowing a global one would not conflict — it would just be a second row saying the
  same thing, and a count of "added: 1" that means nothing changed.
- **Global entries are read-only to a tenant.** RLS already refuses the write; naming
  the refusal turns a silent zero-row DELETE into an explanation.

Normalization is `ingest.normalize_phone` — the same function the lead path uses, so a
number suppressed from a web form and the same number suppressed by hand produce the
same E.164 string, and the gate's equality check actually matches.

THE GLOBAL SCOPE, AND WHAT IT IS NOT
------------------------------------
`scope='global'` shipped fully built on the READ side — the gate ranks it above a tenant
entry, `is_removable` refuses it, `remove_entry` has a named refusal for it, the launch
scrub includes it — and had **no writer anywhere**, in `apps/`, `scripts/`, `alembic/`
or the seed. Both INSERT sites hardcoded `'tenant'`. So `remove_entry`'s "global
suppressions are removed by operations, not from here" named a desk that did not exist,
and `runbooks/dnc-complaint.md` §1 described a row nothing could produce.

`add_global_numbers` is that desk. What it writes is a **platform-wide ABSOLUTE
suppression**: a number Calevate will not dial for any tenant, on any classification,
ever — a regulator or TSP instruction naming a number, or our own permanent refusal
after a complaint. It is deliberately NOT the national DND register: NCPR preferences
are category-scoped and expire daily, and loading them here would refuse lawful
transactional traffic. That half of SEC-COMP §3 is `compliance/preference_scrub.py`,
whose docstring carries the regulatory sources.

The RLS asymmetry is unchanged where it matters. Migration `a1c8e40f27b9` widens WITH
CHECK by exactly one branch — a session with NO `app.tenant_id` may write a
`scope='global'` row — so a TENANT session still cannot suppress a number for every
other client, which is the escalation the original policy was written to prevent. The
ops surface reaches it through `global_db`, never through the owner DB role (hard rule
1). A widened branch that fired on the wrong session over-blocks dialling and can never
under-block it, so the direction of any mistake here is safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.callbacks.service import cancel_for_phones
from apps.api.compliance.dnc_recall import enqueue_dnc_recall
from apps.api.compliance.export import subject_ref
from apps.api.compliance.models import DNC_REMOVABLE_SOURCES
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.ingest.service import normalize_phone

log = get_logger(__name__)

#: What a client reads on a call-back a suppression called off. It says what happened
#: rather than naming the rule, for the reason every client-facing sentence in this tree
#: does: "refused (dnc)" is our vocabulary and a person reads their screen, not our enum.
#: The GATE writes its own DNC sentence on a call-back it refuses at fire time; this is the
#: wording for the ones stopped days earlier, which never reach the gate at all.
CALLBACK_SUPPRESSED_REASON = (
    "This number was added to your do-not-call list, so we did not ring them back."
)

# Where a suppression came from. Free text in the column (no CHECK constraint), pinned
# here so the list stays answerable when someone asks "why is this number blocked".
SOURCES = ("customer_request", "call_optout", "manual", "regulator")

# The reasons a PLATFORM-WIDE suppression can exist. A deliberately shorter list than
# `SOURCES` and deliberately disjoint from the two consumer ones: nobody asks a client's
# receptionist to suppress a number for every business on the platform, so
# `customer_request` and `call_optout` are not answers to this question and their
# presence would invite an operator to widen a single tenant's opt-out to everyone.
# `regulator` = an instruction from TRAI, a TSP or the DLT registrar naming this number.
# `platform_block` = our own permanent refusal to dial it (a complaint we settled, a
# number that must never be called from this platform again).
GLOBAL_SOURCES = ("regulator", "platform_block")

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
    phone_e164: str
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
    500.

    `added` IS THE STATEMENT'S ROWCOUNT, NOT THE LENGTH OF THE LIST WE MEANT TO INSERT.
    This used to report `len(fresh)` — a count computed from a read taken before the
    write — and the docstring accepted the over-report ("in that race `added`
    over-reports by one; the list is still correct"). Two operators pasting the same list
    at once therefore BOTH read "12 numbers suppressed" while one of them inserted
    nothing, and this is a compliance screen: the number a person will quote when asked
    what they did about a complaint. Verified on this driver, which reports an exact
    rowcount for an executemany with `ON CONFLICT DO NOTHING` (3 fresh → 3, 3 conflicting
    → 0, 2 conflicting + 1 fresh → 1), and `rowcount_of` floors an absent rowcount at 0
    rather than guessing — under-reporting a suppression somebody else made is the safe
    direction, over-claiming one nobody made is not.

    `already_suppressed` is then derived from it, so the three counts still sum to what
    was sent and the difference lands where it belongs: a number a racing request
    suppressed a millisecond earlier IS already suppressed by the time this answer is
    given, which is the true statement to make about it.
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

    added = 0
    if fresh:
        result = await session.execute(
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
        added = rowcount_of(result)
        # D-428(b): the suppression is not honoured until the dials the vendor is
        # ALREADY holding are pulled back. Same transaction as the insert above, so the
        # two share a fate. `fresh` only — a re-import of an unchanged list enqueues
        # nothing.
        #
        # `fresh` AND NOT the rows this statement actually inserted, deliberately: the
        # COUNT must be exact and the RECALL must be over-inclusive. A number a racing
        # request inserted a millisecond ago has its own recall enqueued, but that recall
        # is idempotent (`calls.recall_requested_at` is a one-way stamp) and running it
        # twice costs a scan, while missing one leaves a suppressed number's dial sitting
        # in the vendor's queue. The two questions have different safe directions.
        await enqueue_dnc_recall(session, tenant_id=tenant_id, phones=fresh)
        # D-510: and the call-backs this client's agents PROMISED these people, which are
        # dials that have not been placed yet and so are invisible to the recall above.
        #
        # **THIS IS THE FAST DOOR AND NOT THE ENFORCEMENT**, which matters for reading the
        # blast radius: every call-back dial passes `check_dispatch` at its own fire time
        # with an uncached per-number DNC read, and `dnc` is a person-level refusal, so a
        # promise to a suppressed number is settled `refused` on the next tick whether or
        # not this statement ran. What this buys is that the client's screen stops saying
        # "we will ring them on Tuesday" the moment they suppress the number, instead of
        # on Tuesday. Same transaction as the insert, so a suppression that rolls back
        # cannot leave a call-back cancelled for a reason that never happened.
        cancelled = await cancel_for_phones(
            session, phones=fresh, reason=CALLBACK_SUPPRESSED_REASON
        )
        if cancelled:
            log.info(
                "dnc_cancelled_callbacks",
                extra={"tenant_id": str(tenant_id), "cancelled": cancelled},
            )

    # Counts only (hard rule 6): the numbers are the whole point of the request and
    # none of them belong in a log line.
    log.info(
        "dnc_added",
        extra={"tenant_id": str(tenant_id), "added": added, "source": source},
    )
    return AddResult(
        added=added,
        already_suppressed=len(unique) - added,
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
            phone_e164=row[1],
            scope=row[2],
            source=row[3],
            added_at=row[4],
            removable=is_removable(scope=row[2], source=row[3]),
        )
        for row in rows
    ]


async def check_number(session: AsyncSession, *, tenant_id: UUID, raw: str) -> CheckResult:
    """ "Is this number suppressed?" — one number, decided, without paging the list.

    The list itself has answered this since D-436 unmasked it, so this is no longer the
    ONLY way to ask; it is still the right one, because the list is capped and a number
    beyond the cap would read as "not suppressed" — which is the one wrong answer here.

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


@dataclass(frozen=True, slots=True)
class Removal:
    """What a release leaves behind — the TOMBSTONE for a suppression that was lifted.

    Until D-185 a removal left nothing at all. The row was hard-deleted and the audit row
    carried the entry id and the `source` but never the number (correctly — hard rule 6),
    so once the row was gone *nothing anywhere* answered "which number stopped being
    suppressed". A `manual` entry that was really a mis-recorded in-call opt-out could be
    released and the number returned to the dial pool with no reviewable trail, and TRAI's
    obligation attaches to the number rather than to our row id.

    `subject_ref` closes that: the same one-way handle `compliance/export.subject_ref`
    already mints, which `deletion_requests.subject_ref` stores and the erasure proof
    quotes. It confirms a release to an auditor who already holds the number — the
    complaint that prompts the review always arrives WITH the number — and discloses
    nothing to anyone who does not. One instrument for "name a data subject without
    writing a number down", not a second one.

    REJECTED: a tombstone row — keeping `dnc_list` and marking it `removed_at`. It looks
    like the more faithful record and is the worse one, in three separate ways:

    * It keeps a phone number that no longer suppresses anybody. `deletion.ERASURE_LIMITATIONS`
      discloses that a DNC entry survives an erasure, and the whole justification it gives
      the data principal is "removing it would make the person callable again". That
      sentence is FALSE of a released row, so a tombstone would be retained personal data
      with no purpose left — DPDP §8(7) storage limitation — and would force that
      limitation to be widened rather than left alone.
    * `add_numbers`' dedupe read (`WHERE phone_e164 = ANY(:phones)`) would match the
      tombstone and report a re-add as `already_suppressed`. Re-suppressing a released
      number would silently do nothing. Every other read path that missed the
      `removed_at IS NULL` predicate over-blocks, which is safe; that one under-blocks,
      which is the direction hard rule 5 cannot take.
    * It requires the `UNIQUE (tenant_id, phone_e164)` key to become partial, and that key
      is a checked compliance invariant (`scripts/check_compliance_invariants.py`,
      "dnc_list unique (tenant_id, phone_e164)") because it is what makes `add_to_dnc`
      idempotent.

    So the history goes where `dnc.removed` already goes and `dnc_list` keeps meaning
    exactly one thing: the numbers we will not dial right now.

    WHERE IT ACTUALLY LANDS, stated precisely because the word "audited" invites a stronger
    reading than the mechanism supports: `write_audit` writes a hash-chained ROW, and the
    `summary` is NOT part of it — `audit_log` has no summary column, so hashing a field the
    row does not carry would make the chain unverifiable. The chained row carries the actor,
    the tenant, the action and the entry id; `subject_ref` rides the sanitised summary into
    the log stream, keyed by the same entry id. That is the same placement
    `deletion.request_deletion` gives the erasure's `subject_ref`, and following it is the
    point — a second home for one kind of fact is the drift this repo pays for. It is a
    tamper-EVIDENT record of the release plus a correlated detail line, not a tamper-evident
    record of the number. Making the reference itself chained would mean putting it in
    `object_id`, which every other row uses for the object's own id.
    """

    source: str
    subject_ref: str


# A suppression a HUMAN AT THE CLIENT typed in is theirs to undo — a wrong digit in a
# pasted list must be fixable. A suppression that records a CONSUMER's request is not:
# "don't call me again" is the caller's decision, and an account that can delete it can
# un-hear it. So removal is scoped to the one source that means "we typed this".
#
# THE DEFINITION MOVED to `compliance/models.py` (D-189) and this is a re-export, not a
# second copy. `compliance.service.add_to_dnc` has to know the same thing — it is what
# stops a caller's opt-out landing on top of a `manual` row and inheriting its
# deletability — and it cannot import this module: `dnc` normalises through
# `ingest.service`, which imports `compliance.service`, so the arrow only goes one way.
REMOVABLE_SOURCES = DNC_REMOVABLE_SOURCES


def is_removable(*, scope: str, source: str | None) -> bool:
    """The ONE definition of "may this be undone here". `list_entries` renders it as a
    flag and `remove_entry` enforces it; if the two computed it separately, the list
    would eventually offer a button the endpoint refuses — which is how a UI teaches
    someone that our compliance rules are a bug."""
    return scope != "global" and source in REMOVABLE_SOURCES


async def remove_entry(session: AsyncSession, *, entry_id: UUID) -> Removal:
    """Delete one hand-added tenant entry. Returns the audit row's payload.

    Deliberately NOT an admin-realm route. It cannot be one: `admin:tenants` is a
    MUTATING permission, and D-22 refuses mutating permissions while impersonating —
    so an admin-realm principal reaching a tenant's suppression list has either no
    tenant GUC (RLS: zero rows) or a read-only one. A route only ops could call would
    be a route nobody could call.
    """
    row = (
        await session.execute(
            text("SELECT scope, source, phone_e164 FROM dnc_list WHERE id = :id"),
            {"id": entry_id},
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
    return Removal(source=str(source), subject_ref=subject_ref(row[2]))


async def add_global_numbers(
    session: AsyncSession, *, raw_numbers: list[str], source: str
) -> AddResult:
    """Suppress numbers for EVERY tenant. Ops only; the session must carry no tenant GUC.

    Mirrors `add_numbers` deliberately — same counts, same normalization, same
    read-then-insert — because the two are one operation at two scopes and a second
    shape would be a second set of edge cases to get right. Three things differ:

    - the source vocabulary is `GLOBAL_SOURCES`, not `SOURCES`;
    - the dedupe read looks at `tenant_id IS NULL` only. A number a tenant already
      suppressed for itself is NOT already globally suppressed, and reporting it as
      such would silently decline to write the stronger row;
    - the conflict target is the PARTIAL unique index on `(phone_e164) WHERE tenant_id
      IS NULL`, added by migration `a1c8e40f27b9`. It has to be: the table's
      `UNIQUE (tenant_id, phone_e164)` never constrained global rows at all, because
      Postgres treats NULLs as distinct in a unique index, so `ON CONFLICT (tenant_id,
      phone_e164)` on a global insert matches nothing and every retry would have added
      another identical row.
    """
    if source not in GLOBAL_SOURCES:
        raise ProblemError.business_rule(
            "dnc_unknown_global_source",
            "That is not a recognised reason for suppressing a number platform-wide.",
            remediation=f"Use one of: {', '.join(GLOBAL_SOURCES)}.",
        )

    normalized: list[str] = []
    malformed = 0
    for raw in raw_numbers:
        e164 = normalize_phone(raw)
        if e164 is None:
            malformed += 1
            continue
        normalized.append(e164)
    unique = list(dict.fromkeys(normalized))
    if not unique:
        return AddResult(added=0, already_suppressed=0, malformed=malformed)

    existing = {
        row[0]
        for row in (
            await session.execute(
                text(
                    "SELECT phone_e164 FROM dnc_list "
                    "WHERE phone_e164 = ANY(:phones) AND tenant_id IS NULL"
                ),
                {"phones": unique},
            )
        ).all()
    }
    fresh = [phone for phone in unique if phone not in existing]

    if fresh:
        await session.execute(
            text(
                "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source, added_at, "
                "created_at) VALUES (:id, NULL, :phone, 'global', :source, now(), now()) "
                "ON CONFLICT (phone_e164) WHERE tenant_id IS NULL DO NOTHING"
            ),
            [{"id": uuid7(), "phone": phone, "source": source} for phone in fresh],
        )
        # D-428(b), and `tenant_id=None` is load-bearing rather than absent: a global
        # entry outranks every tenant's own list, so the recall has to reach every
        # tenant's queue rather than one.
        await enqueue_dnc_recall(session, tenant_id=None, phones=fresh)

    # Counts only (hard rule 6), and no tenant id — there isn't one.
    log.info("dnc_global_added", extra={"added": len(fresh), "source": source})
    return AddResult(
        added=len(fresh),
        already_suppressed=len(unique) - len(fresh),
        malformed=malformed,
    )


async def list_global_entries(session: AsyncSession, *, limit: int = 100) -> list[DncEntryView]:
    """The platform-wide list, newest first — numbers in full (D-436).

    A separate query from `list_entries` rather than a flag on it: that one runs on a
    tenant session and returns "this tenant's rows plus the global ones", which is the
    right answer for a client and the wrong one for an operator auditing what we block
    for everybody.
    """
    rows = (
        await session.execute(
            text(
                "SELECT id, phone_e164, scope, source, added_at FROM dnc_list "
                "WHERE tenant_id IS NULL ORDER BY added_at DESC, id DESC LIMIT :n"
            ),
            {"n": min(limit, MAX_LIST)},
        )
    ).all()
    return [
        DncEntryView(
            id=row[0],
            phone_e164=row[1],
            scope=row[2],
            source=row[3],
            added_at=row[4],
            # False for every row here, by `is_removable`'s definition. Rendered anyway
            # rather than hardcoded, so the ops list and the client list answer the
            # question with the same function.
            removable=is_removable(scope=row[2], source=row[3]),
        )
        for row in rows
    ]


async def remove_global_entry(session: AsyncSession, *, entry_id: UUID) -> Removal:
    """Lift one platform-wide suppression. Ops only. Returns the audit row's payload.

    A separate function from `remove_entry` and NOT a relaxation of it: that one refuses
    global rows by name (`dnc_global_entry`) and must keep doing so, because the account
    a number was suppressed against is exactly the account that must not be able to lift
    it. This one only ever touches `tenant_id IS NULL`, so an operator cannot reach a
    tenant's own entry through it either — the mistake in both directions is unreachable
    rather than merely discouraged.

    A regulator instruction genuinely gets withdrawn and a number blocked by mistake has
    to be recoverable, so the row is deletable; `audit_log` is where the history of both
    lives (this table is not append-only, and `remove_entry` already deletes). It carries
    the same `Removal` tombstone as `remove_entry` for the same reason, and more urgently:
    the entry a `regulator` source names is the one whose release most needs to be
    answerable to the regulator that asked for it.
    """
    row = (
        await session.execute(
            text("SELECT source, phone_e164 FROM dnc_list WHERE id = :id AND tenant_id IS NULL"),
            {"id": entry_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Global DNC entry")
    result = await session.execute(
        text("DELETE FROM dnc_list WHERE id = :id AND tenant_id IS NULL"), {"id": entry_id}
    )
    if rowcount_of(result) != 1:
        # RLS refusing the write looks exactly like this. Do not report success.
        raise ProblemError.not_found("Global DNC entry")
    return Removal(source=str(row[0]), subject_ref=subject_ref(row[1]))


__all__ = [
    "GLOBAL_SOURCES",
    "MAX_LIST",
    "MAX_NUMBERS_PER_ADD",
    "REMOVABLE_SOURCES",
    "SOURCES",
    "AddResult",
    "CheckResult",
    "DncEntryView",
    "Removal",
    "add_global_numbers",
    "add_numbers",
    "check_number",
    "is_removable",
    "list_entries",
    "list_global_entries",
    "remove_entry",
    "remove_global_entry",
]
