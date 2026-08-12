"""Engine adapters — the ONLY package allowed to see vendor payload shapes.

Hard rule 2 in one sentence: everything else consumes the normalized models in
`calevate_shared` and reaches an engine through `get_engine()`, so swapping vendors
is a change in this directory and nowhere else. The import-linter contract in
`pyproject.toml` enforces it in CI; this docstring only explains why.

Selection is per-environment config (`ENGINE=fake|bolna`), never a code branch in a
business module.
"""

from __future__ import annotations

from calevate_shared.config import Settings
from calevate_shared.engine import VoiceEngine

from apps.api.core.settings import get_settings

_instances: dict[str, VoiceEngine] = {}


def get_engine(settings: Settings | None = None) -> VoiceEngine:
    """One adapter instance per engine name per process (httpx clients are reused)."""
    cfg = settings or get_settings()
    name = cfg.engine
    if name not in _instances:
        if name == "bolna":
            from apps.api.engine.bolna import BolnaEngine

            _instances[name] = BolnaEngine(api_key=cfg.bolna_api_key, fx_rate=cfg.usd_inr_rate)
        else:
            from apps.api.engine.fake import FakeEngine

            _instances[name] = FakeEngine()
    return _instances[name]


def reset_engine_cache() -> None:
    """Tests switch engines between cases; production never calls this."""
    _instances.clear()


__all__ = ["get_engine", "reset_engine_cache"]
