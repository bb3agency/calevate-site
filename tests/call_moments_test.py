"""Key moments: the anchors a client jumps to instead of playing the call again.

The claims here are ranked by what a wrong answer costs, and the first one is the whole
design:

1. **A derived marker is never a guess.** `anchor_of` returns the turn's own `start_ms`
   or None — never a nearby turn, never an approximation. A panel whose timestamps are
   sometimes right is worse than no panel, because the first time it sends someone to the
   wrong part of a forty-minute call they stop trusting every marker in it.
2. **A derived label carries no caller data.** It names the field and the time, never the
   value (hard rule 6). The value is already on the same screen under its own redaction.
3. **The redaction switch is the transcript's.** A model-authored label quotes the caller,
   so the redacted form is what a client sees and the raw one needs the same audited
   endpoint the raw transcript needs (hard rule 5).
4. **A marker cannot outlive the extraction it indexes.** All three erasure sweeps clear
   `moments` with `data`; a marker surviving one is a second copy of erased personal data
   under a column added after the sweep was written — the D-126 shape.
5. **Malformed storage degrades, never 500s.** The column is written by a worker and read
   by a request; a `kind` a later release retires must cost one row of a navigation aid,
   not a client's call detail.

Run: uv run pytest -q tests/call_moments_test.py
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from apps.api.crm.service import _moments_out, get_call
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers import retention
from apps.workers.extraction import ExtractionOutput
from apps.workers.moments import (
    MAX_MOMENTS,
    MIN_ANCHOR_CHARS,
    anchor_of,
    derive_moments,
    merge_moments,
)
from apps.workers.pipeline import _persist_extraction
from sqlalchemy import text
from tests.pipeline_audit_test import _completed_call

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class _Turn:
    """EXACTLY the Protocol `moments.Turn` names, and nothing else.

    No `speaker`, deliberately: the module does not read it, so a fixture that carries one
    would let the Protocol grow a requirement without any test noticing. This class
    failing to construct IS the signal that the Protocol widened.
    """

    idx: int
    text: str
    start_ms: int | None


def _turns(*rows: tuple[int, str, str, int | None]) -> list[Any]:
    """`rows` keeps the speaker column for readability at the call sites — a transcript
    fixture that does not say who spoke is hard to read — and drops it on the way in."""
    return [_Turn(idx=i, text=t, start_ms=ms) for i, _speaker, t, ms in rows]


CALL = _turns(
    (0, "agent", "Namaskaram, this is an AI assistant for Sri Clinic.", 0),
    (1, "caller", "I want an appointment on Tuesday at four.", 8_000),
    (2, "agent", "Tuesday 4pm works. May I have a number?", 15_000),
    (3, "caller", "It is 9876543210.", 21_000),
    (4, "caller", "Actually please do not call me again.", 34_000),
)


# --- 1. the anchor is proven or it is absent ----------------------------------


def test_a_value_anchors_to_the_turn_that_actually_contains_it() -> None:
    assert anchor_of("Tuesday at four", CALL) == 8_000
    assert anchor_of("9876543210", CALL) == 21_000


def test_the_earliest_turn_wins_when_a_value_is_repeated() -> None:
    """The caller says it, the agent reads it back. The moment worth jumping to is the one
    where the information ARRIVED, not the confirmation."""
    assert anchor_of("Tuesday", CALL) == 8_000


def test_a_value_nobody_said_verbatim_produces_no_anchor_at_all() -> None:
    """THE CENTRAL CLAIM. Extraction normalises — "tuesday at four" becomes "Tuesday 4pm",
    and a model may return a value in a form the transcript never contains. Missing the
    marker is the correct outcome; placing it at a plausible-looking turn is not.

    This is also why there is no fuzzy match here. Fuzzy matching would raise the hit rate
    and destroy the only property that makes a derived marker worth more than a model's.
    """
    assert anchor_of("Wednesday 9am", CALL) is None


def test_a_turn_with_no_offset_cannot_anchor_anything() -> None:
    """`TranscriptTurn.start_ms` is nullable and an engine that supplies no per-turn
    offsets is supported. Such a call simply carries no derived markers."""
    untimed = _turns((0, "caller", "Tuesday at four", None))
    assert anchor_of("Tuesday at four", untimed) is None


def test_a_value_too_short_to_be_distinctive_is_refused() -> None:
    """ "5" occurs in half the turns of any call that mentions a time. A marker that lands
    on the wrong one is confidently wrong, which is the failure this whole module is shaped
    to avoid."""
    short = _turns((0, "caller", "Table for 5 at 5, on the 5th", 1_000))
    assert anchor_of("5", short) is None
    assert len("5") < MIN_ANCHOR_CHARS


def test_a_boolean_never_anchors_on_the_word_that_spells_it() -> None:
    """`True` is not a thing anyone said. Without the guard, `str(True)` is "True", which
    casefolds to "true" and matches any turn containing the word — so a boolean field
    would silently anchor to whatever sentence happened to say "true"."""
    saying = _turns((0, "caller", "That is true, I did call before.", 2_000))
    assert anchor_of(True, saying) is None
    assert anchor_of(None, saying) is None


# --- 2. what a derived marker says --------------------------------------------


def test_a_derived_label_names_the_field_and_never_the_value() -> None:
    """Hard rule 6 on a new surface. The caller's number is captured, and the marker says
    a number was captured and when — the digits stay in the panel that already governs
    them."""
    moments = derive_moments(
        turns=CALL,
        extraction={"phone": "9876543210", "slot": "Tuesday at four"},
        field_labels={"phone": "Callback number", "slot": "Appointment slot"},
    )
    labels = [m["label"] for m in moments]
    assert labels == ["Appointment slot captured", "Callback number captured"]
    for moment in moments:
        assert "9876543210" not in moment["label"]
        assert moment["label_redacted"] == moment["label"], (
            "a derived label has no raw form to hide — if these ever differ, a value has "
            "found its way into one of them"
        )


def test_derived_markers_come_back_in_time_order() -> None:
    """The panel is a table of contents. In dictionary order it is a list."""
    moments = derive_moments(
        turns=CALL,
        extraction={"phone": "9876543210", "slot": "Tuesday at four"},
        field_labels={},
        opt_out_turn_idx=4,
    )
    assert [m["at_ms"] for m in moments] == sorted(m["at_ms"] for m in moments)
    assert [m["at_ms"] for m in moments] == [8_000, 21_000, 34_000]


def test_the_opt_out_marker_points_at_the_turn_the_detector_named() -> None:
    """The one marker that is a compliance fact rather than a convenience: `consent_ledger`
    stores the matched words but no place in the audio, and a reviewer asked why a number
    stopped being dialled needs to hear the sentence."""
    moments = derive_moments(turns=CALL, extraction={}, field_labels={}, opt_out_turn_idx=4)
    assert [(m["kind"], m["at_ms"]) for m in moments] == [("opt_out", 34_000)]
    assert moments[0]["source"] == "derived"


def test_an_opt_out_on_the_in_call_path_carries_no_marker() -> None:
    """`OptOutSignal.turn_idx` is None when the engine's tool call raised it — there is no
    turn of ours to point at, and inventing one would put a number in the evidence that
    means nothing (the detector's own docstring says so)."""
    assert derive_moments(turns=CALL, extraction={}, field_labels={}, opt_out_turn_idx=None) == []


def test_a_field_label_the_client_never_set_falls_back_readably() -> None:
    """The schema is the client's product copy, so their words win — but a key with no
    label must not render as `appointment_slot captured`."""
    moments = derive_moments(
        turns=CALL, extraction={"appointment_slot": "Tuesday at four"}, field_labels={}
    )
    assert moments[0]["label"] == "Appointment slot captured"


# --- 3. merging, and which half gives way ------------------------------------


def _model(at_ms: int, label: str = "Caller raised a concern") -> dict[str, Any]:
    return {
        "at_ms": at_ms,
        "kind": "highlight",
        "label": label,
        "label_redacted": label,
        "source": "model",
    }


def test_a_model_marker_on_top_of_a_derived_one_is_dropped() -> None:
    """Two entries a second apart describing one moment read as two moments, and the
    derived one already says the true thing."""
    derived = derive_moments(turns=CALL, extraction={}, field_labels={}, opt_out_turn_idx=4)
    merged = merge_moments(derived, [_model(34_500), _model(50_000)])
    assert [m["at_ms"] for m in merged] == [34_000, 50_000]


def test_the_cap_falls_on_the_model_half_and_never_on_the_derived_one() -> None:
    """THE PRIORITY THAT MATTERS. Dropping a provable anchor to make room for a suggested
    one trades a timestamp that is certainly right for one that is probably right — the
    wrong direction on a panel whose value is that you can trust where it sends you."""
    many = _turns(*[(i, "caller", f"marker number {i:02d}", i * 1_000) for i in range(20)])
    derived = derive_moments(
        turns=many,
        extraction={f"f{i}": f"marker number {i:02d}" for i in range(20)},
        field_labels={},
    )
    assert len(derived) == 20, "the fixture must exceed the cap or this proves nothing"

    merged = merge_moments(derived, [_model(500_000)])
    assert all(m["source"] == "derived" for m in merged), "a model marker displaced a provable one"
    assert len(merged) == 20


def test_model_markers_fill_only_the_room_the_cap_leaves() -> None:
    derived = derive_moments(turns=CALL, extraction={}, field_labels={}, opt_out_turn_idx=4)
    merged = merge_moments(derived, [_model(60_000 + i * 5_000) for i in range(30)])
    assert len(merged) == MAX_MOMENTS
    assert sum(1 for m in merged if m["source"] == "derived") == 1


# --- 4. the read path: redaction, and degrading rather than exploding ---------


def test_the_wire_label_follows_the_same_switch_as_the_transcript() -> None:
    """Hard rule 5. A model label quotes the caller, so the redacted form is the default
    and the raw one is reachable only through the endpoint that audits the read."""
    stored = [
        {
            "at_ms": 21_000,
            "kind": "highlight",
            "label": "Caller gave 9876543210 as the callback",
            "label_redacted": "Caller gave [phone] as the callback",
            "source": "model",
        }
    ]
    assert _moments_out(stored, raw=False)[0].label == "Caller gave [phone] as the callback"
    assert _moments_out(stored, raw=True)[0].label == "Caller gave 9876543210 as the callback"


def test_a_marker_shape_a_later_release_retired_is_dropped_not_raised_on() -> None:
    """The column is written by a worker and read by a request. A `kind` removed in a
    deploy must cost one row of a navigation aid, not turn every affected client's call
    detail into a 500 until the data is migrated."""
    good = {
        "at_ms": 1_000,
        "kind": "opt_out",
        "label": "ok",
        "label_redacted": "ok",
        "source": "derived",
    }
    rubbish: list[Any] = [
        good,
        {
            "at_ms": 2_000,
            "kind": "a_kind_we_retired",
            "label": "x",
            "label_redacted": "x",
            "source": "derived",
        },
        {
            "at_ms": "not a number",
            "kind": "opt_out",
            "label": "x",
            "label_redacted": "x",
            "source": "derived",
        },
        {"kind": "opt_out", "label": "x", "label_redacted": "x", "source": "derived"},
        "a bare string",
        None,
    ]
    out = _moments_out(rubbish, raw=False)
    assert [m.at_ms for m in out] == [1_000]


def test_a_call_with_no_moments_column_yet_reads_as_an_empty_list() -> None:
    """NULL is every row written before this feature existed. It is not an error and it is
    not a marker; the screen hides the panel and says nothing."""
    assert _moments_out(None, raw=False) == []
    assert _moments_out([], raw=True) == []


def test_the_wire_order_is_time_order_whatever_the_column_holds() -> None:
    """The worker sorts, but the column is JSON a migration or a hand-fix could reorder.
    The screen must not have to."""
    stored = [
        {
            "at_ms": 9_000,
            "kind": "opt_out",
            "label": "b",
            "label_redacted": "b",
            "source": "derived",
        },
        {
            "at_ms": 1_000,
            "kind": "opt_out",
            "label": "a",
            "label_redacted": "a",
            "source": "derived",
        },
    ]
    assert [m.at_ms for m in _moments_out(stored, raw=False)] == [1_000, 9_000]


def test_a_moment_that_lost_its_redacted_label_falls_back_to_the_raw_one() -> None:
    """Deliberately NOT a drop. A marker written before `label_redacted` existed, or by a
    path that forgot it, still has a raw label — and for a DERIVED marker the two are the
    same string by construction, so falling back shows the right thing. The alternative,
    dropping it, would silently empty the panel for a whole class of stored rows.

    """
    stored = [{"at_ms": 5_000, "kind": "opt_out", "label": "kept", "source": "derived"}]
    out = _moments_out(stored, raw=False)
    assert [m.label for m in out] == ["kept"]


def test_a_model_moment_with_no_redacted_label_is_dropped_rather_than_leaked() -> None:
    """The other half of the same fallback, and the reason it reads `source` at all.

    A model label quotes the caller. If its redacted form is missing — a restore, a
    hand-fix, a release that changed the shape — falling back to the raw one would print
    unredacted caller text in the view whose entire promise is that it does not (hard
    rule 5). Losing one navigation row is the correct price.

    The first version of this fallback did trust the writer to set both keys. That is the
    assumption every redaction defect in this repo has been made of.
    """
    leaky = [
        {
            "at_ms": 5_000,
            "kind": "highlight",
            "label": "Caller gave 9876543210",
            "source": "model",
        }
    ]
    assert _moments_out(leaky, raw=False) == []
    # ...and the audited raw view still shows it, because that view is allowed to.
    assert [m.label for m in _moments_out(leaky, raw=True)] == ["Caller gave 9876543210"]


def test_the_module_and_the_wire_agree_on_the_closed_sets() -> None:
    """`moments.MomentKind`/`MomentSource` are what the worker may write;
    `CallMomentOut` is what the API will accept. Two closed sets that drift make a
    worker whose output the read path silently discards — which would present as an
    empty panel with no error anywhere.
    """
    from typing import get_args

    from apps.api.crm.schemas import CallMomentOut
    from apps.workers.moments import MomentKind, MomentSource

    wire_kinds = set(get_args(CallMomentOut.model_fields["kind"].annotation))
    wire_sources = set(get_args(CallMomentOut.model_fields["source"].annotation))
    assert set(get_args(MomentKind)) == wire_kinds
    assert set(get_args(MomentSource)) == wire_sources


def test_every_derived_marker_the_module_emits_survives_the_wire() -> None:
    """The end-to-end version of the check above, driven rather than compared: whatever
    `derive_moments` produces must come back out of `_moments_out` unchanged in count."""
    derived = derive_moments(
        turns=CALL,
        extraction={"phone": "9876543210", "slot": "Tuesday at four"},
        field_labels={"phone": "Callback number"},
        opt_out_turn_idx=4,
    )
    assert len(_moments_out(derived, raw=False)) == len(derived) == 3


# ============================================================================
# The seam, against a real database: written by the worker, read by the API,
# erased by the sweep.
# ============================================================================
#
# The three unit sections above prove the arithmetic. This one proves the COLUMN — that
# what `_persist_extraction` writes is what `get_call` returns, and that the DPDP sweep
# takes it away. A feature whose every part is unit-tested and whose seam is not is the
# `archive_payload` shape: a column, an eraser, a screen, and nothing joining them.


async def test_a_marker_written_by_the_worker_is_read_back_by_the_api() -> None:
    """Worker → `call_extractions.moments` → `get_call` → the client's screen.

    Driven through the REAL persist function and the REAL read, because the two are
    written in different modules by different rules — one speaks SQL and JSONB, the other
    speaks Pydantic and the redaction switch — and the way this breaks is a shape
    mismatch that no unit test on either side can see.
    """
    tenant_id, _execution_id, call_id = await _completed_call("mom")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                "text_redacted, start_ms, created_at, updated_at) VALUES "
                "(:i, :t, :c, 0, 'caller', 'I need Tuesday at four', "
                "'I need Tuesday at four', 8000, now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "c": call_id},
        )

    moments = derive_moments(
        turns=[_Turn(idx=0, text="I need Tuesday at four", start_ms=8_000)],
        extraction={"slot": "Tuesday at four"},
        field_labels={"slot": "Appointment slot"},
    )
    await _persist_extraction(
        tenant_id,
        call_id,
        ExtractionOutput(data={"slot": "Tuesday at four"}, valid=True, errors={}),
        schema_version=1,
        moments=moments,
    )

    async with tenant_session(tenant_id) as session:
        detail = await get_call(session, call_id, raw=False)
    assert [(m.at_ms, m.label, m.source) for m in detail.moments] == [
        (8_000, "Appointment slot captured", "derived")
    ]


