"""No shipped code sends Sarvam a model identifier Sarvam has retired (D-105).

THE DEFECT. Two call sites carried `"sarvam-m"` as a literal default:
`apps/workers/extraction.py::SarvamExtractor.__init__` and
`scripts/pilot/gates_api.py`'s pilot `ModelConfig`. Sarvam has since retired that
identifier — their changelog reports that a Chat Completions request naming it FAILS. So
post-call extraction was aimed at a model that no longer answers, and pilot gate 1 would
have configured a live agent, on a real telephone number, with a dead LLM.

Neither literal was wrong when it was written. What was wrong is that there was nowhere
for the correction to land ONCE — the same shape as D-103's engine set and D-104's
credential names, and the third time this repo has paid for a constant it did not have.

WHY THE COST MODEL MAKES THIS WORSE THAN A 400. TRD §10 prices the LLM leg at ₹0.00 on
"Sarvam 105B — free per token", and has since D-36. The code was sending the 24B. The
margin was therefore computed for a model the pipeline was not running, on the one leg
whose whole contribution to the unit economics is that it costs nothing.

WHAT THIS FILE CAN AND CANNOT PROVE. It cannot ask Sarvam anything: `docs.sarvam.ai` and
`api.sarvam.ai` are both refused by this environment's egress proxy, and no request has
ever been made from this repository. So `SARVAM_RETIRED_LLMS` is REPORTED, NOT READ — two
independent search summaries of the vendor changelog agreeing. What this file proves is
narrower and still worth having: that the tree names the identifier in ONE place, and that
no retired name has crept back into a shipped path.

WHY A SCAN AND NOT A PIN ON THE TWO SITES WE FIXED. Pinning them would be satisfied by
this commit and silent on the next one, and the site that hurt most — the pilot gate — is
precisely the one nobody thought to grep, because it is under `scripts/` and reads like a
fixture rather than like production. The same argument `engine_name_drift_test` makes.

IT COVERS EVERY VENDOR THIS PRODUCT NAMES A MODEL TO, and the file keeps its name on
purpose: `calevate_shared/engine.py`, `scripts/check_model_residency.py` (three times) and
`tests/money_rounding_mode_test.py` all cite `sarvam_model_identifier_test` by name, and
renaming a file to widen a docstring would break four citations to fix a label. The
question is the same question — does shipped code name a model identifier the vendor will
refuse, and does it name it twice — and one home for it beats three files that drift.

**WHAT D-410 REMOVED FROM THIS FILE, AND WHY THAT IS A BENEFIT RATHER THAN A GAP.** Under
D-127 the shipped dashboard model was `gemini-2.5-flash`, which the vendor had already
DATED: it retired 16 Oct 2026 (BRD R-04). That deadline was a real, stated cost of taking
the only model the only permitted region served, so this file carried the only mechanism in
the repository that would raise it on a day nobody was thinking about Gemini —
`GEMINI_DEFAULT_LLM_RETIRES`, a `RETIREMENT_RUNWAY_DAYS` window, and a test that turned CI
RED on 16 Sep 2026 whatever the diff under test was about.

D-410 moved both LLM surfaces to Azure OpenAI and **no vendor deadline currently runs
against this product**, so the constant, the window and the calendar test are all deleted
rather than re-aimed at a date nobody has. There is deliberately no dated constant
replacing them: a countdown to a day that has not been announced is a red build waiting for
a reason. If Microsoft dates `gpt-4o-mini`, the mechanism comes back with the date, in this
file, and the decision-log entry says which announcement it came from.

WHAT DID NOT GO, AND WHAT HAS SINCE BEEN GIVEN BACK. `GEMINI_RETIRED_LLMS` grew rather than
shrank at D-410 — with no shipped Gemini identifier left, the set became the WHOLE family
and every name in it was one a module could only be spelling by mistake.

⚠ **IT HAS NOW SHRUNK BY EXACTLY TWO, AND THAT IS A HOLE RE-OPENED ON PURPOSE.** The
provider choice put `gemini-2.5-flash` and `gemini-2.5-flash-lite` back in the tree as
catalogue entries — priced, dated, and `selectable=False` with the reason recorded — so a
set that both banned them and shipped them would be incoherent, which is the identical
argument that kept `gemini-2.5-flash` out of the set under D-127. The two names came OUT of
the ban and `test_the_gemini_ban_is_re_opened_by_exactly_the_two_adopted_names` is what
keeps that bounded. What replaces the ban for those two is NARROWER and stated below: the
only files that may spell them are the two registries, and
`test_no_shipped_module_names_an_adopted_google_model` is the scan that says so.

AND THE D-105 DISCIPLINE FOLLOWED THE DEFAULT RATHER THAN DYING WITH IT.
`test_no_shipped_module_spells_the_gemini_default` existed because a shipped model
identifier written at a call site is correct on the day it is typed and unfixable in one
place afterwards. That is as true of `gpt-4o-mini` as it was of `gemini-2.5-flash`, so the
rule is restated as `test_no_shipped_module_spells_the_azure_default_model` — a rule about
whatever the DEFAULT is, which keeps working the next time it moves.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

from calevate_shared.engine import (
    AZURE_OPENAI_DEFAULT_MODEL,
    GEMINI_RETIRED_LLMS,
    GOOGLE_DIRECT_MODELS,
    LLM_MODEL_NAMES,
    SARVAM_DEFAULT_LLM,
    SARVAM_DEFAULT_STT,
    SARVAM_RETIRED_LLMS,
    SARVAM_TRANSLATING_STT,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Where a model identifier can reach the vendor. `scripts/` is IN, and it is the reason
#: this test exists in this shape: `scripts/pilot/gates_api.py` places real calls against
#: a real Bolna account, so a dead model there burns a pilot gate and a telephone minute.
#: `tests/` is out — a test naming a retired identifier is usually asserting about it.
SCANNED_TREES: tuple[str, ...] = ("apps", "packages/shared/src", "scripts")

#: The module that owns the answer, and the only file allowed to spell these names.
CANONICAL_HOME = "packages/shared/src/calevate_shared/engine.py"


def _string_literals(path: Path) -> set[str]:
    """Every string CONSTANT in the file, from the AST rather than a regex.

    Parsing matters here: a regex over source would also match the identifier inside a
    docstring or a comment explaining the retirement, and this file's whole subject is a
    correction that has to be EXPLAINED somewhere. An `ast.Constant` is a value the code
    can actually send.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _shipped_python() -> list[Path]:
    return [
        path
        for tree in SCANNED_TREES
        for path in sorted((REPO_ROOT / tree).rglob("*.py"))
        if "__pycache__" not in path.parts and ".venv" not in path.parts
    ]


