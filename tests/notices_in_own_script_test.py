"""D-745: the Telugu and Hindi opening notices are written in their own script.

1. A new agent is born with the new sentences, and hard rule 5's meaning is unchanged: the
   AI sentence names the business and says AI, the recording sentence says record.
2. The migration rewrites exactly the old template outputs, leaves an edited line alone,
   and queues ONE platform live-apply run when a live agent's notice changes, so every
   live agent is republished once.
3. It goes down and comes back up.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.api.compliance.disclosure import (
    ai_disclosure_for,
    caller_memory_notice_for,
    recording_notice_for,
)
from apps.api.core.settings import get_settings
from sqlalchemy import create_engine, text
from tests.conftest import create_org_with_receptionist

STEM = "e9b4c2a7d136_notices_in_their_own_script"


def _revision() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / f"{STEM}.py"
    spec = importlib.util.spec_from_file_location(f"_revision_{STEM}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_new_agents_get_the_sentences_in_their_own_script() -> None:
    assert ai_disclosure_for(language="te-IN", business="Raghava") == "ఇది Raghava AI assistant."
    assert recording_notice_for(language="te-IN") == "ఈ call record అవుతుంది."
    assert ai_disclosure_for(language="hi-IN", business="Raghava") == (
        "मैं Raghava का AI assistant हूँ।"
    )
    assert recording_notice_for(language="hi-IN") == "यह call record हो रही है।"
    assert caller_memory_notice_for(language="hi-IN") == (
        "आप दोबारा call करें तो याद रहे, इसलिए हम इस call का एक छोटा note रखते हैं।"
    )
    # The migration's "new" column is the table, so the two cannot drift apart.
    for _, new_ai, _, new_rec, _, new_mem in _revision()._LINES:
        assert "{b}" in new_ai and "AI" in new_ai and "record" in new_rec and "note" in new_mem


async def _agent(business: str) -> uuid.UUID:
    created = await create_org_with_receptionist(
        name=business,
        slug=f"scr-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["agent_id"]))


#: An agent's stored lines as the previous template wrote them; set on the owner connection
#: inside the rolled-back transaction, so nothing here outlives the test.
_SET_LINES = text(
    "UPDATE agents SET ai_disclosure_line = :ai, recording_notice_line = :rec, "
    "caller_memory_notice_line = :mem, disclosure_line = :ai || ' ' || :rec, "
    "status = 'live', engine_agent_ref = :ref WHERE id = :id"
)
_OLD_RECORDING = "Ee call record avutundi."
_OLD_MEMORY = "Meeru adigina daani gurinchi oka chinna note nenu gurthu pettukuntaanu."


async def test_the_migration_rewrites_old_outputs_once_and_queues_one_platform_run() -> None:
    business = f"Script Shop {uuid.uuid4().hex[:6]}"
    old_agent = await _agent(business)
    edited_agent = await _agent(business)
    revision = _revision()
    url = (get_settings().alembic_database_url or get_settings().database_url).replace(
        "+asyncpg", "+psycopg"
    )
    lines = text(
        "SELECT ai_disclosure_line, recording_notice_line, caller_memory_notice_line, "
        "disclosure_line FROM agents WHERE id = :id"
    )
    runs = text(
        "SELECT count(*) FROM live_apply_runs WHERE scope = 'platform' AND reasons ? :reason "
        "AND status = 'pending'"
    )
    sync = create_engine(url)
    try:
        with sync.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY"))
                for agent, ai in (
                    (old_agent, f"Idi {business} AI assistant."),
                    (edited_agent, f"Idi {business} lo AI assistant matladutondi."),
                ):
                    connection.execute(
                        _SET_LINES,
                        {
                            "ai": ai,
                            "rec": _OLD_RECORDING,
                            "mem": _OLD_MEMORY,
                            "ref": f"ref-{agent}",
                            "id": agent,
                        },
                    )
                before = connection.execute(runs, {"reason": revision.REASON}).scalar_one()
                with Operations.context(MigrationContext.configure(connection)):
                    revision.upgrade()
                    connection.execute(text("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY"))
                    assert connection.execute(lines, {"id": old_agent}).one() == (
                        f"ఇది {business} AI assistant.",
                        "ఈ call record అవుతుంది.",
                        "మీరు అడిగిన దాని గురించి ఒక చిన్న note గుర్తు పెట్టుకుంటాను.",
                        f"ఇది {business} AI assistant. ఈ call record అవుతుంది.",
                    )
                    edited = connection.execute(lines, {"id": edited_agent}).one()
                    assert edited[0] == f"Idi {business} lo AI assistant matladutondi."
                    assert edited[1] == "ఈ call record అవుతుంది."
                    after = connection.execute(runs, {"reason": revision.REASON}).scalar_one()
                    assert after == before + 1
                    revision.downgrade()
                    connection.execute(text("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY"))
                    assert connection.execute(lines, {"id": old_agent}).one()[:2] == (
                        f"Idi {business} AI assistant.",
                        "Ee call record avutundi.",
                    )
                    revision.upgrade()
            finally:
                transaction.rollback()
    finally:
        sync.dispose()
