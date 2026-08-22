"""Negative controls for `scripts/check_model_lifecycle`.

The guard is green against the repo as it stands, which proves nothing on its own —
`return []` is green too. Every test here hands it a DOCTORED table or a DOCTORED clock
and asserts the specific refusal or failure by name, in both directions.

THE TWO CLASSES ARE KEPT APART ON PURPOSE, because conflating them is how a guard learns
to lie: exit 2 means it could not MEASURE (empty allow-list, table that does not cover
it, malformed evidence, unreadable attestation) and exit 1 means it measured and the
answer is bad (a date has passed, nothing survives the lead time, a filed portal reading
contradicts the posture). A test that only asserted "non-zero" would pass on a guard that
had collapsed the two, which is the failure CLAUDE.md's coverage-ratchet rule describes.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest
from calevate_shared.model_lifecycle import (
    ATTESTATION_PATH,
    MODEL_LIFECYCLE,
    WARN_LEAD,
    Evidence,
    ModelLifecycle,
    load_attestation,
)
from scripts import check_model_lifecycle as guard

TODAY = date(2026, 8, 22)


def _entry(name: str, retires_on: date, **kwargs: object) -> ModelLifecycle:
    evidence = Evidence(source="fixture", read_on=TODAY, verified=True)
    base = {
        "model": name,
        "version": "2024-07-18",
        "retires_on": retires_on,
        "stage": "GA",
        "replacement": None,
        "offered_in_region": frozenset({"standard-regional"}),
        "retirement": evidence,
        "availability": evidence,
    }
    base.update(kwargs)
    return ModelLifecycle(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- refusals


def test_empty_allow_list_refuses() -> None:
    """The trap CLAUDE.md names: a guard whose subject vanished must not report OK."""
    problems = guard.refusals(frozenset(), {})
    assert problems
    assert any("AZURE_OPENAI_MODELS is empty" in p for p in problems)


def test_model_without_a_lifecycle_entry_refuses() -> None:
    problems = guard.refusals(frozenset({"gpt-4o-mini", "gpt-9-turbo"}), dict(MODEL_LIFECYCLE))
    assert any("gpt-9-turbo" in p and "no MODEL_LIFECYCLE entry" in p for p in problems)


def test_entry_for_a_model_nobody_can_select_refuses() -> None:
    table = dict(MODEL_LIFECYCLE) | {"gpt-gone": _entry("gpt-gone", date(2030, 1, 1))}
    problems = guard.refusals(frozenset({"gpt-4o-mini", "gpt-4.1-mini"}), table)
    assert any("gpt-gone" in p and "not in AZURE_OPENAI_MODELS" in p for p in problems)


def test_evidence_read_in_the_future_refuses() -> None:
    doctored = replace(
        MODEL_LIFECYCLE["gpt-4o-mini"],
        retirement=Evidence(source="s", read_on=date.today() + timedelta(days=1), verified=True),
    )
    problems = guard.refusals(frozenset({"gpt-4o-mini"}), {"gpt-4o-mini": doctored})
    assert any("in the future" in p for p in problems)


def test_sourceless_evidence_refuses() -> None:
    doctored = replace(
        MODEL_LIFECYCLE["gpt-4o-mini"],
        availability=Evidence(source="", read_on=TODAY, verified=False),
    )
    problems = guard.refusals(frozenset({"gpt-4o-mini"}), {"gpt-4o-mini": doctored})
    assert any("no source" in p for p in problems)


def test_unreadable_attestation_refuses_not_fails(tmp_path: Path) -> None:
    """A filed reading that cannot be parsed is NOT an absent one. Treating it as absent
    would be the quietest possible way to lose somebody's portal reading."""
    path = tmp_path / ATTESTATION_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert guard.main([str(tmp_path)]) == 2


def test_attestation_missing_a_field_refuses(tmp_path: Path) -> None:
    path = tmp_path / ATTESTATION_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"resource_location": "eastus2"}), encoding="utf-8")
    with pytest.raises(ValueError, match="missing required field"):
        load_attestation(tmp_path)


def test_attestation_with_an_invented_deployment_type_refuses(tmp_path: Path) -> None:
    path = tmp_path / ATTESTATION_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "resource_location": "eastus2",
                "deployment_model": "gpt-4o-mini",
                "deployment_type": "Standard-ish",
                "read_on": "2026-08-22",
                "read_by": "founder",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="deployment_type"):
        load_attestation(tmp_path)


def test_absent_attestation_is_a_warning_not_a_refusal(tmp_path: Path) -> None:
    assert load_attestation(tmp_path) is None
    assert guard.main([str(tmp_path)]) == 0


# --------------------------------------------------------------------------- failures


def test_a_date_that_has_passed_is_a_build_failure() -> None:
    table = {
        "gpt-4o-mini": _entry("gpt-4o-mini", TODAY - timedelta(days=1)),
        "gpt-4.1-mini": _entry("gpt-4.1-mini", TODAY + timedelta(days=900)),
    }
    problems = guard.failures(table, TODAY, None)
    assert any("gpt-4o-mini retired on" in p and "1 days ago" in p for p in problems)


def test_retirement_today_counts_as_passed() -> None:
    """`<= 0`, not `< 0`: a model retires ON its date, and a guard that let the last day
    through would be green on the one day it mattered."""
    table = {"gpt-4o-mini": _entry("gpt-4o-mini", TODAY)}
    assert guard.failures(table, TODAY, None)


def test_nothing_outlives_the_lead_time_is_a_build_failure() -> None:
    """'Past its date with no replacement configured' — the replacement half."""
    inside = TODAY + timedelta(days=WARN_LEAD.days - 1)
    table = {"a": _entry("a", inside), "b": _entry("b", inside)}
    problems = guard.failures(table, TODAY, None)
    assert any("NO REPLACEMENT IS CONFIGURED" in p for p in problems)