def test_no_shipped_module_sends_a_retired_sarvam_model() -> None:
    """The scan. A retired identifier reaching the vendor is a 400 at post-call time —
    the point in the pipeline furthest from anyone watching — and the symptom an operator
    meets is "extraction is empty", which points at the schema, the prompt and the
    transcript before it points at the model name."""
    offenders: dict[str, set[str]] = {}
    for path in _shipped_python():
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative == CANONICAL_HOME:
            continue
        retired = _string_literals(path) & SARVAM_RETIRED_LLMS
        if retired:
            offenders[relative] = retired

    assert not offenders, (
        "these modules name a Sarvam model identifier the vendor has retired; a request "
        f"carrying one fails at the vendor: {ChainMapLike(offenders)}. Import "
        "`calevate_shared.engine.SARVAM_DEFAULT_LLM` instead."
    )


def test_no_shipped_module_configures_a_translating_sarvam_transcriber() -> None:
    """THE SAME SCAN, FOR A FAILURE WITH NO VENDOR-SIDE SYMPTOM AT ALL.

    Every other name this file bans produces a 4xx from somebody. `saaras:v2.5` does
    not: the engine supports it, the request succeeds, and a well-formed transcript comes
    back — in ENGLISH, because that model translates rather than transcribes
    (`SARVAM_TRANSLATING_STT` carries the vendor's own sentence). So the agent works, the
    pilot gate goes green, and the Telugu-shaped machinery downstream matches nothing:
    `workers/redaction.py` hunts transliterated Telugu digit words and
    `compliance/optout.py` hunts romanised Telugu opt-out phrases, and neither survives a
    translation. An unrecognised opt-out is a compliance failure rather than a quality
    one, which is why this is a scan and not a preference.

    THE DEFECT THAT PROMPTED IT WAS REAL AND HAD SURVIVED REVIEW: `scripts/pilot/
    gates_api.py` configured `saaras:v2.5` while `scripts/pilot/scorecard.py` priced
    "Sarvam Saaras V3 STT" and the conformance suite configured `saaras:v3` — three
    spellings of one leg, of which the one that dialled a real Indian telephone was the
    one that would have returned English.
    """
    offenders: dict[str, set[str]] = {}
    for path in _shipped_python():
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative == CANONICAL_HOME:
            continue
        translating = _string_literals(path) & SARVAM_TRANSLATING_STT
        if translating:
            offenders[relative] = translating

    assert not offenders, (
        "these modules configure a Sarvam transcriber that returns an ENGLISH "
        "TRANSLATION rather than the caller's own words, on a Telugu-first product: "
        f"{ChainMapLike(offenders)}. Nothing will fail loudly — the transcript arrives "
        "well-formed and the Telugu opt-out and redaction matchers silently match "
        "nothing. Use an original-language model (`saaras:v3`)."
    )


