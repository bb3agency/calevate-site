"""The rung words this product does not use, and the guard that stops them coming back.

**WHAT THE WORDS WERE, AND WHY THEY ARE EXCLUDED.** `standard` and `premium` are the
competitor's own rung names (D-547 excludes them BY NAME, TRD §10.3); `basic` is a claim
about the Sarvam voice no measurement in this repository supports; and "value" as a rung
name is a marketing rung we never adopted either. None of the four is our vocabulary, and
the founder read three surfaces on 9 Sep 2026 that were still using them.

**THE SECOND ERROR WAS WORSE THAN THE VOCABULARY, AND IT IS WHY THIS FILE EXISTS RATHER
THAN A FIND-AND-REPLACE.** The two rungs the words were attached to are NOT a voice, a
Bulbul version, or the Sarvam/Cartesia tier. They are the plan's two overage-rate slots —
`plans.overage_rate` and `plans.overage_rate_second` — and the code says so in three
places: `billing/service.py` above `OVERAGE_RUNGS` ("overage-rate slots ... NOT
voice-quality tiers"), `apps/workers/pipeline.py` beside the `meta.tts_tier` stamp ("THIS
IS THE PLAN'S OVERAGE-RATE SLOT AND NOT A VOICE"), and `agents/voices.py`
("`usage_events.meta.tts_tier`
is the PLAN'S OVERAGE RUNG"). Which voice spoke is a different fact on a different key
(`meta.voice_tier`). So the labels named an axis their own numbers do not come from, and
"correcting" them to Clear/Studio would have been the larger error wearing a fix.

**THE ONE ON A CLIENT DOCUMENT.** `invoice._RUNG_WORDING` printed "premium voice" /
"value voice" into a line item on a GST statement. It has never actually reached a client
— that map is read only on the two-rung branch, and the plan's second rate is NULL on
every plan, so every statement built to date took the single-line branch that carries no
rung word at all. One founder decision (setting a second rate) away from appearing.

**WHY A TEXT GUARD.** The same reasoning as `tests/credit_stop_copy_test.py`, which this
file follows deliberately: there is nothing to type. The fact under test is what a human
READS, on surfaces in two languages that import none of each other, and the failure mode
is not a compile error but a word that looks like a tier name. Python copy is read by
IMPORTING the constant, so the guard cannot pass against a string nobody renders;
TypeScript copy is read from source with comments stripped first, because every corrected
file records what it used to say in a comment on purpose and a guard that could not tell
copy from commentary would forbid the record of its own correction.

**THE HALF THAT MATTERS AS MUCH IS THE PERMITTED LIST.** Three of these words are correct
and load-bearing elsewhere, and a sweep that pattern-matched would have broken all three:

* `standard` is the DLT/TRAI NUMBER CLASS — 140 promotional, 160 service, standard — which
  is telecom vocabulary from CLAUDE.md's own domain list and appears in a `<option>` on a
  compliance-facing control.
* `value` is ordinary English on a dozen screens ("New value", "Static value", "we cannot
  show you the value again") and is the name of a Python/TS identifier everywhere.
* `premium` is an insurance term in the vertical examples ("Annual premium, age 30") and
  the LEDGER's own token (`usage_events.meta.tts_tier = "premium"`), which is FROZEN
  FOREVER — `usage_events` is append-only, so every row ever metered carries it and no
  UPDATE can reach one. D-558 renamed the identifiers around it (the wire fields, the
  plan column, the constants) and deliberately did not touch the token; see
  `tests/rung_rename_closed_month_test.py` for what re-spelling it would do to a closed
  month.

⚠ **THE WIRE HALF OF THIS FILE'S "NOT NOW" HAS SINCE BEEN DONE**, in the two-step hard
rule 8 requires (D-558): `minutes_base_rung` / `cost_second_rung_inr` /
`overage_minutes_base_rung` / `overage_rate_second_inr` are the names, the old ones are
still emitted beside them for one release, and `plans.overage_rate_value` gained
`overage_rate_second` beside it. What this file still pins is that the OLD names have not
been deleted early — `test_the_wire_keys_survive_until_step_two` below.

So this file fails if the words come back as RUNG NAMES, and fails if the three permitted
uses disappear.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "apps/web/src"

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"^\s*//.*$", re.MULTILINE)

#: The excluded words, as a RUNG NAME would appear in copy: capitalised at the head of a
#: label, or beside "voice"/"tier"/"rung"/"/ min". Matching the bare word would catch the
#: insurance premium and every "New value" on the site, which is the over-correction the
#: module docstring argues against.
FORBIDDEN = (
    # `\s+` alone missed "Value-tier rate", which is how the commercials form spelled it
    # and which this guard's first draft walked straight past.
    re.compile(r"\b(?:premium|value|standard|basic)[\s-]+(?:voice|tier|rung)s?\b", re.I),
    re.compile(r"\b(?:Premium|Value|Standard|Basic)\s*\((?:v\d|[^)]*voice[^)]*)\)"),
    re.compile(r"\b(?:Premium|Value|Standard|Basic)\s*/\s*min\b"),
)


def _copy_only(source: str) -> str:
    """Source with its commentary removed, so only what a reader could see is scanned."""
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", source))


def _assert_no_rung_words(text: str, where: str) -> None:
    for pattern in FORBIDDEN:
        found = pattern.search(text)
        assert found is None, (
            f"{where} names a pricing rung “{found.group(0) if found else ''}”. "
            "`standard`/`premium` are the competitor's rung names (excluded by D-547), "
            "`basic` is a voice claim nothing here measures, and `value` is a marketing "
            "rung we never adopted. These buckets are the plan's two OVERAGE-RATE SLOTS "
            "(`plans.overage_rate` / `overage_rate_second`) — not a voice, not a Bulbul "
            "version, not the Sarvam/Cartesia tier — so name them for the rate they are."
        )


# ─────────────────────────── the client's own document ───────────────────────────


def test_no_invoice_line_describes_a_rung_as_a_voice_or_a_tier() -> None:
    """The headline: `_RUNG_WORDING` is a phrase on a GST statement a client keeps."""
    from apps.api.billing.invoice import _RUNG_WORDING

    assert set(_RUNG_WORDING) == {"premium", "value"}, (
        "the rung KEYS moved — they are the LEDGER's frozen tokens (`usage_events` is "
        "append-only, so every row ever metered carries them), not words, and not "
        "something a copy fix may re-spell"
    )
    for key, wording in _RUNG_WORDING.items():
        assert wording.strip(), f"the {key} rung renders no description at all"
        _assert_no_rung_words(wording, f"invoice._RUNG_WORDING[{key!r}]")


def test_an_invoice_line_still_says_which_agreed_rate_it_was_charged_at() -> None:
    """Not merely inoffensive — the words have a job.

    Two overage lines on one statement differ only in the rate they were struck at, so the
    description has to name that, or a client reading two "Extra calling minutes" lines has
    no way to tell which agreement each belongs to.
    """
    from apps.api.billing.invoice import _RUNG_WORDING

    for key, wording in _RUNG_WORDING.items():
        assert "rate" in wording.lower(), (
            f"invoice._RUNG_WORDING[{key!r}] = {wording!r} does not say it is a RATE — the "
            "one fact that distinguishes two overage lines on the same statement"
        )
    assert len(set(_RUNG_WORDING.values())) == 2, "the two rungs print the same words"


# ────────────────────── the operator's screens, by reading source ──────────────────────

#: The admin screens that report the overage rungs. The client console is deliberately not
#: on this list: it never names a rung, and `tests` below sweeps the whole tree anyway.
ADMIN_RUNG_SCREENS = (
    "apps/web/src/app/admin/tenants/[tenantId]/page.tsx",
    "apps/web/src/app/admin/tenants/[tenantId]/commercials/page.tsx",
)


@pytest.mark.parametrize("rel", ADMIN_RUNG_SCREENS)
def test_no_admin_screen_labels_a_rung_with_the_excluded_words(rel: str) -> None:
    path = REPO / rel
    assert path.is_file(), f"{rel} has moved — this guard is scanning nothing"
    _assert_no_rung_words(_copy_only(path.read_text(encoding="utf-8")), rel)


def test_the_whole_web_tree_is_clean_of_rung_vocabulary() -> None:
    """The sweep, because the founder asked for the CLASS and not the two screens.

    Marketing, legal, pricing and both consoles: any `.tsx`/`.ts` a human reads. The
    generated OpenAPI client is excluded — it is the wire's own field names and prose, and
    it is not authored here.
    """
    offenders: list[str] = []
    for path in sorted(WEB.rglob("*.ts*")):
        if path.name in {"schema.d.ts", "openapi.json"}:
            continue
        text = _copy_only(path.read_text(encoding="utf-8"))
        for pattern in FORBIDDEN:
            for hit in pattern.finditer(text):
                offenders.append(f"{path.relative_to(REPO)}: {hit.group(0)}")
    assert offenders == [], "rung vocabulary in user-visible copy:\n  " + "\n  ".join(offenders)


# ───────────────────────── and the three that must NOT be swept ─────────────────────────


def test_the_dlt_number_class_still_says_standard() -> None:
    """140 promotional / 160 service / standard is TELECOM vocabulary, not a pricing rung.

    It is a `<option value="standard">` on a compliance-facing control and a wire value the
    campaign path reads; an over-correcting sweep would break the control and the wire
    together.
    """
    numbers = (REPO / "apps/web/src/app/admin/tenants/[tenantId]/page.tsx").read_text(
        encoding="utf-8"
    )
    assert '<option value="standard">standard</option>' in numbers, (
        "the DLT number class lost its `standard` option — that word is the TRAI series "
        "name (CLAUDE.md's domain vocabulary), not one of the excluded rung names"
    )

    from apps.api.campaigns.service import SERIES_FOR_CLASSIFICATION

    assert "standard" in SERIES_FOR_CLASSIFICATION["service"]


def test_ordinary_english_value_and_premium_survive() -> None:
    """Two words that are only forbidden as RUNG names.

    The insurance vertical quotes a policy premium, and half the console's forms say
    "value" about a field's contents. A guard that could not tell these from a tier name
    would delete correct copy to protect a rule about a different word.
    """
    verticals = (REPO / "apps/web/src/lib/verticalExamples.ts").read_text(encoding="utf-8")
    assert "Annual premium" in verticals, "the insurance example lost its policy premium"

    config = REPO / "apps/web/src/app/admin/ops/ConfigPanel.tsx"
    assert "New value" in config.read_text(encoding="utf-8"), (
        'the platform config panel lost its ordinary-English "New value" — that is a '
        "field's contents, not a pricing rung"
    )


def test_the_wire_keys_survive_until_step_two() -> None:
    """The two-step, from the side this file owns: BOTH spellings are on the contract.

    `minutes_premium` / `cost_value_inr` and friends are the wire, the generated client
    and every console bundle already deployed. D-558 added the names that replace them and
    hard rule 8 forbids removing the old ones in the same release — a bundle and an API
    are not redeployed in the same instant, and a sweep that "finished the job" here would
    break whichever of the two shipped second.

    Both directions are asserted. A missing NEW name means the rename never reached the
    contract; a missing OLD one means step 2 landed a release early.
    """
    from apps.api.admin.routes import TierSplitOut

    for field in (
        "minutes_base_rung",
        "minutes_second_rung",
        "minutes_unattributed",
        "cost_base_rung_inr",
        "cost_second_rung_inr",
        "cost_unattributed_inr",
    ):
        assert field in TierSplitOut.model_fields, f"the wire never gained {field}"
    for field in ("minutes_premium", "minutes_value", "cost_premium_inr", "cost_value_inr"):
        assert field in TierSplitOut.model_fields, (
            f"the wire lost the deprecated {field} — step 2 may not land in the release "
            "that stopped writing it (hard rule 8)"
        )
