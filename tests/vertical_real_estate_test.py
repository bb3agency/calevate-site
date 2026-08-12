"""Vertical template #2 (real estate) — is it actually dressed, and does it bite?

ROADMAP §3's last bullet asks for "vertical template #2 fully dressed". Read against
the docs, a dressed template is TWO artefacts, not one:

1. **The extraction schema** — `scripts/seed.py` VERTICAL_TEMPLATES["real_estate"],
   which onboarding copies into the tenant's `extraction_schemas` row (FLOWS §1 step 4)
   and which then drives the leads columns, filters, export and hot-lead rules with no
   per-client code (TRD §7). This existed already.
2. **The per-vertical regression suite** — OPERATIONS §3 defines the mandatory five
   scenarios per client and then says "add per-vertical + red-team as the suite grows".
   The golden transcripts were entirely clinic; the `re_*` cases are the real-estate
   half, and D-15 makes that suite the differentiator, so it is the half that gates
   quality rather than merely declaring columns.

Nothing else in `docs/` is per-vertical: retention defaults are one global set with a
90-day recording floor (SEC-COMP §1), and the system prompt is generated per CLIENT
from the intake answers (FLOWS §1 step 4, PROMPT-GUIDE §2/§4), not per vertical. See
the module note at the bottom for what that means for BRD §4's "launch templates".

This file guards both artefacts against the two ways they rot:

- **Drift** — the suite scoring a schema that is not the one we ship.
- **Vacuum** — a fixture that asserts nothing, which is precisely the hole
  `tests/eval_quality_test.py` was written to close for the clinic cases. The tests
  below degrade the shipped extractor and require the real-estate cases to go RED, so
  "it passed" means something.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, ClassVar

import apps.workers.extraction as extraction_module
import scripts.eval as ev
from calevate_shared.extraction import ExtractionSchemaSpec
from scripts.seed import VERTICAL_TEMPLATES

#: The real-estate suite, by scenario (OPERATIONS §3's mandatory five, in this
#: vertical's own vocabulary) plus the two hazards specific to a property call: a
#: number read aloud, and a caller who says no.
REQUIRED_RE_CASES = {
    "re_qualification_happy_path",  # 1 happy path
    "re_barge_in_site_visit",  # 2 barge-in
    "re_site_visit_slot_confirmed",  # 3 tool-call correctness
    "re_home_loan_out_of_scope",  # 4 out of scope -> T4 + follow-up
    "re_promo_dnc_optout",  # 5 compliance: disclosure + DNC on an outbound promo
    "re_whatsapp_number_spoken_digits",  # spoken digits + redaction
    "re_undecided_declines_site_visit",  # denial: "vaddu" is not a yes
}

#: Fields the real-estate template declares. Keys, because a renamed key is a leads
#: column that silently empties.
RE_FIELD_KEYS = {
    "budget_lakhs",
    "preferred_location",
    "bhk_size",
    "timeline",
    "site_visit_interest",
}


def _fixtures() -> dict[str, Any]:
    return json.loads(ev.FIXTURES.read_text())  # type: ignore[no-any-return]


def _cases() -> dict[str, dict[str, Any]]:
    return {c["id"]: c for c in _fixtures()["cases"]}


# --- The template itself ---------------------------------------------------------


def test_the_real_estate_template_declares_the_fields_a_property_call_produces() -> None:
    """Budget, locality, size, possession, site visit — BRD §4's launch vertical, and
    the five things a Hyderabad property caller actually says."""
    fields = {f["key"]: f for f in VERTICAL_TEMPLATES["real_estate"]}
    assert set(fields) == RE_FIELD_KEYS


def test_the_budget_field_names_its_unit_in_the_key_the_label_and_the_description() -> None:
    """Hard rule 7: money is NUMERIC INR. "50" in a column headed *Budget* is fifty
    rupees to one reader and fifty lakhs to the next, and the CRM keeps neither the
    call nor the caller's tone of voice — only the number. The unit therefore has to
    survive into the leads table (label), the CSV export (key) and the extraction
    prompt (description, which TRD §7 makes the model's instruction verbatim)."""
    budget = next(f for f in VERTICAL_TEMPLATES["real_estate"] if f["key"] == "budget_lakhs")
    assert budget["type"] == "number"
    assert "lakh" in budget["key"].lower()
    assert "lakh" in budget["label"].lower()
    assert "lakh" in budget["description"].lower()


def test_the_golden_suite_scores_the_template_we_actually_ship() -> None:
    """The fixture schema's real-estate half is the shipped template, verbatim.

    A suite scoring a paraphrase measures a product nobody is sold. `required` is the
    one key deliberately not compared: the fixture file runs ONE spec across clinic and
    real-estate cases, and a clinic call missing `budget_lakhs` is not a validation
    failure — it is a different vertical.
    """
    shipped = {f["key"]: f for f in VERTICAL_TEMPLATES["real_estate"]}
    fixture = {f["key"]: f for f in _fixtures()["schema"] if f["key"] in RE_FIELD_KEYS}
    assert set(fixture) == RE_FIELD_KEYS, "the suite does not cover every template field"
    for key, field in fixture.items():
        for attribute in ("label", "type", "enum_values", "description"):
            assert field.get(attribute) == shipped[key].get(attribute), (
                f"{key}.{attribute} has drifted from scripts/seed.py"
            )


def test_the_fixture_schema_stays_a_valid_extraction_schema() -> None:
    ExtractionSchemaSpec(version=1, fields=_fixtures()["schema"])


# --- The suite exists and covers the mandatory five ------------------------------


def test_the_real_estate_suite_covers_the_mandatory_five_scenarios() -> None:
    """OPERATIONS §3's five are per CLIENT, so client #2's vertical needs its own five
    rather than borrowing the clinic's."""
    cases = _cases()
    missing = REQUIRED_RE_CASES - set(cases)
    assert not missing, f"real-estate coverage removed without replacement: {missing}"
    scenarios = {cases[case_id]["scenario"] for case_id in REQUIRED_RE_CASES}
    assert scenarios == {1, 2, 3, 4, 5}


def test_every_real_estate_case_speaks_the_vertical() -> None:
    """Telugu-first and code-mixed, about the things a property call is about. A suite
    of clean English "I would like a two-bedroom apartment" transcripts scores a
    product we do not sell."""
    cases = _cases()
    joined = " ".join(t for c in REQUIRED_RE_CASES for t in cases[c]["transcript"]).lower()
    for token in ("lakhs", "bhk", "site visit", "possession", "kondapur"):
        assert token in joined, f"the real-estate suite never mentions {token!r}"
    # Telugu grammar, not English with Telugu nouns bolted on.
    assert "kavali" in joined and "cheyandi" in joined


def test_the_disclosure_is_spoken_first_on_every_real_estate_call() -> None:
    """Hard rule 5 / PROMPT-GUIDE §1: the AI disclosure and the recording notice are
    the FIRST utterance, including on the outbound promotional call — which is the one
    where a client would most like them dropped."""
    cases = _cases()
    for case_id in REQUIRED_RE_CASES:
        result = ev.CaseResult(case_id=case_id, title=case_id, scenario=1)
        ev._check_compliance(cases[case_id], result)
        assert result.passed, f"{case_id}: {result.failures}"


def test_the_baseline_waives_only_missing_fields_in_this_vertical() -> None:
    """A weaker model may fail to READ a budget. Nothing waives filing the wrong one,
    inventing a locality, or mis-tagging the outcome that drives the hot-lead rules —
    and no `re_*` case is allowed to acquire an `outcome` waiver quietly."""
    for model, entry in ev.load_baseline().items():
        assert isinstance(entry, dict)
        for case_id, kinds in entry.items():
            if case_id in REQUIRED_RE_CASES:
                assert set(kinds) <= {ev.CAPTURE_MISS}, f"{model}/{case_id} waives {kinds}"


# --- Does it bite? ---------------------------------------------------------------
#
# The same method as tests/eval_quality_test.py: break the SHIPPED extractor in a way a
# real model breaks, and require the gate to go red. A fixture that survives every
# degradation is decoration.

Mutator = Callable[[dict[str, Any], str], dict[str, Any]]


class _Rewrites:
    """Runs the real offline extractor over a REWRITTEN transcript.

    Rewriting the input is how a speaker-attribution bug is simulated honestly: the
    extractor is the shipped one, it is simply handed a transcript in which the agent's
    turns look like the caller's — which is exactly what `_caller_turns` existed to
    prevent, and what any model does when the prompt's speaker rule is weakened.
    """

    model_name = "offline-heuristic"

    def __init__(self, rewrite: Callable[[str], str]) -> None:
        self._rewrite = rewrite
        self._inner = extraction_module.OfflineExtractor()

    async def run(self, spec: ExtractionSchemaSpec, transcript: str) -> dict[str, Any]:
        return await self._inner.run(spec, self._rewrite(transcript))


class _Fabricates:
    """Fills every column with a plausible value. The eager model.

    Nothing crashes, nothing is empty, the dashboard looks excellent and the client's
    leads table is fiction. Every case must catch this one.
    """

    model_name = "offline-heuristic"

    _INVENTED: ClassVar[dict[str, Any]] = {
        "name": "Ramesh",
        "intent": "cancel",
        "urgency": "urgent",
        "party_size": 9,
        "wants_callback": True,
        "callback_number": "6666666666",
        "callback_time": "ippude",
        "number_belongs_to": "third_party",
        "budget_lakhs": 999,
        "preferred_location": "Kukatpally",
        "bhk_size": "1BHK",
        "timeline": "next year",
        "site_visit_interest": True,
    }

    async def run(self, spec: ExtractionSchemaSpec, transcript: str) -> dict[str, Any]:
        return {f.key: self._INVENTED[f.key] for f in spec.fields} | {
            "outcome_tag": "resolved",
            "summary": "",
        }


@contextmanager
def _extractor(replacement: Any) -> Iterator[None]:
    real = extraction_module.get_extractor
    extraction_module.get_extractor = lambda: replacement
    try:
        yield
    finally:
        extraction_module.get_extractor = real


async def _gate(replacement: Any) -> tuple[set[str], set[str]]:
    """(regressed case ids, the kinds they regressed on) under a degradation."""
    with _extractor(replacement):
        results, meta = await ev.run_suite("test")
    regressions, _ = ev.classify(results, ev.load_baseline().get(str(meta["model"]), []))
    kinds = {f.kind for r in results if r.case_id in set(regressions) for f in r.failures}
    return set(regressions), kinds


async def test_a_fabricating_extractor_fails_every_real_estate_case() -> None:
    """The vacuum test. If a case can be filled with thirteen invented values and still
    pass, it asserts nothing — which is how three clinic fixtures were once completely
    unguarded. Every `re_*` case must go red, and none of it is waivable."""
    regressed, kinds = await _gate(_Fabricates())
    assert regressed >= REQUIRED_RE_CASES, (
        f"these real-estate cases survive a fully fabricated extraction: "
        f"{sorted(REQUIRED_RE_CASES - regressed)}"
    )
    assert kinds & {ev.RESTRAINT, ev.CAPTURE_WRONG}


async def test_reading_the_agents_pitch_as_the_callers_requirement_fails_the_gate() -> None:
    """The outbound promo case's whole point. The AGENT says "Kokapet lo kotha 2BHK
    flats"; the caller says stop. An extractor that loses speaker attribution files the
    pitch back as the lead's requirement — a qualified-looking row, and a next dispatch,
    built out of a person who just opted out."""
    regressed, kinds = await _gate(_Rewrites(lambda t: t.replace("agent:", "caller:")))
    assert "re_promo_dnc_optout" in regressed
    assert ev.RESTRAINT in kinds


async def test_losing_the_denial_rule_fails_the_declined_site_visit(monkeypatch: Any) -> None:
    """ "Ippudu vaddu, site visit avasaram ledu" contains the words site and visit. An
    extractor matching words instead of meaning marks the visit accepted, and a sales
    team drives to Manikonda for a caller who said no."""
    monkeypatch.setattr(extraction_module.OfflineExtractor, "_NEGATION_RE", re.compile(r"(?!x)x"))
    regressed, kinds = await _gate(extraction_module.OfflineExtractor())
    assert "re_undecided_declines_site_visit" in regressed
    assert ev.RESTRAINT in kinds
    # And the requirement the caller REPLACED, which the same rule decides: with no
    # negation trigger, "2BHK saripodu" stops being a rejection and the household is
    # filed under the size they just ruled out (`capture_wrong`, never waivable).
    assert "re_spouse_takes_the_phone" in regressed


async def test_the_undegraded_real_estate_suite_matches_its_baseline() -> None:
    """The control: without it every test above could be passing for an unrelated
    reason. Also the honest statement of where the offline extractor stands — it reads
    names, enums and booleans, and it cannot read a budget out of "50 lakhs varaku",
    which is a capture_miss and exactly what the per-model baseline is for."""
    results, meta = await ev.run_suite("test")
    baseline = ev.load_baseline().get(str(meta["model"]), [])
    regressions, _ = ev.classify(results, baseline)
    assert not [r for r in regressions if r in REQUIRED_RE_CASES], regressions


async def test_the_offline_extractor_captures_what_it_can_in_this_vertical() -> None:
    """Not every real-estate assertion may be a baselined miss, or the suite would be
    green because it measured nothing. The deterministic floor must genuinely produce
    the BHK, the site-visit consent and the caller's name — those are the values a
    degradation above has to corrupt in order to be caught."""
    results, _ = await ev.run_suite("test")
    captured = {r.case_id: r.captured for r in results}
    assert captured["re_qualification_happy_path"]["bhk_size"] == "2BHK"
    assert captured["re_qualification_happy_path"]["site_visit_interest"] is True
    assert captured["re_qualification_happy_path"]["name"] == "Srinivas"
    assert captured["re_site_visit_slot_confirmed"]["intent"] == "book"
    # And the two the vertical's semantics turn OFF: a refusal, and the agent's turn.
    assert "site_visit_interest" not in captured["re_undecided_declines_site_visit"]
    assert "bhk_size" not in captured["re_promo_dnc_optout"]


# --- What is still NOT dressed ---------------------------------------------------
#
# There is no per-vertical PROMPT anywhere in this repo, and no doc asks for one:
# FLOWS §1 step 4 generates the system prompt per client from the intake answers, and
# PROMPT-GUIDE §2 defines the section order every generated prompt follows. So a
# "vertical template" today means the extraction schema plus this suite — which is less
# than BRD §4's "launch templates for clinics/healthcare and real estate" sounds like,
# and the gap is worth naming rather than papering over with a prompt file nothing
# reads. Wiring a per-vertical [TASK FLOW] starting point into the wizard would be an
# apps/api change and a decision-log entry, not a fixture.
