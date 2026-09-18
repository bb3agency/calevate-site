"""`pipecat` adapter — the control plane of an engine we RUN rather than rent.

D-592 and `docs/PIPECAT-MIGRATION.md` (BINDING), step 3 of its §6. The conversation loop
is `apps/voice-worker/` on Pipecat Cloud; this module is the half that faces the rest of
`apps/api`, and it imports no Pipecat: *"The adapter imports no Pipecat. It speaks to the
worker through the database and, where a call must be started or ended now, through the
carrier's API"* (§2).

WHAT IS DIFFERENT ABOUT THIS ADAPTER, IN ONE PARAGRAPH
=======================================================
Every other adapter in this directory is a defence against a third party who might not
have done what we asked — that is `docs/evidence/voice-engine-contract-2026-09-13.md` §9's
unifying test for what is "Bolna-shaped". Delete the third party and most of those
defences stop measuring anything while still passing. So this file's job is not to make
the 25 methods return values; it is to say, for each one, whether the guarantee SURVIVED,
MOVED, or is VACUOUS — and to refuse rather than to answer where the thing being asked
about does not exist yet. Each method below states which of the three it is.

THE WITNESS MOVED (§1.1). `agent_hosting="owned_runtime"`, so `get_agent` answers from
`agent_config_attestations` — what a WORKER recomputed from the string in its own memory —
and never from the record this adapter itself wrote. An adapter answering from its own
tables would satisfy every clause in the conformance suite and measure nothing: *"it agrees
with the caller by construction"*, the defect `VoiceEngine.get_agent`'s docstring forbids,
arrived at by removing the vendor rather than by writing a lazy adapter.

THE CARRIER LEG IS NOT WRITTEN, AND THAT IS A REFUSAL RATHER THAN A GAP (hard rule 11).
`api.plivo.com` and `www.plivo.com/docs/` are EGRESS-BLOCKED from this container — measured
13 Sep 2026, `curl: (56) CONNECT tunnel failed, response 403`
(`docs/evidence/pre-build-blockers-2026-09-13.md` §10) — and Pipecat's own source contains
exactly ONE Plivo REST endpoint in the whole tree (the hangup,
`src/pipecat/serializers/plivo.py:184`). So the method, path, body and response shape of
every other carrier call are **UNKNOWN**, and writing them would mean inventing an API
surface. `pre-build-blockers` §10 is the research prompt that closes it; until it is
answered each carrier method refuses by name with that ground, and the capability
descriptor says so in the one place a screen reads.

NUMBERS ARE NOT AN API AT ALL (D-596, founder, 13 Sep 2026). `number_series` is EMPTY and
`search_numbers` / `provision_number` / `release_number` refuse — not because the surface
is unread but because this product does not buy numbers: where a number is ours it is a
**140 or 1600 series** number obtained by application through the carrier and the
regulatory process, and it is never retired
(`docs/evidence/pre-build-blockers-2026-09-13.md` §9). That settles a contradiction that
was open between two documents — the contract inventory's §9.1 reasoned these become
refusals, `PIPECAT-MIGRATION.md` §3 listed them as carrier calls, and §9.1 was right.

WHY THE STORE IS INJECTED
=========================
`PipecatControlPlane` is a Protocol and `SqlControlPlane` is the production implementation.
It is not indirection for its own sake, and it is not a seam for a second vendor — there
is no second vendor here. It exists because the far side of this adapter is a DATABASE AND
A SEPARATE PROCESS, and the conformance suite is required to run with neither: *"Neither
test touches the network — `make conformance` must be runnable on a plane"*
(`packages/shared/tests/engine_conformance/conftest.py`). Every other adapter gets that
property from `httpx.MockTransport`, which stands in for the vendor; this one gets it from
a store double that stands in for the database AND for the worker. The rejected
alternative was pointing the conformance subject at a live Postgres: `agent_config_
versions.agent_id` is a foreign key to `agents`, so every clause would first have to seed a
tenant and an agent, and the suite would stop being runnable offline to buy nothing.

WHAT THIS ADAPTER DELIBERATELY DOES NOT DO
==========================================
* It writes no `calls`, `transcript_turns` or `usage_events` row. Those are the pipeline's
  (`apps/workers/pipeline.py`), and an engine adapter that wrote them would be the second
  writer of the record it is supposed to be an independent reader of.
* It does not reach the worker. There is no call from here into `apps/voice-worker/`: the
  database is the whole interface, in both directions (§2).
* It holds no vendor SDK, no HTTP client and no vendor payload shape — so the transport
  ladder (`contract_test.py`'s `TRANSPORT_RECIPES`) does not apply to it, for `FakeEngine`'s
  reason: it does not speak to a vendor over HTTP, it speaks to our own store.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Protocol, cast
from uuid import UUID

from calevate_shared.engine import (
    E164,
    PIPECAT_REF_PREFIX,
    AccountKBListing,
    AccountKBObject,
    AgentConfig,
    AgentSnapshot,
    AvailableNumber,
    CallContext,
    CallHandle,
    EngineAgentRef,
    EngineCapabilities,
    EngineKBRef,
    EngineVoice,
    EngineVoiceListing,
    ExecutionListing,
    ExecutionSnapshot,
    KBSourceRef,
    LlmCredentialPlacement,
    LlmProvider,
    NumberSearch,
    NumberSpec,
    ProvisionedNumber,
    RecallOutcome,
    WebhookAuthMethod,
    WebhookVerdict,
    owned_runtime_agent_ref,
    tenant_of_pipecat_ref,
)
from calevate_shared.events import (
    TERMINAL_STATUSES,
    CallDirection,
    CallEvent,
    CallStatus,
    Speaker,
    TranscriptTurn,
)
from sqlalchemy import text

from apps.api.agents.config_versions import Attestation, latest_attestation, mint_config_version

if TYPE_CHECKING:
    from sqlalchemy.engine import CursorResult
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.session import joined_tenant_session, untenanted_session
from apps.api.engine.capabilities import (
    require_call_compliance_floor,
    require_capability,
    require_speech_leg,
)

log = get_logger(__name__)


#: THE REFUSAL CODE EVERY CARRIER METHOD GIVES, and it is deliberately NOT
#: `engine_capability_absent`.
#:
#: `capabilities.py` draws that line itself: `EngineCapabilityAbsentError` is *"NOT raised
#: for a capability that merely has not been VERIFIED — that stays
#: `engine_capability_unverified` in the adapter waiting on the evidence"*. Every method
#: below that carries this code is waiting on exactly one piece of evidence
#: (`pre-build-blockers` §10), and an operator who reads "this platform cannot do that"
#: would go looking for a different platform rather than for an answer that is one research
#: pass away. `CartesiaEngine` uses the same code for the same distinction.
CARRIER_UNVERIFIED_CODE: Final = "engine_capability_unverified"

#: WHY EVERY CARRIER METHOD IS A REFUSAL, IN THE WORDS AN OPERATOR GETS. One sentence,
#: composed once, for `_NOTE`'s reason in `agents/voices.py`: five hand-written copies
#: would be five chances to drift, and this one has a citation in it that must stay exact.
_CARRIER_REMEDIATION: Final = (
    "The telephony leg of this engine is not built yet: its provider's REST surface is "
    "not reachable from the build environment and has not been read. Nothing here is "
    "broken — this half has not been written. See docs/evidence/"
    "pre-build-blockers-2026-09-13.md §10."
)


def _carrier_not_written(what: str) -> ProblemError:
    """The named refusal a carrier method owes its caller.

    A FUNCTION RATHER THAN A CONSTANT because `detail` names the operation: "the platform
    cannot place calls yet" and "the platform cannot list its numbers yet" send an operator
    to the same document and to different lines of it, and a single generic sentence would
    make five distinct unbuilt things look like one broken one.

    `kind="dependency"` matches every other adapter's answer for "the engine cannot do
    this", so `apps.workers.pipeline.TRANSIENT_ENGINE_CODES` keeps classifying by code
    rather than by kind — and this code is NOT in that set, deliberately: a retry cannot
    write the missing half.
    """
    return ProblemError(
        kind="dependency",
        code=CARRIER_UNVERIFIED_CODE,
        title="The voice platform cannot do that yet",
        detail=what,
        remediation=_CARRIER_REMEDIATION,
    )


#: WHAT THIS ENGINE ANSWERS FOR ITSELF (D-93).
#:
#: Read the three groups separately, because they are true for three different reasons.
#:
#: **OURS BY CONSTRUCTION.** All three speech legs are `ours` and `agent_hosting` is
#: `owned_runtime`: we hold the agent record and we run the program, so every leg really is
#: our choice to make — that is the whole point of running the pipeline
#: (`PIPECAT-MIGRATION.md` §1.1). `knowledge_base` is True and `script_override` is True for
#: the same reason: both are writes to our own tables. §9.1 of the contract inventory
#: predicted `knowledge_base=False` and `PIPECAT-MIGRATION.md` §3's category B — which is
#: BINDING — puts all four KB methods in our own control plane instead, so they write our
#: tables rather than refusing. Nothing about T0 in-call retrieval moves: that is the
#: engine's own KB in `apps/voice-runtime`, `tests/kb_tiers_test.py` pins its route
#: inventory as an equality, and this adapter does not touch it.
#:
#: **FALSE UNTIL THE CARRIER SURFACE IS READ.** `caller_id`, `inbound_binding`,
#: `in_call_handoff` and `transfer` are all False, and every one of them is a fact about
#: the SAME missing half rather than four separate judgements: presenting a number we name,
#: routing an inbound number to an agent, handing a live caller to a human and stopping a
#: call from outside it are all operations against the carrier, whose API is UNKNOWN here
#: (see the module docstring). Declaring any of them True would be the "confident wrong
#: answer" the descriptor exists to make impossible — a console rendering a control that
#: reaches nothing. Each flips when `pre-build-blockers` §10 is answered, and the
#: conformance clause for each already runs in the refusal direction.
#:
#: ⚠ `in_call_handoff=False` HAS A COST WORTH STATING: a publish carrying a roster member
#: on duty is REFUSED rather than silently dropped (D-533), which is the safe direction and
#: is also the direction that makes an agent unpublishable on this engine while a roster is
#: live. That is correct today — an engine that cannot transfer a caller must not accept an
#: agent that promises to.
#:
#: **EMPTY BY DECISION, NOT BY IGNORANCE.** `number_series` is `frozenset()` because we do
#: not buy numbers through an API at all (D-596, founder 13 Sep 2026) — not because the buy
#: endpoint is unread. The distinction matters: the other four flip when a document is
#: read, and this one never does.
#:
#: `campaigns=False` because the Protocol has no campaign method, so a True is
#: unfalsifiable and the conformance suite refuses it outright. `webhook_auth="none"`
#: because nothing external calls us (`PIPECAT-MIGRATION.md` §3D) — see `verify_webhook`,
#: which records what that costs.
PIPECAT_CAPABILITIES = EngineCapabilities(
    # ⚠ **FALSE, AND THIS IS THE FIELD THAT STOPS AN AGENT LYING TO A CALLER.** Nothing in
    # `apps/voice-worker` captures audio — no recorder, no buffer, no upload — so
    # `calls.recording_url` is permanently NULL on this leg. Until that changes, clause 2 of
    # the truthful-answer floor must not say the call is recorded, because it is not.
    records_audio=False,
    stt="ours",
    tts="ours",
    llm="ours",
    agent_hosting="owned_runtime",
    campaigns=False,
    knowledge_base=True,
    number_series=frozenset(),
    caller_id=False,
    inbound_binding=False,
    transfer=False,
    in_call_handoff=False,
    # FALSE, AND IT IS A FACT ABOUT WHAT WE STORE (D-615). `agent_config_versions` holds
    # the composed prompt, the opening line and the model config — `mint_config_version`
    # writes those three and nothing else — so a during-call action has no way to reach the
    # worker, whose only tool is `build_knowledge_tool` (`voice_worker/pipeline.py`). It
    # published fine and dropped the tool, which is `in_call_handoff`'s failure over a
    # client's own integration: an empty tool list on a live agent looks exactly like a
    # client who configured none. It flips when the version carries the tools and the
    # worker dispatches them, which is work rather than a document to read.
    action_tools=False,
    script_override=True,
    webhook_auth="none",
)


@dataclass(frozen=True, slots=True)
class RuntimeAgent:
    """The engine's own record of one agent — what a vendor would hold for us.

    It is NOT the read-back. `get_agent` uses this only to prove the ref exists and to
    answer the two questions the attestation cannot (the agent's display name, and which
    documents the next session will load); everything a compliance check reads comes from
    the attestation instead. See `PipecatEngine.get_agent`.
    """

    engine_agent_ref: EngineAgentRef
    tenant_id: UUID
    agent_id: UUID
    name: str
    agent_config_version_id: UUID
    #: WHAT THE ENGINE WAS TOLD, as published. Not the read-back and never reported as one
    #: — `get_agent` answers from the worker's attestation, and this is the object
    #: `override_call_script` rewrites two fields of before minting the next version.
    config: AgentConfig


class PipecatControlPlane(Protocol):
    """Our own store and our own worker, as the adapter needs to see them.

    Narrow on purpose: every method here is one question the adapter asks, and nothing in
    it is shaped like SQL. That is what lets the conformance suite substitute a double for
    the database and the worker together without the adapter knowing (see the module
    docstring for why that substitution is necessary rather than convenient).
    """

    async def publish(self, cfg: AgentConfig, *, ref: EngineAgentRef) -> UUID:
        """Mint the config version for `cfg` and make `ref` name it. Returns its id."""
        ...

    async def runtime_agent(self, ref: EngineAgentRef) -> RuntimeAgent | None:
        """The engine's record for `ref`, or None if it holds none."""
        ...

    async def forget(self, ref: EngineAgentRef) -> None:
        """Remove the engine's record for `ref`. Absent is success."""
        ...

    async def attested(self, agent: RuntimeAgent) -> Attestation | None:
        """What a worker last said it loaded, or None if none ever has.

        It takes the whole record rather than an agent id because the read is
        tenant-scoped: `agent_config_attestations` is FORCE-RLS'd with no global-read
        policy, so a session with no tenant sees zero rows — which would read as "no worker
        has ever attested" and is the one wrong answer this method can give.
        """
        ...

    async def attach(self, agent: RuntimeAgent, *, handle: EngineKBRef, kb_id: str) -> None:
        """Record that this agent retrieves from `kb_id`, under the engine's `handle`."""
        ...

    async def detach(self, agent: RuntimeAgent, *, handle: EngineKBRef) -> bool:
        """Remove one attachment. False when this agent held no such handle."""
        ...

    async def agent_kb(self, agent: RuntimeAgent) -> tuple[EngineKBRef, ...]:
        """The handles this agent references now."""
        ...

    async def account_kb(self) -> tuple[AccountKBObject, ...]:
        """Every knowledge object on the ENGINE ACCOUNT, whoever it belongs to."""
        ...

    async def voices(self) -> tuple[EngineVoice, ...]:
        """Every voice this deployment's speech vendors are attested to speak."""
        ...

    async def execution(self, call_id: str) -> ExecutionSnapshot | None:
        """One session the runtime recorded, or None."""
        ...

    async def executions(self, *, since: datetime) -> tuple[ExecutionSnapshot, ...]:
        """Every session the runtime recorded that STARTED at or after `since` (D-367)."""
        ...


