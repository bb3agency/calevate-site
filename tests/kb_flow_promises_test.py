"""The promises FLOWS §7 makes, and the two refusals a broken publish has to tell apart.

Two halves, and they fail in opposite directions.

**1. A step promised and not built.** FLOWS §7 described the knowledge flow as
"uploads doc / pastes text / submits URL → parse+chunk → … → embeddings → T0
recompilation → engine KB sync → regression smoke (3 canned questions answered from new
content) → live". Four of those steps do not exist, and a flow diagram naming a step
nobody wrote reads to the next person as a step somebody forgot to CALL — so the risk is
not the missing feature, it is the day someone "restores" a call to a function that was
never written, or tells a client their upload was parsed. The doc now names each absence
and what closes it; the tests below are what stop the doc and the code drifting apart
again. Doctrine borrowed wholesale from
`kb_tiers_test.py::test_the_knowledge_gap_report_has_no_producer_and_cannot_yet`: a gap
that is blocked OUTSIDE this repository is a dated, argued assertion, not an xfail
waiting to flip on a vendor's schedule.

**2. One refusal, and the state that used to have a second.** `runbooks/kb-out-of-sync.md`
describes `kb_engine_out_of_sync`: the engine holds a copy no row of ours mentions. A live
version with no recorded handle used to be refused separately (`kb_engine_ref_unknown`);
since D-689 knowledge is the client's and is one copy per agent, so a live version with no
claim on an agent is one that agent has not been given yet, and a copy the engine still
holds without a claim is exactly the unaccounted case. The tests below hold both halves:
that state is diagnosed as out of sync, and the remediation sends the operator to
reconcile rather than to withdraw a copy by title.

Hard rule 6: knowledge sources here are invented clinic prices. No phone number appears
in a payload or an assertion message.
"""

from __future__ import annotations

import inspect
import uuid
from pathlib import Path

import pytest
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.kb import models as kb_models
from apps.api.kb import service as kb_service
from calevate_shared.engine import KBSourceRef, VoiceEngine
from sqlalchemy import text
from tests.kb_lifecycle_test import (
    _engine_ref,
    _live_versions,
    _publish,
    _publish_new_version,
    _submit_and_approve,
)
from tests.kb_workflow_test import _tenant_with_published_agent

REPO_ROOT = Path(__file__).resolve().parents[1]
FLOWS = REPO_ROOT / "docs" / "FLOWS.md"


# --- 1. a kind we cannot read is refused, not accepted and ignored -------------


