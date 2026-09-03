"""Where the T0-T4 tiers (TRD §6) actually live, and where they only live in the doc.

TRD §6 names five retrieval tiers. Four of the five are not code in this repository, and
they are not absent for the same reason — which is the whole point of writing them down
here rather than in a paragraph nobody re-reads:

* **T0 compiled context** is real and is exercised below. `apps/api/admin/intake.py`
  compiles the client's own business facts into a `[T0 FACTS]` block, splices it into
  the prompt body and stores it as `prompt_versions.compiled_t0_context` (D-39), and
  `apps/api/agents/t0.py` REGENERATES that block on every knowledge publish — the
  second half of TRD §6's sentence, which used to be doc-only and is now the second
  test below. `tests/t0_recompile_test.py` holds the rest of that behaviour.
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
  on `kb_retrieval_logs` — has no producer and cannot have one yet. That is now a
  DATED, ARGUED gap rather than an xfail waiting to flip, because the blocker is not
  our code: see `test_the_knowledge_gap_report_has_no_producer_and_cannot_yet` below
  and the note on `apps/api/kb/models.py:KbRetrievalLog`.

The pins here are pins in the sense pyproject's `xfail_strict` comment describes: each
one fails the day the world changes under it, so whoever closes a gap is told to delete
the marker instead of leaving a comment that outlives the thing it describes.
"""

from __future__ import annotations

import io
import tokenize
import uuid
from pathlib import Path

from apps.api.admin import intake
from apps.api.agents import t0
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
    assert compiled.startswith(t0.T0_HEADER)
    assert "Root canal" in compiled, "a fact the client typed reached the compiled block"


# --- T0 regeneration: promised by both docs, and now done by the publish path --------


async def test_publishing_knowledge_recompiles_the_t0_block() -> None:
    """TRD §6's "regenerated on KB change", asserted at the artifact FLOWS §7 names.

    This was a strict xfail: `publish_source` minted no prompt version and touched no
    prompt, so approving new knowledge changed what the agent could RETRIEVE (T3, inside
    the engine per D-33) and never what it knows at zero latency — the tier TRD §6 says
    answers ~80% of questions. A client saw "published" and the agent kept answering
    from the block compiled at onboarding.

    Two assertions, because either alone would pass on a broken implementation: a NEW
    version (an in-place edit of the live version would satisfy "the facts are there"
    while breaking FLOWS §7's rollback), carrying the newly approved facts.
    """
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


