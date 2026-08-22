"""WHEN EACH MODEL THIS PRODUCT MAY RUN STOPS ANSWERING, and on which deployment type.

**WHY THIS FILE EXISTS AT ALL.** `AzureOpenAIModel` (`engine.py`) is a closed allow-list
that carried NO lifecycle information: a reader could see which models are selectable and
what they cost, and nothing about when a vendor turns one off. D-410 deleted
`GEMINI_DEFAULT_LLM_RETIRES` and recorded, as a benefit, that no dated constant replaced
it. That was true of Gemini and NOT true of the class of problem: a rented model has a
retirement date whether or not this repository writes one down, and the only difference
is whether the build finds out or a caller does, mid-call, as `410 Gone`.

**WHAT A `410 Gone` COSTS HERE, and it is why this is a build gate and not a dashboard
tile.** The in-call LLM leg runs inside the engine, on a phone call, with a caller on the
line. There is no retry that helps and no operator watching. The failure is silent until
it is total.

**THE DATES ARE VENDOR CLAIMS AND THEY MOVE.** Every entry therefore carries its SOURCE
and the DATE IT WAS READ, and says whether it was read from the vendor's own publication
or inferred. This is not ceremony: on **2026-07-23**, in commit `138e0f109f` of
`MicrosoftDocs/azure-ai-docs`, Microsoft moved `gpt-4o-mini` (2024-07-18) from
**2026-10-01** to **2027-04-14** in one edit — an eight-month extension, published without
announcement, and their own page says these details are *"subject to change"*. A date
copied here without its read-date is a fact with no shelf life, and the direction of drift
is not always favourable.

**WHERE THESE READINGS CAME FROM, because it is a better evidence class than this
repository usually gets and the next reader should know why.** Microsoft's documentation
HOST is egress-blocked from this environment (`learn.microsoft.com` → 403 on CONNECT,
measured 22 Aug 2026), which is what forced D-410's own pricing note to fall back on the
decision's record. But Microsoft publishes those pages from a PUBLIC GIT REPOSITORY,
`github.com/MicrosoftDocs/azure-ai-docs`, and this session's git proxy serves anonymous
reads of it. So these are not search summaries and not a tracker's table: they are the
vendor's own source files, at a named commit, with the commit's date and the page's own
`ms.date`. That is a stronger class than VERIFIED-VENDOR-DOCS usually means here, and it
is reproducible — `git clone --depth 1 https://github.com/MicrosoftDocs/azure-ai-docs`.

**IT IS STILL NOT THE PORTAL, AND THE GAP IS THE POINT.** A doc says what the vendor
publishes about a region; only the subscription says what OUR subscription can deploy, at
what quota, on which SKU. Azure exposes that machine-readably — the Models API returns
`lifecycleStatus`, `deprecation` and a **per-SKU `deprecationDate`** for every model
(`concepts-model-retirements-content.md:126`) — and that is what OPERATIONS §2 gate 20b
now asks a human to read and file. `ATTESTATION_PATH` is where it lands, and
`scripts/check_model_lifecycle.py` prefers it over everything written here.

**THIS FILE'S FIRST READING REVERSED D-410's PREMISE, AND D-449 IS WHAT THAT READING
CAUSED.** D-410 chose `gpt-4o-mini` as the default because it was *"documented available
in South India"* while `gpt-4.1-mini`'s Indian availability was *"NOT confirmed"*.
Microsoft's Standard (regional) availability matrix said the opposite for `southindia`:
`gpt-4.1-mini` listed, `gpt-4o-mini` **not** — the shipped default appeared for that
region only on the GLOBAL Standard matrix, and Global is the deployment type OPERATIONS §2
gate 20c exists to forbid because it processes worldwide. So the only permitted region and
the only permitted SKU had no documented way to run the shipped default at all.

That contradiction is now RESOLVED, and it was resolved by moving the REGION rather than
the model: D-449 withdrew the India residency claim and pinned `AZURE_LOCATION` to
`eastus2`, where the same matrix marks both allow-listed models available on the mandated
SKU (`standard-models.md:23`). Recording which of the two moved matters, because "we
changed the default model" and "we stopped claiming Indian residency" are answers to the
same build warning with entirely different consequences for a client's DPA.

⚠ THE STALENESS CAVEAT SURVIVES THE MOVE UNCHANGED. That matrix's own `ms.date` is
08/12/2025, so both `availability` entries below stay `verified=False` and print
`[UNVERIFIED]` on every run. A green region is still a vendor publication about a region,
not a statement about OUR subscription; only OPERATIONS §2 gate 20b closes it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Final, Literal, get_args

#: Azure's deployment types, in the vocabulary this repository uses for them.
#:
#: SPELLED AS SLUGS rather than as the portal's display strings ("Standard", "Global
#: Standard"), because the portal's word for the regional one is just *"Standard"* — a
#: string too easy to read as "the ordinary one" in a file whose entire subject is that
#: the ordinary one is NOT the default. `standard-regional` cannot be misread.
DeploymentType = Literal[
    "standard-regional",
    "global-standard",
    "data-zone-standard",
    "provisioned",
]

DEPLOYMENT_TYPES: Final[frozenset[str]] = frozenset(get_args(DeploymentType))

#: The ONLY deployment type this product may run on, and the reason is not performance.
#:
#: Global Standard is Azure's DEFAULT and routes to capacity anywhere in the world; a
#: Global deployment inside the resource passes every automated check in this tree —
#: including `scripts/check_model_residency.py`, which cannot see a SKU — and breaks the
#: DPA. OPERATIONS §2 gate 20c is the human reading that settles it.
#:
#: D-449 DID NOT RELAX THIS, and the temptation to think it did is worth naming: withdrawing
#: the India residency claim does not make "processes anywhere in the world" acceptable.
#: What we still owe a client is a NAMED region they were told about, `eastus2`, and Global
#: is the deployment type that silently makes that untrue.
MANDATED_DEPLOYMENT_TYPE: Final[DeploymentType] = "standard-regional"

#: How long before a retirement date the build starts warning: **120 days**.
#:
#: NOT AN ARBITRARY ROUND NUMBER — it is the first moment the migration is knowable,
#: taken from the vendor's own published process, and it is deliberately far longer than
#: the notice the vendor promises:
#:
#:   * *"Microsoft selects the official replacement approximately 90-120 days before
#:     retirement"* (`concepts-model-retirements-content.md:136`; the same window is
#:     explained in the "Why 90-120 days?" callout at `:98` — the vendor spells both with
#:     an EN DASH, respelled here with a hyphen because ruff's RUF003 refuses the
#:     character in a comment). Before that window there
#:     may be no replacement to move TO, so a warning earlier than 120 days is a warning
#:     nobody can act on — and a warning nobody can act on is how a build teaches its
#:     readers to ignore warnings.
#:
#:     ⚠ THIS CITATION WAS WRONG UNTIL IT WAS RE-READ (22 Aug 2026, A2 audit). It pointed
#:     at `concepts-model-retirement-SCHEDULE-content.md:20`, which is the heading
#:     `## Foundry Models sold by Azure` — a different FILE, not merely a slipped line.
#:     The two filenames differ by one word and both are in the same directory. Worth
#:     leaving recorded because `WARN_LEAD` is the one constant here whose value is
#:     argued entirely from a vendor sentence: a citation that resolves to a heading is
#:     indistinguishable, to a reader who does not open it, from one that resolves to the
#:     claim.
#:   * The vendor's own notice is *"at least 60 days"* for a GA model
#:     (`concepts-model-retirements-content.md:150`), delivered by email to SUBSCRIPTION
#:     OWNERS. That is one person's inbox, and it is not this build.
#:
#: AND OUR MIGRATION IS NOT A CODE CHANGE, which is what makes 60 days too short for us
#: specifically: switching model means a new Azure deployment on the mandated SKU, a
#: quota reading, and a re-attestation filed in `docs/evidence/` — three steps that are
#: blocked on a human with portal access, i.e. exactly the class CLAUDE.md's tempo rule
#: says has a real timeline and is nobody's to code around.
WARN_LEAD: Final = timedelta(days=120)

#: Where a human files what they read in the Azure portal (OPERATIONS §2 gates 20b/20c).
#:
#: JSON, in a tree whose evidence is otherwise prose, and the exception is deliberate: a
#: guardrail that parsed a paragraph would be a guardrail that fails on a rewording. The
#: prose account of the reading still belongs in `docs/evidence/`; this file is the part
#: the build consumes. Absent is a legitimate state and means UNRESOLVED, not OK — the
#: check says which.
ATTESTATION_PATH: Final = Path("docs/evidence/azure-deployment-attestation.json")


@dataclass(frozen=True, slots=True)
class Evidence:
    """Where a fact came from and when — carried per FACT, not per file.

    `verified` is about the CLASS of the source, not about confidence: True means the
    vendor's own publication was read (here: their docs repository at a named commit),
    False means anything else — a search summary, a tracker, an inference. A False entry
    is printed as `[UNVERIFIED]` on every run of the check rather than quietly averaged
    in with the rest, because D-31/D-32 exist because an unlabelled second-hand claim
    became a silent premise.
    """

    source: str
    read_on: date
    verified: bool
    note: str = ""


@dataclass(frozen=True, slots=True)
class ModelLifecycle:
    """One allow-listed model's dated vendor facts.

    `offered_in_region` is the set of deployment types the vendor's availability matrix
    lists this model under in `AZURE_LOCATION` — NOT a claim about our subscription,
    which only the portal or the Models API can answer (gate 20b). An empty set means
    "the vendor's matrix does not list it in this region at all", which is a real reading
    and not a missing one; `availability` carries how that reading was obtained.
    """

    model: str
    version: str
    retires_on: date
    #: The vendor's own word: GA · Legacy · Deprecated · Retired.
    stage: str
    #: What the vendor names as the migration target, or None when the column is `—`.
    replacement: str | None
    offered_in_region: frozenset[DeploymentType]
    retirement: Evidence
    availability: Evidence

    @property
    def offered_on_mandated_type(self) -> bool:
        return MANDATED_DEPLOYMENT_TYPE in self.offered_in_region

    def days_left(self, today: date) -> int:
        return (self.retires_on - today).days


_MS_DOCS_COMMIT: Final = "19bbfea4b8cdc87e92f542b9d7c47f3a4c7f6b10"

#: `MicrosoftDocs/azure-ai-docs`, the repository Microsoft publishes learn.microsoft.com
#: from. Cited as `path:line @ commit` so the next reader can re-open the exact bytes.
_SCHEDULE: Final = (
    "MicrosoftDocs/azure-ai-docs@"
    f"{_MS_DOCS_COMMIT[:10]} "
    "articles/foundry/openai/includes/concepts-model-retirement-schedule-content.md"
)
#: The Standard (REGIONAL) availability matrix, cited at the row for `AZURE_LOCATION`.
#: `:23` is `eastus2` since D-449; it was `:34` (`southindia`) before. Cited by LINE
#: because a matrix has one row per region and a citation to the page alone would let a
#: reader check the wrong one.
_STANDARD_MATRIX: Final = (
    "MicrosoftDocs/azure-ai-docs@"
    f"{_MS_DOCS_COMMIT[:10]} "
    "articles/foundry/openai/includes/model-matrix/standard-models.md:23"
)
_READ_ON: Final = date(2026, 8, 22)

#: THE ALLOW-LIST'S LIFECYCLE, keyed by the same identifiers as `AZURE_OPENAI_MODELS`.
#:
#: KEYED BY MODEL AND NOT BY THE `Literal`, for `AZURE_LIST_PRICE_USD_PER_MTOK`'s reason:
#: a model identifier read back off a historical `usage_events` row is not a member of
#: today's allow-list and never will be again, and asking "when did that retire" about a
#: leg that already ran is a legitimate question. What that costs is a check the type
#: cannot make — a model added to `AzureOpenAIModel` without an entry here — and
#: `scripts/check_model_lifecycle.py` REFUSES rather than passes when the two disagree,
#: in either direction.
MODEL_LIFECYCLE: Final[dict[str, ModelLifecycle]] = {
    "gpt-4o-mini": ModelLifecycle(
        model="gpt-4o-mini",
        version="2024-07-18",
        retires_on=date(2027, 4, 14),
        stage="Deprecated",
        replacement=None,
        offered_in_region=frozenset({"standard-regional", "global-standard"}),
        retirement=Evidence(
            source=f"{_SCHEDULE}:35 (page ms.date 08/19/2026)",
            read_on=_READ_ON,
            verified=True,
            note=(
                "Row: `| gpt-4o-mini | 2024-07-18 | Deprecated | 2027-04-14 | — |`. "
                "WAS 2026-10-01 until commit 138e0f109f (2026-07-23) extended it — the "
                "2026-10-01 figure circulating in trackers is a real but SUPERSEDED "
                "vendor date. The reported '2026-03-31 for Standard deployments' is a "
                "conflation with gpt-4o (2024-05-13) in the AZURE GOVERNMENT doc "
                "(concepts-model-retirements-content-gov.md:90) — different model, "
                "different cloud. No deployment-type split exists in the schedule: it "
                "publishes ONE date per model version."
            ),
        ),
        availability=Evidence(
            source=_STANDARD_MATRIX,
            read_on=_READ_ON,
            verified=False,
            note=(
                "Row `| eastus2 | ... |`, column `gpt-4o-mini, 2024-07-18`: available on "
                "Standard (regional). This entry read `{global-standard}` until D-449, on "
                "the same matrix's `southindia` row (:34), where this model is marked `-` "
                "— the contradiction that put the shipped default outside the only "
                "permitted region on the only permitted SKU. IT WAS RESOLVED BY MOVING THE "
                "REGION, NOT THE MODEL. Global Standard (standard-global.md:23, ms.date "
                "07/23/2026) also lists it for eastus2, so a Global deployment here would "
                "be as easy to create by accident as it was before — gate 20c, unchanged. "
                "The matrix is the vendor's own, but its `ms.date` is 08/12/2025 and its "
                "content has not changed in this repository's visible history, so it is "
                "carried UNVERIFIED as a statement about today. Settled by OPERATIONS §2 "
                "gate 20b."
            ),
        ),
    ),
    "gpt-4.1-mini": ModelLifecycle(
        model="gpt-4.1-mini",
        version="2025-04-14",
        retires_on=date(2027, 4, 14),
        stage="Legacy",
        replacement=None,
        offered_in_region=frozenset({"standard-regional", "global-standard"}),
        retirement=Evidence(
            source=f"{_SCHEDULE}:30 (page ms.date 08/19/2026)",
            read_on=_READ_ON,
            verified=True,
            note=(
                "Row: `| gpt-4.1-mini | 2025-04-14 | Legacy | 2027-04-14 | — |`. Also "
                "extended by commit 138e0f109f (2026-07-23), from 2026-10-14."
            ),
        ),
        availability=Evidence(
            source=_STANDARD_MATRIX,
            read_on=_READ_ON,
            verified=False,
            note=(
                "Row `| eastus2 | ... |`, column `gpt-4.1-mini, 2025-04-14`: available on "
                "Standard (regional). It was ALSO listed for southindia (:34) — the "
                "opposite of D-410's assumption that its Indian availability was "
                "unconfirmed — so this model was never the one the old region could not "
                "serve, and D-449 does not change its reading. Same staleness caveat as "
                "gpt-4o-mini's row; same gate settles it (20b)."
            ),
        ),
    ),
}


@dataclass(frozen=True, slots=True)
class Attestation:
    """What a human read in the Azure portal, parsed from `ATTESTATION_PATH`.

    This OUTRANKS everything above it, and that ordering is the whole design: the vendor
    publishes what a region offers, our subscription decides what it can deploy, and only
    the second one lets a call succeed.
    """

    resource_location: str
    deployment_model: str
    deployment_type: str
    read_on: date
    read_by: str
    #: Per-SKU `deprecationDate` from the Models API, when the reader captured it.
    deprecation_date: date | None


def load_attestation(root: Path) -> Attestation | None:
    """Parse `ATTESTATION_PATH` under `root`, or None when nobody has filed one.

    RAISES on a file that exists and is wrong, rather than returning None. An absent
    attestation is an honest "not yet read"; a malformed one is a reading somebody
    believes they filed, and treating it as absent would be the quietest possible way to
    lose it.
    """
    path = root / ATTESTATION_PATH
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    required = (
        "resource_location",
        "deployment_model",
        "deployment_type",
        "read_on",
        "read_by",
    )
    missing = [key for key in required if not raw.get(key)]
    if missing:
        raise ValueError(f"{ATTESTATION_PATH} is missing required field(s): {missing}")
    if raw["deployment_type"] not in DEPLOYMENT_TYPES:
        raise ValueError(
            f"{ATTESTATION_PATH} names deployment_type {raw['deployment_type']!r}; "
            f"expected one of {sorted(DEPLOYMENT_TYPES)}"
        )
    deprecation = raw.get("deprecation_date")
    return Attestation(
        resource_location=str(raw["resource_location"]),
        deployment_model=str(raw["deployment_model"]),
        deployment_type=str(raw["deployment_type"]),
        read_on=date.fromisoformat(str(raw["read_on"])),
        read_by=str(raw["read_by"]),
        deprecation_date=date.fromisoformat(str(deprecation)) if deprecation else None,
    )


__all__ = [
    "ATTESTATION_PATH",
    "DEPLOYMENT_TYPES",
    "MANDATED_DEPLOYMENT_TYPE",
    "MODEL_LIFECYCLE",
    "WARN_LEAD",
    "Attestation",
    "DeploymentType",
    "Evidence",
    "ModelLifecycle",
    "load_attestation",
]
