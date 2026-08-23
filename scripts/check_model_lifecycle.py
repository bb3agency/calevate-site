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
    LLM_MODEL_NAMES,
    LLM_MODELS,
    SELECTABLE_LLM_MODELS,
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


def refusals(
    models: frozenset[str],
    table: dict[str, ModelLifecycle],
    selectable: frozenset[str] | None = None,
    catalogue: dict[str, object] | None = None,
) -> list[str]:
    """Reasons this check cannot MEASURE — each one exits 2, never 1 and never 0.

    `models` IS THE WHOLE CATALOGUE, NOT THE SELECTABLE SET, and the widening is the point.
    A model nobody may choose today is one an operator may make choosable tomorrow, and a
    withdrawn model is exactly the kind that sits undated for a year. So every identifier in
    `LLM_MODEL_NAMES` must be dated-or-explicitly-unread here, and `selectable` is used only
    for the one rule that genuinely depends on it: an UNREAD retirement date may not sit
    under a model somebody can run.
    """
    problems: list[str] = []
    choosable = SELECTABLE_LLM_MODELS if selectable is None else selectable
    if not models:
        problems.append(
            "LLM_MODEL_NAMES is empty. There is no catalogue to score, and an empty "
            "catalogue is not a product with no risk — it is a check with no subject."
        )
    if not table:
        problems.append(
            "MODEL_LIFECYCLE is empty. Every model this deployment may run would be "
            "undated, which is the exact state this guard was written to end."
        )
    missing = sorted(models - table.keys())
    if missing:
        problems.append(
            f"{missing} are in the catalogue (LLM_MODEL_NAMES) but have no MODEL_LIFECYCLE "
            "entry. A model can be shipped without a date only by adding one here — "
            "including an UNREAD one, spelled as a real entry with `retires_on=None` and an "
            "Evidence naming the page nobody could open."
        )
    orphans = sorted(table.keys() - models)
    if orphans:
        problems.append(
            f"{orphans} have MODEL_LIFECYCLE entries but are not in LLM_MODEL_NAMES. "
            "Either the catalogue lost a model and the entry should go with it, or the "
            "entry is a typo protecting nothing."
        )
    known = LLM_MODELS if catalogue is None else catalogue
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
        # THE UNREAD-AND-SELECTABLE ARM IS THE WHOLE REASON `retires_on` MAY BE `None` AT
        # ALL. It refuses rather than warns because the answer is not "act sooner", it is
        # "you cannot measure this and you are running it anyway".
        #
        # ⚠ **IT IS STATED OVER THE STANCE NOW, NOT OVER `retires_on is None`, AND THAT IS
        # THE DIFFERENCE HARD RULE 11 WAS WRITTEN ABOUT.** A missing date meant two opposite
        # things and this arm could not tell them apart: "the vendor publishes no shutdown
        # date for this identifier, and somebody opened the page and saw that" is the
        # STRONGEST state a model can be in, and "nobody has looked" is the state this guard
        # exists to end. Collapsing them forced a choice between refusing a durable GA model
        # and inventing a date for it — and inventing one is exactly what happened: a
        # REPORTED `2026-10-16` belonging to a preview snapshot sat under two GA Gemini rows,
        # was restated downstream as fact, and became the premise for withdrawing a whole
        # leg. `ModelLifecycle.retirement_stance` is the fix, and the record's own
        # `__post_init__` is what stops the new state being claimed without a reading: a
        # `none-announced` entry must carry VERIFIED retirement evidence.
        if entry.retirement_stance == "unread" and name in choosable:
            problems.append(
                f"{name} is selectable and NOBODY HAS READ a retirement page for it "
                f"({entry.retirement.source}). Either somebody opens the vendor's "
                "deprecation page and files what it says — a date, or `none-announced` if "
                "it lists the identifier with no shutdown — or the model comes off the "
                "selectable set in LLM_MODELS with a withdrawn_reason. An unread model is a "
                "410 Gone nobody has a clock for."
            )
        # THE LEG HAS TO AGREE WITH THE CATALOGUE. Two registries name the provider — this
        # one and `LLM_MODELS` — and they are written by hand in different files on purpose
        # (a registry that took the leg from the thing it is checking would be asking the
        # code whether it agrees with itself). Disagreement means one of them is describing
        # a model that does not exist, and every per-leg reading below would be aimed wrong.
        spec = known.get(name)
        catalogued = getattr(spec, "provider", None)
        if spec is not None and catalogued != entry.provider:
            problems.append(
                f"{name}: MODEL_LIFECYCLE says it runs on {entry.provider!r} and LLM_MODELS "
                f"says {catalogued!r}. Which leg a model is on decides its endpoint, its "
                "credential entry and which human gate is owed — two answers is none."
            )
        # DEPLOYMENT TYPES ARE AN AZURE FACT. On a leg with no deployments there is no SKU
        # for a model to be offered on, so a non-empty reading here is a fact nobody could
        # have read — and it would make the availability warning below fire about a matrix
        # that does not exist for this vendor.
        if not entry.deployment_types_apply and entry.offered_in_region:
            problems.append(
                f"{name} runs on the {entry.provider!r} leg, which has no deployment types "
                f"at all, but its entry lists {sorted(entry.offered_in_region)}. Regional "
                "availability matrices and SKUs are Azure's; on this leg the only "
                "availability question is whether the engine accepts the identifier."
            )
    return problems


