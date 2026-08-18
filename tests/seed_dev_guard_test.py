"""`scripts/seed_dev.py` publishes three passwords in its own source. Pin the gate.

The script is safe for exactly one reason: it refuses to run anywhere but `APP_ENV=local`,
and there is no override. That is one `if` standing between a documented password and a
deployed host, so it gets a test rather than a comment — and the test is written so that
DELETING the check fails it, not only weakening the message.

`tests/deploy_env_preflight_test.py` guards the other half of the same worry (that no
seeded value reaches a deployed environment file); this one guards the runtime.
"""

from __future__ import annotations

from typing import get_args

import pytest
from apps.api.core.settings import Settings, get_settings
from pydantic import ValidationError
from scripts import seed_dev

#: The annotation, read off the model rather than retyped.
SETTINGS_APP_ENVS = Settings.model_fields["app_env"].annotation


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


#: Every value `Settings.app_env` can hold, minus the one this script is for. Derived from
#: the Literal rather than retyped, so a fourth environment added tomorrow is refused by a
#: test that already exists instead of by one nobody remembered to extend.
_DEPLOYED_ENVS = tuple(e for e in get_args(SETTINGS_APP_ENVS) if e != "local")


@pytest.mark.parametrize("app_env", _DEPLOYED_ENVS)
def test_every_env_that_is_not_local_is_refused(
    app_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", app_env)
    get_settings.cache_clear()
    with pytest.raises(SystemExit) as exc:
        seed_dev._refuse_unless_local()
    # Message, not just the exit: an operator who hits this needs to be told where the
    # deployed path is, and a bare `SystemExit(1)` would pass a weaker version of this test.
    assert "bootstrap_admin" in str(exc.value)
    assert app_env in str(exc.value)
    assert _DEPLOYED_ENVS, "the parametrize list is empty — this test would be vacuous"


@pytest.mark.parametrize("near_miss", ["Local", "LOCAL", " local", "", "development"])
def test_a_near_miss_cannot_even_be_configured(
    near_miss: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case-insensitive-comparison worry is already closed one layer down.

    A "helpful" `app_env.lower() == "local"` here would be the obvious weakening of the
    gate above — and it could never fire, because `Settings.app_env` is a `Literal` and
    `"Local"` never becomes a `Settings`. That is a stronger control than the `if`, so it
    is worth a test of its own: an edit that relaxed the Literal to a bare `str` would
    make the weakening reachable, and this is what would go red.
    """
    monkeypatch.setenv("APP_ENV", near_miss)
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        get_settings()


def test_local_is_allowed_so_the_test_above_is_not_vacuous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The non-vacuity control: a guard that refused everything would pass the test above."""
    monkeypatch.setenv("APP_ENV", "local")
    get_settings.cache_clear()
    seed_dev._refuse_unless_local()  # does not raise


def test_the_script_takes_no_flags_that_could_become_a_force(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """There is no `--force`, and `main` must not quietly ignore what it is handed.

    A script that accepted and dropped an argument is one refactor away from accepting a
    meaningful one. It exits 2 on any argv and — the part that matters — does so BEFORE
    the environment gate, so a stray argument can never be the thing that ran a seed.
    """
    monkeypatch.setenv("APP_ENV", "prod")
    get_settings.cache_clear()
    assert seed_dev.main(["--force"]) == 2


def test_no_seeded_number_is_dialable() -> None:
    """Demo rows must not carry a number a mis-pointed campaign could actually ring.

    `+9199000001xx` is inside the `99` mobile series but in the `00000` block, which no
    Indian operator allocates. The assertion is on the PREFIX rather than on a list of the
    six numbers, so a seventh demo call added later is covered by it too.
    """
    peers = {call.peer_e164 for call in seed_dev.DEMO_CALLS}
    assert len(peers) == len(seed_dev.DEMO_CALLS), "two demo calls share a number"
    for number in peers:
        assert number.startswith("+9199000001"), number


def test_the_demo_prompt_does_not_carry_its_own_compliance_sentences() -> None:
    """Hard rule 5: the AI disclosure and the recording notice are appended server-side.

    A seeded prompt that spelled them out would be a second copy — one a client could edit
    away while `compose_engine_prompt` kept appending the real one, so the agent would say
    it twice and the demo would teach the wrong shape.
    """
    body = seed_dev.DEMO_PROMPT.lower()
    for phrase in ("this call is recorded", "i am an ai", "artificial intelligence"):
        assert phrase not in body, f"{phrase!r} belongs to compose_engine_prompt, not a script"
