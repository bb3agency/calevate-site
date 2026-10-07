"""`/v1/worker` — the server half of the voice worker's wire contract (D-621).

`apps/voice-worker` runs on Pipecat Cloud and cannot reach our Postgres at all
(`docs/DEPLOYMENT.md` §12.5 gate 6). These three routes are what it speaks to instead, and
this file holds them to the five properties `docs/evidence/worker-http-contract.md` says must
be true when the seam is finished. Four of them are hard rules:

1. **A RETRIED DELIVERY LEAVES THE DATABASE EXACTLY AS ONE DELIVERY WOULD** — both ways,
   proved by sending the same batch twice and the same settlement twice and counting rows. It
   is asserted on the SETTLEMENT harder than on the batch, because `usage_events` and
   `call_metering_refusals` are append-only (hard rule 4): there is no UPDATE with which to
   correct a double write, so "answer the retry" is the only shape available and a second
   refusal row would be permanent.
2. **AUTHENTICATION DOES NOT DEGRADE** (hard rule 1's neighbour). No token is 401 on every
   route, and — the sharp end — a deployment with NO token configured authenticates nobody,
   because an absent credential is a deployment nobody wired up and never "no authentication
   required". These routes WRITE the ledger.
3. **THE TENANT COMES FROM THE REF AND NOTHING ELSE** (hard rule 1). A call ref the server
   did not mint is refused, and a body claiming a tenant the ref does not name is refused.
4. **THE SERVER REDACTS, AND A CLIENT'S REDACTION IS NOT STORED** (hard rules 5 and 6). That
   column is what every content reader in this repository names, so the value in it may not
   be one a container on a vendor's infrastructure computed.

SHARED DATABASE DISCIPLINE: every organisation is minted by this module, every assertion is
scoped to ids it created, and nothing counts rows globally.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.db.session import tenant_session
from apps.api.engine.pipecat import engine_agent_ref_for
from apps.api.main import app as api_app
from calevate_shared.engine import TRUTHFUL_ANSWER_DIRECTIVE, pipecat_call_ref
from calevate_shared.events import CallEvent, TranscriptTurn
from calevate_shared.worker_api import (
    MeteredQuantity,
    ObservationBatch,
    SettlementRefusal,
    SettlementRequest,
    UnverifiedCallClaim,
)
from pydantic import ValidationError
from sqlalchemy import text
from tests.worker_api_harness import (
    call_ref,
    declare_pipecat_engine,
    published_agent,
    worker_client,
)
from voice_worker.api_client import WorkerApiError

pytestmark = [pytest.mark.rls]


@pytest.fixture(autouse=True)
def _pipecat_deployment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every test in this file writes through `/v1/worker`, which refuses any other engine
    (D-627). `worker_api_harness.declare_pipecat_engine` records why this is per file."""
    yield from declare_pipecat_engine(monkeypatch)


#: A number the redactor must find, so "did the server redact?" is a question with a visible
#: answer rather than an equality against an unchanged string.
SPOKEN = "my number is 9812345672, call me back"


def batch(
    call_id: str,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    status: str = "in_progress",
    turns: tuple[tuple[int, str], ...] = (),
    text_redacted: str | None = None,
    from_e164: str | None = None,
    to_e164: str | None = None,
) -> ObservationBatch:
    return ObservationBatch(
        agent_id=agent_id,
        direction="inbound",
        from_e164=from_e164,
        to_e164=to_e164,
        events=[
            CallEvent(
                call_id=call_id,
                tenant_id=tenant_id,
                agent_id=agent_id,
                direction="inbound",
                status=status,  # type: ignore[arg-type]
                engine="pipecat",
            )
        ],
        turns=[
            TranscriptTurn(
                call_id=call_id,
                idx=idx,
                speaker="caller",
                text=spoken,
                text_redacted=text_redacted,
            )
            for idx, spoken in turns
        ],
    )


def refusal_settlement(agent_id: uuid.UUID) -> SettlementRequest:
    """One leg nobody could witness and nothing else measured — a silent call with no CDR.

    `meter.CarrierFactsMissingError`'s own four fields, because the worker sends the refusal
    its meter reached rather than one invented here (BLOCKER-1, §1.2).

    ⚠ **THIS USED TO SAY "the shape EVERY production call reaches today" AND IT IS NOW THE
    CORNER CASE (D-625).** A real call transcribes and synthesises, so the ordinary body
    carries this refusal AND the quantities beside it — see
    `test_a_refused_leg_does_not_discard_the_legs_beside_it`, which reuses these refusals for
    exactly that reason.
    """
    return SettlementRequest(
        final_status="completed",
        direction="inbound",
        agent_id=agent_id,
        refusals=[
            SettlementRefusal(
                leg="carrier",
                code="meter_carrier_cdr_missing",
                detail="no carrier CDR was supplied, so the connected duration has no witness.",
                remediation="Retrieve the CDR from the carrier and meter again.",
            )
        ],
    )


async def counts(tenant_id: uuid.UUID, ref: str) -> dict[str, int]:
    """Turns, usage rows, refusals and outbox promises for ONE call. Scoped, never global."""
    async with tenant_session(tenant_id) as db:
        row_id = (
            await db.execute(text("SELECT id FROM calls WHERE engine_call_id = :c"), {"c": ref})
        ).scalar_one()
        turns = (
            await db.execute(
                text("SELECT count(*) FROM transcript_turns WHERE call_id = :c"), {"c": row_id}
            )
        ).scalar_one()
        usage = (
            await db.execute(
                text("SELECT count(*) FROM usage_events WHERE call_id = :c"), {"c": row_id}
            )
        ).scalar_one()
        refusals = (
            await db.execute(
                text("SELECT count(*) FROM call_metering_refusals WHERE call_id = :c"),
                {"c": row_id},
            )
        ).scalar_one()
    async with tenant_session(tenant_id) as db:
        outbox = (
            await db.execute(
                text("SELECT count(*) FROM outbox_messages WHERE dedupe_key = :k"),
                {"k": f"post-call:{row_id}"},
            )
        ).scalar_one()
    return {"turns": turns, "usage": usage, "refusals": refusals, "outbox": outbox}


# ---------------------------------------------------------------------------------------
# 1. The session read.
# ---------------------------------------------------------------------------------------


async def test_the_session_read_answers_the_published_version_the_worker_must_run(
    worker_token: None,
) -> None:
    """The SELECT that used to live in `voice_worker/config.py`, now over the wire.

    The three fields worth asserting are the three the rest of the design rests on: the ids
    are ANSWERED (the worker presents a ref and never names a tenant), the prompt is the
    published version's, and `ai_disclosure_line` travels — because hard rule 5 is re-checked
    by the worker against what actually arrived (`config.refuse_unless_disclosed`), and it
    cannot check a sentence it was never sent.
    """
    tenant_id, agent_id, ref = await published_agent()
    async with worker_client() as api:
        answer = await api.session(ref)

    assert (answer.tenant_id, answer.agent_id) == (tenant_id, agent_id)
    assert answer.system_prompt and answer.prompt_sha256
    assert answer.ai_disclosure_line, "hard rule 5's sentence did not cross the wire"
    assert answer.models.llm_provider == "azure_openai"

    async with tenant_session(tenant_id) as db:
        stored = (
            await db.execute(
                text(
                    "SELECT v.composed_prompt, v.prompt_sha256, "
                    "p.resolved_config->>'opening_line' FROM pipecat_agents p "
                    "JOIN agent_config_versions v ON v.id = p.agent_config_version_id "
                    "WHERE p.agent_id = :a"
                ),
                {"a": agent_id},
            )
        ).one()
    assert (answer.system_prompt, answer.prompt_sha256) == (stored[0], stored[1])
    # The worker speaks this verbatim, so it must be the published version's own words.
    assert stored[2], "the fixture agent volunteers no notice, so this proves nothing"
    assert answer.opening_line == stored[2]


