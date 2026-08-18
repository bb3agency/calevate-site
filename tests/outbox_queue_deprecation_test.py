"""`outbox_messages.queue` says one thing today, and it is the truth (P6.8, D-162).

The column was written by six call sites with `"notifications"` or `"default"`, selected
by `claim_outbox_batch`, and READ BY NOTHING: `dispatch_outbox` published without it and
`WorkerSettings` sets no `queue_name`, so every message landed on arq's one default queue
regardless. It read as routing and routed nothing — the shape that makes an operator
believe notifications are isolated from CRM deliveries when the two are sharing one
worker's ten slots.

This file pins step 1 of the two-step retirement (hard rule 8): the caller can no longer
choose a value, so the column can no longer disagree with reality. It does NOT pin the
column's existence — dropping it is step 2, in a later release, and a test that forbade
the drop would be a test against the rule it is enforcing.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from apps.api.reliability import service as reliability

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("apps",)


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


def test_the_written_value_has_exactly_one_source() -> None:
    """One constant, named, so "which fleet is this?" has a single answer a reviewer can
    find — and so step 2 has one line to delete rather than six."""
    assert reliability.OUTBOX_FLEET == "default"
    source = inspect.getsource(reliability.enqueue_outbox)
    assert "OUTBOX_FLEET" in source


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
    assert "D-162" in preamble, "the column declaration does not name the decision that defers it"
    assert "ROUTES NOTHING" in preamble, "and does not say the one thing a reader must know"

    row_doc = inspect.getsource(reliability.OutboxMessageRow)
    assert "D-162" in row_doc and "READ BY NOTHING" in row_doc, (
        "`claim_outbox_batch` selects the column into this field and nothing branches on "
        "it; a reader meeting `row.queue` must not have to infer that"
    )


def test_no_call_site_still_passes_a_queue() -> None:
    """The sweep, because the signature only stops the callers that are recompiled.

    A `queue=` on an `enqueue_outbox` call is now a TypeError at runtime rather than a
    silent no-op, which is an improvement — but a scan says so at review time instead of
    at 3am, and it also catches the constants (`TENANT_ERASURE_QUEUE`, `DELETION_QUEUE`)
    whose whole content was the string `"default"` and which existed only to be passed
    here.
    """
    offenders: list[str] = []
    for root in SCAN_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            if "__pycache__" in path.parts or path.name.endswith("_test.py"):
                continue
            if path == Path(reliability.__file__):
                continue  # the writer names the column in its INSERT; that is the point
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
