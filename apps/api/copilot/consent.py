"""Whether a client account has turned Pip on, and what that changes (D-788).

The founder's rule, 15 Oct 2026: Pip is OFF for a client account until its OWNER ticks a
short disclosure once, for the whole account. After that, Pip sends to its primary model,
unmasked, what the person types, the files they attach and what its look-up tools read
for them (lead phone numbers, contact details, raw call transcripts). Until then every
ask and every upload is refused with `consent_required`, so there is no masked mode on the
client realm to keep in step with the unmasked one.

The admin console's Pip never asks (`ADMIN_UNMASKED`): it is Calevate's own staff on
Calevate's own console, and the founder exempted it.

WHAT CONSENT DOES NOT CHANGE, and the code that holds each line:
* the standby leg (`service._answer_via_sarvam`) masks every message it sends, because
  that provider's terms permit training on what it receives (SECURITY-COMPLIANCE §4);
* Pip's long-term memories and a routine's instruction stay redacted on write
  (`memory.redacted_content`): data minimisation for what outlives the conversation;
* logs and traces carry no phone number, transcript text or extraction payload (hard
  rule 6);
* every raw transcript Pip reads writes the same `transcript.read_raw` audit row the
  dashboard's raw read writes (hard rule 5).

THE VERSIONING is the legal catalogue's, reused rather than re-invented: `DISCLOSURE` is a
`LegalDocumentSpec` whose revisions say which steps are material, and
`catalogue.reacceptance_required` decides whether a stored acceptance still holds. The
text the owner reads is served from here (the pledge's shape, `compliance/
outbound_pledge.py`), and an acceptance records its SHA-256, so "what did they agree to"
does not depend on this file never having been edited. A new revision whose text changed
but is NOT material keeps existing acceptances valid; a material one re-asks the owner.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.copilot.identity import ASSISTANT_NAME
from apps.api.copilot.schemas import CopilotConsentOut
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.legal.catalogue import LegalDocumentSpec, Revision, reacceptance_required

#: The disclosure's history. Not in `catalogue.DOCUMENTS`: it is not a published legal
#: page, it is the in-panel summary that links to them.
DISCLOSURE: Final = LegalDocumentSpec(
    slug="pip-disclosure",
    title=f"Turning on {ASSISTANT_NAME}",
    blocking=False,
    revisions=(
        Revision(
            revision="1",
            material=True,
            note="D-788: first version; the owner turns Pip on for the account.",
        ),
    ),
)

#: What the owner reads above the checkbox. Paragraphs are separated by a blank line,
#: which the panel preserves. No provider is named (D-679); the legal pages name them.
DISCLOSURE_TEXT: Final = (
    f"When {ASSISTANT_NAME} is on, what anyone on your team types to {ASSISTANT_NAME}, the "
    f"files they attach, and what {ASSISTANT_NAME} reads for them in this account, "
    "including leads' phone numbers, contact details and call transcripts, are sent to "
    f"the AI models that answer {ASSISTANT_NAME}, without masking personal details."
    "\n\n"
    f"By turning {ASSISTANT_NAME} on for everyone on this account, you confirm that your "
    "business has the right to share this data for this purpose and has told the people "
    "it belongs to, as our Terms of Service and Data Processing Addendum describe."
)

DISCLOSURE_TEXT_SHA256: Final = hashlib.sha256(DISCLOSURE_TEXT.encode("utf-8")).hexdigest()

#: The current version as stored on an acceptance row.
DISCLOSURE_VERSION: Final = DISCLOSURE.current_version

ConsentStatus = Literal["accepted", "required", "outdated", "not_required"]


@dataclass(frozen=True, slots=True)
class ConsentState:
    """The latest acceptance for one account, judged against the current disclosure."""

    status: ConsentStatus
    accepted_version: str | None
    accepted_at: datetime | None

    @property
    def unmasked(self) -> bool:
        """Pip may send this account's data to its primary model without masking."""
        return self.status in ("accepted", "not_required")