async def test_a_needs_review_flag_written_by_the_worker_is_read_back_by_the_api() -> None:
    """P4, the same worker→JSONB→Pydantic seam as the moments test above and for the same
    reason: `needs_review` is written as SQL/JSONB by the pipeline and read as a Pydantic
    map through the redaction switch, and a shape mismatch is invisible to a unit test on
    either side. The reason carries no digits (hard rule 6) even though the value does."""
    tenant_id, _execution_id, call_id = await _completed_call("nr")
    await _persist_extraction(
        tenant_id,
        call_id,
        ExtractionOutput(
            data={"callback_number": "1234567890"},
            valid=True,
            errors={},
            needs_review={
                "callback_number": "Callback number was captured but is not a "
                "standard Indian mobile number — check it before dialling."
            },
        ),
        schema_version=1,
        moments=None,
    )

    async with tenant_session(tenant_id) as session:
        detail = await get_call(session, call_id, raw=False)
    assert detail.extraction["callback_number"] == "1234567890"
    assert "callback_number" in detail.extraction_needs_review
    assert "1234567890" not in detail.extraction_needs_review["callback_number"]


async def test_the_scheduled_sweep_clears_the_markers_with_the_extraction() -> None:
    """A marker names what the caller said and when. Leaving it behind after the
    extraction is emptied is a second copy of erased personal data surviving under a
    column added long after the sweep was written — the D-126 shape, which this repo has
    already paid for once.

    Drives `_EXTRACTION_SQL` itself rather than the whole retention tick: that statement
    IS the thing that was edited, and running it directly means the assertion cannot pass
    because some other arm of the sweep happened to skip this row.
    """
    tenant_id, _execution_id, call_id = await _completed_call("erase")
    await _persist_extraction(
        tenant_id,
        call_id,
        ExtractionOutput(data={"slot": "Tuesday"}, valid=True, errors={}),
        schema_version=1,
        moments=[
            {
                "at_ms": 1_000,
                "kind": "opt_out",
                "label": "Caller asked not to be called again",
                "label_redacted": "Caller asked not to be called again",
                "source": "derived",
            }
        ],
    )
    async with tenant_session(tenant_id) as session:
        before = (
            await session.execute(
                text("SELECT moments FROM call_extractions WHERE call_id = :c"), {"c": call_id}
            )
        ).scalar()
    assert before, "the fixture must have written markers or the erasure proves nothing"

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(retention._EXTRACTION_SQL),
            {"cutoff": datetime.now(UTC) + timedelta(days=1), "batch": 100},
        )
        row = (
            await session.execute(
                text("SELECT data, moments FROM call_extractions WHERE call_id = :c"),
                {"c": call_id},
            )
        ).first()
    assert row is not None
    assert row[0] == {}, "the extraction itself must be empty"
    assert row[1] is None, (
        "the markers outlived the extraction they index — a caller's words, still on file "
        "after a certificate said they were destroyed"
    )


