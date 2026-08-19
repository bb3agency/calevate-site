"""No shipped module quantizes money on the ambient `decimal` context.

THE DEFECT. `apps/workers/pipeline.py::_unit_price` — the WRITE path for
`usage_events.unit_cost_paid` — was `(leg_inr / qty).quantize(Decimal("0.0001"))`, with
no rounding mode. `Decimal.quantize()` with no mode uses `decimal.getcontext()`, whose
default is ROUND_HALF_EVEN and which is process-global and mutable by any library in the
image. Two things followed:

* the one rounding in the tree that decides what a supplier leg COST us disagreed with
  every other money rounding in the repo, which is ROUND_HALF_UP;
* it was reachable, not theoretical. A ₹0.0180 telephony leg over a 360-second call is
  exactly ₹0.00005 per second. Half-even stores ₹0.0000 and `qty * unit_cost_paid`
  contributes nothing — the whole leg rounded out of the admin margin panel and out of
  `tier_usage`, the two surfaces that read `_tier_totals`' cost half. (This used to name
  a closed month's client-facing `spend_used` as a third. That reader retired at P1.3:
  it is `calling_revenue_inr` now, priced off MINUTES at the client's own rate, and it
  never touches `unit_cost_paid`.)

`billing/service.py` had already written the argument out in full ("passed EXPLICITLY,
never inherited … a rupee that changes because someone else changed a global is not an
amount we can defend") and `billing/rates.py` restated it. The doctrine existed in two
docstrings and was enforced by nothing, which is the shape of D-102/D-103/D-105: a fact
with no single home, so the correction has one place to land and several to be missed.

WHY THE SCAN IS "ANY QUANTIZE", NOT "ANY MONEY QUANTIZE"
---------------------------------------------------------
Deciding whether a `Decimal` holds rupees needs type inference this test does not have,
and the two heuristics available both fail on the real tree: the quantum is sometimes a
named constant (`MONEY_QUANTUM`) and sometimes a literal, and a money quantum is also
used to round a diagnostic RATIO. So the subject is the narrower, decidable question —
**does this call state its rounding mode** — which is the right question anyway: the
reason a mode must be explicit is that the ambient context is global and mutable, and
that reason does not care what the number means.

Measured against the tree at the time of writing: 12 `quantize` call sites in
`apps/`, `packages/shared/src/` and `scripts/`; 6 pass a mode; 6 do not. Every one of
the 6 genuinely omits it — there are no false positives, because the predicate is a
property of the call and not a guess about its subject.

WHY A SCAN AND NOT A PIN ON THE LINE THAT WAS WRONG
-----------------------------------------------------
Pinning `_unit_price` would be satisfied by the commit that fixed it and silent on the
next writer. The site that hurt was not the obvious one — `billing/` has been swept
repeatedly and is clean; the offender was in a worker, in a helper that reads like
plumbing. The same argument `engine_name_drift_test` and `sarvam_model_identifier_test`
make, and the same shape: derive the vocabulary from the code, scan the whole tree, and
record what cannot be fixed from here as an EQUALITY assertion rather than an allowlist.
"""

from __future__ import annotations

import ast
from decimal import Decimal, DefaultContext, localcontext
from pathlib import Path

from apps.api.billing.models import MONEY
from apps.api.billing.rates import MONEY_Q, ROUNDING
from apps.api.billing.service import ROUNDING as SERVICE_ROUNDING
from apps.api.db.base import Base
from apps.workers.pipeline import _unit_price

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Where a rounding decision can reach a stored or reported amount. `tests/` is out for
#: the reason `sarvam_model_identifier_test` gives: a test that quantizes is usually
#: constructing an expectation, not deciding what a client pays. `alembic/versions` is
#: out because a migration is a historical record.
SCANNED_TREES: tuple[str, ...] = ("apps", "packages/shared/src", "scripts")

