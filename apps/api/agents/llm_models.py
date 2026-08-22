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

THE ALLOW-LIST IS `AZURE_OPENAI_MODELS` AND THERE IS NO SECOND COPY OF IT HERE
-----------------------------------------------------------------------------
Both the choosable set and the refusal message read that frozenset (via `selectable_
models()`), and the PRICE of each comes from `billing/rates.py` — so "what you may
choose" and "what it costs" cannot come to disagree about which models exist.
`every_selectable_model_is_priced()` states that as one predicate, and
`tests/llm_model_selection_test.py` fails if the two sets ever diverge: a selectable
model nobody priced is unmetered spend, and a priced model nobody can select is a number
that rots unnoticed.

⚠ THE MENU MAY NOT CONTAIN A DISH THE KITCHEN CANNOT COOK
---------------------------------------------------------
Under the declared `us-azure-openai` posture the engine addresses a **deployment id**,
not a model name (`calevate_shared.engine.ModelBinding`), and a deployment id is chosen
freely by whoever created it — it can NEVER be derived from the model name. So "which
models may a client choose" is not the allow-list on its own: it is the allow-list
INTERSECTED with the models this deployment has an Azure deployment for.

That intersection is not a nicety. `gpt-4.1-mini` costs 2.7x `gpt-4o-mini`, and a picker
that offered it while the wire kept addressing the default deployment would quote and
meter a client at the dearer rate for calls that ran the cheaper model — a charge for
something we did not deliver, invisible in a transcript, invisible in an execution
payload, and a hard-rule-7 defect rather than a cosmetic one. So there is ONE predicate,
`addressable_models()`, and everything else reads it: `available_models()` marks what
cannot run and says WHY, `validate_llm_model` refuses selecting it, and
`agents/service.py::in_call_llm` refuses to publish one. `tests/llm_model_selection_
test.py` asserts the offered set and the addressable set are the SAME SET, in both
directions, so they cannot drift apart by an edit to one of them.

WHERE THE DEPLOYMENTS COME FROM, and why it is two fields rather than one:
`Settings.azure_openai_deployment` is the deployment for `Settings.azure_openai_model` —
the pair `config.py` already required to move together, and the value pushed to the
engine's own credential store — and `Settings.azure_openai_deployments` carries the
others as `model=deployment` pairs. `deployment_for()` below is the only reader of
either, so "which deployment serves this model" has one answer and one place.