async def test_a_ref_that_names_no_published_agent_is_a_404_and_discloses_nothing(
    worker_token: None,
) -> None:
    """A stranger who guesses learns nothing — `carrier_routes.plivo_answer`'s answer.

    Both shapes: a ref this engine could never have minted, and a well-formed ref for an
    agent with no runtime row. They are ONE answer on purpose; a client that could tell them
    apart could enumerate which agents exist.
    """
    async with worker_client() as api:
        for ref in ("not-a-ref", engine_agent_ref_for(str(uuid.uuid4()), str(uuid.uuid4()))):
            with pytest.raises(WorkerApiError) as refused:
                await api.session(ref)
            assert "404" in str(refused.value)


async def test_a_published_version_without_the_truthful_answer_floor_is_never_served(
    worker_token: None,
) -> None:
    """Hard rule 5 on the server's side of the wire, not only the worker's.

    `mint_config_version` refuses to compose such a version, so the row is inserted by hand
    here — which is the only way one can exist, and exactly the case the check is for.
    """
    tenant_id, agent_id, ref = await published_agent()
    async with tenant_session(tenant_id) as db:
        version_id = uuid.uuid4()
        await db.execute(
            text(
                "INSERT INTO agent_config_versions (id, tenant_id, agent_id, prompt_sha256, "
                " model_config_sha256, composed_prompt, opening_line, model_config) "
                "SELECT :vid, tenant_id, agent_id, :sha, model_config_sha256, "
                "       'You are a helpful receptionist.', opening_line, model_config "
                "FROM agent_config_versions v "
                "WHERE v.id = (SELECT agent_config_version_id FROM pipecat_agents "
                "              WHERE agent_id = :a)"
            ),
            {"vid": version_id, "sha": "f" * 64, "a": agent_id},
        )
        await db.execute(
            text("UPDATE pipecat_agents SET agent_config_version_id = :v WHERE agent_id = :a"),
            {"v": version_id, "a": agent_id},
        )
    async with worker_client() as api:
        with pytest.raises(WorkerApiError) as refused:
            await api.session(ref)
    assert "409" in str(refused.value)


async def test_a_published_version_without_the_confidentiality_rule_is_never_served(
    worker_token: None,
) -> None:
    """D-674 on the server's side: the truthful floor alone is not enough. The version is
    inserted by hand because `mint_config_version` refuses to compose it."""
    tenant_id, agent_id, ref = await published_agent()
    async with tenant_session(tenant_id) as db:
        version_id = uuid.uuid4()
        await db.execute(
            text(
                "INSERT INTO agent_config_versions (id, tenant_id, agent_id, prompt_sha256, "
                " model_config_sha256, composed_prompt, opening_line, model_config) "
                "SELECT :vid, tenant_id, agent_id, :sha, model_config_sha256, "
                "       :prompt, opening_line, model_config "
                "FROM agent_config_versions v "
                "WHERE v.id = (SELECT agent_config_version_id FROM pipecat_agents "
                "              WHERE agent_id = :a)"
            ),
            {
                "vid": version_id,
                "sha": "e" * 64,
                "prompt": "You are a helpful receptionist.\n" + TRUTHFUL_ANSWER_DIRECTIVE,
                "a": agent_id,
            },
        )
        await db.execute(
            text("UPDATE pipecat_agents SET agent_config_version_id = :v WHERE agent_id = :a"),
            {"v": version_id, "a": agent_id},
        )
    async with worker_client() as api:
        with pytest.raises(WorkerApiError) as refused:
            await api.session(ref)
    assert "409" in str(refused.value)


async def test_the_preflight_probe_passes_on_a_good_token_and_fails_on_a_bad_one(
    worker_token: None,
) -> None:
    """`boot.open_runtime(verify=True)`'s whole readiness claim, which is what `SELECT 1` used
    to be and proves strictly more: a base URL carries no credential, so reachability alone
    would say nothing about whether this container may write anything."""
    async with worker_client() as api:
        await api.probe()
    async with worker_client(token="the-old-token") as stale:
        with pytest.raises(WorkerApiError) as refused:
            await stale.probe()
    assert "401" in str(refused.value)


# ---------------------------------------------------------------------------------------
# 2. Authentication.
# ---------------------------------------------------------------------------------------


async def test_every_route_refuses_a_caller_with_no_token(worker_token: None) -> None:
    """401 on all three, asked without the header at all rather than through the client —
    which always sends one, and would therefore never exercise this arm."""
    tenant_id, agent_id, ref = await published_agent()
    call_id, engine_call_id = call_ref(tenant_id)
    transport = httpx.ASGITransport(app=api_app, client=("127.0.0.1", 44444))
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as raw:
        answers = [
            (await raw.get(f"/v1/worker/session/{ref}")).status_code,
            (
                await raw.post(
                    f"/v1/worker/calls/{engine_call_id}/observations",
                    json=batch(call_id, tenant_id, agent_id).model_dump(mode="json"),
                )
            ).status_code,
            (
                await raw.post(
                    f"/v1/worker/calls/{engine_call_id}/settlement",
                    json=refusal_settlement(agent_id).model_dump(mode="json"),
                )
            ).status_code,
        ]
    assert answers == [401, 401, 401]
    # AND NOTHING WAS WRITTEN. A 401 that had already upserted the call row would be a
    # refusal in name only.
    async with tenant_session(tenant_id) as db:
        rows = (
            await db.execute(
                text("SELECT count(*) FROM calls WHERE engine_call_id = :c"),
                {"c": engine_call_id},
            )
        ).scalar_one()
    assert rows == 0


async def test_an_unconfigured_deployment_authenticates_nobody() -> None:
    """The sharp end, and the reason it is its own clause: with no token in `Settings` there
    is no value to compare against, and the tempting reading of that is "no authentication
    required". It is the opposite — a deployment that has not been wired to its worker yet —
    and on a surface that WRITES the ledger the cost of getting it backwards is unbounded.

    Note this test takes no `worker_token` fixture: that absence IS the subject.
    """
    from apps.api.core.settings import get_settings

    get_settings.cache_clear()
    assert get_settings().pipecat_worker_api_token is None, (
        "the control failed: a token is configured in this environment, so this clause "
        "would pass for the wrong reason"
    )
    tenant_id, _agent_id, ref = await published_agent()
    async with worker_client(token="anything-at-all") as api:
        with pytest.raises(WorkerApiError) as refused:
            await api.session(ref)
    assert "401" in str(refused.value)
    assert tenant_id  # the fixture ran; the refusal is not an absent-agent 404


# ---------------------------------------------------------------------------------------
# 3. Tenancy (hard rule 1).
# ---------------------------------------------------------------------------------------


async def test_a_call_ref_naming_another_tenant_cannot_be_written_through(
    worker_token: None,
) -> None:
    """**THE CROSS-TENANT CLAUSE, IN THE TWO SHAPES THE WIRE ADMITS.**

    A token holder is one container, and the only thing standing between it and another
    client's call is that the tenant is PARSED out of the ref and every statement then runs
    under that tenant's RLS. So: (a) a body claiming tenant A posted to a ref naming tenant B
    is refused rather than reconciled, and (b) neighbour B's tables hold nothing about the
    call afterwards.
    """
    a_tenant, a_agent, _ = await published_agent()
    b_tenant, b_agent, _ = await published_agent()
    _call_id, b_ref = call_ref(b_tenant)

    async with worker_client() as api:
        with pytest.raises(WorkerApiError) as refused:
            # The batch claims tenant A; the ref names tenant B.
            await api.post_observations(b_ref, batch(_call_id, a_tenant, a_agent))
    assert "422" in str(refused.value)

    for tenant in (a_tenant, b_tenant):
        async with tenant_session(tenant) as db:
            rows = (
                await db.execute(
                    text("SELECT count(*) FROM calls WHERE engine_call_id = :c"), {"c": b_ref}
                )
            ).scalar_one()
        assert rows == 0, "a refused batch minted a call row anyway"
    assert b_agent  # both fixtures really ran


