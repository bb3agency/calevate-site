"""The production entrypoint for a TTS-tier correction (closes PRODUCTION-READINESS P1.6).

`billing.service.record_tier_correction` is hard rule 4's compensating entry for a call
metered on the wrong TTS rung — the ONLY lawful repair, because `usage_events` carries an
immutability trigger and a mis-billed call cannot be edited. It had no caller outside
pytest, which meant a mis-tiered call in production had no remedy short of hand-written
psql against an append-only table. This script is that caller.

WHY A SCRIPT AND NOT AN ADMIN ROUTE, weighed rather than defaulted
-----------------------------------------------------------------
The input is a CHARACTER COUNT, and there is nowhere in this product to get one:
`rates.tts_cost_inr` refuses to invent one (TRD §10.1's "360-540 chars per call-minute" is
an unmeasured assumption, pilot gate 12) and the engine reports no count at all
(`billing/rates.py` carries the vendor question). The only source is Sarvam's own usage
export, which arrives as a file an operator downloads. A console button would therefore
need a file upload, a parser and a review screen for a correction that has been needed
zero times — an admin surface with no caller is the defect this repo calls "progress that
looks like progress on a screen". A script that reads the same file directly is the
smaller, honest shape, and it is the one `reconcile_credit_ledger.py` already established
for a compensating write over the wallet.

WHAT IT WILL NOT LET AN OPERATOR GET WRONG
------------------------------------------
* **`billed_tier` is READ FROM THE LEDGER, never typed.** `record_tier_correction` takes
  it as an argument, and an operator restating it from memory is how a correction writes a
  delta between two rungs the call was never on. This script reads the rung off the call's
  own `telephony_s` row — the row that priced it — so the delta is always
  `cost(actual) - cost(as metered)`.
* **A call already on the right rung is skipped, loudly**, rather than writing a ₹0.00 row.
* **DRY RUN IS THE DEFAULT.** Nothing is written without `--apply`, exactly as the
  reconciliation script does it.
* **`--ref` is the idempotency key**, and it is keyed per call inside
  `record_tier_correction`, so re-running the same file after a crash corrects nothing
  twice and every call in a batch is corrected once.

WHAT A CORRECTION MOVES, so an operator knows what to expect afterwards (D-372/D-373):
OUR cost ledger, and the rung the call's minutes are priced on — which reprices a MANAGED
client's overage and their invoice on the next render. A PREPAID client's wallet does NOT
move: they are charged `self_serve_inr_per_min x minutes` and the rung is not an input to
that price.

Usage:

    uv run python -m scripts.correct_tts_tier --tenant <uuid> --ref sarvam-2026-08 \\
        --call <uuid> --chars 12500 --actual-tier value
    uv run python -m scripts.correct_tts_tier --tenant <uuid> --ref sarvam-2026-08 \\
        --from-csv corrections.csv --apply

The CSV is `call_id,chars,actual_tier` with an optional header line.

Ids, rungs and rupee deltas only in the report — never a client name and never a phone
number (hard rule 6); a correction report gets pasted into a ticket.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import UUID

from apps.api.billing.rates import TtsTier, tier_correction_inr
from apps.api.billing.service import record_tier_correction
from apps.api.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: The rungs an operator may name. Imported semantics, spelled here as a CLI vocabulary so
#: `--actual-tier bulbul:v2` is refused by argparse rather than by a KeyError three layers
#: down. A third rung added to `rates.TTS_INR_PER_10K_CHARS` fails
#: `tests/tts_tier_correction_script_test.py`, which reads both.
TIER_CHOICES: tuple[TtsTier, ...] = ("premium", "value")

RowStatus = Literal[
    "pending", "written", "already_corrected", "already_on_that_rung", "no_such_call"
]


@dataclass(frozen=True, slots=True)
class Row:
    """One line of the operator's file, with what the ledger says about it."""

    call_id: UUID
    chars: int
    actual_tier: TtsTier
    #: The rung the call was METERED on, read off its `telephony_s` row. None = the call
    #: has no metered row in this tenant's ledger at all.
    billed_tier: TtsTier | None
    delta_inr: Decimal
    status: RowStatus