ON A DEPLOYMENT WITH NO AZURE CREDENTIALS AT ALL — local, CI, any staging without a
resource — there is no deployment indirection: `in_call_llm` passes the model straight
to the engine, so every allow-listed model is addressable and the picker offers them all.
That is not a special case bolted on; it is the same question ("can this deployment put
this model on the wire?") answered for the other arm of the same switch.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal, get_args

from calevate_shared.engine import AZURE_OPENAI_MODELS, DECLARED_POSTURE, LlmProvider

from apps.api.billing.rates import (
    PRICED_LLM_MODELS,
    is_surchargeable_llm_model,
    llm_cost_inr_per_minute,
)
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings

# THE ONE READER OF THE THREE `azure_openai_*` CREDENTIAL FIELDS, imported rather than
# re-derived — the same import `agents/service.py` makes and for the identical reason. It
# answers "does this deployment have an Azure leg at all", which is the question that
# decides whether a model needs a deployment to be addressable or goes to the engine
# verbatim. A second read here would be a second definition of "configured".
from apps.workers.extraction import azure_credentials

#: WHICH LEVEL SUPPLIED THE MODEL. A closed vocabulary rather than a `str`, for
#: `AgentDirection`'s reason (D-440): it is compared against, returned to a browser and
#: switched on by a generated TypeScript client, and a fourth level would have to be
#: added to the type before it could be returned.
LlmModelSource = Literal["agent", "organization", "platform"]

#: The same three as a value — `get_args` on the Literal, never a second tuple beside it
#: (D-104). Read by the tests that enumerate the levels.
LLM_MODEL_SOURCES: Final[tuple[LlmModelSource, ...]] = get_args(LlmModelSource)

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
    """Every model this platform may be told to run, sorted.

    Sorted so the picker's order is stable across interpreter runs — `AZURE_OPENAI_MODELS`
    is a frozenset, whose iteration order is not, and an unstable order here would make
    the OpenAPI snapshot and the screen shuffle for no reason.
    """
    return tuple(sorted(AZURE_OPENAI_MODELS))


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

    Blank-stripping both sides rather than trusting them: `azure_openai_deployment` is
    `str | None` and an operator clearing it in the console leaves `""`, which is not a
    deployment and must not be returned as one.
    """
    if model == platform_default_model():
        return (get_settings().azure_openai_deployment or "").strip() or None
    return (_configured_deployments().get(model) or "").strip() or None


def addressable_models() -> frozenset[str]:
    """Every allow-listed model this deployment can actually put on the wire.

    THE ONE PREDICATE BEHIND THE MENU, THE VALIDATOR AND THE PUBLISH REFUSAL — see the
    module docstring for why offering a model we cannot address is a money defect and not
    a cosmetic one.

    TWO ARMS, because `in_call_llm` has two and this has to answer for the same switch.
    With no Azure credentials there is no deployment indirection at all: the chosen model
    IS what the engine is sent, so every allow-listed model is addressable. With an Azure
    leg, the wire value is a deployment id and only the models one is configured for can
    run.
    """
    if azure_credentials() is None:
        return AZURE_OPENAI_MODELS
    return frozenset(model for model in AZURE_OPENAI_MODELS if deployment_for(model))


#: Why a model in the allow-list cannot be run here. ONE sentence, read by the API
#: response and by the refusal, so an operator and a client are told the same thing.
UNAVAILABLE_REASON: Final = (
    "no Azure deployment is configured for this model on this platform, so it cannot be "
    "addressed — create a deployment for it and add a `model=deployment` entry to "
    "azure_openai_deployments"
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
    """Is every model a client may choose one this repository can put a rupee on?

    A PREDICATE RATHER THAN AN `assert` AT IMPORT, because the two callers want different
    things from the same fact: `tests/llm_model_selection_test.py` wants a named failure,
    and a reader wants one place that states the invariant in words. An unpriced
    selectable model is unmetered spend — `llm_inr_per_ktok` raises `ValueError` on it,
    which on the assist path is a 500 for the client who chose it — so the two sets are
    held equal in BOTH directions rather than by containment.
    """
    return PRICED_LLM_MODELS == AZURE_OPENAI_MODELS


def quoted_inr_per_minute(model: str) -> Decimal:
    """What the language leg of a `QUOTED_CALL_MINUTES`-minute call costs per minute, INR.

    Straight through to `billing/rates.py` — this module states no price of its own. The
    rate card is the one place a vendor's dollar figure and the exchange rate it is struck
    at are written down, and a second derivation here would be the D-103 defect on the
    money axis.
    """
    return llm_cost_inr_per_minute(QUOTED_CALL_MINUTES, model=model)


def available_models() -> tuple[SelectableModel, ...]:
    """The picker's rows, derived from the allow-list and the rate card and nothing else.

    Raises through `quoted_inr_per_minute` if a model in the allow-list has no price. That
    is deliberate and is the reason there is no `try` here: a picker that silently dropped
    an unpriced model would hide exactly the defect `every_selectable_model_is_priced`
    exists to make loud, and would do it on the screen where a client is choosing what to
    spend.
    """
    default = platform_default_model()
    addressable = addressable_models()
    return tuple(
        SelectableModel(
            model=model,
            # OUR vocabulary for the leg, from the DECLARED posture rather than a literal
            # (D-432): a posture move must not leave a provider name behind on a screen.
            provider=DECLARED_POSTURE.llm_provider,
            inr_per_minute=quoted_inr_per_minute(model),
            is_platform_default=model == default,
            is_surcharged=is_surchargeable_llm_model(model),
            is_available=model in addressable,
            unavailable_reason=None if model in addressable else UNAVAILABLE_REASON,
        )
        for model in selectable_models()
    )


def validate_llm_model(value: str | None, *, field: str) -> str | None:
    """`value` if this deployment can actually run it, `None` if it is `None` — else a
    refusal.

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
    addressable = addressable_models()
    if value is None or value in addressable:
        return value
    # THE OFFERED SET AND THE REFUSAL'S SET ARE ONE EXPRESSION, so a message can never
    # name a model the write path would then reject.
    permitted = ", ".join(sorted(addressable)) or "none"
    if value in AZURE_OPENAI_MODELS:
        raise ProblemError(
            kind="validation",
            code="llm_model_not_deployed",
            title="That language model is not switched on for this platform yet",
            detail=(
                f"{value!r} is a model this platform supports, but {UNAVAILABLE_REASON}. "
                f"Until it is, the models you can choose are: {permitted}."
            ),
            remediation=(
                f"Choose one of {permitted} for now, or ask support to switch "
                f"{value} on for this platform."
            ),
            fields=[{"name": field, "reason": "no deployment is configured for this model"}],
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
    "LLM_MODEL_SOURCES",
    "QUOTED_CALL_MINUTES",
    "UNAVAILABLE_REASON",
    "LlmModelSource",
    "ResolvedLlmModel",
    "SelectableModel",
    "addressable_models",
    "available_models",
    "deployment_for",
    "every_selectable_model_is_priced",
    "platform_default_model",
    "quoted_inr_per_minute",
    "resolve_llm_model",
    "selectable_models",
    "validate_llm_model",
]