async def test_another_tenants_agent_cannot_be_filed_onto_a_call(worker_token: None) -> None:
    """RLS does not stop a foreign-key check, so `calls.agent_id` would accept tenant A's
    agent on tenant B's call — and B's post-call pipeline would then run off A's extraction
    schema. Both writing routes that can mint the row refuse it before any row exists."""
    _a_tenant, a_agent, _ = await published_agent()
    b_tenant, _b_agent, _ = await published_agent()
    call_id, b_ref = call_ref(b_tenant)

    async with worker_client() as api:
        with pytest.raises(WorkerApiError) as observed:
            await api.post_observations(b_ref, batch(call_id, b_tenant, a_agent))
        with pytest.raises(WorkerApiError) as settled:
            await api.post_settlement(b_ref, refusal_settlement(a_agent))
    assert "422" in str(observed.value)
    assert "422" in str(settled.value)

    async with tenant_session(b_tenant) as db:
        rows = (
            await db.execute(
                text("SELECT count(*) FROM calls WHERE engine_call_id = :c"), {"c": b_ref}
            )
        ).scalar_one()
    assert rows == 0, "a call row was minted naming another tenant's agent"


async def test_a_ref_this_engine_never_minted_is_refused_before_any_row_is_touched(
    worker_token: None,
) -> None:
    """`tenant_of_pipecat_ref` returns None, and there is nowhere honest to write.

    ONE ANSWER for "not our ref", "not a call we minted" and "no such call", deliberately —
    a client that could tell them apart could enumerate call ids.
    """
    tenant_id, agent_id, _ = await published_agent()
    async with worker_client() as api:
        with pytest.raises(WorkerApiError) as refused:
            await api.post_observations("cartesia:whatever", batch("c", tenant_id, agent_id))
    assert "404" in str(refused.value)


# ---------------------------------------------------------------------------------------
# 4. Idempotency — the clause the whole contract turns on.
# ---------------------------------------------------------------------------------------


async def test_the_same_observation_batch_twice_leaves_exactly_one_row_per_turn(
    worker_token: None,
) -> None:
    """**A RETRIED BATCH INSERTS NOTHING TWICE**, on the `(call_id, idx)` unique constraint
    that already existed (`alembic/versions/05bba2f3c19c…:489`, `crm/models.py:213`).

    The counts are the assertion and the ANSWER is the second one: `turns_already_present`
    going from 0 to 2 is the idempotency working, and a client must not read the smaller
    `turns_written` as loss. A route that silently inserted duplicates would pass a test that
    only looked at the reply.
    """
    tenant_id, agent_id, _ = await published_agent()
    call_id, ref = call_ref(tenant_id)
    payload = batch(call_id, tenant_id, agent_id, turns=((0, "hello"), (1, SPOKEN)))

    async with worker_client() as api:
        first = await api.post_observations(ref, payload)
        second = await api.post_observations(ref, payload)

    assert (first.turns_written, first.turns_already_present) == (2, 0)
    assert (second.turns_written, second.turns_already_present) == (0, 2)
    assert (await counts(tenant_id, ref))["turns"] == 2


async def test_the_same_settlement_twice_writes_one_refusal_and_answers_already_settled(
    worker_token: None,
) -> None:
    """**THE CLAUSE THAT MATTERS MOST, BECAUSE THE LEDGER HAS NO UNDO.**

    `call_metering_refusals` carries no unique index and `usage_events` is append-only with a
    `calevate_forbid_mutation` trigger, so a second settlement that wrote a second row would
    be a permanent, uncorrectable double entry — and on the priced path, a double charge. The
    server therefore ANSWERS the retry: `already_settled`, nothing written, and the post-call
    pipeline still promised exactly once (a second promise would run extraction, the CRM
    fan-out and the hot-lead alert twice).

    The marker is the outbox row itself, claimed FIRST in the same transaction, which makes
    "have we settled this call?" the same atomic question as "have we promised its pipeline?".
    """
    tenant_id, agent_id, _ = await published_agent()
    call_id, ref = call_ref(tenant_id)

    async with worker_client() as api:
        await api.post_observations(ref, batch(call_id, tenant_id, agent_id))
        first = await api.post_settlement(ref, refusal_settlement(agent_id))
        second = await api.post_settlement(ref, refusal_settlement(agent_id))

    assert (first.already_settled, first.refusals_recorded, first.post_call_enqueued) == (
        False,
        1,
        True,
    )
    assert (second.already_settled, second.refusals_recorded, second.post_call_enqueued) == (
        True,
        0,
        False,
    )
    assert await counts(tenant_id, ref) == {
        "turns": 0,
        "usage": 0,
        "refusals": 1,
        "outbox": 1,
    }


async def test_a_settled_call_carries_the_post_call_promise_that_starts_the_pipeline(
    worker_token: None,
) -> None:
    """D-607, relocated to the side that owns the database. The outbox row names the job the
    dispatcher answers to and the ENGINE-SPACE handle the adapter parses the tenant out of —
    never the bare uuid, which `get_execution` could not read."""
    tenant_id, agent_id, _ = await published_agent()
    call_id, ref = call_ref(tenant_id)
    async with worker_client() as api:
        await api.post_observations(ref, batch(call_id, tenant_id, agent_id))
        await api.post_settlement(ref, refusal_settlement(agent_id))

    async with tenant_session(tenant_id) as db:
        row_id = (
            await db.execute(text("SELECT id FROM calls WHERE engine_call_id = :c"), {"c": ref})
        ).scalar_one()
        job, payload = (
            await db.execute(
                text("SELECT job, payload FROM outbox_messages WHERE dedupe_key = :k"),
                {"k": f"post-call:{row_id}"},
            )
        ).one()
    assert job == "run_post_call_pipeline"
    assert payload["execution_id"] == ref
    assert payload["call_id"] == str(row_id)
    assert payload["engine"] == "pipecat"


# ---------------------------------------------------------------------------------------
# 5. Redaction and the ordinary paths.
# ---------------------------------------------------------------------------------------


async def test_the_server_redacts_and_a_client_supplied_redaction_is_never_stored(
    worker_token: None,
) -> None:
    """**HARD RULES 5 AND 6 AT THE ONE PLACE THE WIRE COULD WEAKEN THEM.**

    `text_redacted` is the column every content reader in this repository names —
    `crm/assist.py::_TURNS_SQL`, `workers/caller_memory_distil.py::_TURNS_SQL` — i.e. it is
    what a client's dashboard, the copilot and caller memory are allowed to see. Until D-621
    it was computed inside a container a vendor's runtime operates. It is now computed here,
    by `apps/workers/redaction.redact`, and a value arriving in the body is IGNORED rather
    than trusted: this posts an obviously wrong one and asserts the stored column is the
    redactor's answer and not the client's.
    """
    tenant_id, agent_id, _ = await published_agent()
    call_id, ref = call_ref(tenant_id)
    async with worker_client() as api:
        await api.post_observations(
            ref,
            batch(
                call_id,
                tenant_id,
                agent_id,
                turns=((0, SPOKEN),),
                text_redacted="nothing to see here",
            ),
        )

    async with tenant_session(tenant_id) as db:
        raw, redacted = (
            await db.execute(
                text(
                    "SELECT t.text, t.text_redacted FROM transcript_turns t "
                    "JOIN calls c ON c.id = t.call_id WHERE c.engine_call_id = :c"
                ),
                {"c": ref},
            )
        ).one()
    assert raw == SPOKEN, "the raw column must hold what was said"
    assert redacted != "nothing to see here", "the client's redaction was stored"
    assert "9812345672" not in redacted, "the server did not redact the number"


