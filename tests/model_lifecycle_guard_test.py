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
from calevate_shared.engine import Evidence
from calevate_shared.model_lifecycle import (
    ATTESTATION_PATH,
    MODEL_LIFECYCLE,
    WARN_LEAD,
    ModelLifecycle,
    load_attestation,
)
from scripts import check_model_lifecycle as guard

TODAY = date(2026, 8, 22)


def _entry(name: str, retires_on: date | None, **kwargs: object) -> ModelLifecycle:
    evidence = Evidence(source="fixture", read_on=TODAY, verified=True)
    base = {
        "model": name,
        "provider": "azure_openai",
        "version": "2024-07-18",
        "retires_on": retires_on,
        # DERIVED FROM THE DATE, so a fixture cannot express the incoherent pair
        # `ModelLifecycle.__post_init__` refuses — and so the several dozen call sites below
        # that only care about a date do not each have to restate the stance. A test that
        # wants the third stance ("nobody read the page") passes it explicitly, which is
        # exactly the one case worth spelling out at a call site.
        "retirement_stance": "dated" if retires_on is not None else "none-announced",
        "stage": "GA",
        "replacement": None,
        "offered_in_region": frozenset({"standard-regional"}),
        "retirement": evidence,
        "availability": evidence,
    }
    base.update(kwargs)
    return ModelLifecycle(**base)  # type: ignore[arg-type]


def _all_selectable(table: dict[str, ModelLifecycle]) -> frozenset[str]:
    """Every model in a DOCTORED table, handed to the guard as the selectable set.

    THE SEAM EXISTS BECAUSE THE SPLIT DOES. `failures()` scores only models somebody can
    choose — a retired model nobody may run is a dated record, not a build failure — so a
    doctored table whose names are in no real catalogue would otherwise be scored against an
    EMPTY selectable set and every failure case below would pass for the wrong reason.
    """
    return frozenset(table)


# --------------------------------------------------------------------------- refusals


def test_empty_allow_list_refuses() -> None:
    """The trap CLAUDE.md names: a guard whose subject vanished must not report OK."""
    problems = guard.refusals(frozenset(), {})
    assert problems
    assert any("LLM_MODEL_NAMES is empty" in p for p in problems)


def test_model_without_a_lifecycle_entry_refuses() -> None:
    problems = guard.refusals(frozenset({"gpt-4o-mini", "gpt-9-turbo"}), dict(MODEL_LIFECYCLE))
    assert any("gpt-9-turbo" in p and "no MODEL_LIFECYCLE entry" in p for p in problems)


def test_entry_for_a_model_nobody_can_select_refuses() -> None:
    table = dict(MODEL_LIFECYCLE) | {"gpt-gone": _entry("gpt-gone", date(2030, 1, 1))}
    problems = guard.refusals(frozenset({"gpt-4o-mini", "gpt-4.1-mini"}), table)
    assert any("gpt-gone" in p and "not in LLM_MODEL_NAMES" in p for p in problems)


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
    problems = guard.failures(table, TODAY, None, _all_selectable(table))
    assert any("gpt-4o-mini retired on" in p and "1 days ago" in p for p in problems)


def test_retirement_today_counts_as_passed() -> None:
    """`<= 0`, not `< 0`: a model retires ON its date, and a guard that let the last day
    through would be green on the one day it mattered."""
    table = {"gpt-4o-mini": _entry("gpt-4o-mini", TODAY)}
    assert guard.failures(table, TODAY, None, _all_selectable(table))


def test_nothing_outlives_the_lead_time_is_a_build_failure() -> None:
    """'Past its date with no replacement configured' — the replacement half."""
    inside = TODAY + timedelta(days=WARN_LEAD.days - 1)
    table = {"a": _entry("a", inside), "b": _entry("b", inside)}
    problems = guard.failures(table, TODAY, None, _all_selectable(table))
    assert any("NO REPLACEMENT IS CONFIGURED" in p for p in problems)


