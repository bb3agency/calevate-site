"""The files a client uploads for KYC (D-692), and how long each is kept.

THE BUSINESS CERTIFICATE — required on both paths, kept while the account is active.
DigiLocker verifies the OWNER; it does not yield the business's own certificate, and the
numbering application a client's numbers are rented under needs exactly one: the GST
certificate when the business is registered for GST, otherwise its Certificate of
Incorporation or Udyam certificate — PDF, JPEG or PNG, at most 5 MB, a filename of at most
99 characters (thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/
phone-numbers/send-business-details.md:496-528, VERIFIED-VENDOR-DOCS). `kind` is that
page's `documentKind`, so `kyc.numbering_submission_bundle` hands the next caller a value
it can send unchanged. It is kept so it can be submitted and resubmitted, and is deleted
when the account is erased (`workers/retention.execute_tenant_erasure`).

THE OWNER'S ID — manual path only, an Aadhaar or a PAN card, kept only until a reviewer
decides. The founder's rule (8 Oct 2026): the file is deleted once an admin approves or
rejects (`purge_owner_id`), and one never decided is deleted after `OWNER_ID_MAX_HOLD`
(`workers/kyc_owner_id_purge`). What survives is the result and the MASKED identifier
the client typed (`mask_pan`, `mask_aadhaar`). An Aadhaar upload must be the masked copy
UIDAI issues; we cannot reliably tell a masked image from an unmasked one, so that rests
on the client copy and the reviewer's instruction to reject an unmasked one.

ENCRYPTED BEFORE IT LEAVES THE PROCESS. Every file is sealed with `core/envelope.
seal_bytes` under a fresh DEK, wrapped by the platform KEK, with the tenant and document id
as AAD (`document_context`) — so a copied object cannot be opened as another tenant's or
another row's — and the store's own SSE applies on top. The four envelope fields live on
the row; the object holds only ciphertext.

The type is decided from the file's BYTES and its extension together, never from the
client's declared Content-Type.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.envelope import Envelope, seal_bytes, unseal_bytes
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of

log = get_logger(__name__)

DocumentSlot = Literal["business", "owner_id"]
OwnerIdType = Literal["aadhaar", "pan"]

#: The numbering application's `documentKind` values (send-business-details.md:513-522).
BUSINESS_DOCUMENT_KINDS: Final = ("gst", "incorporation", "udyam")
#: The owner IDs the founder accepts (8 Oct 2026). `kind` -> the ID type it proves.
OWNER_ID_KINDS: Final[dict[str, OwnerIdType]] = {"aadhaar": "aadhaar", "pan_card": "pan"}

KYC_MAX_DOCUMENT_BYTES: Final = 5 * 1024 * 1024
KYC_MAX_FILENAME_CHARS: Final = 99

#: How long an owner-ID file nobody decided on is kept. Thirty days covers a client who
#: uploads and comes back to finish within the month, and a review backlog several times
#: longer than one should ever be; past it the file is serving no review and is deleted.
OWNER_ID_MAX_HOLD: Final = timedelta(days=30)

#: The Income Tax Department's PAN shape: five letters, four digits, one letter.
PAN_PATTERN: Final = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")

#: Extension -> (content type, the leading bytes that type's files start with).
_TYPES: Final[dict[str, tuple[str, tuple[bytes, ...]]]] = {
    "pdf": ("application/pdf", (b"%PDF-",)),
    "jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
}

_UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f/\\]+")


def _refuse(code: str, title: str, detail: str, remediation: str) -> ProblemError:
    return ProblemError(
        kind="validation", code=code, title=title, detail=detail, remediation=remediation
    )


# --- identifiers ------------------------------------------------------------------------


def mask_pan(pan: str) -> str:
    """`ABCDE1234F` -> `XXXXX1234X`, after checking the shape. The full PAN is not kept:
    nothing downstream needs it, and the reviewer compares the visible digits."""
    cleaned = pan.strip().upper()
    if not PAN_PATTERN.fullmatch(cleaned):
        raise _refuse(
            "kyc_pan_format_invalid",
            "That is not a valid PAN",
            "A PAN is five letters, four digits and a letter, like ABCDE1234F.",
            "Check the PAN on the card and type it again.",
        )
    return f"XXXXX{cleaned[5:9]}X"


def mask_aadhaar(last_four: str) -> str:
    """The last four digits only -> `XXXX-XXXX-1234`. We never ask for the full number."""
    cleaned = last_four.strip()
    if not re.fullmatch(r"[0-9]{4}", cleaned):
        raise _refuse(
            "kyc_aadhaar_last_four_invalid",
            "Enter only the last four digits of the Aadhaar",
            "We never take a full Aadhaar number — only its last four digits.",
            "Type the four digits at the end of the Aadhaar number.",
        )
    return f"XXXX-XXXX-{cleaned}"


def masked_owner_id(*, id_type: OwnerIdType, value: str) -> str:
    return mask_pan(value) if id_type == "pan" else mask_aadhaar(value)


# --- uploads ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AcceptedFile:
    """An upload that passed every check, ready to seal and store."""

    filename: str
    suffix: str
    content_type: str
    size_bytes: int
    sha256: str


def accept_upload(*, filename: str, data: bytes) -> AcceptedFile:
    """Validate one upload against the type, size and filename limits, or refuse it."""
    if not data:
        raise _refuse(
            "kyc_document_empty",
            "That file is empty",
            "The file you chose has no content.",
            "Choose the scanned or downloaded document and try again.",
        )
    if len(data) > KYC_MAX_DOCUMENT_BYTES:
        raise _refuse(
            "kyc_document_too_large",
            "That file is too large",
            "Verification documents can be up to 5 MB.",
            "Send a smaller scan or a compressed PDF.",
        )
    cleaned = _UNSAFE_NAME.sub("", filename or "").strip()
    if not cleaned:
        raise _refuse(
            "kyc_document_filename_required",
            "That file has no usable name",
            "The file needs a name we can show back to you.",
            "Rename it to something like 'gst-certificate.pdf' and try again.",
        )
    if len(cleaned) > KYC_MAX_FILENAME_CHARS:
        raise _refuse(
            "kyc_document_filename_too_long",
            "That filename is too long",
            f"Filenames can be up to {KYC_MAX_FILENAME_CHARS} characters.",
            "Shorten the filename and try again.",
        )
    _, _, raw_suffix = cleaned.rpartition(".")
    suffix = raw_suffix.lower()
    spec = _TYPES.get(suffix)
    if spec is None:
        raise _refuse(
            "kyc_document_type_unsupported",
            "That file type is not accepted",
            "Verification documents must be a PDF, JPEG or PNG.",
            "Save the document as a PDF, or photograph it and save it as JPEG or PNG.",
        )
    content_type, signatures = spec
    if not any(data.startswith(signature) for signature in signatures):
        raise _refuse(
            "kyc_document_content_mismatch",
            "That file is not what its name says",
            "The file's contents do not match its extension.",
            "Export the document again as a PDF, JPEG or PNG and upload that file.",
        )
    return AcceptedFile(
        filename=cleaned,
        suffix="jpg" if suffix == "jpeg" else suffix,
        content_type=content_type,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def assert_kind_fits_slot(*, slot: str, kind: str) -> DocumentSlot:
    """The slot/kind pairing the CHECK constraint enforces, refused with a sentence first."""
    if slot == "business" and kind in BUSINESS_DOCUMENT_KINDS:
        return "business"
    if slot == "owner_id" and kind in OWNER_ID_KINDS:
        return "owner_id"
    raise _refuse(
        "kyc_document_kind_unknown",
        "That document type is not one we accept here",
        "Business certificate: GST, incorporation or Udyam. Owner ID: Aadhaar (masked) or "
        "PAN card.",
        "Choose one of the listed document types.",
    )


def document_context(tenant_id: UUID, document_id: UUID) -> str:
    """The AAD a KYC file is sealed under. ONE definition; binds tenant and row."""
    return f"kyc_document:{tenant_id}:{document_id}"


def seal_document(*, tenant_id: UUID, document_id: UUID, data: bytes) -> Envelope:
    return seal_bytes(data, context=document_context(tenant_id, document_id))


def open_document(*, tenant_id: UUID, document_id: UUID, envelope: Envelope) -> bytes:
    """The plaintext of one stored file. In memory for the caller's request only."""
    return unseal_bytes(envelope, context=document_context(tenant_id, document_id))