async def billed_tier_of(
    session: AsyncSession, *, tenant_id: UUID, call_id: UUID
) -> TtsTier | None:
    """The rung this call was METERED on, from the row that priced it.

    `telephony_s` specifically, and not "any row of the call": that is the row
    `rung_seconds` counts the minutes off, so it is the one whose rung decides what a
    managed client was charged. A row carrying no tier, or a tier this module does not
    know, reads as `value` — the same honesty rule `rates.billable_tier` applies, and for
    the same reason: an unproven call was never billed the premium rate, so a correction
    must not pretend it was.
    """
    tier = (
        await session.execute(
            text(
                "SELECT meta->>'tts_tier' FROM usage_events "
                "WHERE tenant_id = :tid AND call_id = :cid AND unit_type = 'telephony_s' "
                "LIMIT 1"
            ),
            {"tid": tenant_id, "cid": call_id},
        )
    ).first()
    if tier is None:
        return None
    return "premium" if str(tier[0]) == "premium" else "value"


async def _already_corrected(
    session: AsyncSession, *, tenant_id: UUID, call_id: UUID, ref: str
) -> bool:
    """Has THIS reference already been applied to THIS call?

    `record_tier_correction` asks the same question under the advisory lock and is the
    enforcement; this is the reporting half, so a DRY RUN can tell an operator which lines
    of their file are already done before they pass `--apply`.
    """
    return (
        await session.execute(
            text(
                "SELECT 1 FROM usage_events WHERE tenant_id = :tid AND call_id = :cid "
                "AND meta->>'correction_ref' = :ref LIMIT 1"
            ),
            {"tid": tenant_id, "cid": call_id, "ref": ref},
        )
    ).first() is not None


async def correct(
    *,
    tenant_id: UUID,
    ref: str,
    entries: list[tuple[UUID, int, TtsTier]],
    note: str | None = None,
    apply: bool = False,
) -> list[Row]:
    """Plan (and, with `apply`, write) one batch. Dry run unless told otherwise.

    ONE transaction for the whole batch, like `reconcile_tenant`: the reads that decide
    each line and the writes that act on them see one ledger, so a call metering
    mid-run cannot make the report disagree with what was written.
    """
    rows: list[Row] = []
    async with tenant_session(tenant_id) as session:
        for call_id, chars, actual_tier in entries:
            billed = await billed_tier_of(session, tenant_id=tenant_id, call_id=call_id)
            if billed is None:
                rows.append(Row(call_id, chars, actual_tier, None, Decimal("0"), "no_such_call"))
                continue
            if billed == actual_tier:
                rows.append(
                    Row(call_id, chars, actual_tier, billed, Decimal("0"), "already_on_that_rung")
                )
                continue
            if await _already_corrected(session, tenant_id=tenant_id, call_id=call_id, ref=ref):
                rows.append(
                    Row(call_id, chars, actual_tier, billed, Decimal("0"), "already_corrected")
                )
                continue

            delta = tier_correction_inr(chars=chars, billed_tier=billed, actual_tier=actual_tier)
            status: RowStatus = "pending"
            if apply:
                written = await record_tier_correction(
                    session,
                    tenant_id=tenant_id,
                    call_id=call_id,
                    chars=chars,
                    billed_tier=billed,
                    actual_tier=actual_tier,
                    ref=ref,
                    note=note,
                )
                # None here means the writer's own idempotency guard fired between the
                # read above and the write — a concurrent run of the same file. Reported
                # as the replay it is, never as a failure.
                status = "written" if written is not None else "already_corrected"
            rows.append(Row(call_id, chars, actual_tier, billed, delta, status))
    return rows


# --- the operator's view -------------------------------------------------------


