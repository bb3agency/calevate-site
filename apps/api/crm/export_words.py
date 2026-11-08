"""The owner's words for the stored keys a CSV export carries.

The exports are read by the owner and their staff in a spreadsheet, so a cell says what the
screen says: "Goal reached", not `hot`; "Incoming call", not `inbound_call`; "Call-back
booked", not `call_back_booked`. These maps are the server's twin of the web's
(`apps/web/src/lib/leadLabels.ts` SOURCE_LABELS, `apps/web/src/lib/callReview.ts`
OUTCOME_WORDS and STATUS_WORDS); `tests/export_words_test.py` holds the two in step.

An unknown key is written as it came, sentence-cased, rather than dropped: a value this build
has not heard of is still a fact about the row.
"""

from __future__ import annotations

from typing import Final

from apps.api.crm.lead_definition import stage_name

SOURCE_WORDS: Final[dict[str, str]] = {
    "inbound_call": "Incoming call",
    "outbound_call": "Outgoing call",
    "test_call": "Test call",
    "campaign": "Campaign",
    "webhook": "Website form",
    "manual": "Import",
}

OUTCOME_WORDS: Final[dict[str, str]] = {
    "needs_you": "Needs you",
    "call_back_booked": "Call-back booked",
    "answered": "Answered",
    "transferred": "Transferred",
    "hung_up_early": "Hung up early",
    "missed": "Missed",
}

CALL_STATUS_WORDS: Final[dict[str, str]] = {
    "completed": "Completed",
    "no_answer": "No answer",
    "busy": "Busy",
    "voicemail": "Voicemail",
    "failed": "Did not connect",
    "in_progress": "On the line",
    "queued": "Dialling",
    "ringing": "Ringing",
}


def _sentence(key: str) -> str:
    words = key.replace("_", " ")
    return words[:1].upper() + words[1:]


def _word(table: dict[str, str], key: str | None) -> str | None:
    if not key:
        return None
    return table.get(key) or _sentence(key)


def lead_stage(status: str | None) -> str | None:
    return stage_name(status) if status else None


def lead_source(source: str | None) -> str | None:
    return _word(SOURCE_WORDS, source)


def call_outcome(tag: str | None) -> str | None:
    return _word(OUTCOME_WORDS, tag)


def call_status(status: str | None) -> str | None:
    return _word(CALL_STATUS_WORDS, status)


__all__ = [
    "CALL_STATUS_WORDS",
    "OUTCOME_WORDS",
    "SOURCE_WORDS",
    "call_outcome",
    "call_status",
    "lead_source",
    "lead_stage",
]
