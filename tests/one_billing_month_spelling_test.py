"""There is ONE Python spelling of "which IST billing month is this instant in".

THE DEFECT THIS SCAN EXISTS FOR. `billing/plans.py::ist_billing_month` has been the
stated home of the +05:30 shift since effective dating landed, and it says so in its own
docstring: "callers that hold an instant in Python … come here rather than adding their
own offset". `apps/workers/pipeline.py` had its own anyway —
`(moment + timedelta(hours=5, minutes=30)).strftime("%Y-%m")` — reachable from the meter,
the one place in this repo where the answer decides which month a spend cap counts a call
into. The two agree for a UTC-expressed instant and DISAGREE for any other, because
`strftime` renders the value's own naive fields rather than converting: an `ended_at` a
vendor stamped `+05:30` (both adapters preserve the offset they were sent — see
`engine/bolna.py::_parse_dt`) was shifted twice, so a 23:00 IST call on the last of the
month metered into the NEXT one while its own `usage_events` rows stayed in the right one.

The doctrine existed in a docstring and was enforced by nothing, which is the shape
D-102/D-103/D-105 each paid for: a fact with one home and several places to be missed.
So this is a SCAN and not a pin on the line that was wrong — pinning the meter would be
satisfied by the commit that fixed it and silent on the next worker, script or route that
needs a billing month at 2am and reaches for `timedelta`.

WHAT IS DETECTED, and why it is this and not "any timezone arithmetic". The decidable
question is: does this expression turn an instant into a `YYYY-MM` string? That is
`strftime("%Y-%m")` (and its f-string twin, `f"{moment:%Y-%m}"`), which is a property of
the call rather than a guess about what the value means. Anything else — a `%Y-%m-%d`
date for a filename, an IST offset used to render a human-readable timestamp
(`compliance/breach.py`) — is not a billing month and is deliberately not the subject.

The one legal site is the definition itself. Read from the AST rather than the source
text, so this file's own prose cannot trip it.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from apps.api.billing.plans import IST, ist_billing_month

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Where a billing month can reach a stored month, a ceiling or a statement. `tests/` is
#: out (a test that formats a month is building an expectation) and `alembic/versions` is
#: out (a migration is a historical record) — the same scope `money_rounding_mode_test`
#: draws for the same reasons.
SCANNED_TREES: tuple[str, ...] = ("apps", "packages/shared/src", "scripts")

#: The ONE module allowed to turn an instant into a billing month, and it is the one that
#: exports the function everybody else must call.
BILLING_MONTH_HOME = "apps/api/billing/plans.py"

#: The format that IS a billing month. `%Y-%m` and nothing longer: `%Y-%m-%d` is a date.
_BILLING_MONTH_FORMAT = "%Y-%m"


def _shipped_python() -> list[Path]:
    return [
        path
        for tree in SCANNED_TREES
        for path in sorted((REPO_ROOT / tree).rglob("*.py"))
        if "__pycache__" not in path.parts and ".venv" not in path.parts
    ]


def _formats_a_billing_month(node: ast.AST) -> bool:
    """`x.strftime("%Y-%m")`, or `f"{x:%Y-%m}"` — the two ways Python spells it."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "strftime"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == _BILLING_MONTH_FORMAT
    ):
        return True
    return (
        isinstance(node, ast.FormattedValue)
        and isinstance(node.format_spec, ast.JoinedStr)
        and any(
            isinstance(part, ast.Constant) and part.value == _BILLING_MONTH_FORMAT
            for part in node.format_spec.values
        )
    )


def _billing_month_formatters() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in _shipped_python():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        sites = {ast.unparse(node) for node in ast.walk(tree) if _formats_a_billing_month(node)}
        if sites:
            found[path.relative_to(REPO_ROOT).as_posix()] = sites
    return found


def test_only_one_module_turns_an_instant_into_a_billing_month() -> None:
    """An EQUALITY assertion, not an allowlist: a second spelling fails here, and so does
    removing the first one — the home has to keep its own implementation."""
    assert set(_billing_month_formatters()) == {BILLING_MONTH_HOME}


def test_the_shared_spelling_converts_rather_than_shifting_naive_fields() -> None:
    """The property the meter's private helper did not have: the answer depends on the
    INSTANT, not on which offset the caller's `tzinfo` happens to carry.

    23:00 IST on 31 August is an August call whether it arrives as `+05:30` or as the
    same moment written in UTC — and the old `moment + 5:30` spelling gave `2026-09` for
    the first of those two.
    """
    as_ist = datetime(2026, 8, 31, 23, 0, tzinfo=IST)
    as_utc = as_ist.astimezone(UTC)
    as_other = as_ist.astimezone(timezone(timedelta(hours=-8)))
    assert ist_billing_month(as_ist) == "2026-08"
    assert ist_billing_month(as_utc) == "2026-08"
    assert ist_billing_month(as_other) == "2026-08"


def test_the_05_30_boundary_is_where_a_utc_month_would_have_been_wrong() -> None:
    """The half-hour after midnight IST on the 1st is the window a UTC month gets wrong,
    and it is why the offset exists at all: 00:30 IST on 1 September is 19:00 UTC on 31
    August."""
    just_after_midnight_ist = datetime(2026, 9, 1, 0, 30, tzinfo=IST)
    assert just_after_midnight_ist.astimezone(UTC).strftime("%Y-%m") == "2026-08"
    assert ist_billing_month(just_after_midnight_ist) == "2026-09"