def test_the_default_is_not_itself_retired() -> None:
    """The blind spot that would make the scan above pointless. `SARVAM_DEFAULT_LLM` lives
    in the one file the scan skips, so nothing else would notice if the next retirement
    caught up with it — which is exactly what happened to `sarvam-30b`, the migration
    target `sarvam-m` was pointed at before it was retired in turn."""
    assert SARVAM_DEFAULT_LLM not in SARVAM_RETIRED_LLMS, (
        f"{SARVAM_DEFAULT_LLM} is in the retired set and is also the default this repo "
        "sends on every extraction"
    )


def test_the_platform_default_transcriber_does_not_translate() -> None:
    """THE BLIND SPOT THE SCAN ABOVE CANNOT SEE, and it opened the moment the STT leg got a
    default.

    `test_no_shipped_module_configures_a_translating_sarvam_transcriber` skips
    `CANONICAL_HOME` — it has to, because that file is where the banned names are DEFINED.
    `SARVAM_DEFAULT_STT` now lives in that same file and is what every published agent
    sends, so a future edit swapping it to a translating identifier would be invisible to
    every other check in this repository: nothing 400s, the pilot goes green, and the
    symptom is a Telugu caller's opt-out that our matchers never see.

    The whole point of the ban is that this failure has no vendor-side signal. A default
    that carries it fails HERE, in CI, rather than on a phone call.
    """
    assert SARVAM_DEFAULT_STT not in SARVAM_TRANSLATING_STT, (
        f"{SARVAM_DEFAULT_STT} is the transcriber every agent now publishes with AND is in "
        "the translating set — it returns an English translation rather than the caller's "
        "own words, on a Telugu-first product. Pick an original-language model."
    )


def test_the_platform_default_transcriber_is_a_model_the_engine_lists() -> None:
    """The second half of "the default is real": the engine has to accept it.

    VERIFIED-VENDOR-DOCS, `bolna-findings/mirror/pages/providers/transcriber/sarvam.md`
    (fetched 20 Aug 2026) — the four Sarvam STT models Bolna's own page lists. That page is
    read here rather than restated, so a default that drifts to an identifier their engine
    does not list (`saaras:v3-realtime`, say, which is Sarvam-direct and beta) fails in CI
    instead of arriving as a vendor rejection at agent-create time on a live account.

    NOT an assertion that the SDK enum and this list agree — they do not, and neither is
    wrong. See `SARVAM_DEFAULT_STT`'s own comment: Bolna's page says what their engine
    ACCEPTS, the SDK says what Sarvam currently SHIPS, and `saaras:v3` is in both.
    """
    page = (REPO_ROOT / "bolna-findings/mirror/pages/providers/transcriber/sarvam.md").read_text(
        encoding="utf-8"
    )
    listed = set(re.findall(r"\b(?:saaras|saarika):v[0-9.]+", page))
    assert listed, "the vendor page named no Sarvam STT model — has the mirror moved?"
    assert SARVAM_DEFAULT_STT in listed, (
        f"{SARVAM_DEFAULT_STT} is what every agent publishes and the engine's own "
        f"transcriber page does not list it. It lists: {sorted(listed)}."
    )


