"""D-861: existing agents get the opening notices in their own letters and the reworded memory
sentence, only where they hold a previous default.

The migration rewrites the three sentences and the legacy bundle where each is exactly a
previous default (the business name inside the AI sentence kept as the line has it), leaves
a line somebody edited alone, queues ONE platform live-apply run when a live agent changes,
and goes down and back up.
"""

from __future__ import annotations

import importlib.util
import re
import uuid
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.api.compliance.disclosure import (
    CALLER_MEMORY_NOTICE_TEMPLATES,
    caller_memory_notice_for,
    recording_notice_for,
)
from apps.api.core.settings import get_settings
from sqlalchemy import create_engine, text
from tests.conftest import create_org_with_receptionist

STEM = "c3e8a1f5d702_notices_in_own_letters"
BUSINESS = "Vennela Real Estate"


def _revision() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / f"{STEM}.py"
    spec = importlib.util.spec_from_file_location(f"_revision_{STEM}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _d865() -> ModuleType:
    stem = "f2b7c4e9d815_ai_notice_introduces_agent"
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / f"{stem}.py"
    spec = importlib.util.spec_from_file_location(f"_revision_{stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ai(language: str) -> str:
    """D-861's AI sentence for BUSINESS, which D-865 replaced with the introduction."""
    revision = _revision()
    return (revision.TE_AI if language == "te-IN" else revision.HI_AI).replace(r"\2", BUSINESS)


def test_the_migrations_copies_are_todays_defaults() -> None:
    """The migration copies rather than imports; a copy nobody compares drifts. Its AI
    sentence is the one D-865's migration takes as the previous default."""
    revision = _revision()
    assert recording_notice_for(language="te-IN") == revision.TE_RECORDING
    assert recording_notice_for(language="hi-IN") == revision.HI_RECORDING
    assert caller_memory_notice_for(language="te-IN") == revision.TE_MEMORY
    assert caller_memory_notice_for(language="hi-IN") == revision.HI_MEMORY
    assert re.fullmatch(_d865().TE_OLD, _ai("te-IN"))
    assert re.fullmatch(_d865().HI_OLD, _ai("hi-IN"))
    new_memory = {new for _old, new in revision._EXACT["caller_memory_notice_line"]}
    assert new_memory == set(CALLER_MEMORY_NOTICE_TEMPLATES.values())


async def _agent() -> uuid.UUID:
    created = await create_org_with_receptionist(
        name=f"Letters Shop {uuid.uuid4().hex[:6]}",
        slug=f"ltr-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["agent_id"]))


_SET_LINES = text(
    "UPDATE agents SET ai_disclosure_line = :ai, recording_notice_line = :rec, "
    "caller_memory_notice_line = :mem, disclosure_line = :ai || ' ' || :rec, "
    "caller_memory_enabled = true, status = 'live', engine_agent_ref = :ref WHERE id = :id"
)
_LINES = text(
    "SELECT ai_disclosure_line, recording_notice_line, caller_memory_notice_line, "
    "disclosure_line FROM agents WHERE id = :id"
)
_RUNS = text(
    "SELECT count(*) FROM live_apply_runs WHERE scope = 'platform' AND reasons ? :reason "
    "AND status = 'pending'"
)
_OLD_TE = (
    f"ఇది {BUSINESS} AI assistant.",
    "ఈ call record అవుతుంది.",
    "మీరు అడిగిన దాని గురించి ఒక చిన్న note గుర్తు పెట్టుకుంటాను.",
)
_LATIN_TE = (
    f"Idi {BUSINESS} AI assistant.",
    "Ee call record avutundi.",
    "Meeru adigina daani gurinchi oka chinna note nenu gurthu pettukuntaanu.",
)
_OLD_HI = (
    f"मैं {BUSINESS} का AI assistant हूँ।",
    "यह call record हो रही है।",
    "आपने जो पूछा, उसका एक छोटा note हम याद रखते हैं।",
)
_EDITED = (
    f"{BUSINESS} లో మీతో మాట్లాడుతున్నది AI assistant.",
    "ఈ call record చేస్తున్నాం.",
    "మీరు అడిగినది ఒక note లో రాసుకుంటాను.",
)


async def test_previous_defaults_are_rewritten_edits_kept_and_one_run_queued() -> None:
    te_agent, latin_agent, hi_agent, edited_agent = (
        await _agent(),
        await _agent(),
        await _agent(),
        await _agent(),
    )
    revision = _revision()
    url = (get_settings().alembic_database_url or get_settings().database_url).replace(
        "+asyncpg", "+psycopg"
    )
    te_new = (
        _ai("te-IN"),
        recording_notice_for(language="te-IN"),
        caller_memory_notice_for(language="te-IN"),
    )
    hi_new = (
        _ai("hi-IN"),
        recording_notice_for(language="hi-IN"),
        caller_memory_notice_for(language="hi-IN"),
    )
    sync = create_engine(url)
    try:
        with sync.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY"))
                for agent, (ai, rec, mem) in (
                    (te_agent, _OLD_TE),
                    (latin_agent, _LATIN_TE),
                    (hi_agent, _OLD_HI),
                    (edited_agent, _EDITED),
                ):
                    connection.execute(
                        _SET_LINES,
                        {"ai": ai, "rec": rec, "mem": mem, "ref": f"ref-{agent}", "id": agent},
                    )
                before = connection.execute(_RUNS, {"reason": revision.REASON}).scalar_one()
                with Operations.context(MigrationContext.configure(connection)):
                    revision.upgrade()
                    connection.execute(text("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY"))

                    def lines_of(agent: uuid.UUID) -> tuple[str, ...]:
                        return tuple(connection.execute(_LINES, {"id": agent}).one())

                    assert lines_of(te_agent) == (*te_new, f"{te_new[0]} {te_new[1]}")
                    assert lines_of(latin_agent) == (*te_new, f"{te_new[0]} {te_new[1]}")
                    assert lines_of(hi_agent) == (*hi_new, f"{hi_new[0]} {hi_new[1]}")
                    assert lines_of(edited_agent)[:3] == _EDITED
                    after = connection.execute(_RUNS, {"reason": revision.REASON}).scalar_one()
                    assert after == before + 1
                    revision.downgrade()
                    connection.execute(text("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY"))
                    # Down to the wording this replaced, never further back.
                    assert lines_of(te_agent)[:3] == _OLD_TE
                    assert lines_of(latin_agent)[:3] == _OLD_TE
                    assert lines_of(hi_agent)[:3] == _OLD_HI
                    assert lines_of(edited_agent)[:3] == _EDITED
                    revision.upgrade()
            finally:
                transaction.rollback()
    finally:
        sync.dispose()
