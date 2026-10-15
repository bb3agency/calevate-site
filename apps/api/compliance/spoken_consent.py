"""After the call: was the WhatsApp opt-in the agent reported actually said? (D-784)

During a call the voice agent asks "Shall I send this on WhatsApp to this number?" and the
WhatsApp action carries the caller's answer and words (`actions/whatsapp.SpokenConsent`). A
yes is appended to `consent_ledger` straight away, because the message goes while the
caller is still on the line. That yes is the MODEL's report, and a model can be wrong or be
talked into it, so once the transcript lands this module looks for the caller's reported
words in what the caller actually said on that call.

A grant whose words are not found is NOT withdrawn: `consent_ledger` is append-only (hard
rule 4) and a "withdrawn" row would claim the person withdrew, which they did not. It is
made loud instead: an `audit_log` entry naming the consent row and the
`whatsapp_spoken_consent_unconfirmed` alarm, so an operator reviews the call. What this
cannot catch is a real "yes" the caller gave to a DIFFERENT question, which the model then
reported against this one; that residual risk is stated in OPERATIONS gate W-8.

Matching is on redacted text on both sides (the stored words were redacted when recorded),
case- and punctuation-blind, any script: the words appear inside one caller turn, or at least
60% of their words appear in one caller turn (the transcript and the words the model passed
both come from the same speech recognition, but the model may trim or reorder them).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.workers.redaction import redact

log = get_logger(__name__)

UNCONFIRMED_ACTION: Final = "consent.spoken_unconfirmed"
MIN_WORD_OVERLAP: Final = 0.6
_SPACE: Final = re.compile(r"\s+")


def _normalize(value: str) -> str:
    kept = "".join(
        " " if unicodedata.category(ch).startswith(("P", "S")) else ch for ch in value.lower()
    )
    return _SPACE.sub(" ", kept).strip()


def words_were_said(words: str, caller_turns: Sequence[str]) -> bool:
    said = _normalize(words)
    if not said:
        return False
    wanted = said.split(" ")
    for turn in caller_turns:
        heard = _normalize(redact(turn).text)
        if not heard:
            continue
        if said in heard:
            return True
        present = set(heard.split(" "))
        if sum(1 for w in wanted if w in present) / len(wanted) >= MIN_WORD_OVERLAP:
            return True
    return False


async def check_call(
    session: AsyncSession, *, tenant_id: UUID, call_id: UUID, caller_turns: Sequence[str]
) -> int:
    """Check every in-call WhatsApp opt-in granted on this call. Returns how many were not
    found in the transcript. Re-runnable: one already flagged is not flagged twice."""
    rows = (
        await session.execute(
            text(
                "SELECT id, evidence FROM consent_ledger WHERE call_id = :cid "
                "AND consent_source = 'in_call_agent_question' AND status = 'granted'"
            ),
            {"cid": call_id},
        )
    ).all()
    unconfirmed = 0
    for consent_id, evidence in rows:
        words = str((evidence or {}).get("caller_words") or "")
        if words_were_said(words, caller_turns):
            log.info("whatsapp_spoken_consent_confirmed", extra={"consent_id": str(consent_id)})
            continue
        unconfirmed += 1
        already = (
            await session.execute(
                text("SELECT 1 FROM audit_log WHERE action = :a AND object_id = :o LIMIT 1"),
                {"a": UNCONFIRMED_ACTION, "o": str(consent_id)},
            )
        ).first()
        if already is not None:
            continue
        await write_audit(
            session,
            action=UNCONFIRMED_ACTION,
            actor_type="system",
            tenant_id=tenant_id,
            object_type="consent_ledger",
            object_id=str(consent_id),
            summary={"call_id": str(call_id), "transcript_turns": str(len(caller_turns))},
        )
        alert(
            "WORKER_DELIVERY",
            "whatsapp_spoken_consent_unconfirmed",
            detail=(
                "an in-call WhatsApp opt-in the agent reported was not found in the caller's "
                "words on that call. Review the call; if the caller did not agree, record a "
                "withdrawal on the Messaging consent screen."
            ),
            tenant_id=str(tenant_id),
            call_id=str(call_id),
        )
    return unconfirmed


__all__ = ["MIN_WORD_OVERLAP", "UNCONFIRMED_ACTION", "check_call", "words_were_said"]
