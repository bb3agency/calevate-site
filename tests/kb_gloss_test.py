"""The English gloss: the script rule, the sweep's idempotency, and its spend controls.

The retrieval half — does the gloss actually make a Tenglish question find anything — is
`tests/kb_gloss_retrieval_test.py`, and the tenancy half is `tests/kb_gloss_rls_test.py`.
This file is about the WRITE side: which chunks earn a gloss, what a re-run costs, and
whether a call we paid for reached the ledger.

NO NETWORK. `chat.complete` is substituted, because what is under test is the sweep's
decisions — claim, classify, store, meter — and none of them is a fact about Azure. The
substitute COUNTS ITS CALLS, which is how "re-running the worker does not re-pay" is
asserted as a number rather than as an absence of new rows.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service
from apps.api.kb.gloss import (
    GLOSS_NOT_NEEDED,
    GLOSS_PENDING,
    GLOSS_READY,
    GLOSS_STATES,
    dominant_script,
    gloss_applies,
    needs_gloss,
)
from apps.workers import kb_gloss
from sqlalchemy import text
from tests.kb_workflow_test import _tenant_with_published_agent

#: One Telugu-script fact and one English fact, both real sentences a clinic would write.
#: The Telugu one carries a Latin borrowing ("WhatsApp") on purpose: a script test that
#: flipped to `latin` the moment a client named a brand would mark most real Telugu
#: knowledge `not_needed` and quietly ship none of this feature.
TELUGU_BODY = (
    "సన్‌రైజ్ క్లినిక్ ఆదివారం ఉదయం 9 గంటల నుండి మధ్యాహ్నం 12 గంటల వరకు మాత్రమే పని చేస్తుంది. "
    "రిపోర్టులు అదే రోజు సాయంత్రం వాట్సాప్‌లో పంపుతారు, WhatsApp నంబర్ ఒకటే."
)
ENGLISH_BODY = "The consultation fee for a first visit is 500 rupees, payable at reception."


@dataclass
class _FakeUsage:
    prompt_tokens: int = 120
    output_tokens: int = 40


@dataclass
class _FakeOutcome:
    content: str | None
    finish_reason: str = "stop"
    usage: _FakeUsage | None = None


class _RecordingProvider:
    """A stand-in for `chat.complete` that records WHICH TEXT it was asked to translate.

    Recording the text rather than only a count, because the sweep is fleet-wide: another
    test's tenant left in the database would move a bare call counter and make an
    idempotency assertion fail for a reason that has nothing to do with idempotency. "This
    body was sent exactly once" is the property, and it is true regardless of who else is
    in the worklist.
    """

    def __init__(self, reply: str = "The clinic is open on Sunday from 9 am to 12 noon.") -> None:
        self.seen: list[str] = []
        self.reply = reply

    async def __call__(self, _leg: Any, messages: Any, **_kwargs: Any) -> _FakeOutcome:
        self.seen.append(str(messages[-1]["content"]))
        return _FakeOutcome(content=self.reply, usage=_FakeUsage())


def _unique(body: str) -> str:
    """The same body, made unique to this test run by a run of DIGITS.

    THE SWEEP IS FLEET-WIDE, which makes "this text was sent to the provider exactly once"
    a claim about the whole database rather than about one tenant — and a chunk another
    test left `pending` (the empty-completion case does, deliberately) would be swept up by
    the next test's tick and counted against it. That failure looks exactly like an
    idempotency defect and is not one.

    DIGITS rather than a uuid's hex, and that is the load-bearing detail: `dominant_script`
    counts Telugu letters against LATIN letters and ignores everything else, so appending
    `a3f9` to a Telugu body nudges it toward `latin` while appending `4179` cannot move it
    at all. A fixture that changed the property under test would be worse than the flake.
    """
    return f"{body} {uuid.uuid4().int % 10**12:012d}"


async def _tenant_with_pending_chunks(*bodies: str) -> tuple[uuid.UUID, uuid.UUID, list[str]]:
    """A tenant whose agent has one submitted source per body, awaiting review.

    Submitted through `kb.service.submit_source` and never inserted: what makes a chunk
    exist is the ingestion path, and a fixture that wrote `kb_documents` directly would
    prove the sweep works on rows no client could produce. Returns the bodies AS STORED,
    because `_unique` made them different from what the caller passed.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    stored = [_unique(body) for body in bodies]
    async with tenant_session(tenant_id) as session:
        for i, body in enumerate(stored):
            await kb_service.submit_source(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                name=f"Source {i}",
                body=body,
            )
    return uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id)), stored


async def _states(tenant_id: uuid.UUID) -> list[tuple[str, str | None, str | None]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT d.gloss_state, d.gloss, d.gloss_model FROM kb_documents d "
                    "JOIN kb_sources s ON s.id = d.source_id ORDER BY s.name, d.idx"
                )
            )
        ).all()
    return [(str(r[0]), r[1], r[2]) for r in rows]


