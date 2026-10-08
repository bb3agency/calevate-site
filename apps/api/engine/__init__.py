"""Engine adapters — the ONLY package allowed to see vendor payload shapes.

Hard rule 2 in one sentence: everything else consumes the normalized models in
`calevate_shared` and reaches an engine through `get_engine()`, so swapping vendors
is a change in this directory and nowhere else. The import-linter contract in
`pyproject.toml` enforces it in CI; this docstring only explains why.

Selection is per-environment config (`ENGINE=`, validated against
`calevate_shared.config.EngineName`), never a code branch in a business module. The
permitted names are not respelled here — D-103 removed the second copy of that set and
`tests/engine_name_drift_test.py` fails on a third.

WHAT AN ENGINE CAN DO is a second question, and it is answered here too (D-93). Every
adapter declares an `EngineCapabilities` descriptor, and `engine_capabilities()` is THE
selector business code asks — because implementing the same Protocol never meant giving
the same ANSWERS. `capabilities.py` holds the selector, the one refusal, and the argument
for both; this module re-exports them so a caller needs exactly one import to reach an
engine and to ask what it can do.
"""

from __future__ import annotations

from typing import get_args

from calevate_shared.config import EngineName, Settings
from calevate_shared.engine import EngineCapabilities, VoiceEngine

from apps.api.core.settings import get_settings
from apps.api.engine.capabilities import (
    EngineCapabilityAbsentError,
    engine_capabilities,
    engine_lacks,
    engine_not_configured,
    require_capability,
    require_speech_leg,
)
from apps.api.engine.catalogue import (
    CatalogueModel,
    EngineCatalogue,
    HoldsCatalogue,
)

_instances: dict[str, VoiceEngine] = {}


def build_engine(cfg: Settings) -> VoiceEngine:
    """THE branch, and the only one: engine name → adapter, built from THESE settings.

    Split out of `get_engine` (D-104) so a caller that must not see a cached answer has
    somewhere honest to go. `get_engine` keys its cache on the engine NAME alone, which is
    right for the request path — one process serves one deployment, and an adapter that
    copies a credential at construction (`cartesia_api_key` is `on_restart` for that reason)
    keeps it for the life of the process. It is WRONG for a caller that hands in a
    `Settings` it built itself: it would get back an adapter constructed from a different
    one and never know. `runtime_config_missing_keys` is exactly that caller, and readiness
    answering about the wrong configuration is worse than readiness not answering.

    The `EngineName` annotation is load-bearing again: it was widened to `str` while
    `cartesia` was missing from the literal, and mypy's `warn_unreachable` now proves the
    `else` is reachable only by `fake` — so a name added to `EngineName` without a branch
    here is a type error rather than a silently-fake engine.
    """
    name: EngineName = cfg.engine
    if name == "cartesia":
        from apps.api.engine.cartesia import CartesiaEngine

        # Both fields default to None, and that is the part that matters: it makes the
        # capability selector report the engine unconfigured and every surface refuse,
        # which is the correct behaviour for an adapter with no account behind it and the
        # same shape `payment_capability` uses.
        return CartesiaEngine(
            api_key=cfg.cartesia_api_key,
            from_number_id=cfg.cartesia_from_number_id,
        )
    if name == "pipecat":
        from apps.api.engine.pipecat import PipecatEngine

        # NO CREDENTIAL ARGUMENTS, and that is the adapter's whole shape rather than an
        # omission: its control plane is this deployment's own database, which the process
        # already holds (D-592). The store defaults to `SqlControlPlane`; the only caller
        # that passes one is the conformance suite, which substitutes the database and the
        # worker together — see the adapter's module docstring.
        return PipecatEngine()
    if name == "thinnest":
        from apps.api.engine.thinnest import ThinnestEngine

        # No signing-secret resolver here: the request path never verifies a delivery
        # (voice-runtime does), and the worker path that does passes its own.
        return ThinnestEngine(api_key=cfg.thinnest_api_key, base_url=cfg.thinnest_api_base_url)
    from apps.api.engine.fake import FakeEngine

    return FakeEngine()


def get_engine(settings: Settings | None = None) -> VoiceEngine:
    """One adapter instance per engine name per process (httpx clients are reused)."""
    cfg = settings or get_settings()
    name = cfg.engine
    if name not in _instances:
        _instances[name] = build_engine(cfg)
    return _instances[name]