def test_every_statement_that_empties_an_extraction_also_clears_its_markers() -> None:
    """THE GUARD, because there are THREE erasure sites and a fourth is a plausible edit.

    `workers/retention.py` empties `call_extractions.data` in three separate statements —
    the scheduled sweep, the DPDP request path and the tenant erasure — and each one had
    to learn about `moments` independently. A fifth column added tomorrow will have the
    same problem, and the test above only drives one of the three.

    Read off the source rather than the database: the defect is a statement someone wrote
    without the new column, which exists in the file before it ever runs.
    """
    source = (REPO_ROOT / "apps" / "workers" / "retention.py").read_text(encoding="utf-8")
    # Each statement, from `UPDATE call_extractions` to its WHERE, however it is wrapped
    # across string literals and lines.
    statements = re.findall(r"UPDATE\s+call_extractions.*?(?=WHERE)", source, flags=re.DOTALL)
    assert len(statements) == 3, (
        f"expected the three known erasure sites, found {len(statements)} — a new one was "
        "added, and it needs the same audit this test performs"
    )
    for statement in statements:
        flat = " ".join(statement.split()).replace('" "', "")
        assert "data = '{}'::jsonb" in flat, flat
        assert "moments = NULL" in flat, (
            f"an erasure empties the extraction and leaves its key moments behind: {flat}"
        )
