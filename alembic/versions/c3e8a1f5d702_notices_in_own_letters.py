"""The opening notices: every word in the language's own letters, and the memory sentence reworded (D-861)

Revision ID: c3e8a1f5d702
Revises: e8c4b1d7a352
Create Date: 2026-10-23 18:00:00.000000

Founder decisions, 23 Oct 2026:

- the memory sentence says why, then what, and is spoken after the greeting;
- a Telugu or Hindi spoken line writes EVERY word in the language's own letters, the English
  words people use too, reversing the 11 Oct 2026 English-letters rule.

`compliance/disclosure` carries the new wording for agents created from now on. This rewrites
the stored lines of every existing agent ONLY where a line is exactly a previous default
(the business name inside the AI sentence is kept as the line has it), so a line an owner or
operator edited is left alone:

    te AI      "ఇది X AI assistant." / "Idi X AI assistant." / "Namaskaram, idi X AI assistant."
               -> "ఇది X ఏఐ అసిస్టెంట్."
    te record  "ఈ call record అవుతుంది." / "Ee call record avutundi."
               -> "ఈ కాల్ రికార్డ్ అవుతుంది."
    te memory  "మీరు అడిగిన దాని గురించి ఒక చిన్న note గుర్తు పెట్టుకుంటాను." / its Latin-letter form
               -> "మీరు మళ్ళీ కాల్ చేసినప్పుడు గుర్తుండేలా, ఈ కాల్ గురించి ఒక చిన్న నోట్ ఉంచుకుంటాను."

and the same for Hindi in Devanagari, the reworded memory sentence in English and the staged
languages, and the legacy bundle `agents.disclosure_line` (AI sentence, a space, recording
sentence).

When a live agent holds a line this rewrites, ONE platform live-apply run is queued (D-720),
so every live agent is republished once from the rewritten rows. The deploy that carries this
also moves the platform-prompt revision (the greeting now comes before the notices), and the
worker-start run (D-739) joins a pending run rather than walking the fleet twice.

DOWNGRADE writes the wording this replaced (Telugu and Hindi script with the English words in
Latin letters, the previous memory sentence) back on lines that exactly match the new
defaults; it queues nothing (a later publish or the drift repair carries it).
"""

from collections.abc import Sequence
from logging import getLogger

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "c3e8a1f5d702"
down_revision: str | None = "e8c4b1d7a352"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")

#: The reason the queued run records, shown to operators on the live-apply screen.
REASON = "notices_in_own_letters"

#: Today's defaults. Copied rather than imported from `compliance/disclosure`, so this file
#: keeps meaning what it meant on the day it ran; `tests/notices_in_own_letters_test.py`
#: compares them.
TE_AI = r"ఇది \2 ఏఐ అసిస్టెంట్."
TE_RECORDING = "ఈ కాల్ రికార్డ్ అవుతుంది."
TE_MEMORY = "మీరు మళ్ళీ కాల్ చేసినప్పుడు గుర్తుండేలా, ఈ కాల్ గురించి ఒక చిన్న నోట్ ఉంచుకుంటాను."
HI_AI = r"मैं \2 का एआई असिस्टेंट हूँ।"
HI_RECORDING = "यह कॉल रिकॉर्ड हो रही है।"
HI_MEMORY = "आप दोबारा कॉल करें तो याद रहे, इसलिए हम इस कॉल का एक छोटा नोट रखते हैं।"

