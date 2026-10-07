"""The engine intake key: what the webhook receiver may decrypt, and nothing else (D-678).

THE PROBLEM. ThinnestAI signs each delivery with a per-endpoint secret
(`thinnest-findings/mirror/pages/api-reference/webhooks.md:36-40`), so voice-runtime must
read that secret to verify a delivery before it acks. voice-runtime deliberately holds no
`PLATFORM_KEK` (`compose.prod.yml`: "THE KEK STAYS OUT OF THE INTERNET-FACING SERVICE"),
and the secret may not sit in the database in plaintext.

THE ANSWER: a second, narrower key, `ENGINE_INTAKE_KEK`, used for exactly two things —

* the per-endpoint webhook signing secret, sealed at registration and opened by the
  receiver to verify a delivery;
* a verified delivery's body, sealed by the receiver for the queue and opened by the
  worker. An inbound ThinnestAI call cannot be fetched by id (`get-call.md:51-52`), so the
  signed delivery is the only copy of its transcript and recording link, and it crosses
  Redis as ciphertext rather than as a caller's words (hard rule 6).

Holding it gives voice-runtime nothing it does not already see: it receives these bodies
in the clear and needs the secrets to check them. It does not open any vendor credential,
which stays under `PLATFORM_KEK`. Envelope encryption is `core/envelope.py`'s, reused with
a ring built here, so there is still one implementation of AES-GCM in the tree.

`Settings.engine_intake_kek` / `engine_intake_kek_retired` are env-only and are NOT blanked
for voice-runtime in `compose.prod.yml`. Outside `local` an unset key refuses by name, so
nothing seals or verifies under a key nobody configured.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from collections.abc import Mapping
from functools import lru_cache
from typing import Any, Final

from apps.api.core.envelope import Envelope, Kek, KekRing, seal, unseal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings

log = get_logger(__name__)

INTAKE_KEK_ENV: Final = "ENGINE_INTAKE_KEK"
INTAKE_KEK_RETIRED_ENV: Final = "ENGINE_INTAKE_KEK_RETIRED"
_KEY_BYTES: Final = 32
#: Public and `local`-only, domain-separated from `PLATFORM_KEK`'s development seed so the
#: two development keys are never the same bytes.
_LOCAL_SEED: Final = b"calevate-local-dev-engine-intake-kek/"


def _unusable(what: str) -> ProblemError:
    return ProblemError(
        kind="dependency",
        code="engine_intake_kek_unusable",
        title="The engine intake key is not usable",
        detail=f"{INTAKE_KEK_ENV} {what}.",
        remediation=(
            f"Set {INTAKE_KEK_ENV} to base64 of 32 random bytes on api, workers AND "
            'voice-runtime: python -c "import base64,os; '
            'print(base64.b64encode(os.urandom(32)).decode())"'
        ),
    )


def _decode(raw: str) -> bytes:
    try:
        material = base64.b64decode(raw.strip(), validate=True)
    except (binascii.Error, ValueError):
        raise _unusable("is not base64") from None
    if len(material) != _KEY_BYTES:
        raise _unusable(f"must decode to exactly {_KEY_BYTES} bytes")
    return material


def _kek(material: bytes) -> Kek:
    digest = hashlib.sha256(b"calevate/engine-intake-kek-id/v1\x00" + material).digest()
    return Kek(kek_id=int.from_bytes(digest[:4], "big") & 0x7FFFFFFF, material=material)


@lru_cache(maxsize=4)
def build_intake_ring(active: str | None, retired: str | None, app_env: str) -> KekRing:
    """The ring from configured strings. Pure and cached on its arguments, so a rotation
    yields a new ring rather than a stale one."""
    if active:
        material = _decode(active)
        if app_env != "local" and material == hashlib.sha256(_LOCAL_SEED + b"local").digest():
            raise _unusable("is the development key this repository publishes")
    elif app_env == "local":
        material = hashlib.sha256(_LOCAL_SEED + app_env.encode()).digest()
    else:
        raise _unusable("is not set")
    retired_keys: tuple[Kek, ...] = ()
    if retired:
        try:
            retired_keys = (_kek(_decode(retired)),)
        except ProblemError:
            # Survivable for `build_ring`'s reason: a broken retired key only loses the
            # ability to open rows not yet rewrapped.
            log.error(
                "engine_intake_kek_retired_unusable", extra={"env_var": INTAKE_KEK_RETIRED_ENV}
            )
    return KekRing(active=_kek(material), retired=retired_keys)


def intake_ring() -> KekRing:
    cfg = get_settings()
    return build_intake_ring(cfg.engine_intake_kek, cfg.engine_intake_kek_retired, cfg.app_env)


# --- webhook signing secrets ----------------------------------------------------------


def webhook_secret_context(engine: str, engine_agent_ref: str) -> str:
    """The AAD that binds a sealed secret to ONE route row, so it cannot be moved to
    another agent's row and verify that agent's deliveries."""
    return f"engine_webhook_secret:{engine}:{engine_agent_ref}"


def seal_webhook_secret(
    secret: str, *, engine: str, engine_agent_ref: str, ring: KekRing | None = None
) -> Envelope:
    return seal(
        secret,
        context=webhook_secret_context(engine, engine_agent_ref),
        ring=ring or intake_ring(),
    )


def open_webhook_secret(
    envelope: Envelope, *, engine: str, engine_agent_ref: str, ring: KekRing | None = None
) -> str:
    return unseal(
        envelope,
        context=webhook_secret_context(engine, engine_agent_ref),
        ring=ring or intake_ring(),
    )


# --- sealed deliveries ----------------------------------------------------------------

_DELIVERY_FIELDS: Final = ("ciphertext", "nonce", "dek_wrapped", "dek_nonce")


def delivery_context(engine: str, execution_id: str, event_name: str) -> str:
    """Binds a sealed body to the inbox unit it was claimed under."""
    return f"engine_delivery:{engine}:{execution_id}:{event_name}"


def seal_delivery(
    body: str, *, engine: str, execution_id: str, event_name: str, ring: KekRing | None = None
) -> dict[str, Any]:
    """A verified delivery body as a JSON-safe envelope for a job payload."""
    envelope = seal(
        body,
        context=delivery_context(engine, execution_id, event_name),
        ring=ring or intake_ring(),
    )
    sealed: dict[str, Any] = {
        name: base64.b64encode(getattr(envelope, name)).decode() for name in _DELIVERY_FIELDS
    }
    sealed["kek_id"] = envelope.kek_id
    sealed["event_name"] = event_name
    return sealed


def open_delivery(
    sealed: Mapping[str, Any], *, engine: str, execution_id: str, ring: KekRing | None = None
) -> bytes:
    """The delivery body, or a permanent `validation` refusal for a malformed envelope."""
    try:
        event_name = str(sealed["event_name"])
        envelope = Envelope(
            ciphertext=base64.b64decode(sealed["ciphertext"], validate=True),
            nonce=base64.b64decode(sealed["nonce"], validate=True),
            dek_wrapped=base64.b64decode(sealed["dek_wrapped"], validate=True),
            dek_nonce=base64.b64decode(sealed["dek_nonce"], validate=True),
            kek_id=int(sealed["kek_id"]),
        )
    except (KeyError, TypeError, ValueError, binascii.Error) as exc:
        raise ProblemError(
            kind="validation",
            code="engine_delivery_unreadable",
            title="A queued engine delivery could not be read",
            detail="The job carried a delivery envelope with fields missing or unreadable.",
        ) from exc
    return unseal(
        envelope,
        context=delivery_context(engine, execution_id, event_name),
        ring=ring or intake_ring(),
    ).encode()


__all__ = [
    "INTAKE_KEK_ENV",
    "INTAKE_KEK_RETIRED_ENV",
    "build_intake_ring",
    "delivery_context",
    "intake_ring",
    "open_delivery",
    "open_webhook_secret",
    "seal_delivery",
    "seal_webhook_secret",
    "webhook_secret_context",
]