async def test_a_turn_that_arrives_before_the_call_is_opened_still_lands(
    worker_token: None,
) -> None:
    """Pipecat dispatches every handler as its own task, so a turn can beat the event that
    opened the call — and `transcript_turns.call_id` is a foreign key with `ON DELETE
    RESTRICT`, so a race would surface as an IntegrityError mid-call.

    This is also why `ObservationBatch` carries `agent_id` and `direction`: a turns-only
    batch names no agent, and a `calls` row cannot be minted without one.
    """
    tenant_id, agent_id, _ = await published_agent()
    call_id, ref = call_ref(tenant_id)
    turns_only = ObservationBatch(
        agent_id=agent_id,
        direction="inbound",
        turns=[TranscriptTurn(call_id=call_id, idx=0, speaker="caller", text="hello")],
    )
    async with worker_client() as api:
        answer = await api.post_observations(ref, turns_only)
        await api.post_observations(ref, batch(call_id, tenant_id, agent_id, status="completed"))

    assert answer.turns_written == 1
    async with tenant_session(tenant_id) as db:
        status = (
            await db.execute(text("SELECT status FROM calls WHERE engine_call_id = :c"), {"c": ref})
        ).scalar_one()
    assert status == "completed"


async def test_a_status_never_moves_backwards_off_a_terminal_row(worker_token: None) -> None:
    """The forward-only clause, which is `apps/workers/pipeline._upsert_call_row`'s and moved
    here unchanged. A late `in_progress` on a completed call is exactly what it is for."""
    tenant_id, agent_id, _ = await published_agent()
    call_id, ref = call_ref(tenant_id)
    async with worker_client() as api:
        await api.post_observations(ref, batch(call_id, tenant_id, agent_id, status="completed"))
        await api.post_observations(ref, batch(call_id, tenant_id, agent_id, status="in_progress"))
    async with tenant_session(tenant_id) as db:
        status = (
            await db.execute(text("SELECT status FROM calls WHERE engine_call_id = :c"), {"c": ref})
        ).scalar_one()
    assert status == "completed"


async def test_a_row_the_hangup_made_terminal_still_takes_the_settlements_other_columns(
    worker_token: None,
) -> None:
    """FORWARD-ONLY PER COLUMN, NOT PER ROW. The carrier's hangup often lands before the
    worker settles; a row-level guard on the status skipped the whole update and lost the
    settlement's `carrier_call_id` (and `ended_at`, `duration_s`, `knowledge_state`)."""
    tenant_id, agent_id, _ = await published_agent()
    call_id, ref = call_ref(tenant_id)
    async with worker_client() as api:
        await api.post_observations(ref, batch(call_id, tenant_id, agent_id))
        async with tenant_session(tenant_id) as db:
            await db.execute(
                text("UPDATE calls SET status = 'no_answer' WHERE engine_call_id = :c"),
                {"c": ref},
            )
        settlement = refusal_settlement(agent_id).model_copy(
            update={"final_status": "failed", "carrier_call_id": "CA-hangup-first"}
        )
        await api.post_settlement(ref, settlement)
    async with tenant_session(tenant_id) as db:
        status, carrier_call_id = (
            await db.execute(
                text("SELECT status, carrier_call_id FROM calls WHERE engine_call_id = :c"),
                {"c": ref},
            )
        ).one()
    assert status == "no_answer", "a terminal status moved sideways"
    assert carrier_call_id == "CA-hangup-first", "the settlement's columns were dropped"


async def test_a_settlement_that_both_prices_and_refuses_one_leg_is_refused(
    worker_token: None,
) -> None:
    """A REFUSAL NAMES A LEG; QUANTITIES NAME OTHER LEGS (D-625), validated not trusted.

    ⚠ **THE EXCLUSIVITY THIS USED TO PIN IS GONE AND THE REPLACEMENT IS NARROWER.** A body
    offering priced legs AND a refusal is the ORDINARY shape now — it is what every call on
    this engine sends. What the ledger genuinely cannot hold is two contradictory records of
    ONE leg, because `usage_events` and `call_metering_refusals` are both append-only under
    hard rule 4 and neither has an UPDATE to correct the other with.

    Nothing is written, including the post-call promise: a refused settlement must not leave
    a pipeline owed over a ledger that was never set.
    """
    tenant_id, agent_id, _ = await published_agent()
    call_id, ref = call_ref(tenant_id)
    contradictory = SettlementRequest(
        final_status="completed",
        direction="inbound",
        agent_id=agent_id,
        refusals=refusal_settlement(agent_id).refusals,
        quantities=[MeteredQuantity(leg="carrier", unit_type="telephony_s", qty=Decimal("60"))],
    )
    async with worker_client() as api:
        await api.post_observations(ref, batch(call_id, tenant_id, agent_id))
        with pytest.raises(WorkerApiError) as refused:
            await api.post_settlement(ref, contradictory)
    assert "422" in str(refused.value)
    assert (await counts(tenant_id, ref))["outbox"] == 0, "a refused settlement promised a pipeline"


async def test_a_refused_leg_does_not_discard_the_legs_beside_it(worker_token: None) -> None:
    """**PARTIAL SETTLEMENT, ON THE SERVER (D-625), AND IT IS THE PRODUCTION SHAPE.**

    The worker measured STT seconds it really witnessed and could not witness the carrier's
    connected minute (BLOCKER-1). Under the old contract this body was a 422 — a refusal and
    quantities together — and the shape the worker sent instead was the refusal ALONE, so the
    measured leg never reached the ledger at all. `usage_events` is append-only, so it could
    not reach it afterwards either.

    BOTH ROWS ARE ASSERTED. A usage row without the refusal would be a call we believe we
    priced in full; a refusal without the usage row is what shipped.
    """
    tenant_id, agent_id, _ = await published_agent()
    call_id, ref = call_ref(tenant_id)
    request = SettlementRequest(
        final_status="completed",
        direction="inbound",
        agent_id=agent_id,
        refusals=refusal_settlement(agent_id).refusals,
        quantities=[MeteredQuantity(leg="stt", unit_type="stt_min", qty=Decimal("1.5"))],
    )
    async with worker_client() as api:
        await api.post_observations(ref, batch(call_id, tenant_id, agent_id))
        answer = await api.post_settlement(ref, request)

    assert (answer.rows_written, answer.refusals_recorded) == (1, 1)
    assert await counts(tenant_id, ref) == {"turns": 0, "usage": 1, "refusals": 1, "outbox": 1}


async def test_a_call_with_nothing_to_meter_settles_to_neither_a_row_nor_a_refusal(
    worker_token: None,
) -> None:
    """**THE THIRD STATE, AND IT IS NOT AN EMPTY SETTLEMENT.**

    A session that transcribed and synthesised nothing has no leg to price — which `meter.py`
    distinguishes deliberately from a leg nobody CAN price, and which `sink.Settlement`'s
    docstring names as its own case. It still has to settle, because the outbox row that
    starts the post-call pipeline rides the settlement (D-607); a call that never settled
    would never be extracted.

    ⚠ This clause exists because the shape check briefly refused exactly this body, which
    would have left such calls permanently unsettled with no pipeline and no alarm.
    """
    tenant_id, agent_id, _ = await published_agent()
    call_id, ref = call_ref(tenant_id)
    nothing = SettlementRequest(final_status="completed", direction="inbound", agent_id=agent_id)
    async with worker_client() as api:
        await api.post_observations(ref, batch(call_id, tenant_id, agent_id))
        answer = await api.post_settlement(ref, nothing)

    assert (answer.rows_written, answer.refusals_recorded) == (0, 0)
    assert answer.post_call_enqueued is True
    assert await counts(tenant_id, ref) == {"turns": 0, "usage": 0, "refusals": 0, "outbox": 1}


