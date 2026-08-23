"""The DECLARED residency posture and its LEGS, proved in both directions of drift.

`tests/model_residency_guard_test.py` proves the guard's structural checks can go red. This
file proves the thing underneath them: that the posture is a DECLARATION, that the
declaration and the tree are compared, and that the comparison fails BOTH WAYS.

**WHY BOTH WAYS IS THE WHOLE POINT.** Making a hard-wired posture declared is a weakening
unless the declaration is checked, because the obvious way to build it — read a flag, run
the matching checks — lets one edited word move the product's residency posture past a
green build. So:

* **CODE DRIFTS FROM DECLARATION**: the tree grows an endpoint or loses a builder while
  still declaring a posture that forbids it. Checks 1-4 catch it.
* **DECLARATION DRIFTS FROM CODE**: the declaration is edited to a single-leg posture while
  the tree is unchanged and still has three. This is the cheap direction — one line — and it
  is the one a flag-reading guard would wave through. Here it fails many ways at once,
  against the REAL repository.

**AND THE POSTURE IN FORCE IS `multi-provider-byok`.** D-432 built the mechanism, D-449 threw
the switch once (India → US, still one vendor), and the provider choice opened the posture
from one vendor to a closed ORDERED SET OF LEGS. `test_the_multi_provider_posture_is_the_one_
in_force` is the standing assertion: it pins the declared name, the legs in order, each
leg's region and — the half a name check alone cannot reach — which of them can PROVE that
region and which delegates it to a human.

**THE ONE THING THE OPENING OF THE POSTURE BOUGHT BACK IS PINNED HERE TOO.**
`test_the_openai_leg_is_the_only_one_whose_region_a_build_can_prove` reads the region off
`openai_base_url()`'s own return template through the guard, which is the first residency
claim provable from this tree's AST since D-127. Everything else about this change makes the
guard prove LESS (the guard's own docstring records the arithmetic); this is the half that
makes the trade worth it, so it is asserted rather than described.
"""

from __future__ import annotations

import re
from decimal import Decimal

import pytest
from calevate_shared import engine
from calevate_shared.engine import (
    DECLARED_LEGS,
    DECLARED_POSTURE,
    GOOGLE_DIRECT_MODELS,
    LLM_MODEL_NAMES,
    LLM_MODELS,
    SELECTABLE_LLM_MODELS,
    AzureOpenAIModel,
    Evidence,
    GoogleDirectModel,
    LlmModelSpec,
    LlmPrice,
    ModelConfig,
    OpenAIDirectModel,
    PostureLeg,
    ResidencyPosture,
    azure_openai_base_url,
    bind_model,
    leg_for_model,
    openai_base_url,
)
from scripts import check_model_residency as guard

#: The posture in force.
DECLARED = guard.POSTURES["multi-provider-byok"]
#: The posture D-449 declared and the provider choice superseded — ONE Azure leg. Used only
#: as a fixture: stating the shipped tree against it is what makes the guard's refusal of a
#: declaration that has dropped two legs observable.
SINGLE_AZURE = guard.POSTURES["us-azure-openai"]
#: The WITHDRAWN posture (D-449). It pins a DIFFERENT region on the same vendor, which is the
#: only way to state that this guard tells two pinned regions apart rather than merely
#: telling a pin from an absence.
INDIA = guard.POSTURES["india-azure-openai"]
#: Two single-leg fixtures whose builder the contract still defines, and one whose it never
#: will.
OPENAI_ONLY = guard.POSTURES["openai-direct"]
GOOGLE_ONLY = guard.POSTURES["google-direct"]

TODAY_EVIDENCE = Evidence(source="fixture", read_on=engine.date(2026, 8, 22), verified=True)


def _spec(**kwargs: object) -> LlmModelSpec:
    base: dict[str, object] = {
        "model": "fixture-model",
        "provider": "azure_openai",
        "price": LlmPrice(
            input_usd_per_mtok=Decimal("1"),
            output_usd_per_mtok=Decimal("2"),
            evidence=TODAY_EVIDENCE,
        ),
        "traps": (),
        "selectable": True,
        "withdrawn_reason": None,
    }
    base.update(kwargs)
    return LlmModelSpec(**base)  # type: ignore[arg-type]


# --- the standing assertion ---------------------------------------------------


def test_the_multi_provider_posture_is_the_one_in_force() -> None:
    """THE TRIPWIRE, RE-AIMED RATHER THAN DELETED.

    It has asserted `india-azure-openai`, then `us-azure-openai`, and now a posture that is
    not one vendor at all. Its job is unchanged: the posture cannot move as a side effect of
    somebody touching this file.

    IT IS STRICTER THAN THE ONE IT REPLACES IN THE HALF THAT MATTERS MOST. A name check alone
    would pass a tree that declared three legs and pinned nothing; this pins the legs IN
    ORDER, each leg's region VALUE, and `region_in_host` — which is the field that decides
    whether a human owes an attestation or a build can settle it.

    If this fails, somebody changed where this product's language models run. That is a DPA
    change (`apps/web/src/lib/legal/dpa.ts` states the posture to clients in an executed
    agreement), not a code change.
    """
    name, failures = guard.declared_posture_name()
    assert failures == []
    assert name == "multi-provider-byok"
    assert guard.declaration_failures(name) == []
    assert DECLARED_POSTURE.name == name

    assert [leg.provider for leg in DECLARED_POSTURE.legs] == ["azure_openai", "openai", "google"]
    assert DECLARED_POSTURE.legs == DECLARED_LEGS

    azure = DECLARED_POSTURE.leg("azure_openai")
    assert azure.region == "eastus2" and azure.region_in_host is False
    assert azure.delegated_gate == ("AZURE_LOCATION", "portal")

    direct = DECLARED_POSTURE.leg("openai")
    assert direct.region == "us" and direct.region_in_host is True
    assert direct.delegated_gate is None, (
        "the OpenAI leg carries its region in the authority, so it owes no portal "
        "attestation — that absence is the prize this leg was adopted for"
    )

    google = DECLARED_POSTURE.leg("google")
    assert google.region is None and google.builder is None and google.builder_suffix is None

    assert "india-azure-openai" in guard.POSTURES, (
        "the WITHDRAWN posture must stay checkable: a mechanism that can only express the "
        "posture in force proves nothing about the posture in force, and dropping this row "
        "deletes the only way to ask whether the tree would still pass as an Indian one"
    )
    assert INDIA.legs[0].region == "southindia" and INDIA.name != name


