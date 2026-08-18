"""Render the three DPDP Rule 7 notices from one incident file.

The executable half of `runbooks/data-breach-notification.md` (D-179, LEGAL-SURFACE F-6).
The runbook says what to establish and who signs off; this turns the answers into the
three documents, refuses to render one with a required element missing, and refuses one
carrying a phone number.

    uv run python -m scripts.breach_notice incident.json
    uv run python -m scripts.breach_notice incident.json --which client

A FILE rather than a pile of flags, and the file is the artifact: it is what gets attached
to the incident ticket, re-rendered when the facts are updated for the 72-hour report, and
read back a year later when somebody asks what we told people. Twelve `--flags` typed into
a terminal at 3am leave no such record.

Nothing here sends anything. Who signs off is a named human decision (runbook §4), and a
tool that could mail every client at once during an incident is a blast radius rather than
a control.

The incident file is JSON with the keys of `compliance.breach.BreachFacts`; `aware_at` is
an ISO-8601 instant WITH an offset, because every deadline is computed from it and a naive
timestamp during an incident spanning midnight IST is a missed statutory deadline waiting
to happen. `runbooks/data-breach-notification.md` §3 carries a skeleton to copy.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from apps.api.compliance.breach import (
    BreachFacts,
    IncompleteBreachNoticeError,
    board_report,
    client_notification,
    data_principal_notice,
)

RENDERERS = {
    "client": client_notification,
    "principal": data_principal_notice,
    "board": board_report,
}


def _facts(document: dict[str, Any]) -> BreachFacts:
    """Build the facts, naming every unknown key rather than ignoring it.

    An ignored key is a required element silently absent: `natur` instead of `nature`
    would otherwise render a notice missing the first thing Rule 7 asks for, and the
    author would have no way to see it.
    """
    known = set(BreachFacts.__dataclass_fields__)
    unknown = sorted(set(document) - known)
    if unknown:
        raise SystemExit(
            f"incident file has keys this renderer does not know: {', '.join(unknown)}. "
            f"Known keys: {', '.join(sorted(known))}"
        )
    raw = dict(document)
    when = raw.get("aware_at")
    if not isinstance(when, str):
        raise SystemExit("incident file needs `aware_at`, an ISO-8601 instant with an offset")
    try:
        raw["aware_at"] = datetime.fromisoformat(when)
    except ValueError as exc:
        raise SystemExit(f"aware_at is not an ISO-8601 instant: {exc}") from exc
    try:
        return BreachFacts(**raw)
    except TypeError as exc:
        raise SystemExit(f"incident file is missing a required key: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("incident", type=Path, help="JSON file of the facts (runbook §3)")
    parser.add_argument(
        "--which",
        choices=(*RENDERERS, "all"),
        default="all",
        help="which notice to render (default: all three)",
    )
    args = parser.parse_args(argv)

    try:
        document = json.loads(args.incident.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"cannot read {args.incident}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{args.incident} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise SystemExit(f"{args.incident} must contain a JSON object")

    facts = _facts(document)
    wanted = list(RENDERERS) if args.which == "all" else [args.which]
    try:
        for name in wanted:
            print(f"{'=' * 78}\n{name.upper()}\n{'=' * 78}\n")
            print(RENDERERS[name](facts))
    except IncompleteBreachNoticeError as exc:
        # The whole list at once: an incident does not have five round trips in it.
        print(f"this notice cannot be rendered yet — {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