#: (previous exact default, new default) per language for the sentences with no business
#: name. The memory sentence's earlier Latin-letter defaults (before D-745) are here too, for
#: an agent that still holds one.
_EXACT: dict[str, tuple[tuple[str, str], ...]] = {
    "recording_notice_line": (
        ("ఈ call record అవుతుంది.", TE_RECORDING),
        ("Ee call record avutundi.", TE_RECORDING),
        ("यह call record हो रही है।", HI_RECORDING),
        ("Yeh call record ho rahi hai.", HI_RECORDING),
    ),
    "caller_memory_notice_line": (
        ("మీరు అడిగిన దాని గురించి ఒక చిన్న note గుర్తు పెట్టుకుంటాను.", TE_MEMORY),
        ("Meeru adigina daani gurinchi oka chinna note nenu gurthu pettukuntaanu.", TE_MEMORY),
        ("आपने जो पूछा, उसका एक छोटा note हम याद रखते हैं।", HI_MEMORY),
        ("Aapne kya poocha, uska ek chhota note main yaad rakhta hoon.", HI_MEMORY),
        (
            "I keep a short note of what you ask about, so I remember it if you call again.",
            "So I remember it when you call again, I keep a short note about this call.",
        ),
        (
            "நீங்கள் கேட்டதைப் பற்றி ஒரு சின்ன note வைத்துக்கொள்கிறேன்.",
            "நீங்கள் மீண்டும் call செய்யும்போது நினைவில் இருக்க, இந்த call பற்றி ஒரு சின்ன note "
            "வைத்துக்கொள்கிறேன்.",
        ),
        (
            "ನೀವು ಕೇಳಿದ್ದರ ಬಗ್ಗೆ ಒಂದು ಚಿಕ್ಕ note ನೆನಪಿಟ್ಟುಕೊಳ್ಳುತ್ತೇನೆ.",
            "ನೀವು ಮತ್ತೆ call ಮಾಡಿದಾಗ ನೆನಪಿರಲಿ ಎಂದು, ಈ call ಬಗ್ಗೆ ಒಂದು ಚಿಕ್ಕ note ಇಟ್ಟುಕೊಳ್ಳುತ್ತೇನೆ.",
        ),
        (
            "നിങ്ങൾ ചോദിച്ചതിനെക്കുറിച്ച് ഒരു ചെറിയ note ഞാൻ ഓർത്തുവെക്കും.",
            "നിങ്ങൾ വീണ്ടും call ചെയ്യുമ്പോൾ ഓർമ്മയുണ്ടാകാൻ, ഈ call പറ്റി ഒരു ചെറിയ note ഞാൻ "
            "സൂക്ഷിക്കും.",
        ),
        (
            "तुम्ही जे विचारले, त्याची एक छोटी note आम्ही लक्षात ठेवतो.",
            "तुम्ही पुन्हा call केल्यावर लक्षात राहावे म्हणून, या call ची एक छोटी note आम्ही ठेवतो.",
        ),
    ),
}

#: (column, POSIX pattern, replacement) for the sentences that carry the business name, which
#: is kept exactly as the line has it. No `(?:` groups: SQLAlchemy's `text()` would read the
#: colon as a bind parameter.
_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("ai_disclosure_line", r"^(ఇది|Idi|Namaskaram, idi) (.+) AI assistant\.$", TE_AI),
    ("ai_disclosure_line", r"^(मैं|Main|Namaste, main) (.+) (का|ka) AI assistant (हूँ।|hoon\.)$", HI_AI),
    (
        "disclosure_line",
        r"^(ఇది|Idi) (.+) AI assistant\. (ఈ call record అవుతుంది|Ee call record avutundi)\.$",
        f"{TE_AI} {TE_RECORDING}",
    ),
    (
        "disclosure_line",
        r"^(मैं|Main) (.+) (का|ka) AI assistant (हूँ।|hoon\.) (यह call record हो रही है।|Yeh call "
        r"record ho rahi hai\.)$",
        f"{HI_AI} {HI_RECORDING}",
    ),
)