def test_one_survivor_is_enough() -> None:
    table = {
        "a": _entry("a", TODAY + timedelta(days=WARN_LEAD.days - 1)),
        "b": _entry("b", TODAY + timedelta(days=WARN_LEAD.days + 1)),
    }
    assert guard.failures(table, TODAY, None, _all_selectable(table)) == []


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
    selectable = _all_selectable(table)
    assert guard.failures(table, TODAY, None, selectable) == []
    assert any("retires in 30 days" in n for n in guard.warnings(table, TODAY, None, selectable))


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


def test_the_shipped_table_covers_the_shipped_catalogue() -> None:
    """Every model on every declared leg, not only the Azure ones. The widening is the whole
    of what a second and third leg cost this registry: a withdrawn model is exactly the kind
    that sits undated for a year, and `gemini-2.5-flash` has 55 days on it."""
    from calevate_shared.engine import LLM_MODEL_NAMES

    assert guard.refusals(LLM_MODEL_NAMES, dict(MODEL_LIFECYCLE)) == []


def test_the_repo_as_it_stands_passes() -> None:
    assert guard.main() == 0


# --------------------------------------------------- three legs, three evidence classes


def test_an_undated_model_nobody_can_select_is_fine() -> None:
    """`retires_on=None` is a READING, not a blank, and this is the arm that makes it usable.

    Microsoft publishes a dated retirement schedule this repository can read at a named
    commit. OpenAI publishes deprecations on a page every egress path here refuses. Inventing
    a far-off date to satisfy a `date` annotation would be the D-31/D-32 error class — a
    guess wearing the shape of a fact — so the registry records the absence and the guard
    tolerates it on a model nobody may run.
    """
    table = {
        "gpt-5.9-imaginary": _entry(
            "gpt-5.9-imaginary", None, provider="openai", offered_in_region=frozenset()
        )
    }
    assert guard.refusals(frozenset(table), table, frozenset(), {}) == []
    assert guard.failures(table, TODAY, None, frozenset()) == []


def test_an_unread_model_somebody_can_select_refuses_to_score() -> None:
    """The other arm, and the whole reason `retires_on` is allowed to be `None` at all.

    An unread date is honest. An unread date under a model an operator or a client can flip a
    live picker onto is the exact state this guard exists to end — so it REFUSES rather than
    warns: the answer is not "act sooner", it is "you cannot measure this and you are running
    it anyway".
    """
    table = {
        "gpt-5.9-imaginary": _entry(
            "gpt-5.9-imaginary",
            None,
            provider="openai",
            retirement_stance="unread",
            offered_in_region=frozenset(),
        )
    }
    problems = guard.refusals(frozenset(table), table, frozenset(table), {})
    assert len(problems) == 1, problems
    assert "NOBODY HAS READ" in problems[0] and "withdrawn_reason" in problems[0]


def test_a_read_page_announcing_nothing_is_selectable_where_an_unread_one_is_not() -> None:
    """**THE DISTINCTION HARD RULE 11 WAS WRITTEN ABOUT, asserted rather than described.**

    Both entries carry `retires_on=None` and they are opposite facts: one says the vendor's
    own deprecation page lists the identifier with no shutdown date, the other says nobody
    opened it. Collapsing them is what forced a choice between refusing a durable GA model
    and inventing a date for it — and inventing one is what happened: a REPORTED 2026-10-16
    belonging to a preview snapshot sat under two GA Gemini rows and was restated downstream
    as fact.

    FAILS IF: `refusals()` goes back to testing `retires_on is None`, which would make the
    two rows below indistinguishable again.
    """
    read = _entry("gemini-x-flash", None, provider="google", offered_in_region=frozenset())
    unread = _entry(
        "gemini-y-flash",
        None,
        provider="google",
        retirement_stance="unread",
        offered_in_region=frozenset(),
    )
    assert read.retirement_stance == "none-announced"
    table = {read.model: read, unread.model: unread}
    problems = guard.refusals(frozenset(table), table, frozenset(table), {})
    assert len(problems) == 1, problems
    assert unread.model in problems[0] and read.model not in problems[0]