async def _run_sweep(
    monkeypatch: pytest.MonkeyPatch,
    provider: _RecordingProvider,
    *,
    only: uuid.UUID | None = None,
) -> str:
    """One tick, with the provider substituted and the tenant list narrowed.

    `only` NARROWS THE WORKLIST, and it is isolation rather than a shortcut. The sweep is
    fleet-wide with a per-tick ceiling, so a suite that has left pending chunks behind
    elsewhere would spend `MAX_CHUNKS_PER_TICK` before ever reaching the tenant under test —
    and the resulting "my chunk was not glossed" reads exactly like a defect in the code
    under test. The real worklist query is asserted separately, on its own, below.
    """
    monkeypatch.setattr(kb_gloss.chat, "complete", provider)
    monkeypatch.setattr(kb_gloss, "azure_credentials", lambda: ("res", "key", "deployment-abc"))
    if only is not None:

        async def _one() -> list[uuid.UUID]:
            return [only]

        monkeypatch.setattr(kb_gloss, "tenants_holding_knowledge", _one)
    return await kb_gloss.write_knowledge_glosses({"job_try": 1})


# --- the script rule ---------------------------------------------------------------


def test_the_script_of_a_string_is_decided_by_its_letters_not_by_a_language_guess() -> None:
    """Telugu with English borrowings is still Telugu; romanised Telugu is not.

    THE SECOND HALF IS THE WHOLE PRODUCT PROBLEM. "Sunday roju clinic enni gantalu" is a
    Telugu sentence and this function must call it `latin`, because that is the string
    Saaras hands us and Latin is the script it cannot match a Telugu passage with.
    """
    assert dominant_script(TELUGU_BODY) == "telugu"
    assert dominant_script(ENGLISH_BODY) == "latin"
    assert dominant_script("Sunday roju clinic enni gantala varaku open untundi?") == "latin"
    # Nothing that carries script at all: neither, and therefore left alone.
    assert dominant_script("8000 // 500 :: 9") == "other"
    assert dominant_script("") == "other"


def test_only_telugu_script_chunks_earn_a_gloss() -> None:
    assert needs_gloss(TELUGU_BODY) is True
    assert needs_gloss(ENGLISH_BODY) is False
    assert needs_gloss("Sunday roju clinic open untundi") is False
    assert needs_gloss("8000") is False


def test_the_gate_opens_only_across_scripts() -> None:
    """The property that makes same-script retrieval structurally unperturbable."""
    # The case the feature exists for: Latin question, Telugu passage.
    assert gloss_applies(question="Sunday roju clinic open aa?", passage=TELUGU_BODY) is True
    assert gloss_applies(question="Is the clinic open on Sunday?", passage=TELUGU_BODY) is True
    # Same script, both directions: shut, so the score cannot move.
    assert gloss_applies(question="ఆదివారం తెరిచి ఉందా?", passage=TELUGU_BODY) is False
    assert gloss_applies(question="What is the fee?", passage=ENGLISH_BODY) is False
    # A question with no script of its own does not open the arm on every passage at once.
    assert gloss_applies(question="8000?", passage=TELUGU_BODY) is False


def test_the_states_the_column_accepts_are_the_states_the_module_names() -> None:
    """`GLOSS_STATES` is rendered into the CHECK by migration `a7f4c31d95e8`, so the two
    can only disagree by somebody editing one of them alone."""
    assert set(GLOSS_STATES) == {GLOSS_PENDING, GLOSS_READY, GLOSS_NOT_NEEDED}


# --- the sweep ---------------------------------------------------------------------


