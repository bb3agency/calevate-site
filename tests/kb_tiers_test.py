"""Where the T0-T4 tiers (TRD §6) actually live, and where they only live in the doc.

TRD §6 names five retrieval tiers. Four of the five are not code in this repository, and
they are not absent for the same reason — which is the whole point of writing them down
here rather than in a paragraph nobody re-reads:

* **T0 compiled context** is real and is exercised below. `apps/api/admin/intake.py`
  compiles the client's own business facts into a `[T0 FACTS]` block, splices it into
  the prompt body and stores it as `prompt_versions.compiled_t0_context` (D-39).
* **T1/T2 (cache + speculative)** are deliberately unbuilt, in TRD §6's own words: "only
  relevant once in-call retrieval moves to the provider". D-33 keeps in-call retrieval
  on the engine's built-in KB for v1, so there is nothing for a cache tier to sit in
  front of. Absent by decision; nothing here pins them.
* **T3 cold lookup** is DELEGATED, not missing: it happens inside the engine's own
  pipeline (D-33), which is why our whole T3 surface is the ingestion side —
  `attach_kb`. There is no retrieval endpoint of ours in the call path, and the test
  below says so, because adding one is a decision against the 100ms budget (TRD §4)
  and must not happen by drift.
* **T4 refuse-and-escalate** is a PROMPT instruction (docs/PROMPT-GUIDE.md §1) with no
  code behind it, and its measurement — the knowledge-gap report TRD §6 promises, built
  on `kb_retrieval_logs` — has no producer at all. That is pinned as a strict xfail:
  the table is declared, migrated, RLS'd and indexed, and nothing in the system has ever
  written a row to it.

The two xfails are pins in the sense pyproject's `xfail_strict` comment describes. Each
one fails the day it starts passing, so whoever closes the gap is told to delete the
marker instead of leaving a comment that outlives the thing it describes.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from apps.api.admin import intake
from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service
from sqlalchemy import text
from tests.intake_test import FACTS, _tenant
from tests.kb_workflow_test import _tenant_with_published_agent

REPO_ROOT = Path(__file__).resolve().parents[1]


async def _prompt_versions(agent_id: uuid.UUID, tenant_id: uuid.UUID) -> list[tuple[int, str]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT version, coalesce(compiled_t0_context, '') FROM prompt_versions "
                    "WHERE agent_id = :aid ORDER BY version"
                ),
                {"aid": agent_id},
            )
        ).all()
    return [(int(r[0]), str(r[1])) for r in rows]


# --- T0: implemented -----------------------------------------------------------------


async def test_t0_context_is_compiled_from_the_clients_own_facts_and_stored() -> None:
    """The one tier that is code. Named here so "T0 is implemented" is a claim this
    suite makes rather than one a reader has to take on trust from another file."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        result = await intake.record_intake(
            session, tenant_id=tenant_id, agent_id=agent_id, facts=FACTS, recorded_by=None
        )
    versions = await _prompt_versions(agent_id, tenant_id)
    compiled = dict(versions)[int(result["prompt_version"])]
    assert compiled.startswith(intake.T0_HEADER)
    assert "Root canal" in compiled, "a fact the client typed reached the compiled block"


# --- T0 regeneration: promised by both docs, implemented by neither path -------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GAP: TRD §6 says T0 is 'regenerated on KB change' and FLOWS §7 puts 'T0 "
        "recompilation' between the version bump and the engine KB sync. "
        "`apps/api/kb/service.publish_source` mints no prompt version and touches no "
        "prompt: T0 is regenerated only by the intake step "
        "(`apps/api/admin/intake.py:record_intake`). Approving new knowledge therefore "
        "changes what the agent can RETRIEVE and never what it knows at zero latency — "
        "the tier that TRD §6 says answers ~80% of questions. Closing this belongs in "
        "`apps/api/agents` + `apps/api/kb` together; delete this marker when it lands."
    ),
)
async def test_publishing_knowledge_recompiles_the_t0_block() -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    before = await _prompt_versions(agent_id, tenant_id)

    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Fees",
            body="A consultation costs 500 rupees and is payable at reception.",
        )
        await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
        await kb_service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(submitted["id"]))
        )

    after = await _prompt_versions(agent_id, tenant_id)
    assert len(after) > len(before), "publishing knowledge minted no new prompt version"
    assert "500 rupees" in after[-1][1], "the newly approved facts are not in the T0 block"


# --- T3: delegated to the engine, and must stay that way by decision ------------------


def test_in_call_retrieval_is_not_reimplemented_on_our_side() -> None:
    """D-33/TRD §6: v1 keeps T3 inside the engine's built-in KB precisely because the
    external route costs two extra hops (+150-400ms) against a 100ms budget. Our whole
    in-call KB surface is therefore the INGESTION side. A retrieval endpoint appearing in
    `apps/voice-runtime` is not a feature, it is that decision being reversed by
    accident, and it needs the measurement TRD §6 demands first.
    """
    runtime = REPO_ROOT / "apps" / "voice-runtime"
    sources = [
        path.read_text().lower()
        for path in runtime.rglob("*.py")
        if "__pycache__" not in path.parts
    ]
    assert sources, "premise: voice-runtime has python sources"
    for text_body in sources:
        for token in ("kb_documents", "kb_sources", "knowledgebase", "retrieve_kb"):
            assert token not in text_body, (
                f"voice-runtime names {token!r}: in-call retrieval moved to our side "
                "without the p95 measurement TRD §6 gates it on"
            )


# --- T4: a prompt instruction whose measurement has no producer ----------------------


def _app_sources_naming(table: str) -> list[str]:
    """Files under apps/ that name a table, excluding the two places every table is
    named for structural reasons: its ORM model and the model registry."""
    excluded = {
        REPO_ROOT / "apps" / "api" / "kb" / "models.py",
        REPO_ROOT / "apps" / "api" / "db" / "registry.py",
    }
    hits = []
    for path in (REPO_ROOT / "apps").rglob("*.py"):
        if "__pycache__" in path.parts or path in excluded:
            continue
        if table in path.read_text():
            hits.append(str(path.relative_to(REPO_ROOT)))
    return hits


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GAP: TRD §6 makes T4 misses the input to the knowledge-gap report — 'T4 misses "
        "are what a client should add next' (`apps/api/kb/models.py:KbRetrievalLog`). "
        "`kb_retrieval_logs` is declared, migrated, indexed and RLS'd, and NOTHING "
        "writes or reads it. T4 itself exists only as a prompt instruction "
        "(docs/PROMPT-GUIDE.md §1), so today a client is never told which questions "
        "their agent could not answer. A producer needs the engine to report retrieval "
        "outcomes (pilot gate 8); delete this marker when one exists."
    ),
)
def test_the_knowledge_gap_report_has_a_producer() -> None:
    assert _app_sources_naming("kb_retrieval_logs"), (
        "kb_retrieval_logs has no writer and no reader anywhere in apps/"
    )
