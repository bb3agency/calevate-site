"""WHICH LANGUAGE MODEL A CLIENT'S AGENTS RUN, and who chose it.

THE THREE LEVELS, and the reason the answer always carries its SOURCE
---------------------------------------------------------------------
`agents.llm_model` -> `organizations.default_llm_model` -> the platform's own model.
A resolver that returned only the string would make "we picked this for you" and "you
picked this" the same answer on the screen, and the two are different facts a client
acts differently on: one is a setting they can clear, the other is a default they can
override. So `resolve_llm_model` returns `ResolvedLlmModel`, never a bare `str`, and
every response that carries the model carries the level it came from beside it.

THE PLATFORM LEVEL IS `Settings.azure_openai_model`, NOT `AZURE_OPENAI_DEFAULT_MODEL`
-------------------------------------------------------------------------------------
The constant is the DEFAULT OF that setting, not the platform's answer. `azure_openai_
model` is `applies: live` (`core/platform_config.py`) — an operator flips it, points the
deployment at a matching model, and from that moment the model this deployment actually
runs is the setting's value. Reading the frozen constant here would report `gpt-4o-mini`
to every client on a deployment running `gpt-4.1-mini`: the D-105 defect (an identifier
changing under a constant nobody re-derived) on the surface that tells a client what
their calls cost. On an unflipped deployment the two are the same string, which is why
this is strictly more correct rather than differently correct.

THREE CONDITIONS DECIDE WHAT A CLIENT MAY PICK, AND ONLY ONE OF THEM IS IN SOURCE
---------------------------------------------------------------------------------
This module used to state one question — is the model in `AZURE_OPENAI_MODELS` and does
this platform have a deployment for it — because there was one leg and one vendor. The
product now offers three legs (Azure OpenAI, OpenAI direct, Google Gemini), the founder
holds all three accounts and installs all three keys, and "what may this client choose"
became a conjunction of three facts with three different owners:

1. **`selectable`** — this repository permits the model on merit: the engine supports the
   identifier, its request-field traps are ones we mitigate at the wire, and it sits in the
   per-minute cost tier a voice product can carry. A reviewed commit; lives in
   `calevate_shared.engine.LLM_MODELS`.
2. **The leg is addressable here** — a credential for the provider, and on Azure ALSO a
   deployment, because Azure alone addresses an operator-chosen deployment id that can
   never be derived from a model name.
3. **The price is billable** — an operator has attested what this account actually pays,
   or the catalogue figure was read from the vendor. `billing/rates.py` owns it.

`offerable_models()` is the ONE predicate that ANDs them, and every surface reads it: the
picker, `validate_llm_model`, the publish path and the rate card. `unofferable_reason()`
says which condition failed, in one sentence an operator can act on, because the three
have three different fixes — a portal deployment, a pasted key, an invoice figure — and a
screen that could not tell them apart would send all three to support.

⚠ A FUNCTION, NEVER A CONSTANT, and that is load-bearing rather than stylistic. Two of the
three conditions are live properties of a deployment: a key installed at 14:00 and a price
attested at 14:05 change the answer twice with no release. A module-level frozenset would
be computed at import and would answer for the process's first second forever — which is
exactly how a picker comes to offer a model the publish path then refuses.

⚠ THE MENU MAY NOT CONTAIN A DISH THE KITCHEN CANNOT COOK
---------------------------------------------------------
Condition (2) is not a nicety on the Azure leg. `gpt-4.1-mini` costs 2.7x `gpt-4o-mini`,
and a picker that offered it while the wire kept addressing the default deployment would
quote and meter a client at the dearer rate for calls that ran the cheaper model — a
charge for something we did not deliver, invisible in a transcript, invisible in an
execution payload, and a hard-rule-7 defect rather than a cosmetic one.

Condition (3) is the same failure one step earlier and is why the PICKER is gated rather
than only the wire: `llm_inr_per_ktok` raises on a model nobody priced, so a selection we
accepted would surface that raise on a metering path AFTER the call was placed — a minute
delivered, a vendor billed, and nothing our ledger can charge for. Refusing the selection
is the only place the failure is free.

WHERE THE DEPLOYMENTS COME FROM, and why it is two fields rather than one:
`Settings.azure_openai_deployment` is the deployment for `Settings.azure_openai_model` —
the pair `config.py` already required to move together, and the value pushed to the
engine's own credential store — and `Settings.azure_openai_deployments` carries the
others as `model=deployment` pairs. `deployment_for()` below is the only reader of
either, so "which deployment serves this model" has one answer and one place.

ON A DEPLOYMENT WITH NO AZURE CREDENTIALS AT ALL — local, CI, any staging without a
resource — there is no deployment indirection: `in_call_llm` passes the model straight
to the engine, so every Azure-catalogue model is addressable and the picker offers them
all. That is not a special case bolted on; it is the same question ("can this deployment
put this model on the wire?") answered for the other arm of the same switch. The other two
legs have no such arm: their credential lives in the engine's own store and there is
nothing to fall back to.

WHAT THIS MODULE STILL DOES NOT DO, on purpose: it holds no key, stores no attestation and
reads no database. The ops console owns both (`apps/api/ops/`), and reaches this module
through exactly two installed functions — `install_llm_credential_reader` here and
`billing/rates.install_llm_price_attestations` — so a rate card and a picker stay
exercisable without a database and the money module never imports the console.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal, get_args

from calevate_shared.engine import (
    LLM_MODELS,
    SELECTABLE_LLM_MODELS,
    LlmProvider,
    leg_for_model,
)

from apps.api.billing.rates import (
    PRICED_LLM_MODELS,
    is_surchargeable_llm_model,
    llm_cost_inr_per_minute,
    llm_price_is_billable,
)
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings

# THE ONE READER OF THE THREE `azure_openai_*` CREDENTIAL FIELDS, imported rather than
# re-derived — the same import `agents/service.py` makes and for the identical reason. It
# answers "does this deployment have an Azure leg at all", which is the question that
# decides whether a model needs a deployment to be addressable or goes to the engine
# verbatim. A second read here would be a second definition of "configured".
from apps.workers.extraction import TenantModelLeg, azure_credentials

#: WHICH LEVEL SUPPLIED THE MODEL. A closed vocabulary rather than a `str`, for
#: `AgentDirection`'s reason (D-440): it is compared against, returned to a browser and
#: switched on by a generated TypeScript client, and a fourth level would have to be
#: added to the type before it could be returned.
LlmModelSource = Literal["agent", "organization", "platform"]

#: The same three as a value — `get_args` on the Literal, never a second tuple beside it
#: (D-104). Read by the tests that enumerate the levels.
LLM_MODEL_SOURCES: Final[tuple[LlmModelSource, ...]] = get_args(LlmModelSource)

#: WHO a "why this model cannot be chosen" sentence is written for.
#:
#: The two audiences need DIFFERENT language for the SAME unavailable model, and that is a
#: correction of a prior design that gave them one sentence. An OPERATOR (admin console, ops
#: console) needs the actionable ground — a missing key, an un-created deployment, an
#: unattested price — because fixing it is theirs and the three fixes are three different
#: five-minute jobs. A CLIENT has no ops console, no vendor portal and no keys; the ground is
#: not a thing they can act on, and printing it ("install the provider's key in the ops
#: console") tells them to do something impossible. So a client is told the one true thing
#: they CAN act on: the model is not on their account yet, and their Calevate team enables it.
#:
#: The split is chosen at the ROUTE by realm, not inferred from a role: the client realm's
#: reader asks for `"client"` and the admin realm's for `"operator"`, so an operator viewing
#: a client's own screen under impersonation (read-only, D-22) sees exactly what the client
#: sees, which is the point of that view.
LlmReasonAudience = Literal["operator", "client"]

#: The call length the per-minute figure on the selection screen is struck at.
#:
#: A REFERENCE LENGTH IS REQUIRED AND CANNOT BE OMITTED, because the in-call LLM cost is
#: NOT constant per minute: TRD §6.1 resends the whole conversation on every turn, so
#: input cost grows quadratically with duration and `llm_cost_inr_per_minute` takes the
#: length for exactly that reason. Five minutes is the length TRD §10.1 publishes its own
#: per-model rows at, so the figure a client sees on this screen and the figure the
#: margin model reasons from are the same figure — which they would not be if this screen
#: quoted minute one.
QUOTED_CALL_MINUTES: Final = 5


@dataclass(frozen=True)
class ResolvedLlmModel:
    """The model an agent will run, and the level that supplied it.

    Frozen and two-field rather than a bare string: "never a silent default" is only
    enforceable if the answer physically cannot be handed on without its provenance.
    """

    model: str
    source: LlmModelSource


@dataclass(frozen=True)
class SelectableModel:
    """One row of the model picker: what it is, who serves it, what a minute costs, and
    whether this deployment can actually run it.

    `inr_per_minute` is a `Decimal` here and becomes a STRING at the HTTP boundary (hard
    rule 7): a JSON float cannot hold a rupee amount exactly, and a price that arrives in
    a browser as `0.30000000000000004` is a number nobody can reconcile against an
    invoice.

    AN UNRUNNABLE MODEL IS PRESENT AND MARKED, NOT OMITTED, and that is a deliberate
    departure from "just filter the list". A missing row tells an operator nothing; a row
    that says *why* tells them the one thing they can act on — that this model needs an
    Azure deployment and an entry in `Settings.azure_openai_deployments`. It cannot be
    SELECTED either way (`validate_llm_model` refuses it), so the client-facing behaviour
    is the same and the operator-facing behaviour is the difference between a bug report
    and a five-minute fix.
    """

    model: str
    provider: LlmProvider
    inr_per_minute: Decimal
    is_platform_default: bool
    #: **Does CHOOSING this model add the plan's per-minute surcharge to the client's
    #: bill?** (D-455.) A property of the MODEL and not of the tenant — what the surcharge
    #: IS lives on `plans.llm_model_surcharge`, and this catalogue deliberately reads no
    #: database. The route pairs the two, so one place decides which models are upgrades
    #: and one place holds the price of an upgrade.
    #:
    #: False for `rates.BASE_RATE_LLM_MODEL`, which is the model every plan's per-minute
    #: rate is struck at — and note it is NOT keyed on `is_platform_default`: an operator
    #: flipping `Settings.azure_openai_model` must not silently re-classify what an
    #: account is billed for, which is the same frozen-baseline argument
    #: `BASE_RATE_LLM_MODEL` carries.
    is_surcharged: bool
    #: Can this deployment actually put this model on the wire? Everything the API does
    #: with a model choice keys off this, never off allow-list membership alone.
    is_available: bool
    #: Why not, in words an operator can act on — `None` exactly when `is_available`.
    unavailable_reason: str | None


def selectable_models() -> tuple[str, ...]:
    """Every model this repository PERMITS ON MERIT, sorted. NOT the picker's list.

    Sorted so the order is stable across interpreter runs — `SELECTABLE_LLM_MODELS` is a
    frozenset, whose iteration order is not, and an unstable order here would make the
    OpenAPI snapshot and the screen shuffle for no reason.

    ⚠ **THIS IS CONDITION (1) OF THREE.** What a client may actually choose is
    `offerable_models()`; see this module's docstring. A surface stated over this function
    alone would offer a model with no key behind it and no price anybody has attested.
    """
    return tuple(sorted(SELECTABLE_LLM_MODELS))


def platform_default_model() -> str:
    """What an account runs when neither it nor its agent chose — see the module docstring
    for why this is the live setting and not the frozen constant behind it."""
    return get_settings().azure_openai_model


def _configured_deployments() -> dict[str, str]:
    """`Settings.azure_openai_deployments` parsed: `{model: deployment_id}`.

    NO FAILURE BRANCH, and that is a property of the field rather than optimism: its
    `pattern` admits only empty or `model=deployment` pairs joined by commas, and pydantic
    enforces it at the console write path, at the boot-time load and on every snapshot
    rebuild. So by the time a value reaches this function it has the shape, and a `try`
    here would be a branch nothing can reach — the kind that shows up as an uncovered
    suppression rather than as safety.

    A later duplicate key wins, which is what `dict` does and what an operator correcting
    a line by appending would expect.
    """
    raw = get_settings().azure_openai_deployments.strip()
    if not raw:
        return {}
    deployments: dict[str, str] = {}
    for entry in raw.split(","):
        # `partition` rather than `split("=", 1)`: it always yields three strings, so the
        # unpacking is total and mypy needs no help believing it — where `split` returns a
        # list whose length only the field's `pattern` guarantees.
        model, _, deployment = entry.partition("=")
        deployments[model] = deployment
    return deployments


def deployment_for(model: str) -> str | None:
    """The Azure deployment id serving `model`, or `None` if this platform has none.

    THE ONE READER OF BOTH DEPLOYMENT FIELDS. `Settings.azure_openai_deployment` answers
    for `Settings.azure_openai_model` and `Settings.azure_openai_deployments` answers for
    everything else, so no model is named in two places and the two can never disagree
    about one model. The order matters and is the whole rule: the singular field is what
    `engine/bolna.py` pushes into the vendor's credential store as `AZURE_OPENAI_MODEL`,
    so if a stray entry in the map ever named the platform's own model, letting the map
    win would point published agents at one deployment and the credential store at
    another. It is ignored instead.

    ⚠ **ASK IT ONLY ABOUT AN AZURE MODEL.** Deployments are an Azure artefact; on the other
    two legs the API addresses the model's own published name and a deployment id has
    nowhere to go (`calevate_shared.engine.bind_model` raises on one). A Gemini identifier
    reaching here would find nothing and read as "not deployed", which is a true sentence
    about a question that does not apply — `_leg_is_addressable` is what keeps the question
    where it belongs.

    Blank-stripping both sides rather than trusting them: `azure_openai_deployment` is
    `str | None` and an operator clearing it in the console leaves `""`, which is not a
    deployment and must not be returned as one.
    """
    if model == platform_default_model():
        return (get_settings().azure_openai_deployment or "").strip() or None
    return (_configured_deployments().get(model) or "").strip() or None


# --- WHICH LEGS THIS PLATFORM HOLDS A CREDENTIAL FOR ---------------------------------
#
# **THE CONTRACT, NOT THE STORE.** The founder holds all three vendor accounts and enters
# all three keys in the ops console; `apps/api/ops/` owns where those keys live, who may
# write one and what the form looks like. This module owns the QUESTION — which legs are
# usable right now — and the seam between them is one installed function, for the reason
# `billing/rates.install_llm_price_attestations` gives at length: the picker must not
# import the console, and it must stay exercisable without a database.

#: A function returning every leg whose credential this platform holds. Installed by ops.
LlmCredentialReader = Callable[[], frozenset[LlmProvider]]

_credential_reader: LlmCredentialReader | None = None


def install_llm_credential_reader(reader: LlmCredentialReader | None) -> None:
    """Register where installed-credential state comes from. `None` uninstalls.

    The sibling of `billing/rates.install_llm_price_attestations`, deliberately the same
    shape: the two facts an operator supplies (a key and a price) arrive through two
    functions with one pattern rather than through two mechanisms. Read that function's note
    on wiring — the reader is synchronous and closes over a refreshed snapshot, because its
    callers sit behind a picker and on a publish path and none of them can await.
    """
    global _credential_reader
    _credential_reader = reader


def installed_llm_providers() -> frozenset[LlmProvider]:
    """The legs this platform can actually put a call on today.

    **WITH NO READER INSTALLED THE ANSWER IS DERIVED FROM `Settings`, AND IT IS AZURE-ONLY.**
    That is not a placeholder: it reproduces exactly what this repository did before there
    was a second leg, so CI, every unit test and any deployment whose console has not been
    filled in behave as they always have. The other two legs are simply not usable until
    somebody installs a key, which is the honest state and the one the picker should show.

    ⚠ **AZURE IS PRESENT ON *BOTH* ARMS OF `azure_credentials()`, AND THAT IS NOT A BUG.**
    A deployment with no Azure credentials at all has no Azure leg to configure — and on
    that arm `in_call_llm` sends the model identifier straight through to the engine's own
    default client, which is the passthrough every conformance fixture and every local run
    exercises. So "can this platform run an Azure-catalogue model" is true either way, and
    it is `_leg_is_addressable` below that knows the two arms need different questions
    asked of them.
    """
    if _credential_reader is not None:
        return _credential_reader()
    return frozenset({"azure_openai"})


def _leg_is_addressable(model: str) -> bool:
    """Can this platform put `model` on the wire at all — credential AND, on Azure, a
    deployment?

    TWO QUESTIONS, ONE PER LEG SHAPE, because the legs genuinely differ in what "configured"
    means and collapsing them would make one of the two answers wrong:

    * **Azure addresses a DEPLOYMENT ID an operator chose** (`PostureLeg.addresses_a_
      deployment`), which can never be derived from the model name. So a key is not enough:
      a model with no deployment would be quoted at its own price while every call ran a
      different deployment — a charge for something we did not deliver, invisible in a
      transcript and in an execution payload, and a hard-rule-7 defect rather than a
      cosmetic one. On the no-credentials arm there is no deployment indirection at all, so
      the model IS what the engine is sent and every catalogue model is addressable.
    * **OpenAI and Google address the model's own published name.** There is nothing to
      configure per model, so the whole question is whether the leg's credential is
      installed — and if it is, every model on it is addressable.
    """
    leg = leg_for_model(model)
    if leg.provider not in installed_llm_providers():
        return False
    if not leg.addresses_a_deployment:
        return True
    if azure_credentials() is None:
        return True
    return deployment_for(model) is not None


#: Why a permitted model cannot be offered here — ONE sentence per ground, keyed by the
#: ground. Read by the API response and by the refusal, so an operator and a client are told
#: the same thing about the same model.
#:
#: **THREE GROUNDS AND THEY HAVE THREE DIFFERENT OWNERS**, which is the whole reason they are
#: separate strings rather than one "unavailable". "No deployment" is an operator's five
#: minutes in the Azure portal; "no credential" is a key the founder pastes into the ops
#: console; "no attested price" is a figure read off an invoice. A screen that could not tell
#: them apart would send all three to support.
NO_DEPLOYMENT_REASON: Final = (
    "no Azure deployment is configured for this model on this platform, so it cannot be "
    "addressed — create a deployment for it and add a `model=deployment` entry to "
    "azure_openai_deployments"
)
NO_CREDENTIAL_REASON: Final = (
    "this platform holds no API key for the provider that serves this model, so a call on it "
    "would authenticate against nothing — install the provider's key in the ops console"
)
NO_ATTESTED_PRICE_REASON: Final = (
    "nobody has recorded what this model costs on this account, and an unpriced minute is "
    "unmetered spend rather than a free one — enter the input and output price from the "
    "vendor invoice in the ops console"
)

#: Kept under its old name because two guards and a doc quote it; it is the Azure ground.
UNAVAILABLE_REASON: Final = NO_DEPLOYMENT_REASON

#: THE ONE SENTENCE A CLIENT SEES for any unavailable model, whichever of the three grounds
#: failed. The grounds are collapsed on purpose: a client cannot install a key, create a
#: deployment or attest a price, so the distinction that is load-bearing for an operator is
#: noise to them — the only true action they have is to ask us. Phrased with no leading dash
#: and no internal em-dash so it completes both "Cannot be chosen — {…}" on the picker and
#: "…is a model this platform supports, but {…}. Until it is, …" in the validator refusal.
CLIENT_UNAVAILABLE_REASON: Final = (
    "it isn't switched on for your account yet; ask your Calevate team to enable it"
)


def _operator_unofferable_reason(model: str) -> str | None:
    """The OPERATOR ground — which of the three conditions failed, named so an operator can
    act on it. `unofferable_reason` is the audience-aware wrapper; this is its truth.

    **THE ONE PLACE THE THREE CONDITIONS ARE ORDERED**, and the order is by whose problem it
    is rather than by cost: a leg with no key cannot be fixed by attesting a price, so the
    key is reported first and the reader is sent to one action at a time. A model failing two
    conditions gets the earlier sentence, which is the one that has to happen first anyway.

    Raises through `leg_for_model` on an identifier the catalogue does not know — deliberately
    the same refusal `bind_model` makes, because a model with no leg has no credential to
    check and no price to attest, and answering "not offered" would imply the question made
    sense.
    """
    if model not in SELECTABLE_LLM_MODELS:
        spec = LLM_MODELS.get(model)
        # A withdrawn model carries its own sentence and it is a better one than any generic
        # phrasing here: it names the trap, the price or the unread page that withheld it.
        return (spec.withdrawn_reason if spec else None) or "this platform does not run it"
    leg = leg_for_model(model)
    if leg.provider not in installed_llm_providers():
        return NO_CREDENTIAL_REASON
    if not _leg_is_addressable(model):
        return NO_DEPLOYMENT_REASON
    if not llm_price_is_billable(model):
        return NO_ATTESTED_PRICE_REASON
    return None


def unofferable_reason(model: str, *, audience: LlmReasonAudience = "operator") -> str | None:
    """Why `model` cannot be offered here, or `None` when it can — in the AUDIENCE's language.

    `None` MEANS THE SAME THING FOR BOTH AUDIENCES: offerability is one fact, so this returns
    `None` for exactly the offerable models whichever audience asks. Only the SENTENCE for an
    unavailable model differs — the operator gets the ground they can fix, the client gets the
    one action they have (`CLIENT_UNAVAILABLE_REASON`; see `LlmReasonAudience`). Keeping the
    None-ness audience-independent is what lets `available_models` derive `is_available` from
    the reason without the flag and the sentence ever disagreeing.

    Default `"operator"` so every existing caller — the guards, the publish path, `offerable_
    models`, the tests — keeps its current behaviour unchanged; the client realm opts in.
    """
    reason = _operator_unofferable_reason(model)
    if reason is None or audience == "operator":
        return reason
    return CLIENT_UNAVAILABLE_REASON


def offerable_models() -> frozenset[str]:
    """**THE ONE PREDICATE BEHIND THE MENU, THE VALIDATOR, THE PUBLISH PATH AND THE RATE
    CARD.** Every model a client or an operator may actually choose right now.

    Three conditions, ANDed, each owned by somebody different (`LlmModelSpec`'s docstring
    states them; `unofferable_reason` above names them one at a time):

    1. this repository permits it on merit — `selectable`, a reviewed commit;
    2. its leg is addressable here — a credential, and on Azure a deployment;
    3. its price is billable — an operator's attestation, or a catalogue figure somebody
       read from the vendor.

    **WHY A FUNCTION AND NOT A CONSTANT**, which is the load-bearing part. Two of the three
    conditions are live properties of a deployment: a key installed at 14:00 and a price
    attested at 14:05 change this set twice without a release. A module-level frozenset would
    be computed at import and would answer for the process's first second forever — which is
    exactly how a picker comes to offer a model the publish path then refuses.

    ⚠ **CONDITION 3 IS HARD RULE 7 AND IT IS WHY THIS SET GATES THE PICKER RATHER THAN ONLY
    THE WIRE.** `llm_inr_per_ktok` raises on an unpriced model; if a client could SELECT one,
    the raise would land on a metering path after the call was already placed — a minute
    delivered, a vendor billed and nothing our ledger can charge for. Refusing the selection
    is the only place the failure is free.
    """
    return frozenset(model for model in SELECTABLE_LLM_MODELS if unofferable_reason(model) is None)


# --- MAY THE DASHBOARD ASSIST RUN ON THIS LEG? ---------------------------------------
#
# **A DIFFERENT QUESTION FROM `selectable`, GOVERNED BY A DIFFERENT REGIME, AND THE PLACE
# THIS REPOSITORY PREVIOUSLY CONTRADICTED ITSELF.** Everything above this line answers "may
# a client CHOOSE this model for their phone agents" — the IN-CALL leg. What follows answers
# "may the DASHBOARD assistant run on this model's provider", and the two do not imply each
# other in either direction.
#
# The contradiction, recorded rather than resolved here, because resolving it is not this
# module's to do (D-477, OPERATIONS §2 gate 41):
#
#   * `calevate_shared/config.py`'s `gemini_api_key` comment bars the Google AI Studio
#     Developer API from the DASHBOARD leg, on a stated ground about free-tier data use.
#   * `calevate_shared/engine.py`'s `GoogleDirectModel` block permits two Gemini models on
#     the IN-CALL leg on entirely different grounds — the thinking-budget trap being
#     eliminated, and price — and does not mention data use at all.
#
# ⚠ **NOTHING HERE ASSERTS A VENDOR'S TERMS AS A FIRST-HAND FINDING, AND THE EVIDENCE CLASS
# IS THE POINT.** `ai.google.dev`, `policies.google.com`, `aistudio.google.com` and
# `platform.openai.com` are all egress-blocked from this environment (re-measured
# 27 Aug 2026), so no vendor-owned page about either data-use position has been read from
# here. What is held for Google is **SECONDARY** — two independent third-party verbatim
# mirrors of the Gemini API Additional Terms, captured ten months apart and agreeing almost
# word for word, relayed into this tree: the unpaid tier uses submitted content to improve
# Google products with human reviewers able to read it, and instructs developers not to
# submit personal information to it. That class is strong enough to keep the leg SHUT and is
# not strong enough to open it (hard rule 11), which is exactly the direction this code
# takes. For OpenAI there is nothing at all, and `DASHBOARD_TERMS_UNREAD` says so.
#
# So what is built is the MECHANISM, with the account-level question as an explicit OPERATOR
# ATTESTATION — the pattern this repo already uses twice, for the LLM price
# (`ops/model_pricing.AttestedModelPrice`) and for the Azure resource's region (OPERATIONS §2
# gates 20/20c). The founder attests; the code enforces; neither guesses.

#: The legs this repository can actually BUILD a dashboard chat request for.
#:
#: AN ENGINEERING FACT, NOT A COMPLIANCE ONE, and it is separate from eligibility below so
#: that the two never get argued about as one thing. `apps/workers/chat.ChatDialect` is
#: `"openai" | "sarvam"`, and the only dashboard leg any surface constructs is the Azure one
#: (`copilot/service._azure_leg`, `workers/extraction.azure_extractor`,
#: `workers/script_assist._draft_via_azure`). No endpoint for the Google Developer API has
#: been verified from a primary source in this tree, and inventing one would be a wire value
#: taken from memory — the exact class of mistake hard rule 11 and D-417 exist for.
#:
#: ⚠ **ATTESTING A PROVIDER'S DATA-USE POSITION DOES NOT BY ITSELF MOVE THE ASSISTANT ONTO
#: IT.** That is stated on the ops screen too, because `ops/model_pricing.ModelOfferability
#: .withheld_reason` was added for exactly the failure of not stating it: a panel that
#: invites an operator to do a five-minute job which cannot succeed.
DASHBOARD_ADDRESSABLE_PROVIDERS: Final[frozenset[LlmProvider]] = frozenset({"azure_openai"})

#: Legs whose dashboard use is gated on an operator attesting the vendor's data-use terms.
#:
#: `google` is here because the bar on that leg is a data-use ground, and a data-use ground
#: is a question about ONE ACCOUNT'S TIER — which nobody in a repository can answer and an
#: operator with the vendor console can. It is the same shape as the price: a fact about our
#: subscription, attested with provenance, never defaulted.
#:
#: **THE TIER IS A PROPERTY OF THE PROJECT, NOT OF THE KEY, AND THAT IS WHY THE ATTESTATION
#: CAPTURES A PROJECT ID.** Google's live Cloud Billing discovery document
#: (`cloudbilling.googleapis.com/$discovery/rest?version=v1`, revision `20260821`, read
#: 27 Aug 2026 — VENDOR-PUBLISHED) defines `billingEnabled` as "True if the project is
#: associated with an open billing account… False if… therefore cannot use paid services",
#: answered by `projects.getBillingInfo` for a PROJECT ID under an OAuth scope a Gemini API
#: key cannot satisfy. Nothing verifiable maps a key back to its project, so that joint is
#: irreducibly human — the Azure region gate's exact shape. The project id is stored as a
#: first-class column so a later credentialled check has a subject; OPERATIONS §2 gate 41
#: names that as the next step, because a human silently unlinking billing flips the terms
#: the same instant and a quarterly signature is the wrong instrument for it.
DASHBOARD_NEEDS_DATA_USE_ATTESTATION: Final[frozenset[LlmProvider]] = frozenset({"google"})

#: Legs withheld from the dashboard because NOBODY HAS READ THE VENDOR'S POSITION.
#:
#: **`openai` IS HERE AND THE DIRECTION IS FAIL-CLOSED, WHICH IS THE WHOLE ANSWER.** The
#: task of deciding it was taken deliberately rather than by omission: OpenAI's own pages are
#: egress-blocked from this environment, no primary source about their API data-use position
#: was read this session, and `ModelLifecycle.retirement_stance` already teaches the
#: distinction this repository needs — "the vendor says nothing" is not "nobody looked", and
#: only the second one is true here. An unread position may not become a permission.
#: Attesting it is NOT the remedy either: an attestation is a reading of a vendor's terms,
#: and moving `openai` out of this set is a reviewed commit that cites what was read.
DASHBOARD_TERMS_UNREAD: Final[frozenset[LlmProvider]] = frozenset({"openai"})

#: A function returning every leg whose data-use terms an operator has attested permit the
#: dashboard assist. Installed by ops, exactly like `LlmCredentialReader` above.
LlmDashboardDataUseReader = Callable[[], frozenset[LlmProvider]]

_data_use_reader: LlmDashboardDataUseReader | None = None


def install_dashboard_data_use_reader(reader: LlmDashboardDataUseReader | None) -> None:
    """Register where dashboard data-use attestations come from. `None` uninstalls.

    The third seam of the same shape as `install_llm_credential_reader` and
    `billing/rates.install_llm_price_attestations`, and deliberately not a fourth mechanism:
    a sync, no-argument reader over an in-process snapshot (`ops/pricing_snapshot.py`), so
    the picker and the assist selector stay exercisable with no database at all.
    """
    global _data_use_reader
    _data_use_reader = reader


def dashboard_data_use_attested() -> frozenset[LlmProvider]:
    """The legs an operator has attested are on a tier the vendor does not train on.

    **WITH NO READER INSTALLED THE ANSWER IS EMPTY, AND EMPTY IS "NOBODY HAS ATTESTED" —
    NEVER "THE OPERATOR SAID NO".** The two are different states and only one of them is a
    finding. `dashboard_leg_reason` reports the absent attestation as an absent attestation,
    which is what an operator can act on; a missing reading rendered as a refusal would be a
    claim about a vendor that nobody made.
    """
    if _data_use_reader is not None:
        return _data_use_reader()
    return frozenset()


#: THE THREE GROUNDS a leg can be barred from the dashboard assist, one sentence each, for an
#: OPERATOR. Separate strings because they have three different remedies: a console
#: attestation, a reviewed commit citing a vendor page somebody read, and code that does not
#: exist yet. A screen that could not tell them apart would send all three to the same place.
NO_DATA_USE_ATTESTATION_REASON: Final = (
    "nobody has attested that this platform's account with this provider is on a tier where "
    "the vendor does not train on submitted prompts and responses, and that nothing on that "
    "account opts our content back into the free-tier terms — the dashboard assistant sends "
    "a client's screen content, so both answers are needed; record them in the ops console "
    "(for Google, the Billing Tier column on AI Studio's Projects page, and Gemini API "
    "Logs/Datasets sharing OFF)"
)
UNREAD_DASHBOARD_TERMS_REASON: Final = (
    "nobody has read this provider's data-use terms for the dashboard leg from a primary "
    "source, and an unread position is not a permission — read the vendor's page and land "
    "the finding as a reviewed commit, which is not something an attestation can stand in for"
)
NO_DASHBOARD_LEG_REASON: Final = (
    "this repository can build no dashboard chat request for this provider — "
    "workers/chat.ChatDialect speaks openai and sarvam only, and no endpoint for this "
    "provider has been verified from a primary source here"
)

#: THE ONE SENTENCE A CLIENT SEES when their own model's provider cannot serve the assistant.
#:
#: The three grounds are collapsed for `CLIENT_UNAVAILABLE_REASON`'s reason and one more that
#: matters here: not one of them is about the CLIENT'S configuration. Their model works,
#: their agents are running on it, and the limitation is entirely ours — so the only true
#: sentence is the one that says so and does not ask them to do anything.
CLIENT_DASHBOARD_UNAVAILABLE_REASON: Final = (
    "the AI model on your account runs your phone agents, but Calevate cannot yet use it for "
    "the in-app assistant"
)


def dashboard_leg_reason(
    provider: LlmProvider,
    *,
    audience: LlmReasonAudience = "operator",
    attested: frozenset[LlmProvider] | None = None,
) -> str | None:
    """Why the DASHBOARD assist may not run on `provider`, or `None` when it may.

    **THE ORDER IS COMPLIANCE FIRST, ENGINEERING SECOND, AND IT IS NOT ARBITRARY.** A leg
    whose data-use position is unread or unattested must report THAT even if we could build a
    request for it tomorrow: reporting "we have not built the leg" first would let the
    engineering work land and silently clear the only ground that was actually load-bearing.
    The reverse order fails open the moment somebody adds a dialect.

    ⚠ **THE ABSENT ATTESTATION AND THE UNBUILT LEG ARE BOTH REPORTED, IN THAT ORDER, AND
    NEITHER IS HIDDEN BY THE OTHER.** Attesting Google's tier today changes this function's
    answer from the first sentence to the third — which is a real, tested change and the
    reason the attestation is not a field nothing reads — and it does NOT make the leg
    eligible, because `DASHBOARD_ADDRESSABLE_PROVIDERS` is a separate fact. The ops console
    says that in as many words on the attestation form, so nobody is invited to do a job
    that cannot finish (`ModelOfferability.withheld_reason`'s lesson, applied one surface
    over).

    `audience` follows `unofferable_reason`: `None`-ness is audience-independent, because
    eligibility is one fact; only the SENTENCE differs. The default is `"operator"` for that
    function's reason — the admin realm and the guards are the majority of callers here,
    and the client realm opts in.

    **`attested` LETS A CALLER ASK ABOUT STATE IT HAS ALREADY READ, AND THE OPS CONSOLE MUST
    PASS IT.** The default reads the in-process SNAPSHOT (`ops/pricing_snapshot.py`), which
    is what every hot path wants — sync, zero IO, at most one poll interval stale. That
    staleness is invisible on an assist and unacceptable on the attestation screen: an
    operator who has just recorded an attestation and is shown the ground it cleared,
    unchanged, has been told their write did not land. The console reads the store in the
    same request and hands the answer in, so the screen states the STORE's truth while the
    ladder states the snapshot's — which is the honest split, because the ladder really is
    running on the snapshot until it refreshes.
    """
    permitted = dashboard_data_use_attested() if attested is None else attested
    ground: str | None = None
    if provider in DASHBOARD_TERMS_UNREAD:
        ground = UNREAD_DASHBOARD_TERMS_REASON
    elif provider in DASHBOARD_NEEDS_DATA_USE_ATTESTATION and provider not in permitted:
        ground = NO_DATA_USE_ATTESTATION_REASON
    elif provider not in DASHBOARD_ADDRESSABLE_PROVIDERS:
        ground = NO_DASHBOARD_LEG_REASON
    if ground is None or audience == "operator":
        return ground
    return CLIENT_DASHBOARD_UNAVAILABLE_REASON


def dashboard_leg_providers() -> frozenset[LlmProvider]:
    """Every declared leg the dashboard assist may run on right now.

    Derived from `dashboard_leg_reason` over the declared vocabulary rather than written as a
    second set beside it (D-104): a leg that stops being eligible must not be able to stay in
    a constant somebody forgot.
    """
    return frozenset(p for p in get_args(LlmProvider) if dashboard_leg_reason(p) is None)


def tenant_dashboard_leg(*, model: str) -> TenantModelLeg:
    """`model` as the assist selector's tenant half — WITHOUT a database and WITHOUT a cycle.

    A pure function over the identifier the caller already resolved
    (`agents/service.resolved_llm_model`), so this module keeps its "reads no database"
    property and `workers/extraction` keeps its "pure function of its arguments" one. The
    dataclass is defined in `workers/extraction` and constructed here, which is the direction
    that already works: `llm_models` imports that module, never the reverse.

    Raises through `leg_for_model` on an identifier the catalogue does not know — the same
    refusal `bind_model` and `_operator_unofferable_reason` make, and for the same reason: a
    model with no declared leg has no provider whose dashboard position could be asked about,
    so answering "not eligible" would imply the question made sense.
    """
    provider = leg_for_model(model).provider
    reason = dashboard_leg_reason(provider)
    return TenantModelLeg(
        model=model,
        provider=provider,
        serves_dashboard=reason is None,
        blocked_reason=reason,
    )


def resolve_llm_model(
    *, agent_model: str | None, organization_model: str | None
) -> ResolvedLlmModel:
    """The three-level fallback, in ONE place.

    Written as a pure function over two nullable strings rather than as a method on a row
    so that every caller resolves identically: the agent detail route, the publish path
    and the organization screen all ask this, and a second `or` chain spelled at one of
    them is how the screen and the phone line start disagreeing about which model is
    running.

    NO DATABASE ACCESS AND NO ROW TYPE, deliberately. The two values arrive from a query
    the caller already had to run, so taking them as arguments keeps this testable
    without a database and keeps the resolution out of the RLS story entirely — the rows
    were already scoped when they were read.
    """
    if agent_model:
        return ResolvedLlmModel(model=agent_model, source="agent")
    if organization_model:
        return ResolvedLlmModel(model=organization_model, source="organization")
    return ResolvedLlmModel(model=platform_default_model(), source="platform")


def every_selectable_model_is_priced() -> bool:
    """Is every model this repository permits one it can also put a rupee REFERENCE on?

    **STATED OVER `SELECTABLE_LLM_MODELS`, WHICH IS WHAT IT ALWAYS MEANT.** It read
    `PRICED_LLM_MODELS == AZURE_OPENAI_MODELS` while Azure was the only leg anything was
    offered on, and that spelling was a coincidence of the evidence rather than the
    invariant: several tests and documents went on to assert the Azure identity as if it
    were the rule. The rule is that the reference card and the permitted set are the SAME
    SET, in both directions — a permitted model with no reference figure is a blank cell
    where the console's pre-fill should be, and a reference for a model nobody may choose
    is a number that rots unnoticed.

    ⚠ **IT IS NOT THE HARD-RULE-7 CHECK ANY MORE, AND THAT IS A PROMOTION RATHER THAN A
    LOSS.** "Is this model BILLABLE" is a live, per-deployment question — an attestation
    installed this morning changes it — so it cannot be an equality between two module
    constants at all. It is condition (3) of `offerable_models()`, asked per model, and
    `llm_inr_per_ktok` refuses the money outright rather than trusting anyone to have
    checked. This predicate went back to being what its name says.

    A PREDICATE RATHER THAN AN `assert` AT IMPORT, because the two callers want different
    things from the same fact: `tests/llm_model_selection_test.py` wants a named failure,
    and a reader wants one place that states the invariant in words.
    """
    return PRICED_LLM_MODELS == SELECTABLE_LLM_MODELS


def quoted_inr_per_minute(model: str) -> Decimal:
    """What the language leg of a `QUOTED_CALL_MINUTES`-minute call costs per minute, INR.

    Straight through to `billing/rates.py` — this module states no price of its own. The
    rate card is the one place a vendor's dollar figure and the exchange rate it is struck
    at are written down, and a second derivation here would be the D-103 defect on the
    money axis.
    """
    return llm_cost_inr_per_minute(QUOTED_CALL_MINUTES, model=model)


def available_models(*, audience: LlmReasonAudience = "operator") -> tuple[SelectableModel, ...]:
    """The picker's rows, derived from the allow-list and the rate card and nothing else.

    `audience` decides ONLY the wording of `unavailable_reason` on a blocked row — the
    operator's actionable ground or the client's one-action sentence (see `unofferable_
    reason`). `is_available` is the same for both because it is `reason is None` and
    offerability is one fact; the client realm must pass `"client"` so a client never reads
    the operator ground. Default `"operator"` keeps the ops console and every existing
    caller unchanged.

    Raises through `quoted_inr_per_minute` if a model in the allow-list has no price. That
    is deliberate and is the reason there is no `try` here: a picker that silently dropped
    an unpriced model would hide exactly the defect `every_selectable_model_is_priced`
    exists to make loud, and would do it on the screen where a client is choosing what to
    spend.
    """
    default = platform_default_model()
    return tuple(
        SelectableModel(
            model=model,
            # OUR vocabulary for the leg, from the MODEL rather than from the posture as a
            # whole (D-456): the posture now declares three legs, so "which provider" is a
            # property of the model chosen and no longer a property of the product. Still
            # never a literal (D-432) — a leg leaving the declared set must not leave a
            # provider name behind on a screen, and `leg_for_model` raises rather than
            # guessing for a model no declared leg claims.
            provider=leg_for_model(model).provider,
            inr_per_minute=quoted_inr_per_minute(model),
            is_platform_default=model == default,
            is_surcharged=is_surchargeable_llm_model(model),
            # ONE call, not two, and the pair is derived from it: a row whose flag and
            # whose sentence were computed by separate predicates is a row that can say
            # "available" and give a reason why not, which is the shape of a screen nobody
            # can act on.
            is_available=reason is None,
            unavailable_reason=reason,
        )
        for model, reason in (
            (model, unofferable_reason(model, audience=audience)) for model in selectable_models()
        )
    )


def validate_llm_model(
    value: str | None, *, field: str, audience: LlmReasonAudience = "operator"
) -> str | None:
    """`value` if this deployment can actually run it, `None` if it is `None` — else a
    refusal.

    `audience` decides only the WORDING of the `llm_model_not_deployed` refusal's ground —
    the client realm passes `"client"` so a client submitting a blocked model (the picker
    disables it, but a hand-built request can still reach here) is told to ask their Calevate
    team rather than to edit a deployments setting. Default `"operator"` for the admin realm
    and every existing caller.

    **IT CHECKS ADDRESSABILITY, NOT ALLOW-LIST MEMBERSHIP**, and that is the whole point:
    a model this platform has no Azure deployment for would be quoted and metered at its
    own price while every call ran a different deployment, so accepting the selection and
    ignoring it is the one outcome that must not happen (module docstring). The two
    refusals are deliberately DIFFERENT codes — `llm_model_not_available` is "this is not
    a model we run" and `llm_model_not_deployed` is "we run it, but not here yet" — because
    the first is the caller's mistake and the second is an operator's to fix, and a screen
    that could not tell them apart would send a client to support for a config change.

    `None` IS A VALUE HERE AND MEANS INHERIT, which is why this returns `str | None`
    rather than refusing it: clearing an agent's model is how a client goes back to their
    organization default, and clearing the organization's is how they go back to the
    platform's. A route that could only SET would leave a client stuck with the first
    choice they ever made.

    422 problem+json NAMING THE PERMITTED VALUES, not just "invalid": the caller is a
    screen that has to tell somebody what to pick instead, and a refusal that does not
    say what would have worked is a refusal they cannot act on. `fields` carries the
    field name so a form can highlight the input (BACKEND-PATTERNS §3).

    NOT a Pydantic `Literal` on the request model, and this is the rejected alternative
    worth recording: it would validate in the right place but would render the refusal as
    FastAPI's generic 422 with the allow-list buried in a `ctx.expected` string, and — the
    part that decides it — it would bake the allow-list into the OpenAPI schema as an
    enum, so adding a model would silently break every generated client pinned to the old
    union. The allow-list is a live property of the platform, not of the wire contract.
    """
    offerable = offerable_models()
    if value is None or value in offerable:
        return value
    # THE OFFERED SET AND THE REFUSAL'S SET ARE ONE EXPRESSION, so a message can never
    # name a model the write path would then reject.
    permitted = ", ".join(sorted(offerable)) or "none"
    if value in SELECTABLE_LLM_MODELS:
        # A MODEL THIS REPOSITORY PERMITS THAT THIS DEPLOYMENT CANNOT SERVE YET. The
        # reason is one of three and is an OPERATOR'S to fix — a deployment, a key or a
        # price — so it carries its own sentence rather than the Azure-shaped one this
        # branch used to hard-code, which would have told a client to create an Azure
        # deployment for a Gemini model.
        raise ProblemError(
            kind="validation",
            code="llm_model_not_deployed",
            title="That language model is not switched on for this platform yet",
            detail=(
                f"{value!r} is a model this platform supports, but "
                f"{unofferable_reason(value, audience=audience)}. Until it is, the models "
                f"you can choose are: {permitted}."
            ),
            remediation=(
                f"Choose one of {permitted} for now, or ask support to switch "
                f"{value} on for this platform."
            ),
            fields=[{"name": field, "reason": "this platform cannot serve this model yet"}],
        )
    raise ProblemError(
        kind="validation",
        code="llm_model_not_available",
        title="That language model is not available",
        detail=(
            f"{value!r} is not a language model this platform runs. The models you can "
            f"choose are: {permitted}."
        ),
        remediation=(
            f"Choose one of {permitted}, or send null to fall back to the account default."
        ),
        fields=[{"name": field, "reason": "not one of the available language models"}],
    )


__all__ = [
    "CLIENT_DASHBOARD_UNAVAILABLE_REASON",
    "CLIENT_UNAVAILABLE_REASON",
    "DASHBOARD_ADDRESSABLE_PROVIDERS",
    "DASHBOARD_NEEDS_DATA_USE_ATTESTATION",
    "DASHBOARD_TERMS_UNREAD",
    "LLM_MODEL_SOURCES",
    "NO_ATTESTED_PRICE_REASON",
    "NO_CREDENTIAL_REASON",
    "NO_DASHBOARD_LEG_REASON",
    "NO_DATA_USE_ATTESTATION_REASON",
    "NO_DEPLOYMENT_REASON",
    "QUOTED_CALL_MINUTES",
    "UNAVAILABLE_REASON",
    "UNREAD_DASHBOARD_TERMS_REASON",
    "LlmCredentialReader",
    "LlmDashboardDataUseReader",
    "LlmModelSource",
    "LlmReasonAudience",
    "ResolvedLlmModel",
    "SelectableModel",
    "TenantModelLeg",
    "available_models",
    "dashboard_data_use_attested",
    "dashboard_leg_providers",
    "dashboard_leg_reason",
    "deployment_for",
    "every_selectable_model_is_priced",
    "install_dashboard_data_use_reader",
    "install_llm_credential_reader",
    "installed_llm_providers",
    "offerable_models",
    "platform_default_model",
    "quoted_inr_per_minute",
    "resolve_llm_model",
    "selectable_models",
    "tenant_dashboard_leg",
    "unofferable_reason",
    "validate_llm_model",
]
