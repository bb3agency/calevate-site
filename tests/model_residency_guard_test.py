"""The residency guard, proved against the states it exists to catch (D-127, PLAN Part 12).

`scripts/check_model_residency.py` is the gate; this file is the evidence that the gate
can go red. A check nobody has watched fail is a check nobody knows is connected — the
same argument `check_redaction_exposure.check_allowlist` makes when it refuses to pass on
a route table with no permissions in it at all, and the same shape as
`tests/wiring_guard_test.py`.

The guard lands BEFORE the Vertex client (Part 13), so every violation below is
constructed rather than remembered. That is the point: the thing being defended against
is nine characters in a URL that nobody has written yet, and the only honest way to know
the defence works is to write those characters here and watch them be refused.

Six shapes, and the middle two are the ones a reviewer would miss:

* the AI Studio host — the endpoint this tree reaches TODAY, and the one D-127 disqualifies;
* the bare Vertex host — the global endpoint, on which the caller cannot choose a region;
* `us-central1` — a real regional endpoint, correctly formed, in the wrong country;
* a regional host with **`locations/global`** in the path — the two halves of the URL
  disagreeing, which is why the host check and the path check are separate checks;
* a region read from an instance attribute instead of the frozen constant — the shape
  that turns into a config knob three commits later;
* a `Settings` field that could hold the region at all, which is the failure that never
  appears in a URL literal because the value arrives from a database row.

Plus the two anti-rubber-stamp cases: prose naming a banned host must NOT fail (this is an
AST walk, not a grep), and the Sheets/OAuth hosts in `workers/google_sheets.py` must not
be judged at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts import check_model_residency as guard

# One correctly pinned Vertex call, written the way Part 13 should write it: the region
# in a `Final` constant, interpolated into BOTH the host and the `locations/` segment.
COMPLIANT = (
    "from typing import Final\n"
    'VERTEX_LOCATION: Final = "asia-south1"\n'
    'PROJECT = "calevate-prod"\n'
    "URL = (\n"
    '    f"https://{VERTEX_LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT}"\n'
    '    f"/locations/{VERTEX_LOCATION}/publishers/google/models/gemini:generateContent"\n'
    ")\n"
)


def _tree(tmp_path: Path, body: str, name: str = "client.py") -> Path:
    (tmp_path / name).write_text(body, encoding="utf-8")
    return tmp_path


def _failures(root: Path) -> list[str]:
    """Every endpoint failure a doctored tree produces, judged against ITS OWN constants
    and with no allowance — the real registry names a real file and would not apply."""
    references = guard.url_references(roots=(root,))
    return guard.endpoint_failures(
        references, frozen=guard.frozen_region_constants(roots=(root,)), allowances={}
    )


# --- the standing assertion ---------------------------------------------------


def test_the_real_tree_is_clean() -> None:
    """The same five checks `make guardrails` runs, over the real repository."""
    references = guard.url_references()
    constants = guard.frozen_region_constants()
    assert guard.blindness_failures(guard.template_count(), constants, references) == []
    assert guard.endpoint_failures(references, constants) == []
    assert guard.stale_allowances(references) == []
    assert guard.loose_region_literals() == []
    assert guard.console_config_failures() == []


def test_a_compliant_tree_passes() -> None:
    """Half of the pair the brief calls decorative without: a check that only ever fails
    is as useless as one that only ever passes, and this is the shape Part 13 must be able
    to write without arguing with the guard."""
    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        root = _tree(Path(scratch), COMPLIANT)
        assert _failures(root) == []
        assert guard.loose_region_literals(roots=(root,)) == []
        assert set(guard.frozen_region_constants(roots=(root,))) == {"VERTEX_LOCATION"}


# --- 1: no global Google model host -------------------------------------------


def test_the_ai_studio_host_is_caught(tmp_path: Path) -> None:
    """`apps/workers/extraction.py:55` as it stands today, minus its dated allowance."""
    root = _tree(
        tmp_path,
        'CHAT = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"\n',
    )
    offenders = _failures(root)
    assert any("AI Studio Developer API" in offender for offender in offenders), offenders
    assert any("human reviewers" in offender for offender in offenders), offenders


def test_the_bare_vertex_host_is_the_global_endpoint_and_is_caught(tmp_path: Path) -> None:
    """No region in the host and `locations/global` in the path — Google's own escape
    hatch from data residency, and the one that looks most like a Vertex URL."""
    root = _tree(
        tmp_path,
        'URL = "https://aiplatform.googleapis.com/v1/projects/p/locations/global"\n',
    )
    offenders = _failures(root)
    assert any("no region prefix" in offender for offender in offenders), offenders
    assert any("'global'" in offender for offender in offenders), offenders


# --- 2: the region in the host ------------------------------------------------


def test_a_us_central1_host_fails(tmp_path: Path) -> None:
    """THE negative control. A perfectly well-formed Vertex regional endpoint, in Iowa.

    Nothing about this line is malformed, nothing raises, and every test in the repository
    stays green while a client's callers' words leave the country — which is the entire
    reason this check is syntactic and mandatory rather than a review convention.
    """
    root = _tree(
        tmp_path,
        'URL = "https://us-central1-aiplatform.googleapis.com/v1/projects/p'
        '/locations/us-central1/publishers/google/models/gemini:generateContent"\n',
    )
    offenders = _failures(root)
    assert any(
        "'us-central1'" in offender and "residency change" in offender for offender in offenders
    ), offenders
    # And separately on the path segment, because the two can disagree.
    assert any("locations/" in offender for offender in offenders), offenders


def test_a_region_that_is_not_the_frozen_constant_is_refused(tmp_path: Path) -> None:
    """The shape that becomes a config knob three commits later: the host is right today
    because `self._location` happens to hold the right string today."""
    root = _tree(
        tmp_path,
        "class Vertex:\n"
        "    def __init__(self, location: str) -> None:\n"
        "        self._location = location\n"
        "    def url(self) -> str:\n"
        '        return f"https://{self._location}-aiplatform.googleapis.com/v1"\n',
    )
    offenders = _failures(root)
    assert any("{self._location}" in offender for offender in offenders), offenders
    assert any("Final" in offender for offender in offenders), offenders


# --- 4: the region in the path ------------------------------------------------


def test_a_correct_host_with_the_wrong_location_is_caught(tmp_path: Path) -> None:
    """The subtler half, and the reason checks 2 and 4 are not one check. The host says
    Mumbai; the path says global. Vertex honours the path."""
    root = _tree(
        tmp_path,
        'URL = "https://asia-south1-aiplatform.googleapis.com/v1/projects/p'
        '/locations/global/publishers/google/models/gemini:generateContent"\n',
    )
    offenders = _failures(root)
    assert offenders, "a host pinned to Mumbai with locations/global was accepted"
    assert all("locations/" in offender for offender in offenders), offenders
    assert any("not pinned at all" in offender for offender in offenders), offenders


# --- 3: the region's provenance -----------------------------------------------


def test_a_region_literal_outside_a_final_constant_is_caught(tmp_path: Path) -> None:
    """A default argument that READS like a pin and is one keyword away from not being
    one. Nothing here is a URL, so checks 1, 2 and 4 see nothing at all."""
    root = _tree(
        tmp_path,
        "class Vertex:\n"
        '    def __init__(self, location: str = "asia-south1") -> None:\n'
        "        self._location = location\n",
    )
    offenders = guard.loose_region_literals(roots=(root,))
    assert len(offenders) == 1, offenders
    assert "Final" in offenders[0] and "asia-south1" in offenders[0]
    assert _failures(root) == [], "no URL literal here — the endpoint checks must be quiet"


def test_a_settings_field_named_for_a_region_is_caught() -> None:
    """The failure that never appears in a URL literal. `managed_fields()` derives the
    console's editable set from `Settings.model_fields`, so `vertex_location` is editable
    from a web form the day it is declared and the guard has to see the DECLARATION."""
    offenders = guard.console_config_failures(
        fields={"vertex_location": "asia-south1", "sarvam_api_key": None},
        managed=["vertex_location"],
    )
    assert len(offenders) == 1, offenders
    assert "console-editable" in offenders[0] and "3am" in offenders[0]

    # Declared but not yet managed is still a failure: `managed_fields()` is derived, so
    # a field one rename away from being offered is a field that will be offered.
    hidden = guard.console_config_failures(fields={"gemini_region": "asia-south1"}, managed=[])
    assert len(hidden) == 1 and "declared" in hidden[0], hidden


def test_a_settings_field_holding_a_google_host_is_caught_whatever_it_is_called() -> None:
    """Names are a heuristic; the default value is evidence. `llm_base` says nothing and
    holds the whole residency decision."""
    offenders = guard.console_config_failures(
        fields={"llm_base": "https://aiplatform.googleapis.com/v1"}, managed=["llm_base"]
    )
    assert len(offenders) == 1, offenders
    assert "it is the residency knob" in offenders[0]


def test_the_live_settings_model_has_nowhere_to_put_a_region() -> None:
    """The claim above, asserted against the real model rather than a fixture — otherwise
    the two tests together prove only that the fixture is well written."""
    fields, managed = guard.live_settings()
    assert len(fields) > 40, "the Settings model came back nearly empty — this is blind"
    assert "app_env" not in managed, "managed_fields() no longer excludes the bootstrap set"
    assert guard.console_config_failures(fields, managed) == []


# --- the dated allowance ------------------------------------------------------


def test_the_registry_is_empty_and_the_tree_needs_no_exception() -> None:
    """The state the registry is supposed to REACH, asserted rather than assumed.

    It held one entry — `apps/workers/extraction.py`, whose `GEMINI_CHAT_URL` named the
    AI Studio Developer API — recorded with a date and a closer (PLAN Part 13). Part 13
    landed: `vertex_generate_url()` builds an `asia-south1` URL from the frozen constant,
    the AI Studio literal is gone from the tree, and `stale_allowances()` then REQUIRED
    the entry to be deleted, which is precisely the contract it was written under.

    So this asserts the two halves separately, because they can fail apart: the real tree
    needs no exception at all, and no exception is granted. A registry that quietly
    regrew an entry for a file that no longer offends would be the permanent skip the
    dated-allowance design exists to make impossible.
    """
    references = guard.url_references()
    assert guard.endpoint_failures(references, guard.frozen_region_constants(), allowances={}) == []
    assert guard.ALLOWANCES == {}, (
        "an allowance is granted again — read its `removed_by` and confirm it names the "
        "work that closes it, because the registry can only ever shrink"
    )


def test_an_allowance_whose_defect_has_gone_is_caught() -> None:
    """The freshness half, which is what makes the registry shrink-only.

    Driven through a SYNTHETIC allowance now that the real one is gone. That is the
    stronger version of this test, not a weaker one: it no longer depends on a defect
    happening to still be in the tree, so it keeps proving the mechanism after every
    future entry is closed too — the `allowances=` seam exists for exactly this.
    """
    allowance = guard.DatedAllowance(
        host=guard.AI_STUDIO_HOST,
        recorded="2026-08-15",
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
    # nothing is reported. Without this the test above passes on a `stale_allowances` that
    # simply returns one failure for every entry it is given.
    still_current = guard.stale_allowances(
        references=[
            guard.Reference(
                "apps/workers/extraction.py",
                55,
                f"https://{guard.AI_STUDIO_HOST}/v1beta/models/x:generateContent",
            )
        ],
        allowances={"apps/workers/extraction.py": allowance},
    )
    assert still_current == []


def test_the_real_vertex_client_is_what_the_guard_judges() -> None:
    """The tripwire has a subject again, and it is the shipped client.

    `blindness_failures` refuses to pass a tree in which NOTHING names a Google model
    host, because that reads identically to a scan that stopped reading files. Before
    Part 13 the subject was the offending AI Studio literal; now it is
    `workers/extraction.vertex_generate_url`, and this asserts the guard is reading THAT
    — host and `locations/` segment both resolved from the frozen constant, in the real
    file, not in a fixture.
    """
    references = [
        reference
        for reference in guard.url_references()
        if reference.path == "apps/workers/extraction.py"
    ]
    assert len(references) == 1, references
    template = references[0].template
    assert f"{{{'VERTEX_LOCATION'}}}-{guard.VERTEX_HOST}" in template, template
    assert "locations/{VERTEX_LOCATION}" in template, template
    assert guard.AI_STUDIO_HOST not in template


# --- anti-rubber-stamp --------------------------------------------------------


def test_a_banned_host_in_prose_is_not_a_violation(tmp_path: Path) -> None:
    """This is an AST walk, not a grep, and the difference is load-bearing HERE more than
    anywhere: the guard's own docstring, the D-127 row and SECURITY-COMPLIANCE §4 all name
    the disqualified host in order to disqualify it. A source-text scan would report the
    explanation as the offence and teach the next reader to delete the explanation."""
    root = _tree(
        tmp_path,
        '"""We do NOT use generativelanguage.googleapis.com — see D-127."""\n'
        "# nor bare aiplatform.googleapis.com, which is the global endpoint\n"
        "SAFE = 1\n",
    )
    assert _failures(root) == []


def test_a_banned_host_in_a_non_python_file_is_caught(tmp_path: Path) -> None:
    """The text half, which has no subject in this repo today and therefore no evidence
    that it works — a tripwire nobody has stepped on is a tripwire nobody has connected.

    The frontend must never call a model provider (CLAUDE.md forbids it and there is no
    ad-hoc fetch), so this is a guard against the day somebody does it in a deploy script
    or a route handler rather than a check with daily work to do. A line naming either
    host becomes a reference and is judged by the same host and `locations/` rules — the
    second half of this test is what proves that, and it is the assertion that corrected
    the guard's own docstring, which had claimed the text half could only ban by name.
    """
    (tmp_path / "assist.ts").write_text(
        'const ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models";\n',
        encoding="utf-8",
    )
    offenders = _failures(tmp_path)
    assert len(offenders) == 1, offenders
    assert offenders[0].endswith("asia-south1-aiplatform.googleapis.com.")
    assert "assist.ts:1" in offenders[0]

    # The region rules reach it too — the text half is line-level, not name-level.
    (tmp_path / "assist.ts").write_text(
        'const ENDPOINT = "https://us-central1-aiplatform.googleapis.com/v1";\n',
        encoding="utf-8",
    )
    wrong_region = _failures(tmp_path)
    assert len(wrong_region) == 1 and "region 'us-central1'" in wrong_region[0], wrong_region


def test_the_other_google_apis_are_not_judged() -> None:
    """`workers/google_sheets.py` reaches `oauth2.` and `sheets.googleapis.com` on every
    CRM export. Those are the tenant's own destination and carry no inference; a guard
    that fired on them would be turned off within a week."""
    hosts = [reference.template for reference in guard.url_references()]
    assert not any("sheets.googleapis.com" in template for template in hosts), hosts
    assert not any("oauth2.googleapis.com" in template for template in hosts), hosts


def test_the_blindness_guard_fires_when_the_scan_finds_nothing() -> None:
    """Check 5. Every failure mode of this file — a parse error swallowed, a root renamed,
    `Final` detection broken — presents as a clean tree, so the run refuses to call a scan
    that found nothing a pass."""
    blind = guard.blindness_failures(0, {}, [])
    assert len(blind) == 3, blind
    assert any("it is blind" in failure for failure in blind)
    assert any("VERTEX_REGION" in failure for failure in blind)

    seeing = guard.blindness_failures(
        guard.MINIMUM_TEMPLATES,
        {"VERTEX_REGION": guard.SELF},
        [guard.Reference("apps/workers/extraction.py", 55, guard.AI_STUDIO_HOST)],
    )
    assert seeing == []


def test_the_guards_own_region_constant_is_the_one_the_decision_row_pins() -> None:
    """The canary's own premise, and the one thing no other check can cover.

    `VERTEX_REGION` is spelled in the guard rather than imported (the
    `check_bootstrap_keys.BOOTSTRAP_KEYS` argument: a guardrail that imported the value it
    checks would be asking the code whether it agrees with itself). The cost of that is
    that editing it would break nothing — every other test in this file would keep
    passing against the new region. The decision log is the only outside authority on
    which region is permitted, so this is where the two are tied together.
    """
    assert guard.VERTEX_REGION == "asia-south1"
    roadmap = (Path(__file__).resolve().parents[1] / "docs" / "ROADMAP.md").read_text(
        encoding="utf-8"
    )
    row = next(line for line in roadmap.splitlines() if line.startswith("| D-127 "))
    assert f"`{guard.VERTEX_REGION}` and NOWHERE ELSE" in row, (
        "D-127 no longer pins the region this guard enforces — one of the two moved"
    )
    assert guard.SELF in row, "D-127 no longer names the guardrail that enforces it"


# --- the two exemptions, and whether either is still doing work -------------------


def test_the_docstring_exemption_is_load_bearing_on_the_real_tree() -> None:
    """It was not when it shipped, and it is now — which is a fact worth pinning rather
    than a note worth leaving stale.

    `_templates` skips docstrings because the guard's whole subject is a host that has to
    be NAMED in order to be banned. When Part 12 landed, the only file naming one in a
    docstring was the guard itself, which was skipped for the endpoint checks anyway — so
    the exemption could have been deleted and the CLI would have stayed green, and an
    exemption nobody can watch fail is one nobody has evidence is connected.

    Part 13 changed that: `VertexGeminiExtractor`'s docstring explains why the AI Studio
    host is disqualified, by name, in a file this guard scans. So turning the exemption
    off now REPORTS THAT EXPLANATION AS THE OFFENCE — which is exactly the failure mode
    the exemption exists to prevent, and this test is the evidence.

    If this test ever fails, the honest fix is to say so here rather than to delete the
    exemption: the subject may have moved, and the machinery is still right.
    """
    subjects = [
        reference.path for reference in guard.url_references() if reference.path != guard.SELF
    ]
    assert subjects == ["apps/workers/extraction.py"], subjects

    original = guard._docstrings
    try:
        guard._docstrings = lambda tree: set()  # type: ignore[assignment]
        references = guard.url_references()
        failures = guard.endpoint_failures(references, guard.frozen_region_constants())
    finally:
        guard._docstrings = original  # type: ignore[assignment]

    # Two subjects now, and the SHIPPED one is the point. The guard's own prose is the
    # second — it explains both bans at length — and it only shows up here because the
    # self-exemption stopped being a whole-file skip; before that narrowing this list
    # would have held the client alone.
    offenders = {failure.split(":", 1)[0] for failure in failures}
    assert "apps/workers/extraction.py" in offenders, failures
    assert offenders == {"apps/workers/extraction.py", guard.SELF}, offenders
    assert any(guard.AI_STUDIO_HOST in failure for failure in failures)

    # And with the exemption restored, the same tree is clean — otherwise the assertion
    # above would be evidence of a broken tree rather than of a working exemption.
    assert guard.endpoint_failures(guard.url_references(), guard.frozen_region_constants()) == []


def test_the_guard_judges_its_own_file_apart_from_the_two_host_declarations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The single-file hole, narrowed from a whole file to two literals.

    The guard has to name both hosts to ban them, so SOMETHING here must be exempt. It
    used to be the entire module, which made the one place in `apps/`, `packages/` and
    `scripts/` where a `us-central1` URL passed the check the very file a person edits
    when they are relaxing the check. Now the exemption is `_host_definition`: a template
    that IS one of the two host strings and nothing else.

    Driven through a DOCTORED file standing in for `SELF`, because the real one cannot be
    made to offend without editing the guard — and a test that could not watch the
    exemption fail would be asserting about a `continue`.
    """
    stand_in = tmp_path / "check_model_residency.py"
    stand_in.write_text(
        "from typing import Final\n"
        # The two declarations, exactly as the real file writes them.
        f'AI_STUDIO_HOST: Final = "{guard.AI_STUDIO_HOST}"\n'
        f'VERTEX_HOST: Final = "{guard.VERTEX_HOST}"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(guard, "SELF", guard._rel(stand_in))
    assert _failures(tmp_path) == [], "the guard cannot declare the hosts it bans"

    stand_in.write_text(
        "from typing import Final\n"
        f'AI_STUDIO_HOST: Final = "{guard.AI_STUDIO_HOST}"\n'
        f'VERTEX_HOST: Final = "{guard.VERTEX_HOST}"\n'
        # A URL, in the guard's own file. Under the old whole-file skip this passed.
        'FALLBACK = "https://us-central1-aiplatform.googleapis.com/v1/projects/p"\n',
        encoding="utf-8",
    )
    failures = _failures(tmp_path)
    assert len(failures) == 1, failures
    assert "us-central1" in failures[0]


def test_the_real_guard_names_the_hosts_only_as_declarations() -> None:
    """The other side of the same rule, against the real file rather than a stand-in: no
    reference the scan produces comes from `SELF`, because the only two literals there
    that could produce one are the declarations. A URL added to this file would appear
    here AND fail `test_the_real_tree_is_clean`."""
    assert [r for r in guard.url_references() if r.path == guard.SELF] == []
    assert guard.AI_STUDIO_HOST in (guard.REPO_ROOT / guard.SELF).read_text(encoding="utf-8")
