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

IT NOW COVERS GEMINI TOO (D-127, PLAN Part 13), and the file keeps its name on purpose:
`calevate_shared/engine.py`, `scripts/check_model_residency.py` (three times) and
`tests/money_rounding_mode_test.py` all cite `sarvam_model_identifier_test` by name, and
renaming a file to widen a docstring would break four citations to fix a label. The
question is the same question — does shipped code name a model identifier the vendor will
refuse — and one home for it beats two files that drift.

THE GEMINI HALF DIFFERS IN ONE WAY WORTH STATING: those identifiers are not dead yet.
`gemini-2.5-flash-lite` — which `workers/extraction.py` defaulted to before Part 13 —
RETIRES 16 Oct 2026 (BRD R-04), and Google names `gemini-3.1-flash-lite` as its
replacement. Banning it now rather than on the day is the whole value: a name that dies
on a schedule costs a post-call pipeline returning empty extractions with a 404 nobody is
watching for, and the only cheap moment to act is the one where the identifier is being
written.
"""

from __future__ import annotations

import ast
from pathlib import Path

from calevate_shared.engine import (
    GEMINI_DEFAULT_LLM,
    GEMINI_RETIRED_LLMS,
    SARVAM_DEFAULT_LLM,
    SARVAM_RETIRED_LLMS,
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


def test_the_default_is_not_itself_retired() -> None:
    """The blind spot that would make the scan above pointless. `SARVAM_DEFAULT_LLM` lives
    in the one file the scan skips, so nothing else would notice if the next retirement
    caught up with it — which is exactly what happened to `sarvam-30b`, the migration
    target `sarvam-m` was pointed at before it was retired in turn."""
    assert SARVAM_DEFAULT_LLM not in SARVAM_RETIRED_LLMS, (
        f"{SARVAM_DEFAULT_LLM} is in the retired set and is also the default this repo "
        "sends on every extraction"
    )


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


def test_no_shipped_module_sends_a_retired_gemini_model() -> None:
    """The same scan, for the vendor whose retirement has a date on it.

    `apps/workers/extraction.py` carried `model: str = "gemini-2.5-flash-lite"` as a
    default argument until Part 13 — a literal in exactly the shape D-105 was written
    about, eight weeks from a vendor 404 on a path where the symptom is "extraction is
    empty" and the first three places anyone looks are the schema, the prompt and the
    transcript.
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
        "these modules name a Gemini model identifier that is retired or dated for "
        f"retirement: {ChainMapLike(offenders)}. Import "
        "`calevate_shared.engine.GEMINI_DEFAULT_LLM` instead."
    )


def test_the_gemini_default_is_not_itself_retired() -> None:
    """The same blind spot as the Sarvam one, and the same reason it is not hypothetical:
    `gemini-2.5-flash-lite` WAS the migration target for the 2.0 family before it acquired
    a retirement date of its own."""
    assert GEMINI_DEFAULT_LLM not in GEMINI_RETIRED_LLMS, (
        f"{GEMINI_DEFAULT_LLM} is in the retired set and is also what this repo sends on "
        "every user-triggered assist"
    )
    assert GEMINI_DEFAULT_LLM.startswith("gemini-3"), (
        "D-127 and BRD R-04 require a 3.x Flash-Lite: the 2.5 family retires 16 Oct 2026"
    )


def test_the_vertex_client_resolves_the_constant_rather_than_spelling_a_model() -> None:
    """The rewiring half. A file that swapped one literal for another passes the scan and
    reintroduces the defect the moment Google moves again."""
    from apps.workers.extraction import VertexGeminiExtractor
    from apps.workers.google_oauth import ServiceAccount

    account = ServiceAccount(
        client_email="a@b.iam.gserviceaccount.com",
        private_key="k",
        token_uri="https://oauth2.googleapis.com/token",
    )
    assert VertexGeminiExtractor(account, "calevate-prod").model_name == GEMINI_DEFAULT_LLM


class ChainMapLike:
    """Readable failure text for `{file: {names}}` without a dict repr full of `set()`."""

    def __init__(self, offenders: dict[str, set[str]]) -> None:
        self._offenders = offenders

    def __str__(self) -> str:
        return "; ".join(
            f"{path} → {sorted(names)}" for path, names in sorted(self._offenders.items())
        )

    __repr__ = __str__
