"""The DECLARED residency posture, proved in both directions of drift (D-432).

`tests/model_residency_guard_test.py` proves the guard's four checks can go red. This file
proves the thing D-432 added underneath them: that the posture is a DECLARATION, that the
declaration and the tree are compared, and that the comparison fails BOTH WAYS.

**WHY BOTH WAYS IS THE WHOLE POINT.** Making a hard-wired posture declared is a weakening
unless the declaration is checked, because the obvious way to build it — read a flag, run
the matching checks — lets one edited word move the product's residency posture past a
green build. So:

* **CODE DRIFTS FROM DECLARATION** (`test_a_tree_that_moved_off_azure_...`): the tree grows
  an `api.openai.com` endpoint or loses its builder while still declaring India. Checks 1-4
  catch it, exactly as they did before D-432.
* **DECLARATION DRIFTS FROM CODE** (`test_declaring_a_posture_the_tree_is_not_in_...`): the
  declaration is edited to `openai-direct` while the tree is unchanged and still Azure. This
  is the cheap direction — one line — and it is the one a flag-reading guard would wave
  through. Here it fails four ways at once, against the REAL repository.

**AND THE POSTURE IN FORCE IS `us-azure-openai` (D-449).** D-432 built the mechanism; D-449
threw the switch, moving the declaration to `eastus2` and WITHDRAWING the India residency
claim rather than upgrading anything. `test_the_us_posture_is_the_one_in_force` is the
standing assertion that replaced the India tripwire, and it is deliberately stronger than
the one it replaces: it pins the declared name AND the region AND requires that the
withdrawn posture is still KNOWN to the guard while not being the declared one. Nothing
below declares a different posture anywhere but in a fixture argument.

**AND ONE TEST PROVES THE GENERALIZATION IS LOAD-BEARING.**
`test_the_guard_tells_two_pinned_regions_apart_on_the_real_tree` states the SHIPPED tree
against both pinning specs, undoctored: it passes as `us-azure-openai` and is refused as
`india-azure-openai`, with both regions named in the refusal. Before D-449 the guard
compared everything against one module constant, so it could express "pins southindia" and
"pins nothing" and had no way to check a posture pinning some OTHER region — which is
precisely the check a posture move needs.

**AND THE CONTROL IS NOW STATED OVER THE TABLE RATHER THAN OVER ONE FIXTURE POSTURE.**
`test_every_posture_in_the_table_is_stated_against_the_real_tree` requires that exactly one
row passes the shipped tree and that every other row is refused by something. It exists
because the row-at-a-time habit is how a table acquires a spec nobody has ever watched
refuse anything, and a spec like that may not describe a posture this guard can check at
all. `google-direct` is the third vendor and the reason it matters: a table that could
express only "Azure or not Azure" made every check LOOK vendor-independent, and stating a
third vendor is what showed two of them were not — the `Settings`-endpoint check knew only
Azure's name, and the watched-host set was hand-written beside the table instead of derived
from it.
"""

from __future__ import annotations

import pytest
from calevate_shared import engine
from calevate_shared.engine import DECLARED_POSTURE, ResidencyPosture, bind_model
from scripts import check_model_residency as guard

#: The disqualified posture, used ONLY as a fixture. Reaching for it here is what makes the
#: guard's refusal of the real tree observable; `POSTURES` says at length why it has a row.
FOREIGN = guard.POSTURES["openai-direct"]
#: The WITHDRAWN posture (D-449). Same fixture role as `FOREIGN` and a second job the
#: non-pinning spec cannot do: it pins a region, and a DIFFERENT one, which is the only way
#: to state that this guard tells two pinned regions apart rather than merely telling a pin
#: from an absence.
INDIA = guard.POSTURES["india-azure-openai"]
US = guard.POSTURES["us-azure-openai"]
#: The THIRD vendor, and the row that made the table's vendor-independence observable.
#: Same fixture role again: never declared here, only stated over the real tree.
GOOGLE = guard.POSTURES["google-direct"]


# --- the standing assertion ---------------------------------------------------


