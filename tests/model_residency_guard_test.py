"""The residency guard, proved against the states it exists to catch.

`scripts/check_model_residency.py` is the gate; this file is the evidence that the gate can
go red. A check nobody has watched fail is a check nobody knows is connected — the same
argument `check_redaction_exposure.check_allowlist` makes when it refuses to pass on a route
table with no permissions in it at all.

**THIS FILE CARRIES AN EXTRA BURDEN THAT ITS D-127 VERSION DID NOT, AND THE BURDEN GREW.**
The guard got WEAKER at D-410 — Vertex put `asia-south1` in the hostname and in the path, so
residency was provable from the AST, and `<resource>.openai.azure.com` names no region at
all. It got weaker again when the posture opened from one vendor to a SET OF LEGS: three of
the four watched hosts now belong to a declared leg, so the wrong-vendor clause refuses one
host where it used to refuse three, and `api.openai.com` — which was BANNED outright — is a
leg's permitted host. A guard that quietly checks less than it used to while still printing
`OK` is the defect class this repository keeps finding, so several cases below are not about
catching a bad URL:

* `test_the_guard_states_what_it_cannot_prove_on_every_run` pins the honesty. The delegation
  notice has to reach a reader on the pass path AND the fail path, name what each leg does
  and does not owe, and name the gates that own the rest.
* `test_the_human_gate_that_owns_the_unprovable_half_is_written_down` pins the OTHER end of
  that sentence: a pointer to a deleted owner is worse than no pointer.
* `test_the_openai_global_endpoint_is_refused_and_the_regional_one_is_the_remedy` is where
  the ban's replacement is pinned, so nobody reads the absence of the old clause as an
  absence of any clause.

The properties the guard still proves, each with its own negative control:

1. ONE SPELLING OF EACH PINNED REGION — a loose literal, a SECOND frozen constant, the
   constant moving house, and (new, once a posture can hold more than one leg) a frozen
   region constant that NO declared leg pins.
2. NO `Settings` FIELD CAN CARRY A REGION — the failure that never appears in a URL literal,
   because the value arrives from a database row. Plus its sibling: a field that would be a
   hand-typed ENDPOINT, which is a second constructor made of a text box. **The endpoint half
   is checked for every vendor any known LEG names**, not only the declared ones.
3. NO ENDPOINT OUTSIDE ITS LEG'S BUILDER — a hand-written f-string, a builder suffix spelled
   in the wrong file, an unfrozen copy of it in the right one, OpenAI's global endpoint under
   a leg that pins `us`, Gemini's host anywhere but its one builder suffix (D-478), and the
   Azure regional hostname that D-410 rejects FOR NOW.
4. NO BUILDER CAN EMIT A REGION OTHER THAN ITS LEG'S — a builder that grew a `location=`
   parameter, one that interpolates a runtime value, one that never refuses a bad resource,
   and one that has been renamed out from under the check.
7. NO DECLARED LEG IS INERT — `tests/residency_posture_test.py` owns that one, because the
   subject is the catalogue rather than a URL.

Plus the branch nobody can reach today: `test_adopting_the_regional_hostname_restores_the_
ast_proof` runs the guard with `REGIONAL_HOST_ADOPTED` flipped, which is what makes
"switching is one line" a fact rather than a comment — and which is no longer hypothetical
machinery, because the OpenAI leg runs the same region-in-host check on its own builder
today.

Plus the anti-rubber-stamp cases: prose naming a watched host must NOT fail (this is an AST
walk, not a grep), the Sheets/OAuth hosts must not be judged at all, and the guard's own file
is judged like any other except for the exact declaration strings `SELF_DECLARATIONS` derives
from the leg table.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts import check_model_residency as guard

# One correctly built Azure endpoint, written the way `workers/extraction.py` writes it:
# the resource through the ONE builder, nothing spelled by hand. There is no host literal
# and no region literal here at all, which is the whole shape D-410 ships.
COMPLIANT = (
    "from typing import Final\n"
    "from calevate_shared.engine import azure_openai_base_url\n"
    'RESOURCE: Final = "calevate-prod"\n'
    'URL = f"{azure_openai_base_url(RESOURCE)}/chat/completions"\n'
)


def _tree(root: Path, body: str, name: str = "client.py") -> Path:
    (root / name).write_text(body, encoding="utf-8")
    return root


#: The region constants a SHIPPED tree must carry under the declared posture: one per leg
#: that pins a region, each in the contract, each holding that leg's own region. Written as a
#: helper because check 1 is now an equality against a per-leg SET rather than against one
#: constant — a fixture that supplied only Azure's would be testing a tree with a leg missing.
def _pinned() -> dict[str, tuple[str, str]]:
    return {
        guard.REGION_CONSTANT: (guard.BUILDER_HOME, guard.AZURE_REGION_US),
        guard.OPENAI_REGION_CONSTANT: (guard.BUILDER_HOME, guard.OPENAI_REGION_US),
    }


#: This file's own canaries, as `frozen_region_constants` reports them: one `Final` per region
#: in `KNOWN_REGIONS`, all in `SELF`, none of them a second spelling of anything.
def _canaries() -> dict[str, tuple[str, str]]:
    return {
        "AZURE_REGION_US": (guard.SELF, guard.AZURE_REGION_US),
        "AZURE_REGION_INDIA": (guard.SELF, guard.AZURE_REGION_INDIA),
        "OPENAI_REGION_US": (guard.SELF, guard.OPENAI_REGION_US),
    }


def _failures(root: Path) -> list[str]:
    """Every endpoint failure a doctored tree produces, judged against ITS OWN constants
    and with no allowance — the real registry names a real file and would not apply."""
    references = guard.endpoint_references(roots=(root,))
    return guard.endpoint_failures(
        references, frozen=guard.frozen_region_constants(roots=(root,)), allowances={}
    )


# --- the standing assertion ---------------------------------------------------


def test_the_real_tree_is_clean() -> None:
    """The same checks `make guardrails` runs, over the real repository."""
    references = guard.endpoint_references()
    constants = guard.frozen_region_constants()
    assert guard.blindness_failures(guard.template_count(), constants, references) == []
    assert guard.single_spelling_failures(constants) == []
    assert guard.loose_region_literals() == []
    assert guard.console_config_failures() == []
    assert guard.endpoint_failures(references, constants) == []
    assert guard.stale_allowances(references) == []
    assert guard.builder_failures() == []
    assert guard.delegation_failures() == []
    assert guard.inert_leg_failures() == []


def test_a_compliant_tree_passes(tmp_path: Path) -> None:
    """Half of the pair the brief calls decorative without: a check that only ever fails
    is as useless as one that only ever passes, and this is the shape every caller in the
    tree must be able to write without arguing with the guard."""
    root = _tree(tmp_path, COMPLIANT)
    assert _failures(root) == []
    assert guard.loose_region_literals(roots=(root,)) == []
    assert guard.endpoint_references(roots=(root,)) == [], (
        "the compliant shape names no host at all — that is what going through the "
        "builder MEANS, and a reference here would mean the fixture is not the shape"
    )


# --- 1: one spelling of the region --------------------------------------------


def test_a_region_literal_outside_a_final_constant_is_caught(tmp_path: Path) -> None:
    """A default argument that READS like a pin and is one keyword away from not being
    one. Nothing here is a URL, so check 3 sees nothing at all."""
    root = _tree(
        tmp_path,
        "class Azure:\n"
        '    def __init__(self, location: str = "southindia") -> None:\n'
        "        self._location = location\n",
    )
    offenders = guard.loose_region_literals(roots=(root,))
    assert len(offenders) == 1, offenders
    assert "Final" in offenders[0] and "southindia" in offenders[0]
    assert _failures(root) == [], "no endpoint literal here — check 3 must be quiet"


def test_a_second_frozen_region_constant_is_caught() -> None:
    """THE STRENGTHENING D-410 BOUGHT, and the one place this guard got stricter.

    The Vertex version accepted any `Final` holding the region, and that was defensible
    while every model URL in the tree carried the region: checks on the URLs would have
    caught two constants the moment they disagreed. There are no such URLs now. A second
    constant is a second answer to where this product's models run, with nothing left
    downstream able to notice the day they stop agreeing.
    """
    offenders = guard.single_spelling_failures(
        _pinned()
        | {"AZURE_REGION_FOR_BILLING": ("apps/api/billing/rates.py", guard.AZURE_REGION_US)}
    )
    assert len(offenders) == 1, offenders
    assert "no declared leg pins" in offenders[0], offenders
    assert "AZURE_REGION_FOR_BILLING" in offenders[0]


def test_the_region_constant_moving_house_is_caught() -> None:
    """Right name, wrong home. The constant is read by the adapter, the extractor, the
    cost model and this guard; a copy that drifted into one caller's module would be
    invisible to a name-only check."""
    offenders = guard.single_spelling_failures(
        _pinned() | {guard.REGION_CONSTANT: ("apps/workers/azure.py", guard.AZURE_REGION_US)}
    )
    assert len(offenders) == 1 and "apps/workers/azure.py" in offenders[0], offenders
    assert guard.REGION_CONSTANT in offenders[0], offenders


def test_no_region_constant_at_all_is_caught() -> None:
    """The state a careless deletion produces, and the one that reads most like success:
    with no constant anywhere, every other check in the file finds nothing to complain
    about."""
    offenders = guard.single_spelling_failures({})
    assert len(offenders) == 2, offenders
    assert all("no shipped module defines" in failure for failure in offenders), offenders
    joined = " ".join(offenders)
    assert guard.REGION_CONSTANT in joined and guard.OPENAI_REGION_CONSTANT in joined, offenders


def test_the_guards_own_canaries_are_not_counted_as_second_spellings() -> None:
    """The guard spells EVERY known region on the `check_bootstrap_keys.BOOTSTRAP_KEYS`
    doctrine — a guardrail that imported the value it checks would be asking the code
    whether it agrees with itself. So none of them may be reported as the second spelling
    the test above catches, and the real tree proves it: the withdrawn region's constant
    (D-449) is present too and is equally not a second spelling."""
    constants = guard.frozen_region_constants()
    for name, where in _canaries().items():
        assert constants[name] == where, name
    assert constants[guard.REGION_CONSTANT] == (guard.BUILDER_HOME, guard.AZURE_REGION_US)
    assert constants[guard.OPENAI_REGION_CONSTANT] == (
        guard.BUILDER_HOME,
        guard.OPENAI_REGION_US,
    )
    assert guard.single_spelling_failures(constants) == []


# --- 2: the console can never decide this -------------------------------------


def test_a_settings_field_named_for_a_region_is_caught() -> None:
    """The failure that never appears in a URL literal. `managed_fields()` derives the
    console's editable set from `Settings.model_fields`, so `azure_location` is editable
    from a web form the day it is declared and the guard has to see the DECLARATION."""
    offenders = guard.console_config_failures(
        fields={"azure_location": "eastus2", "sarvam_api_key": None},
        managed=["azure_location"],
    )
    assert len(offenders) == 1, offenders
    assert "console-editable" in offenders[0] and "3am" in offenders[0]

    # Declared but not yet managed is still a failure: `managed_fields()` is derived, so
    # a field one rename away from being offered is a field that will be offered.
    hidden = guard.console_config_failures(fields={"model_region": "eastus2"}, managed=[])
    assert len(hidden) == 1 and "declared" in hidden[0], hidden


def test_a_settings_field_that_would_be_a_second_endpoint_constructor_is_caught() -> None:
    """D-410's sibling of the region knob, and the reason the check is a PAIR rather than
    the word "url".

    Check 3 says the model endpoint has exactly one constructor. A console field called
    `azure_openai_base_url` would be a second one made of a text box — and unlike the
    region, it would not even need a code change to point the leg somewhere else. The
    endpoint words are paired with a vendor token because plenty of settings are
    legitimately URLs, and a check that banned the word would be routed around by
    renaming rather than obeyed.
    """
    offenders = guard.console_config_failures(
        fields={"azure_openai_base_url": None}, managed=["azure_openai_base_url"]
    )
    assert len(offenders) == 1, offenders
    assert "second one" in offenders[0] and "model ENDPOINT" in offenders[0]
    assert f"{guard.BUILDER}()" in offenders[0], (
        "the refusal must name the constructor the field would be duplicating, or the "
        "reader has to go and find which of four builders this vendor uses"
    )
    assert "'azure'" in offenders[0], (
        "`azure_openai_base_url` carries two vendor tokens and the LEFTMOST is the vendor "
        "— attributing it to OpenAI would point the reader at the wrong builder"
    )

    # …and the four settings the leg genuinely needs are NOT caught, which is what stops
    # this check being deleted the first time somebody configures Azure properly.
    assert (
        guard.console_config_failures(
            fields={
                "azure_openai_resource": None,
                "azure_openai_api_key": None,
                "azure_openai_deployment": None,
                "azure_openai_model": "gpt-4o-mini",
            },
            managed=["azure_openai_resource", "azure_openai_deployment", "azure_openai_model"],
        )
        == []
    )


def test_the_endpoint_knob_check_covers_every_vendor_the_posture_table_knows() -> None:
    """THE HOLE THIS TEST WAS WRITTEN FOR, and it was live under the DECLARED posture — not
    only under a hypothetical future one.

    The vendor half of this check used to be a hard-coded tuple of Azure token pairs
    (`("azure", "url")` and two siblings), so `Settings.openai_base_url` and
    `Settings.gemini_api_base` passed. `apps/web/src/lib/legal/dpa.ts` warrants to clients
    that "no configuration setting may carry a region, an endpoint or a posture", and this
    function is the enforcement behind the middle term — so the warranty was being enforced
    for one vendor out of the three the table can express, with a green run either way.

    IT IS STATED OVER `POSTURES` AND NOT OVER A LIST OF NAMES, which is what makes it hold
    for the NEXT vendor as well: every token every spec declares must be refused beside an
    endpoint word. A posture added with no `vendor_tokens`, or a check re-narrowed to the
    declared posture's, fails here rather than in an audit.

    FAILS IF: `KNOWN_VENDOR_TOKENS` stops being the union over `POSTURES` (e.g. it is
    re-narrowed to `declared_spec().vendor_tokens`), or the vendor half is hard-coded back
    to Azure's name, or a spec is added without saying what its vendor is called.
    """
    assert len(guard.KNOWN_VENDOR_TOKENS) >= 3, guard.KNOWN_VENDOR_TOKENS
    for leg in guard.KNOWN_LEGS:
        assert leg.vendor_tokens, f"the {leg.provider!r} leg does not say what its vendor is called"
        for token in leg.vendor_tokens:
            assert token in guard.KNOWN_VENDOR_TOKENS, (token, leg.provider)
            for suffix in guard.ENDPOINT_KNOB_WORDS:
                field = f"{token}_api_{suffix}"
                offenders = guard.console_config_failures(fields={field: None}, managed=[field])
                assert len(offenders) == 1, (field, offenders)
                assert f"{token!r}" in offenders[0] and f"{suffix!r}" in offenders[0], offenders


def test_the_endpoint_knob_check_catches_the_vendors_own_name_for_the_field() -> None:
    """`api_base` carries no `url`, no `endpoint` and no `host`, and it is the LIKELIEST
    spelling of the field this check exists to refuse.

    It is the vendor's own name for the value: `AZURE_OPENAI_API_BASE` is one of the four
    flat credential entries the engine stores (D-417), and OpenAI's SDK reads
    `OPENAI_API_BASE`. So the field somebody actually declares after copying a vendor's
    setup page is exactly the one the three original fragments waved through.

    FAILS IF: `base` is dropped from `ENDPOINT_KNOB_WORDS`.
    """
    assert "base" in guard.ENDPOINT_KNOB_WORDS
    for field in ("azure_openai_api_base", "openai_api_base", "gemini_api_base"):
        offenders = guard.console_config_failures(fields={field: None}, managed=[field])
        assert len(offenders) == 1, (field, offenders)
        assert "'base'" in offenders[0], offenders

    # And the boundary: a URL word with NO vendor beside it stays legitimate. Banning the
    # word alone is the check people route around by renaming, and this repository has
    # four live fields that would fail it.
    assert (
        guard.console_config_failures(
            fields={
                "webhook_base_url": None,
                "database_url": None,
                "object_store_endpoint": None,
                "smtp_host": None,
                # A vendor token with no endpoint word is configuration, not a knob: this
                # is the AI Studio key that no surface in the product opens.
                "gemini_api_key": None,
                "google_sheets_provider": None,
            },
            managed=[],
        )
        == []
    )


def test_a_settings_field_holding_a_model_host_is_caught_whatever_it_is_called() -> None:
    """Names are a heuristic; the default value is evidence. `llm_base` says nothing and
    holds the whole residency decision."""
    offenders = guard.console_config_failures(
        fields={"llm_base": "https://calevate.openai.azure.com/openai/v1"}, managed=["llm_base"]
    )
    assert len(offenders) == 1, offenders
    assert "it is the residency knob" in offenders[0]

    # The disqualified vendor reads the same way, and is the likelier typo: Azure's v1
    # surface is OpenAI-compatible, so the same client speaks to both.
    direct = guard.console_config_failures(
        fields={"llm_base": "https://api.openai.com/v1"}, managed=["llm_base"]
    )
    assert len(direct) == 1 and "residency knob" in direct[0], direct


def test_the_live_settings_model_has_nowhere_to_put_a_region() -> None:
    """The claim above, asserted against the real model rather than a fixture — otherwise
    the two tests together prove only that the fixture is well written."""
    fields, managed = guard.live_settings()
    assert len(fields) > 40, "the Settings model came back nearly empty — this is blind"
    assert "app_env" not in managed, "managed_fields() no longer excludes the bootstrap set"
    assert guard.console_config_failures(fields, managed) == []


# --- 3: no endpoint outside the one builder -----------------------------------


def test_a_hand_built_azure_endpoint_is_caught(tmp_path: Path) -> None:
    """THE central negative control of the rewrite.

    Nothing about this line is malformed, nothing raises, and every other test in the
    repository stays green — which is exactly the reason check 3 is syntactic and
    mandatory rather than a review convention. The Vertex analogue of this test was a
    `us-central1` host; there is no such thing to write any more, and this is what took
    its place.
    """
    root = _tree(
        tmp_path,
        "class Azure:\n"
        "    def __init__(self, resource: str) -> None:\n"
        '        self._url = f"https://{resource}.openai.azure.com/openai/v1"\n',
    )
    offenders = _failures(root)
    assert len(offenders) == 1, offenders
    assert "by hand" in offenders[0] and guard.BUILDER in offenders[0]
    assert "evil.example" in offenders[0], (
        "the refusal must say WHY a hand-written f-string is dangerous rather than only "
        "that it is refused — the resource lands at the front of the authority"
    )


def test_the_builders_own_suffix_is_permitted_only_in_the_builders_own_file(
    tmp_path: Path,
) -> None:
    """The single exemption, and all three of its conditions.

    Exactly one literal in the tree may name an Azure host. It earns that by being the
    right FILE, the exact STRING and a `Final` — and each condition is dropped here in
    turn, because an exemption granted on a subset of its conditions is one that will be
    inherited by the next thing that looks similar.
    """
    suffix_line = f'_AZURE_ENDPOINT_SUFFIX: Final = "{guard.BUILDER_SUFFIX}"\n'
    body = "from typing import Final\n" + suffix_line

    # Wrong file: the same declaration, somewhere that is not `BUILDER_HOME`.
    root = _tree(tmp_path, body)
    wrong_file = _failures(root)
    assert len(wrong_file) == 1 and "by hand" in wrong_file[0], wrong_file

    # Right file, right string, NOT frozen — a rebindable module global is a knob.
    unfrozen = guard.Reference(guard.BUILDER_HOME, 1, guard.BUILDER_SUFFIX, frozen=False)
    assert len(guard.endpoint_failures([unfrozen], {}, {})) == 1

    # Right file, frozen, but the STRING has drifted — a suffix that grew a query
    # parameter or lost `/v1` is a different endpoint wearing the exemption.
    drifted = guard.Reference(
        guard.BUILDER_HOME, 1, f"{guard.BUILDER_SUFFIX}?api-version=2024-10-21", frozen=True
    )
    assert len(guard.endpoint_failures([drifted], {}, {})) == 1

    # All three together, and only then, is it permitted.
    permitted = guard.Reference(guard.BUILDER_HOME, 1, guard.BUILDER_SUFFIX, frozen=True)
    assert guard.endpoint_failures([permitted], {}, {}) == []


def test_the_openai_global_endpoint_is_refused_and_the_regional_one_is_the_remedy(
    tmp_path: Path,
) -> None:
    """⚠ **THIS TEST REPLACES A BAN, AND THE REPLACEMENT IS WEAKER IN KIND.**

    `api.openai.com` used to be refused OUTRIGHT, with D-410's reason: OpenAI's India data
    residency covers storage at rest only, and for a phone call the transcript IS the
    inference input. D-449 withdrew the India requirement, so that ground stopped
    discriminating, and the host is now a declared leg's. The guard's own docstring records
    the arithmetic — the wrong-vendor clause went from refusing three of four watched hosts
    to refusing one — and this is where the replacement is pinned so nobody mistakes it for
    the old rule.

    WHAT IS REFUSED NOW IS SHARPER ON THE THING THAT ACTUALLY MOVES DATA. The pinned endpoint
    and the vendor's GLOBAL one differ by one label, and only one of them is a regional
    claim. So a literal naming the host without the residency label in front of it gets its
    own sentence — "that is the vendor's GLOBAL endpoint" — rather than being lumped in with
    "built by hand", and the remedy names the builder and the constant that spell it.

    FAILS IF: `region_in_host` stops being read in `_leg_literal_failures`, which would let
    `https://api.openai.com/v1` pass as an ordinary hand-built endpoint under a leg adopted
    precisely because its region is checkable.
    """
    root = _tree(tmp_path, 'URL = "https://api.openai.com/v1/chat/completions"\n')
    offenders = _failures(root)
    assert len(offenders) == 1, offenders
    assert "GLOBAL endpoint" in offenders[0], offenders
    assert "residency label" in offenders[0], offenders
    assert guard.OPENAI_REGION_CONSTANT in offenders[0], offenders
    assert guard.OPENAI_BUILDER in offenders[0], offenders

    # The REGIONAL form is still refused — but as a second constructor, not as a residency
    # defect, and the message says which. One literal per leg, and it is the builder's.
    (tmp_path / "client.py").unlink()
    regional = _tree(tmp_path, 'URL = "https://us.api.openai.com/v1"\n', name="two.py")
    offenders = _failures(regional)
    assert len(offenders) == 1, offenders
    assert "by hand" in offenders[0], offenders
    assert "no caller input" in offenders[0], (
        "the OpenAI builder takes no argument, so the hostile-label sentence would be "
        "boilerplate here — printing it anyway teaches the reader that these explanations "
        "are boilerplate everywhere"
    )


def test_every_leg_host_the_table_knows_is_both_watched_and_judged(tmp_path: Path) -> None:
    """The scan has to SEE a host before any clause can refuse it, and the two halves used
    to be maintained apart.

    `WATCHED_HOSTS` was a hand-written tuple beside a table of postures, so a leg could be
    added with a `permitted_host` no scan ever looked for: `endpoint_references()` would
    yield nothing, `endpoint_failures()` would say nothing, and check 3 would be unenforced
    under the one leg it existed for while the run printed OK. It is derived now, and
    `test_the_raw_transcript_host_is_deliberately_not_a_watched_host` states the other half
    of the rule — a watched host with no clause behind it is cost with no check — so this
    asserts BOTH: seen, and refused.

    FAILS IF: `WATCHED_HOSTS` goes back to a literal tuple and a leg's host drops out of it,
    or `_leg_literal_failures` stops being reached for some leg.
    """
    declared = guard.declared_spec()
    for leg in guard.KNOWN_LEGS:
        # A host written `.suffix` needs a label in front of it to be a hostname; one
        # written whole is already one. Both shapes appear in the table.
        host = (
            f"calevate{leg.permitted_host}" if leg.permitted_host[0] == "." else leg.permitted_host
        )
        assert leg.permitted_host in guard.WATCHED_HOSTS, leg.provider
        assert guard._mentions_watched_host(f"https://{host}/v1"), leg.provider

        root = _tree(tmp_path, f'URL = "https://{host}/v1"\n')
        offenders = _failures(root)
        assert len(offenders) == 1, (leg.provider, offenders)
        if declared.leg(leg.provider) is None:
            assert leg.permitted_host in offenders[0], offenders
            continue
        # A DECLARED leg refuses its own host for its own reason, and the sentences are
        # deliberately different: built by hand (Azure and, since D-478, Google — both have a
        # builder and an out-of-contract literal is a second constructor) or the missing
        # residency label (OpenAI).
        assert any(
            marker in offenders[0] for marker in ("by hand", "residency label", "ZERO literals")
        ), (leg.provider, offenders)


def test_a_gemini_endpoint_built_by_hand_is_refused_outside_the_one_builder(
    tmp_path: Path,
) -> None:
    """D-478 MOVED THE GOOGLE LEG FROM "ZERO LITERALS" TO "EXACTLY ONE", and this proves the
    other half: the one literal is the builder's frozen suffix in the contract, and every
    OTHER literal naming the host — a hand-built endpoint in a handler, a stray constant —
    is still refused.

    Until D-478 the leg carried no builder (the in-call Google provider builds its own client
    from a single API key), so the budget was ZERO literals anywhere. D-478 puts the dashboard
    copilot on the Gemini OpenAI-compat `/chat/completions` surface, which
    `google_openai_compat_base_url()` assembles from `GEMINI_BUILDER_SUFFIX` — so a SECOND
    literal, in a synthetic tree that is not the contract, is a second constructor and refused
    exactly as the Azure leg's hand-built subdomain URL is.

    FAILS IF: the exemption is granted by host substring rather than by the exact frozen
    suffix in BUILDER_HOME, which would let any handler name the host.
    """
    root = _tree(tmp_path, f'URL = "https://{guard.GEMINI_DIRECT_HOST}/v1beta/openai"\n')
    offenders = _failures(root)
    assert len(offenders) == 1, offenders
    assert guard.GEMINI_DIRECT_HOST in offenders[0], offenders
    assert "by hand" in offenders[0], offenders
    assert guard.GEMINI_BUILDER in offenders[0], offenders

    # The Sheets hosts are the boundary and they are NOT judged: `.googleapis.com` is a
    # domain shared by a model API and by the tenant's own CRM destination, so the watched
    # string is a full hostname. A suffix match here would fire on every export.
    (tmp_path / "client.py").unlink()
    sheets = _tree(tmp_path, 'URL = "https://sheets.googleapis.com/v4/spreadsheets"\n')
    assert _failures(sheets) == []


def test_the_regional_hostname_is_refused_while_it_is_rejected_for_now(tmp_path: Path) -> None:
    """The rejected-FOR-NOW alternative, refused with its reason rather than lumped in.

    This one is not a residency defect — it is the STRONGER form, and refusing it for the
    same reason as a hand-built subdomain URL would teach the next reader that the region
    in a hostname is somehow suspect. What makes it a failure today is that D-410 ships one
    endpoint form, two forms is two postures, and the v1 surface is only DOCUMENTED on the
    other one. So the refusal names the route in: gate 20d, then the builder, then the flag.
    """
    root = _tree(
        tmp_path,
        'URL = "https://southindia.api.cognitive.microsoft.com/openai/v1"\n',
    )
    offenders = _failures(root)
    assert len(offenders) == 1, offenders
    assert "rejected-FOR-NOW" in offenders[0], offenders
    assert "gate 20d" in offenders[0] and "REGIONAL_HOST_ADOPTED" in offenders[0], offenders
    assert "IMPROVE residency" in offenders[0], (
        "the refusal must say this form is better rather than worse, or the next reader "
        "learns the opposite of the truth from a red build"
    )


def test_adopting_the_regional_hostname_restores_the_ast_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dormant branch, exercised — which is what makes "switching is one line" a fact.

    D-410 records the regional hostname as rejected for now, and OPERATIONS §2 gate 20d is
    the call that reopens it. The prize is concrete: a hostname carrying the declared region
    gives this guard back exactly what Vertex gave it — a residency claim provable from a string
    literal instead of one a human vouches for. So the check that would do the proving is
    WRITTEN and TESTED now, behind one flag, rather than promised in a comment. A dormant
    branch nobody has run is a branch that does not work.
    """
    monkeypatch.setattr(guard, "REGIONAL_HOST_ADOPTED", True)

    # The DECLARED region spelled literally in the host: accepted, and no longer merely
    # asserted. It is `eastus2` since D-449 and the literal has to move with the
    # declaration — that is the point of the check, not an incidental fixture detail.
    root = _tree(tmp_path, 'URL = "https://eastus2.api.cognitive.microsoft.com/openai/v1"\n')
    assert _failures(root) == []

    # Through the frozen constant, which is how the builder would spell it.
    root = _tree(
        tmp_path,
        "from typing import Final\n"
        'AZURE_LOCATION: Final = "eastus2"\n'
        'URL = f"https://{AZURE_LOCATION}.api.cognitive.microsoft.com/openai/v1"\n',
    )
    assert _failures(root) == []

    # AND THE CONSTANT'S VALUE IS WHAT COUNTS, NOT THAT IT IS FROZEN (D-449). A frozen
    # `AZURE_LOCATION` still holding the WITHDRAWN region is exactly what a half-finished
    # posture move leaves behind, and accepting it because the name resolves would make
    # this branch prove provenance and nothing about geography.
    root = _tree(
        tmp_path,
        "from typing import Final\n"
        'AZURE_LOCATION: Final = "southindia"\n'
        'URL = f"https://{AZURE_LOCATION}.api.cognitive.microsoft.com/openai/v1"\n',
    )
    offenders = _failures(root)
    assert len(offenders) == 1, offenders
    assert "{AZURE_LOCATION}" in offenders[0] and "'eastus2'" in offenders[0], offenders

    # And the whole point: a different region is now CAUGHT, from the AST, with no human
    # in the loop. `swedencentral` is not a strawman — it is one of `gpt-4.1-mini`'s
    # default quota regions, which is exactly how a wrong one gets typed.
    root = _tree(tmp_path, 'URL = "https://swedencentral.api.cognitive.microsoft.com/openai/v1"\n')
    offenders = _failures(root)
    assert len(offenders) == 1, offenders
    assert "'swedencentral'" in offenders[0] and "residency change" in offenders[0], offenders


