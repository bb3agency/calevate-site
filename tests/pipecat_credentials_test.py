"""The Pipecat path's credential surface: declared, shown, refused, and never stored (D-614).

**WHAT WENT WRONG, AND IT WAS AN ABSENCE RATHER THAN A BUG.** D-592 moved the conversation
loop from a rented engine to a container we deploy, and the CONFIGURATION SURFACE did not
follow. `Settings` carried six `bolna_*` fields and nothing for the carrier the owned
runtime actually answers the phone on, so `PLIVO_AUTH_ID` / `PLIVO_AUTH_TOKEN` lived in two
`Final` constants inside `apps/voice-worker` and two entries in a CI script's registry — no
row in the platform's credential inventory, nothing on any screen, and no way for an
operator to ask whether this deployment has a carrier credential at all.

**WHAT IS ASSERTED HERE, AND WHY EACH FAILURE IS WORSE THAN THE ONE BELOW IT:**

1. **A carrier credential must never be storable in `platform_secrets`.** Its reader is a
   container on Pipecat Cloud that must never hold `PLATFORM_KEK` (DEPLOYMENT §12.2), so a
   stored value is one nothing can ever read — an operator rotating a LIVE carrier
   credential on a screen that cannot reach it, and being told it worked.
2. **The console must nevertheless SHOW it**, with the reason and with where the value
   goes. An absence reads identically to "this build does not have that setting", which is
   the defect `BootstrapKeyOut` was written for and which the web console then reproduced
   by never rendering the list.
3. **Its absence from THIS host must not render as a fault.** `configured: false` is the
   correct and permanent state on every VPS, so the row carries `held_by` instead of a
   verdict — otherwise the screen tells an operator to install a carrier credential on a
   box with no reader for it.
4. **One value, one name, two homes.** `voice_worker/boot.py` promises every variable it
   reads is spelled exactly as its `Settings` field is spelled. Nothing enforced that.

THIS FILE IS ALSO THE `check_half_wired` CONSUMER, AND SAYS SO RATHER THAN BEING QUIET
ABOUT IT. That gate asks whether any file outside the declaration sites names a `Settings`
field, because "a key an operator can install that changes no behaviour is worse than no
key". These two fields DO change behaviour — what the console lists, what the write path
refuses, what the probe answers — but the behaviour is DERIVED from `Settings.model_fields`
rather than reached by name, which the gate cannot see. The assertions below are that
behaviour, exercised.
"""

from __future__ import annotations

import pytest
from apps.api.core.platform_config import is_secret_key
from apps.api.core.settings import (
    ENV_ONLY_DISPLAY,
    ENV_ONLY_FOREIGN_ENV,
    ENV_ONLY_KEYS,
    env_var_for,
)
from apps.api.ops.secret_probes import PROBES, probe_credential
from apps.api.ops.secret_service import manageable_secret_keys
from calevate_shared.config import Settings

#: The pair, once. Both names are `Settings` fields by the first test below.
CARRIER_KEYS = ("plivo_auth_id", "plivo_auth_token")


@pytest.mark.parametrize("key", CARRIER_KEYS)
def test_the_carrier_credential_is_a_declared_settings_field(key: str) -> None:
    """The register, which is the whole reason the field exists.

    `env_var_for`, `env_declares`, `ENV_ONLY_DISPLAY`, `GET /v1/ops/config` and both CI
    parity guards all derive from `Settings.model_fields`. A credential outside it has no
    row anywhere a person looks, however carefully it is documented in Markdown.
    """
    assert key in Settings.model_fields
    field = Settings.model_fields[key]
    # Defaulted `None` like every other credential in this model: a credential with a
    # shipped default is a credential shipped in the source.
    assert not field.is_required()
    assert field.get_default(call_default_factory=True) is None
    assert env_var_for(key) == key.upper()


@pytest.mark.parametrize("key", CARRIER_KEYS)
def test_the_console_never_offers_to_store_a_carrier_credential(key: str) -> None:
    """The failure this decision exists to make impossible.

    A box on a screen implies the value reaches the thing that uses it. Here it cannot:
    `platform_secrets` is sealed with `PLATFORM_KEK` and the reader is the one deployable
    that must never hold it. Both console surfaces are checked, not one — `managed_fields`
    would put it in a PLAINTEXT table, which is the worse of the two mistakes.
    """
    from apps.api.core.platform_config import managed_fields

    assert key in ENV_ONLY_KEYS
    assert key not in manageable_secret_keys()
    assert key not in managed_fields()