def test_the_us_posture_is_the_one_in_force() -> None:
    """THE TRIPWIRE, RE-AIMED BY D-449 RATHER THAN DELETED.

    It used to assert `india-azure-openai`, and its whole job was that the posture could
    not move as a side effect of somebody touching this file. D-449 moved it deliberately —
    a decision-log entry, a client-facing warranty withdrawal, and the documents that state
    it — so the tripwire is re-aimed at the new declaration and is STRICTER than before: it
    pins the name, the region VALUE and the provider, and it additionally requires that the
    withdrawn posture is still a posture this guard KNOWS while not being the one declared.

    Both halves matter. If the name check alone survived, a tree could declare
    `us-azure-openai` while `AZURE_LOCATION` still held `southindia` and this test would
    pass. If the withdrawn spec were dropped from `POSTURES`, nothing could state the
    shipped tree against it and the refusal below would become unobservable.

    If this fails, somebody changed where this product's language models run. That is a
    DPA change (`apps/web/src/lib/legal/dpa.ts` states the posture to clients in an
    executed agreement), not a code change.
    """
    name, failures = guard.declared_posture_name()
    assert failures == []
    assert name == "us-azure-openai"
    assert guard.declaration_failures(name) == []
    assert DECLARED_POSTURE.name == name
    assert DECLARED_POSTURE.region == "eastus2"
    assert DECLARED_POSTURE.llm_provider == "azure_openai"

    assert "india-azure-openai" in guard.POSTURES, (
        "the WITHDRAWN posture must stay checkable: a mechanism that can only express the "
        "posture in force proves nothing about the posture in force, and dropping this row "
        "deletes the only way to ask whether the tree would still pass as an Indian one"
    )
    assert INDIA.region == "southindia" and INDIA.name != name


def test_the_guard_tells_two_pinned_regions_apart_on_the_real_tree() -> None:
    """THE PROOF THAT D-449's GENERALIZATION IS LOAD-BEARING RATHER THAN DECORATIVE.

    Nothing here is doctored: this is the repository exactly as it ships, stated against
    two specs that differ ONLY in the region they pin. Before D-449 this test could not have
    been written — `frozen_region_constants` matched one module constant, so the guard could
    express "pins southindia" and "pins nothing" and had no third shape at all. A posture
    move under that design left `AZURE_LOCATION` unchecked by VALUE, which is exactly the
    half a hurried move forgets.

    THE FAILURE MUST NAME BOTH REGIONS, and that is asserted rather than assumed: a message
    saying only that something is wrong sends the reader to the declaration, which is the
    half that is usually right. Naming the pinned region and the frozen one says which of
    the two moved.
    """
    constants = guard.frozen_region_constants()

    assert guard.single_spelling_failures(constants, US) == []

    refused = guard.single_spelling_failures(constants, INDIA)
    assert len(refused) == 1, refused
    assert INDIA.region in refused[0] and US.region in refused[0], refused
    assert guard.REGION_CONSTANT in refused[0], refused

    # THE CANARY, so the two results above cannot both be produced by a scan that has
    # silently stopped seeing anything. A `frozen_region_constants` returning `{}` would
    # make the US call pass for the wrong reason (nothing found is nothing wrong) — it
    # would not, because the empty case is its own message, but proving the subject exists
    # is cheaper than reasoning about which branch an empty scan lands in.
    assert (
        guard.blindness_failures(guard.template_count(), constants, guard.endpoint_references(), US)
        == []
    )
    assert constants[guard.REGION_CONSTANT] == (guard.BUILDER_HOME, US.region)


def test_the_declaration_is_source_and_nothing_else() -> None:
    """It is a `Final` literal in the portability contract: not a setting, not an
    environment variable, not a `platform_config` row.

    The three refusals are asserted rather than assumed because each is a different way the
    mechanism would stop being a posture. A settings field is the D-95 §4 failure — a
    residency decision invertible from a web form at 3am. The other two are the same failure
    wearing different clothes.
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


def test_declaring_a_posture_the_tree_is_not_in_is_caught_against_the_real_tree() -> None:
    """THE CENTRAL NEGATIVE CONTROL OF D-432, and the one a flag-reading guard would miss.

    Nothing here is doctored: the repository is exactly as it ships, and only the posture
    handed to the checks changes. Every one of the four fails, and each names a different
    thing that would have to be true before this tree could honestly claim to be running
    anywhere but on our own Azure resource.
    """
    references = guard.endpoint_references()
    constants = guard.frozen_region_constants()

    region = guard.single_spelling_failures(constants, FOREIGN)
    assert len(region) == 1 and "pins no region" in region[0], region

    endpoints = guard.endpoint_failures(references, constants, {}, FOREIGN)
    assert endpoints and all(guard.AZURE_HOST_SUFFIX in failure for failure in endpoints)
    assert any("declaration was edited without the tree" in failure for failure in endpoints)

    builder = guard.builder_failures(None, FOREIGN)
    assert len(builder) == 1 and "openai_base_url" in builder[0], builder

    record = guard.declaration_failures("openai-direct")
    assert len(record) == 3, record
    for field in ("addresses_a_deployment", "llm_provider", "region"):
        assert any(f"declares {field}=" in failure for failure in record), (field, record)


def test_every_posture_in_the_table_is_stated_against_the_real_tree() -> None:
    """THE NEGATIVE CONTROL, WIDENED FROM ONE FIXTURE POSTURE TO THE WHOLE TABLE.

    The two tests above state the shipped tree against `openai-direct` and against
    `india-azure-openai` and watch it be refused. Both were written one posture at a time,
    which is how a table ends up with a row nothing has ever been stated against — and a
    spec nobody has watched refuse anything is a spec that could be describing a posture
    this guard has no way to check. `google-direct` arrived to make the vendor-independence
    of checks 2 and 3 observable, so the control is now stated over `POSTURES` itself:
    exactly one posture passes the real tree, and every other one is refused by something.

    WHY "REFUSED BY SOMETHING" AND NOT A FIXED COUNT PER POSTURE. The postures fail
    DIFFERENTLY and that is correct: `india-azure-openai` differs from the declaration only
    in the region, so check 1 alone catches it; `openai-direct` and `google-direct` differ
    in the region, the provider, the deployment question, the builder and the host, so four
    checks catch them. A test demanding the same count from each would be asserting that
    the postures are the same posture. The per-posture detail is pinned in the two tests
    around this one, and in the Google case below.

    FAILS IF: a `PostureSpec` is added that the shipped tree would ALSO satisfy — which is
    the one thing a second declarable posture must never be, because two postures the same
    tree passes are not two postures.
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
        )
        if name == declared:
            assert refusals == [], (name, refusals)
        else:
            assert refusals, (
                f"posture {name!r} is a row nothing can distinguish from the declared one "
                "over the real tree — either it is not a different posture, or this guard "
                "cannot tell that it is"
            )