async def test_a_leg_whose_price_is_not_ours_to_know_is_recorded_rather_than_invented(
    worker_token: None,
) -> None:
    """**HARD RULE 7 AT THE WIRE.** `MeteredQuantity` carries no money by construction, so the
    server prices — and two of §1.3's five legs have no rate to price them WITH: the carrier's
    connected minute is priced by the carrier's own CDR (§1.2) and Pipecat Cloud's active
    minute is an unanswered vendor question (§7 P-1).

    A quantity naming either is therefore settled as a RECORDED REFUSAL, never as a figure
    the worker asserted. ⚠ **AND THE STT LEG BESIDE IT IS NOW WRITTEN (D-625)** — this
    docstring used to end "and is not written either, because there is no partial
    settlement", which is exactly the sentence that made this engine bill nothing.
    """
    tenant_id, agent_id, _ = await published_agent()
    call_id, ref = call_ref(tenant_id)
    request = SettlementRequest(
        final_status="completed",
        direction="inbound",
        agent_id=agent_id,
        quantities=[
            MeteredQuantity(leg="stt", unit_type="stt_min", qty=Decimal("1.5")),
            MeteredQuantity(leg="carrier", unit_type="telephony_s", qty=Decimal("60")),
        ],
    )
    async with worker_client() as api:
        await api.post_observations(ref, batch(call_id, tenant_id, agent_id))
        answer = await api.post_settlement(ref, request)

    assert (answer.refusals_recorded, answer.rows_written) == (1, 1)
    async with tenant_session(tenant_id) as db:
        row_id = (
            await db.execute(text("SELECT id FROM calls WHERE engine_call_id = :c"), {"c": ref})
        ).scalar_one()
        leg, code = (
            await db.execute(
                text("SELECT leg, code FROM call_metering_refusals WHERE call_id = :c"),
                {"c": row_id},
            )
        ).one()
        usage = (
            await db.execute(
                text("SELECT count(*) FROM usage_events WHERE call_id = :c"), {"c": row_id}
            )
        ).scalar_one()
    assert (leg, code) == ("carrier", "meter_leg_not_priceable_here")
    assert usage == 1, "the leg we could price was discarded with the one we could not"


async def _settle_one_stt_leg(quantity: MeteredQuantity) -> tuple[str, Decimal, Decimal, Any]:
    """Settle a call carrying one STT quantity; answer the usage row it wrote."""
    tenant_id, agent_id, _ = await published_agent()
    call_id, ref = call_ref(tenant_id)
    request = SettlementRequest(
        final_status="completed", direction="inbound", agent_id=agent_id, quantities=[quantity]
    )
    async with worker_client() as api:
        await api.post_observations(ref, batch(call_id, tenant_id, agent_id))
        answer = await api.post_settlement(ref, request)

    assert (answer.rows_written, answer.refusals_recorded) == (1, 0)
    async with tenant_session(tenant_id) as db:
        row_id = (
            await db.execute(text("SELECT id FROM calls WHERE engine_call_id = :c"), {"c": ref})
        ).scalar_one()
        unit, qty, cost, meta = (
            await db.execute(
                text(
                    "SELECT unit_type, qty, unit_cost_paid, meta FROM usage_events "
                    "WHERE call_id = :c"
                ),
                {"c": row_id},
            )
        ).one()
    return str(unit), Decimal(qty), Decimal(cost), meta


async def test_a_priced_leg_is_multiplied_by_the_rate_card_this_host_holds(
    worker_token: None,
) -> None:
    """The quantity is the WORKER's and the rate is OURS, and the rate survives the column.

    `stt_rate_inr_per_minute()` is the one door, read here rather than restated. The product
    is held to `STT_INR_PER_HOUR` directly: 90 s at ₹30/hour is ₹0.75, and the per-second
    unit this replaced stored ₹0.0083 a second and metered ₹0.747 (D-638).
    """
    from apps.api.billing.rates import STT_INR_PER_HOUR, stt_rate_inr_per_minute

    unit, qty, cost, _ = await _settle_one_stt_leg(
        MeteredQuantity(leg="stt", unit_type="stt_min", qty=Decimal("1.5"), meta={"source": "t"})
    )

    assert unit == "stt_min"
    assert qty == Decimal("1.5")
    assert cost == stt_rate_inr_per_minute() == Decimal("0.5")
    assert qty * cost == STT_INR_PER_HOUR * 90 / 3600 == Decimal("0.75")


async def test_an_older_worker_reporting_seconds_is_written_in_minutes(
    worker_token: None,
) -> None:
    """The worker deploys independently of this API, so an image older than D-638 still
    sends `stt_s`. The leg is priced, not refused, and lands in the ledger unit at the exact
    per-minute rate — never as a new `stt_s` row at the lossy per-second one."""
    unit, qty, cost, meta = await _settle_one_stt_leg(
        MeteredQuantity(leg="stt", unit_type="stt_s", qty=Decimal("90"))
    )

    assert unit == "stt_min"
    assert (qty, cost) == (Decimal("1.5000"), Decimal("0.5000"))
    assert qty * cost == Decimal("0.75")
    assert meta["audio_seconds"] == "90"


async def test_a_batch_larger_than_the_ceiling_is_refused_at_the_edge() -> None:
    """**EVERY CALLER-CONTROLLED LIST HAS A CEILING, AND THIS IS WHAT PROVES IT.**

    `check_list_bounds` governs RESPONSES and correctly does not reach a request body, but
    its argument does: what needs a ceiling is a list whose length the CALLER controls, and
    from the server's side that is exactly what this is. The client is a container on a
    third party's infrastructure holding a token — "our own worker would never send a
    million turns" is a fact about the code we ship, not about what can arrive on the socket.

    Refused by Pydantic at the edge (422), so the host never materialises the list in Python
    and never loops INSERTs over it. The ceilings sit far above any real flush
    (`PIPECAT_WORKER_TURN_BATCH_SIZE` defaults to 8), so nothing legitimate is ever refused.
    """
    from calevate_shared.worker_api import (
        MAX_EVENTS_PER_BATCH,
        MAX_QUANTITIES,
        MAX_TURNS_PER_BATCH,
    )

    with pytest.raises(ValidationError):
        ObservationBatch(
            agent_id=uuid.uuid4(),
            direction="inbound",
            turns=[
                TranscriptTurn(call_id="c", idx=i, speaker="caller", text="x")
                for i in range(MAX_TURNS_PER_BATCH + 1)
            ],
        )
    with pytest.raises(ValidationError):
        ObservationBatch(
            agent_id=uuid.uuid4(),
            direction="inbound",
            events=[
                CallEvent(
                    call_id="c",
                    tenant_id=uuid.uuid4(),
                    agent_id=uuid.uuid4(),
                    direction="inbound",
                    status="in_progress",
                    engine="pipecat",
                )
                for _ in range(MAX_EVENTS_PER_BATCH + 1)
            ],
        )
    with pytest.raises(ValidationError):
        SettlementRequest(
            final_status="completed",
            direction="inbound",
            agent_id=uuid.uuid4(),
            quantities=[
                MeteredQuantity(leg="stt", unit_type="second", qty=Decimal("1"))
                for _ in range(MAX_QUANTITIES + 1)
            ],
        )


async def _parties(tenant_id: uuid.UUID, ref: str) -> tuple[str | None, str | None]:
    async with tenant_session(tenant_id) as db:
        row = (
            await db.execute(
                text("SELECT from_e164, to_e164 FROM calls WHERE engine_call_id = :c"),
                {"c": ref},
            )
        ).one()
    return row[0], row[1]


async def test_a_batch_that_names_the_parties_writes_them_to_the_call(
    worker_token: None,
) -> None:
    """The seam D-623 exists to finish, end to end: wire model -> route -> column.

    ⚠ **NO CARRIER LEG CAN SEND THIS TODAY** (DEPLOYMENT §12.5 gate 9) — Pipecat's Plivo
    handshake parses neither party and the outbound dial is unbuilt. The test supplies them
    by hand, which is the point: the SERVER's half is provable now, so the day a producer
    exists nothing between the socket and the column has to be designed under pressure.
    """
    tenant_id, agent_id, _ = await published_agent()
    call_id, ref = call_ref(tenant_id)

    async with worker_client() as api:
        await api.post_observations(
            ref,
            batch(call_id, tenant_id, agent_id, from_e164="+919000000001", to_e164="+918000000002"),
        )

    assert await _parties(tenant_id, ref) == ("+919000000001", "+918000000002")