def failures(
    table: dict[str, ModelLifecycle],
    today: date,
    attested: Attestation | None,
    selectable: frozenset[str] | None = None,
) -> list[str]:
    """Reasons the answer is BAD. Exit 1.

    **STATED OVER THE SELECTABLE SET, AND THAT SPLIT IS THE ONE THING THIS FUNCTION LEARNED
    WHEN THE CATALOGUE OPENED.** A retired model an operator can flip a live switch onto is
    a 410 Gone on the next call and must turn the build red. A retired model nobody may
    choose is a dated record of WHY it was withdrawn — `gemini-2.5-flash` is in this table
    precisely because Google turns it off on 16 Oct 2026 — and failing the build on the day
    its own refusal comes true would be a countdown to a day nobody can act on, which is the
    thing D-410 deleted and the thing that teaches readers to ignore a red build. It warns
    instead, by name, forever.
    """
    problems: list[str] = []
    choosable = SELECTABLE_LLM_MODELS if selectable is None else selectable
    scored = {name: e for name, e in table.items() if name in choosable}
    retired = sorted(
        name for name, e in scored.items() if (left := e.days_left(today)) is not None and left <= 0
    )
    for name in retired:
        entry = table[name]
        assert entry.retires_on is not None  # `retired` selected on a non-None days_left
        replacement = entry.replacement or "none published"
        problems.append(
            f"{name} retired on {entry.retires_on.isoformat()} "
            f"({(today - entry.retires_on).days} days ago) and is still SELECTABLE. Vendor "
            f"replacement: {replacement}. Source: {entry.retirement.source}. An operator or "
            "a client flipping the picker to it buys a 410 Gone on the next call."
        )
    # WHAT COUNTS AS A SURVIVOR, and `none-announced` is one — which it could not be while a
    # missing date was ambiguous. A model whose vendor has announced no shutdown at all
    # outlives the lead time more convincingly than one dated eighteen months out, and
    # treating it as a non-survivor would fire "NO REPLACEMENT IS CONFIGURED" on a catalogue
    # of perfectly durable models. `unread` is still not a survivor, and cannot reach here
    # anyway: `refusals()` above stops the run before it is scored.
    survivors = {
        name
        for name, e in scored.items()
        if e.retirement_stance == "none-announced"
        or ((left := e.days_left(today)) is not None and left > WARN_LEAD.days)
    }
    if scored and not survivors:
        problems.append(
            "NO REPLACEMENT IS CONFIGURED: every SELECTABLE model is retired, retires "
            f"within {WARN_LEAD.days} days, or has no date anybody has read. The catalogue "
            "must offer a model that outlives the lead time — and adding one is not a "
            "one-line diff, see LLM_MODELS for what an entry costs."
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
        if attested.deployment_model not in AZURE_OPENAI_MODELS:
            problems.append(
                f"{ATTESTATION_PATH} records a deployment of "
                f"{attested.deployment_model!r}, which is not in AZURE_OPENAI_MODELS "
                f"({sorted(AZURE_OPENAI_MODELS)}). An Azure attestation describes an Azure "
                "deployment: a model from another leg has no deployment to attest, and the "
                "thing that is deployed must be something this repository can price and "
                "date. This is stated over the AZURE set rather than the whole catalogue "
                "for exactly that reason — the catalogue now spans three legs and only one "
                "of them has deployments at all."
            )
        elif (
            attested.deprecation_date is not None
            and attested.deprecation_date != table[attested.deployment_model].retires_on
        ):
            # `table[...]` cannot KeyError here: the arm above already refused a
            # deployment_model outside AZURE_OPENAI_MODELS, and `refusals()` refuses a table
            # that does not cover the catalogue. The filed date is interpolated rather than
            # `.isoformat()`d because it may legitimately be None on another leg, and a
            # conditional expression for a case this branch cannot reach would be an
            # unreachable arm the ratchet counts and a reader cannot evaluate.
            problems.append(
                f"{ATTESTATION_PATH} read a per-SKU deprecationDate of "
                f"{attested.deprecation_date.isoformat()} for "
                f"{attested.deployment_model}, but MODEL_LIFECYCLE says "
                f"{table[attested.deployment_model].retires_on}. THE PORTAL "
                "WINS — update the entry and its read_on. The subscription's own SKU "
                "date is the one a call actually obeys."
            )
    return problems


def warnings(
    table: dict[str, ModelLifecycle],
    today: date,
    attested: Attestation | None,
    selectable: frozenset[str] | None = None,
) -> list[str]:
    """Things a human must act on that this repository cannot settle by itself."""
    notes: list[str] = []
    choosable = SELECTABLE_LLM_MODELS if selectable is None else selectable
    for name, entry in sorted(table.items()):
        offered = "SELECTABLE" if name in choosable else "withdrawn"
        left = entry.days_left(today)
        if entry.retirement_stance == "none-announced":
            # THE VENDOR ANNOUNCED NOTHING, AND SOMEBODY CHECKED. Reported on every run and
            # NOT as a defect: it is the strongest state an identifier can be in, and it is
            # here because it is PERISHABLE in a way a date is not. A shutdown date stays
            # true until it arrives; "nothing is announced" is true only as of the day the
            # page was read, and on both of the legs that carry this stance the page is
            # egress-blocked from this container and from CI — so no run can ever re-check
            # it, and the only thing that can is a person at the next rate-card review.
            #
            # ⚠ It also carries the caveat that makes the state honest: Google publishes its
            # shutdown dates as the EARLIEST possible retirement rather than a commitment,
            # and OpenAI's is a >=6-month notice policy, so "none announced" bounds the
            # notice period and never the lifetime.
            notes.append(
                f"{name} ({entry.provider}, {offered}): NO SHUTDOWN IS ANNOUNCED, read "
                f"{entry.retirement.read_on.isoformat()} at {entry.retirement.source}. That "
                "is a reading and not a blank — but it is only true as of that date, and "
                "this leg's deprecation page is egress-blocked here, so no run can re-check "
                "it. Re-read at the next rate-card review."
            )
        elif left is None:
            # THE UNREAD-DATE WARNING, WHICH IS THE PER-LEG DIFFERENCE MADE VISIBLE ON EVERY
            # RUN. It is not a defect in this file: it is the reading. Azure publishes a
            # dated schedule and this table consumes it; OpenAI and Google publish
            # deprecations on pages every egress path here refuses.
            notes.append(
                f"{name} ({entry.provider}, {offered}): NOBODY HAS READ A RETIREMENT PAGE "
                f"FOR IT. {entry.retirement.source}. The model cannot be made selectable "
                "until somebody does — see LLM_MODELS for the other half of the same block."
            )
        elif left <= 0 and name not in choosable:
            # RETIRED AND WITHDRAWN: a warning rather than a failure, and the entry STAYS.
            # It is the dated record of why the model is not on offer, and deleting it the
            # day it expires would delete the evidence for the refusal.
            notes.append(
                f"{name} ({entry.provider}) retired {-left} days ago "
                f"({entry.retires_on.isoformat() if entry.retires_on else '?'}) and is "
                "withdrawn, so this is a note and not a build failure. The entry stays: it "
                "is the dated record of why it is not on offer."
            )
        elif 0 < left <= WARN_LEAD.days:
            notes.append(
                f"{name} ({entry.provider}, {offered}) retires in {left} days "
                f"({entry.retires_on.isoformat() if entry.retires_on else '?'}); vendor "
                f"replacement: {entry.replacement or 'none published yet'}. On the Azure leg "
                "migration is a new deployment plus gates 20b/20c, not a code change."
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
            where = AZURE_LOCATION if entry.deployment_types_apply else "engine-side"
            notes.append(
                f"{name}: {where} availability is [UNVERIFIED] — {entry.availability.note}"
            )
    if attested is None:
        default = table.get(AZURE_OPENAI_DEFAULT_MODEL)
        # STATED OVER THE AZURE LEG ALONE. "What could we deploy instead" is a question about
        # deployments, and only one leg has any — a Gemini identifier in this list would be
        # an answer nobody could act on to a question about an Azure SKU.
        offered = sorted(
            n
            for n, e in table.items()
            if e.deployment_types_apply
            and e.offered_on_mandated_type
            and (e.days_left(today) or 0) > 0
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
    refused = refusals(LLM_MODEL_NAMES, table)
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
    # THE HEADLINE IS THE SOONEST **SELECTABLE** RETIREMENT, and the distinction is the same
    # one `failures` makes: a withdrawn model's date is a record, not a deadline, and putting
    # a 55-day Gemini countdown in the green line would report an emergency about a model no
    # client can reach. Undated entries are excluded because they have nothing to be soonest.
    dated = [
        entry
        for name, entry in table.items()
        if entry.retires_on is not None and name in SELECTABLE_LLM_MODELS
    ]
    soonest = min(dated, key=lambda e: e.retires_on or date.max) if dated else None
    headline = (
        f"soonest selectable {soonest.model} retires "
        f"{soonest.retires_on.isoformat() if soonest.retires_on else '?'}, "
        f"{soonest.days_left(today)} days"
        if soonest is not None
        else "NO selectable model carries a date"
    )
    print(
        f"MODEL LIFECYCLE: OK ({len(table)} model(s) across "
        f"{len({e.provider for e in table.values()})} leg(s); {headline}; "
        f"warn lead {WARN_LEAD.days}d; {len(notes)} warning(s))"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
