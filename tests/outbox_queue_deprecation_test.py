"""`outbox_messages.queue` is on its way out, and nothing in `apps/` writes it (D-217).

The column was written by six call sites with `"notifications"` or `"default"`, selected
by `claim_outbox_batch`, and READ BY NOTHING: `dispatch_outbox` published without it and
`WorkerSettings` sets no `queue_name`, so every message landed on arq's one default queue
regardless. It read as routing and routed nothing — the shape that makes an operator
believe notifications are isolated from CRM deliveries when the two are sharing one
worker's ten slots.

P6.8/D-162 removed the caller's CHOICE. **This file now pins the release that removes the
VALUE**, which is hard rule 8's first step towards the drop: no statement in `apps/` names
the column, `OutboxMessageRow` no longer carries it, and migration `b7e4c1a90d38` gives
the column a server default so an `INSERT` that omits it is legal — the property that lets
the old image keep working through `docs/DEPLOYMENT.md` §4b's swap gap.

It still does NOT pin the column's existence. `ALTER TABLE outbox_messages DROP COLUMN
queue` is step 2, in the next release, with no code change beside it; a test that forbade
the drop would be a test against the rule it is enforcing.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from apps.api.reliability import service as reliability

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("apps",)
MIGRATION = (
    REPO_ROOT
    / "alembic"
    / "versions"
    / "b7e4c1a90d38_the_outbox_queue_column_stops_being_written.py"
)


def test_a_caller_cannot_choose_a_queue() -> None:
    """The parameter is gone from the signature, which is what makes the column honest.

    Asserted on the SIGNATURE rather than on behaviour because the defect was never that
    a wrong value was written — it was that a value was written at all, by a caller who
    reasonably believed it decided something.
    """
    params = inspect.signature(reliability.enqueue_outbox).parameters

    assert "queue" not in params, (
        "enqueue_outbox takes a queue again. Nothing routes on it: dispatch_outbox "
        "publishes without it and WorkerSettings sets no queue_name, so a caller "
        "choosing one is choosing nothing while believing otherwise (D-162)."
    )
    assert "job" in params and "payload" in params, "the two arguments that DO decide"


def test_no_statement_in_the_service_writes_the_column() -> None:
    """The INSERTs stopped naming it, which is what "stops writing a column" means.

    Asserted on both writers rather than on one: `enqueue_outbox` and
    `enqueue_outbox_once` are separate statements and a revert would plausibly touch
    only the one a reader was looking at.
    """
    for writer in (reliability.enqueue_outbox, reliability.enqueue_outbox_once):
        source = inspect.getsource(writer)
        assert "queue" not in source.split('"""')[-1], (
            f"{writer.__name__} names `queue` in its statement again. Nothing routes on "
            "it and migration b7e4c1a90d38 defaults it; naming it re-opens the column "
            "the drop is waiting on (D-217)."
        )


def test_the_claim_does_not_read_the_column_either() -> None:
    """A column nobody writes and something still SELECTs is half-retired.

    `OutboxMessageRow.queue` was the last reader — carried "so the column's one consumer
    is where a filter would go" if a second fleet ever arrived. D-162 closed the other
    way, so the field went with the write.
    """
    assert not hasattr(reliability.OutboxMessageRow, "__annotations__") or (
        "queue" not in reliability.OutboxMessageRow.__annotations__
    ), "OutboxMessageRow carries `queue` again; nothing branches on it (D-217)"
    claim = inspect.getsource(reliability.claim_outbox_batch)
    assert "o.queue" not in claim, "the claim selects the column again (D-217)"


def test_the_database_default_and_the_constant_still_agree() -> None:
    """One value, two homes, and they may not drift while both exist.

    `OUTBOX_FLEET` survives the write removal because the migration's default is the same
    string, and a default in a migration silently disagreeing with the constant a reader
    finds in the service is how a retired column comes back to life wearing a new value.
    Both go in step 2's change.
    """
    assert reliability.OUTBOX_FLEET == "default"
    migration = MIGRATION.read_text(encoding="utf-8")
    assert f'FLEET = "{reliability.OUTBOX_FLEET}"' in migration, (
        "the migration's default no longer matches `OUTBOX_FLEET`"
    )
    assert "SET DEFAULT" in migration, (
        "the migration stopped defaulting the column, so an INSERT that omits it — which "
        "is now every INSERT — would violate NOT NULL"
    )


def test_a_reader_meets_the_warning_where_they_meet_the_column() -> None:
    """The deferral has to be legible AT THE DECLARATION, not only beside the constant.

    D-162 is a real decision and the audit agrees with it (R-7), so the fix is not a
    router — it is that nobody reaches `outbox_messages.queue` believing it routes. The
    argument used to live only on `OUTBOX_FLEET` in `service.py`, which a reader browsing
    the model never opens; the column declaration and the claimed row that carries it now
    both name D-162 and both name what closes it. Asserted rather than trusted, because a
    comment is exactly the thing a later edit removes without noticing.
    """
    models_source = Path(reliability.__file__).with_name("models.py").read_text(encoding="utf-8")
    declaration = models_source.split("queue: Mapped[str]")[0]
    preamble = declaration[-1800:]
    assert "D-217" in preamble, "the column declaration does not name the decision retiring it"
    assert "ROUTES NOTHING" in preamble, "and does not say the one thing a reader must know"
    assert "DROP COLUMN" in preamble, (
        "the declaration no longer names step 2, so the next reader cannot tell a column "
        "awaiting its drop from one that is simply unused"
    )


def test_no_call_site_still_passes_a_queue() -> None:
    """The sweep, because the signature only stops the callers that are recompiled.

    A `queue=` on an `enqueue_outbox` call is now a TypeError at runtime rather than a
    silent no-op, which is an improvement — but a scan says so at review time instead of
    at 3am, and it also catches the constants (`TENANT_ERASURE_QUEUE`, `DELETION_QUEUE`)
    whose whole content was the string `"default"` and which existed only to be passed
    here.

    `reliability/service.py` USED TO BE EXEMPT from this sweep, on the grounds that "the
    writer names the column in its INSERT; that is the point". It no longer does, so the
    exemption went with it — the sweep now covers the file that would most plausibly
    re-introduce the write.
    """
    offenders: list[str] = []
    for root in SCAN_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            if "__pycache__" in path.parts or path.name.endswith("_test.py"):
                continue
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith("#:"):
                    continue
                if stripped.startswith("queue=") or "_QUEUE = " in stripped:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno} → {stripped}")
    assert not offenders, (
        "a queue argument or a queue-name constant came back, and nothing routes on "
        f"either: {offenders}. See D-162 — the column is retiring, not gaining callers."
    )
