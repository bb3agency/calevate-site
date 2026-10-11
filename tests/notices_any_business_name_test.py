"""`f8c3a1d9e4b2`: an old-template opening notice is brought to the current wording whatever
business name it carries, the name is kept exactly as written, a line in any other shape is
left alone, and one platform live-apply run is queued when a live agent changes.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.api.admin import service as admin_service
from apps.api.core.settings import get_settings
from sqlalchemy import create_engine, text

STEM = "f8c3a1d9e4b2_notices_any_business_name"


def _revision() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / f"{STEM}.py"
    spec = importlib.util.spec_from_file_location(f"_revision_{STEM}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _agent() -> uuid.UUID:
    created = await admin_service.create_organization(
        name=f"Account {uuid.uuid4().hex[:6]}",
        slug=f"anb-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["agent_id"]))


_SET = text(
    "UPDATE agents SET ai_disclosure_line = :ai, disclosure_line = :bundle, status = 'live', "
    "engine_agent_ref = :ref WHERE id = :id"
)
_READ = text("SELECT ai_disclosure_line, disclosure_line FROM agents WHERE id = :id")
_RUNS = text(
    "SELECT count(*) FROM live_apply_runs WHERE scope = 'platform' AND reasons ? :reason "
    "AND status = 'pending'"
)


async def test_old_shapes_are_rewritten_for_any_name_and_others_are_left() -> None:
    cases = {
        await _agent(): (
            "Namaskaram, idi Raghava Organics AI assistant.",
            "Namaskaram, idi Raghava Organics AI assistant. Ee call record avutundi.",
            "ఇది Raghava Organics AI assistant.",
            "ఇది Raghava Organics AI assistant. ఈ call record అవుతుంది.",
        ),
        await _agent(): (
            "Main Sri Traders ka AI assistant hoon.",
            "Main Sri Traders ka AI assistant hoon. Yeh call record ho rahi hai.",
            "मैं Sri Traders का AI assistant हूँ।",
            "मैं Sri Traders का AI assistant हूँ। यह call record हो रही है।",
        ),
        await _agent(): (
            "Hello, this is the AI assistant for Lake View Homes.",
            "Hello, this is the AI assistant for Lake View Homes. This call is being recorded.",
            "This is the AI assistant for Lake View Homes.",
            "This is the AI assistant for Lake View Homes. This call is being recorded.",
        ),
        await _agent(): (
            "Namaskaram! Memu Raghava Organics nunchi AI assistant.",
            "Namaskaram! Memu Raghava Organics nunchi AI assistant.",
            "Namaskaram! Memu Raghava Organics nunchi AI assistant.",
            "Namaskaram! Memu Raghava Organics nunchi AI assistant.",
        ),
    }
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
                for agent, (ai, bundle, _, _) in cases.items():
                    connection.execute(
                        _SET, {"ai": ai, "bundle": bundle, "ref": f"ref-{agent}", "id": agent}
                    )
                before = connection.execute(_RUNS, {"reason": revision.REASON}).scalar_one()
                with Operations.context(MigrationContext.configure(connection)):
                    revision.upgrade()
                    connection.execute(text("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY"))
                    for agent, (_, _, new_ai, new_bundle) in cases.items():
                        assert connection.execute(_READ, {"id": agent}).one() == (
                            new_ai,
                            new_bundle,
                        )
                    after = connection.execute(_RUNS, {"reason": revision.REASON}).scalar_one()
                    assert after == before + 1
            finally:
                transaction.rollback()
    finally:
        sync.dispose()