#: Every request path `apps/voice-runtime` mounts, as (METHOD, path).
#:
#: THIS IS THE GUARD, and the token scan below is only its cheap second net. The event
#: that reverses D-33 is "an endpoint appeared on the caller's audio path", and an
#: endpoint is not a spelling — a retrieval tool called `POST /tools/v1/{engine}/lookup`
#: that posts a question to a managed vector API names none of `kb_sources`,
#: `kb_documents`, `knowledgebase` or `retrieve_kb`, and the blocklist that preceded this
#: set would have waved it through. (It could not even see `knowledge_base`, spelled with
#: the underscore this repo uses everywhere else.)
#:
#: The route inventory cannot be spelled around. It is also the pin that makes the
#: OTHER guards apply: `tests/voice_runtime_import_surface_test.py` bans `httpx`,
#: `apps.api.kb` and every model SDK both at boot AND across a request — but its request
#: pass drives a hand-maintained list of endpoints (`_drive`), so a lazy
#: `import httpx` inside a route nobody added to that list is invisible to it. A new row
#: here is the moment somebody has to add the route there too.
#:
#: Adding a row is allowed. It costs the measurement TRD §6.2 gates it on
#: (`tests/tool_endpoint_budget_test.py` is the harness) and a decision-log entry, which
#: is the whole point: this decision must be taken, not drifted into.
VOICE_RUNTIME_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        # BACKEND-PATTERNS §6's three, on every service.
        ("GET", "/healthz"),
        ("GET", "/healthz/live"),
        ("GET", "/healthz/ready"),
        # The post-call engine webhook receiver (hard rule 3's 500ms).
        ("POST", "/hooks/v1/engine/{engine}"),
        # The in-call opt-out (SEC-COMP §2.3, D-56). It retrieves nothing.
        ("POST", "/tools/v1/{engine}/opt-out"),
        # THE CALL-BACK PAIR (D-510), ADDED DELIBERATELY AND NOT DRIFTED INTO — which is
        # what this set exists to force, and this comment is the entry it demands.
        #
        # NEITHER RETRIEVES ANYTHING, which is the question D-33 asks of a new route on
        # this path. `callback` does exactly one piece of work before it defers: two
        # `strptime` calls and three comparisons over short strings
        # (`calevate_shared.calling_window.resolve_slot`) — no IO, no database, no model,
        # nothing that could grow into a lookup. `callback/cancel` computes nothing at all.
        # The reason that arithmetic is allowed here rather than in the worker behind it is
        # measurable and not stylistic: the caller is on the line being told whether we may
        # ring them at ten at night, and a refusal that arrives after they hang up is not a
        # refusal — it is a promise we cannot keep.
        #
        # THE COST THIS SET CHARGES IS PAID: `tests/callback_tool_test.py` drives both, and
        # both are driven in `voice_runtime_import_surface_test._drive` so the ban on
        # `httpx`, `apps.api.kb` and every model SDK is enforced ACROSS a request on them
        # and not only at boot.
        ("POST", "/tools/v1/{engine}/callback"),
        ("POST", "/tools/v1/{engine}/callback/cancel"),
    }
)


def test_in_call_retrieval_is_not_reimplemented_on_our_side() -> None:
    """D-33/TRD §6: v1 keeps T3 inside the engine's built-in KB precisely because the
    external route costs two extra hops (+150-400ms) against a 100ms budget. Our whole
    in-call KB surface is therefore the INGESTION side. A retrieval endpoint appearing in
    `apps/voice-runtime` is not a feature, it is that decision being reversed by
    accident, and it needs the measurement TRD §6 demands first.

    Asserted as the mounted ROUTE INVENTORY (see `VOICE_RUNTIME_ROUTES`) rather than as
    a token scan of the sources, which is what this was and which any plausible
    retrieval endpoint would have walked straight past. An EQUALITY, so it also fails if
    a route DISAPPEARS: the opt-out tool going missing is the compliance hole SEC-COMP
    §2.3 opened this endpoint to close, and it should not vanish quietly either.
    """
    import main as voice_runtime_app

    mounted = {
        (method.upper(), path)
        for path, operations in voice_runtime_app.app.openapi()["paths"].items()
        for method in operations
    }
    assert mounted == VOICE_RUNTIME_ROUTES, (
        "voice-runtime's mounted routes changed.\n"
        f"  added:   {sorted(mounted - VOICE_RUNTIME_ROUTES)}\n"
        f"  removed: {sorted(VOICE_RUNTIME_ROUTES - mounted)}\n"
        "Every path here runs while a caller is on the line. A retrieval endpoint is "
        "D-33 reversed and needs TRD §6.2's measurement first; anything else needs an "
        "entry in this set and a driven branch in "
        "`voice_runtime_import_surface_test._drive`."
    )

    # The cheap second net: the ingestion tables, by name, in a service that must never
    # read them. Kept because it catches a retrieval helper added to an EXISTING handler,
    # which changes no route.
    runtime = REPO_ROOT / "apps" / "voice-runtime"
    sources = [
        path.read_text(encoding="utf-8").lower()
        for path in runtime.rglob("*.py")
        if "__pycache__" not in path.parts
    ]
    assert sources, "premise: voice-runtime has python sources"
    for text_body in sources:
        for token in ("kb_documents", "kb_sources", "knowledge_base", "knowledgebase"):
            assert token not in text_body, (
                f"voice-runtime names {token!r}: in-call retrieval moved to our side "
                "without the p95 measurement TRD §6 gates it on"
            )


