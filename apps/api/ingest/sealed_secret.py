"""Inbound lead-source secrets, sealed at rest (D-735).

`inbound_webhooks.secret_ref` and `previous_secret_ref` hold the credential a lead source
presents, and for a Meta Lead Ads source the client's own App Secret. They were stored in
plaintext, so a database read (a backup, a replica, a stray `SELECT`) handed out every
client's credentials. They are now sealed with the platform envelope (`core/envelope.seal`,
AES-256-GCM under a per-value DEK wrapped by `PLATFORM_KEK`), the mechanism the voice-consent
documents and the integration credentials use, and stored in the same text column as
`sealed:v1:<base64url JSON>`.

The context binds the ciphertext to its tenant and source, so a sealed value copied onto
another row does not open. Both columns of one row share it: a rotation moves the current
value into `previous_secret_ref` in SQL, without unsealing.

`open_source_secret` still accepts a plaintext value, so a row written before migration
`b7e2c9d4a1f3` (or by an older release during the rollout) keeps verifying; the migration
seals every existing row and its downgrade restores plaintext.
"""

from __future__ import annotations

import base64
import json
from typing import Final
from uuid import UUID

from apps.api.core.envelope import Envelope, seal, unseal

SEALED_PREFIX: Final = "sealed:v1:"

_FIELDS: Final = ("ciphertext", "nonce", "dek_wrapped", "dek_nonce")


def source_secret_context(tenant_id: UUID | str, webhook_id: UUID | str) -> str:
    return f"inbound_webhook_secret:{tenant_id}:{webhook_id}"


def is_sealed(stored: str | None) -> bool:
    return bool(stored) and str(stored).startswith(SEALED_PREFIX)


def seal_source_secret(secret: str, *, tenant_id: UUID | str, webhook_id: UUID | str) -> str:
    """The stored form of one lead-source secret."""
    envelope = seal(secret, context=source_secret_context(tenant_id, webhook_id))
    body: dict[str, str | int] = {
        name: base64.b64encode(getattr(envelope, name)).decode() for name in _FIELDS
    }
    body["kek_id"] = envelope.kek_id
    packed = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode())
    return SEALED_PREFIX + packed.decode()


def open_source_secret(
    stored: str | None, *, tenant_id: UUID | str, webhook_id: UUID | str
) -> str | None:
    """The secret a stored value holds; a plaintext value (pre-D-735) is returned as is."""
    if stored is None:
        return None
    if not stored.startswith(SEALED_PREFIX):
        return stored
    body = json.loads(base64.urlsafe_b64decode(stored[len(SEALED_PREFIX) :]))
    envelope = Envelope(
        ciphertext=base64.b64decode(body["ciphertext"]),
        nonce=base64.b64decode(body["nonce"]),
        dek_wrapped=base64.b64decode(body["dek_wrapped"]),
        dek_nonce=base64.b64decode(body["dek_nonce"]),
        kek_id=int(body["kek_id"]),
    )
    return unseal(envelope, context=source_secret_context(tenant_id, webhook_id))


__all__ = [
    "SEALED_PREFIX",
    "is_sealed",
    "open_source_secret",
    "seal_source_secret",
    "source_secret_context",
]