def test_a_none_announced_entry_needs_a_page_somebody_actually_read() -> None:
    """ "The vendor announced nothing" is a claim about the outside world, so it needs a
    reading — an unverifiable one is a guess wearing the shape of a fact (hard rule 11).

    Enforced on the RECORD rather than in the guard, so a hand-built entry in a unit test
    cannot express the state either. FAILS IF that invariant moves into a check somebody can
    run selectively.
    """
    with pytest.raises(ValueError, match="announced no retirement"):
        _entry(
            "gemini-z-flash",
            None,
            provider="google",
            offered_in_region=frozenset(),
            retirement=Evidence(source="a tracker", read_on=TODAY, verified=False),
        )


def test_a_stance_that_disagrees_with_its_own_date_is_refused() -> None:
    """Both directions of the coherence invariant, on the record itself."""
    for stance, retires_on in (("dated", None), ("none-announced", date(2027, 1, 1))):
        with pytest.raises(ValueError, match="retirement_stance"):
            _entry(
                "gpt-incoherent",
                retires_on,
                retirement_stance=stance,
                offered_in_region=frozenset(),
                provider="openai",
            )


def test_a_deployment_type_on_a_leg_that_has_none_refuses() -> None:
    """Regional availability matrices and SKUs are AZURE facts.

    On a leg with no deployments there is no SKU for a model to be offered on, so a non-empty
    reading is a fact nobody could have read — and it would make the availability warning
    fire about a matrix that does not exist for that vendor.
    """
    table = {
        "gemini-x": _entry(
            "gemini-x",
            TODAY + timedelta(days=900),
            provider="google",
            offered_in_region=frozenset({"standard-regional"}),
        )
    }
    problems = guard.refusals(frozenset(table), table, frozenset(), {})
    assert any("no deployment types at all" in p for p in problems), problems

    # …and empty is correct on that leg rather than merely tolerated.
    fine = {
        "gemini-x": _entry(
            "gemini-x",
            TODAY + timedelta(days=900),
            provider="google",
            offered_in_region=frozenset(),
        )
    }
    assert guard.refusals(frozenset(fine), fine, frozenset(), {}) == []


def test_two_registries_disagreeing_about_a_models_leg_refuses() -> None:
    """Which leg a model runs on decides its endpoint, its credential entry and which human
    gate is owed. Two registries name it — this one and `LLM_MODELS` — and they are written
    by hand in different files on purpose, so disagreement means one of them is describing a
    model that does not exist and every per-leg reading is aimed wrong."""
    table = {"gpt-4o-mini": _entry("gpt-4o-mini", TODAY + timedelta(days=900), provider="openai")}
    catalogue = {"gpt-4o-mini": MODEL_LIFECYCLE["gpt-4o-mini"]}  # .provider is azure_openai
    problems = guard.refusals(frozenset(table), table, frozenset(), catalogue)
    assert any("two answers is none" in p for p in problems), problems


def test_a_retired_model_nobody_can_select_warns_instead_of_failing() -> None:
    """THE SPLIT THIS GUARD LEARNED WHEN THE CATALOGUE OPENED, and it is the one that keeps
    both halves honest.

    A retired model an operator can flip a live switch onto is a 410 Gone on the next call
    and must turn the build red. A retired model nobody may choose is the dated record of WHY
    it is withdrawn — `gemini-2.5-flash` is in the table precisely because Google turns it
    off on 16 Oct 2026 — and failing the build on the day its own refusal comes true is a
    countdown to a day nobody can act on, which is what D-410 deleted and what teaches a
    reader to ignore a red build.

    FAILS IF: `failures()` goes back to scoring the whole table, which would turn this
    repository red on 16 Oct 2026 over a model no client can reach.
    """
    table = {
        "gemini-old": _entry(
            "gemini-old",
            TODAY - timedelta(days=1),
            provider="google",
            offered_in_region=frozenset(),
        )
    }
    assert guard.failures(table, TODAY, None, frozenset()) == []
    notes = guard.warnings(table, TODAY, None, frozenset())
    assert any("retired 1 days ago" in n and "withdrawn" in n for n in notes), notes
    assert any("dated record of why it is not on offer" in n for n in notes), notes

    # …and the same entry, selectable, is a build failure.
    assert guard.failures(table, TODAY, None, frozenset(table))


