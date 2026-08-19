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


def test_every_seeded_login_is_one_the_api_would_accept() -> None:
    """**A seeded credential that cannot sign in is not a credential.**

    This file already refuses to run the seed anywhere but `local`; this is the other
    half — that what it creates on `local` actually WORKS. It did not. Every account was
    created at a `.local` address, which `EmailStr` (pydantic → `email-validator`)
    rejects as a special-use name, so the rows existed, the script reported success, and
    the sign-in form answered "the part after the @-sign is a special-use or reserved
    name". The seed and the door disagreed and nothing said so.

    DRIVEN THROUGH `LoginIn` ITSELF, the wire model `POST /auth/login` validates against,
    rather than through a `TypeAdapter(EmailStr)` that merely resembles it: the point is
    that THIS ROUTE accepts these values, and a reconstruction could drift from the route
    while still passing. It covers the password too, for the same reason and the same
    class of bug — `LoginIn` bounds the password, so a seeded one below `MIN_PASSWORD_CHARS`
    would be exactly as unusable and exactly as silent.

    Note what this does NOT assert: that the address is undeliverable. That is
    `test_no_seeded_address_could_reach_a_real_mailbox` below, and the two pull in
    opposite directions — the reason the first fix reached for `.local` at all. Both must
    hold at once, and `example.com` is the domain that satisfies both.
    """
    from apps.api.authn.routes import LoginIn

    credentials = (
        (seed_dev.ADMIN_EMAIL, seed_dev.ADMIN_PASSWORD),
        (seed_dev.OWNER_EMAIL, seed_dev.OWNER_PASSWORD),
        (seed_dev.STAFF_EMAIL, seed_dev.STAFF_PASSWORD),
    )
    assert credentials, "nothing was checked, so this test proved nothing"
    for email, password in credentials:
        try:
            LoginIn(email=email, password=password)
        except ValidationError as exc:  # pragma: no cover - only on the defect
            raise AssertionError(
                f"the seed creates {email!r}, which POST /auth/login refuses: {exc}"
            ) from exc


def test_no_seeded_address_could_reach_a_real_mailbox() -> None:
    """The other half of the constraint above: seeded mail must go nowhere, ever.

    A dev stack runs real notification jobs. If a seeded address were a domain somebody
    owns, a hot-lead alert or an invitation would leave a laptop and land on a stranger —
    so a REGISTRABLE domain is disqualified even though it validates cleanly. `.dev` is
    the trap here: it passes `EmailStr` and reads as developer-ish, and
    `sunrise-dental.dev` is a domain a person can buy.

    `example.com` is reserved by RFC 2606 §3 and can never be registered by anyone, which
    is a stronger guarantee than "we did not configure SMTP" — it holds even when someone
    does configure SMTP. Asserted on the SUFFIX so a fourth seeded account inherits it.
    """
    addresses = (seed_dev.ADMIN_EMAIL, seed_dev.OWNER_EMAIL, seed_dev.STAFF_EMAIL)
    assert len(set(addresses)) == len(addresses), "two seeded accounts share an address"
    for email in addresses:
        assert email.endswith(".example.com"), (
            f"{email!r} is not under the RFC 2606 reserved domain, so it may be "
            "registrable and a dev-stack notification could reach a real person"
        )