@pytest.mark.parametrize("key", CARRIER_KEYS)
def test_the_console_says_the_key_exists_and_why_it_cannot_be_set_here(key: str) -> None:
    """Absence is not an explanation — the point of `ENV_ONLY_DISPLAY`.

    The reason must NAME where the value goes, because an operator who cannot store it
    here has to be sent somewhere, and "the deployment's environment" is the wrong answer
    for a variable that belongs in a vendor's secret set.
    """
    reason = ENV_ONLY_DISPLAY[key]
    assert "secret set" in reason
    assert env_var_for(key) in reason


@pytest.mark.parametrize("key", CARRIER_KEYS)
def test_the_carrier_key_is_reported_as_held_by_another_environment(key: str) -> None:
    """`configured: false` is CORRECT here, permanently, on every host this API runs on.

    So the row must not carry a verdict at all. Without `held_by` the console paints a
    warning an operator would clear by putting a live carrier credential on a VPS that has
    no reader for it — a worse state than the one the badge complained about.
    """
    assert ENV_ONLY_FOREIGN_ENV[key].startswith("the Pipecat Cloud secret set")


def test_only_the_voice_containers_own_keys_are_held_by_a_foreign_environment() -> None:
    """The other direction. `APP_ENV` or `PLATFORM_KEK` acquiring a `held_by` would silence
    a genuine fault on the one screen that reports it.

    ⚠ **THIS WAS `..._only_the_carrier_pair_...` UNTIL D-618, AND THE SET GREW BY ONE
    WITHOUT THE RULE MOVING.** `gnani_api_key` is held by the same foreign environment for
    the same reason as the carrier pair — its reader is the `apps/voice-worker` container,
    which must never hold `PLATFORM_KEK` — with one more: nothing in `apps/api` holds a
    Gnani client at all, so a stored value would have no reader on this host under any
    arrangement. What this test still pins is that a key of THIS deployment's own can never
    acquire a `held_by` and stop being reported when it is genuinely missing.
    """
    assert set(ENV_ONLY_FOREIGN_ENV) == {*CARRIER_KEYS, "gnani_api_key"}
    assert set(ENV_ONLY_FOREIGN_ENV) <= set(ENV_ONLY_DISPLAY)


def test_the_token_half_is_name_classified_as_a_credential() -> None:
    """`plivo_auth_token` matches `_SECRET_NAME_FRAGMENTS`; `plivo_auth_id` does not, and
    that asymmetry is deliberate rather than an oversight.

    The id is the HTTP Basic USERNAME — an account identifier, not a secret. What keeps it
    out of the plaintext `platform_settings` table is `ENV_ONLY_KEYS` (asserted above), not
    its name, and this test is what makes that dependency visible if the classification is
    ever relied on instead.
    """
    assert is_secret_key("plivo_auth_token")
    assert not is_secret_key("plivo_auth_id")


@pytest.mark.parametrize("key", CARRIER_KEYS)
async def test_a_carrier_credential_answers_no_probe_rather_than_a_green_tick(key: str) -> None:
    """Hard rule 11 in its most tempting form.

    Plivo authenticates with HTTP Basic over the PAIR and this contract is handed ONE
    candidate, so a probe here could only shape-check; the only Plivo endpoint in evidence
    is the hang-up DELETE; and `api.plivo.com` is egress-blocked from the build
    environment, so nothing else could be written down without inventing it.
    `no_probe` says "this has NOT been checked", which is the true answer.
    """
    assert key not in PROBES
    result = await probe_credential(key, "whatever")
    assert result.outcome == "no_probe"
    assert result.verified is False


def test_every_variable_the_worker_reads_is_spelled_as_its_settings_field() -> None:
    """`voice_worker/boot.py`'s central promise, enforced instead of maintained by hand.

    Derived from the module rather than retyped: every `*_ENV` constant it declares, plus
    the per-provider LLM map, is either a `Settings` field spelled identically or one of
    the names registered in `check_env_parity` as deliberately not one. A drift here is a
    founder putting one value under two names and half the platform reading the wrong one.
    """
    from scripts.check_env_parity import CONTAINER_ENV_KEYS, SDK_ENV_KEYS
    from voice_worker import boot

    declared = {
        value
        for name, value in vars(boot).items()
        if name.endswith("_ENV") and isinstance(value, str)
    }
    declared |= set(boot.LLM_KEY_ENV_BY_PROVIDER.values())
    assert {"PLIVO_AUTH_ID", "PLIVO_AUTH_TOKEN"} <= declared

    misspelled = sorted(
        name
        for name in declared
        if name.lower() not in Settings.model_fields
        and name not in CONTAINER_ENV_KEYS
        and name not in SDK_ENV_KEYS
    )
    assert not misspelled, (
        f"{misspelled} are read by the voice worker under a name that is neither a "
        "Settings field nor a registered exception — one value, two names"
    )