def test_both_kinds_of_missing_date_are_reported_on_every_run_and_read_differently() -> None:
    """The per-leg difference, made visible rather than left in a docstring — in TWO
    sentences now, because a missing date means two opposite things.

    `none-announced` is a reading and is reported as PERISHABLE: it was true on the day the
    page was opened, both legs that carry it have egress-blocked deprecation pages, and no
    run can ever re-check it. `unread` is reported as the block it is. A single sentence
    covering both is what let the wrong one be believed.
    """
    notes = guard.warnings(dict(MODEL_LIFECYCLE), TODAY, None)
    announced = [n for n in notes if "NO SHUTDOWN IS ANNOUNCED" in n]
    unread = [n for n in notes if "NOBODY HAS READ A RETIREMENT PAGE" in n]

    assert {n.split()[1] for n in announced} == {
        "(google,",
        "(openai,",
    } or announced, announced
    assert all("Re-read at the next rate-card review" in n for n in announced), announced
    # Every selectable model with no date is in the read half, and nothing in the unread
    # half is selectable — which is `refusals()`'s rule, restated where a reader meets it.
    assert all("SELECTABLE" not in n for n in unread), unread
    assert unread, notes


def test_the_shipped_gemini_ga_rows_carry_no_shutdown_and_are_selectable() -> None:
    """**THE CORRECTION, PINNED SO IT CANNOT SILENTLY REVERT.**

    This test used to assert the opposite — that both rows carried `2026-10-16` and that
    neither was selectable — and it passed, because the registry it was checking was wrong.
    Google's own deprecations page (dated 13 Aug 2026) lists both GA identifiers with NO
    shutdown date; 16 Oct belonged to dated PREVIEW snapshots this repository has never
    shipped. The bad date was read back out of `model_lifecycle.py` by later sessions,
    restated as fact in `docs/evidence/`, and became the premise for withdrawing the whole
    Google leg — which is why hard rule 11 exists and why the assertion is now stated over
    the STANCE rather than over a literal date.

    FAILS IF: a GA Gemini row grows a shutdown date without somebody re-reading the page, or
    drops back to `unread`, or leaves the selectable set.
    """
    from calevate_shared.engine import SELECTABLE_LLM_MODELS

    for name in ("gemini-2.5-flash", "gemini-2.5-flash-lite"):
        entry = MODEL_LIFECYCLE[name]
        assert entry.provider == "google"
        assert entry.retirement_stance == "none-announced", name
        assert entry.retires_on is None, name
        assert entry.days_left(TODAY) is None, name
        # The reading has to be a reading: `__post_init__` refuses `none-announced` on
        # unverified evidence, and this pins the page it names as well.
        assert entry.retirement.verified, name
        assert "deprecations" in entry.retirement.source, name
        assert name in SELECTABLE_LLM_MODELS, name
        # NO REPLACEMENT IS NAMED, and that is deliberate: this row used to point at
        # `gemini-3.6-flash`, which is not on the engine's published supported-model list at
        # all, so it was a migration target nothing could be configured onto.
        assert entry.replacement is None, name


def test_an_attestation_naming_a_model_from_another_leg_is_a_build_failure() -> None:
    """An Azure attestation describes an Azure deployment. A model from another leg has no
    deployment to attest, and the thing that is deployed must be something this repository
    can price and date."""
    attested = guard.Attestation(
        resource_location="eastus2",
        deployment_model="gemini-2.5-flash",
        deployment_type="standard-regional",
        read_on=TODAY,
        read_by="founder",
        deprecation_date=None,
    )
    problems = guard.failures(dict(MODEL_LIFECYCLE), TODAY, attested)
    assert any("not in AZURE_OPENAI_MODELS" in p for p in problems), problems
