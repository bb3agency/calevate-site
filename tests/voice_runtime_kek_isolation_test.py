"""voice-runtime does not receive `PLATFORM_KEK` (compose.prod.yml).

All three Python services share `env_file: [.env]` through one YAML anchor, and the KEK is
in that file because api, workers and the `migrate` one-shot need it. voice-runtime never
unwraps a DEK (`start_config_refresher(with_secrets=False)`) and is the service the
internet reaches, so its own `environment:` block blanks the key; Compose ranks
`environment` above `env_file`. What is asserted:

1. voice-runtime sets both KEK variables to a literal empty string — not `${...}`, which
   would be interpolated from the deploy shell and the project `.env`;
2. no OTHER service blanks them, so the first deploy's api, workers and migrate are
   unchanged;
3. the shared anchor still hands every service the same `env_file`, so the override is
   the only difference;
4. an empty KEK is what the envelope reads as "no usable key" and refuses by name.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from apps.api.core import envelope
from apps.api.core.errors import ProblemError
from apps.api.core.settings import Settings

COMPOSE_PROD = Path(__file__).resolve().parents[1] / "compose.prod.yml"
KEK_VARS = ("PLATFORM_KEK", "PLATFORM_KEK_RETIRED")


def _services() -> dict[str, Any]:
    document = yaml.safe_load(COMPOSE_PROD.read_text(encoding="utf-8"))
    return dict(document["services"])


def test_voice_runtime_blanks_the_kek_with_a_literal() -> None:
    environment = _services()["voice-runtime"]["environment"]
    for name in KEK_VARS:
        assert environment.get(name) == "", f"voice-runtime must set {name} to a literal ''"
    raw = COMPOSE_PROD.read_text(encoding="utf-8")
    assert "${PLATFORM_KEK" not in raw, "an interpolated KEK would be read from the shell"


@pytest.mark.parametrize("service", ["api", "workers", "migrate"])
def test_no_other_service_loses_the_kek(service: str) -> None:
    environment = _services()[service].get("environment") or {}
    for name in KEK_VARS:
        assert name not in environment, f"{service} must read {name} from .env"


@pytest.mark.parametrize("service", ["api", "voice-runtime", "workers", "migrate"])
def test_every_python_service_still_reads_the_one_env_file(service: str) -> None:
    assert _services()[service]["env_file"] == [".env"]


def test_an_empty_kek_is_refused_by_name_rather_than_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The value voice-runtime now holds, read the way the envelope reads it outside local."""
    monkeypatch.setenv("PLATFORM_KEK", "")
    monkeypatch.setenv("PLATFORM_KEK_RETIRED", "")
    cfg = Settings()

    assert not cfg.platform_kek
    with pytest.raises(ProblemError) as refused:
        envelope.build_ring(kek=cfg.platform_kek, retired=cfg.platform_kek_retired, app_env="prod")
    assert refused.value.code == "platform_kek_unusable"