def test_one_survivor_is_enough() -> None:
    table = {
        "a": _entry("a", TODAY + timedelta(days=WARN_LEAD.days - 1)),
        "b": _entry("b", TODAY + timedelta(days=WARN_LEAD.days + 1)),
    }
    assert guard.failures(table, TODAY, None) == []


def test_attested_global_deployment_is_a_build_failure() -> None:
    attested = guard.Attestation(
        resource_location="eastus2",
        deployment_model="gpt-4o-mini",
        deployment_type="global-standard",
        read_on=TODAY,
        read_by="founder",
        deprecation_date=None,
    )
    problems = guard.failures(dict(MODEL_LIFECYCLE), TODAY, attested)
    assert any("routes worldwide" in p for p in problems)


def test_attested_wrong_region_is_a_build_failure() -> None:
    attested = guard.Attestation(
        resource_location="Sweden Central",
        deployment_model="gpt-4o-mini",
        deployment_type="standard-regional",
        read_on=TODAY,
        read_by="founder",
        deprecation_date=None,
    )
    problems = guard.failures(dict(MODEL_LIFECYCLE), TODAY, attested)
    assert any("residency breach" in p for p in problems)


def test_portal_sku_date_disagreeing_with_the_table_is_a_build_failure() -> None:
    """THE PORTAL WINS. A per-SKU deprecationDate is what a call actually obeys, so a
    silent disagreement with the doc-derived date must not be averaged away."""
    attested = guard.Attestation(
        resource_location="eastus2",
        deployment_model="gpt-4o-mini",
        deployment_type="standard-regional",
        read_on=TODAY,
        read_by="founder",
        deprecation_date=date(2026, 10, 1),
    )
    problems = guard.failures(dict(MODEL_LIFECYCLE), TODAY, attested)
    assert any("THE PORTAL WINS" in p for p in problems)


# --------------------------------------------------------------------------- warnings


def test_inside_the_lead_time_warns_without_failing() -> None:
    table = {
        "a": _entry("a", TODAY + timedelta(days=30)),
        "b": _entry("b", TODAY + timedelta(days=900)),
    }
    assert guard.failures(table, TODAY, None) == []
    assert any("retires in 30 days" in n for n in guard.warnings(table, TODAY, None))


def test_an_unverified_entry_is_visibly_unverified() -> None:
    """'Silently trusted' is the thing the evidence class exists to prevent."""
    notes = guard.warnings(dict(MODEL_LIFECYCLE), TODAY, None)
    assert any("[UNVERIFIED]" in n for n in notes)


def test_a_stale_reading_warns() -> None:
    stale = TODAY - timedelta(days=guard.STALE_AFTER_DAYS + 1)
    old = Evidence(source="s", read_on=stale, verified=True)
    table = {"a": _entry("a", TODAY + timedelta(days=900), retirement=old)}
    assert any("last read" in n for n in guard.warnings(table, TODAY, None))


def test_the_default_not_offered_on_the_mandated_type_is_named() -> None:
    """THE WARNING THAT IS NOW QUIET AGAINST THE SHIPPED TABLE, kept covered by a DOCTORED
    one (D-449).

    It fired for one release and what it caught was not a doc detail: on Microsoft's own
    Standard (regional) matrix the shipped default was not offered in `southindia`, so the
    only permitted region and the only permitted SKU could not run the model this product
    ships. That was resolved by moving the REGION (`eastus2`), which is why the shipped
    table no longer trips it.

    THE BRANCH STAYS AND SO DOES THIS TEST, for two reasons. It is the only thing that
    would notice the same defect arriving from the other direction — a new allow-list
    member, or another region move, that the mandated SKU does not serve — and that failure
    is silent until a call 404s mid-conversation. And an uncovered branch is a coverage
    ratchet failure, so a quiet branch with no test is a branch somebody deletes to make
    the number go down.

    It is stated against a doctored table rather than the real one BECAUSE the real one is
    green: a test that could only pass while the tree had the defect would have to be
    deleted the day the defect was fixed, which is how a guard loses its negative control.
    """
    assert not any(
        "CONTRADICTS THE SHIPPED DEFAULT" in n
        for n in guard.warnings(dict(MODEL_LIFECYCLE), TODAY, None)
    ), "the shipped table trips this warning again — the region or the default has moved"

    from calevate_shared.engine import AZURE_OPENAI_DEFAULT_MODEL

    doctored = {
        AZURE_OPENAI_DEFAULT_MODEL: _entry(
            AZURE_OPENAI_DEFAULT_MODEL,
            TODAY + timedelta(days=900),
            offered_in_region=frozenset({"global-standard"}),
        ),
        "other-model": _entry("other-model", TODAY + timedelta(days=900)),
    }
    notes = guard.warnings(doctored, TODAY, None)
    named = [n for n in notes if "CONTRADICTS THE SHIPPED DEFAULT" in n]
    assert len(named) == 1, notes
    assert "global-standard" in named[0] and "other-model" in named[0], named
    # And it names the way OUT, which is the half that makes it actionable: either the
    # default moves to a model the region serves, or the region moves — and the second is
    # a residency decision with a decision-log entry, the way D-449 was.
    assert "REGION moves" in named[0], named


def test_the_shipped_table_covers_the_shipped_allow_list() -> None:
    from calevate_shared.engine import AZURE_OPENAI_MODELS

    assert guard.refusals(AZURE_OPENAI_MODELS, dict(MODEL_LIFECYCLE)) == []


def test_the_repo_as_it_stands_passes() -> None:
    assert guard.main() == 0