def test_the_openai_leg_is_the_only_one_whose_region_a_build_can_prove() -> None:
    """THE ONE THING OPENING THE POSTURE BOUGHT BACK, asserted rather than described.

    Under D-127 residency was provable from the AST: Vertex put `asia-south1` in the host AND
    in the path. D-410 lost that — `<resource>.openai.azure.com` names no region — and every
    residency statement since has been a human attestation. `us.api.openai.com` puts the
    region back in the authority, so `leg_builder_failures` reads it off the builder's own
    return template.

    THE NEGATIVE CONTROL IS WHAT MAKES IT EVIDENCE. A builder returning the vendor's GLOBAL
    endpoint satisfies every other clause in check 4 — right arity, no region parameter, no
    runtime hole — and is refused by this one alone.

    FAILS IF: `region_in_host` stops being read, or `openai_base_url()` stops interpolating
    `OPENAI_DATA_RESIDENCY`.
    """
    leg = DECLARED.leg("openai")
    assert leg is not None and leg.region_in_host
    assert guard.leg_builder_failures(leg, _contract()) == []
    assert openai_base_url() == "https://us.api.openai.com/v1"

    globalised = (
        _contract()
        .replace(
            'return f"https://{OPENAI_DATA_RESIDENCY}{_OPENAI_ENDPOINT_SUFFIX}"',
            'return f"https://api.openai.com{_OPENAI_PATH}"',
        )
        .replace(
            '_OPENAI_ENDPOINT_SUFFIX: Final = ".api.openai.com/v1"',
            '_OPENAI_ENDPOINT_SUFFIX: Final = ".api.openai.com/v1"\n_OPENAI_PATH: Final = "/v1"',
        )
    )
    offenders = guard.leg_builder_failures(leg, globalised)
    assert len(offenders) == 1, offenders
    assert "residency label" in offenders[0] and "GLOBAL" in offenders[0], offenders
    assert "OPENAI_DATA_RESIDENCY" in offenders[0], offenders

    # …and the Azure leg makes NO such claim, which is the honest half: its region is not in
    # the URL, so nothing here can read it and gates 20/20c own it instead.
    azure = DECLARED.leg("azure_openai")
    assert azure is not None and not azure.region_in_host
    assert azure.delegated_gate is not None


def _contract() -> str:
    return (guard.REPO_ROOT / guard.CONTRACT).read_text(encoding="utf-8")


def test_the_guard_tells_two_pinned_regions_apart_on_the_real_tree() -> None:
    """THE PROOF THAT THE REGION IS COMPARED BY VALUE RATHER THAN BY NAME.

    Nothing here is doctored: this is the repository exactly as it ships, stated against two
    specs whose Azure leg differs ONLY in the region it pins. A posture move under a
    name-only design leaves `AZURE_LOCATION` unchecked by VALUE, which is exactly the half a
    hurried move forgets.

    THE FAILURE MUST NAME BOTH REGIONS, and that is asserted rather than assumed: a message
    saying only that something is wrong sends the reader to the declaration, which is the
    half that is usually right.
    """
    constants = guard.frozen_region_constants()

    assert guard.single_spelling_failures(constants, DECLARED) == []

    refused = guard.single_spelling_failures(constants, INDIA)
    assert refused, refused
    joined = " ".join(refused)
    assert INDIA.legs[0].region in joined and "eastus2" in joined, refused
    assert guard.REGION_CONSTANT in joined, refused

    # THE CANARY, so the two results above cannot both be produced by a scan that has
    # silently stopped seeing anything.
    assert (
        guard.blindness_failures(
            guard.template_count(), constants, guard.endpoint_references(), DECLARED
        )
        == []
    )
    assert constants[guard.REGION_CONSTANT] == (guard.BUILDER_HOME, "eastus2")
    assert constants[guard.OPENAI_REGION_CONSTANT] == (guard.BUILDER_HOME, "us")


def test_a_region_constant_no_declared_leg_pins_is_refused() -> None:
    """The arm that only exists once a posture can hold more than one leg.

    Under a single-leg declaration the OpenAI residency constant is a frozen constant
    spelling a KNOWN region that nothing in the declaration pins — a promise nothing keeps,
    and precisely the artefact a posture move that dropped a leg would leave behind.
    """
    constants = guard.frozen_region_constants()
    refused = guard.single_spelling_failures(constants, SINGLE_AZURE)
    assert refused, refused
    assert any(guard.OPENAI_REGION_CONSTANT in failure for failure in refused), refused
    assert any("no declared leg pins" in failure for failure in refused), refused


