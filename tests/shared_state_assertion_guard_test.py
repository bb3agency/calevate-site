"""A test may not count a globally-visible table without saying why that is safe.

THE DEFECT CLASS, and it has produced four members that we know of:

  * `outbox_backpressure_test` asserted `during.deferred - before.deferred == 3` and
    `after.deferred == before.deferred` against fleet-wide counters, while its own setup
    ran the REAL claim — which leases up to `OUTBOX_BATCH` of whatever other suites had
    queued.
  * a hard-rule-6 log scan matched a phone-shaped run of digits inside a uuid7 tenant id
    (0.245% per id, ~9% per run over ~40 ids).
  * `platform_audit_test` took `count(*) FROM organizations` before and after a webhook
    and asserted the delta was zero — under `admin_session`, which is unscoped by design,
    so any suite creating a tenant in that window failed it.
  * `audit_chain_concurrency_test` asserted `entries_checked == count(*) FROM audit_log`
    with the count read AFTER the walk, on the one table every suite in this repo appends
    to. Its own sibling forty lines above gets this right and explains why.

Every one was green on a quiet box and red under load, which is the worst failure shape a
test suite has: it teaches people to re-run rather than to read. And every one of them was
introduced by somebody who knew the rule — this repo's suites share ONE Postgres and ONE
Redis, and the header of half of them says so.

WHY A REGISTRY RATHER THAN A CLEVERER CHECK. The tempting version infers safety: trace the
counted value to its assertion and allow `>=`, `<=` and `== 0`. That is decidable for
today's seven sites and wrong in general — `platform_state == 1` is safe because a CHECK
constraint makes it a singleton, which no amount of local analysis can see, and the
`platform_audit` delta was TWO statements apart with a network round trip between them. A
registry cannot be fooled and cannot be subtly wrong; the cost is one line of prose per
site, written at the moment somebody is actually thinking about it. It is the same shape
as `db/registry.RLS_EXEMPT_TENANT_COLUMNS`, for the same reason.

WHAT IS NOT COVERED, said plainly. This sees whole-table COUNTS on tables no tenant policy
scopes. It does not see: counts on tenant tables taken from an `admin_session` (RLS is what
makes those safe, and a session type is not decidable from a SQL string), Redis keyspace
assertions, or a count that is correctly scoped but compared against a number derived from
a shared resource anyway. The registry is a floor, not a proof.
"""

from __future__ import annotations

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent

#: Tables a plain SELECT reads in FULL from any session — no `tenant_id`, or an RLS
#: exemption that makes the read global (`db/registry.RLS_EXEMPT_TENANT_COLUMNS` is the
#: authority for the second group). A count on one of these is a count of every suite's
#: rows, not this suite's.
GLOBALLY_VISIBLE = (
    "admin_users",
    "audit_log",
    "engine_agent_routes",
    "idempotency_records",
    "organizations",
    "outbox_messages",
    "platform_ai_spend",
    "platform_config_version",
    "platform_secrets",
    "platform_settings",
    "platform_state",
    "reserved_slugs",
    "webhook_deliveries",
    "webhook_inbox_events",
)

#: (test file, table) -> why an unscoped count of it is safe under parallel suites.
#:
#: Adding an entry is the point: it is a sentence somebody has to be able to write. If the
#: honest sentence is "it isn't, but it usually passes", the fix is to scope the query.
UNSCOPED_COUNT_REASONS: dict[tuple[str, str], str] = {
    ("admin_security_test.py", "organizations"): (
        "asserted as `orgs >= 1` — a floor. Other suites can only make it larger, and "
        "the property is that the admin realm can enumerate clients at all. The "
        "assertions that matter in the same block are `== 0` on tenant tables, which "
        "is the RLS fail-closed direction: another suite's rows cannot make a hidden "
        "table visible."
    ),
    ("audit_chain_concurrency_test.py", "audit_log"): (
        "both sites count BEFORE `verify_chain` and compare with `>=`. The ledger only "
        "ever grows, so a concurrent append can only make the walk's coverage exceed "
        "the count — never fall short. Reading the count AFTER the walk and asserting "
        "equality is exactly the defect this file's second site used to carry."
    ),
    ("client_health_test.py", "organizations"): (
        "`orgs >= 1`, a floor, beside `== 0` fail-closed assertions on tenant tables. "
        "Same shape as admin_security_test.py."
    ),
    ("ops_hold_queue_test.py", "organizations"): (
        "`orgs >= 1`, a floor, beside `== 0` on `kyc_records` and "
        "`first_campaign_reviews`. Another suite's tenant can only raise the floor, and "
        "the zero assertions are the RLS fail-closed direction, which a concurrent "
        "writer cannot invert."
    ),
    ("rls_test.py", "organizations"): (
        "`== 0` under `untenanted_session`, which is the whole point of the test: with "
        "no GUC set, RLS must hide EVERY row including other suites'. A concurrent "
        "writer cannot make this pass falsely — it can only produce rows that must "
        "still be hidden."
    ),
    ("tm_registration_test.py", "platform_state"): (
        "`== 1` on a table `ck_platform_state_singleton` constrains to one row. No "
        "suite can add a second, so the count is not shared state in any meaningful "
        "sense — asserting it is asserting the constraint holds."
    ),
}

