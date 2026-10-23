"""D-861: existing agents get the reworded memory sentence only where they hold the old default.

The migration rewrites `agents.caller_memory_notice_line` where it is exactly a previous
template, leaves a sentence somebody edited alone, queues ONE platform live-apply run when a
live agent that remembers callers changes, and goes down and back up.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.api.compliance.disclosure import caller_memory_notice_for
from apps.api.core.settings import get_settings
from sqlalchemy import create_engine, text
from tests.conftest import create_org_with_receptionist

STEM = "c3e8a1f5d702_memory_sentence_reworded"

_OLD_TE = "మీరు అడిగిన దాని గురించి ఒక చిన్న note గుర్తు పెట్టుకుంటాను."
_OLD_EN = "I keep a short note of what you ask about, so I remember it if you call again."
_EDITED = "మీరు అడిగినది ఒక note లో రాసుకుంటాను."


def _revision() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / f"{STEM}.py"
    spec = importlib.util.spec_from_file_location(f"_revision_{STEM}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _agent() -> uuid.UUID:
    created = await create_org_with_receptionist(
        name=f"Memory Shop {uuid.uuid4().hex[:6]}",
        slug=f"mem-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["agent_id"]))


_SET_LINE = text(
    "UPDATE agents SET caller_memory_notice_line = :mem, caller_memory_enabled = true, "
    "status = 'live', engine_agent_ref = :ref WHERE id = :id"
)
_LINE = text("SELECT caller_memory_notice_line FROM agents WHERE id = :id")
_RUNS = text(
    "SELECT count(*) FROM live_apply_runs WHERE scope = 'platform' AND reasons ? :reason "
    "AND status = 'pending'"
)


async def test_old_defaults_are_reworded_an_edit_is_kept_and_one_run_is_queued() -> None:
    te_agent, en_agent, edited_agent = await _agent(), await _agent(), await _agent()
    revision = _revision()
    url = (get_settings().alembic_database_url or get_settings().database_url).replace(
        "+asyncpg", "+psycopg"
    )
    sync = create_engine(url)
    try:
        with sync.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY"))
                for agent, line in (
                    (te_agent, _OLD_TE),
                    (en_agent, _OLD_EN),
                    (edited_agent, _EDITED),
                ):
                    connection.execute(_SET_LINE, {"mem": line, "ref": f"ref-{agent}", "id": agent})
                before = connection.execute(_RUNS, {"reason": revision.REASON}).scalar_one()
                with Operations.context(MigrationContext.configure(connection)):
                    revision.upgrade()
                    connection.execute(text("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY"))

                    def line_of(agent: uuid.UUID) -> str:
                        return str(connection.execute(_LINE, {"id": agent}).scalar_one())

                    assert line_of(te_agent) == caller_memory_notice_for(language="te-IN")
                    # Matched on the text: an English default on a Telugu agent is reworded too.
                    assert line_of(en_agent) == caller_memory_notice_for(language="en-IN")
                    assert line_of(edited_agent) == _EDITED
                    after = connection.execute(_RUNS, {"reason": revision.REASON}).scalar_one()
                    assert after == before + 1
                    revision.downgrade()
                    connection.execute(text("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY"))
                    assert line_of(te_agent) == _OLD_TE
                    assert line_of(en_agent) == _OLD_EN
                    assert line_of(edited_agent) == _EDITED
                    revision.upgrade()
            finally:
                transaction.rollback()
    finally:
        sync.dispose()