def test_the_declaration_is_source_and_nothing_else() -> None:
    """It is a `Final` literal in the portability contract: not a setting, not an
    environment variable, not a `platform_config` row.

    The three refusals are asserted rather than assumed because each is a different way the
    mechanism would stop being a posture. A settings field is the D-95 §4 failure — a
    residency decision invertible from a web form at 3am.
    """
    declarations = guard._final_string_constants(guard.DECLARATION_CONSTANT)
    assert len(declarations) == 1, declarations
    assert declarations[0].path == guard.CONTRACT
    assert declarations[0].frozen, "a rebindable module global is a knob, not a declaration"

    fields, managed = guard.live_settings()
    assert not [name for name in fields if "posture" in name.lower()]
    assert guard.console_config_failures(
        {**fields, "llm_residency_posture": None}, {*managed, "llm_residency_posture"}
    ), "a Settings field naming the posture must be refused whatever its default"


# --- DECLARATION drifts from CODE ---------------------------------------------


def test_declaring_a_single_leg_posture_over_the_real_tree_is_caught() -> None:
    """THE CENTRAL NEGATIVE CONTROL, and the one a flag-reading guard would miss.

    Nothing here is doctored: the repository is exactly as it ships, and only the posture
    handed to the checks changes. Dropping two legs from the declaration leaves a tree that
    still freezes their region, still names their host and still defines their builder —
    every one of which is now a claim the declaration does not make.
    """
    references = guard.endpoint_references()
    constants = guard.frozen_region_constants()

    region = guard.single_spelling_failures(constants, OPENAI_ONLY)
    assert region and any(guard.REGION_CONSTANT in failure for failure in region), region

    endpoints = guard.endpoint_failures(references, constants, {}, OPENAI_ONLY)
    assert endpoints and any(guard.AZURE_HOST_SUFFIX in failure for failure in endpoints)
    assert any("declaration was edited without the tree" in failure for failure in endpoints)

    record = guard.declaration_failures("openai-direct")
    assert record, record
    assert any(guard.LEGS_CONSTANT in failure for failure in record), record


def test_every_posture_in_the_table_is_stated_against_the_real_tree() -> None:
    """THE NEGATIVE CONTROL, STATED OVER THE WHOLE TABLE RATHER THAN ONE FIXTURE.

    Written one posture at a time, a table ends up with a row nothing has ever been stated
    against — and a spec nobody has watched refuse anything is a spec that could be
    describing a posture this guard has no way to check. So: exactly one posture passes the
    real tree, and every other one is refused by something.

    WHY "REFUSED BY SOMETHING" AND NOT A FIXED COUNT PER POSTURE. The postures fail
    DIFFERENTLY and that is correct: `india-azure-openai` differs from the declaration in the
    region and in two missing legs; `google-direct` differs in every field there is. A test
    demanding the same count from each would be asserting that the postures are the same
    posture.

    FAILS IF: a `PostureSpec` is added that the shipped tree would ALSO satisfy — which is
    the one thing a second declarable posture must never be.
    """
    references = guard.endpoint_references()
    constants = guard.frozen_region_constants()
    declared, resolution = guard.declared_posture_name()
    assert resolution == [] and declared is not None

    for name, spec in sorted(guard.POSTURES.items()):
        refusals = (
            guard.single_spelling_failures(constants, spec)
            + guard.endpoint_failures(references, constants, {}, spec)
            + guard.builder_failures(None, spec)
            + guard.declaration_failures(name)
            + guard.inert_leg_failures(spec=spec)
        )
        if name == declared:
            assert refusals == [], (name, refusals)
        else:
            assert refusals, (
                f"posture {name!r} is a row nothing can distinguish from the declared one "
                "over the real tree — either it is not a different posture, or this guard "
                "cannot tell that it is"
            )


def test_declaring_google_only_over_the_real_tree_is_refused_by_every_check() -> None:
    """The leg with no builder, stated over the shipped tree.

    It earns its own test rather than only a row in the loop above because the two things it
    proves are invisible from a count. Check 3 refuses the Azure and OpenAI literals by
    naming Gemini's host as the only one this declaration permits — possible only because
    `permitted_host` is read from the spec and the watched-host set is derived from the
    table. And check 4 says NOTHING, because a leg with no builder has no function to read:
    the obligation moved into check 3's zero-literal rule instead, which is stronger.

    FAILS IF: `google-direct` is deleted, or `builder=None` starts demanding a function.
    """
    references = guard.endpoint_references()
    constants = guard.frozen_region_constants()

    region = guard.single_spelling_failures(constants, GOOGLE_ONLY)
    assert region and any("no declared leg pins" in failure for failure in region), region

    endpoints = guard.endpoint_failures(references, constants, {}, GOOGLE_ONLY)
    assert endpoints, endpoints
    assert all(GOOGLE_ONLY.legs[0].permitted_host in failure for failure in endpoints), endpoints

    assert guard.builder_failures(None, GOOGLE_ONLY) == [], (
        "a leg with no builder has nothing for check 4 to read, and demanding a function "
        "there would demand an endpoint the engine would never send"
    )

    record = guard.declaration_failures("google-direct")
    assert record and any(guard.LEGS_CONSTANT in failure for failure in record), record

    assert GOOGLE_ONLY.legs[0].delegated_gate is None
    assert guard.delegation_failures("no gate here", GOOGLE_ONLY) == []
    assert "NO REGIONAL CLAIM" in GOOGLE_ONLY.legs[0].warrant