#: Call sites that omit the mode TODAY, cannot be fixed from the slice that found them,
#: and are therefore recorded rather than left to be rediscovered. Keyed by file and by
#: the source of the call itself, never by line number, so an unrelated edit above does
#: not turn this into a maintenance tax.
#:
#: This is an EQUALITY assertion, not an exemption list: adding a site fails, and FIXING
#: one of these fails too, so an entry cannot outlive the defect it describes.
#:
#: **EMPTY, and that is the assertion.** The five sites this dict shipped with are gone:
#: the two in `apps/api/engine/fake.py` and the three in `scripts/pilot/fidelity.py` all
#: pass `rounding=ROUNDING` now. An empty mapping is a stronger statement than a missing
#: one — `_ambient_quantize_sites()` returns `{}` only when EVERY quantize in the three
#: scanned trees states its mode — so the dict stays, and the next omission fails here
#: with nowhere to be recorded except deliberately.
KNOWN_AMBIENT_ROUNDING: dict[str, set[str]] = {}


def _shipped_python() -> list[Path]:
    return [
        path
        for tree in SCANNED_TREES
        for path in sorted((REPO_ROOT / tree).rglob("*.py"))
        if "__pycache__" not in path.parts and ".venv" not in path.parts
    ]


def _states_rounding(call: ast.Call) -> bool:
    """`x.quantize(q, rounding=...)` or the positional `x.quantize(q, ROUND_HALF_UP)`.

    Both spellings are accepted because `Decimal.quantize(exp, rounding=None,
    context=None)` takes the mode second positionally, and a call that passes a
    `context=` has also stated where the mode comes from rather than inheriting the
    process-global one.
    """
    if len(call.args) >= 2:
        return True
    return any(keyword.arg in {"rounding", "context"} for keyword in call.keywords)


def _ambient_quantize_sites() -> dict[str, set[str]]:
    """Every `.quantize(...)` in shipped code that states no rounding mode.

    Read from the AST, never from source text: a docstring or a comment explaining WHY
    the mode must be explicit — this repo has several, and this file is one — must not
    be mistaken for a call that omits it.
    """
    found: dict[str, set[str]] = {}
    for path in _shipped_python():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders = {
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "quantize"
            and not _states_rounding(node)
        }
        if offenders:
            found[path.relative_to(REPO_ROOT).as_posix()] = offenders
    return found


#: Every mode `decimal` names. Listed rather than imported as a set because the module
#: exposes them as bare strings with no collection to read, and a definition is detected
#: by the NAME the assignment uses — `ROUNDING = ROUND_HALF_UP`, `X = decimal.ROUND_UP`,
#: or the raw string, which is the third way somebody could spell one.
ROUNDING_MODE_NAMES: frozenset[str] = frozenset(
    {
        "ROUND_HALF_UP",
        "ROUND_HALF_EVEN",
        "ROUND_HALF_DOWN",
        "ROUND_UP",
        "ROUND_DOWN",
        "ROUND_CEILING",
        "ROUND_FLOOR",
        "ROUND_05UP",
    }
)


def _rounding_mode_definitions() -> set[tuple[str, str]]:
    """`{(file, name)}` for every MODULE-LEVEL binding of a decimal rounding mode.

    Module level only, and the value must BE a mode. A `rounding=ROUNDING` argument is a
    use, not a definition, and flagging uses would flag every correct call site in the
    repo — the calibration failure that gets a guard deleted.
    """
    found: set[tuple[str, str]] = set()
    for path in _shipped_python():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.Assign | ast.AnnAssign):
                continue
            value = node.value
            if isinstance(value, ast.Name):
                spelled: str | None = value.id
            elif isinstance(value, ast.Attribute):
                spelled = value.attr
            elif isinstance(value, ast.Constant) and isinstance(value.value, str):
                spelled = value.value
            else:
                spelled = None
            if spelled not in ROUNDING_MODE_NAMES:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            found.update(
                (path.relative_to(REPO_ROOT).as_posix(), target.id)
                for target in targets
                if isinstance(target, ast.Name)
            )
    return found


def test_no_shipped_module_rounds_money_on_the_ambient_context() -> None:
    """The scan, as an equality against what is known open.

    An entry added here without a fix is a claim that somebody looked and could not fix
    it from where they stood; an entry left here after a fix fails just as loudly, which
    is what stops this becoming the allowlist that a grep-shaped guard degenerates into.
    """
    assert _ambient_quantize_sites() == KNOWN_AMBIENT_ROUNDING, (
        "a `Decimal.quantize()` in shipped code states no rounding mode, so it takes the "
        "process-global `decimal` context (ROUND_HALF_EVEN by default, and mutable by any "
        "library in the image). Pass `rounding=` — `billing.rates.ROUNDING` for money. If "
        "the site cannot be fixed from your slice, record it in KNOWN_AMBIENT_ROUNDING "
        "with the slice that owns it; if you fixed one, delete its entry."
    )