def missing_engine_credential_keys(cfg: Settings) -> tuple[str, ...]:
    """The environment keys the SELECTED engine needs and does not have.

    WHY THE ADAPTER ANSWERS (D-104). The alternative is one `if cfg.engine == ...` per
    vendor in `core/settings.py`, which is how `/healthz/ready` once reported a
    credential-less deployment fit to take traffic: every new engine needs another branch,
    and whoever adds it is editing a core module to record a fact about a vendor, which
    hard rule 2 says only `apps/api/engine/` may hold.

    So the adapter answers both halves: `holds_credentials()` for whether it can reach its
    vendor (this is the one authority; the second, uncalled one is gone — P2.6), and
    `credential_env_keys` for what to NAME in the readiness response. Readiness needs the
    name, not just the verdict, because "not ready" without the key an operator must set
    is a red light with no next step.

    Built uncached from `cfg`, never `get_engine` — see `build_engine`.
    """
    adapter = build_engine(cfg)
    return () if adapter.holds_credentials() else adapter.credential_env_keys


def all_credential_env_keys() -> tuple[str, ...]:
    """Every environment variable ANY engine adapter reads a credential from.

    DERIVED from `EngineName` and the adapters, never retyped — a fourth engine is
    covered by the function that already exists rather than by an edit somebody has to
    remember. `credential_env_keys` is a class-level attribute with a default on all three
    adapters, so this needs no `Settings` and no constructed engine, which is what lets
    `tests/conftest.py` call it before any configuration exists.

    Its one caller is the test harness. `_no_ambient_credentials` strips these for the
    same reason it strips `AWS_*`: a developer whose `.env` carries a real vendor key was
    silently running a DIFFERENT suite from CI, and the two readiness tests that assert a
    key is ABSENT failed on their machine and nowhere else — the exact class
    `tests/harness_ambient_env_test.py` was written to end, arriving through a door that
    file did not cover.
    """
    from apps.api.engine.cartesia import CartesiaEngine
    from apps.api.engine.fake import FakeEngine
    from apps.api.engine.pipecat import PipecatEngine
    from apps.api.engine.thinnest import ThinnestEngine

    # KEYED OFF EACH ADAPTER'S OWN `name`, and NEVER a literal set of engine names here:
    # `tests/engine_name_drift_test.py` fails a third spelling, because this repo has
    # exactly two homes for that set — `EngineName`/`SELECTABLE_ENGINES` (which names
    # `ENGINE=` may take) and `WEBHOOK_AUTH_BY_ENGINE` (which names have an authenticity
    # story) — and a third spelling drifts the first time either grows. The adapters
    # already declare `name`, so the mapping is derivable and the literal bought nothing.
    adapters: tuple[type[VoiceEngine], ...] = (
        CartesiaEngine,
        FakeEngine,
        PipecatEngine,
        ThinnestEngine,
    )
    by_name = {adapter.name: adapter for adapter in adapters}
    # Exhaustiveness against the Literal rather than against the tuple above: an engine
    # added to `EngineName` without an adapter here is a failure, not a credential that
    # silently stops being stripped.
    missing = set(get_args(EngineName)) - set(by_name)
    if missing:
        raise AssertionError(
            f"engines with no adapter in all_credential_env_keys: {sorted(missing)}"
        )
    keys: list[str] = []
    for adapter in by_name.values():
        for key in adapter.credential_env_keys:
            if key not in keys:
                keys.append(key)
    return tuple(keys)


async def engine_catalogue(engine: VoiceEngine | None = None) -> EngineCatalogue:
    """The selected engine's OWN voices and models (`engine/catalogue.py`), for the offer
    seam. Refuses on the `tts` capability where the engine publishes no catalogue of its own:
    an empty catalogue would read as an account with nothing to offer."""
    adapter = engine if engine is not None else get_engine()
    if not isinstance(adapter, HoldsCatalogue):
        raise engine_lacks("tts", engine=adapter.name)
    return await adapter.read_catalogue()


def reset_engine_cache() -> None:
    """Tests switch engines between cases; production never calls this."""
    _instances.clear()


__all__ = [
    "CatalogueModel",
    "EngineCapabilities",
    "EngineCapabilityAbsentError",
    "EngineCatalogue",
    "all_credential_env_keys",
    "build_engine",
    "engine_capabilities",
    "engine_catalogue",
    "engine_lacks",
    "engine_not_configured",
    "get_engine",
    "missing_engine_credential_keys",
    "require_capability",
    "require_speech_leg",
    "reset_engine_cache",
]
