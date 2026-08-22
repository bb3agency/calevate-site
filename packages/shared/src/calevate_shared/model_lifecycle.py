"""WHEN EACH MODEL THIS PRODUCT MAY RUN STOPS ANSWERING, and on which deployment type.

**IT COVERS EVERY DECLARED LEG, AND THE LEGS DO NOT ANSWER THE SAME.** Azure publishes a
dated retirement schedule per model version and per SKU, in a git repository this
environment can read at a named commit — that is one of the four grounds D-449 retains it
on, and it is what the whole mechanism below was built around. Google publishes a date this
environment can only reach through search summaries. OpenAI publishes deprecations on a page
every egress path here refuses, so its two models carry `retires_on=None`: an UNREAD date,
recorded as one, never a guess dressed as a fact. Reading the three side by side in one
table is the point — the difference between the legs IS the finding.

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

from calevate_shared.engine import Evidence, LlmProvider

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


#: `Evidence` NOW LIVES IN THE PORTABILITY CONTRACT (`calevate_shared.engine`) and is
#: imported rather than redefined. It was born here, and it moved for one reason: a MODEL'S
#: PRICE needs the same record, the price lives in the contract because hard rule 7 turns it
#: into money, and a contract that imported this module to get the record would have made
#: this module unable to name a `LlmProvider` — which it now must. One record, one home, one
#: direction of dependency.


@dataclass(frozen=True, slots=True)
class ModelLifecycle:
    """One catalogue model's dated vendor facts.

    `offered_in_region` is the set of deployment types the vendor's availability matrix
    lists this model under in `AZURE_LOCATION` — NOT a claim about our subscription,
    which only the portal or the Models API can answer (gate 20b). An empty set means
    "the vendor's matrix does not list it in this region at all", which is a real reading
    and not a missing one; `availability` carries how that reading was obtained.

    **IT IS PER-LEG NOW, AND TWO FIELDS CHANGED MEANING RATHER THAN GAINING ONE.** Deployment
    types and regional availability matrices are AZURE facts: no other leg has a deployment,
    a SKU or a per-region matrix, so `offered_in_region` is required to be EMPTY on any other
    provider and `provider` is what says which reading applies. An empty set therefore means
    two different things on two different legs, which is exactly why the leg has to be on the
    record rather than inferred from the identifier.
    """

    model: str
    #: Which leg runs it — the same answer `calevate_shared.engine.LLM_MODELS` gives, held
    #: here as well because `check_model_lifecycle` compares the two and a registry that took
    #: the provider from the thing it is checking would be asking the code whether it agrees
    #: with itself.
    provider: LlmProvider
    version: str
    #: When the vendor turns it off — or `None` when NOBODY HERE HAS READ A DATE.
    #:
    #: **`None` IS A READING, NOT A BLANK, AND IT IS THE DIFFERENCE BETWEEN THE LEGS.**
    #: Microsoft publishes a dated retirement schedule per model version and per SKU, which
    #: is one of the four grounds D-449 retains Azure on and which this whole file exists to
    #: consume. OpenAI publishes deprecations on a page this environment cannot open
    #: (`platform.openai.com` → egress-blocked, measured 22 Aug 2026), so the honest state on
    #: that leg is UNREAD rather than "none exists" — and inventing a far-off date to satisfy
    #: a `date` annotation would be exactly the D-31/D-32 error class, a guess wearing the
    #: shape of a fact. An undated model may not be selectable
    #: (`check_model_lifecycle.refusals`), so the gap cannot reach a call; it warns on every
    #: run naming the URL that closes it.
    retires_on: date | None
    #: The vendor's own word: GA · Legacy · Deprecated · Retired · or "unread".
    stage: str
    #: What the vendor names as the migration target, or None when there is none published.
    replacement: str | None
    offered_in_region: frozenset[DeploymentType]
    retirement: Evidence
    availability: Evidence

    @property
    def deployment_types_apply(self) -> bool:
        """Does this leg have deployment types at all? Azure alone."""
        return self.provider == "azure_openai"

    @property
    def offered_on_mandated_type(self) -> bool:
        return MANDATED_DEPLOYMENT_TYPE in self.offered_in_region

    def days_left(self, today: date) -> int | None:
        """Days until the vendor turns it off, or `None` when no date has been read.

        `None` RATHER THAN A SENTINEL INT, because every caller has to branch anyway and a
        large positive number would read as "safe for years" in exactly the reports this
        module exists to make honest.
        """
        return None if self.retires_on is None else (self.retires_on - today).days


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

#: THE CATALOGUE'S LIFECYCLE, keyed by the same identifiers as `LLM_MODEL_NAMES` — every
#: model on every declared leg, selectable or not.
#:
#: KEYED BY MODEL AND NOT BY THE `Literal`s, for `LLM_MODELS`' reason: a model identifier
#: read back off a historical `usage_events` row is not a member of today's allow-list and
#: never will be again, and asking "when did that retire" about a leg that already ran is a
#: legitimate question. What that costs is a check the type cannot make — a model added to
#: one of the three `Literal`s without an entry here — and `scripts/check_model_lifecycle.py`
#: REFUSES rather than passes when the two disagree, in either direction.
#:
#: **IT COVERS THE MODELS NOBODY MAY SELECT, AND THAT IS THE POINT RATHER THAN AN
#: OVERSIGHT.** Four of the six entries are `selectable=False` in `LLM_MODELS`: the two
#: Gemini models on merit, the two OpenAI models on a price nobody here has read. A dated
#: entry for a model nobody can choose is what turns a refusal into a CHECKED fact — the
#: Gemini retirement is 55 days out as this is written, and the day it passes this file is
#: what says so, in a run, rather than a paragraph somebody has to remember to re-read.
#: `check_model_lifecycle` FAILS on a retired SELECTABLE model and WARNS on a retired
#: withdrawn one, which is the only split that keeps both halves honest: a countdown to a
#: day nobody can act on is what D-410 deleted, and a countdown nobody is running is what
#: put a dead model in two call sites before that.
MODEL_LIFECYCLE: Final[dict[str, ModelLifecycle]] = {
    "gpt-4o-mini": ModelLifecycle(
        model="gpt-4o-mini",
        provider="azure_openai",
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
        provider="azure_openai",
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
    # --- THE OPENAI-DIRECT LEG: UNDATED, AND THE ABSENCE IS THE FINDING ---------------
    #
    # Both entries carry `retires_on=None`. That is not a gap somebody forgot to fill: it is
    # the concrete form of one of D-449's four grounds for keeping Azure. Microsoft publishes
    # a dated retirement schedule per model version and per SKU, in a git repository this
    # environment can read at a named commit; OpenAI publishes deprecations on a page every
    # egress path here refuses. So on this leg the honest answer to "when does it stop
    # answering" is nobody here knows, and `check_model_lifecycle` says so on every run
    # rather than letting a green line imply otherwise.
    "gpt-5.4-mini": ModelLifecycle(
        model="gpt-5.4-mini",
        provider="openai",
        version="unread",
        retires_on=None,
        stage="unread",
        replacement=None,
        # EMPTY BECAUSE THE CONCEPT DOES NOT EXIST HERE, not because the matrix omits it.
        # There are no deployments on this leg, so there is no SKU for a model to be offered
        # on and no per-region matrix to read — see `ModelLifecycle.deployment_types_apply`.
        offered_in_region=frozenset(),
        retirement=Evidence(
            source="platform.openai.com/docs/deprecations (NOT READ — egress-blocked)",
            read_on=_READ_ON,
            verified=False,
            note=(
                "openai.com, platform.openai.com and help.openai.com are all refused by "
                "this environment's egress proxy (measured 22 Aug 2026, "
                "docs/evidence/llm-provider-postures.md §0.2), so no OpenAI retirement page "
                "was read at its own URL. No date is invented here. Closed by a human on an "
                "unblocked network; until then this model cannot be selectable."
            ),
        ),
        availability=Evidence(
            source="bolna-findings/mirror/pages/providers/llm-model/openai.md:38-51",
            read_on=_READ_ON,
            verified=True,
            note=(
                "VERIFIED-VENDOR-DOCS, hash-checked mirror: the engine's own supported-model "
                "table lists it and marks it 'Recommended: fastest TTFT, lowest cost' (:46). "
                "⚠ That recommendation has no measured number behind it — the vendor's own "
                "latency page (concepts/latency.md:64-69) measures no GPT-5 model at all and "
                "ties gpt-4.1-mini with gemini-2.5-flash at ~150ms. AVAILABILITY here means "
                "the engine will accept the identifier, which is the only availability "
                "question a leg with no regions and no deployments has."
            ),
        ),
    ),
    "gpt-5.6-luna": ModelLifecycle(
        model="gpt-5.6-luna",
        provider="openai",
        version="unread",
        retires_on=None,
        stage="unread",
        replacement=None,
        offered_in_region=frozenset(),
        retirement=Evidence(
            source="platform.openai.com/docs/deprecations (NOT READ — egress-blocked)",
            read_on=_READ_ON,
            verified=False,
            note="Same blocked host as gpt-5.4-mini; no date is invented here either.",
        ),
        availability=Evidence(
            source="bolna-findings/mirror/pages/providers/llm-model/openai.md:38-51",
            read_on=_READ_ON,
            verified=True,
            note=(
                "VERIFIED-VENDOR-DOCS: listed on the engine's OpenAI page and ABSENT from "
                "its Azure page (azure-openai.md:38-47). That asymmetry is the vendor's own "
                "'Azure has a short lag' (:90) as a concrete difference rather than a "
                "slogan, and it is the reason a second leg buys reach and not only a second "
                "bill. VERIFIED-OSS, bolna/constants.py:329 @ 0172347b601e: its "
                "reasoning-effort map includes `none`, so the reasoning budget can be zeroed."
            ),
        ),
    ),
    # --- THE GOOGLE LEG: DATED, 55 DAYS OUT, AND SELECTABLE BY NOBODY -----------------
    #
    # These two are the reason `check_model_lifecycle` had to learn the difference between a
    # retired SELECTABLE model (a build failure — an operator can flip a switch onto it) and
    # a retired withdrawn one (a warning — the entry is the dated record of WHY it is
    # withdrawn, and deleting it on the day it expires would delete the evidence). D-410
    # removed the last dated constant from this repository and recorded that as a benefit;
    # these rows put a date back, on models nobody may run, which is the only shape that
    # benefit survives in.
    "gemini-2.5-flash": ModelLifecycle(
        model="gemini-2.5-flash",
        provider="google",
        version="2.5",
        retires_on=date(2026, 10, 16),
        stage="Deprecated",
        replacement="gemini-3.6-flash",
        offered_in_region=frozenset(),
        retirement=Evidence(
            source="docs/evidence/gemini-direct-api.md §4.1",
            read_on=_READ_ON,
            verified=False,
            note=(
                "REPORTED: every ai.google.dev host is egress-blocked here, so this is search "
                "summaries of Google's release notes rather than the vendor's page. ⚠ GOOGLE'S "
                "OWN PAGES DISAGREE BY FOUR DAYS — 16 Oct in release notes, 20 Oct on the "
                "lifecycle page — and the EARLIER date is carried, because a retirement guard "
                "that rounds toward the vendor's slower page is a guard that warns after the "
                "outage. The named replacement, gemini-3.6-flash, is global-only with no data "
                "residency and takes a non-zero thinking level with no way to reach zero, "
                "which is why this is a dead end rather than a migration."
            ),
        ),
        availability=Evidence(
            source="bolna-findings/mirror/pages/providers/llm-model/gemini.md:34-43",
            read_on=_READ_ON,
            verified=True,
            note=(
                "VERIFIED-VENDOR-DOCS: the engine lists it and marks it 'Recommended — "
                "proven, stable, fast'. The engine will accept the identifier; what it will "
                "not do is let us set a thinking budget, which is the trap recorded at "
                "calevate_shared.engine.THINKING_TOKENS_SHARE_THE_REPLY_BUDGET."
            ),
        ),
    ),
    "gemini-2.5-flash-lite": ModelLifecycle(
        model="gemini-2.5-flash-lite",
        provider="google",
        version="2.5",
        retires_on=date(2026, 10, 16),
        stage="Deprecated",
        replacement="gemini-3.1-flash-lite",
        offered_in_region=frozenset(),
        retirement=Evidence(
            source="docs/evidence/gemini-direct-api.md §4.1",
            read_on=_READ_ON,
            verified=False,
            note=(
                "REPORTED, and WEAKER THAN ITS SIBLING'S BY ONE STEP WORTH NAMING: the source "
                "dates 'gemini-2.5-pro and gemini-2.5-flash' explicitly and treats -flash-lite "
                "as part of the same retiring family ('gemini-2.5-flash/-lite ... retires in "
                "~8 weeks') without naming it in the sentence carrying the date. So this row's "
                "date is an INFERENCE from the family, not a reading of this identifier, and "
                "it is recorded as one. It fails in the safe direction — an early warning on a "
                "model nobody may select — and the same human opening "
                "ai.google.dev/gemini-api/docs/pricing settles it."
            ),
        ),
        availability=Evidence(
            source="bolna-findings/mirror/pages/providers/llm-model/gemini.md:34-43",
            read_on=_READ_ON,
            verified=True,
            note=(
                "VERIFIED-VENDOR-DOCS: listed by the engine, and named beside gpt-4.1-mini as "
                "a low-TTFT choice on the engine's own latency page (concepts/latency.md:127) "
                "— which is the strongest thing anybody can say for this leg and is still not "
                "enough to outweigh a retirement 55 days out."
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


# `Evidence` IS DELIBERATELY ABSENT FROM `__all__` even though this module names it in every
# entry below: it is `calevate_shared.engine`'s record now, and re-exporting it here would
# give one type two import paths — the drift this repository calls a defect even when both
# work. Importers take it from the contract.
__all__ = [
    "ATTESTATION_PATH",
    "DEPLOYMENT_TYPES",
    "MANDATED_DEPLOYMENT_TYPE",
    "MODEL_LIFECYCLE",
    "WARN_LEAD",
    "Attestation",
    "DeploymentType",
    "ModelLifecycle",
    "load_attestation",
]