async def test_a_batch_without_parties_leaves_the_column_null_rather_than_inventing_one(
    worker_token: None,
) -> None:
    """**THE CASE EVERY PRODUCTION CALL ACTUALLY TAKES**, so it is asserted rather than
    assumed. A NULL here is honest: `leads.phone_e164` is NOT NULL and simply files no lead,
    caller memory skips the call on `from_e164 IS NOT NULL`, and the erasure subject is
    absent. Those are known consequences of an unbuilt producer — what must never happen is
    a placeholder that reads like a real number."""
    tenant_id, agent_id, _ = await published_agent()
    call_id, ref = call_ref(tenant_id)

    async with worker_client() as api:
        await api.post_observations(ref, batch(call_id, tenant_id, agent_id))

    assert await _parties(tenant_id, ref) == (None, None)


async def test_a_later_batch_neither_blanks_nor_overwrites_a_party_the_first_one_knew(
    worker_token: None,
) -> None:
    """**BOTH HALVES, BECAUSE ONLY THE SECOND ONE DISTINGUISHES THE UPSERT'S ARGUMENT
    ORDER** — and the first version of this test asserted only the first half and therefore
    passed against the wrong SQL. A `COALESCE` preserves a stored value under EITHER
    ordering when the incoming value is NULL, so the blanking case proves nothing about the
    order; only a DISAGREEMENT does.

    Half one: a later flush carrying no parties (every flush, in practice) must not blank
    them. Half two: a later flush carrying DIFFERENT parties must not adopt them — a second
    value is a disagreement, not an update, and silently taking the newer one would move a
    lead, a caller memory and a DPDP erasure subject to a different person with nothing
    logged anywhere.
    """
    tenant_id, agent_id, _ = await published_agent()
    call_id, ref = call_ref(tenant_id)

    async with worker_client() as api:
        await api.post_observations(
            ref,
            batch(call_id, tenant_id, agent_id, from_e164="+919000000003", to_e164="+918000000004"),
        )
        await api.post_observations(ref, batch(call_id, tenant_id, agent_id, turns=((0, "hi"),)))
        assert await _parties(tenant_id, ref) == ("+919000000003", "+918000000004")

        await api.post_observations(
            ref,
            batch(call_id, tenant_id, agent_id, from_e164="+917777777777", to_e164="+916666666666"),
        )

    assert await _parties(tenant_id, ref) == ("+919000000003", "+918000000004")


# ---------------------------------------------------------------------------------------
# The carrier's own id, and the outbound row the dial already wrote.
# ---------------------------------------------------------------------------------------

CARRIER_CALL_ID = "5401fd2e-6344-40df-a22c-c8ffea7a92e7"


async def _call_row(tenant_id: uuid.UUID, ref: str) -> Any:
    async with tenant_session(tenant_id) as db:
        return (
            await db.execute(
                text(
                    "SELECT id, carrier_call_id, direction, to_e164, agent_id, status "
                    "FROM calls WHERE engine_call_id = :c"
                ),
                {"c": ref},
            )
        ).one()


async def test_a_batch_records_the_carriers_call_id_and_a_later_one_cannot_move_it(
    worker_token: None,
) -> None:
    tenant_id, agent_id, _ = await published_agent()
    call_id, ref = call_ref(tenant_id)
    first = batch(call_id, tenant_id, agent_id).model_copy(
        update={"carrier_call_id": CARRIER_CALL_ID}
    )
    later = batch(call_id, tenant_id, agent_id, turns=((0, "hi"),)).model_copy(
        update={"carrier_call_id": "another-carrier-call"}
    )

    async with worker_client() as api:
        await api.post_observations(ref, first)
        await api.post_observations(ref, batch(call_id, tenant_id, agent_id))
        await api.post_observations(ref, later)

    assert (await _call_row(tenant_id, ref))[1] == CARRIER_CALL_ID


async def test_a_settlement_that_mints_the_row_records_the_carriers_call_id(
    worker_token: None,
) -> None:
    tenant_id, agent_id, _ = await published_agent()
    _call_id, ref = call_ref(tenant_id)
    request = refusal_settlement(agent_id).model_copy(update={"carrier_call_id": CARRIER_CALL_ID})

    async with worker_client() as api:
        await api.post_settlement(ref, request)

    assert (await _call_row(tenant_id, ref))[1] == CARRIER_CALL_ID


@pytest.mark.parametrize("value", ["", "x" * 65, "has space", "semi;colon", "+919876500001\n"])
def test_a_carrier_call_id_that_is_not_an_identifier_is_refused_at_the_edge(value: str) -> None:
    with pytest.raises(ValidationError):
        ObservationBatch(agent_id=uuid.uuid4(), direction="inbound", carrier_call_id=value)
    with pytest.raises(ValidationError):
        SettlementRequest(
            final_status="completed",
            direction="inbound",
            agent_id=uuid.uuid4(),
            carrier_call_id=value,
        )


async def _dialled_row(tenant_id: uuid.UUID, agent_id: uuid.UUID, *, stamped: str) -> uuid.UUID:
    """The row `agents.service.dispatch_call` writes before it dials, already stamped with
    whatever handle the dial returned."""
    row_id = uuid.uuid4()
    async with tenant_session(tenant_id) as db:
        await db.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, 'outbound', "
                "'+919876500009', 'queued', now(), now())"
            ),
            {"id": row_id, "tid": tenant_id, "aid": agent_id, "ecid": stamped},
        )
    return row_id


def _outbound(payload: Any) -> Any:
    """The same body with the direction an outbound call claim gives the worker."""
    update: dict[str, Any] = {"direction": "outbound", "carrier_call_id": CARRIER_CALL_ID}
    if isinstance(payload, ObservationBatch):
        update["events"] = [
            event.model_copy(update={"direction": "outbound"}) for event in payload.events
        ]
    return payload.model_copy(update=update)


@pytest.mark.parametrize("stamped", ["ours", "vendor"])
async def test_an_outbound_call_lands_on_the_row_the_dial_wrote(
    worker_token: None, stamped: str
) -> None:
    """The worker addresses an outbound call by the dialled row's own id, carried on the
    stream URL's signed call claim. Whether the dial stamped our ref or a vendor handle onto
    that row, the session and the settlement must converge on it and never mint a second
    row for one call — a second row would bill the call twice and leave the lead pointing
    at a row with no transcript."""
    tenant_id, agent_id, _ = await published_agent()
    probe = uuid.uuid4()
    row_id = await _dialled_row(
        tenant_id,
        agent_id,
        stamped=f"vendor-handle-{probe}" if stamped == "vendor" else f"placeholder-{probe}",
    )
    ref = pipecat_call_ref(tenant_id, row_id)
    if stamped == "ours":
        async with tenant_session(tenant_id) as db:
            await db.execute(
                text("UPDATE calls SET engine_call_id = :r WHERE id = :id"),
                {"r": ref, "id": row_id},
            )

    async with worker_client() as api:
        await api.post_observations(
            ref, _outbound(batch(str(row_id), tenant_id, agent_id, turns=((0, "hello"),)))
        )
        await api.post_settlement(ref, _outbound(refusal_settlement(agent_id)))

    row = await _call_row(tenant_id, ref)
    assert row[0] == row_id
    assert row[1] == CARRIER_CALL_ID
    assert (row[2], row[3]) == ("outbound", "+919876500009"), "the dialled party was lost"
    assert row[5] == "completed"
    async with tenant_session(tenant_id) as db:
        rows = (
            await db.execute(
                text("SELECT count(*) FROM calls WHERE id = :id OR engine_call_id = :r"),
                {"id": row_id, "r": ref},
            )
        ).scalar_one()
    assert rows == 1
    assert (await counts(tenant_id, ref)) == {"turns": 1, "usage": 0, "refusals": 1, "outbox": 1}