#: `count(*) FROM <table>`; the `WHERE` check below is what decides scoping.
_COUNT = re.compile(r"count\(\*\)\s+FROM\s+(\w+)", re.IGNORECASE)

#: How far past the FROM to look for a scoping predicate. Generous, because these queries
#: are string-concatenated across several source lines.
_PREDICATE_WINDOW = 280


def _code_only(source: str) -> str:
    """Blank out comment lines, keeping line count so reported numbers stay usable.

    Written after this guard flagged the PROSE of a comment explaining a fix it had just
    prompted — a check that reads its own documentation as a violation is a check people
    turn off.
    """
    return "\n".join("" if line.lstrip().startswith("#") else line for line in source.split("\n"))


def _unscoped_counts(path: Path) -> list[tuple[str, int]]:
    source = _code_only(path.read_text(encoding="utf-8"))
    found: list[tuple[str, int]] = []
    for match in _COUNT.finditer(source):
        table = match.group(1)
        if table not in GLOBALLY_VISIBLE:
            continue
        if re.search(r"\bWHERE\b", source[match.end() : match.end() + _PREDICATE_WINDOW], re.I):
            continue
        found.append((table, source[: match.start()].count("\n") + 1))
    return found


def test_every_unscoped_count_of_a_shared_table_is_registered_with_a_reason() -> None:
    unregistered: list[str] = []
    for path in sorted(TESTS.glob("*_test.py")):
        if path.name == Path(__file__).name:
            continue
        for table, line in _unscoped_counts(path):
            if (path.name, table) not in UNSCOPED_COUNT_REASONS:
                unregistered.append(f"{path.name}:{line} counts all of `{table}`")
    assert not unregistered, (
        "these count a table every other suite also writes to, with no predicate "
        "scoping the count to this test's own rows:\n  "
        + "\n  ".join(unregistered)
        + "\n\nThe suites share one Postgres. Either scope the query to rows this test "
        "created, or add an entry to UNSCOPED_COUNT_REASONS saying why the assertion "
        "survives another suite writing to that table concurrently. Green on a quiet "
        "box and red under load is the worst shape a test can have."
    )


def test_the_registry_has_no_entries_for_counts_that_are_gone() -> None:
    """A stale exemption is a hole nobody is looking through any more.

    The same rule `RLS_EXEMPT_TENANT_COLUMNS` gets from `check_rls_coverage`: registry
    drift is checked in BOTH directions, or the list grows monotonically and stops
    describing the tree.
    """
    live = {
        (path.name, table)
        for path in TESTS.glob("*_test.py")
        for table, _line in _unscoped_counts(path)
    }
    stale = sorted(
        f"{name}:{table}" for name, table in UNSCOPED_COUNT_REASONS if (name, table) not in live
    )
    assert not stale, (
        f"UNSCOPED_COUNT_REASONS exempts counts that no longer exist: {stale}. "
        "Delete the entries — an exemption outliving its subject is how the next one "
        "gets waved through under a reason written for something else."
    )


def test_every_reason_is_a_sentence_rather_than_a_shrug() -> None:
    """The registry's value is the thinking, not the key. A one-word reason is an
    exemption nobody had to justify."""
    for (name, table), reason in UNSCOPED_COUNT_REASONS.items():
        assert len(reason) >= 80, f"{name}:{table} has a reason too short to be one: {reason!r}"