def test_declaring_google_direct_over_the_real_tree_is_refused_by_every_check() -> None:
    """The third vendor, stated over the shipped tree exactly as `openai-direct` is.

    It earns its own test rather than only a row in the loop above because the two things
    it was added to prove are both invisible from a count. Check 3 refuses the Azure
    literal by naming Gemini's host as the one this declaration permits — which is only
    possible because `permitted_host` is read from the spec and the watched-host set is
    derived from the table. And check 4 refuses because the builder this posture names does
    not exist, which is what a declaration arriving ahead of its code looks like.

    FAILS IF: `google-direct` is deleted, or its `permitted_host` / `builder` stop being
    read from the spec.
    """
    references = guard.endpoint_references()
    constants = guard.frozen_region_constants()

    region = guard.single_spelling_failures(constants, GOOGLE)
    assert len(region) == 1 and "pins no region" in region[0], region

    endpoints = guard.endpoint_failures(references, constants, {}, GOOGLE)
    assert endpoints and all(guard.AZURE_HOST_SUFFIX in failure for failure in endpoints)
    assert all(GOOGLE.permitted_host in failure for failure in endpoints), endpoints

    builder = guard.builder_failures(None, GOOGLE)
    assert len(builder) == 1 and "gemini_base_url" in builder[0], builder

    record = guard.declaration_failures("google-direct")
    assert len(record) == 3, record
    for field in ("addresses_a_deployment", "llm_provider", "region"):
        assert any(f"declares {field}=" in failure for failure in record), (field, record)

    # The posture makes NO regional claim, so it delegates nothing — and says so out loud
    # rather than by omission, per `test_the_delegated_human_gate_...` below.
    assert GOOGLE.delegated_gate is None
    assert guard.delegation_failures("no gate here", GOOGLE) == []
    assert "NO REGIONAL CLAIM" in GOOGLE.warrant


def test_a_posture_name_the_guard_does_not_know_is_a_hard_failure() -> None:
    """The single word that would otherwise bypass the whole mechanism.

    A guard that accepted an unrecognised name would enforce nothing while printing the same
    `OK` — which is a worse outcome than the hard-wiring D-432 replaced, because the green
    line now carries a posture's name and a reader would believe it.
    """
    failures = guard.declaration_failures("cheap-us-region")
    assert len(failures) == 1
    assert "not one this check knows" in failures[0]
    assert "decision-log entry" in failures[0]


def test_a_record_that_contradicts_its_own_declared_name_is_caught() -> None:
    """The declaration is a NAME and a RECORD, and the record is what the runtime obeys.

    A name that said India beside a record that pinned no region would leave
    `engine.bind_model` and `agents.service.in_call_llm` acting on one posture while every
    static check enforced another — the two-states-at-once failure, which is invisible from
    either half alone.
    """
    coherent = {
        "name": guard.DECLARATION_CONSTANT,
        "llm_provider": "azure_openai",
        "region": "AZURE_LOCATION",
        "addresses_a_deployment": True,
    }
    assert guard.declaration_failures("us-azure-openai", coherent) == []

    for field, wrong in (
        ("region", None),
        ("llm_provider", "openai"),
        ("addresses_a_deployment", False),
        ("name", '"us-azure-openai"'),
    ):
        failures = guard.declaration_failures("us-azure-openai", {**coherent, field: wrong})
        assert len(failures) == 1 and f"declares {field}=" in failures[0], (field, failures)


