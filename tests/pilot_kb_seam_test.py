"""Gate 8's KB probes against the adapter they are pointed at, not against the fake.

THE SEAM THIS FILE EXISTS FOR. `tests/pilot_knowledge_test.py` proves the probes'
behaviour against `FakeEngine`, and says so in its own docstring: *"`FakeEngine` … is
used unmodified as the well-behaved control, so the happy path is proven against the
adapter the conformance suite already governs."* The fake accepts a `KBSourceRef` with
`document=None` and an `attach_kb` with no `agent=`; the PRIMARY adapter refuses both,
by name, before a byte leaves the process. So every gate 8 KB assertion was green
against an engine that cannot refuse, while the run an operator would actually do —
`scripts.pilot.runner` hands the probes `get_engine(settings)`, the real Bolna adapter —
could not attach anything at all.

That is D-491's shape a second time: the publisher's renderer seam and this one were
built for the same vendor fact (Bolna's `POST /knowledgebase` is multipart and ingests a
FILE), the publisher was fixed, and the pilot harness that exists to VERIFY that vendor
fact was left holding prose.

Both halves are asserted here against the real adapter, which needs no network for
either: both refusals are raised before the first request.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal

import pytest
from apps.api.core.errors import ProblemError
from apps.api.engine.bolna import BolnaEngine
from calevate_shared.engine import AgentConfig, ModelConfig
from scripts.pilot.knowledge import (
    KbSourceInput,
    ProbeMisuseError,
    inconclusive_detail_for,
    probe_kb_agent_linkage,
    probe_kb_delete_clears_agent_reference,
)
from tests.pilot_knowledge_test import _agent, _check


def _bolna() -> BolnaEngine:
    """No key and no client. Neither refusal under test reaches `_http`, so an engine
    that could not make a request is the honest way to prove that."""
    return BolnaEngine(api_key=None, fx_rate=Decimal("83"))


def _agent_config() -> AgentConfig:
    return AgentConfig(
        tenant_id="pilot",
        agent_id="pilot-agent",
        name="calevate-pilot",
        direction="outbound",
        language_primary="te-IN",
        opening_line="Namaskaram.",
        system_prompt="pilot",
        models=ModelConfig(),
    )


# --- half one: the document ---------------------------------------------------


def test_the_probe_renders_a_document_for_the_engine_that_needs_one() -> None:
    """RED BEFORE THE FIX: `resolve()` returned `KBSourceRef(text=...)` with
    `document=None`, so `BolnaEngine.attach_kb` refused `engine_kb_document_missing`
    on the first probe of the gate."""
    source = KbSourceInput(kb_id="kb1", title="faq", text="Timings are 9 to 5.").resolve()

    assert source.document, (
        "gate 8 attaches this to the engine under test; an engine that ingests files "
        "refuses prose by name and the gate reports it as inconclusive"
    )
    assert source.content_sha256 == hashlib.sha256(source.document).hexdigest()
    # The approved TEXT survives alongside the document: an engine that ingests prose
    # still gets what a human approved.
    assert "Timings are 9 to 5." in source.text


def test_the_rendered_document_is_deterministic() -> None:
    """The digest is the publisher's re-upload guard, so two renders of one input must
    hash the same or the guard never matches."""
    first = KbSourceInput(kb_id="kb1", title="faq", text="Timings are 9 to 5.").resolve()
    second = KbSourceInput(kb_id="kb1", title="faq", text="Timings are 9 to 5.").resolve()
    assert first.content_sha256 == second.content_sha256


def test_text_the_renderer_refuses_is_a_probe_misuse_not_a_verdict() -> None:
    """A source the renderer cannot draw is a bad INPUT, not a vendor finding. It must
    stop the run rather than become an inconclusive row attributed to the engine."""
    with pytest.raises(ProbeMisuseError, match="kb1"):
        KbSourceInput(kb_id="kb1", title="faq", text="   ").resolve()


async def test_the_real_adapter_no_longer_refuses_the_probes_source() -> None:
    """The cross-side assertion, made against `BolnaEngine` itself.

    With a document present the adapter's document guard is passed, so the refusal that
    remains is the AGENT one — a different code, and the one the report must name.
    """
    source = KbSourceInput(kb_id="kb1", title="faq", text="Timings are 9 to 5.").resolve()
    with pytest.raises(ProblemError) as raised:
        await _bolna().attach_kb("agent_1", source, agent=None)
    assert raised.value.code == "engine_kb_agent_config_required", raised.value.code


async def test_the_adapter_still_refuses_prose_which_is_why_the_render_is_load_bearing() -> None:
    """The other direction, so the test above cannot pass by the guard being deleted."""
    source = KbSourceInput(kb_id="kb1", title="faq", text="Timings are 9 to 5.").resolve()
    with pytest.raises(ProblemError) as raised:
        await _bolna().attach_kb(
            "agent_1", source.model_copy(update={"document": None}), agent=_agent_config()
        )
    assert raised.value.code == "engine_kb_document_missing"


# --- half two: what the operator is told when the adapter refuses -------------


def test_an_answered_refusal_is_never_reported_as_re_run_after_gate_2() -> None:
    """RED BEFORE THE FIX: every refusal that was not the capability code was rendered
    as "Re-run after gate 2 passes", which for an ANSWERED refusal is advice to loop
    forever — the exact failure `_is_capability_refusal` was written to remove, on two
    codes it did not know about."""
    for code in ("engine_kb_agent_config_required", "engine_kb_document_missing"):
        detail = inconclusive_detail_for(
            ProblemError(kind="dependency", code=code, title="t", detail="d")
        )
        assert "Re-run after gate 2 passes" not in detail, code
        assert code in detail, code


def test_a_transient_failure_still_says_re_run() -> None:
    """The other branch survives: a timeout IS worth re-running, and collapsing the two
    would be the same mistake pointed the other way."""
    assert "Re-run after gate 2 passes" in inconclusive_detail_for(TimeoutError())


async def test_the_linkage_probe_reports_the_adapters_own_refusal() -> None:
    """End to end through the probe, against the real adapter: the row an operator reads
    must name the code that actually refused."""
    out = await probe_kb_agent_linkage(_bolna(), _agent("agent_a", "kb1"), _agent("agent_b", "kb2"))
    check = _check(out.checks, "kb_list_carries_agent_linkage")
    assert check.status == "not_run"
    assert "engine_kb_agent_config_required" in check.detail
    assert "Re-run after gate 2 passes" not in check.detail


async def test_the_delete_probe_reports_the_adapters_own_refusal() -> None:
    out = await probe_kb_delete_clears_agent_reference(_bolna(), _agent("agent_a", "kb1"))
    check = _check(out.checks, "kb_delete_clears_agent_reference")
    assert check.status == "not_run"
    assert "engine_kb_agent_config_required" in check.detail
    assert "Re-run after gate 2 passes" not in check.detail
