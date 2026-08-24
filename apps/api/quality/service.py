"""The client's monthly QA report: stored by the harness, read by the screen.

NOTHING IS COMPUTED HERE, AND THAT IS THE POINT (SURFACES §2, D-15)
--------------------------------------------------------------------
`make qa-report` has computed this document since M3. SURFACES §2 asks for it "rendered
in-app, not just PDF", and the cheap way to get that — a second counting pass in this
file, over the same fixtures — is the accumulation CLAUDE.md forbids. Worse than
duplication: a QA report that disagrees with itself is the sales asset contradicting the
dashboard in front of the client, and the client cannot tell which one is lying.

So the flow is one-directional. `scripts/qa_report.summarize` computes
`calevate_shared.qa_report.QaReport`; the same CLI run stores that object here
(`store_report`); this module hands it back (`latest_report`, `list_reports`) after
revalidating it against the model. There is no path in this file that counts a scenario.

`tests/qa_report_in_app_test.py::test_the_in_app_report_and_the_cli_report_agree` is the
guard: it parses the numbers back out of the CLI's Markdown and compares them field by
field with what the route returns. A number re-derived here turns it red.

WHY NOT COMPUTE ON REQUEST: the harness replays ~110 scenarios through the extractor,
which is a model call per case. CLAUDE.md: model providers are called from workers or
the engine, never a request handler. OPERATIONS §3 already named the alternative —
"report stored per run".
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from calevate_shared.qa_report import QaReport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.session import admin_session, tenant_session

log = get_logger(__name__)

_UPSERT = (
    "INSERT INTO qa_reports (id, tenant_id, as_of, vertical, model, data, generated_at, "
    "  created_at, updated_at) "
    "VALUES (:id, :tid, :as_of, :vertical, :model, CAST(:data AS jsonb), :generated_at, "
    "  now(), now()) "
    "ON CONFLICT (tenant_id, as_of, vertical) DO UPDATE SET "
    "  model = EXCLUDED.model, data = EXCLUDED.data, "
    "  generated_at = EXCLUDED.generated_at, updated_at = now() "
    "RETURNING id"
)

_SELECT = (
    "SELECT id, as_of, vertical, model, data, generated_at FROM qa_reports "
    "{where} ORDER BY as_of DESC, vertical LIMIT :limit"
)


async def store_report(report: QaReport, *, slug: str) -> UUID:
    """File a computed report against the tenant named by `--client`.

    The slug is resolved on an `admin_session()` — the only session that may enumerate
    tenants (b57e2f9c4a13) — and the write itself happens inside the TENANT's own RLS
    context, so the row lands under the same policy every read of it will face. Writing
    it from the directory session would work and would be the beginning of a habit of
    writing tenant rows from a widened session.

    An unknown slug is REFUSED. `make qa-report CLIENT=typo --store` filing a report
    against nobody, silently, is the failure this check exists for: the operator would
    see a success line and the client would see an empty screen next month.

    Idempotent by (tenant, month-end, vertical): the document is a pure function of its
    inputs, so a re-run overwrites rather than accumulating a second copy of itself.
    """
    async with admin_session() as directory:
        row = (
            await directory.execute(
                text("SELECT id FROM organizations WHERE slug = :slug AND deleted_at IS NULL"),
                {"slug": slug},
            )
        ).first()
    if row is None:
        raise ProblemError.not_found("Tenant")
    tenant_id = UUID(str(row[0]))

    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text(_UPSERT),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "as_of": report.as_of,
                    "vertical": report.vertical,
                    "model": report.model,
                    # `model_dump_json` rather than a dict: the model owns how a date is
                    # serialized, and a hand-built dict would put a `datetime.date` into
                    # JSONB through psycopg's adapter instead.
                    "data": report.model_dump_json(),
                    "generated_at": datetime.now(UTC),
                },
            )
        ).scalar_one()
    return UUID(str(stored))


def _parse(data: object, *, report_id: object) -> QaReport:
    """Revalidate a stored document against the model that wrote it.

    A row written by an older shape must not render as a half-filled screen: the client
    would read missing numbers as zero. `QaReport.version` exists so a mismatch is an
    error a person sees rather than a document that quietly means something else.
    """
    try:
        return QaReport.model_validate(data)
    except ValueError as exc:  # pydantic ValidationError is a ValueError
        # The ID, never the document: an operator needs to know WHICH row to regenerate,
        # and the row's contents are the client's (hard rule 6 keeps ids in logs).
        log.error("qa_report_unreadable", extra={"qa_report_id": str(report_id)})
        raise ProblemError(
            kind="internal",
            code="qa_report_unreadable",
            title="Quality report unreadable",
            detail="This month's quality report could not be opened, so we are not "
            "showing it rather than showing you incomplete figures.",
            remediation="Please try again shortly. If it keeps happening, quote the trace "
            "id on this response to our team and we will regenerate the report for you.",
        ) from exc


async def list_reports(session: AsyncSession, *, limit: int = 24) -> list[QaReport]:
    """This tenant's reports, newest month first. RLS scopes it; no tenant filter here."""
    rows = (
        await session.execute(text(_SELECT.format(where="")), {"limit": max(1, min(limit, 60))})
    ).all()
    return [_parse(row[4], report_id=row[0]) for row in rows]


async def latest_report(session: AsyncSession, *, vertical: str | None = None) -> QaReport | None:
    """The most recent report, or None when the harness has never run for this tenant.

    None is a real answer and the screen renders it as one. A zeroed report would claim
    a clean run that never happened — the single worst thing this surface could say.
    """
    where = "WHERE vertical = :vertical" if vertical else ""
    params: dict[str, object] = {"limit": 1}
    if vertical:
        params["vertical"] = vertical
    row = (await session.execute(text(_SELECT.format(where=where)), params)).first()
    return None if row is None else _parse(row[4], report_id=row[0])


__all__ = ["latest_report", "list_reports", "store_report"]