async def test_an_outbound_call_naming_another_agent_cannot_take_the_dialled_row(
    worker_token: None,
) -> None:
    """The dialled row is this tenant's (RLS), but it was dialled for ONE agent. A worker
    body naming another agent is refused exactly as on an inbound row, and the refusal rolls
    the re-key back with it."""
    tenant_id, agent_id, _ = await published_agent()
    other_agent = uuid.uuid4()
    async with tenant_session(tenant_id) as db:
        await db.execute(
            text(
                "INSERT INTO agents SELECT (jsonb_populate_record(NULL::agents, to_jsonb(a) || "
                "jsonb_build_object('id', CAST(:new AS text), 'name', a.name || ' (copy)', "
                "'engine_agent_ref', NULL))).* FROM agents a WHERE a.id = :aid"
            ),
            {"new": str(other_agent), "aid": agent_id},
        )
    stamped = f"vendor-handle-{uuid.uuid4()}"
    row_id = await _dialled_row(tenant_id, agent_id, stamped=stamped)
    ref = pipecat_call_ref(tenant_id, row_id)

    async with worker_client() as api:
        with pytest.raises(WorkerApiError) as refused:
            await api.post_observations(ref, _outbound(batch(str(row_id), tenant_id, other_agent)))
    assert "422" in str(refused.value)

    async with tenant_session(tenant_id) as db:
        kept = (
            await db.execute(
                text("SELECT engine_call_id FROM calls WHERE id = :id"), {"id": row_id}
            )
        ).scalar_one()
    assert kept == stamped


async def test_an_inbound_ref_never_re_keys_a_dialled_row(worker_token: None) -> None:
    """Only an OUTBOUND body may adopt a dialled row: an inbound call with a colliding id is
    a fresh row of its own."""
    tenant_id, agent_id, _ = await published_agent()
    stamped = f"vendor-handle-{uuid.uuid4()}"
    row_id = await _dialled_row(tenant_id, agent_id, stamped=stamped)
    ref = pipecat_call_ref(tenant_id, row_id)

    async with worker_client() as api:
        await api.post_observations(ref, batch(str(row_id), tenant_id, agent_id))

    async with tenant_session(tenant_id) as db:
        kept = (
            await db.execute(
                text("SELECT engine_call_id FROM calls WHERE id = :id"), {"id": row_id}
            )
        ).scalar_one()
    assert kept == stamped
    assert (await _call_row(tenant_id, ref))[0] != row_id


async def test_a_settlement_can_mint_the_row_with_its_parties(
    worker_token: None,
) -> None:
    """A call that failed before its first flush is minted BY THE SETTLEMENT, which is why
    `SettlementRequest` carries the pair too. If it did not, the one moment nothing else will
    supply them is exactly the moment they are lost."""
    tenant_id, agent_id, _ = await published_agent()
    _, ref = call_ref(tenant_id)

    async with worker_client() as api:
        await api.post_settlement(
            ref,
            SettlementRequest(
                final_status="failed",
                direction="inbound",
                agent_id=agent_id,
                from_e164="+919000000005",
                to_e164="+918000000006",
                refusals=[
                    SettlementRefusal(
                        leg="carrier",
                        code="carrier_facts_missing",
                        detail="no CDR",
                        remediation=None,
                    )
                ],
            ),
        )

    assert await _parties(tenant_id, ref) == ("+919000000005", "+918000000006")


# ---------------------------------------------------------------------------------------
# A settlement with no parties is an operator event (D-628).
# ---------------------------------------------------------------------------------------


def _capture_alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, dict[str, str]]]:
    """Every `alert()` the worker service fires, as (stage, code, ids).

    Patched on the MODULE THAT CALLS IT, which is the shape `fx_rate_test` established: the
    alarm path itself is under test elsewhere, and what matters here is that this call site
    reaches it at all.
    """
    import apps.api.worker.service as service_module

    fired: list[tuple[str, str, dict[str, str]]] = []

    def record(stage: str, code: str, *, detail: str | None = None, **ids: str) -> None:
        fired.append((stage, code, dict(ids)))

    monkeypatch.setattr(service_module, "alert", record)
    return fired