class SqlControlPlane:
    """`PipecatControlPlane` over the database this monolith already runs.

    **IT TAKES NO SESSION AND IT DOES NOT ALWAYS OPEN ONE.** `VoiceEngine`'s signatures
    carry no session and must not grow one — three of the four adapters speak to a vendor
    over HTTP and have no database at all, so a session parameter would put a storage
    concept into the port whose entire purpose is that adapters are interchangeable. So
    every method below asks `joined_tenant_session` for the tenant it already knows, which
    runs in the CALLER's transaction when the caller is in one for that same tenant and
    opens its own otherwise.

    ⚠ **IT USED TO OPEN ITS OWN UNCONDITIONALLY AND THAT WAS A DEADLOCK, NOT A DESIGN.**
    `agents/service.publish_agent` loads the `agents` row `FOR UPDATE` and calls
    `update_agent` while still holding it; `agent_config_versions.agent_id` and
    `pipecat_agents.agent_id` are both foreign keys to `agents`, and PostgreSQL validates a
    foreign key by taking `FOR KEY SHARE` on the referenced row — which conflicts with
    `FOR UPDATE`. A second connection therefore blocked on a lock only its own caller could
    release, while that caller was blocked awaiting this store: reachable in production
    from `kb/service.publish_source` → `recompile_t0` → `publish_agent` → `update_agent`,
    and invisible in CI only because the default test engine is the fake and touches no
    database. `db/session.joined_tenant_session` carries the full argument and the rejected
    alternatives.

    WHAT THAT CHANGES FOR A CALLER: on the join path this store's writes are part of the
    caller's transaction and roll back with it. That is the stronger guarantee and it is
    why the READS join too — after a joined `publish`, the `pipecat_agents` row is
    uncommitted, so a `runtime_agent` on a second connection would answer "no such agent"
    and turn every publish read-back into a refusal. One rule for every method is also the
    only rule that stays true when a new one is added.

    The engine calls that are NOT transactional stay exactly as they were:
    `kb/service.publish_source` attaches documents before it records its own claim row, so
    a crash between the two still leaves an account object no claim names — precisely the
    orphan `list_account_kb` exists to find, and why that method reads this store rather
    than the caller's claim table.

    Tenancy is RLS, as everywhere: writes and per-agent reads run under a tenant-scoped
    session, and the tenant comes out of the ref the adapter minted — never out of the
    ambient session, which `joined_tenant_session` makes structurally unreadable. The one
    exception is `account_kb`, which is cross-tenant by definition and runs untenanted
    against the `pipecat_kb_objects_global_read` policy (migration `e2f5a91c8d47`, on
    `engine_kb_routes`' pattern).
    """

    async def publish(self, cfg: AgentConfig, *, ref: EngineAgentRef) -> UUID:
        tenant_id = UUID(cfg.tenant_id)
        agent_id = UUID(cfg.agent_id)
        async with joined_tenant_session(tenant_id) as session:
            version = await mint_config_version(session, tenant_id, cfg)
            await session.execute(
                text(
                    "INSERT INTO pipecat_agents "
                    "(id, tenant_id, agent_id, engine_agent_ref, name, "
                    " agent_config_version_id, resolved_config) "
                    "VALUES (:id, :tid, :aid, :ref, :name, :vid, CAST(:cfg AS jsonb)) "
                    # UPDATE, not DO NOTHING: this row is engine STATE and `update_agent`
                    # is a full replacement by contract. The append-only history is
                    # `agent_config_versions`, which the line above wrote.
                    "ON CONFLICT (agent_id) DO UPDATE SET "
                    "  engine_agent_ref = EXCLUDED.engine_agent_ref, "
                    "  name = EXCLUDED.name, "
                    "  agent_config_version_id = EXCLUDED.agent_config_version_id, "
                    "  resolved_config = EXCLUDED.resolved_config, "
                    "  updated_at = now()"
                ),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "aid": agent_id,
                    "ref": ref,
                    "name": cfg.name,
                    "vid": version.id,
                    "cfg": json.dumps(cfg.model_dump(mode="json")),
                },
            )
            return version.id

    async def runtime_agent(self, ref: EngineAgentRef) -> RuntimeAgent | None:
        tenant_id = _tenant_of(ref)
        if tenant_id is None:
            # A ref this adapter did not mint. Not an error here — `get_agent` turns it
            # into the Protocol's "an unknown ref must RAISE" — and NOT a database round
            # trip either, because there is no tenant to scope one to.
            return None
        async with joined_tenant_session(tenant_id) as session:
            row = (
                await session.execute(
                    text(
                        "SELECT tenant_id, agent_id, name, agent_config_version_id, "
                        "       resolved_config "
                        "FROM pipecat_agents WHERE engine_agent_ref = :ref"
                    ),
                    {"ref": ref},
                )
            ).first()
        if row is None:
            return None
        return RuntimeAgent(
            engine_agent_ref=ref,
            tenant_id=row[0],
            agent_id=row[1],
            name=row[2],
            agent_config_version_id=row[3],
            # Validated rather than cast, `latest_attestation`'s reason: a row written
            # before a field moved must fail HERE, with the ref in hand, rather than inside
            # a Pydantic error three layers up in a publish.
            config=AgentConfig.model_validate(row[4]),
        )

    async def forget(self, ref: EngineAgentRef) -> None:
        tenant_id = _tenant_of(ref)
        if tenant_id is None:
            return
        async with joined_tenant_session(tenant_id) as session:
            # The agent's record goes; its KNOWLEDGE OBJECTS do not. That asymmetry is the
            # one `FakeEngine.delete_agent` argues at length and is the harder answer on
            # purpose: an account object nothing references is exactly the residue
            # `list_account_kb` exists to report, and a delete that tidied it away would
            # make the orphan report structurally incapable of finding anything.
            await session.execute(
                text("DELETE FROM pipecat_agents WHERE engine_agent_ref = :ref"), {"ref": ref}
            )
            await session.execute(
                text(
                    "UPDATE pipecat_kb_objects SET engine_agent_ref = NULL "
                    "WHERE engine_agent_ref = :ref"
                ),
                {"ref": ref},
            )

    async def attested(self, agent: RuntimeAgent) -> Attestation | None:
        async with joined_tenant_session(agent.tenant_id) as session:
            return await latest_attestation(session, agent.agent_id)

    async def attach(self, agent: RuntimeAgent, *, handle: EngineKBRef, kb_id: str) -> None:
        async with joined_tenant_session(agent.tenant_id) as session:
            await session.execute(
                text(
                    "INSERT INTO pipecat_kb_objects "
                    "(handle, tenant_id, engine_agent_ref, kb_id, state) "
                    "VALUES (:handle, :tid, :ref, :kb, 'ready') "
                    # Re-attaching the SAME source replaces the attachment rather than
                    # appending beside it, `FakeEngine.attach_kb`'s rule: a duplicate is
                    # precisely the defect the rest of this seam has to be able to expose.
                    "ON CONFLICT (handle) DO UPDATE SET "
                    "  engine_agent_ref = EXCLUDED.engine_agent_ref, "
                    "  kb_id = EXCLUDED.kb_id, state = 'ready'"
                ),
                {
                    "handle": handle,
                    "tid": agent.tenant_id,
                    "ref": agent.engine_agent_ref,
                    "kb": kb_id,
                },
            )

    async def detach(self, agent: RuntimeAgent, *, handle: EngineKBRef) -> bool:
        async with joined_tenant_session(agent.tenant_id) as session:
            result = await session.execute(
                text(
                    "DELETE FROM pipecat_kb_objects "
                    "WHERE handle = :handle AND engine_agent_ref = :ref"
                ),
                {"handle": handle, "ref": agent.engine_agent_ref},
            )
        # `CursorResult.rowcount` rather than `Result.rowcount` — the async `execute` is
        # typed as the general `Result`, and a DELETE's affected-row count is the one thing
        # this method has to report: it is what tells a detach that removed nothing from
        # one that removed something, which the Protocol requires it to RAISE on.
        return bool(cast("CursorResult[Any]", result).rowcount)

    async def agent_kb(self, agent: RuntimeAgent) -> tuple[EngineKBRef, ...]:
        async with joined_tenant_session(agent.tenant_id) as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT handle FROM pipecat_kb_objects "
                        "WHERE engine_agent_ref = :ref ORDER BY handle"
                    ),
                    {"ref": agent.engine_agent_ref},
                )
            ).scalars()
        return tuple(str(handle) for handle in rows)

    async def account_kb(self) -> tuple[AccountKBObject, ...]:
        async with untenanted_session() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT handle, kb_id, state, created_at FROM pipecat_kb_objects "
                        "ORDER BY handle"
                    )
                )
            ).all()
        return tuple(
            AccountKBObject(
                handle=str(row[0]),
                claimed_source_id=_claimed_source(str(row[1])),
                state=row[2],
                created_at=row[3],
            )
            for row in rows
        )

    async def voices(self) -> tuple[EngineVoice, ...]:
        """The voices an OPERATOR has attested, and nothing else.

        **THIS IS THE ONE METHOD WHOSE SOURCE GOT WEAKER RATHER THAN STRONGER, AND IT IS
        NOT A SHORTCUT.** `list_voices` exists because the ENGINE's catalogue is narrower
        than the model vendor's and the difference is a live 400 (D-585). With the engine
        deleted, the catalogue that matters is each speech vendor's own — Sarvam's and
        Cartesia's — and neither is reachable: `sarvam.ai` and `docs.sarvam.ai` are
        EGRESS-BLOCKED from this container (CLAUDE.md, re-measured 27 Aug 2026), and the
        clients that would call them live in `apps/voice-worker/`, which is step 4. So the
        only honest source is the rows an operator typed and attested
        (`platform_voice_catalog`, `origin = 'operator'`, D-590), which is what this reads.
        Inventing a speaker list would be the laundering hard rule 11 forbids.

        ⚠ **IT MADE `agents/voice_sync.sync_voice_catalogue` CIRCULAR ON THIS ENGINE —
        RE-AIMED IN D-615.** It read this listing and wrote it back into the table it came
        from, and the note here said the loop was "inert today" because an operator-origin
        row survives the sync's upsert untouched. That was half the story: the PRUNE arm is
        not an upsert. An operator-origin listing is `complete`, so the first tick after a
        deployment changed engine would stamp `withdrawn_at` on every row the operator had
        not attested — the whole `synced` catalogue a previous engine cached — and the
        empty-listing alarm would fire on a deployment that has simply attested nothing yet,
        naming a credential this adapter does not have. `sync_voice_catalogue` now refuses to
        run at all where `capabilities.lists_voices_independently()` is False, and
        `voice_admission.admit_voice` is the only writer left on this engine — which is the
        right answer, because an operator attesting a voice IS the authority once the vendor
        is gone. A `synced`-origin row left over from another engine is still deliberately
        NOT returned here.
        """
        async with untenanted_session() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT engine_voice_id, label, tts_model, languages, is_custom "
                        "FROM platform_voice_catalog "
                        "WHERE origin = 'operator' AND withdrawn_at IS NULL "
                        "ORDER BY tts_model, engine_voice_id"
                    )
                )
            ).all()
        return tuple(
            EngineVoice(
                voice_id=str(row[0]),
                label=str(row[1]),
                tts_model=str(row[2]),
                languages=tuple(str(code) for code in (row[3] or ())),
                is_custom=bool(row[4]),
            )
            for row in rows
        )

    async def execution(self, call_id: str) -> ExecutionSnapshot | None:
        """One session the runtime recorded, read back out of the rows it wrote (D-607).

        **THIS IS NOT THE THING `executions` REFUSES TO DO, AND THE DIFFERENCE IS THE WHOLE
        ARGUMENT.** That method is the POLLER's, and D-31 promotes the poller from safety
        net to guarantee of record precisely because the vendor's listing is an INDEPENDENT
        authority — a listing built from `calls` would be the poller comparing our store
        with itself, so it still answers nothing and its docstring still says why. This one
        is a POINT READ for a call somebody already told us about: `apps/voice-worker`
        committed the outbox row that started this pipeline in the same transaction as the
        call row, so the existence of the call is not in question here and nothing is being
        corroborated. What is being fetched is CONTENT — the transcript and the disposition
        — and on this engine we ARE the engine (§1.2: *"the transcript, the turns and the
        outcome are ours because nobody else ever had them"*), so our rows are the primary
        record rather than a second opinion about somebody else's.

        **WHY IT PARSES THE TENANT OUT OF THE ID.** `calls` is FORCE-RLS'd and this
        signature carries no tenant, so a row is unreachable until one is chosen — and
        choosing one is hard rule 1's whole subject. The three ways were: widen the policy
        (never), add a global `engine_call_id → tenant` routing table on
        `engine_agent_routes`' pattern, or mint the tenant into the id we already control.
        `pipecat_call_ref` is the third, on the argument `engine_agent_ref_for` records for
        the agent ref — with no incoming webhook and ids we mint, the resolution is a parse
        instead of a query. A ref this adapter did not mint parses to `None` and is
        reported as "no record", never guessed at.

        **WHAT IT DELIBERATELY LEAVES EMPTY, AND WHY EACH ONE IS THE HONEST ANSWER.**

        * `cost` — `None`, so `apps/workers/pipeline.py`'s metering stage does not run.
          That is not a gap: the worker already wrote this call's `usage_events` rows at
          settlement from the meter that watched the session, and a second pass pricing the
          same legs off a snapshot would be two writers of one append-only ledger.
        * `latency` — `None`. The worker records no per-turn timings today; inventing a
          `CallLatency()` would read as "the engine reported an object we could parse
          nothing out of", which is a different and false claim (`ExecutionSnapshot
          .latency`).
        * `raw_document` — `None`. There is no vendor document: the rows below ARE the
          record, and `_archive_engine_document` answers `none_offered`.
        * `recording_url` — whatever the row holds, which is `NULL` until something records
          audio. The worker does not (BLOCKER-1: the carrier leg is not built).
        * `from_e164`/`to_e164` — read from the row rather than assumed absent. The worker
          leaves them `NULL` because §1.2 gives the party numbers to the carrier's CDR, so
          today they are `None` and `_upsert_lead` correctly declines to file a lead under
          a number nobody witnessed; the day the reconciliation fills those columns this
          method starts returning them with no edit.
        * `billable_ready` — `False` unless the CDR has been reconciled, which nothing does
          yet. §1.2 again: *"the billable quantity is now witnessed by the party that
          charges for it"*, and nothing here may stand in for that.

        Hard rule 6: this returns transcript TEXT, which is what the extraction stage
        consumes and what `transcript_turns.text` already holds. It is never logged — the
        log line below is ids and counts.
        """
        tenant_id = tenant_of_pipecat_ref(call_id)
        if tenant_id is None:
            # A handle this adapter never minted — a deployment that has run another
            # engine, or a caller that passed `calls.id` where the engine-space id belongs.
            # Reported as "no record", because inventing a tenant to go looking with is the
            # one thing hard rule 1 forbids outright.
            return None
        async with joined_tenant_session(tenant_id) as session:
            row = (
                await session.execute(
                    text(
                        "SELECT id, agent_id, direction, status, started_at, ended_at, "
                        "       duration_s, from_e164, to_e164, recording_url "
                        "FROM calls WHERE engine_call_id = :ecid AND tenant_id = :tid"
                    ),
                    {"ecid": call_id, "tid": tenant_id},
                )
            ).first()
            if row is None:
                return None
            turns = (
                await session.execute(
                    text(
                        "SELECT idx, speaker, text, text_redacted, lang, start_ms, end_ms "
                        "FROM transcript_turns WHERE call_id = :cid AND tenant_id = :tid "
                        "ORDER BY idx"
                    ),
                    {"cid": row[0], "tid": tenant_id},
                )
            ).all()
        status = cast(CallStatus, str(row[3]))
        log.info(
            "pipecat_execution_read",
            extra={
                "tenant_id": str(tenant_id),
                "call_id": str(row[0]),
                "status": status,
                "turn_count": len(turns),
            },
        )
        return ExecutionSnapshot(
            engine_call_id=call_id,
            engine_agent_ref=engine_agent_ref_for(str(tenant_id), str(row[1])),
            direction=cast(CallDirection, str(row[2])),
            status=status,
            # OUR OWN VOCABULARY IS THE RAW ONE HERE, and that is not a shortcut. `raw_status`
            # exists so an adapter can report what the vendor said before the mapping; this
            # engine has no vendor and no second vocabulary, so the two are the same string
            # and a made-up second spelling would be an invention.
            raw_status=status,
            terminal=status in TERMINAL_STATUSES,
            billable_ready=False,
            started_at=row[4],
            ended_at=row[5],
            duration_s=row[6],
            from_e164=row[7],
            to_e164=row[8],
            recording_url=row[9],
            transcript=[
                TranscriptTurn(
                    call_id=call_id,
                    idx=int(turn[0]),
                    speaker=cast(Speaker, str(turn[1])),
                    text=str(turn[2]),
                    text_redacted=turn[3],
                    lang=turn[4],
                    start_ms=turn[5],
                    end_ms=turn[6],
                )
                for turn in turns
            ],
            # `PipecatEngine.name`, read off the class rather than spelled again: that
            # attribute is what `all_credential_env_keys` and the factory key off, and a
            # third spelling of the engine name is the drift `tests/engine_name_drift_test.py`
            # exists to catch.
            engine=PipecatEngine.name,
        )

    async def executions(self, *, since: datetime) -> tuple[ExecutionSnapshot, ...]:
        """Empty, always, and the system is CONSISTENT rather than unfinished.

        **IT DOES NOT READ `calls`**, and that is §9.2's warning taken literally: D-31
        promotes the poller from safety net to guarantee of record because the vendor's
        listing is an INDEPENDENT authority, and a `list_executions` that read the table
        `apps/workers/pipeline.py` writes FROM `list_executions` would be the poller
        comparing our store with itself.

        ⚠ **`execution()` NOW DOES READ `calls`, AND THE TWO ARE NOT IN CONTRADICTION
        (D-607).** That method is a POINT READ for a call the worker's own settlement
        transaction already attested through the outbox — nothing is being corroborated, and
        what it fetches is CONTENT, which §1.2 gives to us outright because nobody else ever
        had it. This one is the DISCOVERY question, "which calls happened that you have not
        heard about", and answering it from the table that holds what we have heard about is
        the tautology D-31 warns of. It stays empty until the runtime keeps a record of its
        own that is independent of `calls` — or, more likely, until §1.2's other half lands
        and the reconciliation reads the CARRIER's CDR, which is a genuinely independent
        authority and is the one this engine is entitled to.

        No dial can have happened yet in any case: `start_outbound_call` refuses every one
        of them on this engine (BLOCKER-1).
        """
        return ()