#: The downgrade's patterns: today's wording back to what it replaced.
_REVERSE_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("ai_disclosure_line", r"^(ఇది) (.+) ఏఐ అసిస్టెంట్\.$", r"ఇది \2 AI assistant."),
    ("ai_disclosure_line", r"^(मैं) (.+) का एआई असिस्टेंट हूँ।$", r"मैं \2 का AI assistant हूँ।"),
    (
        "disclosure_line",
        r"^(ఇది) (.+) ఏఐ అసిస్టెంట్\. ఈ కాల్ రికార్డ్ అవుతుంది\.$",
        r"ఇది \2 AI assistant. ఈ call record అవుతుంది.",
    ),
    (
        "disclosure_line",
        r"^(मैं) (.+) का एआई असिस्टेंट हूँ। यह कॉल रिकॉर्ड हो रही है।$",
        r"मैं \2 का AI assistant हूँ। यह call record हो रही है।",
    ),
)


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _values(pairs: Sequence[tuple[str, str]]) -> str:
    return "VALUES " + ", ".join(f"({_quote(src)}, {_quote(dst)})" for src, dst in pairs)


def _reverse_exact() -> dict[str, list[tuple[str, str]]]:
    """New -> the wording it replaced: the first previous default listed for it, which is the
    post-D-745 form, never the older Latin-letter one."""
    out: dict[str, list[tuple[str, str]]] = {}
    for column, pairs in _EXACT.items():
        first: dict[str, str] = {}
        for old, new in pairs:
            first.setdefault(new, old)
        out[column] = [(new, old) for new, old in first.items()]
    return out


def _queue_platform_run() -> None:
    """One platform run when any live agent holds a line this migration rewrites."""
    matches = [
        f"EXISTS (SELECT 1 FROM ({_values(pairs)}) AS m(src, dst) WHERE a.{column} = m.src)"
        for column, pairs in _EXACT.items()
    ] + [f"a.{column} ~ {_quote(pattern)}" for column, pattern, _ in _PATTERNS]
    queued = execute_data_statement(
        sa.text(
            "WITH runs AS (INSERT INTO live_apply_runs (id, scope, tenant_id, reasons) "
            f"SELECT gen_random_uuid(), 'platform', NULL, '[\"{REASON}\"]'::jsonb "
            "WHERE EXISTS (SELECT 1 FROM agents a WHERE a.deleted_at IS NULL "
            "AND a.status = 'live' AND a.engine_agent_ref IS NOT NULL "
            f"AND ({' OR '.join(matches)})) RETURNING id) "
            "INSERT INTO outbox_messages (id, job, payload, status, attempt_count, "
            "created_at, updated_at) SELECT gen_random_uuid(), 'apply_live_settings', "
            "jsonb_build_object('run_id', id::text), 'pending', 0, now(), now() FROM runs"
        ),
        note="Queued one platform live apply when a live agent's notice changes.",
    )
    log.info("notices in own letters: %s platform live-apply run queued", queued)


def _rewrite(
    exact: dict[str, list[tuple[str, str]]] | dict[str, tuple[tuple[str, str], ...]],
    patterns: tuple[tuple[str, str, str], ...],
) -> None:
    for column, pairs in exact.items():
        rewritten = execute_data_statement(
            sa.text(
                f"UPDATE agents a SET {column} = m.dst, updated_at = now() "
                f"FROM ({_values(pairs)}) AS m(src, dst) WHERE a.{column} = m.src"
            ),
            note=f"Rewrote {column} values that exactly match a previous default.",
        )
        log.info("notices in own letters: %s %s rewritten", rewritten, column)
    for column, pattern, replacement in patterns:
        rewritten = execute_data_statement(
            sa.text(
                f"UPDATE agents SET {column} = regexp_replace({column}, {_quote(pattern)}, "
                f"{_quote(replacement)}), updated_at = now() WHERE {column} ~ {_quote(pattern)}"
            ),
            note=f"Rewrote {column} values in a previous default's shape.",
        )
        log.info("notices in own letters: %s %s rewritten by shape", rewritten, column)


def upgrade() -> None:
    # The FORCE bracket (`f4a2c7e19d63`): `agents` is FORCE-RLS'd, so without it these
    # statements match no rows.
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    _queue_platform_run()
    _rewrite(_EXACT, _PATTERNS)
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    _rewrite(_reverse_exact(), _REVERSE_PATTERNS)
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")