def test_a_posture_name_the_guard_does_not_know_is_a_hard_failure() -> None:
    """The single word that would otherwise bypass the whole mechanism.

    A guard that accepted an unrecognised name would enforce nothing while printing the same
    `OK` — worse than the hard-wiring D-432 replaced, because the green line now carries a
    posture's name and a reader would believe it.
    """
    failures = guard.declaration_failures("cheap-us-region")
    assert len(failures) == 1
    assert "not one this check knows" in failures[0]
    assert "decision-log entry" in failures[0]


def test_a_record_that_contradicts_its_own_declared_name_is_caught() -> None:
    """The declaration is a NAME, a RECORD and a TUPLE OF LEGS, and the record is what the
    runtime obeys. A name that said one thing beside a record that carried other legs would
    leave `engine.bind_model` and `agents.service.in_call_llm` acting on one posture while
    every static check enforced another."""
    coherent = {"name": guard.DECLARATION_CONSTANT, "legs": guard.LEGS_CONSTANT}
    assert guard.declaration_failures("multi-provider-byok", coherent) == []

    for field, wrong in (
        ("legs", "(AZURE_OPENAI_LEG,)"),
        ("name", '"multi-provider-byok"'),
    ):
        failures = guard.declaration_failures("multi-provider-byok", {**coherent, field: wrong})
        assert len(failures) == 1 and f"declares {field}=" in failures[0], (field, failures)


def test_a_leg_record_that_contradicts_its_spec_is_caught() -> None:
    """THE LEG HALF OF CHECK 0, and the reason each leg is its own module `Final`.

    The guard reads the declaration's keywords from the AST and compares SCALARS. An inline
    tuple of records would arrive as one opaque source string and this check would degrade to
    matching a rendering nobody controls — so every field below is doctored one at a time in
    a copy of the real contract and has to be caught by name.

    THE `region` FIELD IS THE SHARP ONE. It is compared to the NAME of the constant that must
    hold it, not to a value: `region=AZURE_LOCATION` and `region="eastus2"` produce the same
    endpoint and are not the same fact, and only the first one is checkable against check 1.
    """
    source = _contract()
    assert guard.declaration_failures("multi-provider-byok", None, DECLARED, source) == []

    for original, doctored, field in (
        (
            '    provider="openai",\n    region=OPENAI_DATA_RESIDENCY,',
            '    provider="openai",\n    region="us",',
            "region",
        ),
        (
            "    region_in_host=True,\n    addresses_a_deployment=False,",
            "    region_in_host=False,\n    addresses_a_deployment=False,",
            "region_in_host",
        ),
        (
            '    builder="openai_base_url",\n    builder_arity=0,',
            '    builder="openai_base_url",\n    builder_arity=1,',
            "builder_arity",
        ),
        (
            '    permitted_host="generativelanguage.googleapis.com",',
            '    permitted_host="gemini.googleapis.com",',
            "permitted_host",
        ),
    ):
        assert original in source, original
        failures = guard.declaration_failures(
            "multi-provider-byok", None, DECLARED, source.replace(original, doctored, 1)
        )
        assert any(f"declares {field}=" in failure for failure in failures), (field, failures)


def test_a_reordered_or_shortened_leg_tuple_is_caught() -> None:
    """`DECLARED_LEGS` is compared as an ORDERED SEQUENCE, not as a set.

    Order carries no dispatch, and that is exactly why comparing it as a set would be easy to
    justify and wrong: the guard's failure messages, the delegation notice and the green line
    all name the legs in declaration order, so the incumbent leg being listed first is a
    property a reader relies on. A dropped leg is the more serious half — it is a vendor the
    tree still builds endpoints for and the declaration no longer admits to.
    """
    source = _contract()
    original = "DECLARED_LEGS: Final = (AZURE_OPENAI_LEG, OPENAI_DIRECT_LEG, GOOGLE_DIRECT_LEG)"
    assert original in source

    for doctored in (
        "DECLARED_LEGS: Final = (OPENAI_DIRECT_LEG, AZURE_OPENAI_LEG, GOOGLE_DIRECT_LEG)",
        "DECLARED_LEGS: Final = (AZURE_OPENAI_LEG, OPENAI_DIRECT_LEG)",
    ):
        failures = guard.declaration_failures(
            "multi-provider-byok", None, DECLARED, source.replace(original, doctored, 1)
        )
        assert len(failures) == 1, failures
        assert guard.LEGS_CONSTANT in failures[0] and "in that order" in failures[0], failures

    gone = source.replace(original, "", 1)
    failures = guard.declaration_failures("multi-provider-byok", None, DECLARED, gone)
    assert len(failures) == 1 and "declares no" in failures[0], failures


def test_a_second_or_misplaced_declaration_is_caught() -> None:
    """One posture, one declaration. A second is a second answer to where this product's
    models run, and — like a second region constant — nothing downstream would notice the
    day they stopped agreeing."""
    one = guard.Reference(guard.CONTRACT, 1, "multi-provider-byok", frozen=True)
    assert guard.declared_posture_name([one]) == ("multi-provider-byok", [])

    elsewhere = guard.Reference("apps/api/core/config.py", 9, "openai-direct", frozen=True)
    name, failures = guard.declared_posture_name([elsewhere])
    assert name is None and "not in" in failures[0]

    name, failures = guard.declared_posture_name([one, elsewhere])
    assert name is None and "more than one place" in failures[0]

    name, failures = guard.declared_posture_name([])
    assert name is None and "no module declares" in failures[0]


