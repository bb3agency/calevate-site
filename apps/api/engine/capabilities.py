"""The engine capability seam: ONE selector, ONE refusal, authored reason codes (D-93).

This is the fourth instance of a shape this repo has already settled three times —
`billing/payments.payment_capability`, `ingest/meta.lead_retrieval_capability`,
`workers/sheets_sync.get_sheets_transport` (and `campaigns/provisioning.
number_provisioning_capability`, which is the same shape for the TELEPHONY vendor). It is
deliberately not a fourth *design*: a config-named implementation, one selector every
surface asks, and refusals that name OUR state rather than quoting a vendor.

WHAT IS DIFFERENT HERE, AND WHY IT IS NOT A NEW SHAPE
-----------------------------------------------------
The other three answer "is anything wired up at all?" — the reason codes are about
missing credentials and unimplemented providers. This one answers "what can the wired-up
thing DO?", because a voice engine is never absent (one is always selected, `ENGINE=`)
and is never uniformly capable. So the availability question is asked PER CAPABILITY, and
the descriptor doing the answering is declared by the adapter itself
(`EngineCapabilities`) rather than derived from settings. That keeps the property those
three have and this one needs most: "we are configured" and "we can actually do it"
cannot disagree, because there is only one place either is written down.

WHY THE REFUSAL IS A `ProblemError` SUBCLASS RATHER THAN A NEW EXCEPTION
------------------------------------------------------------------------
BACKEND-PATTERNS' error ladder is `ProblemError`, and a second exception hierarchy for
one family of failures is two ways to do one thing. Subclassing keeps every existing
handler, status mapping and log site working unchanged, and adds the one thing a bare
`ProblemError` could not carry: the capability NAME as a field, so a test, a metric and
an operator all read the same token instead of parsing it out of English prose.

The alternative that was rejected: encoding the capability in the `code`
(`engine_lacks_tts`). `code` is documented as the STABLE machine identifier the frontend
switches on and it becomes the last segment of the problem `type` URL, so making it
per-capability would mint seven problem types for one condition and force the console to
enumerate them. One code, one attribute.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from calevate_shared.engine import (
    EngineCapabilities,
    EngineCapabilityName,
    NumberSeries,
    SpeechLeg,
    VoiceEngine,
)

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

#: The one machine code for "the selected engine cannot do this". Stable across every
#: capability (see the module docstring); the capability itself rides on the exception.
ENGINE_CAPABILITY_ABSENT: Final = "engine_capability_absent"

#: What an operator is told to do about each absent capability, in one sentence they can
#: act on. Authored per capability rather than generated, because "this engine does not
#: do X" is useless without "so do Y instead" — and the Y differs: a dictated speech leg
#: is a product fact to accept, a missing knowledge base is work that moves into our
#: layer, an unprovisionable number is a purchase that happens elsewhere.
_REMEDIATION: Final[dict[EngineCapabilityName, str]] = {
    "stt": (
        "The voice platform in use supplies its own speech recognition, so a "
        "transcription model cannot be selected here."
    ),
    "tts": (
        "The voice platform in use supplies its own voices, so a voice from our "
        "catalogue cannot be selected here."
    ),
    "llm": (
        "The voice platform in use supplies its own language model, so a model cannot "
        "be selected here."
    ),
    "campaigns": (
        "Campaigns are dispatched by Calevate rather than by the voice platform; nothing "
        "needs configuring on the platform side."
    ),
    "knowledge_base": (
        "The voice platform in use has no knowledge base, so published knowledge reaches "
        "the agent through its script instead. Contact us before relying on document "
        "retrieval."
    ),
    "numbers": (
        "Numbers are bought from the telephony provider rather than the voice platform. "
        "Contact us and we will provision one for your account."
    ),
    "transfer": (
        "The voice platform in use cannot transfer a live call. Use the escalation phone "
        "number configured on the agent."
    ),
}


class EngineCapabilityAbsentError(ProblemError):
    """The refusal for a capability the selected engine does not have.

    `kind="dependency"` because that is what it is — an external system cannot do the
    thing — and because the ladder already maps that kind to the right status and marks
    it retryable-or-not consistently with every other dependency failure. Retrying will
    not help, but neither does inventing a new kind: the client-facing consequence is
    identical to any other "the platform we rent cannot do this", and `remediation` is
    what actually tells them what to do.

    NOT raised for a capability that merely has not been VERIFIED yet. "Bolna probably
    supports transfer but nobody has run the pilot gate" is a different fact from "this
    engine has no transfer", and conflating them would let a pilot result quietly change
    a client-facing refusal. Unverified stays `engine_capability_unverified` in the
    adapter that is waiting on the evidence.
    """

    def __init__(self, capability: EngineCapabilityName, *, engine: str) -> None:
        self.capability: EngineCapabilityName = capability
        self.engine = engine
        super().__init__(
            kind="dependency",
            code=ENGINE_CAPABILITY_ABSENT,
            title="The voice platform cannot do that",
            # No vendor name and no vendor prose crosses this boundary (hard rule 2):
            # which engine is running is OUR deployment detail, and a client cannot act
            # on it. The capability is named in our own vocabulary instead.
            detail=f"The voice platform in use does not provide: {capability}.",
            remediation=_REMEDIATION[capability],
        )


def engine_lacks(capability: EngineCapabilityName, *, engine: str) -> EngineCapabilityAbsentError:
    """Build the refusal AND record it. One call site's worth of discipline, centralised:
    every absent-capability refusal is logged with the same two labels, so "which
    capability do our clients keep hitting" is a log query rather than an investigation.

    Ids and our own vocabulary only — no client detail, no vendor message (hard rule 6).
    """
    log.warning("engine_capability_absent", extra={"capability": capability, "engine": engine})
    return EngineCapabilityAbsentError(capability, engine=engine)


#: This deployment selected an engine whose adapter holds no credentials. Suffixed with
#: the engine name so an alert says WHICH — the name is OUR config, not vendor text.
NO_CREDENTIALS_REASON: Final = "no_engine_credentials"


@dataclass(frozen=True, slots=True)
class EngineAvailability:
    """Can this deployment reach its selected engine at all, as ONE answer.

    Distinct from `EngineCapabilities`, and the two must not be collapsed. Capabilities
    are what the engine COULD do for anybody; this is whether we can talk to it. An engine
    with a built-in knowledge base and no API key still has a built-in knowledge base, and
    a surface that read `capabilities.knowledge_base` as permission to publish would offer
    a button that fails at the vendor boundary every time.

    `capabilities` rides on the same object rather than being fetched separately — the
    argument `PaymentCapability.creates_orders` and `RetrievalCapability.retriever` both
    make: two facts, one lookup, one object. `reason` is non-None exactly when `available`
    is False, and it is an authored code naming OUR state.
    """

    available: bool
    engine: str
    capabilities: EngineCapabilities
    reason: str | None = None


def engine_availability(engine: VoiceEngine | None = None) -> EngineAvailability:
    """THE deployment-level selector: is the selected engine usable, and what can it do?

    The credential answer is DERIVED from the adapter (`holds_credentials`), never from a
    second read of settings — `lead_retrieval_capability` makes the argument in full. That
    matters most for an adapter like `cartesia`, which is wired and configurable and has
    no account behind it: every surface gets the same `no_engine_credentials` answer from
    one place, rather than each request discovering it separately at the vendor boundary.
    """
    resolved = engine if engine is not None else _selected_engine()
    caps = resolved.capabilities
    if not resolved.holds_credentials():
        return EngineAvailability(
            available=False,
            engine=resolved.name,
            capabilities=caps,
            reason=f"{NO_CREDENTIALS_REASON}:{resolved.name}",
        )
    return EngineAvailability(available=True, engine=resolved.name, capabilities=caps)


def engine_not_configured(reason: str | None) -> ProblemError:
    """The ONE deployment-side refusal, so every surface says it the same way.

    RFC-9457: the machine code is the LAST SEGMENT of `type` and there is no `code` key.
    The authored `reason` is logged for an operator and never returned — a client cannot
    act on `no_engine_credentials:cartesia`, and naming our vendor to them leaks an
    internal detail they have no use for.
    """
    log.warning("engine_not_configured", extra={"reason": reason or "unknown"})
    return ProblemError(
        kind="dependency",
        code="engine_not_configured",
        title="The voice platform is unavailable",
        detail="This deployment cannot reach its voice platform right now.",
        remediation="Contact us — this is a configuration problem on our side, not yours.",
    )


def _selected_engine() -> VoiceEngine:
    # Imported inside the function, exactly as `lead_retrieval_capability` imports its
    # adapters: `apps.api.engine.__init__` imports this module for the refusal type, so a
    # module-scope import back into it would be a cycle. The seam depends on nothing.
    from apps.api.engine import get_engine

    return get_engine()


def engine_capabilities(engine: VoiceEngine | None = None) -> EngineCapabilities:
    """THE selector. Every surface asks this; nothing reads an adapter's attribute
    directly and nothing decides for itself what the engine can do.

    `engine` is an optional override for tests and for the two callers that already hold
    an adapter (the publish path, the KB publish path) — passing the one they hold is
    cheaper and, more importantly, guarantees the capability they check belongs to the
    adapter they are about to call. A second `get_engine()` here would be a second read
    of the same thing, which is how a surface that offers a control and a route that
    refuses it come to disagree.
    """
    if engine is not None:
        return engine.capabilities
    return _selected_engine().capabilities


def require_capability(capability: EngineCapabilityName, *, engine: VoiceEngine) -> None:
    """Raise unless `engine` has `capability`. The one guard an adapter or a service uses.

    Takes the adapter rather than looking one up, for the reason above: a guard that
    checked a different instance from the one about to be called is a guard that passes
    on the wrong evidence.
    """
    if not engine.capabilities.has(capability):
        raise engine_lacks(capability, engine=engine.name)


def require_speech_leg(leg: SpeechLeg, *, engine: VoiceEngine, value: str | None) -> None:
    """Refuse a BYOK selection for a leg this engine DICTATES — and only then.

    This is the guard that makes `SpeechControl` mean something. Dropping the value
    instead (the tempting, quieter option) produces the exact failure this slice exists
    to remove: an operator picks Bulbul v3, the row saves, the publish succeeds, and the
    caller hears the engine's own voice. Nothing in that sequence reports a problem, so
    the screen keeps offering the choice forever.

    `value is None` passes: an agent that names no voice is not asserting anything about
    the engine's speech, and refusing it would make an unconfigured agent unpublishable
    on an engine that needs no configuration.
    """
    if value is None:
        return
    if not engine.capabilities.is_ours(leg):
        raise engine_lacks(leg, engine=engine.name)


def provisionable_series(engine: VoiceEngine) -> frozenset[NumberSeries]:
    """The number classes this engine can provision. Empty is the normal answer today."""
    return engine.capabilities.number_series


__all__ = [
    "ENGINE_CAPABILITY_ABSENT",
    "NO_CREDENTIALS_REASON",
    "EngineAvailability",
    "EngineCapabilityAbsentError",
    "engine_availability",
    "engine_capabilities",
    "engine_lacks",
    "engine_not_configured",
    "provisionable_series",
    "require_capability",
    "require_speech_leg",
]