#: The prefix every ref this adapter mints starts with. Its own word rather than the engine
#: name, so a ref cannot be mistaken for a vendor id in a log line.
#:
#: RE-EXPORTED FROM THE CONTRACT PACKAGE, NOT DECLARED HERE. THREE deployables now speak
#: this grammar and none of them may import the others: the WORKER parses it off the
#: WebSocket URL a carrier connects to (`voice_worker/carrier.py`, agent refs) and mints
#: the CALL ref at settlement (`voice_worker/sink.py`), and this adapter reads both back.
#: Two spellings would be two programs disagreeing about which agent a ringing phone
#: reaches — which is exactly what happened: D-603 and D-607 landed `OWNED_RUNTIME_REF_
#: PREFIX` and `PIPECAT_REF_PREFIX` as two `Final = "pipecat"` declarations in one file.
#: Collapsed to one at integration.
_REF_PREFIX: Final = PIPECAT_REF_PREFIX


def engine_agent_ref_for(tenant_id: str, agent_id: str) -> EngineAgentRef:
    """`pipecat:<tenant>:<agent>` — the handle this engine gives one agent.

    **IT NAMES THE AGENT INSTEAD OF HASHING IT, AND THAT IS THE DECISION.** Every other
    adapter's ref is a vendor-minted opaque string, which is why `engine_agent_routes`
    exists: an incoming webhook carries only that string and resolving it to a tenant needs
    a table. Here WE mint it, nothing external ever sends it back to us, and a ref that
    carries its own two ids makes the resolution a parse instead of a query — which is the
    redundancy §9.2 of the contract inventory predicted (*"with no incoming webhook and ids
    we mint, the attribution table is redundant"*). Removing that table is a migration with
    an RLS story and is NOT done here; what is done is not adding a second dependency on it.

    Stable by construction, which is the conformance suite's ref-stability clause: the same
    agent published twice is the same ref, with no round trip to find out.

    THE BODY MOVED TO `calevate_shared.engine` AND THE NAME STAYED HERE: this module is
    where an adapter-shaped caller looks for it, and the worker — which must parse the
    same string on the carrier leg — cannot import an `apps.api` module at all.
    """
    return owned_runtime_agent_ref(tenant_id, agent_id)