@pytest.mark.parametrize("unsupported", ["url", "file"])
async def test_a_submission_we_cannot_read_is_refused_by_name(unsupported: str) -> None:
    """The endpoint used to answer 201 to a fetch it never performed.

    `kind="url"` with a `uri` was accepted, the `uri` was written to a column nothing
    reads, and the chunks came from whatever text the caller ALSO pasted. A client (or an
    integrator reading the OpenAPI schema) had every reason to believe the page had been
    fetched, and the only signal otherwise was that the agent answered from the wrong
    text — discovered on a call, by a caller.

    The refusal is a 422 with a remediation, because the caller CAN act on it: paste the
    words. A silent success is the one outcome they cannot act on.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()

    with pytest.raises(ProblemError) as raised:
        async with tenant_session(tenant_id) as session:
            await kb_service.submit_source(
                session,
                tenant_id=tenant_id,
                name="Fees",
                body="A consultation costs 500 rupees and is payable at reception.",
                kind=unsupported,
                uri="https://example.test/fees",
            )

    assert raised.value.code == "kb_kind_unsupported"
    assert raised.value.status == 422
    assert raised.value.remediation, "a refusal an operator cannot act on is a dead end"

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT count(*) FROM kb_sources WHERE tenant_id = "
                    "(SELECT tenant_id FROM agents WHERE id = :a)"
                ),
                {"a": agent_id},
            )
        ).scalar()
    assert rows == 0, "a refused submission must leave no row behind to be approved later"


async def test_text_is_still_accepted_and_still_chunks() -> None:
    """The other direction of the same guard. Without it the refusal above is satisfied
    by an endpoint that refuses everything, which is a different outage."""
    tenant_id, _agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session,
            tenant_id=tenant_id,
            name="Fees",
            body="A consultation costs 500 rupees and is payable at reception.",
        )
    assert submitted["chunks"] == 1
    assert submitted["status"] == "pending_approval"


def test_the_supported_kinds_are_a_subset_of_what_the_column_allows() -> None:
    """The refusal must be a NARROWING of the schema, never a second vocabulary.

    `kb_sources.kind` carries a CHECK constraint over `KB_KINDS`. A supported kind the
    column rejects would be a 500 from the database on a path that had just told the
    caller their submission was valid — and it is exactly the shape of drift D-103 found
    between `agents.ENGINES` and `SELECTABLE_ENGINES`, where a widened Literal met a
    constraint nobody widened with it.
    """
    assert set(kb_models.KB_KINDS) >= kb_service.SUPPORTED_SUBMISSION_KINDS
    assert kb_service.SUPPORTED_SUBMISSION_KINDS, "refusing every kind is not a narrowing"


# --- 2. the steps FLOWS §7 no longer promises ---------------------------------


def test_nothing_can_ask_the_engines_knowledge_base_a_question() -> None:
    """Why the "regression smoke" step cannot be built here, asserted at the contract.

    FLOWS §7 promised "3 canned questions answered from new content" as a step of the
    publish. Retrieval happens inside the ENGINE (D-33/TRD §6.2), and our whole KB surface
    on `VoiceEngine` is ingestion and bookkeeping — attach, detach, list, and (D-519)
    list what the ACCOUNT holds. There is no method that takes a question, so a
    per-publish verification of what the agent can RETRIEVE is not something this
    repository can write. The only instrument is a live PSTN call, which is pilot gate
    8's `probe_telugu_retrieval`.

    `list_account_kb` was added for the orphan sweep and does NOT weaken this: it asks
    the engine what objects exist on the shared account, which is bookkeeping of exactly
    the same kind as `list_kb` — one enumerates what an agent references, the other what
    the account holds. Neither carries a question or returns retrieved text.

    This fails the day the Protocol grows a retrieval method. That is the day the step
    becomes buildable, and the day FLOWS §7's paragraph has to be rewritten rather than
    left standing as an explanation that is no longer true.
    """
    kb_methods = {
        name
        for name, _ in inspect.getmembers(VoiceEngine, inspect.isfunction)
        if "kb" in name or "knowledge" in name
    }
    assert kb_methods == {"attach_kb", "detach_kb", "list_kb", "list_account_kb"}, (
        f"`VoiceEngine` now carries {sorted(kb_methods)}. If one of them can ASK the "
        "knowledge base something, FLOWS §7's regression-smoke paragraph is obsolete — "
        "build the step and delete the paragraph, do not leave both."
    )


def test_the_flow_doc_does_not_promise_a_step_nobody_wrote() -> None:
    """The doc side of the same pin.

    Text assertions are weak instruments and this one is deliberately narrow: it names
    the three phrases that described machinery this repo does not have, and it requires
    the paragraph that explains their absence to still be there. A doc that quietly grows
    the promise back is the failure; a doc that loses the explanation is the same failure
    one step later, because an unexplained absence gets "fixed" by the next reader.
    """
    flows = FLOWS.read_text(encoding="utf-8")
    raw = flows.split("## 7. Knowledge Update Flow")[1].split("\n## ")[0]
    # Whitespace-normalised, so re-wrapping a markdown paragraph cannot break the pin —
    # a guard that fails on a reflow is one somebody deletes rather than reads.
    section = " ".join(raw.split())

    for phrase in ("regression smoke", "embeddings", "submits URL"):
        promise = f"→ {phrase}"
        assert promise not in section, (
            f"FLOWS §7 promises {phrase!r} as a step again. If it was built, delete this "
            "assertion and pin the step; if it was not, the arrow is a call somebody will "
            "go looking for."
        )
    assert "cannot be built on our side at all" in section, (
        "the paragraph explaining why the regression smoke is absent is gone; an absence "
        "with no argument beside it is one somebody restores"
    )


# --- 3. two refusals, one disease, and the order that decides the cure ---------


async def _forget_the_handle(tenant_id: uuid.UUID, agent_id: uuid.UUID, name: str) -> None:
    """Erase the engine handle we recorded for the LIVE version of a named source.

    This is the state a version published before `_remember_engine_kb_ref` existed is in:
    live in our tables, attached on the engine, and unaddressable. Reproduced by removing
    the CLAIM ROW (`engine_kb_routes`, D-519 — it was a JSONB key on `kb_documents` before
    that) rather than by patching the reader, because the refusal under test is a
    statement about the row.
    """
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "DELETE FROM engine_kb_routes "
                "WHERE source_id IN (SELECT id FROM kb_sources WHERE tenant_id = "
                "(SELECT tenant_id FROM agents WHERE id = :a) "
                "AND name = :n AND is_active = true)"
            ),
            {"a": agent_id, "n": name},
        )


async def test_a_live_version_whose_claim_is_gone_is_diagnosed_as_out_of_sync() -> None:
    """The state `kb_engine_ref_unknown` used to name: the live version's claim is gone and
    the engine still holds its copy. That copy is unaccounted, so the publish refuses with
    `kb_engine_out_of_sync` and nothing moves."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish_new_version(tenant_id, agent_id, "Fees", "A consultation costs 500 rupees.")
    await _forget_the_handle(tenant_id, agent_id, "Fees")

    v2 = await _submit_and_approve(tenant_id, agent_id, "Fees", "A consultation costs 800 rupees.")

    with pytest.raises(ProblemError) as raised:
        await _publish(tenant_id, v2)

    assert raised.value.code == "kb_engine_out_of_sync"
    assert "reconcile" in (raised.value.remediation or "")
    assert await _live_versions(tenant_id, agent_id, "Fees") == [1]


async def test_a_hand_attached_copy_refuses_the_publish_with_the_reconcile_cure() -> None:
    """With every claim intact, a document somebody attached by hand is unaccounted and the
    publish refuses with the reconcile remediation, leaving the live version as it was."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish_new_version(tenant_id, agent_id, "Fees", "A consultation costs 500 rupees.")
    ref = await _engine_ref(tenant_id, agent_id)
    await get_engine().attach_kb(
        ref, KBSourceRef(kb_id=str(uuid.uuid4()), title="Hand-attached", text="Parking is free.")
    )
    v2 = await _submit_and_approve(tenant_id, agent_id, "Fees", "A consultation costs 800 rupees.")

    with pytest.raises(ProblemError) as raised:
        await _publish(tenant_id, v2)

    assert raised.value.code == "kb_engine_out_of_sync"
    assert "reconcile" in (raised.value.remediation or "")
    assert "withdraw the stale copy" not in (raised.value.remediation or "")
    assert await _live_versions(tenant_id, agent_id, "Fees") == [1]