# --- rows -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KycDocumentRow:
    id: UUID
    slot: str
    kind: str
    object_key: str
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime
    purged_at: datetime | None
    payload_nonce: bytes
    dek_wrapped: bytes
    dek_nonce: bytes
    kek_version: int

    def envelope(self, ciphertext: bytes) -> Envelope:
        return Envelope(
            ciphertext=ciphertext,
            nonce=self.payload_nonce,
            dek_wrapped=self.dek_wrapped,
            dek_nonce=self.dek_nonce,
            kek_id=self.kek_version,
        )


_CURRENT = (
    "SELECT id, slot, kind, object_key, filename, content_type, size_bytes, created_at, "
    "purged_at, payload_nonce, dek_wrapped, dek_nonce, kek_version FROM kyc_documents "
    "WHERE tenant_id = :tid AND superseded_at IS NULL ORDER BY slot"
)


async def current_documents(session: AsyncSession, *, tenant_id: UUID) -> dict[str, KycDocumentRow]:
    """This tenant's current document per slot, keyed by slot. RLS-scoped session."""
    rows = (await session.execute(text(_CURRENT), {"tid": tenant_id})).all()
    return {
        str(row[1]): KycDocumentRow(
            id=row[0],
            slot=str(row[1]),
            kind=str(row[2]),
            object_key=str(row[3]),
            filename=str(row[4]),
            content_type=str(row[5]),
            size_bytes=int(row[6]),
            created_at=row[7],
            purged_at=row[8],
            payload_nonce=bytes(row[9]),
            dek_wrapped=bytes(row[10]),
            dek_nonce=bytes(row[11]),
            kek_version=int(row[12]),
        )
        for row in rows
    }