def test_a_second_or_misplaced_declaration_is_caught() -> None:
    """One posture, one declaration. A second is a second answer to where this product's
    models run, and — like a second region constant — nothing downstream would notice the
    day they stopped agreeing."""
    one = guard.Reference(guard.CONTRACT, 1, "us-azure-openai", frozen=True)
    assert guard.declared_posture_name([one]) == ("us-azure-openai", [])

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
    the wrong one silently, which is the exact failure this mechanism exists to prevent.
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


def test_a_tree_that_moved_off_azure_while_still_declaring_india_is_caught() -> None:
    """The other direction, and the one D-410 already covered — kept here so the pair is
    readable in one place rather than split across two files by accident of history."""
    renamed = (
        (guard.REPO_ROOT / guard.CONTRACT)
        .read_text(encoding="utf-8")
        .replace("def azure_openai_base_url(", "def openai_base_url(")
    )
    failures = guard.builder_failures(renamed, US)
    assert len(failures) == 1 and "defines no `azure_openai_base_url()`" in failures[0]

    record = guard.declaration_failures(
        "us-azure-openai",
        {
            "name": guard.DECLARATION_CONSTANT,
            "llm_provider": "openai",
            "region": None,
            "addresses_a_deployment": False,
        },
    )
    assert len(record) == 3, record


def test_the_delegated_human_gate_is_posture_conditional_and_stands_down_loudly() -> None:
    """The gates a human owns (OPERATIONS §2 20/20c) exist because a REGION-PINNING posture
    makes a claim this check cannot prove — which is as true of `us-azure-openai` as it was
    of the India posture it replaced: D-449 changed which region a human confirms, not
    whether one has to. A posture that makes NO regional claim delegates nothing,
    so requiring the gate there would demand a human confirm a fact nobody is asserting.

    That stand-down is a `delegated_gate=None` in the spec — a claim written out loud — and
    not an absence somebody has to notice.
    """
    assert US.delegated_gate == ("AZURE_LOCATION", "portal")
    assert FOREIGN.delegated_gate is None
    assert guard.delegation_failures(None, US) == []
    assert guard.delegation_failures("no gate here", US) != []
    assert guard.delegation_failures("no gate here", FOREIGN) == []
    assert "NO REGIONAL CLAIM" in FOREIGN.warrant, (
        "a posture that proves less must SAY it proves less on every green run — a green "
        "line that reads the same under both postures is the defect D-410 recorded"
    )


# --- the deployment-versus-model question, settled by type --------------------


def test_the_deployment_is_a_separate_thing_only_because_the_posture_says_so() -> None:
    """IS `azure_openai_deployment` GENUINELY DISTINCT FROM `azure_openai_model`? Yes — and
    the distinction is an artefact of Azure, which is why it is a POSTURE property rather
    than a hard-wired pair of settings.

    Under a posture that addresses a deployment the two strings differ and both are carried,
    one for the wire and one for the price list. Under a posture that addresses the model by
    its own name they collapse to one string, and a leftover deployment id is REFUSED rather
    than ignored: silently dropping it is how an operator ends up believing a field they
    filled in is doing something.
    """
    assert DECLARED_POSTURE.addresses_a_deployment is True
    bound = bind_model(deployment="prod-gpt-4o-mini", model="gpt-4o-mini")
    assert (bound.addressed, bound.priced) == ("prod-gpt-4o-mini", "gpt-4o-mini")
    with pytest.raises(ValueError, match="deployment name is required"):
        bind_model(deployment=None, model="gpt-4o-mini")


def test_a_posture_that_addresses_the_model_by_name_collapses_the_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other arm, exercised through a posture declared in a FIXTURE — never in source.

    This is what makes `ModelBinding` more than two attributes with a comment: the same call
    site reads `.addressed` under both postures and gets the right string under both, so the
    wire/price distinction cannot be got wrong by a caller that does not know which posture
    it is in.
    """
    monkeypatch.setattr(
        engine,
        "DECLARED_POSTURE",
        ResidencyPosture(
            name="openai-direct",
            # Our vocabulary (`LlmProvider`) is closed to one member and this fixture is
            # only exercising `addresses_a_deployment`; inventing a member here would be a
            # second, untyped spelling of the leg.
            llm_provider="azure_openai",
            region=None,
            addresses_a_deployment=False,
        ),
    )
    bound = engine.bind_model(deployment=None, model="gpt-4o-mini")
    assert (bound.addressed, bound.priced) == ("gpt-4o-mini", "gpt-4o-mini")
    with pytest.raises(ValueError, match="nowhere to go"):
        engine.bind_model(deployment="prod-gpt-4o-mini", model="gpt-4o-mini")
