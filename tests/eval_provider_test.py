"""The eval harness's PROVIDER dimension — the half of task #87 that is not blocked.

Scoring Sarvam against Azure OpenAI over the golden transcripts needs a Sarvam key, an
Azure resource and egress, none of which exists in this repo or this environment. The
machinery that will do it on the day they arrive does exist, and this file is what stops it
rotting between now and then: every assertion here runs with no credential of any kind.

Ranked by what each failure costs, worst first:

1. **A provider with no key must REFUSE, never score.** An unscored provider that renders
   as a column of zeroes is evidence of something nobody measured, and the decision it
   feeds is where an Indian caller's transcript gets processed. It is also the one way
   this flag could make the harness worse than not having it.
2. **The comparison is per FIELD.** One aggregate number cannot separate "missed a field"
   from "filed the wrong value", and only one of those is survivable in a client's CRM.
3. **The default path is untouched.** `make eval-ci` is a merge gate; a flag that changed
   what it measures would be a silent change to what ships.
4. **A provider column is the provider it says it is.** `get_extractor()` falls back to
   the offline heuristic by design, and a comparison that inherited that fallback would
   label offline output "sarvam".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from apps.api.core.settings import get_settings
from apps.workers import extraction
from apps.workers.extraction import AZURE_PROVIDER, SARVAM_PROVIDER, OfflineExtractor
from calevate_shared.engine import AZURE_OPENAI_MODELS
from calevate_shared.extraction import ExtractionSchemaSpec
from scripts.eval import (
    CANNOT_RUN,
    FIXTURES,
    INVENTED,
    MISSED,
    PROVIDERS,
    RIGHT,
    WRONG,
    CaseResult,
    EvidenceLeakError,
    FieldScore,
    ProviderRun,
    field_scorecard,
    main_async,
    render_comparison,
    resolve_providers,
    run_case,
    write_evidence,
)

pytestmark = pytest.mark.anyio


# --- 1. an absent credential refuses, and says what to set ----------------------------


def test_a_provider_with_no_credential_is_refused_by_name() -> None:
    scorable, refused = resolve_providers([SARVAM_PROVIDER, AZURE_PROVIDER, "offline"])

    # The one that needs nothing still resolves; the other two are named, not scored.
    assert [name for name, _ in scorable] == ["offline"]
    assert {miss.provider for miss in refused} == {SARVAM_PROVIDER, AZURE_PROVIDER}
    # The refusal names the variable to set. "No credential" would send an operator into
    # Settings to work out which one — and for Azure there are THREE of them, which is the
    # whole reason `requires` is carried as prose rather than derived from a field name.
    assert "SARVAM_API_KEY" in str(refused[0])
    assert "AZURE_OPENAI_RESOURCE" in str(refused[1])
    assert "AZURE_OPENAI_DEPLOYMENT" in str(refused[1])
    # …and says plainly that nothing was measured, because the sentence a reader will
    # otherwise supply for themselves is "it scored zero".
    assert "nothing was measured" in str(refused[0])


def _with_settings(monkeypatch: Any, **overrides: Any) -> None:
    """Point `apps.workers.extraction` at a doctored `Settings`.

    Patched on the EXTRACTION module rather than on `apps.api.core.settings`, and the
    difference is not cosmetic: `extraction.py` does `from … import get_settings`, so the
    name is bound at import time and patching the source module leaves the binding alone.
    A test that patched the wrong one would pass for the wrong reason on every provider
    that has no credential anyway — which is all of them, here.
    """
    original = get_settings()
    monkeypatch.setattr(
        extraction, "get_settings", lambda: original.model_copy(update=dict(overrides))
    )


def test_the_wrong_kind_of_key_cannot_produce_an_azure_column(monkeypatch: Any) -> None:
    """D-127 G-1's rule, restated for the vendor D-410 chose.

    `Settings.gemini_api_key` outlived Gemini deliberately — its whole job is now to tell
    an operator who installed the WRONG credential apart from one who installed none
    (`assist_capability`, and see the field's comment in `calevate_shared/config.py`). What
    it must never do is open a door. A score measured through a credential the residency
    decision forbids would be evidence gathered by the means the decision forbids, so the
    `azure` column comes from `azure_extractor()` or from nothing.
    """
    _with_settings(monkeypatch, gemini_api_key="k")
    scorable, refused = resolve_providers([AZURE_PROVIDER])
    assert scorable == []
    assert [miss.provider for miss in refused] == [AZURE_PROVIDER]


def test_a_half_configured_azure_credential_refuses_rather_than_scoring(
    monkeypatch: Any,
) -> None:
    """D-410's new failure mode, and the one this harness could most easily get wrong.

    Every other provider here is ONE string: it is present or it is not. Azure needs a
    resource, a key and a deployment id, so there is a state no previous provider had —
    an operator midway through a change, with two of the three installed. Scoring that
    would mean building an extractor addressed at nothing and reporting its 4xx as the
    model's quality.

    `azure_credentials()` is the single place that decides, and it distinguishes UNSET
    (the ordinary state, says nothing) from HALF-SET (logs `azure_credential_incomplete`
    naming the FIELDS, never the values — one of the three IS the credential). Both answer
    `None` here, because a refusal is the only honest column for either.
    """
    _with_settings(
        monkeypatch,
        azure_openai_resource="calevate-prod",
        azure_openai_api_key="k",
        azure_openai_deployment=None,
    )
    scorable, refused = resolve_providers([AZURE_PROVIDER])
    assert scorable == []
    assert [miss.provider for miss in refused] == [AZURE_PROVIDER]


def test_a_fully_configured_azure_credential_scores_as_the_model_it_names(
    monkeypatch: Any,
) -> None:
    """The other half of the pair — a refusal that fires unconditionally is not a check.

    It also pins the trap Azure sets and no other provider does: the API is addressed by
    the DEPLOYMENT id, while `model_name` — what the scorecard column is headed with and
    what the cost model reads — is the MODEL the deployment was made from. A column headed
    with the deployment id would name a string only this operator's subscription
    understands, in a document whose whole purpose is comparing models across runs.
    """
    _with_settings(
        monkeypatch,
        azure_openai_resource="calevate-prod",
        azure_openai_api_key="k",
        azure_openai_deployment="calevate-4o-mini-southindia",
    )
    scorable, refused = resolve_providers([AZURE_PROVIDER])
    assert refused == []
    assert [name for name, _ in scorable] == [AZURE_PROVIDER]
    assert scorable[0][1].model_name in AZURE_OPENAI_MODELS, (
        "the column is headed with the DEPLOYMENT id — a string only this operator's "
        "subscription understands — in a document whose purpose is comparing models"
    )


async def test_the_runner_exits_2_and_scores_nothing_when_a_key_is_absent(
    tmp_path: Path,
) -> None:
    """Exit 2 is "could not be run", never 1 ("ran, and something regressed").

    A CI step that read a missing key as a regression would send somebody hunting for an
    extractor defect that does not exist; one that read it as 0 would be worse.
    """
    evidence = tmp_path / "scorecard.md"
    code = await main_async(
        "ci", None, update_baseline=False, providers=[SARVAM_PROVIDER], evidence=evidence
    )
    assert code == CANNOT_RUN
    # Nothing was written: an artefact is a claim, and refusing means there is none.
    assert not evidence.exists()


async def test_one_missing_provider_refuses_the_whole_comparison(tmp_path: Path) -> None:
    """A comparison silently missing the column somebody asked about reads as "we
    compared them" — and the absent one is invariably the one the decision is about."""
    evidence = tmp_path / "scorecard.md"
    code = await main_async(
        "ci",
        None,
        update_baseline=False,
        providers=["offline", SARVAM_PROVIDER],
        evidence=evidence,
    )
    assert code == CANNOT_RUN
    assert not evidence.exists()


async def test_an_unknown_provider_name_is_refused_rather_than_ignored() -> None:
    code = await main_async("ci", None, update_baseline=False, providers=["sarvam-v2"])
    assert code == CANNOT_RUN


# --- 2. the comparison is per field ---------------------------------------------------


def _case(**verdicts: str) -> CaseResult:
    result = CaseResult(case_id="c", title="c", scenario=1)
    for key, verdict in verdicts.items():
        result.verdict(key, verdict)
    return result


def test_the_scorecard_separates_a_miss_from_a_wrong_value() -> None:
    """The distinction the whole harness is built on, carried into the comparison.

    A model that MISSES `callback_number` files nothing and the SMB rings the caller back
    off the transcript. A model that gets it WRONG dials a stranger. Collapsing both into
    "1 field not captured" is how a comparison recommends the second model.
    """
    scores = field_scorecard(
        [
            _case(callback_number=MISSED),
            _case(callback_number=WRONG),
            _case(callback_number=RIGHT),
        ]
    )
    score = scores["callback_number"]
    assert (score.right, score.missed, score.wrong) == (1, 1, 1)
    assert score.asked == 3
    cell = score.cell()
    assert "1/3 right" in cell and "1 missed" in cell
    # Shouted, because it is unwaivable on every model tier.
    assert "**1 WRONG**" in cell


def test_restraint_is_counted_even_when_it_succeeds() -> None:
    """A model that invents nothing must be distinguishable from one nobody asked."""
    scores = field_scorecard([_case(budget_lakhs=INVENTED), _case(budget_lakhs="restrained")])
    score = scores["budget_lakhs"]
    assert score.withheld == 2
    assert "**1 INVENTED**" in score.cell()
    # No value was ever expected, so there is no `right` fraction to print.
    assert "right" not in score.cell()


def test_a_field_nobody_scored_reads_as_not_measured_never_zero() -> None:
    """`docs/evidence/bolna-pilot-scorecard.md`'s rule, applied to this table: a blank
    measured cell is NOT MEASURED, and a zero there becomes a wrong conclusion."""
    runs = [
        ProviderRun("offline", "offline-heuristic", [_case(name=RIGHT)], []),
        ProviderRun("sarvam", "sarvam-m", [_case(budget_lakhs=RIGHT)], []),
    ]
    meta = {"client": "ci", "vertical": "all", "ran_at": "t", "cases": 1}
    document = render_comparison(runs, meta)
    # Both fields appear, and each provider's untouched field says so rather than 0/0.
    assert "| `name` |" in document
    assert "| `budget_lakhs` |" in document
    assert "_not measured_" in document
    assert "0/0" not in document


class _StubExtractor:
    """An extractor that returns exactly what a test tells it to.

    The `Extractor` protocol is two members, so this is the whole of it. It exists
    because the verdicts have to be driven through `run_case` — the assertions above
    build `CaseResult`s by hand, which tests the SCORECARD and not the classification
    that feeds it. That gap was real: collapsing `WRONG` into `MISSED` inside `run_case`
    left every test in this file green.
    """

    model_name = "stub"

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    async def run(self, spec: ExtractionSchemaSpec, transcript: str) -> dict[str, Any]:
        return dict(self._data)


async def test_a_wrong_value_is_classified_wrong_and_a_blank_one_is_a_miss() -> None:
    """The distinction, driven through the REAL comparison rather than asserted about a
    hand-built result.

    Same two answers, same field, same case: one extractor files a different name and one
    files nothing. If those ever produce the same verdict, every per-field column in the
    scorecard silently stops being able to report the failure this harness exists for.
    """
    payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
    spec = ExtractionSchemaSpec(version=1, fields=payload["schema"])
    case = next(c for c in payload["cases"] if "name" in (c.get("expect") or {}))

    wrong = await run_case(spec, case, _StubExtractor({"name": "Nobody Whatsoever"}))
    blank = await run_case(spec, case, _StubExtractor({}))

    assert wrong.field_verdicts["name"] == WRONG
    assert blank.field_verdicts["name"] == MISSED
    # …and the scorecard carries the difference through, in the cell an operator reads.
    assert field_scorecard([wrong])["name"].wrong == 1
    assert field_scorecard([blank])["name"].missed == 1
    assert "**1 WRONG**" in field_scorecard([wrong])["name"].cell()
    assert "WRONG" not in field_scorecard([blank])["name"].cell()


async def test_a_field_the_caller_never_mentioned_is_classified_invented() -> None:
    """Restraint, driven the same way. `expect_absent` is the half that quietly ruins a
    CRM, and a verdict that never fires would report a fabricating model as restrained."""
    payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
    spec = ExtractionSchemaSpec(version=1, fields=payload["schema"])
    # A TEXT field, so the fabricated value survives schema validation and reaches the
    # comparison. A value the validator drops would land as null and be scored
    # `restrained` — which is the right answer for a dropped value and the wrong test.
    text_fields = {f.key for f in spec.fields if f.type == "text"}
    case, key = next(
        (c, k) for c in payload["cases"] for k in (c.get("expect_absent") or []) if k in text_fields
    )

    invented = await run_case(spec, case, _StubExtractor({key: "something nobody said"}))
    restrained = await run_case(spec, case, _StubExtractor({}))

    assert invented.field_verdicts[key] == INVENTED
    assert restrained.field_verdicts[key] == "restrained"
    assert "**1 INVENTED**" in field_scorecard([invented])[key].cell()


async def test_the_offline_provider_scores_the_real_fixtures_today() -> None:
    """The harness itself is exercised with no credential, so it cannot rot while task
    #87 waits on a key. Runs ONE fixture case rather than the suite: this is about the
    plumbing from provider to per-field verdict, and the suite's own coverage is
    `eval_harness_test.py`'s."""
    payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
    spec = ExtractionSchemaSpec(version=1, fields=payload["schema"])
    case = next(c for c in payload["cases"] if c.get("expect"))

    result = await run_case(spec, case, OfflineExtractor())

    # Every field the case had an expectation about got a verdict, and every verdict is
    # one of the five — a typo'd verdict would silently vanish from every scorecard.
    assert set(result.field_verdicts) >= set(case["expect"])
    assert set(result.field_verdicts.values()) <= {RIGHT, MISSED, WRONG, INVENTED, "restrained"}


# --- 3. the default path is untouched -------------------------------------------------


async def test_no_provider_flag_runs_the_gate_exactly_as_before(capsys: Any) -> None:
    """`make eval-ci` is a merge gate. This is the assertion that the flag did not move
    it: with no `--provider`, the output is the regression report, not a scorecard."""
    code = await main_async("ci", None, update_baseline=False)
    printed = capsys.readouterr().out
    assert code == 0
    assert printed.startswith("# Calevate regression report")
    assert "EVIDENCE ARTIFACT" not in printed


async def test_update_baseline_refuses_to_move_two_models_at_once() -> None:
    """`--update-baseline` is the one automated path that can lower the bar. Two
    baselines from one command is a diff no reviewer reads as two decisions."""
    code = await main_async(
        "ci", None, update_baseline=True, providers=["offline", SARVAM_PROVIDER]
    )
    assert code == CANNOT_RUN


# --- 4. a column is the provider it says it is ----------------------------------------


def test_the_registry_never_substitutes_one_provider_for_another() -> None:
    """`get_extractor()` ends at `OfflineExtractor` on purpose — a post-call pipeline that
    failed for want of a key would lose a lead. A NAMED provider must not inherit that:
    `sarvam` with no key resolves to nothing at all, not to the offline heuristic."""
    scorable, refused = resolve_providers([SARVAM_PROVIDER])
    assert scorable == []
    assert len(refused) == 1

    # …and `configured` is the one entry allowed to be whatever config selects, which is
    # why it is a NAME in the table rather than an unlabelled default.
    configured = PROVIDERS["configured"].build()
    assert configured is not None
    assert isinstance(configured, OfflineExtractor)


def test_every_registry_entry_is_named_after_the_provider_it_builds() -> None:
    """The dict key and the `Provider.name` are what a scorecard column is labelled with,
    and a mismatch would put one provider's numbers under another's heading."""
    for key, provider in PROVIDERS.items():
        assert key == provider.name


# --- The committed artefact -----------------------------------------------------------


def test_the_evidence_writer_refuses_a_document_that_still_carries_a_number(
    tmp_path: Path,
) -> None:
    """`docs/evidence/` is committed and git is forever.

    `_safe` masks every value on the way into a failure line, so this second sweep should
    never fire — which is exactly why it exists: a non-zero count means layer 1 has a
    hole, and the cheap outcome is a refused write rather than a permanent leak.
    """
    out = tmp_path / "scorecard.md"
    with pytest.raises(EvidenceLeakError):
        write_evidence(out, "| `callback_number` | got 9876543210 |")
    assert not out.exists()


def test_the_committed_scorecard_matches_what_the_harness_writes_today() -> None:
    """The artefact in `docs/evidence/` is generated, and a generated file nobody can
    regenerate is a hand-edited one within a month. This pins the two together on the
    parts that do not move: the banner, the regenerate command and the caveats."""
    document = Path("docs/evidence/extraction-provider-scorecard.md").read_text(encoding="utf-8")
    assert document.startswith("# Extraction provider scorecard — EVIDENCE ARTIFACT")
    assert "<!-- GENERATED FILE — do not hand-edit. -->" in document
    assert "uv run python -m scripts.eval --client=ci --provider=offline" in document
    # The caveat that stops this file being read as a licence to move the raw-PII
    # extraction pass off Sarvam, which D-127 G-7 forbids whatever the numbers say and
    # which D-410 deliberately did not revisit when it moved both LLM surfaces to Azure.
    assert "GEMINI_EXTRACTION_DEFAULT is False" in document


def test_a_verdict_the_scorecard_cannot_hold_is_an_error_not_a_lost_column() -> None:
    """The five verdict constants are bound to `FieldScore`'s five fields by string
    identity and nothing else, so `record()` must REFUSE a name it does not hold.

    The failure this rules out is silent: a verdict counted into an attribute nobody
    reads is missing from `asked`, missing from `withheld`, and printed by `cell()` as
    `_not measured_` — a field that WAS measured reported as evidence nobody gathered, in
    the document that feeds a residency decision. The one-character edit that would
    produce it is `getattr(self, verdict, 0)`, which reads like defensive programming.

    Also pinned: the five constants ARE the five fields, so renaming one on its own is
    caught here rather than in a scorecard three months from now.
    """
    score = FieldScore()
    with pytest.raises(AttributeError):
        score.record("rihgt")
    for verdict in (RIGHT, MISSED, WRONG, INVENTED, "restrained"):
        score.record(verdict)
    assert score.asked == 3 and score.withheld == 2, "a verdict landed nowhere"
    assert vars(score) == {
        "right": 1,
        "missed": 1,
        "wrong": 1,
        "invented": 1,
        "restrained": 1,
    }, "a verdict landed on an attribute no reader of the scorecard consults"
