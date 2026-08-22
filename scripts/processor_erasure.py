"""The operator's half of a vendor-side erasure obligation (D-433).

The executable companion to `runbooks/processor-erasure.md`. `processor_erasure_overdue`
pages; this is what you run.

    uv run python -m scripts.processor_erasure list
    uv run python -m scripts.processor_erasure sent <task-id> --reference "TICKET-123"
    uv run python -m scripts.processor_erasure answered <task-id> --outcome confirmed

**NOTHING HERE SENDS ANYTHING**, for the reason `scripts/breach_notice.py` records about
its own surface: a tool that can write to a vendor on behalf of a compliance obligation is
a blast radius rather than a control, and the wording of a deletion demand is a human's to
write. This records what a human did.

**Why a script and not an admin screen.** The population is tiny (one row per erasure per
processor that holds a copy), the actor is an operator who has already been paged, and the
alternative — a route, an OpenAPI regeneration, a typed client and a React view — is a
product surface for a workflow that is three states long. If the volume ever justifies a
screen, this module is the behaviour it would call.

**`--tenant` is required and is not a convenience.** `processor_erasure_tasks` is FORCE-RLS'd
(hard rule 1), so every statement here runs inside `tenant_session` and a missing tenant
would silently return zero rows rather than erroring — "no open tasks" is exactly the wrong
thing for this tool to say by accident.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import UUID

from apps.api.compliance.processor_erasure import (
    OVERDUE_AFTER_DAYS,
    overdue_tasks,
    record_answer,
    record_request_sent,
    settled_tasks,
)
from apps.api.db.session import tenant_session


async def _list(tenant_id: UUID, *, all_open: bool) -> int:
    async with tenant_session(tenant_id) as session:
        tasks = await overdue_tasks(session, tenant_id=tenant_id, min_days=0 if all_open else None)
    if not tasks:
        print(
            "No outstanding vendor-side erasure obligations for this tenant"
            + ("" if all_open else f" older than {OVERDUE_AFTER_DAYS} days (use --all)")
            + "."
        )
        return 0
    print(f"{len(tasks)} outstanding vendor-side erasure obligation(s):\n")
    for task in tasks:
        print(f"  task      {task.id}")
        print(f"  processor {task.processor}   status {task.status}   open {task.days_open}d")
        # The subject hash, never the number (hard rule 6). It is here so an operator
        # holding the number can confirm they are looking at the right task, and it tells
        # anyone who does not hold the number nothing.
        print(f"  subject   {task.subject_ref or '(whole tenant — no single subject)'}")
        print("  quote these vendor ids in the request:")
        for ref in task.vendor_refs:
            print(f"      {ref}")
        print()
    print("Send the written request (runbooks/processor-erasure.md §3), then record it.")
    return 0


async def _settled(tenant_id: UUID) -> int:
    """What the vendors actually answered, and when.

    The question a client has to answer before telling a data principal their data is
    gone everywhere. The certificate cannot say it — it was issued before the vendor
    replied — so this is the record.
    """
    async with tenant_session(tenant_id) as session:
        tasks = await settled_tasks(session, tenant_id=tenant_id)
    if not tasks:
        print("No vendor-side erasure obligation has been answered for this tenant yet.")
        return 0
    for task in tasks:
        answered = task.answered_at.date().isoformat() if task.answered_at else "?"
        print(
            f"  {task.status.upper():9} {task.processor:12} answered {answered} "
            f"after {task.days_open}d   task {task.id}"
        )
    if any(t.status == "refused" for t in tasks):
        print(
            "\nA REFUSED obligation is evidence the gap is structural, not procedural. "
            "It belongs in front of whoever is negotiating the vendor DPA "
            "(OPERATIONS §2 gate 36)."
        )
    return 0


async def _sent(tenant_id: UUID, task_id: UUID, reference: str | None) -> int:
    async with tenant_session(tenant_id) as session:
        moved = await record_request_sent(session, task_id=task_id, vendor_reference=reference)
    if not moved:
        # Deliberately an ERROR and not a shrug. The guard is `status = 'open'`, so a
        # refusal here means the task is already `requested`, already answered, or in
        # another tenant — and each of those means the operator is about to believe
        # something that is not true about a statutory obligation.
        print(
            f"REFUSED: task {task_id} is not in state 'open'. It has already been sent, "
            "already been answered, or belongs to another tenant. Run `list` to see.",
            file=sys.stderr,
        )
        return 1
    print(f"Recorded: request sent for task {task_id}.")
    return 0


async def _answered(tenant_id: UUID, task_id: UUID, outcome: str, note: str | None) -> int:
    async with tenant_session(tenant_id) as session:
        moved = await record_answer(session, task_id=task_id, outcome=outcome, note=note)
    if not moved:
        print(
            f"REFUSED: task {task_id} is not in state 'requested'. Record that the "
            "request was sent first (`sent`), or it has already been answered.",
            file=sys.stderr,
        )
        return 1
    print(f"Recorded: task {task_id} answered '{outcome}'.")
    if outcome == "refused":
        # The one branch that prints advice, because it is the one an operator will not
        # already know what to do with, and the wrong response ("try again") is tempting.
        print(
            "\nA refusal is not a failure to retry. It is evidence that the gap is "
            "structural: put it in front of whoever is negotiating the vendor DPA "
            "(OPERATIONS §2 gate 36, wording in "
            "docs/evidence/subprocessor-erasure-reach.md §6), and tell the client before "
            "they answer their data principal."
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.processor_erasure", description=__doc__)
    parser.add_argument("--tenant", required=True, type=UUID, help="tenant uuid (RLS scope)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="show outstanding obligations and the ids to quote")
    p_list.add_argument(
        "--all", action="store_true", help="include tasks younger than the overdue clock"
    )

    sub.add_parser("settled", help="show obligations the vendors have answered, and when")

    p_sent = sub.add_parser("sent", help="record that the written request was sent")
    p_sent.add_argument("task_id", type=UUID)
    p_sent.add_argument("--reference", default=None, help="the vendor's own ticket id, if any")

    p_ans = sub.add_parser("answered", help="record the vendor's reply")
    p_ans.add_argument("task_id", type=UUID)
    p_ans.add_argument("--outcome", required=True, choices=("confirmed", "refused"))
    p_ans.add_argument("--note", default=None)

    args = parser.parse_args(argv)
    if args.command == "list":
        return asyncio.run(_list(args.tenant, all_open=args.all))
    if args.command == "settled":
        return asyncio.run(_settled(args.tenant))
    if args.command == "sent":
        return asyncio.run(_sent(args.tenant, args.task_id, args.reference))
    return asyncio.run(_answered(args.tenant, args.task_id, args.outcome, args.note))


if __name__ == "__main__":
    raise SystemExit(main())