def _tenant_of(ref: EngineAgentRef) -> UUID | None:
    """The tenant an AGENT ref names, or None if this adapter did not mint it.

    Delegated rather than open-coded: the agent ref and the call ref
    (`calevate_shared.engine.pipecat_call_ref`) are one format with one tenant position,
    and the worker cannot import this module to reuse a parser that lived here — so the
    parser lives in `calevate_shared` and both callers use it. The four lines this
    replaced were byte-identical to it.
    """
    return tenant_of_pipecat_ref(ref)


def _claimed_source(kb_id: str) -> UUID | None:
    """`KBSourceRef.kb_id` as a source id, or None when it is not one.

    `AccountKBObject.claimed_source_id` documents itself as a CLAIM rather than a fact, and
    inventing an attribution for a non-uuid is exactly the guess it refuses to make.
    `FakeEngine._claimed_source` is the same function for the same reason.
    """
    try:
        return UUID(kb_id)
    except ValueError:
        return None


class PipecatEngine:
    """Implements `VoiceEngine` against our own control plane and our own runtime."""

    name = "pipecat"
    capabilities = PIPECAT_CAPABILITIES

    #: EMPTY, and the annotation is load-bearing on every adapter (`bolna.py`): without
    #: `tuple[str, ...]` mypy infers a one-element tuple type, a Protocol's mutable
    #: attributes are invariant, and the class stops satisfying `VoiceEngine` the day a
    #: second key is added.
    #:
    #: Empty because this adapter IS its own vendor for everything it currently does: the
    #: control plane is our database, which every deployable already has, so there is no
    #: key an operator could set that would change whether it works.
    #:
    #: ⚠ **AND THAT IS A REAL LOSS OF RESOLUTION, NOT A CLEAN ANSWER** — §9.3 names it. A
    #: running pipeline needs Sarvam, Cartesia, an LLM leg and the carrier, and
    #: `holds_credentials() -> bool` cannot say "it can transcribe and cannot synthesise".
    #: Those keys are the WORKER's (step 4) and they are not read here, so listing them
    #: would make readiness report on a process this one does not run. Readiness is honest
    #: today for a different reason: nothing on this engine can place a call at all, and it
    #: refuses by name rather than by a red light.
    #:
    #: **D-614 ADDED THE CARRIER PAIR TO `Settings` AND DELIBERATELY DID NOT ADD IT HERE.**
    #: `plivo_auth_id` / `plivo_auth_token` are now real fields, so this tuple COULD name
    #: them — and naming them would turn `/healthz/ready` red on every host, permanently,
    #: for a credential no VPS process reads and that belongs in a container's secret set
    #: (`core/settings.ENV_ONLY_FOREIGN_ENV`). `missing_engine_credential_keys` asks "can
    #: THIS process reach its vendor", and the answer for those two is "this process never
    #: tries". The loss of resolution above is unchanged by that decision, not cured by it.
    credential_env_keys: tuple[str, ...] = ()

    def __init__(self, *, store: PipecatControlPlane | None = None) -> None:
        self._store: PipecatControlPlane = store if store is not None else SqlControlPlane()

    def holds_credentials(self) -> bool:
        """True: the control plane is our own store, so there is nothing to configure.

        Not a stub and not optimism. The question this method answers is *"can this
        adapter actually talk to its vendor?"* and this adapter's vendor is us — the same
        answer `FakeEngine` gives, for the same structural reason rather than because it is
        a fixture. The half that genuinely could be unconfigured is the carrier, and that
        refuses by name from the capability descriptor, which is where a screen asks.
        """
        return True

    # --- ids -----------------------------------------------------------------

    @staticmethod
    def _kb_handle(ref: EngineAgentRef, kb_id: str) -> EngineKBRef:
        """The engine's handle for one attached source.

        Derived from (agent ref, our kb_id) rather than minted, so a re-attach of the same
        source addresses the same object instead of stranding the previous one — the leak
        `attach_kb`'s docstring calls "a KB that can only ever grow". `FakeEngine` derives
        its handles the same way and for the same reason.
        """
        digest = hashlib.sha256(f"{ref}|{kb_id}".encode()).hexdigest()[:24]
        return f"pckb_{digest}"

    # --- guards --------------------------------------------------------------

    def _assert_speech_is_ours(self, cfg: AgentConfig) -> None:
        """Refuse a selection for any leg this engine does not own, on BOTH write paths.

        Every leg IS ours here, so these three calls pass today — and they are made anyway,
        for `FakeEngine._assert_speech_is_ours`' reason: the guard belongs to the WRITE
        path, not to the descriptor that happens to be permissive, and an adapter that
        checked only where it currently refuses is one edit away from accepting a value it
        cannot honour. The handoff arm is the one that actually bites here
        (`in_call_handoff=False`, see the capability descriptor).
        """
        require_speech_leg("stt", engine=self, value=cfg.models.stt_model)
        require_speech_leg("llm", engine=self, value=cfg.models.llm_model)
        require_speech_leg("tts", engine=self, value=cfg.models.tts_voice)
        if cfg.handoff is not None:
            require_capability("in_call_handoff", engine=self)
        # THE ACTIONS ARM, AND IT IS THE ONE THAT ACTUALLY BIT (D-615). `AgentConfig
        # .action_tools` is filled on every publish by `agents/service.publish_agent`, this
        # adapter never read it, and `mint_config_version` stores only the composed prompt,
        # the opening line and the model config — so a client's during-call action was
        # dropped between the console saying "live" and the worker, which builds one tool
        # (`build_knowledge_tool`) and knows nothing about ours. Refusing by name is
        # `in_call_handoff`'s rule applied to the same class of silence.
        if cfg.action_tools:
            require_capability("action_tools", engine=self)

    def _assert_this_engine_hosts_agents(self) -> None:
        """Present for the shape rather than for the branch it takes.

        `owned_runtime` answers `hosts_agents()` True, so this never refuses on this
        adapter. It is here because the three agent methods on EVERY adapter go through one
        named assert, and an adapter that omitted it would be the one place a future
        capability change stopped being enforced.
        """
        require_capability("agent_hosting", engine=self)

    async def _held(self, ref: EngineAgentRef) -> RuntimeAgent:
        """The engine's record for `ref`, or the Protocol's refusal for an unknown one.

        *"An unknown ref must RAISE, not return an empty snapshot. A caller reading back an
        agent that does not exist is a caller about to record 'prompt not applied' for an
        agent it never created."*
        """
        held = await self._store.runtime_agent(ref)
        if held is None:
            raise ProblemError(
                kind="dependency",
                code="engine_rejected",
                # NOT "voice engine rejected the request", which this adapter inherited
                # from a rented-engine refusal and which is false twice here: nothing
                # rejected anything, and WE are the engine. `plain_language_guard` caught
                # the wording — "the request" is not a thing the reader can see — and the
                # honest title is the one that names what is missing.
                title="That agent is not on the voice platform",
                detail="The voice platform does not hold that agent.",
            )
        return held

    # --- B: our own control plane (PIPECAT-MIGRATION.md §3 category B) --------

    async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
        """Put the agent on the engine — which here means minting the version a worker
        loads and recording the handle that names it.

        THE VERSION IS THE POINT, not the row. `mint_config_version` is where hard rule 5
        stops being VERIFIED against a vendor and becomes STRUCTURAL: it refuses a config
        whose composed prompt does not carry the truthful-answer floor, and the version is
        immutable, so a worker that loads it will attest to exactly those bytes.
        """
        self._assert_this_engine_hosts_agents()
        self._assert_speech_is_ours(cfg)
        ref = engine_agent_ref_for(cfg.tenant_id, cfg.agent_id)
        await self._store.publish(cfg, ref=ref)
        return ref

    async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None:
        """Full replacement, which on this engine is a new version plus a re-pointed row.

        It does NOT check that `ref` already exists. That is deliberate and matches the
        content-addressed store underneath: the ref is a pure function of the two ids in
        `cfg`, so an update against a ref this engine has never held is an update of the
        agent that ref NAMES, and publishing it is the same act as creating it. The
        alternative — refusing — would make a republish after a `delete_agent`
        compensation fail for no reason a caller could act on.
        """
        self._assert_this_engine_hosts_agents()
        self._assert_speech_is_ours(cfg)
        await self._store.publish(cfg, ref=ref)

    async def override_call_script(
        self, ref: EngineAgentRef, *, opening_line: str, system_prompt: str
    ) -> None:
        """Swap what the agent SAYS, keeping everything else it is (D-544).

        §9.1 of the contract inventory predicts this method "collapses into `update_agent`"
        here, because the reason it exists — Bolna's full-replacement PUT costing a whole
        agent body twice per window — is a vendor cost we no longer pay. It is kept as a
        separate method anyway, and the reason is not symmetry: `workers/maintenance.py`
        calls it with a COMPOSED maintenance script and no `AgentConfig` at all, so
        collapsing it would move the composition into the caller and give the maintenance
        window a second way to write an agent. One way per problem means this stays the one
        way to say "keep the agent, change the words".

        The two strings replace the config's own and are re-composed through
        `compose_engine_prompt` inside `mint_config_version`, exactly as every other
        adapter re-composes them — so the override is a real version a worker can load and
        attest, not a side channel the read-back cannot see.
        """
        require_capability("script_override", engine=self)
        held = await self._held(ref)
        # `model_copy(update=...)` and not a mutation, `FakeEngine.override_call_script`'s
        # reason: the config is what the next version is minted from, and rebuilding it
        # with exactly two fields replaced is what makes "nothing else moved" a property of
        # the stored object rather than of the code that wrote it.
        await self._store.publish(
            held.config.model_copy(
                update={"opening_line": opening_line, "system_prompt": system_prompt}
            ),
            ref=ref,
        )

    async def delete_agent(self, ref: EngineAgentRef) -> None:
        """Remove the agent. **IDEMPOTENT BY CONTRACT** — absent is the post-condition
        already satisfied, never an error, because the only caller is the orphan
        compensator and raising there would DLQ a job whose work is done.

        The agent's KNOWLEDGE OBJECTS survive it (see `SqlControlPlane.forget`), and the
        `agent_config_versions` history survives it absolutely: that table is append-only
        (hard rule 4) and an attestation quoting one of its rows must stay resolvable
        after the agent is gone, or the record of what a worker was running in March
        disappears the day somebody deletes an agent in September.
        """
        await self._store.forget(ref)

    async def attach_kb(
        self, ref: EngineAgentRef, source: KBSourceRef, *, agent: AgentConfig | None = None
    ) -> EngineKBRef:
        """Record that this agent retrieves from an approved source, and name the copy.

        `agent` IS IGNORED, and that is the honest answer rather than an oversight (D-488).
        It exists for engines that hold the knowledge linkage as agent state and can only
        rewrite it with a full-replacement PUT; here the linkage is a row of its own, so
        there is no second object to keep in step.

        **IT PUSHES NO TEXT ANYWHERE, AND THAT IS THE SHAPE RATHER THAN A GAP.** On a rented
        engine this uploads a document to the vendor and the handle addresses the vendor's
        copy. Here the text is already in `kb_documents`/`kb_chunks` — the store the
        retriever reads (D-502, pgvector in the Postgres we already run) — so the only new
        fact is WHICH approved sources this agent may retrieve from, which is what this
        row is. An adapter that copied the chunks into a second table would be the second
        writer of a client's knowledge.
        """
        require_capability("knowledge_base", engine=self)
        held = await self._held(ref)
        handle = self._kb_handle(ref, source.kb_id)
        await self._store.attach(held, handle=handle, kb_id=source.kb_id)
        return handle

    async def detach_kb(
        self, ref: EngineAgentRef, kb: EngineKBRef, *, agent: AgentConfig | None = None
    ) -> None:
        """Remove one attachment, and RAISE if there was nothing to remove.

        *"Detaching a handle the engine does not have MUST RAISE"* — the publisher's next
        act is to attach the replacement, and it is entitled to know the old text is gone.
        Deliberately not `delete_agent`'s absent-is-success: the two methods have different
        callers and the test is what the caller does next.
        """
        require_capability("knowledge_base", engine=self)
        held = await self._held(ref)
        if not await self._store.detach(held, handle=kb):
            raise ProblemError(
                kind="dependency",
                code="engine_rejected",
                title="That knowledge base is not attached to this agent",
                detail="The voice platform does not hold that knowledge base.",
            )

    async def list_kb(self, ref: EngineAgentRef) -> list[EngineKBRef]:
        """The handles this agent references now.

        Refuses on an unknown ref rather than answering `[]`, for `get_agent`'s reason: an
        empty list is a POSITIVE claim that the agent holds no documents, and
        `kb/service._reconcile_engine_state` reads exactly that claim to decide whether the
        engine is serving text our rows cannot account for.
        """
        require_capability("knowledge_base", engine=self)
        held = await self._held(ref)
        return list(await self._store.agent_kb(held))

    async def list_account_kb(self) -> AccountKBListing:
        """Every knowledge object on the ENGINE ACCOUNT, referenced or not.

        **IT READS THE OBJECT TABLE AND NOT THE AGENT**, which is the entire difference
        between this method and `list_kb` (D-519): an object no agent references is exactly
        the residue every failure in this feature leaves, and an adapter that answered from
        the agent would make the orphan report structurally incapable of finding one.

        `complete=True` is a FACT here rather than the optimistic default the type refuses:
        it is one query over one table with no page to miss. §9.2 of the contract inventory
        warns that this is where `ListingIncompleteReason` becomes vacuous vocabulary — it
        is right, and the honest response is to say so rather than to invent a reason. What
        is NOT vacuous is the listing itself: the objects it reports were written by the
        attach path and are compared against `kb_sources` by `kb/orphans.py`, so the
        cross-check is still between two writers.
        """
        require_capability("knowledge_base", engine=self)
        return AccountKBListing(objects=list(await self._store.account_kb()), complete=True)

    async def list_voices(self) -> EngineVoiceListing:
        """The voices this deployment's speech vendors are attested to speak.

        See `SqlControlPlane.voices` for where they come from and why that source is the
        only honest one available. `complete=True` because it is one query over one table;
        what it is complete ABOUT is an operator's attestations, which the note above says
        in the one place a reader will look.
        """
        require_capability("tts", engine=self)
        return EngineVoiceListing(voices=list(await self._store.voices()), complete=True)

    async def set_llm_credential(
        self, secret: str, *, provider: LlmProvider
    ) -> LlmCredentialPlacement:
        """Refuses — and **THE EXISTING GATE WOULD HAVE GIVEN THE WRONG ANSWER** (§9.1).

        Every other adapter refuses this through `require_capability("llm")`, because the
        method is only meaningful where the LLM leg is ours. Here the leg IS ours —
        `capabilities.is_ours("llm")` is True — so that gate PASSES, and an adapter that
        leaned on it would have installed nothing and reported success. The refusal needs a
        different ground and this is it: the method's purpose is *"pushing OUR key into THE
        ENGINE'S credential store"*, and there is no store this process can push to. So
        there is nothing here to replace and nothing to supersede — which is also why
        `LlmCredentialPlacement`'s two fields have no referent on this engine.

        ⚠ **THE REFUSAL SURVIVES D-614 AND ITS REMEDIATION DID NOT** (re-argued 15 Sep
        2026, which is what that decision asked of this method). The ground above used to
        read *"the worker reads its keys from our secrets manager at process start"*, and
        the remediation told an operator "rotate the model key in the ops console; the
        runtime picks it up when it restarts". **Both halves were wrong, and the second was
        wrong in the expensive direction**: `voice_worker/boot.py` reads every key from its
        own PROCESS ENVIRONMENT, injected by the Pipecat Cloud secret set, and it cannot do
        otherwise — `PLATFORM_KEK` must never be in that image (DEPLOYMENT §12.2), so that
        container can never open `platform_secrets` however many times it restarts. An
        operator who rotated a model key on the screen and restarted the worker would have
        been told the job was done while every call kept authenticating on the old key.

        The refusal ITSELF is unchanged and is still correct — this adapter has no
        credential store to install into — so what changes is the sentence an operator
        acts on, which is the half of an error that is part of the interface.

        Raising rather than no-opping, because the Protocol says every caller's response to
        "the credential did not land" is the same, and because a rotation script that
        reported success forever against an engine with no credential store is silent by
        construction — the identical failure `CartesiaEngine.set_llm_credential` refuses.
        """
        raise ProblemError(
            kind="dependency",
            code=CARRIER_UNVERIFIED_CODE,
            title="This voice platform holds no LLM credential of ours",
            detail=(
                "The voice platform in this deployment runs inside our own software and "
                "reads its model keys from the secrets manager, so there is no separate "
                "credential store to install one into."
            ),
            remediation=(
                "Rotate the model key in TWO places, because the voice runtime cannot read "
                "the ops console: install it in the console for the rest of the platform, "
                "then set the same value in the voice worker's secret set and redeploy "
                "that container. Nothing is pushed to a voice platform's credential store "
                "— there is none."
            ),
        )

    # --- C: reconciled reads (§3 category C) ---------------------------------

    async def get_agent(self, ref: EngineAgentRef) -> AgentSnapshot:
        """**WHAT THE WORKER LAST ATTESTED — never what the control plane intends** (§1.1).

        This is the method the third `AgentHosting` member exists for. Under a rented
        engine the vendor is an independent witness; delete the vendor and an adapter
        answering from its own tables satisfies every clause and measures nothing. So the
        witness moves rather than the contract: a running worker recomputes the prompt
        digest from the string in its own memory, writes it to `agent_config_attestations`,
        and THAT is what this reports.

        THE THREE ANSWERS, AND WHY THEY ARE THREE RATHER THAN TWO:

        1. **No worker has ever attested.** A real answer, not a failure: an agent that has
           been published and never dialled has no witness yet. The compliance fields read
           back `None` with `_readable=False`, which is precisely the tri-state's meaning
           ("the adapter could not FIND it"), and `verification.judge` scores the publish
           `unreadable` rather than applied. That is the correct direction to fail in.
        2. **A worker attested and its own digest disagrees with the version it names.**
           Everything we know is that it is running something else; there is nothing here
           that describes it, so the same `_readable=False` applies and the mismatch is
           logged. `Attestation.matches` is the verdict and it is a FINDING, not an error —
           nothing raises on it, because the row is evidence either way.
        3. **A worker attested and the digests agree.** Then the bytes in that process are
           the bytes on the version row, by content addressing rather than by assumption,
           and this reports them: the composed prompt, the greeting, and the `ModelConfig`
           that version was minted from.

        **WHAT IS READ FROM THE ENGINE RECORD INSTEAD OF THE ATTESTATION, AND WHY THAT IS
        NOT A CHEAT.** `name` and `knowledge_base_refs` come from `pipecat_agents` /
        `pipecat_kb_objects`. Neither is covered by a digest, and §9.2 is right that a
        read-back of state nothing else writes is self-agreement — so they are reported for
        what they are: the state the NEXT session will load. `knowledge_base_refs_readable`
        is True because we genuinely can locate the field, which is the tri-state's
        question; what it does not claim is that a running process has confirmed it. The
        compliance-bearing fields are the ones the witness gates, and they are gated.

        `handoff_destinations_readable` follows `capabilities.in_call_handoff`, which is
        False here, so the empty tuple is a declared "cannot tell" rather than a claim that
        nobody is on duty — `FakeEngine` makes the identical call from the identical field.
        """
        self._assert_this_engine_hosts_agents()
        held = await self._held(ref)
        attested = await self._store.attested(held)
        # A LOCAL NAME RATHER THAN `attested is not None and attested.matches` REPEATED:
        # every field below is gated on it, and the narrowing has to reach them all.
        # `composed_prompt` is checked as well as `matches`, and it is not defensive
        # padding: a version minted before migration `e2f5a91c8d47` added the content
        # columns carries the empty default and cannot be backfilled (the bytes it digests
        # were never stored, and the table is append-only). Such a row can still MATCH — the
        # digest is the real one — so without this the read-back would report an empty
        # prompt as the thing the worker is holding, which is the one lie this method
        # exists to prevent.
        witness = (
            attested
            if attested is not None and attested.matches and attested.composed_prompt
            else None
        )
        if attested is not None and witness is None:
            # WARNING rather than `alert()`: the component that decides whether one stale
            # worker is a page is the drift sweep, which can see how many there are. The
            # same reasoning `record_attestation` states at its own mismatch.
            log.warning(
                "pipecat_attestation_mismatch_on_read_back",
                extra={
                    "agent_id": str(held.agent_id),
                    "config_version_id": str(attested.agent_config_version_id),
                },
            )
        return AgentSnapshot(
            engine_agent_ref=ref,
            name=held.name,
            system_prompt=witness.composed_prompt if witness else None,
            system_prompt_readable=witness is not None,
            # NOTHING TO PUT HERE, AND THAT IS THE HONEST EMPTY. `alternate_prompts` is
            # Bolna's per-language task list; a Pipecat pipeline has one system prompt and
            # there is no second string for `every_prompt_carries` to score.
            alternate_prompts=(),
            greeting=witness.opening_line if witness else None,
            greeting_readable=witness is not None,
            knowledge_base_refs=list(await self._store.agent_kb(held)),
            knowledge_base_refs_readable=True,
            models=witness.models if witness else None,
            models_readable=witness is not None,
            handoff_destinations=(),
            handoff_destinations_readable=self.capabilities.in_call_handoff,
            engine=self.name,
        )

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        """One session the runtime recorded, or a refusal — never a fabricated snapshot.

        *"Reading an execution the engine never placed is reported"*: a fabricated
        `status="failed"` snapshot is the worst available answer, because it is
        indistinguishable from a real failed call and the poller would record a repair for
        a phantom.

        ⚠ **THIS SAID "TODAY THERE ARE NONE, SO THIS RAISES" AND THAT IS NO LONGER TRUE
        (D-607).** `SqlControlPlane.execution` reads the call and its turns back out of the
        rows `apps/voice-worker` wrote, which is what lets a settled call reach the post-call
        pipeline at all. The refusal below is now the answer for a call this engine really
        has no record of, rather than for every call.

        §1.2 SPLITS THE GUARANTEE AND THIS IS THE "CONTENT" HALF: the transcript, the turns
        and the outcome are ours because nobody else ever had them. The FACTS half — did it
        connect, how long, what did it cost — belongs to the carrier's CDR, which is not
        retrievable from here (see the module docstring), and `billable_ready` is therefore
        the field to watch: it may never be honestly True on this engine until a CDR can be
        read, because *"the billable quantity is now witnessed by the party that charges for
        it"* and nothing else may stand in for that.
        """
        found = await self._store.execution(call_id)
        if found is None:
            raise ProblemError(
                kind="dependency",
                code="engine_rejected",
                title="There is no record of that call",
                detail="The voice platform holds no record of that call.",
                failure_stage="CORE_LOGIC",
            )
        return found

    async def list_executions(self, *, since: datetime) -> ExecutionListing:
        """Our store, reconciled against the carrier's CDR — and the reconciliation is the
        guarantee (§1.2).

        **COMPLETENESS HERE IS NOT ABOUT PAGING.** Over our own store a listing is one query
        and there is no page to miss, which §9.2 correctly calls out as making the whole
        `ListingIncompleteReason` vocabulary vacuous. What is NOT vacuous is the other half
        of §1.2: a session we hold and cannot match to a CDR is an unwitnessed billable
        fact, and the poller is entitled to hear about it. So a window carrying sessions is
        reported INCOMPLETE with `carrier_cdr_unavailable` — the member that lands with the
        adapter that emits it, exactly as `ListingIncompleteReason`'s own note requires —
        and an empty window is complete, because there is nothing whose CDR we needed.

        `since` is anchored on when the session STARTED, never on when it finished (D-367).
        The anchor is a free choice here rather than a vendor artifact, and it is kept
        because `pipeline.reconcile_outstanding_calls` is written against it: a window of
        width W under the other reading drops every call longer than W.
        """
        rows = await self._store.executions(since=since)
        if not rows:
            return ExecutionListing(snapshots=[], complete=True)
        return ExecutionListing(
            snapshots=list(rows),
            complete=False,
            incomplete_reason="carrier_cdr_unavailable",
        )

    # --- D: webhook intake (§3 category D) -----------------------------------

    def verify_webhook(
        self, headers: dict[str, str], body: bytes, source_ip: str
    ) -> WebhookVerdict:
        """`none`, because **NOTHING EXTERNAL CALLS US** (`PIPECAT-MIGRATION.md` §3D).

        There is no counterpart to this method on this engine: the worker is inside our own
        trust boundary, authenticates as itself, and writes to the database directly. So
        there is no signature to check and no egress range to allowlist, and `method="none"`
        with a reason is what stops a caller mistaking the answer for evidence.

        ⚠ **WHAT `none` COST, AND WHERE IT WAS PAID — D-615, CLOSED.** The receiver's
        `none` branch (`apps/voice-runtime/engine_intake.verify_source`) opened the route
        when the delivery's engine IS this deployment's engine — right for the fake engine,
        whose whole purpose is running the pipeline offline, and a public unauthenticated
        write endpoint on a deployment running `ENGINE=pipecat`. It was fixed exactly where
        this note said it belonged: in the receiver's admission rule and with a decision-log
        row, not by changing this declaration (`hmac` here would fail closed and would also
        be a claim that this engine signs its webhooks, which is false). The receiver now
        requires `APP_ENV=local` as well, because what `fake` earned its open door with is
        being a DEV INSTRUMENT (DEV-SETUP §3) and not the word `none`; `pipecat` declares
        the same word for the opposite reason — nothing external calls it — and a deliverer
        that does not exist loses nothing by being refused.
        """
        method: WebhookAuthMethod = self.capabilities.webhook_auth
        return WebhookVerdict(
            ok=True,
            method=method,
            reason="the runtime writes directly; nothing external calls this engine",
        )

    def parse_webhook(self, payload: dict[str, Any]) -> CallEvent:
        """Normalize a delivery — which on this engine is OUR OWN vocabulary already.

        The isolation boundary this method exists to be has nothing to separate: there is
        no vendor payload, so the status map is the IDENTITY and an unrecognised status
        still falls closed to `failed` rather than being passed through. It is implemented
        rather than refused because the Protocol is not optional and because the shape it
        parses is the worker's own event, which is the only thing that could ever arrive.

        **NEVER SETS `tenant_id`/`agent_id`.** A guessed tenant is a cross-tenant write
        (hard rule 1), and the resolution belongs to the receiver that knows the ref.
        """
        # AN ABSENT STATUS IS NOT A COMPLETED CALL, and this line defaulted to
        # `"completed"`. `_normalized_status` fails closed on a status it does not
        # RECOGNISE, and the default one field away failed OPEN on a status that was never
        # SENT — so the adapter that refuses `"some-new-status-2027"` settled a payload
        # carrying no status at all as a success. `status` is what decides whether a call
        # is settled, metered and extracted, so that is the one wrong answer with a cost.
        #
        # `or ""` is the shape `bolna.py::_snapshot` and `cartesia.py` already use (both
        # map the empty string through their table and land on `failed`), so this is the
        # existing answer applied rather than a second one invented. The empty `raw_status`
        # that results is honest: the sender said nothing, and the forensic row records
        # that rather than a word we supplied on its behalf.
        status = str(payload.get("status") or "")
        return CallEvent(
            call_id=str(payload.get("id") or payload.get("execution_id") or ""),
            engine_agent_ref=str(payload["agent_id"]) if payload.get("agent_id") else None,
            direction="inbound" if payload.get("direction") == "inbound" else "outbound",
            status=_normalized_status(status),
            raw_status=status,
            from_e164=payload.get("from_number"),
            to_e164=payload.get("to_number"),
            recording_url=payload.get("recording_url"),
            engine=self.name,
        )

    # --- A: the carrier (§3 category A) --------------------------------------
    #
    # Every method below refuses. Two different grounds, and they are not interchangeable:
    # the numbers group is a PRODUCT decision that will never flip (D-596), and the call
    # group is UNREAD EVIDENCE that flips the day `pre-build-blockers` §10 is answered.
    # Recording them as one would tell the next reader that buying a number is one research
    # pass away, which is the opposite of what the founder decided.

    async def start_outbound_call(
        self, ref: EngineAgentRef, to: E164, ctx: CallContext
    ) -> CallHandle:
        """Refuses: the dial is a carrier call and the carrier's API is UNREAD.

        THE COMPLIANCE FLOOR IS ASKED FIRST ANYWAY, and not as decoration. On `owned_runtime`
        `require_call_compliance_floor` is a no-op — the prompt is agent-record state the
        worker loads and attests, so `ctx.system_prompt` is None by design — but calling it
        is what keeps the floor on the DIAL path of every adapter rather than on the ones
        that happen to need it, and it is the expression this adapter would put on the wire.

        THE CALLER ID IS ASKED SECOND, AND THE ORDER IS THE POINT (D-420). A context
        carrying `from_e164` must be refused by a name a console can act on
        (`caller_id`), not by the generic "this half is not built" — those send an operator
        to two different places, and only one of them is about the number they just
        configured.
        """
        require_call_compliance_floor(engine=self, prompt_on_the_wire=ctx.system_prompt)
        if ctx.from_e164:
            require_capability("caller_id", engine=self)
        raise _carrier_not_written(
            "This voice platform cannot place outbound calls yet: its telephony leg is not built."
        )

    async def end_call(self, call_id: str) -> RecallOutcome:
        """Refuses: stopping a live call is a carrier operation.

        **AND THE REFUSAL IS WORTH MORE THAN A `RecallOutcome.UNKNOWN` WOULD BE.** §9.2
        observes that a pipeline we own can finally tell `PREVENTED` from `ALREADY_RUNNING`,
        so `UNKNOWN` should never be returned on this engine. Returning it today would be
        an unearned claim of a different kind — that we stopped something — on a path whose
        one observable failure is reporting success for a call it did not stop. The DNC
        recall reads this verdict to decide whether a number may be RECORDED as not called,
        which is the one place somebody may later have to prove a negative.
        """
        raise _carrier_not_written(
            "This voice platform cannot stop a call in progress yet: its telephony leg is "
            "not built."
        )

    async def transfer(self, call_id: str, to: E164, warm: bool) -> None:
        """Refuses by name, from the descriptor. Two independent reasons, both standing:
        `transfer` has NO caller anywhere in the tree, and an out-of-band transfer is a
        carrier operation whose API is unread. §9.1 expects this to become *"the first
        honest True this field has ever carried"* once the carrier leg exists; it is not
        true yet and a capability nobody can exercise must not be claimed."""
        require_capability("transfer", engine=self)
        raise AssertionError("unreachable while `transfer` is False")  # pragma: no cover

    async def search_numbers(self, query: NumberSearch) -> Sequence[AvailableNumber]:
        """Refuses by name: **we do not buy numbers through an API** (D-596).

        Not a gap and not an unread endpoint. Where a number is ours to supply it is a 140
        or 1600 series number obtained by APPLICATION through the carrier and the
        regulatory process (founder, 13 Sep 2026). The refusal is `require_capability`
        rather than an empty list for `CartesiaEngine.search_numbers`' reason: an empty
        result reads as "no inventory today" and puts an operator on a screen that looks
        like it works and never will.
        """
        require_capability("numbers", engine=self)
        raise AssertionError("unreachable while `number_series` is empty")  # pragma: no cover

    async def provision_number(self, spec: NumberSpec) -> ProvisionedNumber:
        """Refuses every series, by name — see `search_numbers` (D-596)."""
        require_capability("numbers", engine=self)
        raise AssertionError("unreachable while `number_series` is empty")  # pragma: no cover

    async def release_number(self, number: ProvisionedNumber) -> None:
        """Refuses by name. Nothing here was ever bought, and a 140/1600-series number is
        never retired (D-596) — so there is no other end of a recurring cost to close.

        NOT "absent is success": answering a release with silence would let an offboarding
        record a rental as stopped that nobody ever started or will stop charging.
        """
        require_capability("numbers", engine=self)
        raise AssertionError("unreachable while `number_series` is empty")  # pragma: no cover

    async def list_engine_numbers(self) -> Sequence[ProvisionedNumber]:
        """Refuses: the numbers ARE ours, and listing them is a carrier read we cannot make.

        **THIS ONE IS NOT D-596 AND MUST NOT BE FILED UNDER IT.** We hold numbers; what is
        missing is the endpoint that enumerates them, which `pre-build-blockers` §10 asks
        for (question 7) and nothing in this container can reach. An empty list would be a
        claim that we checked — the answer `workers/number_rental.reconcile_engine_numbers`
        turns into "our database has forgotten nothing", which is the one thing it exists
        to be able to doubt.
        """
        raise _carrier_not_written(
            "This voice platform cannot list the numbers it holds yet: its telephony leg "
            "is not built."
        )

    async def bind_inbound_number(self, ref: EngineAgentRef, number: ProvisionedNumber) -> None:
        """Refuses by name (`inbound_binding`): pointing a number at an agent is a carrier
        write, and the route is unread (`pre-build-blockers` §10, question 8).

        Refusing rather than writing our own row: `phone_numbers.agent_id` is already the
        authority on which agent owns a number, and a bind that only reached our database
        is the exact half-done state D-420 exists to close — the console says saved and the
        number goes on answering however the carrier was last configured.
        """
        require_capability("inbound_binding", engine=self)

    async def unbind_inbound_number(self, number: ProvisionedNumber) -> None:
        """Refuses by name, for `bind_inbound_number`'s reason — and refuses rather than
        no-opping even though "nothing of ours answers this number" may be true: telling an
        offboarding that a release step completed on a platform that never took it is how a
        stranger ends up reaching an AI that collects their details."""
        require_capability("inbound_binding", engine=self)


#: Raw status -> ours. The IDENTITY, because this engine IS its own vendor and stores our
#: own enum — the same shape `FakeEngine._STATUS_MAP` takes, and DERIVED from the Literal
#: rather than retyped so a member added to `CallStatus` cannot be silently normalized to
#: `failed` the day it is invented.
_STATUS_VALUES: Final[frozenset[str]] = frozenset(CallStatus.__args__)  # type: ignore[attr-defined]


def _normalized_status(raw: str) -> CallStatus:
    """Ours if we know it, `failed` if we do not — fail closed on the unknown."""
    if raw in _STATUS_VALUES:
        return raw  # type: ignore[return-value]
    return "failed"


__all__ = [
    "PIPECAT_CAPABILITIES",
    "PipecatControlPlane",
    "PipecatEngine",
    "RuntimeAgent",
    "SqlControlPlane",
    "engine_agent_ref_for",
]
