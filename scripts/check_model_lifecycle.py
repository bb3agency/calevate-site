"""Guardrail: no allow-listed model may outlive its vendor's retirement date unnoticed.

**THE FAILURE THIS EXISTS TO PREVENT** is not a wrong number in a doc. It is a phone
call, in progress, with a caller on the line, where the in-call LLM leg returns
`410 Gone` because a vendor turned off a model on a date nobody in this repository had
written down. There is no retry that helps and nobody is watching. D-410 deleted
`GEMINI_DEFAULT_LLM_RETIRES` and recorded the absence of a dated constant as a benefit;
what was actually true is that GEMINI's date left with Gemini, and the CLASS of problem —
a rented model with a vendor's clock on it — arrived unchanged at Azure.

**THREE OUTCOMES, AND THE MIDDLE ONE IS THE POINT OF THE DESIGN.**

    exit 2  REFUSED   It could not measure. The allow-list is empty, or the lifecycle
                      table does not cover exactly the allow-list, or an entry is
                      malformed, or a filed attestation is unreadable. A guard that
                      cannot see its own subject must REFUSE, never print OK — this is
                      the shape CLAUDE.md's coverage-ratchet rule spells out at length
                      and `check_metadata_columns` already implements.
    exit 1  FAIL      It measured, and the answer is bad: a selectable model is past its
                      retirement date, or every selectable model is inside the warning
                      lead with nothing to migrate TO.
    exit 0  OK/WARN   Warnings print and do not fail. What warns is stated below.

**WHY A WARN TIER AT ALL, when CLAUDE.md is hostile to findings nobody acts on.** Because
the two questions have different evidence classes and conflating them would make this
guard lie in one direction or the other. A retirement DATE is a vendor publication we
read at a named commit. Regional AVAILABILITY on the mandated SKU, and quota, are
properties of an Azure SUBSCRIPTION THAT DOES NOT EXIST YET — every gate that would
answer them is marked *"Blocked outside this repo on: an Azure subscription"*. Failing
the build over an undeployed deployment would be inventing a fact to make a gate green,
which is the D-31/D-32 error class pointing the other way. So availability WARNS, loudly,
by name, on every run, and OPERATIONS §2 gate 20b is what closes it.

**THE WARNING THAT CONTRADICTED THE SHIPPED DEFAULT IS NOW QUIET, AND ITS BRANCH STAYS.**
It fired for one release: Microsoft's Standard (regional) matrix did not list
`gpt-4o-mini` in `southindia`, so the shipped default could not be run in the only
permitted region on the only permitted SKU. D-449 resolved it by moving the REGION to
`eastus2`, which serves both allow-listed models there. A warning nobody is currently
seeing is exactly the kind of code a tidy-up deletes, so: it is the only thing in this
tree that would notice the same defect arriving from the other direction — a model added
to `AzureOpenAIModel`, or a region moved again, that the mandated SKU does not serve —
and the failure it catches is silent until a call gets a 404 mid-conversation.
`tests/model_lifecycle_guard_test.py` keeps it covered with a doctored table rather than
with the shipped one, which is also what stops the coverage ratchet counting it as an
uncovered branch.

Run: `uv run python -m scripts.check_model_lifecycle`   (also in `make guardrails`)
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from calevate_shared.engine import (
    AZURE_LOCATION,
    AZURE_OPENAI_DEFAULT_MODEL,
    AZURE_OPENAI_MODELS,
)
from calevate_shared.model_lifecycle import (
    ATTESTATION_PATH,
    MANDATED_DEPLOYMENT_TYPE,
    MODEL_LIFECYCLE,
    WARN_LEAD,
    Attestation,
    ModelLifecycle,
    load_attestation,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The oldest a reading may be before it stops counting as current: two years.
#:
#: A retirement date is not a fact, it is a fact AS OF a date — Microsoft moved
#: `gpt-4o-mini` eight months in a single unannounced edit (`model_lifecycle.py`). A
#: `read_on` older than this means nobody has re-read the vendor since, and the entry is
#: reported as stale rather than trusted. Two years rather than one because these are
#: 18-month lifecycles: a shorter window would fire on entries nobody could act on and
#: train the reader to skip the output, which is the failure mode WARN_LEAD is chosen
#: against too.
STALE_AFTER_DAYS = 730


def refusals(models: frozenset[str], table: dict[str, ModelLifecycle]) -> list[str]:
    """Reasons this check cannot MEASURE — each one exits 2, never 1 and never 0."""
    problems: list[str] = []
    if not models:
        problems.append(
            "AZURE_OPENAI_MODELS is empty. There is no allow-list to score, and an empty "
            "allow-list is not a product with no risk — it is a check with no subject."
        )
    if not table:
        problems.append(
            "MODEL_LIFECYCLE is empty. Every model this deployment may run would be "
            "undated, which is the exact state this guard was written to end."
        )
    undated = sorted(models - table.keys())
    if undated:
        problems.append(
            f"{undated} are selectable (AzureOpenAIModel) but have no MODEL_LIFECYCLE "
            "entry. A model can be shipped without a date only by adding one here — "
            "including 'unknown', spelled as a real entry with an unverified Evidence."
        )
    orphans = sorted(table.keys() - models)
    if orphans:
        problems.append(
            f"{orphans} have MODEL_LIFECYCLE entries but are not in AZURE_OPENAI_MODELS. "
            "Either the allow-list lost a model and the entry should go with it, or the "
            "entry is a typo protecting nothing."
        )
    for name, entry in sorted(table.items()):
        if entry.model != name:
            problems.append(f"MODEL_LIFECYCLE[{name!r}].model is {entry.model!r}.")
        if not entry.retirement.source or not entry.availability.source:
            problems.append(f"{name}: an Evidence carries no source. See D-31/D-32.")
        for label, evidence in (
            ("retirement", entry.retirement),
            ("availability", entry.availability),
        ):
            if evidence.read_on > date.today():
                problems.append(
                    f"{name}: {label} evidence claims to have been read on "
                    f"{evidence.read_on.isoformat()}, which is in the future."
                )
    return problems


def failures(
    table: dict[str, ModelLifecycle], today: date, attested: Attestation | None
) -> list[str]:
    """Reasons the answer is BAD. Exit 1."""
    problems: list[str] = []
    retired = sorted(name for name, e in table.items() if e.days_left(today) <= 0)
    for name in retired:
        entry = table[name]
        replacement = entry.replacement or "none published"
        problems.append(
            f"{name} retired on {entry.retires_on.isoformat()} "
            f"({-entry.days_left(today)} days ago) and is still selectable via "
            f"Settings.azure_openai_model. Vendor replacement: {replacement}. "
            f"Source: {entry.retirement.source}. An operator flipping the switch to it "
            "buys a 410 Gone on the next call."
        )
    survivors = {name: e for name, e in table.items() if e.days_left(today) > WARN_LEAD.days}
    if table and not survivors:
        problems.append(
            "NO REPLACEMENT IS CONFIGURED: every model in AZURE_OPENAI_MODELS is retired "
            f"or retires within {WARN_LEAD.days} days. The allow-list must gain a model "
            "that outlives the lead time — and adding one is not a one-line diff, see "
            "AzureOpenAIModel's comment for the three things it costs."
        )
    if attested is not None:
        if attested.resource_location.replace(" ", "").lower() != AZURE_LOCATION:
            problems.append(
                f"{ATTESTATION_PATH} records resource_location "
                f"{attested.resource_location!r}; AZURE_LOCATION is {AZURE_LOCATION!r}. "
                "A resource outside the only permitted region is a residency breach, not "
                "a config difference (OPERATIONS §2 gate 20)."
            )
        if attested.deployment_type != MANDATED_DEPLOYMENT_TYPE:
            problems.append(
                f"{ATTESTATION_PATH} records deployment_type "
                f"{attested.deployment_type!r}; only {MANDATED_DEPLOYMENT_TYPE!r} keeps "
                "processing in the resource's region. Global routes worldwide and is "
                "indistinguishable from the endpoint (gate 20c)."
            )
        if attested.deployment_model not in table:
            problems.append(
                f"{ATTESTATION_PATH} records a deployment of "
                f"{attested.deployment_model!r}, which is not in AZURE_OPENAI_MODELS. "
                "The thing that is deployed and the things this repository can price and "
                "date must be the same set."
            )
        elif (
            attested.deprecation_date is not None
            and attested.deprecation_date != table[attested.deployment_model].retires_on
        ):
            problems.append(
                f"{ATTESTATION_PATH} read a per-SKU deprecationDate of "
                f"{attested.deprecation_date.isoformat()} for "
                f"{attested.deployment_model}, but MODEL_LIFECYCLE says "
                f"{table[attested.deployment_model].retires_on.isoformat()}. THE PORTAL "
                "WINS — update the entry and its read_on. The subscription's own SKU "
                "date is the one a call actually obeys."
            )
    return problems


def warnings(
    table: dict[str, ModelLifecycle], today: date, attested: Attestation | None
) -> list[str]:
    """Things a human must act on that this repository cannot settle by itself."""
    notes: list[str] = []
    for name, entry in sorted(table.items()):
        left = entry.days_left(today)
        if 0 < left <= WARN_LEAD.days:
            notes.append(
                f"{name} retires in {left} days ({entry.retires_on.isoformat()}); vendor "
                f"replacement: {entry.replacement or 'none published yet'}. Migration is "
                "a new Azure deployment plus gates 20b/20c, not a code change."
            )
        age = (today - entry.retirement.read_on).days
        if age > STALE_AFTER_DAYS:
            notes.append(
                f"{name}: retirement date last read {age} days ago "
                f"({entry.retirement.read_on.isoformat()}). Vendor dates move — this one "
                "moved eight months in one edit — so re-read it at "
                f"{entry.retirement.source}."
            )
        if not entry.retirement.verified:
            notes.append(f"{name}: retirement date is [UNVERIFIED] — {entry.retirement.note}")
        if not entry.availability.verified:
            notes.append(
                f"{name}: {AZURE_LOCATION} availability is [UNVERIFIED] — {entry.availability.note}"
            )
    if attested is None:
        default = table.get(AZURE_OPENAI_DEFAULT_MODEL)
        offered = sorted(
            n for n, e in table.items() if e.offered_on_mandated_type and e.days_left(today) > 0
        )
        notes.append(
            f"NOBODY HAS FILED {ATTESTATION_PATH} — so which models this subscription can "
            f"actually deploy in {AZURE_LOCATION} as {MANDATED_DEPLOYMENT_TYPE} is "
            "UNRESOLVED. It is one portal reading away (OPERATIONS §2 gates 20b/20c), "
            "and the Models API returns a per-SKU deprecationDate that settles the dates "
            "at the same time."
        )
        # QUIET AGAINST THE SHIPPED TABLE SINCE D-449 AND DELIBERATELY KEPT — see this
        # module's docstring. It fired once, and what it caught was not a doc detail: the
        # region and the SKU this product had committed to could not, on the vendor's own
        # tables, run the model it shipped. The two ways it fires again are a new
        # allow-list member the mandated SKU does not serve in our region, and a region
        # that moves again; both are silent until a call 404s.
        if default is not None and not default.offered_on_mandated_type:
            notes.append(
                f"AND THE VENDOR'S OWN MATRIX CONTRADICTS THE SHIPPED DEFAULT: "
                f"{AZURE_OPENAI_DEFAULT_MODEL} is not listed for {AZURE_LOCATION} on "
                f"{MANDATED_DEPLOYMENT_TYPE} (only {sorted(default.offered_in_region)}), "
                f"while {offered or 'nothing else in the allow-list'} is. Either the "
                "default moves to a model this region serves on the mandated SKU, or the "
                "REGION moves — which is a residency decision and a decision-log entry, "
                "the way D-449 was. If the portal agrees with the matrix, the answer to "
                f"'what would we run' is "
                f"{offered[0] if offered else 'NOTHING WE HAVE ALLOW-LISTED'}."
            )
    return notes


def main(argv: list[str] | None = None) -> int:
    root = Path(argv[0]) if argv else REPO_ROOT
    today = date.today()
    table = MODEL_LIFECYCLE
    refused = refusals(AZURE_OPENAI_MODELS, table)
    attested: Attestation | None = None
    if not refused:
        try:
            attested = load_attestation(root)
        except Exception as exc:  # the message IS the output; a narrower catch would let a
            # new parse failure escape as a traceback, which reads as a broken guard
            # rather than as a bad attestation
            refused.append(f"{ATTESTATION_PATH} exists but could not be read: {exc}")
    if refused:
        print("MODEL LIFECYCLE: REFUSED TO SCORE")
        for problem in refused:
            print(f"  - {problem}")
        return 2

    bad = failures(table, today, attested)
    notes = warnings(table, today, attested)
    for note in notes:
        print(f"  ! {note}")
    if bad:
        print("MODEL LIFECYCLE: FAIL")
        for problem in bad:
            print(f"  - {problem}")
        return 1
    soonest = min(table.values(), key=lambda e: e.retires_on)
    print(
        f"MODEL LIFECYCLE: OK ({len(table)} model(s) dated; soonest {soonest.model} "
        f"retires {soonest.retires_on.isoformat()}, {soonest.days_left(today)} days; "
        f"warn lead {WARN_LEAD.days}d; {len(notes)} warning(s))"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
