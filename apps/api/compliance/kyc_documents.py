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

THE OWNER'S ID — manual path only, the owner's PAN card, kept only until a reviewer
decides. The founder's rule (8 Oct 2026): the file is deleted once an admin approves or
rejects (`request_owner_id_deletion`, then `delete_requested_documents`), and one never
decided is deleted after `OWNER_ID_MAX_HOLD` (`workers/kyc_owner_id_purge`, which also
retries every requested deletion that has not yet succeeded). What survives is the result
and the MASKED PAN the client typed (`mask_pan`).

NO AADHAAR COPY ON THIS PATH (D-696). Aadhaar (Authentication and Offline Verification)
Regulations 2021, reg. 16C(1), bars accepting an Aadhaar "in physical or electronic form
(without authentication), as a proof of identity" without first verifying UIDAI's signature
on its Secure QR code or offline e-KYC XML (docs/evidence/aadhaar-offline-and-pan-
verification-2026-10-09.md). We do not verify that signature, so a reviewer looking at an
Aadhaar image is exactly what the regulation forbids, masked copy or not. Aadhaar stays
available through DigiLocker, where the licensed provider carries the UIDAI obligations.
`kind = 'aadhaar'` survives only on rows uploaded before D-696; migration c5e9a2d71b48
requested their deletion and its CHECK keeps any held one on its way out.

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

#: The numbering application's `documentKind` values (send-business-details.md:513-522).
BUSINESS_DOCUMENT_KINDS: Final = ("gst", "incorporation", "udyam")
#: The owner IDs the manual path accepts: the PAN card only (D-696). `kind` -> the ID type
#: it proves, which is what the client types at submit.
OWNER_ID_KINDS: Final[dict[str, str]] = {"pan_card": "pan"}
#: The owner-ID kind the manual path took before D-696. Refused with its own sentence, so a
#: client holding an Aadhaar copy is told what to send instead.
RETIRED_AADHAAR_KIND: Final = "aadhaar"

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


def aadhaar_copy_not_accepted() -> ProblemError:
    """The refusal for an Aadhaar copy on the manual path (D-696), one wording for the
    upload and the submit."""
    return _refuse(
        "kyc_aadhaar_copy_not_accepted",
        "Please upload your PAN card instead",
        "We can no longer accept a copy of an Aadhaar card when we check your documents "
        "ourselves. The owner's PAN card is the ID we check.",
        "Upload a clear photo or scan of the owner's PAN card and type its PAN.",
    )


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
    if slot == "owner_id" and kind == RETIRED_AADHAAR_KIND:
        raise aadhaar_copy_not_accepted()
    raise _refuse(
        "kyc_document_kind_unknown",
        "That document type is not one we accept here",
        "Business certificate: GST, incorporation or Udyam. Owner ID: PAN card.",
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
    delete_requested_at: datetime | None
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

    @property
    def held(self) -> bool:
        """The file is ours to use: neither deleted nor due for deletion."""
        return self.purged_at is None and self.delete_requested_at is None


_CURRENT = (
    "SELECT id, slot, kind, object_key, filename, content_type, size_bytes, created_at, "
    "purged_at, payload_nonce, dek_wrapped, dek_nonce, kek_version, delete_requested_at "
    "FROM kyc_documents "
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
            delete_requested_at=row[13],
        )
        for row in rows
    }


@dataclass(frozen=True, slots=True)
class PendingDeletion:
    """A file whose deletion was requested in a transaction that has committed."""

    document_id: UUID
    object_key: str


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
) -> list[PendingDeletion]:
    """Supersede the slot's current row and insert the new one, in the caller's
    transaction. Returns the superseded files still held, whose deletion this requested, for
    the caller to delete once this commits (`delete_requested_documents`) — only the current
    file of a slot is kept.

    Supersede-then-insert under the partial unique index: two concurrent uploads to one
    slot cannot both become current; the loser's INSERT fails on the index.
    """
    superseded = (
        await session.execute(
            text(
                "UPDATE kyc_documents SET superseded_at = now(), "
                "  delete_requested_at = COALESCE(delete_requested_at, now()), "
                "  updated_at = now() "
                "WHERE tenant_id = :tid AND slot = :slot AND superseded_at IS NULL "
                "RETURNING id, object_key, purged_at IS NULL"
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
    return [
        PendingDeletion(document_id=row[0], object_key=str(row[1])) for row in superseded if row[2]
    ]


def new_document_id() -> UUID:
    return uuid7()


async def mark_purged(session: AsyncSession, *, document_id: UUID) -> bool:
    """Record that a document's bytes were deleted. Call only AFTER the object delete
    succeeded. False if it was already purged."""
    result = await session.execute(
        text(
            "UPDATE kyc_documents SET purged_at = now(), "
            "  delete_requested_at = COALESCE(delete_requested_at, now()), updated_at = now() "
            "WHERE id = :id AND purged_at IS NULL"
        ),
        {"id": document_id},
    )
    return rowcount_of(result) == 1


async def request_owner_id_deletion(
    session: AsyncSession, *, tenant_id: UUID
) -> PendingDeletion | None:
    """Request deletion of this tenant's held owner-ID file, for the caller to delete once
    this commits. Called when a reviewer decides; None when there is nothing held.

    It does NOT mark the file purged: that is written only after the delete succeeds, so a
    delete that fails leaves a row the nightly purge retries."""
    row = (
        await session.execute(
            text(
                "UPDATE kyc_documents SET delete_requested_at = COALESCE(delete_requested_at, "
                "  now()), updated_at = now() "
                "WHERE tenant_id = :tid AND slot = 'owner_id' AND purged_at IS NULL "
                "RETURNING id, object_key"
            ),
            {"tid": tenant_id},
        )
    ).first()
    return PendingDeletion(document_id=row[0], object_key=str(row[1])) if row else None


async def delete_requested_documents(tenant_id: UUID, pending: list[PendingDeletion]) -> None:
    """Delete files whose deletion a committed transaction requested, then mark each purged.

    For a background task after the request committed. A failure is logged and not raised:
    the rows still say "requested, not purged", which is exactly what the nightly purge
    selects and retries (`workers/kyc_owner_id_purge`), alarming if it gives up."""
    from apps.api.db.session import tenant_session
    from apps.workers.storage import StorageUnavailableError, delete_objects

    try:
        await delete_objects([item.object_key for item in pending])
    except StorageUnavailableError:
        log.warning("kyc_document_delete_failed", extra={"count": len(pending)})
        return
    async with tenant_session(tenant_id) as session:
        for item in pending:
            await mark_purged(session, document_id=item.document_id)


__all__ = [
    "BUSINESS_DOCUMENT_KINDS",
    "KYC_MAX_DOCUMENT_BYTES",
    "KYC_MAX_FILENAME_CHARS",
    "OWNER_ID_KINDS",
    "OWNER_ID_MAX_HOLD",
    "PAN_PATTERN",
    "RETIRED_AADHAAR_KIND",
    "AcceptedFile",
    "DocumentSlot",
    "KycDocumentRow",
    "PendingDeletion",
    "aadhaar_copy_not_accepted",
    "accept_upload",
    "assert_kind_fits_slot",
    "current_documents",
    "delete_requested_documents",
    "document_context",
    "mark_purged",
    "mask_pan",
    "new_document_id",
    "open_document",
    "record_document",
    "request_owner_id_deletion",
    "seal_document",
]
