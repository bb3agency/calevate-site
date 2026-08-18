"""The half-wired sweep, proved against the states it exists to catch.

`scripts/check_half_wired.py` is the gate; this file is the evidence that the gate can go
red. A check nobody has watched fail is a check nobody knows is connected — the argument
`tests/wiring_guard_test.py` makes for its own subject, and the reason
`check_redaction_exposure` refuses to pass on a route table with no permissions in it.

Every state below actually shipped in this repository and was found by hand during the
sweep that produced this file:

* `cohere_api_key` — a `Settings` field, classified `applies: live` so the ops console
  offered it as installable, read by no code path anywhere (D-231).
* `fail_fast`, `get_sample`, `voice_selection_available` — three public functions whose
  only mention outside their own `def` was their own module's `__all__` (D-232).
* `campaign_contacts.dedupe_hash` — an unsalted truncated SHA-256 of a phone number,
  written on every upload and read by nothing, ever (D-233).
* a broad `except` in the pilot's KB prober that turned "our adapter raised" into "the
  vendor says this handle is unknown" (D-234).

The last block is the blind-spot half, in the shape `check_wiring.blind_spots` uses:
these assert the properties the scans DEPEND on, because a scan that has quietly stopped
seeing anything reads exactly like a clean tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts import check_half_wired as guard

REPO_ROOT = Path(__file__).resolve().parent.parent


def _write(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# --- 1. columns something writes and nothing reads -----------------------------


_MODELS = """
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import CheckConstraint


class Widget:
    __tablename__ = "widgets"
    __table_args__ = (CheckConstraint("shape IS NULL OR shape IN ('round',)", name="shape_enum"),)

    label: Mapped[str] = mapped_column()
    shape: Mapped[str] = mapped_column()
    fingerprint: Mapped[str] = mapped_column()
"""

_SERVICE = """
from sqlalchemy import text


async def create(session, label, shape, digest):
    await session.execute(
        text(
            "INSERT INTO widgets (label, shape, fingerprint) "
            "VALUES (:label, :shape, :digest)"
        ),
        {"label": label, "shape": shape, "digest": digest},
    )


async def read(session):
    return (await session.execute(text("SELECT label FROM widgets"))).all()
"""


def test_a_column_with_a_writer_and_no_reader_fails(tmp_path: Path) -> None:
    """`fingerprint` is inserted and never selected — `dedupe_hash`'s exact shape."""
    _write(tmp_path, "models.py", _MODELS)
    _write(tmp_path, "service.py", _SERVICE)

    offenders = guard.write_only_columns(roots=[tmp_path], baseline={})

    assert [line.split(":")[0] for line in offenders] == ["Widget.fingerprint"]


def test_a_column_read_only_by_a_check_constraint_is_not_a_finding(tmp_path: Path) -> None:
    """`shape` is inserted and selected by nothing — but a CHECK evaluates it on every
    write and refuses the row, which is a reader, and the sharpest kind.

    Four live columns are in exactly this state (`AuthSession.revoked_reason`,
    `QaCallSample.reviewed_by_admin_id`, `FirstCampaignReview.decision_source`,
    `RecordingErasureHold.tenant_erasure_id`). Reporting them would have made the first
    run four-fifths noise, which is how a guardrail teaches people to add exemptions.
    """
    _write(tmp_path, "models.py", _MODELS)
    _write(tmp_path, "service.py", _SERVICE)

    offenders = guard.write_only_columns(roots=[tmp_path], baseline={})

    assert not any("Widget.shape" in line for line in offenders)


def test_a_returning_clause_counts_as_a_read(tmp_path: Path) -> None:
    """`RETURNING` sits after the SET clause and is a READ — which is what makes
    `mark_inbox_processed` a reader of `processed_at` rather than only its writer."""
    _write(tmp_path, "models.py", _MODELS)
    _write(
        tmp_path,
        "service.py",
        "from sqlalchemy import text\n\n"
        "async def touch(session):\n"
        '    await session.execute(text("UPDATE widgets SET fingerprint = now() '
        'RETURNING fingerprint"))\n'
        '    await session.execute(text("SELECT label, shape FROM widgets"))\n',
    )

    assert guard.write_only_columns(roots=[tmp_path], baseline={}) == []


def test_the_column_baseline_may_not_outlive_its_reason() -> None:
    """An entry for a column that has since gained a reader is a standing excuse for a
    solved problem, and an entry naming no column is a hole for the next one to land in.
    Both fail, so the registry can only shrink."""
    failures = guard.stale_baselines()
    assert failures == [], "\n".join(failures)


# --- 2. settings nothing consumes ----------------------------------------------


