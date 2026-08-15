"""Engine adapters — the ONLY package allowed to see vendor payload shapes.

Hard rule 2 in one sentence: everything else consumes the normalized models in
`calevate_shared` and reaches an engine through `get_engine()`, so swapping vendors
is a change in this directory and nowhere else. The import-linter contract in
`pyproject.toml` enforces it in CI; this docstring only explains why.

Selection is per-environment config (`ENGINE=fake|bolna`), never a code branch in a
business module.

WHAT AN ENGINE CAN DO is a second question, and it is answered here too (D-93). Every
adapter declares an `EngineCapabilities` descriptor, and `engine_capabilities()` is THE
selector business code asks — because implementing the same Protocol never meant giving
the same ANSWERS. `capabilities.py` holds the selector, the one refusal, and the argument
for both; this module re-exports them so a caller needs exactly one import to reach an
engine and to ask what it can do.
"""

from __future__ import annotations

from calevate_shared.config import Settings
from calevate_shared.engine import EngineCapabilities, VoiceEngine

from apps.api.core.settings import get_settings
from apps.api.engine.capabilities import (
    EngineAvailability,
    EngineCapabilityAbsentError,
    engine_availability,
    engine_capabilities,
    engine_lacks,
    engine_not_configured,
    require_capability,
    require_speech_leg,
)

_instances: dict[str, VoiceEngine] = {}


def get_engine(settings: Settings | None = None) -> VoiceEngine:
    """One adapter instance per engine name per process (httpx clients are reused)."""
    cfg = settings or get_settings()
    # Widened to `str`, and the reason for widening it is GONE. This said `EngineName`
    # "does NOT yet include `cartesia`"; it does — D-93/D-94 landed the literal in
    # `calevate_shared/config.py` (`Literal["fake", "bolna", "cartesia"]`), so every
    # member reaches a branch below and mypy's `warn_unreachable` has nothing to object
    # to under the narrow type. The annotation is now vestigial rather than load-bearing:
    # narrowing it back to `EngineName` is a typing-only change with no runtime effect.
    # What the original note got right and is worth keeping: shipping the branch BEFORE
    # the literal was correct, because the alternative is the "route nobody mounted"
    # defect — an adapter that exists, passes conformance, and no configuration can reach.
    name: str = cfg.engine
    if name not in _instances:
        if name == "bolna":
            from apps.api.engine.bolna import BolnaEngine

            _instances[name] = BolnaEngine(api_key=cfg.bolna_api_key, fx_rate=cfg.usd_inr_rate)
        elif name == "cartesia":
            from apps.api.engine.cartesia import CartesiaEngine

            # `getattr` is vestigial for the same reason as the widening above: both keys
            # ARE real `Settings` fields now (`cartesia_api_key`,
            # `cartesia_from_number_id` in `calevate_shared/config.py`, D-93/D-94), each
            # defaulting to None. The None default is the part that still matters — it
            # makes the capability selector report the engine unconfigured and every
            # request refuse, which is the correct behaviour for an adapter with no
            # credentials and the same shape `payment_capability` uses.
            _instances[name] = CartesiaEngine(
                api_key=getattr(cfg, "cartesia_api_key", None),
                from_number_id=getattr(cfg, "cartesia_from_number_id", None),
            )
        else:
            from apps.api.engine.fake import FakeEngine

            _instances[name] = FakeEngine()
    return _instances[name]


def reset_engine_cache() -> None:
    """Tests switch engines between cases; production never calls this."""
    _instances.clear()


__all__ = [
    "EngineAvailability",
    "EngineCapabilities",
    "EngineCapabilityAbsentError",
    "engine_availability",
    "engine_capabilities",
    "engine_lacks",
    "engine_not_configured",
    "get_engine",
    "require_capability",
    "require_speech_leg",
    "reset_engine_cache",
]