async def test_a_terminal_settlement_with_no_parties_is_an_operator_alert(
    worker_token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**THE SILENCE IS MADE AUDIBLE, BECAUSE IT COSTS SOMEBODY SOMETHING (D-628).**

    Nothing on this engine produces `calls.from_e164`/`to_e164` (§12.5 gate 9), and the
    consequence is not a blank screen field: `workers/pipeline.py:1600` cannot attribute a
    post-call OPT-OUT, so a caller who asked not to be called again gets no DNC row; `:1968`
    files no lead, because `leads.phone_e164` is NOT NULL; and a DPDP erasure has no subject.
    Only the first of the three says anything today, and only once a caller has actually
    opted out — which is one call too late to be a warning.

    Nothing is invented to fill the gap — the assertion below is that the row stays NULL AND
    that an operator is told.
    """
    tenant_id, agent_id, _ = await published_agent()
    call_id, ref = call_ref(tenant_id)
    fired = _capture_alerts(monkeypatch)

    async with worker_client() as api:
        await api.post_observations(ref, batch(call_id, tenant_id, agent_id))
        await api.post_settlement(ref, refusal_settlement(agent_id))

    assert await _parties(tenant_id, ref) == (None, None), "a party was invented"
    codes = [(stage, code) for stage, code, _ in fired]
    assert ("WORKER_TERMINAL", "call_settled_without_parties") in codes
    (ids,) = [ids for _stage, code, ids in fired if code == "call_settled_without_parties"]
    assert ids["tenant_id"] == str(tenant_id)


async def test_a_settlement_that_knows_one_party_raises_nothing(
    worker_token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ONE party is enough to attribute a suppression and to file a lead, so it is not the
    condition. The alarm fires on "nobody", never on "incomplete" — a code that fired on a
    knowable call would be the noise D-591 exists to keep out of the console."""
    tenant_id, agent_id, _ = await published_agent()
    _, ref = call_ref(tenant_id)
    fired = _capture_alerts(monkeypatch)

    async with worker_client() as api:
        await api.post_settlement(
            ref,
            SettlementRequest(
                final_status="completed",
                direction="inbound",
                agent_id=agent_id,
                from_e164="+919000000007",
            ),
        )

    assert [code for _stage, code, _ids in fired] == []


async def test_parties_learned_from_an_earlier_batch_are_not_reported_as_absent(
    worker_token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**THE ALARM READS THE COLUMN, NOT THE REQUEST**, and that is not a detail.

    The upsert COALESCEs the stored party over the incoming one, so a settlement carrying no
    parties against a call whose first observation batch DID carry them leaves the row intact
    — and an alarm that judged the request body would call that call unattributable and send
    an operator looking for a number that is already there.
    """
    tenant_id, agent_id, _ = await published_agent()
    call_id, ref = call_ref(tenant_id)

    async with worker_client() as api:
        await api.post_observations(
            ref, batch(call_id, tenant_id, agent_id, from_e164="+919000000008")
        )
        fired = _capture_alerts(monkeypatch)
        await api.post_settlement(ref, refusal_settlement(agent_id))

    assert [code for _stage, code, _ids in fired] == []


# ---------------------------------------------------------------------------------------
# A call claim the worker could not verify (PB1).
# ---------------------------------------------------------------------------------------


async def test_a_dialled_call_settled_as_inbound_pages_naming_both_rows(
    worker_token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The worker's `CARRIER_CLAIM_SECRET` differs from voice-runtime's, so the call we
    dialled ran as inbound under the worker's own id. The dialled row will never settle;
    only the server can tell this from a forgery, because only it can see the row."""
    tenant_id, agent_id, _ = await published_agent()
    dialled = await _dialled_row(tenant_id, agent_id, stamped=f"vendor-{uuid.uuid4().hex}")
    _, ref = call_ref(tenant_id)
    fired = _capture_alerts(monkeypatch)
    settlement = refusal_settlement(agent_id).model_copy(
        update={"call_claim_unverified": UnverifiedCallClaim(claimed_call_id=dialled)}
    )

    async with worker_client() as api:
        await api.post_settlement(ref, settlement)

    mismatches = [ids for _stage, code, ids in fired if code == "carrier_call_claim_mismatch"]
    assert len(mismatches) == 1
    assert mismatches[0]["call_id"] == str(dialled)
    assert mismatches[0]["settled_call_id"] != str(dialled)


@pytest.mark.parametrize("claimed", ["none", "unknown", "inbound"])
async def test_an_unverified_claim_naming_no_dialled_row_of_ours_does_not_page(
    claimed: str, worker_token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale or forged claim is a log line, not a page: it names no row, a row we never
    dialled, or (under RLS) another tenant's."""
    tenant_id, agent_id, _ = await published_agent()
    _, ref = call_ref(tenant_id)
    claimed_id = {"none": None, "unknown": uuid.uuid4(), "inbound": None}[claimed]
    if claimed == "inbound":
        other_call, other_ref = call_ref(tenant_id)
        async with worker_client() as api:
            await api.post_observations(other_ref, batch(other_call, tenant_id, agent_id))
        async with tenant_session(tenant_id) as db:
            claimed_id = (
                await db.execute(
                    text("SELECT id FROM calls WHERE engine_call_id = :c"), {"c": other_ref}
                )
            ).scalar_one()
    fired = _capture_alerts(monkeypatch)
    settlement = refusal_settlement(agent_id).model_copy(
        update={"call_claim_unverified": UnverifiedCallClaim(claimed_call_id=claimed_id)}
    )

    async with worker_client() as api:
        answer = await api.post_settlement(ref, settlement)

    assert answer.post_call_enqueued
    assert "carrier_call_claim_mismatch" not in [code for _stage, code, _ids in fired]


# ---------------------------------------------------------------------------------------
# The attestation route (D-626) and the engine gate (D-627).
# ---------------------------------------------------------------------------------------


async def test_the_worker_attestation_is_written_and_the_server_judges_it(
    worker_token: None,
) -> None:
    """**THE TABLE HAD NO PRODUCTION WRITER AT ALL UNTIL THIS ROUTE (D-626).**

    `record_attestation` was reachable only from tests, so `agent_config_attestations` was
    empty on every deployment and `PipecatEngine.get_agent` answered
    `system_prompt_readable=False` for every agent for ever — i.e. hard rule 5's engine-side
    verification never ran once on this leg.

    THE SERVER JUDGES, THE WORKER REPORTS. The digest sent here is the one the control plane
    itself wrote, so `matches` must be true; the next test sends a different one and it must
    be false, which is what proves the verdict is computed from the version row rather than
    echoed from the body.
    """
    from apps.api.agents.config_versions import latest_attestation
    from calevate_shared.worker_api import AttestationIn

    tenant_id, agent_id, agent_ref = await published_agent()
    async with tenant_session(tenant_id) as db:
        version_id, expected = (
            await db.execute(
                text(
                    "SELECT agent_config_version_id, v.prompt_sha256 FROM pipecat_agents p "
                    "JOIN agent_config_versions v ON v.id = p.agent_config_version_id "
                    "WHERE p.agent_id = :a"
                ),
                {"a": agent_id},
            )
        ).one()

    async with worker_client() as api:
        answer = await api.post_attestation(
            agent_ref,
            AttestationIn(
                agent_id=agent_id,
                agent_config_version_id=version_id,
                observed_prompt_sha256=expected,
            ),
        )

    assert answer.matches is True
    async with tenant_session(tenant_id) as db:
        stored = await latest_attestation(db, agent_id)
    assert stored is not None
    assert stored.prompt_sha256 == expected
    assert stored.matches is True


async def test_a_worker_running_a_different_prompt_is_recorded_as_a_mismatch(
    worker_token: None,
) -> None:
    """A MISMATCH IS A FINDING, NOT AN ERROR — a stale deploy, a version published after the
    session started, a prompt truncated on the way in. Refusing the write would delete the
    evidence of exactly the condition the table exists to catch, so it is a 200."""
    from calevate_shared.worker_api import AttestationIn

    tenant_id, agent_id, agent_ref = await published_agent()
    async with tenant_session(tenant_id) as db:
        version_id = (
            await db.execute(
                text("SELECT agent_config_version_id FROM pipecat_agents WHERE agent_id = :a"),
                {"a": agent_id},
            )
        ).scalar_one()

    async with worker_client() as api:
        answer = await api.post_attestation(
            agent_ref,
            AttestationIn(
                agent_id=agent_id,
                agent_config_version_id=version_id,
                observed_prompt_sha256="0" * 64,
            ),
        )

    assert answer.matches is False


async def test_the_writing_routes_refuse_a_deployment_running_another_engine(
    worker_token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**409, BECAUSE THE CONSUMER OF THESE ROWS DOES NOT ASK WHICH ENGINE WROTE THEM
    (D-627).** `settle_call` puts `"engine": "pipecat"` in the outbox payload and
    `workers/pipeline._post_call_target` never reads it — the adapter comes from the
    process-wide `ENGINE`. So on a deployment running another engine an accepted settlement
    mints rows whose pipeline asks the wrong vendor for this call, and the extraction, CRM
    columns and lead are lost.

    The SESSION READ is deliberately exempt: it writes nothing, and it is what `probe`
    presents at boot.
    """
    from apps.api.core.settings import get_settings as _settings

    tenant_id, agent_id, agent_ref = await published_agent()
    call_id, ref = call_ref(tenant_id)
    monkeypatch.setenv("ENGINE", "cartesia")
    _settings.cache_clear()

    async with worker_client() as api:
        await api.session(agent_ref)  # the read still answers
        with pytest.raises(WorkerApiError) as refused:
            await api.post_settlement(ref, refusal_settlement(agent_id))
        assert "409" in str(refused.value)
        with pytest.raises(WorkerApiError) as refused_batch:
            await api.post_observations(ref, batch(call_id, tenant_id, agent_id))
        assert "409" in str(refused_batch.value)

    async with tenant_session(tenant_id) as db:
        minted = (
            await db.execute(
                text("SELECT count(*) FROM calls WHERE engine_call_id = :c"), {"c": ref}
            )
        ).scalar_one()
    assert minted == 0, "a refused write still minted the call row it would have written to"


def test_an_unpriceable_leg_says_its_quantity_is_not_kept_anywhere() -> None:
    """The dead end, named where the next person will be standing.

    A `telephony_s` quantity is refused here AND its code is not in `REMETERABLE_CODES`, so
    `_record_remeter_demands` parks no measurement for it either. That is deliberate:
    nothing prices the carrier leg from a rate card, and the carrier's charge reaches the
    ledger from its CDR on the server (`workers/carrier_events.read_carrier_cdr`), never from
    a worker settlement. The refusal says where to look instead.

    Pure: no database, no route. `_price_one` is the whole decision.
    """
    from apps.api.worker.service import (
        REMETERABLE_CODES,
        _LegNotPriceableError,
        _price_one,
        _PricingBasis,
    )

    with pytest.raises(_LegNotPriceableError) as refused:
        _price_one(
            MeteredQuantity(leg="carrier", unit_type="telephony_s", qty=Decimal("60")),
            _PricingBasis(llm_model=None, tts_provider=None, tts_inr_per_1k=None),
        )

    refusal = refused.value.refusal
    assert refusal.code == "meter_leg_not_priceable_here"
    assert refusal.code not in REMETERABLE_CODES
    assert "recorded nowhere" in refusal.detail
    assert refusal.remediation is not None
    assert "read_carrier_cdr" in refusal.remediation