# --- T4: a prompt instruction whose measurement has no producer ----------------------


def _without_comments(source: str) -> str:
    """`source` with `#` comments removed, so a CROSS-REFERENCE is not read as a producer.

    The guard below is text-based on purpose — it must catch a table named inside a raw
    SQL string, which no import graph would show. But that made it fire on
    `crm/lead_projection.py`, which merely cites `kb_retrieval_logs` in prose to explain
    why it reuses that table's vocabulary. A comment cannot write a row, so dropping
    comments removes false positives without weakening the property: a string literal, an
    identifier and a docstring all still count.
    """
    out: list[str] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type != tokenize.COMMENT:
                out.append(tok.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return source  # unparseable: fall back to the blunt match rather than pass blindly
    return "\n".join(out)


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
        if table in _without_comments(path.read_text(encoding="utf-8")):
            hits.append(str(path.relative_to(REPO_ROOT)))
    return hits


def test_the_knowledge_gap_report_has_no_producer_and_cannot_yet() -> None:
    """The gap, dated 2026-08-11, and the argument for why it is not code we can write.

    TRD §6 makes T4 misses the input to the knowledge-gap report — "T4 misses are what a
    client should add next" — and `kb_retrieval_logs` is declared, migrated, indexed and
    RLS'd with nothing writing or reading it. This used to be a strict xfail, i.e. a bet
    that the producer was merely unbuilt. It is not: the producer cannot exist yet, for
    reasons that live outside this repository, and an xfail that can only flip when a
    VENDOR changes is a pin nobody can act on.

    1. **We never observe a retrieval.** D-33 keeps in-call retrieval inside the
       engine's own KB, and neither surface the engine gives us carries a retrieval
       outcome: `CallEvent` (webhook) is call lifecycle, `ExecutionSnapshot` (the
       authenticated fetch that is the truth) is status, cost, recording, transcript and
       `engine_extracted`. There is no query, no tier, no score, no retrieval latency in
       either. Whether Bolna can ever report one is pilot gate 8 — TRD §6 marks the
       surrounding behaviour UNVERIFIED for the same reason.
    2. **The obvious substitute is worse than nothing.** Inferring "the agent said it
       didn't know" from post-call transcripts would fill `query` with raw caller
       utterances in a table that has no `text_redacted` counterpart and no redaction
       path (hard rule 5 makes redacted the default everywhere transcripts are served),
       and would put guesses in `tier`, `top_score` and `latency_ms` — columns that
       describe a retrieval that did not happen on our side. A report built on that
       would tell a client which questions we THINK went unanswered, in a table whose
       column names claim measurement.
    3. **The reader has no home yet either.** TRD §6 assigns knowledge-gap analysis to
       the managed RAG/memory service, and the provider is blocked behind the D-28
       bake-off gate (runs with M2, "before any CRM feature depends on the provider").

    So the honest state is: the table stays, unwritten, as the shape the report will
    take; the doc's promise is deferred, not quietly satisfied by a table-filler. This
    test fails the day a producer appears — delete it then, and pin the producer's
    behaviour instead — and also the day the dated note vanishes from the model, which
    is what stops an inert table from losing its explanation.
    """
    assert _app_sources_naming("kb_retrieval_logs") == [], (
        "something now names kb_retrieval_logs: if it is a real producer of retrieval "
        "outcomes, delete this test and pin the producer; if it is a transcript-derived "
        "guess, see argument (2) above"
    )
    model_source = (REPO_ROOT / "apps" / "api" / "kb" / "models.py").read_text(encoding="utf-8")
    assert "GAP (2026-08-11)" in model_source, (
        "the dated gap note on KbRetrievalLog is the only place the table explains why "
        "it is empty; a table with no rows and no explanation gets filled by guesswork"
    )
