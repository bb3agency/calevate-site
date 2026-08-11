"""Reconcile the double-credits a check-then-write race left on `credit_ledger`.

Run (READ ONLY, the default):

    uv run python -m scripts.reconcile_credit_ledger
    uv run python -m scripts.reconcile_credit_ledger --tenant <uuid>

Write the corrections:

    uv run python -m scripts.reconcile_credit_ledger --apply

WHAT HAPPENED. The top-up and usage writers used to run their dedupe SELECT before
taking `lock_tenant_credits`, so two concurrent writers both read "not charged yet" and
both appended. The hole is closed; the residue is not. A schema audit tried to add a
partial unique index on `(tenant_id, ref)` and could not, because the data still
violates it: `(tenant_id, ref, reason)` groups holding more than one entry, each extra
entry a payment credited twice or a call debited twice.

WHY THIS SCRIPT DOES NOT DELETE ANYTHING. Hard rule 4: `credit_ledger` is INSERT-only,
and a database trigger enforces it. That is not an obstacle to route around — the rows
ARE the evidence that the race happened, and a ledger somebody can tidy is not evidence
of anything. So the balance is repaired the way every other mistake on an append-only
ledger is repaired: by appending ONE compensating entry per duplicated group.

THE COMPENSATING ENTRY.

    reason  'adjustment'  — the only value of the four (`ck_credit_ledger_reason_enum`)
                            that is honest here. Not 'refund': no money went back to
                            the client, this is a bookkeeping correction of OUR error.
    delta   -(surplus)    — the sum of every entry in the group EXCEPT the first. The
                            first entry is the real one; the rest are the race's output.
                            A duplicated top-up nets a debit, a duplicated usage charge
                            nets a credit. NUMERIC throughout (hard rule 7).
    ref     dedupe:<reason>:<original ref>:<fingerprint>
    meta    the kept entry's id, the ids this entry cancels, the surplus as a STRING.

The `ref` is doing three jobs at once and each one constrains it:

1. **Traceability.** It carries the reason and the reference of the group it corrects,
   so a reader who finds it can go straight to the two rows that caused it, and `meta`
   names those rows by id.
2. **It must NOT be the duplicated reference itself.** Reusing `UTR-900011` would turn
   a pair into a triple and keep the unique index just as unbuildable as before.
3. **It is the idempotency key.** The fingerprint is a digest of the exact entry ids
   being cancelled, so the SAME surplus always derives the SAME ref — a re-run's
   lookup hits the row the first run wrote and writes nothing — while a NEW duplicate
   appearing later derives a DIFFERENT ref and gets its own correction for its own
   amount, never a second cancellation of an amount already cancelled.

IDEMPOTENCY IS THE WHOLE GAME, because the defect being repaired is itself a double
write. Two guards, both taken with `lock_tenant_credits` ALREADY HELD — the lock comes
before the lookups, which is exactly the ordering whose absence caused the duplicates:

- the group's prior corrections are read out of `meta` and their entry ids subtracted,
  so nothing is compensated twice even across runs, and
- the derived `ref` is looked up directly, so a correction can never be appended twice
  even if `meta` were ever unreadable.

Two operators running this at once therefore write one entry between them, and the
second one's re-scan happens inside the lock the first one holds.

Every write goes through `billing.service.record_entry`. It owns the balance
arithmetic, the `clock_timestamp()` ordering and the advisory lock; a hand-rolled
INSERT here would be a second, divergent definition of what a ledger entry is.

`allow_negative=True`: a tenant who was over-credited may already have spent the
phantom rupees. Their balance is then genuinely negative and the ledger must say so —
refusing to record the correction would leave a wallet that reads richer than it is,
which is the exact condition this script exists to end.

THE INDEX (settled — lift this verbatim into a migration).

Five attempts have now been made to add a unique index here. The first four were all on
`(tenant_id, ref)` and all correctly refused. The key was wrong, and the shape below is
what the evidence supports. Every claim in it was measured against a database that had
just run the suite, by snapshotting the violating groups, running, diffing, and pulling
the rows — not by reading code.

    CREATE UNIQUE INDEX CONCURRENTLY ux_credit_ledger_tenant_reason_ref
        ON credit_ledger (tenant_id, reason, ref)
     WHERE ref IS NOT NULL
       AND reason IN ('topup', 'usage', 'adjustment')
       AND occurred_at >= '<LEDGER_UNIQUE_INDEX_CUTOFF>'::timestamptz;

`reason` IS IN THE KEY, and this is the finding the four refusals missed. `ref` is not
one namespace: a `usage` row carries a call id, a `topup` row carries whatever the bank
printed, and `TopUpIn.payment_ref` accepts any string of 3 to 120 characters — a 36-char
UUID among them. The system does not prevent that collision, it TOLERATES it, in three
places deliberately: `find_topup` scopes to `reason = 'topup'`, `charge_for_call` scopes
its dedupe to `reason = 'usage'`, and `scan_tenant` above groups by `(ref, reason)`. A
`UNIQUE (tenant_id, ref)` would turn a tolerated, defended-against collision into an
IntegrityError on the top-up route — a 500 on a valid payment. That is strictly worse
than the duplicates it would catch, and it is why the fifth attempt changed the key
instead of the predicate.

THE PREDICATE, clause by clause:

- `ref IS NOT NULL` — a null ref is "no idempotency key", not a key that collides.
- `reason IN (...)` — the three reasons that have an idempotency contract TODAY.
  `refund` is left out on purpose: it has no writer in `apps/` at all, all 527 refund
  rows carry a NULL ref, and the obvious future shape — several partial refunds against
  one payment reference — is legitimate and would fire the index. Excluding it costs
  nothing now (`ref IS NOT NULL` already excludes every one of them) and avoids
  designing a constraint against a feature nobody has written yet.
- `occurred_at >= <cutoff>` — the grandfather line. Hard rule 4 forbids deleting the
  pre-fix residue, and this script does not delete it either: it appends a compensating
  entry and the duplicate rows REMAIN. So the residue is permanent, and a partial index
  is the only shape that can ever build. Verified: the same index without the cutoff
  fails on `(…, topup, UTR-RACE-0)`.

BEFORE IT CAN LAND, three things, none of them optional:

1. **Move the cutoff to your own authoring instant** and re-verify the build. The
   constant below is a placeholder; a cutoff is only honest if it sits after every
   duplicate on the target database and at or before deploy.
2. **Delete the two tripwires in the same commit.** `schema_hardening_2_test.py::
   test_the_ledger_still_accepts_the_double_credit_its_own_fixtures_write` and
   `schema_hardening_3_test.py::test_the_reconcilers_over_charge_fixture_still_mints_a_
   post_cutoff_violation` assert the index is ABSENT, and each mints a duplicate pair
   per run to prove it. Measured over a full suite run: they are the ONLY writers that
   put a violation after the cutoff. Both docstrings already say to delete them here.
   Also drop the note in `billing/models.CreditLedgerEntry` that points at them.
3. **`CONCURRENTLY`, outside a transaction.** A plain `CREATE UNIQUE INDEX` takes a
   SHARE lock and blocks every credit write for the length of the build, on a table the
   post-call pipeline writes to continuously. Alembic runs migrations in a transaction,
   so this needs `with op.get_context().autocommit_block():` — and note that a
   CONCURRENTLY build can fail and leave an INVALID index behind, which the downgrade
   must `DROP INDEX IF EXISTS` unconditionally.

WHAT THE INDEX DOES NOT BUY. Every writer that could produce a duplicate key is already
serialized by `lock_tenant_credits`, and `tests/credit_ledger_uniqueness_test.py` pins
that. The index is a backstop against a future writer that forgets the lock, not a fix
for a live defect — so it is worth having, and not worth breaking a money route for.

DEV DATABASES. This repository's shared dev database carries duplicates the suite wrote
before the fixtures were pinned, including some stamped in 2027 by a test that has since
been rewritten not to write them. Those rows cannot be removed (hard rule 4), so the
build will fail there against any sane cutoff. `make db-reset` before verifying locally;
production has never run a test and has none of them.

PII: the output is ids and rupee amounts. No organization name, no phone number
(hard rule 6) — a reconciliation report gets pasted into tickets and chat.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final, Literal
from uuid import UUID

from apps.api.billing.service import (
    get_balance,
    lock_tenant_credits,
    record_entry,
    to_paise,
)
from apps.api.db.session import admin_session, tenant_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# `reason` is constrained to four values by `ck_credit_ledger_reason_enum`, so what this
# entry IS lives in the ref prefix and in `meta.kind` rather than in a fifth reason.
COMPENSATION_REASON: Final = "adjustment"
DUPLICATE_REF_PREFIX: Final = "dedupe"
META_KIND: Final = "duplicate_ledger_entry"

# The grandfather line for `ux_credit_ledger_tenant_reason_ref` (see THE INDEX, above).
# Entries at or after it are covered by the unique index; everything before it is the
# residue this script compensates and hard rule 4 forbids removing.
#
# It lives HERE, not only in the migration, because two other places have to agree with
# it and would otherwise each carry their own copy of the date: the reconciliation
# suite's residue seed (which must stay strictly BEFORE it, forever) and the test that
# asserts the index still builds. One constant, three readers.
LEDGER_UNIQUE_INDEX_CUTOFF: Final = datetime(2026, 8, 12, tzinfo=UTC)

# Enough digest to make two different id-sets colliding a non-event, short enough that
# the ref stays readable in a terminal next to the reference it corrects.
_FINGERPRINT_CHARS: Final = 12

CorrectionStatus = Literal["pending", "written", "already_reconciled", "nothing_to_write"]


# --- what the detector found ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    """One `(tenant_id, ref, reason)` that holds more than one entry.

    `entry_ids` and `deltas` are ordered oldest first — the same order
    `_newest_balance` reads the ledger in — so entry[0] is the write that was supposed
    to happen and everything after it is the race's output.
    """

    tenant_id: UUID
    ref: str
    reason: str
    entry_ids: tuple[UUID, ...]
    deltas: tuple[Decimal, ...]

    @property
    def kept_entry_id(self) -> UUID:
        return self.entry_ids[0]

    @property
    def duplicate_entry_ids(self) -> tuple[UUID, ...]:
        return self.entry_ids[1:]

    @property
    def surplus_inr(self) -> Decimal:
        """What the duplication is worth: the signed amount the balance is overstated
        by. Positive for a double top-up, negative for a double charge."""
        return sum(self.deltas[1:], Decimal("0"))

    def delta_of(self, entry_id: UUID) -> Decimal:
        return self.deltas[self.entry_ids.index(entry_id)]


@dataclass(frozen=True, slots=True)
class Correction:
    """One compensating entry — planned, written, or found already present."""

    group: DuplicateGroup
    cancels: tuple[UUID, ...]
    delta_inr: Decimal
    ref: str
    status: CorrectionStatus


@dataclass(frozen=True, slots=True)
class TenantReport:
    tenant_id: UUID
    corrections: tuple[Correction, ...]
    balance_inr: Decimal
    balance_after_inr: Decimal

    @property
    def groups(self) -> int:
        return len(self.corrections)

    @property
    def duplicate_entries(self) -> int:
        return sum(len(c.group.duplicate_entry_ids) for c in self.corrections)

    @property
    def surplus_inr(self) -> Decimal:
        return sum((c.group.surplus_inr for c in self.corrections), Decimal("0"))


@dataclass(frozen=True, slots=True)
class Report:
    applied: bool
    scanned_tenants: int
    tenants: tuple[TenantReport, ...]

    @property
    def corrections(self) -> tuple[Correction, ...]:
        return tuple(c for t in self.tenants for c in t.corrections)

    @property
    def groups(self) -> int:
        return len(self.corrections)

    @property
    def duplicate_entries(self) -> int:
        return sum(t.duplicate_entries for t in self.tenants)

    @property
    def surplus_inr(self) -> Decimal:
        return sum((t.surplus_inr for t in self.tenants), Decimal("0"))

    @property
    def written(self) -> int:
        return sum(1 for c in self.corrections if c.status == "written")

    @property
    def pending(self) -> int:
        return sum(1 for c in self.corrections if c.status == "pending")


# --- the detector --------------------------------------------------------------


async def scan_tenant(session: AsyncSession, tenant_id: UUID) -> list[DuplicateGroup]:
    """Every duplicated `(ref, reason)` on one wallet. Reads only.

    Grouped by reason as well as ref because they are different facts: a payment
    reference credited twice and a call id debited twice are corrected in opposite
    directions, and `charge_for_call` / the top-up route already treat the two
    namespaces as separate (`credit_routes._find_topup` scopes its lookup by reason).

    The session must already be scoped to this tenant — RLS is what keeps one wallet's
    refs from being read while answering for another.
    """
    rows = (
        await session.execute(
            text(
                "SELECT ref, reason, "
                "  array_agg(id ORDER BY occurred_at, id), "
                "  array_agg(delta ORDER BY occurred_at, id) "
                "FROM credit_ledger WHERE tenant_id = :tid AND ref IS NOT NULL "
                "GROUP BY ref, reason HAVING count(*) > 1 "
                "ORDER BY min(occurred_at), ref"
            ),
            {"tid": tenant_id},
        )
    ).all()
    return [
        DuplicateGroup(
            tenant_id=tenant_id,
            ref=str(row[0]),
            reason=str(row[1]),
            entry_ids=tuple(UUID(str(value)) for value in row[2]),
            deltas=tuple(Decimal(str(value)) for value in row[3]),
        )
        for row in rows
    ]


def compensation_ref(group: DuplicateGroup, cancels: tuple[UUID, ...]) -> str:
    """The compensating entry's own reference — traceable, distinct, content-addressed.

    Content-addressed over the entry ids being cancelled is what makes a second run a
    no-op: same surplus, same digest, same ref, and the lookup finds the row the first
    run wrote. It is also what stops a LATER duplicate from being folded into the
    correction that already exists — a different set of ids is a different ref and gets
    its own entry for its own amount.
    """
    digest = hashlib.sha256("\n".join(sorted(str(i) for i in cancels)).encode()).hexdigest()
    return f"{DUPLICATE_REF_PREFIX}:{group.reason}:{group.ref}:{digest[:_FINGERPRINT_CHARS]}"


def compensation_meta(group: DuplicateGroup, cancels: tuple[UUID, ...]) -> dict[str, Any]:
    """Ids and amounts. Amounts are strings: a rupee that goes into JSON as a number
    comes back out of some reader as a float (hard rule 7)."""
    return {
        "kind": META_KIND,
        "dedupe": {"ref": group.ref, "reason": group.reason},
        "kept_entry_id": str(group.kept_entry_id),
        "compensated_entry_ids": [str(i) for i in cancels],
        "surplus_inr": str(sum((group.delta_of(i) for i in cancels), Decimal("0"))),
        "script": "scripts/reconcile_credit_ledger.py",
    }


async def _already_compensated(session: AsyncSession, group: DuplicateGroup) -> set[UUID]:
    """The entry ids this group's existing corrections have already cancelled.

    MUST be called with `lock_tenant_credits` held: this is the check half of a
    check-then-write, and running it outside the lock is the precise mistake that
    produced the duplicates in the first place.
    """
    rows = (
        await session.execute(
            text(
                "SELECT meta FROM credit_ledger WHERE tenant_id = :tid AND reason = :reason "
                "AND meta -> 'dedupe' ->> 'ref' = :ref "
                "AND meta -> 'dedupe' ->> 'reason' = :group_reason"
            ),
            {
                "tid": group.tenant_id,
                "reason": COMPENSATION_REASON,
                "ref": group.ref,
                "group_reason": group.reason,
            },
        )
    ).all()
    cancelled: set[UUID] = set()
    for row in rows:
        meta = row[0] or {}
        for value in meta.get("compensated_entry_ids", []):
            cancelled.add(UUID(str(value)))
    return cancelled


async def _ref_exists(session: AsyncSession, tenant_id: UUID, ref: str) -> bool:
    """The second guard, on the key a unique index would enforce. Cheap, and it holds
    even for an entry whose `meta` a future migration reshaped."""
    found = (
        await session.execute(
            text("SELECT 1 FROM credit_ledger WHERE tenant_id = :tid AND ref = :ref LIMIT 1"),
            {"tid": tenant_id, "ref": ref},
        )
    ).first()
    return found is not None


async def plan_correction(session: AsyncSession, group: DuplicateGroup) -> Correction:
    """What this group still needs, given what has already been written for it."""
    cancelled = await _already_compensated(session, group)
    pending = tuple(i for i in group.duplicate_entry_ids if i not in cancelled)
    if not pending:
        return Correction(
            group=group,
            cancels=(),
            delta_inr=Decimal("0"),
            ref="",
            status="already_reconciled",
        )

    delta = -sum((group.delta_of(i) for i in pending), Decimal("0"))
    ref = compensation_ref(group, pending)
    if await _ref_exists(session, group.tenant_id, ref):
        return Correction(
            group=group, cancels=pending, delta_inr=delta, ref=ref, status="already_reconciled"
        )
    # `record_entry` returns early on a zero delta, so a group whose surplus nets to
    # nothing would be re-planned on every run forever. Name it instead.
    status: CorrectionStatus = "nothing_to_write" if delta == 0 else "pending"
    return Correction(group=group, cancels=pending, delta_inr=delta, ref=ref, status=status)


# --- the reconciler ------------------------------------------------------------


async def reconcile_tenant(tenant_id: UUID, *, apply: bool = False) -> TenantReport | None:
    """Scan one wallet and, when applying, append its corrections. None = nothing found.

    The whole tenant runs in ONE transaction under ONE advisory lock, so the scan, the
    idempotency lookups and the writes all see the same wallet: a top-up landing
    mid-run cannot make the correction disagree with the rows it was derived from.
    """
    async with tenant_session(tenant_id) as session:
        if apply:
            # Before the scan, not after: the plan is a read the write depends on.
            await lock_tenant_credits(session, tenant_id)

        groups = await scan_tenant(session, tenant_id)
        if not groups:
            return None

        balance_before = (await get_balance(session, tenant_id=tenant_id)).amount_inr
        corrections: list[Correction] = []
        for group in groups:
            correction = await plan_correction(session, group)
            if apply and correction.status == "pending":
                await record_entry(
                    session,
                    tenant_id=tenant_id,
                    delta=correction.delta_inr,
                    reason=COMPENSATION_REASON,
                    ref=correction.ref,
                    meta=compensation_meta(group, correction.cancels),
                    # The phantom credit may already be spent; a wallet that reads
                    # richer than it is, is the condition being ended here.
                    allow_negative=True,
                )
                correction = Correction(
                    group=correction.group,
                    cancels=correction.cancels,
                    delta_inr=correction.delta_inr,
                    ref=correction.ref,
                    status="written",
                )
            corrections.append(correction)

        outstanding = sum(
            (c.delta_inr for c in corrections if c.status in ("pending", "written")),
            Decimal("0"),
        )
        return TenantReport(
            tenant_id=tenant_id,
            corrections=tuple(corrections),
            balance_inr=balance_before,
            balance_after_inr=balance_before + outstanding,
        )


async def _all_tenant_ids() -> list[UUID]:
    """Every organization, through the one sanctioned enumeration surface.

    `admin_session` widens `USING` on `organizations` and nothing else, so the wallets
    themselves are still read one tenant at a time under that tenant's own RLS context.
    Soft-deleted organizations are included deliberately: their rows still block the
    unique index, and their balances are still wrong.
    """
    async with admin_session() as session:
        rows = (await session.execute(text("SELECT id FROM organizations ORDER BY id"))).all()
    return [UUID(str(row[0])) for row in rows]


async def reconcile(*, tenant_id: UUID | None = None, apply: bool = False) -> Report:
    """Dry run unless `apply=True`. The default writes nothing, anywhere."""
    targets = [tenant_id] if tenant_id is not None else await _all_tenant_ids()
    reports: list[TenantReport] = []
    for target in targets:
        found = await reconcile_tenant(target, apply=apply)
        if found is not None:
            reports.append(found)
    return Report(applied=apply, scanned_tenants=len(targets), tenants=tuple(reports))


# --- the operator's view -------------------------------------------------------


def _inr(amount: Decimal) -> str:
    return f"INR {to_paise(amount)}"


def format_report(report: Report) -> str:
    """Ids and amounts only — never a name, never a phone number (hard rule 6)."""
    mode = "APPLIED" if report.applied else "DRY RUN (nothing written)"
    lines = [
        f"credit_ledger reconciliation — {mode}",
        f"scanned {report.scanned_tenants} tenant(s); "
        f"{report.groups} duplicated (tenant_id, ref, reason) group(s) "
        f"across {len(report.tenants)} tenant(s); "
        f"{report.duplicate_entries} surplus entr(ies)",
        "",
    ]
    for tenant in report.tenants:
        lines.append(
            f"  tenant {tenant.tenant_id}  groups={tenant.groups}  "
            f"surplus={_inr(tenant.surplus_inr)}  "
            f"balance {_inr(tenant.balance_inr)} -> {_inr(tenant.balance_after_inr)}"
        )
        for correction in tenant.corrections:
            group = correction.group
            lines.append(
                f"      {group.reason}:{group.ref}  x{len(group.entry_ids)}  "
                f"surplus={_inr(group.surplus_inr)}  "
                f"{correction.status}  delta={_inr(correction.delta_inr)}"
            )
            lines.append(f"        keeps {group.kept_entry_id}")
            for entry_id in group.duplicate_entry_ids:
                lines.append(f"        cancels {entry_id}")
            if correction.ref:
                lines.append(f"        ref {correction.ref}")
    if report.tenants:
        lines += [
            "",
            f"  total surplus {_inr(report.surplus_inr)} — the amount the affected "
            "balances are overstated by",
        ]
    if report.applied:
        lines.append(f"  wrote {report.written} compensating entr(ies)")
    elif report.pending:
        lines.append(
            f"  {report.pending} compensating entr(ies) WOULD be written — re-run with --apply"
        )
    else:
        lines.append("  nothing to write")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="reconcile_credit_ledger",
        description=(
            "Find (tenant_id, ref, reason) groups holding more than one credit_ledger "
            "entry and append one compensating entry per group. Reports only unless "
            "--apply is passed."
        ),
    )
    # Opt IN to writing. A money-moving script whose default is to write is a footgun,
    # and this one runs against every tenant when no --tenant is given.
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually append the compensating entries (default: dry run)",
    )
    parser.add_argument(
        "--tenant",
        type=UUID,
        default=None,
        help="reconcile one tenant instead of scanning every organization",
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = await reconcile(tenant_id=args.tenant, apply=args.apply)
    print(format_report(report))
    return 0


if __name__ == "__main__":
    # Windows defaults to ProactorEventLoop, which psycopg's async mode cannot use —
    # the same override `scripts/seed.py` and tests/conftest.py apply.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
