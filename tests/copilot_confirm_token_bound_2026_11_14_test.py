"""A script suggestion written in Telugu can be confirmed.

Production, 14 Nov 2026: the founder approved Pip's suggestion for Varsha's script and read
"Token can be at most 4096 characters". The confirm token carries the signed request, and a
JWT escapes each Telugu letter as six characters before base64 grows it by a third, so a
long Telugu request could never be confirmed. Each test signs the longest words a
suggestion can carry, in an Indic script, with the token's real claims.
"""

from __future__ import annotations

import uuid

import jwt
from apps.api.agents.script_proposals import MAX_ANSWER_CHARS, MAX_CHANGE_CHARS
from apps.api.copilot.schemas import MAX_CONFIRM_TOKEN_CHARS, CopilotConfirmIn
from apps.api.copilot.write_tools import ACTOR_CLAIM, PROPOSAL_ALGORITHM, PROPOSAL_AUDIENCE
from apps.workers.script_assist import OWNER_QUESTIONS

#: One Telugu letter, generated rather than typed: the worst case for JSON escaping.
LETTER = chr(0x0C35)


def _token(args: dict[str, object]) -> str:
    claims = {
        "aud": PROPOSAL_AUDIENCE,
        "sub": str(uuid.uuid4()),
        ACTOR_CLAIM: {"sub": str(uuid.uuid4())},
        "jti": str(uuid.uuid4()),
        "iat": 1_800_000_000,
        "exp": 1_800_000_900,
        "tool": "suggest_script_change",
        "args": args,
        "obj": str(uuid.uuid4()),
    }
    return jwt.encode(claims, b"k" * 32, algorithm=PROPOSAL_ALGORITHM)


def test_the_longest_telugu_change_request_can_be_confirmed() -> None:
    """FAILS IF: a change request at its full length in Telugu makes a token the confirm
    route refuses (4,096 did)."""
    token = _token(
        {
            "agent_id": str(uuid.uuid4()),
            "mode": "change",
            "change": LETTER * MAX_CHANGE_CHARS,
            "answers": None,
        }
    )
    assert len(token) > 4_096
    assert CopilotConfirmIn(token=token).token == token


def test_a_whole_script_from_the_longest_telugu_answers_can_be_confirmed() -> None:
    """FAILS IF: every owner answer at its full length in Telugu no longer fits."""
    token = _token(
        {
            "agent_id": str(uuid.uuid4()),
            "mode": "whole",
            "change": None,
            "answers": dict.fromkeys(OWNER_QUESTIONS, LETTER * MAX_ANSWER_CHARS),
        }
    )
    assert len(token) <= MAX_CONFIRM_TOKEN_CHARS
    assert CopilotConfirmIn(token=token).token == token
