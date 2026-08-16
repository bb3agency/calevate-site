"""`RESEND_API_KEY` comes from the ENVIRONMENT and from nowhere else.

The transport shipped with the key as a `platform_secrets` row — console-managed,
encrypted, rotatable from a browser, exactly like the Bolna and Sarvam keys. That is the
right home for a vendor credential in this repo (D-95, PLATFORM-CONFIG §5) and it is the
wrong home for THIS one, for a reason that has nothing to do with encryption:

**the process that has to send the most important email cannot reach the store.**
`scripts/host_alert.py` runs on the DATABASE host (D-26 puts Postgres on its own box),
opens no database connection, and is what pages a human when a backup fails or a disk
fills. It can only read this credential from its own environment. So the key is required
in an environment file no matter what the console holds — and "also offer it in the
console" is then not a convenience, it is TWO HOMES FOR ONE CREDENTIAL, where the
environment silently wins (`apply_platform_overrides`). The failure that buys is an
operator rotating the key on a screen, seeing it accepted, and watching mail keep going
out under the old one.

WHAT IS *NOT* ENV-ONLY, and the line matters: `EMAIL_PROVIDER`. It is a SELECTION rather
than a credential — turning email on, or falling back to SMTP because a Resend account is
suspended, is precisely the change D-95 built the console for. The api/worker hosts read
it from the store; the database host reads it from its own `EnvironmentFile`. One fact,
two hosts, no shared secret.
"""

from __future__ import annotations

from apps.api.core.platform_config import FIELD_APPLIES, managed_fields
from apps.api.core.settings import ENV_ONLY_DISPLAY, ENV_ONLY_KEYS, ENV_ONLY_REASONS
from apps.api.ops.secret_probes import PROBES
from apps.api.ops.secret_service import manageable_secret_keys
from calevate_shared.config import Settings

KEY = "resend_api_key"


def test_the_key_is_env_only() -> None:
    assert KEY in ENV_ONLY_KEYS
    assert KEY in ENV_ONLY_REASONS, "env-only WITHOUT being bootstrap — a distinct category"
    assert KEY in Settings.model_fields, "an entry naming no field protects nothing"


def test_neither_console_surface_offers_it() -> None:
    """Both, because a key excluded from one and offered by the other is worse than a key
    offered by both: it looks managed and is not."""
    assert KEY not in managed_fields(), "the config surface would let it be typed as plain text"
    assert KEY not in manageable_secret_keys(), "the secrets surface would store a second copy"
    assert KEY not in FIELD_APPLIES, (
        "an APPLIES rule describes when a STORED value takes effect — a key that cannot "
        "be stored having one is a claim about a path that does not exist"
    )


def test_the_console_still_explains_it_rather_than_hiding_it() -> None:
    """ABSENCE IS NOT AN EXPLANATION — `BOOTSTRAP_REASONS` was written for this exact
    problem and this key inherits it. An operator looking for the Resend key must not have
    to tell "this build does not have it" from "this one cannot be set here"."""
    assert KEY in ENV_ONLY_DISPLAY
    reason = ENV_ONLY_DISPLAY[KEY]
    assert "RESEND_API_KEY" in reason, "the reason must name the variable to set"
    assert len(reason) > 80, "a reason too thin to act on is not an explanation"


def test_it_can_still_be_tested_even_though_it_cannot_be_stored() -> None:
    """`POST /v1/ops/secrets/{key}/test` takes a candidate and stores nothing, so it is
    the one chance to catch a wrong key BEFORE it goes into a host's environment and a
    deploy. Removing the probe alongside the storage would have thrown that away."""
    assert KEY in PROBES


def test_the_selector_is_not_swept_up_with_the_credential() -> None:
    """The line this whole change rests on. `email_provider` must stay console-managed, or
    an operator cannot switch to SMTP during a Resend outage without a deploy."""
    assert "email_provider" not in ENV_ONLY_KEYS
    assert "email_provider" in managed_fields()