def test_a_settings_field_nothing_reads_fails() -> None:
    """The state `cohere_api_key` was in: declared, classified `applies: live` — so the
    ops console offered it to an operator as an installable key — and read by nothing at
    all (D-231).

    THE FIELD NAME HERE IS SYNTHETIC, and that is the finding this test learned. The
    scan counts string constants as reads, because most column and key access in this
    repo is raw `text()` SQL — so writing the real name into this assertion would have
    made this very file the consumer the check was looking for, and the test would have
    passed for a reason that has nothing to do with the code. The real name appears only
    in this docstring, which the scan excludes.
    """
    # Composed rather than written, for the reason above: any literal spelling of the
    # name — in the call, in the assertion, in a comment that reaches the AST — is a
    # read, and this file is inside the scan.
    absent = "_".join(["absent", "vendor", "credential"])

    offenders = guard.unconsumed_settings({absent: 1})

    assert len(offenders) == 1
    assert absent in offenders[0]


def test_a_settings_field_something_reads_passes() -> None:
    offenders = guard.unconsumed_settings({"usd_inr_rate": 304})
    assert offenders == []


# --- 3. public functions nothing references ------------------------------------


def test_a_function_whose_only_mention_is_its_own_dunder_all_fails(tmp_path: Path) -> None:
    """The `fail_fast` / `get_sample` / `voice_selection_available` shape exactly.

    `__all__` is a re-export list, not a caller. Counting it would have made all three
    look alive — which is why they survived six audit waves.
    """
    _write(
        tmp_path,
        "module.py",
        "def used() -> int:\n"
        "    return 1\n"
        "\n"
        "\n"
        "def orphan() -> int:\n"
        "    return 2\n"
        "\n"
        "\n"
        '__all__ = ["orphan", "used"]\n',
    )
    _write(tmp_path, "caller.py", "from module import used\n\nprint(used())\n")

    offenders = guard.unreferenced_exports(baseline={}, roots=[tmp_path])

    assert len(offenders) == 1, offenders
    assert "orphan()" in offenders[0]


def test_a_route_handler_is_never_reported(tmp_path: Path) -> None:
    """FastAPI dispatches by decorator, and this repo names its routers `invite_router`,
    `sources_router`, `national_dnd_router` and a dozen more — so the verb is what is
    matched. An exact-match list of receiver names goes stale on the next module, and a
    guardrail that reports live endpoints as dead code is one people route around."""
    _write(
        tmp_path,
        "routes.py",
        "from fastapi import APIRouter\n"
        "\n"
        "invite_router = APIRouter()\n"
        "\n"
        "\n"
        '@invite_router.post("/accept")\n'
        "async def accept_invitation() -> None:\n"
        "    return None\n",
    )

    assert guard.unreferenced_exports(baseline={}, roots=[tmp_path]) == []


# --- 4. stub bodies -------------------------------------------------------------


def test_an_undocumented_stub_fails(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "stubs.py",
        "def later() -> None:\n    pass\n\n\ndef never() -> None:\n    raise NotImplementedError\n",
    )

    offenders = guard.stub_bodies(roots=[tmp_path])

    assert len(offenders) == 2, offenders
    assert "an empty body" in offenders[0] or "an empty body" in offenders[1]


def test_a_protocol_member_is_not_a_stub(tmp_path: Path) -> None:
    """`...` in a Protocol body is the language's own spelling of "this is a signature",
    and `calevate_shared/engine.py` is twenty of them. Excluded by CLASS, not by a list
    of method names that would need editing every time the Protocol grows."""
    _write(
        tmp_path,
        "port.py",
        "from typing import Protocol\n"
        "\n"
        "\n"
        "class VoiceEngine(Protocol):\n"
        "    def create_agent(self) -> None: ...\n"
        "    def end_call(self) -> None: ...\n",
    )

    assert guard.stub_bodies(roots=[tmp_path]) == []


def test_a_documented_deliberate_stub_is_not_a_finding(tmp_path: Path) -> None:
    """`engine/cartesia.py::_cost` returns None because a stamped guess at a vendor's
    currency is worse than no cost at all, and says so in eleven lines of docstring. The
    rule is CLAUDE.md's: a deferral that names what closes it is a decision."""
    _write(
        tmp_path,
        "adapter.py",
        "def cost() -> None:\n"
        '    """Not implemented deliberately: nothing sourced says what currency the\n'
        '    vendor reports. Closes at pilot gate 4."""\n'
        "    raise NotImplementedError\n",
    )

    assert guard.stub_bodies(roots=[tmp_path]) == []


# --- 5. handlers that swallow ---------------------------------------------------


def test_a_broad_handler_that_does_nothing_fails(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "swallow.py",
        "def a() -> None:\n"
        "    try:\n"
        "        work()\n"
        "    except Exception:\n"
        "        pass\n"
        "\n"
        "\n"
        "def b():\n"
        "    try:\n"
        "        return work()\n"
        "    except:  # noqa: E722\n"
        "        return None\n",
    )

    offenders = guard.swallowed_exceptions(roots=[tmp_path])

    assert len(offenders) == 2, offenders
    assert "`except Exception`" in offenders[0]
    assert "a bare `except:`" in offenders[1]


