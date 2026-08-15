"""One definition of the engine set, and a scanner that fails when a second appears.

THE DEFECT THIS FILE EXISTS FOR (D-103). `calevate_shared.config.EngineName` grew
`cartesia` when D-93 landed the adapter. `apps/voice-runtime/engine_intake.py` had its
own `EngineName = Literal["bolna", "fake"]`, and it did not. Two copies of one union in
two deployables, disagreeing, with nothing in the tree able to notice: `check_wiring`
checks routers, migration heads and deferred columns, import-linter checks the direction
of imports, and neither can see that two `Literal`s spell different things. The audit for
D-93 had already found the FIRST copy of this class, which is what makes it a class
rather than an incident.

So the fix is not "add cartesia to the second copy". The fix is that there is no second
copy, and that the next one fails a test instead of shipping.

TWO QUESTIONS, TWO HOMES, AND THEY ARE NOT THE SAME QUESTION
------------------------------------------------------------
* **Which names may `ENGINE=` be?** `calevate_shared.config.EngineName`, with
  `SELECTABLE_ENGINES` as the importable value. A `Literal` because pydantic validates
  the setting against it and mypy checks comparisons against it.
* **Which names does this codebase have an authenticity story for?**
  `calevate_shared.engine.WEBHOOK_AUTH_BY_ENGINE`, whose keys are the shipped adapters.
  This is the set the voice-runtime receiver answers for.

The second is a superset of the first, and the gap between them is exactly one entry:
`fake-restricted`, the conformance fixture that is deliberately unselectable and is the
only engine in the tree declaring `hmac`. `test_every_selectable_engine_has_an_
authenticity_story` is what keeps the containment true, because the direction that hurts
is the missing one: a selectable engine absent from the table is a deployment whose every
webhook is answered `unknown engine`.

WHY A SOURCE SCANNER AND NOT A LIST OF PLACES TO CHECK
-------------------------------------------------------
A test that asserts `engine_intake.KNOWN_ENGINES == frozenset(WEBHOOK_AUTH_BY_ENGINE)`
pins the copy we know about. It says nothing about the copy somebody writes next month in
a module nobody has thought of yet — and the two copies that already existed were both
written by people who were not thinking about the other one. `_engine_name_collections`
walks the whole Python tree for any literal collection that spells two or more engine
names, so a third copy fails on the commit that introduces it, wherever it is.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from calevate_shared.config import SELECTABLE_ENGINES
from calevate_shared.engine import WEBHOOK_AUTH_BY_ENGINE

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Every name either home knows. The scanner derives its vocabulary from the two homes
#: rather than listing engine names of its own — a guard that spelled the set would be a
#: fourth copy of it.
ALL_ENGINE_NAMES: frozenset[str] = SELECTABLE_ENGINES | frozenset(WEBHOOK_AUTH_BY_ENGINE)

#: The two files allowed to spell these names in a collection, and what each one answers.
#: Everything else must IMPORT one of them.
CANONICAL_HOMES: dict[str, str] = {
    "packages/shared/src/calevate_shared/config.py": (
        "`EngineName` / `SELECTABLE_ENGINES` — which names `ENGINE=` may be"
    ),
    "packages/shared/src/calevate_shared/engine.py": (
        "`WEBHOOK_AUTH_BY_ENGINE` — which names have an authenticity story"
    ),
}

#: The Python trees a copy could hide in. `tests/` is deliberately EXCLUDED: a test that
#: restates the set is doing the thing `scripts/pilot/gates_api.DOCUMENTED_EGRESS_IP`
#: argues for — "a gate that imported the value it tests would be asking the code whether
#: it agrees with itself" — and `tests/engine_capability_test.py` restates the shipped
#: set for exactly that reason. `alembic/versions` is excluded because a migration is a
#: historical record: the CHECK constraint it wrote is a fact about the past and editing
#: it would be a lie, not a fix.
SCANNED_TREES: tuple[str, ...] = ("apps", "packages/shared/src", "scripts")

#: Copies that exist TODAY, cannot be fixed from inside this slice, and are therefore
#: recorded here rather than left to be rediscovered. This is an equality assertion, not
#: an exemption list: adding a copy fails, and FIXING one of these fails too, so the entry
#: cannot outlive the defect it describes.
#:
#: `apps/api/agents/models.py::ENGINES` is not a cosmetic disagreement. It renders the
#: `ck_agents_engine_enum` CHECK constraint (migration 05bba2f3c19c writes
#: `engine IN ('fake', 'bolna')`), and `admin/service.py::_default_engine` inserts
#: `get_settings().engine` into that column when a tenant is born. So on a deployment
#: running `ENGINE=cartesia` — a configuration `config.EngineName` accepts — creating a
#: client fails with an IntegrityError from Postgres, not with a named refusal.
#:
#: Closing it is two edits this slice does not own: `ENGINES = tuple(sorted(
#: SELECTABLE_ENGINES))` in that module, and a migration widening the CHECK. When both
#: land, delete this entry — this test will tell you to.
KNOWN_OPEN_COPIES: dict[str, str] = {
    "apps/api/agents/models.py": (
        "ENGINES renders ck_agents_engine_enum and is still ('fake', 'bolna'); widening "
        "it needs a migration, so it is REPORTED by D-103 rather than fixed by it"
    ),
}


def _literal_strings(node: ast.AST) -> set[str]:
    """The string constants this node spells as a COLLECTION, if it is one.

    Four shapes, because those are the four ways this repo has actually written an engine
    set: a tuple/list/set of names (`agents/models.py`), a dict keyed by name
    (`WEBHOOK_AUTH_BY_ENGINE`), and `Literal[...]` (both `EngineName`s). A `==` comparison
    against one name is NOT included and that is deliberate: `apps/api/engine/__init__.py`
    is a factory and a factory must branch per engine, so flagging comparisons would flag
    the one place the branch belongs.
    """
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return {
            e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
        }
    if isinstance(node, ast.Dict):
        return {
            k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }
    if isinstance(node, ast.Subscript):
        base = node.value
        named_literal = (isinstance(base, ast.Name) and base.id == "Literal") or (
            isinstance(base, ast.Attribute) and base.attr == "Literal"
        )
        if not named_literal:
            return set()
        members = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        return {
            e.value for e in members if isinstance(e, ast.Constant) and isinstance(e.value, str)
        }
    return set()


def _engine_name_collections() -> dict[str, set[str]]:
    """Every file outside the canonical homes that spells two or more engine names.

    Two, not one: a single name is a legitimate mention — a log field, a probe's `source`
    string, one branch of the factory — and flagging it would make this guard noise that
    somebody eventually deletes. Two or more in one collection is a SET, and a set is the
    thing there may only be one of.
    """
    offenders: dict[str, set[str]] = {}
    for tree in SCANNED_TREES:
        for path in sorted((REPO_ROOT / tree).rglob("*.py")):
            if "__pycache__" in path.parts or ".venv" in path.parts:
                continue
            relative = path.relative_to(REPO_ROOT).as_posix()
            if relative in CANONICAL_HOMES:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                spelled = _literal_strings(node) & ALL_ENGINE_NAMES
                if len(spelled) >= 2:
                    offenders.setdefault(relative, set()).update(spelled)
    return offenders


# --- 1. the scanner: no third copy, and no silent loss of the second ----------


def test_no_module_outside_the_two_homes_spells_the_engine_set() -> None:
    """The guard the previous drift needed and did not have.

    Equality against `KNOWN_OPEN_COPIES` rather than a subset check, so this fails in both
    directions: a NEW copy appears, or a recorded one is quietly fixed while its entry
    stays behind claiming a defect that is gone. A stale exemption is the same failure as
    the drift — a statement about the code that the code no longer supports.
    """
    offenders = _engine_name_collections()
    unexpected = {
        path: sorted(names) for path, names in offenders.items() if path not in KNOWN_OPEN_COPIES
    }
    assert not unexpected, (
        "these modules spell the engine set instead of importing it:\n"
        + "\n".join(f"  - {path}: {names}" for path, names in sorted(unexpected.items()))
        + "\n\nThere are exactly two homes for this set:\n"
        + "\n".join(f"  - {home}: {why}" for home, why in sorted(CANONICAL_HOMES.items()))
        + "\nImport `calevate_shared.config.SELECTABLE_ENGINES` or the keys of "
        "`WEBHOOK_AUTH_BY_ENGINE`; a second spelling drifts the first time either grows."
    )

    closed = sorted(set(KNOWN_OPEN_COPIES) - set(offenders))
    assert not closed, (
        f"{closed} no longer spells the engine set — the defect is fixed, so delete its "
        "entry from KNOWN_OPEN_COPIES and let the scanner enforce the rule everywhere."
    )


def test_the_receiver_derives_its_engine_set_and_does_not_define_one() -> None:
    """The specific copy D-103 removed, pinned so it cannot come back by hand.

    Both halves matter. The VALUE has to be the shared table's keys — that is what makes
    "known to the receiver" and "has an authenticity story" one answer. And the SOURCE has
    to be an import, because a `frozenset({"bolna", "fake", "cartesia"})` typed out here
    would satisfy the value assertion on the day it was written and drift on the next one.
    """
    from engine_intake import KNOWN_ENGINES

    assert set(KNOWN_ENGINES) == set(WEBHOOK_AUTH_BY_ENGINE)

    source = (REPO_ROOT / "apps" / "voice-runtime" / "engine_intake.py").read_text()
    module = ast.parse(source)
    spelled = {
        name for node in ast.walk(module) for name in _literal_strings(node) & ALL_ENGINE_NAMES
    }
    assert not spelled, (
        f"engine_intake.py spells engine names in a collection again: {sorted(spelled)}. "
        "It must read `WEBHOOK_AUTH_BY_ENGINE`, which is the table it already authenticates "
        "from — a second spelling in this file is exactly the drift D-103 closed."
    )


def test_every_selectable_engine_has_an_authenticity_story() -> None:
    """The containment that makes two sets safe instead of two copies.

    The direction asserted is the one that hurts. A selectable engine missing from
    `WEBHOOK_AUTH_BY_ENGINE` is a deployment where `verify_source` answers `unknown engine`
    to every delivery its own vendor sends: total, silent webhook loss, recovered only by
    the 10-minute poller, and looking from the outside exactly like a stranger probing the
    URL. The other direction is legitimate and is asserted as such below.
    """
    missing = sorted(SELECTABLE_ENGINES - set(WEBHOOK_AUTH_BY_ENGINE))
    assert not missing, (
        f"{missing} can be selected as ENGINE= but declares no webhook authenticity "
        "method, so the receiver would refuse every one of its deliveries as an unknown "
        "engine. Add the entry to WEBHOOK_AUTH_BY_ENGINE with the adapter's declaration."
    )

    unselectable = sorted(set(WEBHOOK_AUTH_BY_ENGINE) - SELECTABLE_ENGINES)
    assert unselectable == ["fake-restricted"], (
        "the only engine allowed to have an authenticity story without being selectable "
        f"is the conformance fixture `fake-restricted`; found {unselectable}"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "OPEN DEFECT, reported by D-103 and not fixable from this slice: "
        "apps/api/agents/models.py::ENGINES renders ck_agents_engine_enum as "
        "engine IN ('fake', 'bolna'), so a deployment running ENGINE=cartesia cannot "
        "insert an agent row. Fix = derive ENGINES from SELECTABLE_ENGINES + a migration "
        "widening the CHECK; then delete this marker (xfail_strict makes it fail if you "
        "do not) and its KNOWN_OPEN_COPIES entry."
    ),
)
def test_an_agent_row_may_carry_any_selectable_engine() -> None:
    """The CONSEQUENCE of the third copy, pinned where a reader will meet it.

    `admin/service.py::_default_engine` writes `get_settings().engine` into `agents.engine`
    on the tenant-birth path, and that column carries a CHECK rendered from `ENGINES`. So
    the drift is not a style complaint about a tuple: under `ENGINE=cartesia` the first
    thing a new client does — exist — fails with an IntegrityError out of Postgres rather
    than with a refusal anyone authored.

    An xfail rather than a comment because `xfail_strict = true` (pyproject) turns this
    into the repo's documented way to PIN A KNOWN DEFECT: green while the defect stands,
    and a hard failure the moment somebody fixes it without removing the pin.
    """
    from apps.api.agents.models import ENGINES

    admitted_by_the_check_constraint = set(ENGINES)
    assert admitted_by_the_check_constraint >= SELECTABLE_ENGINES


__all__: list[Any] = []