def format_report(rows: list[Row], *, applied: bool, ref: str) -> str:
    """Ids, rungs and rupees. Never a name, never a number (hard rule 6).

    **AT THE LEDGER'S OWN PRECISION, NOT AT PAISE, AND THE LINES THEREFORE ADD UP.**
    This printed `to_paise` on each row and `to_paise` of the raw total, which is the
    "a figure quantized twice arrives twice" defect `money_walk_test` exists for — and it
    is reachable on ordinary inputs, not on contrived ones. Measured: two calls of 2,996
    characters corrected premium→value are ₹-4.4940 each; paise-rounded per line that
    prints ₹-4.49 twice, adding to ₹-8.98 beside a total of `to_paise(-8.9880)` = ₹-8.99.
    A report whose own lines do not add to its own total is the first thing its reader
    checks.

    The fix is NOT `allocate_paise` here, and the difference from the invoice matters: an
    invoice must publish paise because a client pays in paise, so its lines are ALLOCATED
    to the total. This is an operator's account of rows that were written, and
    `usage_events.unit_cost_paid` is NUMERIC(12,4) — `tier_correction_inr` already
    quantizes at `MONEY_Q`, so the deltas ARE exact at four decimals and printing them
    unrounded is both the truth about the ledger and exactly additive. Rounding a row to
    make a total add up would misstate the row; not rounding at all makes the question
    disappear.
    """
    mode = "APPLIED" if applied else "DRY RUN (nothing written)"
    lines = [f"tts tier correction {ref} — {mode}", f"{len(rows)} line(s) read", ""]
    moved = sum(
        (row.delta_inr for row in rows if row.status in ("pending", "written")), Decimal("0")
    )
    for row in rows:
        lines.append(
            f"  {row.call_id}  {row.billed_tier or '-'} -> {row.actual_tier}  "
            f"{row.chars} chars  INR {row.delta_inr}  [{row.status}]"
        )
    lines.append("")
    lines.append(f"net change to OUR recorded cost for this batch: INR {moved}")
    lines.append(
        "a correction moves our cost ledger and the rung the minutes are priced on "
        "(D-372); a prepaid wallet does not move (D-373)"
    )
    if not applied and any(row.status == "pending" for row in rows):
        lines.append("re-run with --apply to write these.")
    return "\n".join(lines)


def read_csv(path: Path) -> list[tuple[UUID, int, TtsTier]]:
    """`call_id,chars,actual_tier`, with an optional header.

    Strict: a malformed line RAISES rather than being skipped. A correction file whose bad
    rows are silently dropped is a batch that reports success having corrected some of it,
    which is the half-applied shape hard rule 4 exists to keep out of the ledger.
    """
    entries: list[tuple[UUID, int, TtsTier]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for index, record in enumerate(csv.reader(handle), start=1):
            if not record or not record[0].strip():
                continue
            if index == 1 and record[0].strip().lower() in ("call_id", "call"):
                continue
            if len(record) != 3:
                raise ValueError(f"{path}:{index}: expected call_id,chars,actual_tier")
            tier = record[2].strip()
            if tier not in TIER_CHOICES:
                raise ValueError(f"{path}:{index}: {tier!r} is not one of {TIER_CHOICES}")
            entries.append((UUID(record[0].strip()), int(record[1]), tier))
    return entries


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="correct_tts_tier",
        description=(
            "Correct calls metered on the wrong TTS rung, by appending compensating "
            "entries (hard rule 4). Dry run unless --apply."
        ),
    )
    parser.add_argument("--tenant", required=True, type=UUID, help="the tenant's organization id")
    parser.add_argument(
        "--ref",
        required=True,
        help=(
            "the ops reference for this batch — the idempotency key. Name the evidence, "
            "e.g. the Sarvam usage export it came from."
        ),
    )
    parser.add_argument("--note", default=None, help="free text stored on every row")
    parser.add_argument("--call", type=UUID, help="a single call id (with --chars/--actual-tier)")
    parser.add_argument("--chars", type=int, help="characters synthesized, from the vendor export")
    parser.add_argument("--actual-tier", choices=TIER_CHOICES, help="the rung that actually ran")
    parser.add_argument("--from-csv", type=Path, help="call_id,chars,actual_tier per line")
    parser.add_argument(
        "--apply", action="store_true", help="write the corrections (default: report only)"
    )
    args = parser.parse_args(argv)
    if args.from_csv is None and (
        args.call is None or args.chars is None or args.actual_tier is None
    ):
        parser.error("give either --from-csv, or all of --call, --chars and --actual-tier")
    if args.from_csv is not None and args.call is not None:
        parser.error("--from-csv and --call are alternatives, not a pair")
    return args


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    entries = (
        read_csv(args.from_csv)
        if args.from_csv is not None
        else [(args.call, args.chars, args.actual_tier)]
    )
    rows = await correct(
        tenant_id=args.tenant, ref=args.ref, entries=entries, note=args.note, apply=args.apply
    )
    print(format_report(rows, applied=args.apply, ref=args.ref))
    # A line the ledger could not act on is a non-zero exit, so a wrapper notices: the
    # operator's file named a call this tenant does not have.
    return 1 if any(row.status == "no_such_call" for row in rows) else 0


if __name__ == "__main__":  # pragma: no cover - CLI
    sys.exit(asyncio.run(main()))