async def test_a_telugu_chunk_is_glossed_and_an_english_chunk_costs_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both directions of the per-chunk decision, and the English one pays no provider.

    That asymmetry is the feature's cost model: an English-speaking account's knowledge
    base is closed out for free by a character count, and only Telugu text reaches Azure.
    """
    tenant_id, _, (telugu, english) = await _tenant_with_pending_chunks(TELUGU_BODY, ENGLISH_BODY)
    provider = _RecordingProvider()
    await _run_sweep(monkeypatch, provider, only=tenant_id)

    states = await _states(tenant_id)
    assert len(states) == 2
    telugu_row = next(s for s in states if s[0] == GLOSS_READY)
    english_row = next(s for s in states if s[0] == GLOSS_NOT_NEEDED)
    assert telugu_row[1] == "The clinic is open on Sunday from 9 am to 12 noon."
    # The MODEL, not the deployment: `rates.llm_inr_per_ktok` publishes no price for a
    # deployment name, and this column is what a reviewer's screen labels the gloss with.
    assert telugu_row[2] and telugu_row[2] != "deployment-abc"
    assert english_row[1] is None and english_row[2] is None
    assert provider.seen.count(telugu) == 1
    assert english not in provider.seen, "an English chunk reached the provider"


async def test_re_running_the_sweep_neither_duplicates_nor_re_pays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """IDEMPOTENCY, asserted as a call count rather than as an absence of new rows.

    A second tick must find nothing to do. `gloss_state` is what makes that true for the
    ENGLISH chunk as well — `gloss IS NULL` would re-select it forever and re-pay a model
    call to reach the same "no", which is the defect the column exists to prevent.
    """
    tenant_id, _, (telugu, english) = await _tenant_with_pending_chunks(TELUGU_BODY, ENGLISH_BODY)
    provider = _RecordingProvider()
    await _run_sweep(monkeypatch, provider, only=tenant_id)
    first = await _states(tenant_id)
    assert provider.seen.count(telugu) == 1

    await _run_sweep(monkeypatch, provider, only=tenant_id)
    assert provider.seen.count(telugu) == 1, (
        "a second tick re-paid for a chunk it had already glossed"
    )
    assert english not in provider.seen, (
        "a second tick re-paid to rediscover that an English chunk needs nothing"
    )
    assert await _states(tenant_id) == first


async def test_a_paid_gloss_reaches_the_ledger_under_its_own_feature_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hard rule 7, and the SEPARABILITY the feature name buys.

    This is background spend no client action triggers, so an operator asking "what did we
    spend on the client's behalf" must be able to isolate it — which is only possible if
    the rows say `kb_gloss` and not the name of an interactive surface.
    """
    tenant_id, _, _bodies = await _tenant_with_pending_chunks(TELUGU_BODY, ENGLISH_BODY)
    await _run_sweep(monkeypatch, _RecordingProvider(), only=tenant_id)

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT unit_type, qty, meta ->> 'feature' FROM usage_events "
                    "WHERE meta ->> 'feature' = 'kb_gloss'"
                )
            )
        ).all()
    assert rows, "a translation we paid for did not reach usage_events"
    assert {str(r[2]) for r in rows} == {"kb_gloss"}
    # Two rows, in and out, and a positive quantity on each: the shape
    # `record_ai_assist_usage` writes. Nothing here is estimated — the fake provider
    # returned a usage block, which is the only case that may be metered at all.
    assert all(float(r[1]) > 0 for r in rows)


async def test_an_empty_completion_is_left_pending_rather_than_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider that answers with nothing must not close the chunk out.

    Storing an empty gloss would mark the chunk `ready` and make the failure permanent and
    invisible; `not_needed` would be a lie about a Telugu chunk. Pending is the honest
    state and the next tick is the retry.
    """
    tenant_id, _, _bodies = await _tenant_with_pending_chunks(TELUGU_BODY)
    await _run_sweep(monkeypatch, _RecordingProvider(reply="   "), only=tenant_id)
    assert [s[0] for s in await _states(tenant_id)] == [GLOSS_PENDING]


async def test_the_real_worklist_query_finds_a_tenant_that_has_uploaded_knowledge() -> None:
    """THE SEAM THE OTHER TESTS NARROW, exercised for real exactly once.

    `_run_sweep(only=...)` substitutes this function, which would let the actual query rot
    unnoticed — an unregistered reason, a renamed column, a trigger that stopped firing —
    while every other test in this file stayed green. D-368's trigger on `kb_sources` is
    what puts the row there, so this asserts the trigger and the query together.
    """
    tenant_id, _, _bodies = await _tenant_with_pending_chunks(TELUGU_BODY)
    assert tenant_id in await kb_gloss.tenants_holding_knowledge()


async def test_a_deployment_with_no_language_credential_runs_without_glossing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tolerant boot (BACKEND-PATTERNS §2): no credential is a configuration state, not a
    crash and not an alert — every other queue still runs."""
    monkeypatch.setattr(kb_gloss, "azure_credentials", lambda: None)
    assert await kb_gloss.write_knowledge_glosses({"job_try": 1}) == "no_provider"


async def test_no_client_prose_reaches_a_log_line(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Hard rule 6. The sweep handles nothing BUT client prose, so this is the file where
    a stray `extra={"content": ...}` would be cheapest to write and worst to ship."""
    tenant_id, _, _bodies = await _tenant_with_pending_chunks(TELUGU_BODY, ENGLISH_BODY)
    with caplog.at_level("DEBUG"):
        await _run_sweep(monkeypatch, _RecordingProvider(), only=tenant_id)
    emitted = "\n".join(
        [record.getMessage() for record in caplog.records]
        + [str(getattr(record, "__dict__", {})) for record in caplog.records]
    )
    assert TELUGU_BODY[:40] not in emitted
    assert ENGLISH_BODY[:40] not in emitted
    assert "The clinic is open on Sunday" not in emitted
    assert str(tenant_id) in emitted, "the log must still be actionable — ids, just not prose"