def test_a_region_that_is_not_the_frozen_constant_is_refused_on_the_regional_form(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shape that becomes a config knob three commits later: the host is right today
    because `self._location` happens to hold the right string today. Under the regional
    form the guard can see the provenance, and provenance is the half a grep cannot do."""
    monkeypatch.setattr(guard, "REGIONAL_HOST_ADOPTED", True)
    root = _tree(
        tmp_path,
        "class Azure:\n"
        "    def __init__(self, location: str) -> None:\n"
        "        self._location = location\n"
        "    def url(self) -> str:\n"
        '        return f"https://{self._location}.api.cognitive.microsoft.com/openai/v1"\n',
    )
    offenders = _failures(root)
    assert any("{self._location}" in offender for offender in offenders), offenders
    assert any("`Final` constant" in offender for offender in offenders), offenders


# --- 4: the builder cannot emit a region other than the declared posture's ----


#: A builder shaped the way `calevate_shared.engine` shapes it, for the negative controls
#: below to be edits OF something rather than inventions.
BUILDER_SOURCE = (
    "from typing import Final\n"
    "import re\n"
    '_SUFFIX: Final = ".openai.azure.com/openai/v1"\n'
    '_RE: Final = re.compile(r"^[A-Za-z0-9-]+$")\n'
    "def azure_openai_base_url(resource: str) -> str:\n"
    "    if not _RE.fullmatch(resource):\n"
    '        raise ValueError("not a DNS label")\n'
    '    return f"https://{resource}{_SUFFIX}"\n'
)


def test_the_reference_builder_shape_passes() -> None:
    """The other half of every case below — a check that only fails is decorative.

    IT IS STATED PER LEG NOW (`leg_builder_failures`) RATHER THAN OVER THE POSTURE. The
    posture-level `builder_failures` loops every declared leg, so handing it a fixture
    containing ONE builder would report the other two as missing and every case below would
    pass for the wrong reason. The sabotages here are edits to the Azure builder, so the
    Azure leg is what they are stated against.
    """
    assert guard.leg_builder_failures(guard.AZURE_LEG, BUILDER_SOURCE) == []


def test_a_builder_that_grew_a_region_parameter_is_caught() -> None:
    """THE case check 4 exists for, and the only way a region other than the declared
    posture's could ever be emitted: give the builder somewhere to put one. Azure's
    endpoint has nowhere to put a region anyway, so such a parameter would be inert —
    which is worse than an error, because it reads like a residency control and is not
    one. The default in the doctored source below is `southindia` BECAUSE it is the
    withdrawn region: a builder that could still be steered back to the region D-449
    left is the sharpest form of this defect, not a leftover from before the move."""
    source = BUILDER_SOURCE.replace(
        "def azure_openai_base_url(resource: str) -> str:",
        'def azure_openai_base_url(resource: str, location: str = "southindia") -> str:',
    )
    offenders = guard.leg_builder_failures(guard.AZURE_LEG, source)
    assert any("'location'" in offender for offender in offenders), offenders
    # "exactly 1" rather than "exactly one argument" since D-432: the permitted arity is
    # a property of the DECLARED posture (`PostureSpec.builder_arity`) rather than a
    # constant of this check, so the refusal prints the number the declaration allows.
    assert any("permits exactly 1" in offender for offender in offenders), offenders


def test_a_builder_that_interpolates_a_runtime_value_is_caught() -> None:
    """The blind spot this file admits to, closed at the one place it matters. A hole that
    is neither the argument nor a module `Final` is a value computed somewhere the AST
    cannot follow — and the builder is the one function whose output has to be readable,
    because check 3's single exemption is granted on the strength of it."""
    source = BUILDER_SOURCE.replace(
        '    return f"https://{resource}{_SUFFIX}"',
        "    return f\"https://{resource}{os.environ['SUFFIX']}\"",
    )
    offenders = guard.leg_builder_failures(guard.AZURE_LEG, source)
    assert len(offenders) == 1, offenders
    assert "interpolates" in offenders[0] and "os.environ" in offenders[0]


def test_a_builder_that_returns_something_unreadable_is_caught() -> None:
    """A builder whose output cannot be read is not safer for being opaque — it is a
    constructor nothing has checked, holding an exemption granted to a constructor that
    was checked."""
    source = BUILDER_SOURCE.replace(
        '    return f"https://{resource}{_SUFFIX}"',
        "    return _assemble(resource)",
    )
    offenders = guard.leg_builder_failures(guard.AZURE_LEG, source)
    assert any("not a string template" in offender for offender in offenders), offenders


def test_a_builder_that_never_refuses_a_bad_resource_is_caught() -> None:
    """The attack the Vertex builder structurally could not have. `VERTEX_LOCATION` sat at
    the FRONT of its host, so whatever a caller interpolated landed in a PATH and the host
    stayed Google's. Azure's custom subdomain puts the caller's value at the very front of
    the authority, so a builder that interpolated freely turns `evil.example/x` into a URL
    whose HOST is an attacker's and whose tail merely reads like ours."""
    source = BUILDER_SOURCE.replace(
        '    if not _RE.fullmatch(resource):\n        raise ValueError("not a DNS label")\n',
        "",
    )
    offenders = guard.leg_builder_failures(guard.AZURE_LEG, source)
    assert len(offenders) == 1, offenders
    assert "never raises" in offenders[0] and "evil.example" in offenders[0]


def test_a_builder_whose_refusal_is_only_a_presence_check_is_caught() -> None:
    """ "It raises" is not enough, and this is the gap that the FIRST sabotage run found.

    `if not resource: raise` contains an `ast.Raise` and satisfies the coarse check, while
    accepting `"evil.example/x"` — the one input the refusal exists for. The resource
    becomes the first label of the hostname, so what has to be checked is its SHAPE against
    a pattern, never its presence.

    WHAT THIS STILL CANNOT DO, said here because it was learned by watching the check
    NOT go red: a guard rewritten to `if False and not _RE.fullmatch(resource)` keeps the
    raise and the pattern call and refuses nothing, and no AST reading distinguishes a
    predicate that can fire from one that cannot. That half is proved by CALLING the
    builder — `tests/in_call_llm_provider_test.py::test_a_resource_that_is_not_one_dns_
    label_is_refused_rather_than_interpolated` hands it the attack strings and requires a
    `ValueError`. Shape here, effect there, and neither pretending to be the other.
    """
    source = BUILDER_SOURCE.replace("    if not _RE.fullmatch(resource):", "    if not resource:")
    offenders = guard.leg_builder_failures(guard.AZURE_LEG, source)
    assert len(offenders) == 1, offenders
    assert "not behind a pattern match" in offenders[0], offenders
    assert "evil.example/x" in offenders[0], offenders


def test_a_renamed_or_deleted_builder_is_caught() -> None:
    """The failure that reads like a clean tree: with no builder, check 4 has nothing to
    judge and check 3's exemption is granted to a function that no longer exists."""
    source = BUILDER_SOURCE.replace("def azure_openai_base_url(", "def build_url(")
    offenders = guard.leg_builder_failures(guard.AZURE_LEG, source)
    assert len(offenders) == 1, offenders
    assert "defines no" in offenders[0] and "verified\nnothing" not in offenders[0]
    assert guard.BUILDER in offenders[0]


def test_the_real_builder_is_the_one_the_guard_reads() -> None:
    """Check 4 against the shipped function rather than a fixture — otherwise the cases
    above prove only that the fixture is well written. Both facts are asserted: the guard
    finds it, and the file it finds it in is the one check 3 exempts."""
    assert guard.builder_failures() == []
    source = (guard.REPO_ROOT / guard.BUILDER_HOME).read_text(encoding="utf-8")
    assert f"def {guard.BUILDER}(" in source
    assert guard.BUILDER_SUFFIX in source, (
        "the builder's suffix is spelled in this guard rather than imported, on the "
        "not-imported doctrine — so the two have to be tied together somewhere, and this "
        "is where. If the v1 path shape changes, both move deliberately."
    )


# --- 5: the check can still see -----------------------------------------------


def test_the_blindness_guard_fires_when_the_scan_finds_nothing() -> None:
    """Every failure mode of the guard — a parse error swallowed, a root renamed, `Final`
    detection broken — presents as a clean tree, so the run refuses to call a scan that
    found nothing a pass."""
    blind = guard.blindness_failures(0, {}, [])
    # Four kinds of blindness, and the last one is PER LEG WITH A BUILDER: the template floor,
    # the parse canary, the subject canary, and one missing-reference finding for each of the
    # THREE legs whose endpoint any literal may name at all (Google joined at D-478).
    assert len(blind) == 6, blind
    assert any("it is blind" in failure for failure in blind)
    assert any(
        all(region in failure for region in guard.KNOWN_REGIONS)
        for failure in blind
        if "KNOWN_REGIONS" in failure
    ), blind
    assert any(guard.REGION_CONSTANT in failure for failure in blind)
    assert any(guard.OPENAI_REGION_CONSTANT in failure for failure in blind)
    # SINCE D-478 the Google leg HAS a builder, so it too owes a reference: an empty scan is
    # blind to its host exactly as it is to the others'. (Its region is still None — the
    # reference canary is about the host literal, not a residency claim.)
    assert any(guard.GEMINI_DIRECT_HOST in failure for failure in blind), blind

    seeing = guard.blindness_failures(
        guard.MINIMUM_TEMPLATES,
        _canaries() | _pinned(),
        [
            guard.Reference(guard.BUILDER_HOME, 1, guard.BUILDER_SUFFIX, frozen=True),
            guard.Reference(guard.BUILDER_HOME, 2, guard.OPENAI_BUILDER_SUFFIX, frozen=True),
            guard.Reference(guard.BUILDER_HOME, 3, guard.GEMINI_BUILDER_SUFFIX, frozen=True),
        ],
    )
    assert seeing == []


def test_the_two_canaries_fail_apart() -> None:
    """They measure different things and the distinction is worth keeping.

    The guard's own `Final`s — one per region in `KNOWN_REGIONS` — are the PARSE canary, so
    their absence means the walk is broken. `AZURE_LOCATION` is the SUBJECT canary: its
    absence means the walk is fine and there is no residency decision left in the tree for
    it to read. One reading covering both would report a deleted decision as a broken scan.

    SINCE D-449 THE PARSE CANARY IS ONE PROBE PER KNOWN REGION, and a HALF-blind scan — one
    that still sees the declared region and has stopped seeing the withdrawn one — is
    caught here. That is the failure the old single probe could not express, and it is the
    one that would make a leftover `AZURE_LOCATION: Final = "southindia"` invisible.
    """
    references = [
        guard.Reference(guard.BUILDER_HOME, 1, guard.BUILDER_SUFFIX, frozen=True),
        guard.Reference(guard.BUILDER_HOME, 2, guard.OPENAI_BUILDER_SUFFIX, frozen=True),
        guard.Reference(guard.BUILDER_HOME, 3, guard.GEMINI_BUILDER_SUFFIX, frozen=True),
    ]

    parse_broken = guard.blindness_failures(guard.MINIMUM_TEMPLATES, _pinned(), references)
    assert len(parse_broken) == 1, parse_broken
    for region in guard.KNOWN_REGIONS:
        assert region in parse_broken[0], (region, parse_broken)

    half_blind = guard.blindness_failures(
        guard.MINIMUM_TEMPLATES,
        {k: v for k, v in _canaries().items() if k != "AZURE_REGION_INDIA"} | _pinned(),
        references,
    )
    assert len(half_blind) == 1, half_blind
    assert guard.AZURE_REGION_INDIA in half_blind[0], half_blind
    assert guard.AZURE_REGION_US not in half_blind[0], half_blind

    subject_gone = guard.blindness_failures(guard.MINIMUM_TEMPLATES, _canaries(), references)
    assert len(subject_gone) == 1 and "SUBJECT canary" in subject_gone[0], subject_gone
    assert guard.REGION_CONSTANT in subject_gone[0], subject_gone
    assert guard.OPENAI_REGION_CONSTANT in subject_gone[0], subject_gone


# --- 6: the honesty, which is the half D-410 made load-bearing ----------------


def test_the_guard_states_what_it_cannot_prove_on_every_run(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE TEST THIS FILE EXISTS FOR AFTER D-410, and it is not about catching a bad URL.

    The guard got weaker: `<resource>.openai.azure.com` names no region, so the region can
    no longer be proved from the AST. A weakened check that still prints a bare `OK` is
    strictly worse than a deleted one, because a reader takes the same sentence to mean the
    same thing it used to. So the notice has to reach a reader on BOTH paths, name BOTH
    facts a human owns, and name WHERE that human looks — a vague "see the docs" would be
    the same defect in a longer sentence.
    """
    notice = guard.delegated_notice(guard.declared_spec())
    for fact in (guard.AZURE_REGION_US, "REGIONAL", "GLOBAL", "portal", "gates 20 and 20c"):
        assert fact in notice, fact
    assert "azure_openai_resource" in notice
    assert "recorded cost rather than an oversight" in notice
    # D-449: the notice must say the India claim was WITHDRAWN, in those terms. A reader who
    # has seen the old text supplies the old meaning from memory otherwise, and this
    # paragraph is the one they rely on for what a green run does NOT cover.
    assert "WITHDRAWN" in notice and "not upgraded" in notice
    assert guard.AZURE_REGION_INDIA not in notice, (
        "the delegated gate is a US resource now; naming the withdrawn region as the thing "
        "a human confirms would send them to look for the wrong fact"
    )

    assert guard.main() == 0
    passed = capsys.readouterr().out
    assert "MODEL RESIDENCY: OK" in passed
    assert notice in passed, "a green run must still say what it did not check"

    # …and the failure path, driven through a synthetic failure so the notice is proved to
    # survive the branch where a reader is busiest and least likely to go looking for it.
    # `*_` since D-432: every check now takes the resolved `PostureSpec` main() hands it.
    monkeypatch.setattr(guard, "delegation_failures", lambda *_: ["synthetic"])
    assert guard.main() == 1
    failed = capsys.readouterr().out
    assert "MODEL RESIDENCY: FAIL" in failed
    assert notice in failed


def test_the_human_gate_that_owns_the_unprovable_half_is_written_down() -> None:
    """The other end of that sentence, against the real document.

    The notice points at OPERATIONS §2 gates 20 and 20c. A pointer to a deleted owner is
    worse than no pointer, because it converts "nobody has checked the region" into "the
    docs say somebody has". So the guard reads the document, and this proves it can.
    """
    assert guard.delegation_failures() == []

    operations = (guard.REPO_ROOT / guard.OPERATIONS_DOC).read_text(encoding="utf-8")
    gate = next(line for line in operations.splitlines() if line.startswith("| 20 "))
    assert "East US 2" in gate and "portal" in gate.lower()
    assert guard.SELF in gate, (
        "gate 20 no longer names the guardrail whose weakness it exists to cover — the "
        "two halves of D-410's residency posture have to point at each other"
    )


def test_the_delegation_check_fires_when_the_gate_is_gone() -> None:
    """Sabotage-verified through an injected document, because the real one cannot be
    emptied without deleting an operations gate."""
    offenders = guard.delegation_failures("# Operations\n\nNothing about Azure here.\n")
    assert len(offenders) == 1, offenders
    assert "prints OK over the gap" in offenders[0]

    # A gate that names the constant but no portal is not the gate: the whole content of
    # the delegation is that a PERSON goes and reads the resource.
    half = guard.delegation_failures(f"| 20 H | check `{guard.REGION_CONSTANT}` somehow |\n")
    assert len(half) == 1, half

    assert (
        guard.delegation_failures(f"| 20 H | read `{guard.REGION_CONSTANT}` in the portal |\n")
        == []
    )


# --- the dated allowance ------------------------------------------------------


def test_the_registry_is_empty_and_the_tree_needs_no_exception() -> None:
    """The state the registry is supposed to STAY in, asserted rather than assumed.

    Two halves, because they can fail apart: the real tree needs no exception at all, and
    no exception is granted. A registry that quietly regrew an entry for a file that no
    longer offends would be the permanent skip the dated-allowance design exists to make
    impossible.
    """
    references = guard.endpoint_references()
    assert guard.endpoint_failures(references, guard.frozen_region_constants(), allowances={}) == []
    assert guard.ALLOWANCES == {}, (
        "an allowance is granted again — read its `removed_by` and confirm it names the "
        "work that closes it, because the registry can only ever shrink"
    )


def test_an_allowance_whose_defect_has_gone_is_caught() -> None:
    """The freshness half, which is what makes the registry shrink-only. Driven through a
    SYNTHETIC allowance so it keeps proving the mechanism after every future entry is
    closed too — the `allowances=` seam exists for exactly this."""
    allowance = guard.DatedAllowance(
        host=guard.AZURE_HOST_SUFFIX,
        recorded="2026-08-19",
        reason="a bounded exception that has since been fixed",
        removed_by="the work that fixed it",
    )
    stale = guard.stale_allowances(
        references=[guard.Reference("apps/workers/extraction.py", 55, "https://api.sarvam.ai/")],
        allowances={"apps/workers/extraction.py": allowance},
    )
    assert len(stale) == 1, stale
    assert "DELETE the entry" in stale[0]

    # And the other direction: while the literal is still there, the entry is current and
    # nothing is reported. Without this the assertion above passes on a `stale_allowances`
    # that simply returns one failure for every entry it is given.
    still_current = guard.stale_allowances(
        references=[
            guard.Reference(
                "apps/workers/extraction.py",
                55,
                f"https://x{guard.AZURE_HOST_SUFFIX}/openai/v1",
            )
        ],
        allowances={"apps/workers/extraction.py": allowance},
    )
    assert still_current == []


def test_an_allowance_suspends_the_check_for_its_own_host_only() -> None:
    """An allowance is a DEFERRAL of one defect, not a licence for the file. Without this,
    `endpoint_failures` could be satisfied by any entry naming the path and the registry
    would be a per-file skip with a date on it."""
    reference = guard.Reference("apps/workers/extraction.py", 9, "https://x.openai.azure.com/v1")
    allowance = guard.DatedAllowance(
        host=guard.AZURE_HOST_SUFFIX, recorded="2026-08-19", reason="bounded", removed_by="work"
    )
    assert guard.endpoint_failures([reference], {}, {"apps/workers/extraction.py": allowance}) == []

    # The same file, allowed for a DIFFERENT host, is still judged.
    other = guard.DatedAllowance(
        host=guard.OPENAI_DIRECT_HOST, recorded="2026-08-19", reason="bounded", removed_by="work"
    )
    assert len(guard.endpoint_failures([reference], {}, {"apps/workers/extraction.py": other})) == 1


# --- anti-rubber-stamp --------------------------------------------------------


def test_a_watched_host_in_prose_is_not_a_violation(tmp_path: Path) -> None:
    """This is an AST walk, not a grep, and the difference is load-bearing HERE more than
    anywhere: the guard's own docstring, the D-410 row and SECURITY-COMPLIANCE §4 all name
    the disqualified hosts in order to disqualify them. A source-text scan would report the
    explanation as the offence and teach the next reader to delete the explanation."""
    root = _tree(
        tmp_path,
        '"""We do NOT call api.openai.com — see D-410, and the endpoint is\n'
        'built by azure_openai_base_url() rather than spelled .openai.azure.com."""\n'
        "# nor southindia.api.cognitive.microsoft.com, which is rejected for now\n"
        "SAFE = 1\n",
    )
    assert _failures(root) == []


def test_a_watched_host_in_a_non_python_file_is_caught(tmp_path: Path) -> None:
    """The text half, which has no subject in this repo today and therefore no evidence
    that it works — a tripwire nobody has stepped on is a tripwire nobody has connected.

    The frontend must never call a model provider (CLAUDE.md forbids it and there is no
    ad-hoc fetch), so this guards against the day somebody does it in a deploy script or a
    route handler rather than being a check with daily work to do. A line naming a watched
    host becomes a reference and is judged by the same rules — the second half of this test
    is what proves that.
    """
    (tmp_path / "assist.ts").write_text(
        'const ENDPOINT = "https://calevate.openai.azure.com/openai/v1";\n',
        encoding="utf-8",
    )
    offenders = _failures(tmp_path)
    assert len(offenders) == 1, offenders
    assert "assist.ts:1" in offenders[0] and "by hand" in offenders[0]

    # The per-leg rules reach it too — the text half is line-level, not name-level, and the
    # clause it lands on is the one for the leg whose host it names.
    (tmp_path / "assist.ts").write_text(
        'const ENDPOINT = "https://api.openai.com/v1";\n', encoding="utf-8"
    )
    direct = _failures(tmp_path)
    assert len(direct) == 1 and "GLOBAL endpoint" in direct[0], direct


def test_the_google_apis_that_remain_are_not_judged() -> None:
    """`workers/google_sheets.py` reaches `oauth2.` and `sheets.googleapis.com` on every
    CRM export, and D-410 left Google there deliberately (SECURITY-COMPLIANCE §4: Sheets
    only, no model legs). Those are the tenant's own destination and carry no inference; a
    guard that fired on them would be turned off within a week.

    SINCE D-478 the ONE `googleapis.com` reference the scan may see is the Gemini leg's
    builder suffix in the contract — the copilot's OpenAI-compat host. The Sheets and OAuth
    hosts still must NOT appear as references at all: the watched string is the full Gemini
    host, never `.googleapis.com`, precisely so they do not."""
    hosts = [reference.template for reference in guard.endpoint_references()]
    assert not any("sheets.googleapis.com" in template for template in hosts), hosts
    assert not any("oauth2.googleapis.com" in template for template in hosts), hosts
    googleapis = [template for template in hosts if "googleapis.com" in template]
    assert googleapis == [guard.GEMINI_BUILDER_SUFFIX], googleapis


def test_the_docstring_exemption_is_load_bearing_on_the_real_tree() -> None:
    """It was not when this guard shipped, and it is — which is a fact worth pinning rather
    than a note worth leaving stale.

    `_templates` skips docstrings because the guard's whole subject is a set of hosts that
    have to be NAMED in order to be watched. Turning the exemption off REPORTS THOSE
    EXPLANATIONS AS THE OFFENCE, which is exactly the failure mode the exemption exists to
    prevent, and this is the evidence.

    FOUR FILES MAKE THE ARGUMENT, and it is worth knowing which:

      extraction.py             why the region is invisible in the Azure hostname
      calevate_shared/engine.py the builder's own docstring, on the v1 surface it emits
      engine/bolna.py           why `provider: "google"` is REFUSED rather than missing
      check_model_residency.py  this guard's explanation of every watched host

    `bolna.py` JOINED THE LIST WHEN GEMINI'S HOST BECAME A WATCHED ONE, and that is the
    exemption doing its job rather than drifting: the docstring at `_llm_routing` names
    `generativelanguage.googleapis.com` in order to say the branch that would reach it is
    refused, which is exactly the "a correction has to be EXPLAINED somewhere" case. A
    source-text scan would report the explanation as the offence.

    If this list ever reaches a size where updating it feels like paperwork, model
    endpoints have spread through the tree and THAT is the finding.
    """
    original = guard._docstrings
    try:
        guard._docstrings = lambda tree: set()
        references = guard.endpoint_references()
        failures = guard.endpoint_failures(references, guard.frozen_region_constants())
    finally:
        guard._docstrings = original

    offenders = {failure.split(":", 1)[0] for failure in failures}
    assert offenders == {
        "apps/api/engine/bolna.py",
        "apps/workers/extraction.py",
        guard.BUILDER_HOME,
        guard.SELF,
    }, offenders

    # And with the exemption restored, the same tree is clean — otherwise the assertion
    # above would be evidence of a broken tree rather than of a working exemption.
    assert (
        guard.endpoint_failures(guard.endpoint_references(), guard.frozen_region_constants()) == []
    )


def test_the_guard_judges_its_own_file_apart_from_the_declarations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The single-file hole, narrowed from a whole file to a handful of exact strings.

    The guard has to name the hosts to watch them and the suffix to permit it, so SOMETHING
    here must be exempt. It is `_host_definition`: a template that IS one of those strings
    and nothing else — none of which has a scheme or a label in front of it, so none of
    them is an endpoint.

    Driven through a DOCTORED file standing in for `SELF`, because the real one cannot be
    made to offend without editing the guard — and a test that could not watch the
    exemption fail would be asserting about a `continue`.
    """
    stand_in = tmp_path / "check_model_residency.py"
    declarations = (
        "from typing import Final\n"
        f'AZURE_HOST_SUFFIX: Final = "{guard.AZURE_HOST_SUFFIX}"\n'
        f'AZURE_REGIONAL_HOST_SUFFIX: Final = "{guard.AZURE_REGIONAL_HOST_SUFFIX}"\n'
        f'OPENAI_DIRECT_HOST: Final = "{guard.OPENAI_DIRECT_HOST}"\n'
        f'BUILDER_SUFFIX: Final = "{guard.BUILDER_SUFFIX}"\n'
    )
    stand_in.write_text(declarations, encoding="utf-8")
    monkeypatch.setattr(guard, "SELF", guard._rel(stand_in))
    assert _failures(tmp_path) == [], "the guard cannot declare the hosts it watches"

    # A URL, in the guard's own file. A whole-file skip would pass this, and a whole-file
    # skip would put the tree's single hole in the file a person edits when relaxing it.
    stand_in.write_text(
        declarations + 'FALLBACK = "https://calevate.openai.azure.com/openai/v1"\n',
        encoding="utf-8",
    )
    failures = _failures(tmp_path)
    assert len(failures) == 1, failures
    assert "by hand" in failures[0]


def test_the_real_guard_names_the_hosts_only_as_declarations() -> None:
    """The other side of that rule, against the real file rather than a stand-in: no
    reference the scan produces comes from `SELF`, because the only literals there that
    could produce one are the four declarations. A URL added to this file would appear here
    AND fail `test_the_real_tree_is_clean`."""
    assert [r for r in guard.endpoint_references() if r.path == guard.SELF] == []
    source = (guard.REPO_ROOT / guard.SELF).read_text(encoding="utf-8")
    for host in guard.SELF_DECLARATIONS:
        assert host in source


def test_the_guards_own_region_constant_is_the_one_the_decision_row_pins() -> None:
    """The canary's own premise, and the one thing no other check can cover.

    The region constants are spelled in the guard rather than imported (the
    `check_bootstrap_keys.BOOTSTRAP_KEYS` argument: a guardrail that imported the value it
    checks would be asking the code whether it agrees with itself). The cost of that is
    that editing one would break nothing — every other test in this file would keep passing
    against the new region. The decision log is the only outside authority on which region
    is permitted, so this is where the two are tied together.

    IT READS D-449's ROW, NOT D-410's (which pinned `southindia` and is superseded on the
    region alone). Retargeting it is the point of the test rather than maintenance of it:
    if the guard's declared region and the decision that authorises it can drift apart, the
    guard is enforcing a region nobody decided on.
    """
    assert guard.AZURE_REGION_US == "eastus2"
    assert guard.OPENAI_REGION_US == "us", (
        "the OpenAI leg's region is spelled here rather than imported, on the same doctrine "
        "— and unlike the Azure one it is also the first label of a hostname, so this "
        "constant and `openai_base_url()` have to agree or check 4 refuses the builder"
    )
    assert guard.AZURE_REGION_INDIA == "southindia", (
        "the WITHDRAWN region keeps its constant so the guard can still refuse it — see "
        "AZURE_REGION_INDIA and KNOWN_REGIONS"
    )
    roadmap = (guard.REPO_ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    row = next(line for line in roadmap.splitlines() if line.startswith("| D-449 "))
    assert f"`{guard.AZURE_REGION_US}`" in row, (
        "D-449 no longer pins the region this guard enforces — one of the two moved"
    )
    assert guard.SELF in row, "D-449 no longer names the guardrail that enforces it"
    assert f"`{guard.BUILDER}()`" in row, (
        "D-449 no longer names the one builder check 3 grants its single exemption to"
    )


# --- the raw-transcript leg: one prophylactic clause, and its boundary -----------
#
# `SARVAM_CHAT_URL` is the endpoint the FIRST post-call extraction posts to, and that pass
# reads `turn.text` — the raw transcript, digits and all (`GEMINI_EXTRACTION_DEFAULT is
# False`). The Azure endpoint has a builder, a single-literal rule and four AST checks
# behind it; this one had nothing, and was a rebindable module global besides — the exact
# thing `_is_builder_suffix` calls "a knob" when it makes `frozen` a condition of its own
# exemption.


def test_the_raw_transcript_endpoint_is_frozen() -> None:
    """`SARVAM_CHAT_URL` must be `Final`.

    FAILS IF: the annotation is dropped from `apps/workers/extraction.py`. `Final` does
    not stop a runtime rebind — nothing in Python does — but it makes one a mypy error in
    CI and a thing a reviewer sees, which is exactly the strength the Azure suffix has and
    this constant did not.
    """
    import ast

    source = (guard.REPO_ROOT / "apps" / "workers" / "extraction.py").read_text(encoding="utf-8")
    assignments = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "SARVAM_CHAT_URL"
    ]
    assert len(assignments) == 1, (
        "SARVAM_CHAT_URL is not a single annotated module constant; a plain assignment is "
        "a rebindable global on the leg that sees un-redacted caller PII"
    )
    assert guard._is_final(assignments[0].annotation), "SARVAM_CHAT_URL is no longer Final"


def test_a_settings_default_pointing_at_the_raw_transcript_host_is_refused() -> None:
    """The prophylactic half: today no `Settings` field points at Sarvam, so this clause
    guards a field nobody has written yet.

    It is worth having because `managed_fields()` derives the console-editable set by
    SUBTRACTION — `Settings` minus bootstrap keys minus credential-shaped names — so a
    future `sarvam_base_url` would be editable from a web form the day it was declared,
    with nothing to notice. A text box that re-points THIS leg moves raw caller PII, not
    redacted prose.

    FAILS IF: the `SETTINGS_ENDPOINT_HOSTS` clause is deleted from
    `console_config_failures`, or the host is dropped from that tuple.
    """
    failures = guard.console_config_failures(
        {"sarvam_base_url": "https://api.sarvam.ai/v1"}, {"sarvam_base_url"}
    )
    assert len(failures) == 1, failures
    assert "sarvam_base_url" in failures[0]
    assert "RAW transcript" in failures[0]


def test_the_raw_transcript_host_is_deliberately_not_a_watched_host() -> None:
    """The boundary of the clause above, stated so the next reader does not "finish the
    job" by adding the host to `WATCHED_HOSTS`.

    That tuple feeds `endpoint_failures`, where every failure clause names its OWN host
    and its own remedy — so a host with no clause there produces zero findings. What
    adding it WOULD do is widen `SELF_DECLARATIONS`, i.e. grow the set of strings this
    guard exempts from its own scan, and pull the host into the docs-prose machinery:
    cost with no check behind it.

    FAILS IF: somebody adds it to `WATCHED_HOSTS` without adding the `endpoint_failures`
    clause that would make it mean something.
    """
    assert not guard._mentions_watched_host("https://api.sarvam.ai/v1/chat/completions")
    assert "api.sarvam.ai" not in guard.SELF_DECLARATIONS
    assert guard.SETTINGS_ENDPOINT_HOSTS == ("api.sarvam.ai",)


def test_an_ordinary_settings_default_is_still_not_reported_twice() -> None:
    """The new clause sits BEFORE the watched-host one and `continue`s, so a field cannot
    earn two findings.

    FAILS IF: the `continue` is dropped, or the clause is moved below the watched-host
    check — either way an Azure-shaped default would be reported once by each.
    """
    failures = guard.console_config_failures(
        {"some_url": f"https://x{guard.AZURE_HOST_SUFFIX}/openai/v1"}, {"some_url"}
    )
    assert len(failures) == 1, failures


def test_the_regional_hostname_under_a_posture_with_no_azure_leg_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The arm that only exists once a posture can be declared WITHOUT an Azure leg.

    With `REGIONAL_HOST_ADOPTED` flipped, the regional-host clause compares the label against
    the Azure leg's region — and under a declaration that has no Azure leg there is no region
    to compare it to. The honest answer is a refusal naming that fact, not a `None`
    dereference and not silence: a regional Azure hostname in a tree whose declaration has
    left Azure is exactly the artefact a half-finished posture move produces.

    FAILS IF: the clause assumes an Azure leg exists, which is what it did while a posture
    could only ever have one leg.
    """
    monkeypatch.setattr(guard, "REGIONAL_HOST_ADOPTED", True)
    root = _tree(tmp_path, 'URL = "https://eastus2.api.cognitive.microsoft.com/openai/v1"\n')
    references = guard.endpoint_references(roots=(root,))
    offenders = guard.endpoint_failures(
        references,
        frozen=guard.frozen_region_constants(roots=(root,)),
        allowances={},
        spec=guard.POSTURES["google-direct"],
    )
    assert len(offenders) == 1, offenders
    assert "declares no Azure leg at all" in offenders[0], offenders


def test_the_region_knob_remedy_inverts_under_a_posture_that_pins_nothing() -> None:
    """The rule never had a vendor, but the REMEDY has to follow the declaration.

    Under a posture with a region-pinning leg the answer is "move it into that leg's frozen
    constant". Under one that pins no region on any leg there IS no such constant, and
    telling the reader to create one would be the opposite instruction — the field should not
    exist at all, because a console knob naming a region under a posture that makes no
    regional claim is a promise the declaration does not make.
    """
    pinning = guard.console_config_failures(
        fields={"llm_region": None}, managed=[], spec=guard.POSTURES["us-azure-openai"]
    )
    assert len(pinning) == 1 and guard.REGION_CONSTANT in pinning[0], pinning
    assert "3am" in pinning[0], pinning

    unpinned = guard.console_config_failures(
        fields={"llm_region": None}, managed=[], spec=guard.POSTURES["google-direct"]
    )
    assert len(unpinned) == 1, unpinned
    assert "pins NO region" in unpinned[0] and "should not exist" in unpinned[0], unpinned
    assert guard.REGION_CONSTANT not in unpinned[0], (
        "pointing a reader at a constant this posture forbids is the opposite instruction"
    )


def test_a_module_qualified_builder_call_still_counts_as_a_caller(tmp_path: Path) -> None:
    """Check 7 asks whether anybody BUILDS this leg's endpoint, and a caller that imported
    the module rather than the name is still a caller.

    `engine.azure_openai_base_url(...)` and `azure_openai_base_url(...)` are the same call and
    a scan that saw only the second would report a live leg as inert — which under check 7 is
    a red build on a tree that is fine, i.e. the failure mode that gets a check deleted.
    """
    root = _tree(
        tmp_path,
        "from calevate_shared import engine\n"
        'URL = engine.azure_openai_base_url("calevate-prod")\n'
        "OTHER = engine.openai_base_url()\n",
    )
    sites = guard.builder_call_sites(roots=(root,))
    assert sites[guard.BUILDER], sites
    assert sites[guard.OPENAI_BUILDER], sites

    # …and a MENTION is not a call: an import, an `__all__` entry or a docstring naming the
    # builder must not satisfy a check about whether the leg is exercised.
    (tmp_path / "client.py").unlink()
    mention = _tree(
        tmp_path,
        "from calevate_shared.engine import azure_openai_base_url\n"
        '__all__ = ["azure_openai_base_url"]\n'
        '"""We build endpoints with azure_openai_base_url."""\n',
        name="mention.py",
    )
    assert guard.builder_call_sites(roots=(mention,)) == {
        guard.BUILDER: [],
        guard.OPENAI_BUILDER: [],
        guard.GEMINI_BUILDER: [],
    }
