"""`/healthz/ready` is red when the database is behind the code (D-390).

THE DEFECT. Readiness answered every question about this deployment's CREDENTIALS —
engine key, KEK, audit secret, object-store credentials — and no question at all about
its SCHEMA. `scripts/vps-deploy.sh` migrates before it swaps containers, so its own
ordering is safe, but nothing in the running process ever re-asked afterwards. A
container brought up outside that script — a bare `docker compose up -d api` in the
deploy directory, a partial `--no-pull` deploy, a migrate step that failed while the
swap went ahead anyway — served against whatever schema it found, returning 500 on
every request that touched a column the release had added, while `/healthz/ready`
reported `ready` and the orchestrator kept it in rotation.

That is D-49's shape exactly: unfit to serve AND silent about it. The difference is that
D-49 was about a variable nobody set; this is about a step nobody ran.

THE THIRD ANSWER IS WHY THIS IS NOT A ONE-LINE EQUALITY. A database at a revision this
image has never heard of is a ROLLBACK — `scripts/deploy_revision_check.py` supports it
deliberately, because migrations are expand-only and the previous release runs fine on
the newer schema. `stored != head` would therefore have refused to bring up the release
you roll back TO, during the incident you are rolling back FOR. So the question is
"does this image have migrations the database has not applied", not "do the two strings
match", and this file pins all three answers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
from apps.api.core import health as health_module
from apps.api.main import app as api_app
from httpx import ASGITransport, AsyncClient, Response

#: Not a real revision. Standing in for "this image carries a migration beyond the one
#: the database is stamped with", which is the only state that must go red.
UNAPPLIED = "0000deadbeef"


async def _no_queue() -> tuple[int, float | None]:
    return 0, None


async def _ready() -> Response:
    async with AsyncClient(transport=ASGITransport(app=api_app), base_url="http://api") as http:
        return await http.get("/healthz/ready")


@pytest.fixture
def otherwise_healthy(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Everything readiness asks about EXCEPT the schema is green, so the verdict this
    file reads is unambiguously the schema's."""
    monkeypatch.setattr(health_module, "runtime_config_missing_keys", lambda _settings: [])
    monkeypatch.setattr(health_module, "_queue_stats", _no_queue)
    yield


@pytest.fixture
async def stored_revision() -> AsyncIterator[str]:
    """What the test database is actually stamped with. Read rather than assumed: the head
    moves with every migration, and a hardcoded revision would make this file a thing that
    needs editing rather than a thing that holds."""
    from apps.api.db.session import untenanted_session
    from sqlalchemy import text

    async with untenanted_session() as session:
        result = await session.execute(text("SELECT version_num FROM alembic_version"))
        yield str(result.scalar_one())


def _pretend_image_carries(
    monkeypatch: pytest.MonkeyPatch, *, known: set[str], heads: set[str]
) -> None:
    """Substitute the IMAGE's migration graph, never the database's answer.

    The database read stays real — it is the half that would be wrong if this probe
    queried the wrong table or swallowed the wrong exception.
    """
    monkeypatch.setattr(
        health_module,
        "_image_migration_graph",
        lambda: (frozenset(known), frozenset(heads)),
    )


async def test_a_database_at_this_images_head_is_ready(
    otherwise_healthy: None, stored_revision: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The positive half. A schema probe that fired when it should not would refuse every
    correct deployment, which is a worse outage than the one it prevents."""
    _pretend_image_carries(monkeypatch, known={stored_revision}, heads={stored_revision})

    response = await _ready()

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ready"


async def test_a_database_behind_this_images_head_is_not_ready(
    otherwise_healthy: None, stored_revision: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE DEFECT. The image carries a migration the database has not applied, so every
    request touching what that migration added will fail — and this used to answer
    `ready`."""
    _pretend_image_carries(monkeypatch, known={stored_revision, UNAPPLIED}, heads={UNAPPLIED})

    response = await _ready()

    assert response.status_code == 503, response.text
    assert response.json()["status"] == "not_ready"


async def test_the_verdict_names_the_schema_rather_than_a_dependency(
    otherwise_healthy: None, stored_revision: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One word, and it has to be the actionable one: `db_down` sends an operator to
    Postgres, `schema_behind` sends them to `alembic upgrade head`."""
    _pretend_image_carries(monkeypatch, known={stored_revision, UNAPPLIED}, heads={UNAPPLIED})

    response = await _ready()

    # The detail is `ops:manage`-gated (the endpoint's whole disclosure design), so an
    # anonymous probe reads the status and the operator reads the log line. What is
    # asserted here is that the probe REFUSED — `health_disclosure_test` owns who sees why.
    assert response.status_code == 503
    assert set(response.json()) == {"status", "service"}


async def test_a_rollback_leaves_the_previous_release_able_to_come_up(
    otherwise_healthy: None, stored_revision: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The database is AHEAD: its revision is not in this image's chain at all.

    `scripts/deploy_revision_check.py` calls this out by exit code and skips migrations
    for it. Reporting it red here would mean the release you roll back to never passes
    readiness — a probe that fires hardest during the incident it is supposed to help
    with.
    """
    _pretend_image_carries(monkeypatch, known={UNAPPLIED}, heads={UNAPPLIED})

    response = await _ready()

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ready"


async def test_an_unreadable_migration_tree_abstains_rather_than_accuses(
    otherwise_healthy: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A process that cannot read its own versions tree has an image defect, and
    `schema_behind` would send the operator to run a migration that is not the problem."""
    monkeypatch.setattr(health_module, "_image_migration_graph", lambda: None)

    response = await _ready()

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ready"


def test_the_image_graph_is_resolved_from_this_repository() -> None:
    """The substitution above is only honest if the real thing works. Not a mock's mock:
    this reads the actual `alembic/versions` tree the container ships."""
    health_module._migration_graph = None
    health_module._migration_graph_failed = False
    graph = health_module._image_migration_graph()

    assert graph is not None, "the repo's own alembic tree must be readable"
    known, heads = graph
    assert heads, "a repository with no head has no schema to be current with"
    assert heads <= known
    assert len(known) > len(heads), "more than one migration has ever been written here"