#: The admin console's state: exempt, never asked, never masked.
ADMIN_UNMASKED: Final = ConsentState(status="not_required", accepted_version=None, accepted_at=None)

_LATEST = (
    "SELECT disclosure_version, accepted_at FROM copilot_consents "
    "WHERE tenant_id = :tid ORDER BY accepted_at DESC, created_at DESC LIMIT 1"
)


async def read_consent(session: AsyncSession, *, tenant_id: UUID) -> ConsentState:
    """The account's consent, under RLS (the session must be this tenant's)."""
    row = (await session.execute(text(_LATEST), {"tid": tenant_id})).first()
    if row is None:
        return ConsentState(status="required", accepted_version=None, accepted_at=None)
    version = str(row[0])
    status: ConsentStatus = "outdated" if reacceptance_required(DISCLOSURE, version) else "accepted"
    return ConsentState(status=status, accepted_version=version, accepted_at=row[1])


def consent_required() -> ProblemError:
    """Pip is off for this account. Reached by an ask, an upload or a background task.

    The sentence serves both audiences without knowing which one is reading: the owner
    can act on it in the panel, and anyone else learns who can."""
    return ProblemError(
        kind="permission",
        code="copilot_consent_required",
        title=f"{ASSISTANT_NAME} is off for this account",
        detail=(
            f"The account owner needs to turn {ASSISTANT_NAME} on before anyone on the "
            f"account can use it."
        ),
        remediation=(
            f"If you are the account owner, open {ASSISTANT_NAME} and turn it on there. "
            "Otherwise, ask them to."
        ),
    )


async def require_consent(session: AsyncSession, *, tenant_id: UUID) -> ConsentState:
    """The account's consent, or `consent_required`. Returns the state so a caller can
    pass `unmasked` on without a second read."""
    state = await read_consent(session, tenant_id=tenant_id)
    if not state.unmasked:
        raise consent_required()
    return state


async def record_consent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    version: str,
    text_sha256: str,
    ip: str | None,
) -> UUID:
    """Append one acceptance of the CURRENT disclosure. A screen rendered before a new
    version cannot accept words the owner was never shown, so a stale version or hash is
    refused rather than recorded."""
    if version != DISCLOSURE_VERSION or text_sha256 != DISCLOSURE_TEXT_SHA256:
        raise ProblemError.conflict(
            "copilot_consent_outdated",
            f"What {ASSISTANT_NAME} shows before it is turned on has changed since this "
            "panel was opened.",
            remediation=f"Close {ASSISTANT_NAME}, open it again, read it and turn it on.",
        )
    consent_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO copilot_consents (id, tenant_id, disclosure_version, text_sha256, "
            "  accepted_by_user_id, ip, accepted_at, created_at) "
            "VALUES (:id, :tid, :version, :sha, :uid, :ip, now(), now())"
        ),
        {
            "id": consent_id,
            "tid": tenant_id,
            "version": version,
            "sha": text_sha256,
            "uid": user_id,
            "ip": ip,
        },
    )
    return consent_id


def consent_out(state: ConsentState, *, can_accept: bool) -> CopilotConsentOut:
    """The wire form. `can_accept` is the caller's to decide: it is about who is asking."""
    return CopilotConsentOut(
        status=state.status,
        version=DISCLOSURE_VERSION,
        text=DISCLOSURE_TEXT,
        text_sha256=DISCLOSURE_TEXT_SHA256,
        can_accept=can_accept and state.status in ("required", "outdated"),
        accepted_at=state.accepted_at,
    )


__all__ = [
    "ADMIN_UNMASKED",
    "DISCLOSURE",
    "DISCLOSURE_TEXT",
    "DISCLOSURE_TEXT_SHA256",
    "DISCLOSURE_VERSION",
    "ConsentState",
    "ConsentStatus",
    "consent_out",
    "consent_required",
    "read_consent",
    "record_consent",
    "require_consent",
]