# THERE IS NO AZURE EQUIVALENT OF THE TEST ABOVE, AND THE ABSENCE IS DELIBERATE.
# "the default is one this platform ships" is `AZURE_OPENAI_DEFAULT_MODEL in
# AZURE_OPENAI_MODELS`, and mypy strict already proves it: the constant infers a `Literal`,
# `Settings.azure_openai_model` is annotated `AzureOpenAIModel`, and the assignment of one
# to the other is checked at every CI run. A test restating it would be a second place the
# rule lives (D-103/D-105) buying nothing — the same argument `apps/workers/extraction.py`
# makes for having no `model_not_allowed` refusal reason. Sarvam has no such Literal,
# because the retired set is a vendor CHANGELOG fact rather than a type, which is why that
# half needs the assertion and this half does not.


def test_the_extractor_and_the_pilot_gate_agree_with_the_constant() -> None:
    """Both sites resolve to the shared answer at RUNTIME, not merely by looking similar.

    The scan proves no retired literal is present; it cannot prove a site was rewired
    rather than just edited. A file that swapped `"sarvam-m"` for `"sarvam-105b"` in place
    passes the scan and reintroduces the defect the moment the vendor moves again.
    """
    from apps.workers.extraction import SarvamExtractor

    assert SarvamExtractor(api_key="k").model_name == SARVAM_DEFAULT_LLM

    # Imported here rather than at module scope: `scripts.pilot` pulls in the pilot
    # harness, which is heavier than this file needs for its other three cases.
    from scripts.pilot.gates_api import __file__ as gates_source

    gates_literals = _string_literals(Path(gates_source))
    assert SARVAM_DEFAULT_LLM not in gates_literals, (
        "scripts/pilot/gates_api.py spells the model identifier instead of importing it — "
        "which passes the retired-name scan and breaks on the next retirement"
    )


def test_no_shipped_module_names_a_gemini_model_at_all() -> None:
    """The scan for the vendor this product no longer uses, and the set is now the whole
    family.

    `apps/workers/extraction.py` carried `model: str = "gemini-2.5-flash-lite"` as a
    default argument, and later `gemini-2.5-flash` as the shipped dashboard model — a
    literal in exactly the shape D-105 was written about, on a path where the symptom is
    "extraction is empty" and the first three places anyone looks are the schema, the
    prompt and the transcript.

    D-410 took Gemini out of the product entirely, which CLOSED the one hole this set
    carried: `gemini-2.5-flash` used to be excluded because banning the name we shipped
    would have been incoherent.

    ⚠ **THAT HOLE IS OPEN AGAIN AND THE SET IS THE FAMILY MINUS `GOOGLE_DIRECT_MODELS`.**
    The two adopted identifiers are catalogue entries now, so the same incoherence argument
    applies to them and they are out of this ban. Everything else in the family stays — most
    of it dated or dead at the vendor — and the failure is the same either way: a 404 from a
    third party at the moment furthest from anyone watching.

    A TRIPWIRE WITH NO SUBJECT IN THE TREE, which is the state it should be in. What it
    catches is a Gemini identifier coming BACK — from a search result, an old branch, a doc
    written before 19 Aug 2026 — onto a leg where nothing here can price it, date it or say
    which of the three legs it belongs to.
    """
    offenders: dict[str, set[str]] = {}
    for path in _shipped_python():
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative == CANONICAL_HOME:
            continue
        retired = _string_literals(path) & GEMINI_RETIRED_LLMS
        if retired:
            offenders[relative] = retired

    assert not offenders, (
        "these modules name a Gemini model identifier this product has no entry for: "
        f"{ChainMapLike(offenders)}. The catalogue is `LLM_MODEL_NAMES` and it carries two "
        "Google identifiers, both withdrawn; every other name in the family is priced by "
        "nothing, dated by nothing and assigned to no leg. The first post-call extraction "
        "pass reads the RAW transcript and stays on Sarvam permanently "
        "(`SARVAM_DEFAULT_LLM`, `GEMINI_EXTRACTION_DEFAULT is False`)."
    )