async def record_document(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    slot: DocumentSlot,
    kind: str,
    object_key: str,
    accepted: AcceptedFile,
    sealed: Envelope,
    uploaded_by_user_id: UUID,
) -> list[str]:
    """Supersede the slot's current row and insert the new one, in the caller's
    transaction. Returns the object keys of superseded rows whose bytes are still held, for
    the caller to delete once this commits — only the current file of a slot is kept.

    Supersede-then-insert under the partial unique index: two concurrent uploads to one
    slot cannot both become current; the loser's INSERT fails on the index.
    """
    superseded = (
        await session.execute(
            text(
                "UPDATE kyc_documents SET superseded_at = now(), purged_at = now(), "
                "  updated_at = now() "
                "WHERE tenant_id = :tid AND slot = :slot AND superseded_at IS NULL "
                "RETURNING object_key"
            ),
            {"tid": tenant_id, "slot": slot},
        )
    ).all()
    await session.execute(
        text(
            "INSERT INTO kyc_documents (id, tenant_id, slot, kind, object_key, filename, "
            "  content_type, size_bytes, sha256, uploaded_by_user_id, payload_nonce, "
            "  dek_wrapped, dek_nonce, kek_version, created_at, updated_at) "
            "VALUES (:id, :tid, :slot, :kind, :key, :filename, :ctype, :size, :sha, :uid, "
            "  :pn, :dw, :dn, :kv, now(), now())"
        ),
        {
            "id": document_id,
            "tid": tenant_id,
            "slot": slot,
            "kind": kind,
            "key": object_key,
            "filename": accepted.filename,
            "ctype": accepted.content_type,
            "size": accepted.size_bytes,
            "sha": accepted.sha256,
            "uid": uploaded_by_user_id,
            "pn": sealed.nonce,
            "dw": sealed.dek_wrapped,
            "dn": sealed.dek_nonce,
            "kv": sealed.kek_id,
        },
    )
    return [str(row[0]) for row in superseded]


def new_document_id() -> UUID:
    return uuid7()


async def mark_purged(session: AsyncSession, *, document_id: UUID) -> bool:
    """Record that a document's bytes were deleted. False if it was already purged."""
    result = await session.execute(
        text(
            "UPDATE kyc_documents SET purged_at = now(), updated_at = now() "
            "WHERE id = :id AND purged_at IS NULL"
        ),
        {"id": document_id},
    )
    return rowcount_of(result) == 1


async def purge_owner_id(session: AsyncSession, *, tenant_id: UUID) -> str | None:
    """Mark this tenant's held owner-ID file purged and return its object key, for the
    caller to delete. Called when a reviewer decides; None when there is nothing held."""
    row = (
        await session.execute(
            text(
                "UPDATE kyc_documents SET purged_at = now(), updated_at = now() "
                "WHERE tenant_id = :tid AND slot = 'owner_id' AND purged_at IS NULL "
                "RETURNING object_key"
            ),
            {"tid": tenant_id},
        )
    ).first()
    return str(row[0]) if row is not None else None


__all__ = [
    "BUSINESS_DOCUMENT_KINDS",
    "KYC_MAX_DOCUMENT_BYTES",
    "KYC_MAX_FILENAME_CHARS",
    "OWNER_ID_KINDS",
    "OWNER_ID_MAX_HOLD",
    "PAN_PATTERN",
    "AcceptedFile",
    "DocumentSlot",
    "KycDocumentRow",
    "OwnerIdType",
    "accept_upload",
    "assert_kind_fits_slot",
    "current_documents",
    "delete_quietly",
    "document_context",
    "mark_purged",
    "mask_aadhaar",
    "mask_pan",
    "masked_owner_id",
    "new_document_id",
    "open_document",
    "purge_owner_id",
    "record_document",
    "seal_document",
]


async def delete_quietly(keys: list[str]) -> None:
    """Delete objects whose rows already say they are gone, after the transaction that
    said so committed. A failure is logged, not raised: the row is already purged and the
    account-closure sweep still removes anything left under the tenant's prefix."""
    from apps.workers.storage import StorageUnavailableError, delete_objects

    try:
        await delete_objects(keys)
    except StorageUnavailableError:
        log.warning("kyc_document_delete_failed", extra={"count": len(keys)})