def test_main_refuses_to_run_a_single_check_without_a_resolvable_posture(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every check below check 0 is stated RELATIVE to the declared posture, so a tree whose
    declaration cannot be resolved has no rules to be judged against.

    `main()` therefore returns before any of them, and `declared_spec()` raises rather than
    inventing a default — a guard that fell back to a posture nobody declared would enforce
    the wrong one silently.
    """
    monkeypatch.setattr(guard, "declared_posture_name", lambda *_: (None, ["synthetic"]))
    assert guard.main() == 1
    assert "synthetic" in capsys.readouterr().out
    with pytest.raises(RuntimeError, match="cannot be resolved"):
        guard.declared_spec()

    monkeypatch.setattr(guard, "declared_posture_name", lambda *_: ("cheap-us-region", []))
    assert guard.main() == 1
    assert "not one this check knows" in capsys.readouterr().out
    with pytest.raises(RuntimeError, match="cannot be resolved"):
        guard.declared_spec()


# --- CODE drifts from DECLARATION ---------------------------------------------


def test_a_tree_that_lost_a_builder_while_still_declaring_its_leg_is_caught() -> None:
    """The other direction — kept here so the pair is readable in one place rather than split
    across two files by accident of history. Stated on BOTH builder-bearing legs, because a
    check that looked at one of them would be exactly as green on a tree that had lost the
    other."""
    for leg, definition in (
        (DECLARED.leg("azure_openai"), "def azure_openai_base_url("),
        (DECLARED.leg("openai"), "def openai_base_url("),
    ):
        assert leg is not None
        renamed = _contract().replace(definition, "def build_url(", 1)
        failures = guard.leg_builder_failures(leg, renamed)
        assert failures, (leg.provider, failures)
        assert f"defines no `{leg.builder}()`" in failures[0], failures


def test_the_delegated_human_gate_is_per_leg_and_stands_down_loudly() -> None:
    """The gates a human owns (OPERATIONS §2 20/20c) exist because a leg whose region is NOT
    in its URL makes a claim this check cannot prove. A leg that carries its region in the
    authority, and a leg that makes no regional claim at all, delegate NOTHING — and that
    stand-down is a `delegated_gate=None` in the spec, a claim written out loud, rather than
    an absence somebody has to notice.

    THE NOTICE HAS TO SAY WHICH IS WHICH. A reader who meets a delegation notice listing
    every leg learns that this guard proves no region anywhere; one of the three now proves
    its own, and reporting that is the difference between an honest report and a
    pessimistic one.
    """
    azure = DECLARED.leg("azure_openai")
    direct = DECLARED.leg("openai")
    google = DECLARED.leg("google")
    assert azure is not None and direct is not None and google is not None

    assert azure.delegated_gate == ("AZURE_LOCATION", "portal")
    assert direct.delegated_gate is None and google.delegated_gate is None
    assert guard.delegation_failures(None, DECLARED) == []
    assert guard.delegation_failures("no gate here", DECLARED) != []
    assert guard.delegation_failures("no gate here", OPENAI_ONLY) == []
    assert guard.delegation_failures("no gate here", GOOGLE_ONLY) == []

    notice = guard.delegated_notice(DECLARED)
    assert "NOTHING IS DELEGATED" in notice
    assert "first label of the authority" in notice, (
        "the leg that proves its own region must SAY so — otherwise the notice reads as if "
        "every leg were an attestation, which is the pessimistic version of the same lie"
    )
    assert "WITHDRAWN" in notice and "not upgraded" in notice


# --- the catalogue: three legs, one key space ---------------------------------


def test_the_three_model_literals_do_not_intersect() -> None:
    """ONE IDENTIFIER, ONE PROVIDER, ONE PRICE — FOREVER.

    `LLM_MODELS` is keyed by the bare identifier because that is all a historical
    `usage_events` row carries (D-455 stamps `meta.llm_model`), so a re-rendered invoice
    years from now resolves a price by name alone. `gpt-4o-mini` is a real model on OpenAI
    direct at the same list price and is deliberately NOT offered there: two providers behind
    one string would make the ledger unable to say which leg a minute ran on.

    FAILS IF: a model is added to two Literals, which is the easy mistake — the vendors'
    catalogues genuinely overlap.
    """
    from typing import get_args

    azure = set(get_args(AzureOpenAIModel))
    direct = set(get_args(OpenAIDirectModel))
    google = set(get_args(GoogleDirectModel))
    assert azure and direct and google
    assert not (azure & direct) and not (azure & google) and not (direct & google)
    assert azure | direct | google == LLM_MODEL_NAMES
    assert set(LLM_MODELS) == LLM_MODEL_NAMES, (
        "the catalogue and the Literals have drifted: a model in a Literal with no spec is "
        "unpriced spend, and a spec for a model no Literal names is a number that rots"
    )
    for name, spec in LLM_MODELS.items():
        assert spec.model == name


def test_a_price_nobody_here_has_read_cannot_reach_a_bill() -> None:
    """**HARD RULE 7 HAS NO `REPORTED` TIER, AND THE ENFORCEMENT MOVED TO THE SEAM IT IS
    ABOUT.**

    It used to live at `LlmModelSpec.__post_init__`, which refused `selectable=True` on
    unverified price evidence. That was correct and coarse: it protected `unit_cost_paid` by
    DELETING the model, so an egress rule in this container blocked a whole multi-vendor
    offering that the founder holds the accounts for. The protection is now on the MONEY —
    `billing/rates.llm_inr_per_ktok` is the one door to a bill and it opens on exactly two
    keys, an operator attestation or a catalogue figure somebody read from the vendor — which
    is strictly stronger, because no edit to `LLM_MODELS` can open it.

    So what this asserts is the property, not the old mechanism: every REPORTED catalogue
    price is unbillable in a process where nothing is attested, whatever `selectable` says.
    """
    from apps.api.billing.rates import llm_price_is_billable

    for name, spec in LLM_MODELS.items():
        assert llm_price_is_billable(name) == spec.price.evidence.verified, name

    # The catalogue invariants that DID stay at construction: a price has to exist, be
    # positive and be attributed. A zero reads as a free model on every screen that shows the
    # reference figure, and a free leg is the one cost mistake nobody investigates.
    with pytest.raises(ValueError, match="non-positive catalogue price"):
        _spec(
            price=LlmPrice(
                input_usd_per_mtok=Decimal("0"),
                output_usd_per_mtok=Decimal("2"),
                evidence=TODAY_EVIDENCE,
            )
        )
    with pytest.raises(ValueError, match="price with no evidence source"):
        _spec(
            price=LlmPrice(
                input_usd_per_mtok=Decimal("1"),
                output_usd_per_mtok=Decimal("2"),
                evidence=Evidence(source="", read_on=TODAY_EVIDENCE.read_on, verified=True),
            )
        )


def test_a_withdrawn_model_must_say_why_and_an_offered_one_must_not() -> None:
    """ "Not offered" with no sentence beside it is a decision the next reader re-litigates
    from a pricing page; a reason under a model that IS offered is a stale sentence that
    reads as reassuring while being wrong. Both are refused at construction."""
    with pytest.raises(ValueError, match="gives no reason"):
        _spec(selectable=False, withdrawn_reason=None)
    with pytest.raises(ValueError, match="also carries a withdrawn_reason"):
        _spec(selectable=True, withdrawn_reason="stale")

    for name in LLM_MODEL_NAMES - SELECTABLE_LLM_MODELS:
        assert LLM_MODELS[name].withdrawn_reason, name
    for name in SELECTABLE_LLM_MODELS:
        assert LLM_MODELS[name].withdrawn_reason is None, name


def test_the_gemini_leg_splits_on_the_trap_and_only_on_the_trap() -> None:
    """**THE GOOGLE LEG IS OFFERED, AND EXACTLY THE MODELS THAT CAN RETURN SILENCE ARE NOT.**

    This test used to assert that every Gemini model was withheld, on two grounds: the
    thinking-token trap and a 16 Oct 2026 retirement. One of those was simply FALSE — the GA
    identifiers carry no announced shutdown and that date belonged to preview snapshots — and
    it is the worked example behind hard rule 11. The other is real, verified from four
    primary sources, and it splits the leg cleanly:

    * on 2.5 flash and flash-lite the engine sends `thinking_budget=0` and Google's own docs
      say 0 DISABLES thinking, so the trap is ELIMINATED and the models are offered;
    * on every 3.x the engine sends `thinking_level`, whose enum has no zero, and the vendor
      states in its own words that Gemini 3 Flash and Flash-Lite "do not support full
      thinking-off". Thinking can consume `max_output_tokens` and return a candidate with no
      content — dead air on a phone call, with the engine's own `"Dead turn detected"` branch
      yielding nothing.

    FAILS IF: a 3.x model becomes selectable, or a 2.5 GA model is withheld again, or the
    trap stops being recorded on the models it applies to.
    """
    for name in GOOGLE_DIRECT_MODELS:
        spec = LLM_MODELS[name]
        assert spec.provider == "google"
        assert spec.price.input_usd_per_mtok > 0 and spec.price.output_usd_per_mtok > 0
        # THE TRAP IS ON EVERY MODEL ON THE LEG, including the two it is eliminated on: the
        # elimination is a branch in somebody else's repository at a pinned commit, not a
        # term of any contract, and the adapter reads this tuple to know it must never send
        # a `thinking_budget` that would switch thinking back on.
        assert any(trap.name == "thinking-tokens-share-the-reply-budget" for trap in spec.traps), (
            name
        )
        mitigated = "2.5" in name and "pro" not in name
        assert spec.selectable is mitigated, name
        if not mitigated:
            assert spec.withdrawn_reason and "thinking" in spec.withdrawn_reason.lower(), name

    assert {
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    } == GOOGLE_DIRECT_MODELS & SELECTABLE_LLM_MODELS


def test_every_gpt5_model_carries_the_two_traps_that_break_a_publish() -> None:
    """The `temperature: 1` trap is not an OpenAI-direct trap — it is a GPT-5 trap, already
    armed on the Azure leg we ship, and today it is latent only because no shipped identifier
    starts with `gpt-5`. Carrying it on the MODEL is what stops it being latent-and-forgotten
    the moment one becomes selectable."""
    for name, spec in LLM_MODELS.items():
        traps = {trap.name for trap in spec.traps}
        if name.startswith("gpt-5"):
            assert "temperature-must-be-one" in traps, name
            assert "max-tokens-becomes-max-completion-tokens" in traps, name
        else:
            assert "temperature-must-be-one" not in traps, name


# --- check 7: no declared leg is inert ----------------------------------------


def test_every_declared_leg_is_named_by_a_model_and_has_its_builder_called() -> None:
    """CHECK 7 AGAINST THE REAL TREE, plus both negative controls.

    The defect it exists for has already happened twice one level down: D-453 found a posture
    whose `permitted_host` was absent from a hand-written watched-host tuple, so every clause
    stated over it ran on an empty set and printed OK. A declared leg has the same shape of
    hole — if no model names it, its endpoint rules are enforced against nothing; if nothing
    calls its builder, the ONE literal check 3 exempts is the suffix of a function that never
    runs.

    THE TWO ARMS FAIL APART AND HAVE DIFFERENT FIXES, which is why they are two findings: a
    leg with models and no caller is a half-wired feature, and a leg with a caller and no
    models is a permission granted to nobody.
    """
    assert guard.inert_leg_failures(spec=DECLARED) == []

    providers = guard.live_model_providers()
    assert set(providers) == {"azure_openai", "openai", "google"}
    calls = guard.builder_call_sites()
    assert calls["azure_openai_base_url"] and calls["openai_base_url"]

    no_models = guard.inert_leg_failures(
        providers={"azure_openai": ["gpt-4o-mini"], "openai": ["gpt-5.4-mini"]},
        calls=calls,
        spec=DECLARED,
    )
    assert len(no_models) == 1, no_models
    assert "'google' leg and NO model" in no_models[0], no_models
    assert "permission granted to nobody" in no_models[0], no_models

    no_caller = guard.inert_leg_failures(
        providers=providers,
        calls={"azure_openai_base_url": ["x.py:1"], "openai_base_url": []},
        spec=DECLARED,
    )
    assert len(no_caller) == 1, no_caller
    assert "ever CALLS openai_base_url()" in no_caller[0], no_caller
    assert "half-wired" in no_caller[0], no_caller


def test_a_withdrawn_model_still_counts_as_naming_its_leg() -> None:
    """The Google leg is named only by models nobody may select, and that is deliberate.

    Check 7 asks whether a leg can be REACHED at all, not whether anybody is on offer there.
    A leg with two withdrawn models is a leg whose rules have a subject — its host is watched,
    its zero-literal budget is enforced, its `withdrawn_reason` is where the refusal lives.
    Requiring a SELECTABLE model instead would delete the row that carries the refusal, which
    is the opposite of what the check is for.
    """
    assert GOOGLE_DIRECT_MODELS - SELECTABLE_LLM_MODELS, (
        "no model on the Google leg is withdrawn any more, so this test proves nothing about "
        "check 7's tolerance — do not delete it, find the leg that still has one"
    )
    assert guard.live_model_providers()["google"] == sorted(GOOGLE_DIRECT_MODELS)
    assert guard.inert_leg_failures(spec=DECLARED) == []
    # AND THE PROOF THAT WITHDRAWN ALONE IS ENOUGH: the OpenAI leg's `gpt-5.6-luna` is
    # withheld while `gpt-5.4-mini` is offered, so check 7 sees a leg named by both kinds.
    assert (
        guard.inert_leg_failures(
            providers={**guard.live_model_providers(), "google": ["gemini-3.5-flash"]},
            spec=DECLARED,
        )
        == []
    )


# --- the deployment-versus-model question, settled by the model's own leg -----


def test_the_deployment_question_follows_the_models_own_leg() -> None:
    """IS `azure_openai_deployment` GENUINELY DISTINCT FROM `azure_openai_model`? Yes — and
    the distinction is an artefact of Azure, which is why it is a LEG property rather than a
    hard-wired pair of settings.

    **BOTH ARMS ARE NOW REACHABLE FROM SHIPPED CONFIGURATION.** Under one leg the
    addresses-the-model-by-name arm could only be exercised by monkeypatching the declared
    posture, which is a test asserting about a fixture. The OpenAI and Google legs address
    the model by its own published name, so the same call site reads `.addressed` under both
    and gets the right string under both — which is what makes `ModelBinding` more than two
    attributes with a comment.
    """
    bound = bind_model(deployment="prod-gpt-4o-mini", model="gpt-4o-mini")
    assert (bound.addressed, bound.priced) == ("prod-gpt-4o-mini", "gpt-4o-mini")
    with pytest.raises(ValueError, match="deployment name is required"):
        bind_model(deployment=None, model="gpt-4o-mini")

    direct = bind_model(deployment=None, model="gpt-5.4-mini")
    assert (direct.addressed, direct.priced) == ("gpt-5.4-mini", "gpt-5.4-mini")
    with pytest.raises(ValueError, match="nowhere to go"):
        bind_model(deployment="prod-whatever", model="gpt-5.4-mini")


def test_a_model_the_catalogue_does_not_know_cannot_be_bound_or_placed() -> None:
    """It RAISES rather than guessing the incumbent leg. A model nobody priced, dated or
    assigned a provider has no business on a wire, and defaulting it to Azure is how a Gemini
    identifier ends up in an Azure deployment field as a 404 mid-call."""
    with pytest.raises(ValueError, match="not a model this repository knows"):
        leg_for_model("gpt-9-turbo")
    with pytest.raises(ValueError, match="not a model this repository knows"):
        bind_model(deployment=None, model="gpt-9-turbo")

    assert leg_for_model("gemini-2.5-flash").provider == "google"
    assert leg_for_model("gpt-4o-mini").provider == "azure_openai"


def test_a_provider_the_posture_does_not_declare_has_no_leg() -> None:
    """`ResidencyPosture.leg` raises rather than returning `None`, and the message names what
    IS declared: a provider the posture does not contain has no endpoint, no credential and
    no residency story, so a caller that got `None` would have to invent all three."""
    single = ResidencyPosture(name="fixture", legs=(DECLARED_LEGS[0],))
    assert single.leg("azure_openai").provider == "azure_openai"
    with pytest.raises(ValueError, match="declares no 'openai' leg"):
        single.leg("openai")


# --- the runtime half of the endpoint rule ------------------------------------


def test_the_endpoint_validator_is_stated_per_leg() -> None:
    """The static check covers the LITERAL and this covers the VALUE, and between them there
    is no path by which an engine is handed a hand-typed model endpoint.

    THE THREE LEGS ANSWER DIFFERENTLY AND THAT IS THE POINT. Azure: an endpoint its own
    builder could have emitted, on a resource that is one DNS label — but nothing about the
    region, which the hostname does not carry. OpenAI: the whole claim, because an endpoint
    that is not `openai_base_url()`'s output is not in `OPENAI_DATA_RESIDENCY`. Google: the
    ABSENCE of an endpoint, because the engine builds its own client from an API key and
    never reads one.
    """
    ok_azure = ModelConfig(
        llm_provider="azure_openai",
        llm_model="prod-deployment",
        llm_base_url=azure_openai_base_url("calevate-prod"),
    )
    assert ok_azure.llm_base_url == "https://calevate-prod.openai.azure.com/openai/v1"
    with pytest.raises(ValueError, match="requires llm_base_url"):
        ModelConfig(llm_provider="azure_openai", llm_model="prod-deployment")
    with pytest.raises(ValueError, match="Azure OpenAI v1 endpoint"):
        ModelConfig(
            llm_provider="azure_openai",
            llm_model="prod-deployment",
            llm_base_url="https://evil.example/x.openai.azure.com/openai/v1",
        )

    assert (
        ModelConfig(
            llm_provider="openai", llm_model="gpt-5.4-mini", llm_base_url=openai_base_url()
        ).llm_base_url
        == "https://us.api.openai.com/v1"
    )
    with pytest.raises(ValueError, match=re.escape("must be 'https://us.api.openai.com/v1'")):
        ModelConfig(
            llm_provider="openai",
            llm_model="gpt-5.4-mini",
            llm_base_url="https://api.openai.com/v1",
        )
    with pytest.raises(ValueError, match="requires llm_base_url"):
        ModelConfig(llm_provider="openai", llm_model="gpt-5.4-mini")

    assert ModelConfig(llm_provider="google", llm_model="gemini-2.5-flash").llm_base_url is None
    with pytest.raises(ValueError, match="takes no base URL"):
        ModelConfig(
            llm_provider="google",
            llm_model="gemini-2.5-flash",
            llm_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        )

    # And the shape a caller reaches for when it wants "just point the LLM somewhere": it
    # would route to the engine's default client against our endpoint, which fails as a
    # confusing 4xx from a vendor rather than as a sentence about what is wrong.
    with pytest.raises(ValueError, match="only meaningful with an llm_provider"):
        ModelConfig(llm_base_url="https://calevate.openai.azure.com/openai/v1")
    assert ModelConfig().llm_base_url is None


def test_the_builder_refuses_a_resource_that_is_not_one_dns_label() -> None:
    """The EFFECT of check 4's shape check, proved by calling the builder — the split that
    file's docstring insists on. A guard rewritten to `if False and not _RE.fullmatch(...)`
    keeps the raise and the pattern call and refuses nothing."""
    for hostile in ("evil.example/x", "", "a", "x" * 65, "calevate.prod", "-lead"):
        with pytest.raises(ValueError, match="not a valid Azure OpenAI resource name"):
            azure_openai_base_url(hostile)


def test_the_openai_builder_takes_nothing_and_can_only_emit_one_url() -> None:
    """No argument, and that is the design rather than an omission: there is exactly one
    OpenAI-direct endpoint this product may address, and a parameter would be a caller's
    opportunity to vary the one thing the leg was adopted for."""
    assert openai_base_url() == "https://us.api.openai.com/v1"
    with pytest.raises(TypeError):
        openai_base_url("us")  # type: ignore[call-arg]


def test_a_posture_leg_is_frozen() -> None:
    """A leg that can be mutated at runtime is a leg two callers can disagree about — the
    same argument `EngineCapabilities` makes about a capability."""
    with pytest.raises(AttributeError):
        DECLARED_LEGS[0].region = "swedencentral"  # type: ignore[misc]
    assert isinstance(DECLARED_LEGS[0], PostureLeg)


def test_a_declaration_with_no_record_or_no_leg_record_is_caught() -> None:
    """The NAME alone is not the posture, and a leg NAMED in the tuple is not a leg.

    Three shapes of half-declaration, each of which reads as a smaller edit than it is. A
    name with no `ResidencyPosture(...)` beside it is a declaration nothing obeys — the
    record is what `bind_model` and `in_call_llm` read. A `DECLARED_LEGS` entry with no
    `PostureLeg(...)` behind it is a leg the guard cannot compare a single scalar of, which
    is precisely the state an inline record would put EVERY leg in permanently.
    """
    source = _contract()

    no_record = source.replace(
        "DECLARED_POSTURE: Final = ResidencyPosture(", "OTHER_POSTURE: Final = ResidencyPosture(", 1
    )
    failures = guard.declaration_failures("multi-provider-byok", None, DECLARED, no_record)
    assert len(failures) == 1 and "declares no" in failures[0], failures
    assert guard.POSTURE_RECORD_CONSTANT in failures[0], failures

    orphan = source.replace(
        "OPENAI_DIRECT_LEG: Final = PostureLeg(", "UNUSED_LEG: Final = PostureLeg(", 1
    )
    failures = guard.declaration_failures("multi-provider-byok", None, DECLARED, orphan)
    assert failures, failures
    assert any("OPENAI_DIRECT_LEG" in failure and "declares no" in failure for failure in failures)
    assert any("SCALARS" in failure for failure in failures), failures