#: The lifecycle registry: a table keyed by the allow-list, not a call site. Its
#: exemption is earned by the test below, never by this line.
LIFECYCLE_REGISTRY: Final = "packages/shared/src/calevate_shared/model_lifecycle.py"


def test_no_shipped_module_spells_the_azure_default_model() -> None:
    """D-105's rule, following the default rather than dying with the last one.

    `test_no_shipped_module_spells_the_gemini_default` existed because a shipped model
    identifier written at a call site is correct on the day it is typed and unfixable in
    one place afterwards — which is precisely how `"sarvam-m"` ended up in two modules and
    survived the vendor retiring it. That is as true of `gpt-4o-mini` as it was of
    `gemini-2.5-flash`, and MORE true in one respect: `gpt-4.1-mini` is a LIVE console
    switch (`Settings.azure_openai_model`), so a module that spelled the default would keep
    sending the default after an operator moved off it, and the cost model — which reads
    the setting — would price the other one. Two answers to "which model is running", one
    of them a rupee figure.

    A RULE ABOUT THE DEFAULT RATHER THAN ABOUT ONE STRING, so it keeps working the next
    time the default moves. Exact-match on the identifier, not containment: a sentence in
    an operator-facing error that MENTIONS the model ("confirm the deployment's model is
    gpt-4o-mini or later") is prose a person reads, not a value the code sends.
    """
    offenders = {
        path.relative_to(REPO_ROOT).as_posix(): {AZURE_OPENAI_DEFAULT_MODEL}
        for path in _shipped_python()
        if path.relative_to(REPO_ROOT).as_posix() not in (CANONICAL_HOME, LIFECYCLE_REGISTRY)
        and AZURE_OPENAI_DEFAULT_MODEL in _string_literals(path)
    }
    assert not offenders, (
        "these modules spell the Azure model identifier instead of reading "
        "`Settings.azure_openai_model` (or, where no deployment config is in scope, "
        f"importing `calevate_shared.engine.AZURE_OPENAI_DEFAULT_MODEL`): "
        f"{ChainMapLike(offenders)}. A second spelling is a site the live `gpt-4.1-mini` "
        "switch will not reach."
    )


def test_no_shipped_module_names_an_adopted_google_model() -> None:
    """What replaces the ban for the two identifiers that came OUT of it.

    `GEMINI_RETIRED_LLMS` cannot carry `gemini-2.5-flash` and `gemini-2.5-flash-lite` any
    more — they are catalogue entries, and a set that both banned them and shipped them
    would be the incoherence D-127 avoided by leaving a hole. So the rule they get instead
    is narrower and stated over the two files that legitimately hold every model identifier:
    the contract, which declares the `Literal` and prices it, and the lifecycle registry,
    which dates it.

    WHY THAT IS ENOUGH RATHER THAN A CONSOLATION. What the ban prevented was an identifier
    reaching a vendor from a call site nobody re-reads. Nothing in this product can reach a
    vendor with a model it did not resolve through `SELECTABLE_LLM_MODELS`, and both of
    these are `selectable=False` with a `withdrawn_reason` — so a call site that spelled one
    would be refused before the wire, by the picker, by the two column CHECK constraints and
    by the publish path. What this scan still adds is the thing those cannot: it catches the
    name arriving from a doc or an old branch and being written down as though it were a
    choice, on a leg whose only safe model retires in eight weeks.

    FAILS IF: a worker, an adapter or a pilot script spells one of these — including in an
    f-string default or a fixture that ships.
    """
    allowed = {CANONICAL_HOME, LIFECYCLE_REGISTRY}
    offenders: dict[str, set[str]] = {}
    for path in _shipped_python():
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative in allowed:
            continue
        named = _string_literals(path) & GOOGLE_DIRECT_MODELS
        if named:
            offenders[relative] = named

    assert not offenders, (
        "these modules spell a Google model identifier: "
        f"{ChainMapLike(offenders)}. Both are in the catalogue and both are "
        "`selectable=False` — Google retires them on 16 Oct 2026 and the engine's thinking "
        "budget can be zeroed on no successor — so a call site naming one is either dead "
        "configuration or a choice nobody made. The only files that may spell them are "
        f"{sorted(allowed)}."
    )


