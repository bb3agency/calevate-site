"""The signed consent of a person whose voice we cloned, kept sealed (D-721).

A consent document names a real person and carries their signature, so the object in storage
is ciphertext under the platform key, never the document. One object per voice: a new
consent replaces it.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Final

from apps.api.core.envelope import Envelope, seal_bytes, unseal_bytes
from apps.api.core.errors import ProblemError

#: The kinds a signed document arrives as, by their leading bytes. A browser downloads it
#: back, so the type served is decided here and never taken from the upload's own header.
_KINDS: Final[tuple[tuple[bytes, str, str], ...]] = (
    (b"%PDF-", "application/pdf", "pdf"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
)
_UNSAFE_NAME: Final = re.compile(r"[\x00-\x1f\x7f/\\\"]+")
FILENAME_MAX: Final = 120


@dataclass(frozen=True, slots=True)
class ConsentDocument:
    filename: str
    content_type: str
    data: bytes


def _context(voice_id: str) -> str:
    return f"voice_consent:{voice_id}"


def accept_document(*, filename: str | None, data: bytes) -> ConsentDocument:
    """The upload as we will keep it, or a refusal naming what is wrong with it."""
    kind = next(((ctype, ext) for magic, ctype, ext in _KINDS if data.startswith(magic)), None)
    if kind is None:
        raise ProblemError(
            kind="validation",
            code="voice_consent_document_format",
            title="The consent document must be a PDF, JPEG or PNG",
            detail="The file you chose is not a PDF, JPEG or PNG.",
            remediation="Scan or save the signed consent as a PDF and upload that.",
        )
    content_type, ext = kind
    name = _UNSAFE_NAME.sub("", filename or "").strip()[:FILENAME_MAX] or f"consent.{ext}"
    return ConsentDocument(filename=name, content_type=content_type, data=data)


async def keep_consent_document(*, voice_id: str, document: ConsentDocument) -> str:
    """Seal and store one consent document; the object's key."""
    from apps.workers.storage import store_voice_consent, voice_consent_key

    envelope = seal_bytes(document.data, context=_context(voice_id))
    sealed = json.dumps(
        {
            "v": 1,
            "filename": document.filename,
            "content_type": document.content_type,
            "kek_id": envelope.kek_id,
            "nonce": base64.b64encode(envelope.nonce).decode(),
            "dek_wrapped": base64.b64encode(envelope.dek_wrapped).decode(),
            "dek_nonce": base64.b64encode(envelope.dek_nonce).decode(),
            "ciphertext": base64.b64encode(envelope.ciphertext).decode(),
        }
    ).encode()
    return await store_voice_consent(key=voice_consent_key(voice_id), data=sealed)


async def open_consent_document(*, voice_id: str, key: str) -> ConsentDocument | None:
    """The stored document, unsealed, or None when the object is gone."""
    from apps.workers.storage import read_voice_consent

    raw = await read_voice_consent(key)
    if raw is None:
        return None
    doc = json.loads(raw)
    envelope = Envelope(
        ciphertext=base64.b64decode(doc["ciphertext"]),
        nonce=base64.b64decode(doc["nonce"]),
        dek_wrapped=base64.b64decode(doc["dek_wrapped"]),
        dek_nonce=base64.b64decode(doc["dek_nonce"]),
        kek_id=int(doc["kek_id"]),
    )
    return ConsentDocument(
        filename=str(doc.get("filename") or "consent"),
        content_type=str(doc.get("content_type") or "application/pdf"),
        data=unseal_bytes(envelope, context=_context(voice_id)),
    )


__all__ = [
    "ConsentDocument",
    "accept_document",
    "keep_consent_document",
    "open_consent_document",
]