def test_a_narrow_handler_is_never_the_subject(tmp_path: Path) -> None:
    """`except ValueError: return None` around a parse IS the function's interface, and
    this repo has about thirty. Flagging them would bury the one that matters."""
    _write(
        tmp_path,
        "parse.py",
        "def parse(raw):\n"
        "    try:\n"
        "        return int(raw)\n"
        "    except ValueError:\n"
        "        return None\n",
    )

    assert guard.swallowed_exceptions(roots=[tmp_path]) == []


def test_a_broad_handler_that_records_state_is_not_swallowing(tmp_path: Path) -> None:
    """`core/health.ready` sets `redis_ok = False` and logs nothing: the failure IS the
    readiness verdict, which is louder than a log line. A rule of "must log" reported it,
    and a guard that calls four correct handlers defects gets answered with an
    allowlist."""
    _write(
        tmp_path,
        "probe.py",
        "def ready():\n"
        "    redis_ok = True\n"
        "    try:\n"
        "        ping()\n"
        "    except Exception:\n"
        "        redis_ok = False\n"
        "    return redis_ok\n",
    )

    assert guard.swallowed_exceptions(roots=[tmp_path]) == []


# --- 6. deferral markers --------------------------------------------------------


def test_a_marker_fails_wherever_it_hides(tmp_path: Path) -> None:
    """Comments never reach an AST, so this section reads raw text — a marker scan over
    parsed source is a scan that cannot see its own subject."""
    _write(
        tmp_path,
        "marked.py",
        "# TODO wire this up\n"
        "def f():\n"
        '    """FIXME: the retry budget is a guess."""\n'
        "    return 1\n",
    )

    offenders = guard.unclosed_deferrals(roots=[tmp_path])

    assert len(offenders) == 2, offenders
    assert "`TODO`" in offenders[0]
    assert "`FIXME`" in offenders[1]


def test_prose_that_names_the_vocabulary_is_not_a_marker(tmp_path: Path) -> None:
    """`engine_conformance/contract_test.py` argues that a refusal "becomes a TODO with
    a name" the day an engine grows campaign objects. That is a sentence about markers,
    not one, and a check that cannot tell them apart is a check people route around."""
    _write(
        tmp_path,
        "prose.py",
        "def f():\n"
        '    """The day this is used it stops being a lie detector and becomes a TODO\n'
        '    with a name."""\n'
        "    return 1\n",
    )

    assert guard.unclosed_deferrals(roots=[tmp_path]) == []


# --- 0. can the check still see its subject? ------------------------------------


def test_the_guard_refuses_rather_than_passing_on_a_tree_it_cannot_read() -> None:
    """The D-176 property, asserted rather than assumed: every section here compares a
    derived set against another derived set, and a comparison whose left side is empty
    answers "clean" for everything. `check_wiring` printed `OK (0 routers all mounted)`
    from exactly this."""
    assert guard.blind_spots() == [], "the live tree must be visible to the check"

    empty = Path("/nonexistent-tree-for-a-negative-control")
    assert guard.write_only_columns(roots=[empty], baseline={}) == []
    assert guard.stub_bodies(roots=[empty]) == []
    assert guard.swallowed_exceptions(roots=[empty]) == []
    assert guard.unclosed_deferrals(roots=[empty]) == []


@pytest.mark.parametrize(
    ("floor", "subject"),
    [(100, "columns"), (20, "settings"), (100, "public functions")],
)
def test_each_scan_is_still_populated(floor: int, subject: str) -> None:
    """The floors `blind_spots` enforces, restated where a reader will see them. An order
    of magnitude below the true counts, because the question is "is this registry still
    populated" and a floor that tracked the real number would fail on every deletion."""
    counts = {
        "columns": len(guard._declared_columns(guard._model_files(guard.SCAN_ROOTS))),
        "settings": len(guard.settings_fields()),
        "public functions": len(guard._public_functions()),
    }
    assert counts[subject] >= floor


def test_a_registry_file_is_not_evidence_about_its_own_subject() -> None:
    """This guard blinded itself on its first run: `WRITE_ONLY_BASELINE` names
    `Lead.first_call_id` in a string, string identifiers count as reads (they must —
    most column access here is raw `text()` SQL), so every baselined column looked
    consumed and `stale_baselines()` demanded the whole registry be deleted.

    The fix is narrow on purpose — a registry file's STRINGS are not evidence, its CALLS
    still are. Dropping the file wholesale reported this script's own section functions
    as dead code, which is the same defect pointing the other way.
    """
    baselined = set(guard.WRITE_ONLY_BASELINE)
    still_write_only = {line.split(":")[0] for line in guard.write_only_columns(baseline={})}
    assert baselined <= still_write_only, (
        "a baselined column must still be detectable as write-only — otherwise the "
        "registry is reading itself"
    )

    sections = {"write_only_columns", "unconsumed_settings", "unreferenced_exports"}
    reported = {line.split(" ")[1].removesuffix("():") for line in guard.unreferenced_exports()}
    assert not (sections & reported), "the guard's own sections are called by `sections()`"