def test_the_gemini_ban_is_re_opened_by_exactly_the_two_adopted_names() -> None:
    """The bound on the hole, so it cannot widen by an edit to one set.

    `GEMINI_RETIRED_LLMS` is the family MINUS the adopted identifiers, and that subtraction
    is the only reason any Gemini name is allowed in this tree. Stated as an equality in
    both directions: nothing adopted may still be banned (incoherent), and nothing banned
    may quietly become adopted without appearing in the catalogue — which is where the
    price, the date and the `withdrawn_reason` live.

    FAILS IF: a third Gemini identifier leaves the ban without gaining a catalogue entry, or
    an adopted one is put back into the ban while it is still in `LLM_MODEL_NAMES`.
    """
    assert GOOGLE_DIRECT_MODELS
    assert not (GEMINI_RETIRED_LLMS & GOOGLE_DIRECT_MODELS), (
        "a model this product carries in its catalogue is also on the ban list — the two "
        "statements cannot both be acted on, and the ban is the one that would be believed"
    )
    assert GOOGLE_DIRECT_MODELS <= LLM_MODEL_NAMES
    assert not (GEMINI_RETIRED_LLMS & LLM_MODEL_NAMES), (
        "a banned identifier is in the catalogue: every name in LLM_MODEL_NAMES is one the "
        "product can price, date and assign to a leg, and a banned one is by definition none "
        "of those"
    )


def test_the_lifecycle_registrys_exemption_is_earned_not_asserted() -> None:
    """`model_lifecycle.py` spells every allow-listed model, and that is not the defect
    the test above is about.

    THE RULE IS ABOUT A SECOND ANSWER TO "WHICH MODEL IS RUNNING". A call site that
    spells the default gives one, and it goes stale the moment an operator moves the live
    switch. A table KEYED BY every member of the allow-list gives none: it says something
    about all of them, and it stays correct under any value of the switch — which is the
    opposite property.

    So the exemption is conditioned on exactly that, rather than on the filename. If the
    registry ever spells an identifier that is not an allow-listed model — a call site
    smuggled into a table — it is no longer a statement about all of them and this fails.
    THE TWO DIRECTIONS HAVE TWO OWNERS, deliberately. This test owns "every allow-listed
    model is named", which is what makes the file a statement about all of them. The
    other direction — "and nothing else is" — belongs to
    `scripts/check_model_lifecycle.py`, which REFUSES (exit 2) when the table does not
    exactly cover the allow-list. It cannot live here: any string could be a model name,
    so a test in this file could only guess, while the guard compares the table against
    the allow-list itself and knows. An earlier draft of this assertion tried to own both
    and silently owned neither — it filtered the spelled names down to the allow-list
    first, so a smuggled non-allow-listed identifier could never appear in the result.
    """
    spelled = _string_literals(REPO_ROOT / LIFECYCLE_REGISTRY)
    missing = LLM_MODEL_NAMES - spelled
    assert not missing, (
        f"{LIFECYCLE_REGISTRY} is exempt from the rules above only while it names EVERY "
        f"model in the catalogue, and it does not name {sorted(missing)}. A registry "
        "covering the whole catalogue is a statement about all of them and survives the "
        "live switch moving; one covering part of it is exactly the stale second answer "
        "those rules exist to forbid. IT IS STATED OVER `LLM_MODEL_NAMES` AND NOT OVER THE "
        "AZURE LITERAL since the catalogue gained three legs — the exemption now covers two "
        "Google identifiers this file otherwise bans everywhere, so the earning has to be "
        "over the whole set or it is an exemption for the half nobody checked."
    )


class ChainMapLike:
    """Readable failure text for `{file: {names}}` without a dict repr full of `set()`."""

    def __init__(self, offenders: dict[str, set[str]]) -> None:
        self._offenders = offenders

    def __str__(self) -> str:
        return "; ".join(
            f"{path} → {sorted(names)}" for path, names in sorted(self._offenders.items())
        )

    __repr__ = __str__