def test_the_money_quantum_is_the_column_it_quantizes_for() -> None:
    """The blind spot the scan cannot see: a mode passed correctly at the wrong scale.

    `MONEY_Q` is derived from `MONEY.scale`, so this asserts the derivation is about the
    right column — every NUMERIC money column in the billing schema shares one scale, and
    a second scale would mean one quantum can no longer serve them all.
    """
    from apps.api.billing import models

    # Every mapped class in the billing module, discovered rather than listed: a table
    # added tomorrow is covered on the day it lands, which is the whole point of a guard
    # that is meant to fail on the NEXT instance.
    mapped = [
        value
        for value in vars(models).values()
        if isinstance(value, type) and issubclass(value, Base) and value is not Base
    ]
    scales = {
        f"{model.__tablename__}.{column.name}": getattr(column.type, "scale", None)
        for model in mapped
        for column in model.__table__.columns
        if getattr(column.type, "scale", None) is not None
    }
    assert scales, "no NUMERIC column found in billing/models.py — this test lost its subject"
    assert MONEY.scale == 4, "MONEY moved scale; MONEY_Q derives from it and every stored cost"
    assert set(scales.values()) == {MONEY.scale}, (
        f"the billing schema now holds more than one NUMERIC scale ({scales}), so a single "
        "MONEY_Q cannot be the storage quantum for all of them"
    )
    assert Decimal("0.0001") == MONEY_Q


def test_there_is_exactly_one_definition_of_the_rounding_mode() -> None:
    """`billing.service.ROUNDING` and `billing.rates.ROUNDING` were two definitions of one
    decision. The scan below is what keeps that at one.

    **WHY THIS IS AN AST SCAN AND NOT `service.ROUNDING is rates.ROUNDING`.** That
    identity assertion was written first, and sabotaging the fix — putting `ROUNDING =
    ROUND_HALF_UP` back into `service.py` — did not turn it red. `decimal.ROUND_HALF_UP`
    is the interned STRING `'ROUND_HALF_UP'`, so `is` compares equal between any two
    modules that both name it, and the test could not fail for the defect it was written
    against. It was a tautology wearing an identity check, which is the exact class D-97
    found three of; it is recorded here rather than quietly replaced, because the next
    person to reach for `is` on a `decimal` constant should meet this paragraph.

    Measured against the tree: 1 module-level rounding-mode definition, in `rates.py`,
    0 false positives — a `rounding=ROUNDING` ARGUMENT is not a definition and is not
    counted, which is the distinction that keeps this from flagging every correct call
    site in the repo.
    """
    definitions = _rounding_mode_definitions()
    assert definitions == {("apps/api/billing/rates.py", "ROUNDING")}, (
        f"the tree defines the money rounding mode in {sorted(definitions)}. There is one "
        "home — `billing.rates.ROUNDING` — and every other module imports it; a second "
        "definition is a second decision waiting to disagree with the first."
    )
    assert SERVICE_ROUNDING == ROUNDING, "the re-export still resolves to the one home"


def test_the_metering_writer_ignores_a_hostile_ambient_context() -> None:
    """The behavioural half, and the reason this is not merely tidying.

    `_unit_price` is the write path for `unit_cost_paid`. Under a context set to ROUND_UP
    — which any library in the image can do, and which `localcontext` here does honestly
    rather than by monkeypatching our own code — the answer must not move.
    """
    leg, qty = Decimal("0.0180"), Decimal("360")  # exactly ₹0.00005/second
    assert _unit_price(leg, qty) == Decimal("0.0001"), "half-up is the doctrine"
    with localcontext() as ctx:
        ctx.rounding = "ROUND_DOWN"
        assert _unit_price(leg, qty) == Decimal("0.0001"), (
            "the leg price moved because a library changed the process-global decimal "
            "context — the exact failure an explicit mode exists to prevent"
        )
        assert _unit_price(Decimal("0.01"), Decimal("3")) == Decimal("0.0033")
    assert DefaultContext.rounding == "ROUND_HALF_EVEN", (
        "the default this test is defending against is no longer half-even; re-read the "
        "argument in billing/rates.py before relaxing anything"
    )
