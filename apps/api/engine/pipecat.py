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

THE CARRIER LEG GOES THROUGH `engine/carrier.py` (D-662). `Settings.carrier` chooses the
carrier; every carrier method below delegates to that seam and never names a vendor. On
Vobiz the dial, the hang-up and the inbound binding are real requests read from Vobiz's
own documentation (`apps/api/engine/vobiz.py`). On Plivo every one of them still refuses
by name, because Plivo's REST surface is egress-blocked and unread
(`apps/api/engine/plivo_carrier.py`). The capability descriptor follows the carrier, so a
screen asking before it calls gets the same answer the call gives.

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
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final, Protocol, cast
from uuid import UUID

from calevate_shared.carrier import CarrierName, answer_path, events_path
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
    CallLatency,
    CostBreakdown,
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
    TurnLatency,
    WebhookAuthMethod,
    WebhookVerdict,
    owned_runtime_agent_ref,
    pipecat_call_ref,
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
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.db.session import joined_tenant_session, tenant_session, untenanted_session
from apps.api.engine.capabilities import (
    require_call_compliance_floor,
    require_capability,
    require_speech_leg,
)
from apps.api.engine.carrier import (
    CARRIER_UNVERIFIED_CODE,
    CarrierClient,
    capability_unverified,
    get_carrier,
)

log = get_logger(__name__)


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
#: **THE CARRIER HALF FOLLOWS THE CARRIER** (`capabilities_for_carrier`). This constant is
#: the Plivo profile: `caller_id` and `inbound_binding` are False because Plivo's REST
#: surface is unread, so presenting a number we name and routing a number to an agent are
#: operations nobody can write yet. On Vobiz both are True, because both requests are read
#: from Vobiz's own documentation (`engine/vobiz.py`).
#:
#: `transfer` stays False on every carrier: `VoiceEngine.transfer` has no caller in the
#: tree, and a live caller is handed to a person through `agents/transfer_providers`
#: instead. `in_call_handoff` stays False for the same reason — it describes an engine that
#: runs the handover itself from a destination fixed at publish, which this one does not.
#:
#: ⚠ `in_call_handoff=False` NO LONGER MAKES AN AGENT UNPUBLISHABLE, AND THE ADAPTER'S
#: REFUSAL IS UNCHANGED. `_assert_speech_is_ours` still refuses a config carrying a
#: `handoff` by name — an adapter must refuse what it cannot honour, and dropping a
#: destination here would be the silence D-533 wrote that refusal against. What changed is
#: one step earlier: `agents/handoff.spec_for` asks
#: `agents/transfer_providers.transfer_blocked_reason` first and sends NO destination to an
#: engine that can transfer by neither mechanism. So the agent publishes, the client is
#: told on their own handover screen that the platform cannot put a caller through yet, and
#: the in-call tool degrades truthfully (`agents/handoff_execution`). Refusing the whole
#: publish took a working receptionist off the phone to prevent a promise nothing was
#: making: the roster is not the agent, and the caller-facing promise is refused by the
#: tool rather than by the publish.
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

#: The Vobiz profile: a dial presents the caller id we name, and a number can be pointed at
#: an agent's Application (`engine/vobiz.py`). Everything else is the base profile.
PIPECAT_VOBIZ_CAPABILITIES = PIPECAT_CAPABILITIES.model_copy(
    update={"caller_id": True, "inbound_binding": True}
)


def capabilities_for_carrier(carrier: CarrierName) -> EngineCapabilities:
    """What this engine can do on `carrier`. One branch, here, for the whole adapter."""
    if carrier == "vobiz":
        return PIPECAT_VOBIZ_CAPABILITIES
    return PIPECAT_CAPABILITIES


#: A dial refused because a fact the request needs is missing (our call id, the public
#: callback address, the published agent). Raised before any request leaves the process.
CARRIER_DIAL_PRECONDITION_FAILED: Final = "carrier_dial_precondition_failed"

#: Seconds added to the agent's own cap for the carrier's `time_limit`, so the carrier's
#: ceiling is a backstop behind the worker's and never the first thing to end a call.
CARRIER_TIME_LIMIT_MARGIN_S: Final = 60
#: Vobiz's own default `time_limit` (`vobiz-findings/mirror/pages/call/make-call.md:71`). No
#: dial asks for more than the carrier would grant unasked.
CARRIER_TIME_LIMIT_CEILING_S: Final = 14_400


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
    #: When `agent_config_version_id` became the version a new session loads. An
    #: attestation of ANOTHER version observed before this instant was made by a session
    #: that started before the publish, so it says nothing about the current version.
    published_at: datetime
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

    async def record_dial(
        self, ref: EngineAgentRef, *, call_id: str, carrier_call_id: str, from_e164: str
    ) -> None:
        """The carrier accepted a dial for our intent row `call_id`: keep its id for the
        call and the caller id it was asked to present."""
        ...

    async def carrier_call_of(self, call_ref: str) -> str | None:
        """The carrier's id for the call this engine handle names, or None."""
        ...

    async def record_number_binding(
        self, ref: EngineAgentRef, *, e164: str, binding_id: str
    ) -> None:
        """The carrier attached this number to `binding_id` (Vobiz: an Application)."""
        ...

    async def number_binding(self, ref: EngineAgentRef, *, e164: str) -> str | None:
        """The binding this number was last attached to, or None."""
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
                        "       resolved_config, updated_at "
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
            published_at=row[5],
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

        * `cost` — on a COMPLETED call, a `CostBreakdown` marked `legs_metered_at_settlement`
          whose `total_inr` is the sum of the leg rows the worker's settlement already wrote
          (our supplier cost, from attested rates). The metering stage then writes the
          billable-minute row and charges the client through `charge_for_call` exactly as for
          every other engine, and writes no leg twice. `None` on any other status, as the fake
          adapter does: a call that did not complete is not charged.
        * `latency` — the `call_engine_latency` row the worker's settlement wrote
          (`voice_worker/latency.py` measures it), or `None` when there is none: a call on
          which no caller turn was answered. Never an empty `CallLatency()`, which would
          read as "the engine reported an object we could parse nothing out of" — a
          different and false claim (`ExecutionSnapshot.latency`).
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
            settled_cost = (
                await session.execute(
                    text(
                        "SELECT COALESCE(SUM(qty * unit_cost_paid), 0) FROM usage_events "
                        "WHERE call_id = :cid AND tenant_id = :tid "
                        "AND unit_cost_paid IS NOT NULL"
                    ),
                    {"cid": row[0], "tid": tenant_id},
                )
            ).scalar_one()
            timing = (
                await session.execute(
                    text(
                        "SELECT region, time_to_first_audio_ms, turns, parse_warnings "
                        "FROM call_engine_latency WHERE call_id = :cid AND tenant_id = :tid"
                    ),
                    {"cid": row[0], "tid": tenant_id},
                )
            ).first()
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
            latency=_stored_latency(timing),
            cost=(
                CostBreakdown(
                    total_inr=Decimal(str(settled_cost)),
                    # Our own ledger, in rupees: no vendor currency was converted or assumed.
                    source_currency="INR",
                    currency_stated=True,
                    legs_metered_at_settlement=True,
                )
                if status == "completed"
                else None
            ),
            engine=PipecatEngine.name,
        )

    async def record_dial(
        self, ref: EngineAgentRef, *, call_id: str, carrier_call_id: str, from_e164: str
    ) -> None:
        """Stamp the carrier's id and our presented caller id onto the intent row.

        Its OWN transaction, not the caller's: `dispatch_call` commits the intent row before
        the dial for the same reason — the carrier has accepted a call that may be ringing,
        and a caller's rollback must not take the only handle on it with it. The row is
        addressed by our id, never by a number, and `from_e164` keeps a value already there.
        """
        tenant_id = _tenant_of(ref)
        if tenant_id is None:
            return
        async with tenant_session(tenant_id) as session:
            result = await session.execute(
                text(
                    "UPDATE calls SET carrier_call_id = :cc, "
                    "from_e164 = COALESCE(from_e164, :from_e), updated_at = now() "
                    "WHERE id = :id AND tenant_id = :tid"
                ),
                {"cc": carrier_call_id, "from_e": from_e164, "id": call_id, "tid": tenant_id},
            )
        if rowcount_of(result) == 0:
            log.warning(
                "carrier_call_id_not_stamped",
                extra={"call_id": call_id, "tenant_id": str(tenant_id)},
            )

    async def carrier_call_of(self, call_ref: str) -> str | None:
        tenant_id = tenant_of_pipecat_ref(call_ref)
        if tenant_id is None:
            return None
        async with joined_tenant_session(tenant_id) as session:
            value = (
                await session.execute(
                    text(
                        "SELECT carrier_call_id FROM calls "
                        "WHERE engine_call_id = :ref AND tenant_id = :tid"
                    ),
                    {"ref": call_ref, "tid": tenant_id},
                )
            ).scalar_one_or_none()
        return str(value) if value else None

    async def record_number_binding(
        self, ref: EngineAgentRef, *, e164: str, binding_id: str
    ) -> None:
        """Joined, because the number's row may be held `FOR UPDATE` by the caller
        (`agents/service.attach_number_to_agent`), and a second connection would wait on it."""
        tenant_id = _tenant_of(ref)
        if tenant_id is None:
            return
        async with joined_tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE phone_numbers SET carrier_binding_id = :bid, updated_at = now() "
                    "WHERE e164 = :e164 AND tenant_id = :tid"
                ),
                {"bid": binding_id, "e164": e164, "tid": tenant_id},
            )

    async def number_binding(self, ref: EngineAgentRef, *, e164: str) -> str | None:
        tenant_id = _tenant_of(ref)
        if tenant_id is None:
            return None
        async with joined_tenant_session(tenant_id) as session:
            value = (
                await session.execute(
                    text(
                        "SELECT carrier_binding_id FROM phone_numbers "
                        "WHERE e164 = :e164 AND tenant_id = :tid"
                    ),
                    {"e164": e164, "tid": tenant_id},
                )
            ).scalar_one_or_none()
        return str(value) if value else None

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
        own that is independent of `calls`.

        ⚠ **THIS USED TO CONTINUE "or, more likely, until §1.2's other half lands and the
        reconciliation reads the CARRIER's CDR, which is a genuinely independent authority
        and is the one this engine is entitled to". THE CDR IS STILL THE RIGHT AUTHORITY AND
        WE ARE NOT ENTITLED TO IT** (verified 19 Sep 2026, on a founder audit asking for
        exactly that poller). It is not deferred work; it is work this product cannot do, and
        the difference matters because a plan may not wait for it:

        * **Model B (D-474, `docs/ROADMAP.md:716`)** — *"the client buys the connection on
          their own Exotel/Plivo/Vobiz account, passes that carrier's KYC, remains the
          subscriber of record and issues us revocable API credentials."* A CDR is a record
          inside THE CLIENT'S OWN carrier account, and reading it needs a key against that
          account.
        * **There is no per-tenant carrier-credential store in this tree.** The only carrier
          secrets that exist are `Settings.plivo_auth_id` / `plivo_auth_token` — ONE
          deployment-wide pair in the `calevate-pipecat-worker` secret set, whose stated
          purpose is hanging the leg up at `EndFrame` (`apps/api/core/settings.py:255-268`,
          `voice_worker/boot.py:132-144`). One pair cannot authenticate a lookup against N
          clients' accounts, and `campaigns/provisioning.PROVISIONING_IMPLEMENTED` is False
          because the capability is REFUSED rather than unbuilt — flipping it is adopting
          Model A, a legal decision and not a config change (`agents/handoff.py:17-21` states
          the same fact for the whisper).
        * **The API shape is UNKNOWN from here in any case.** `www.plivo.com/docs/` and
          `api.plivo.com` both answer `curl: (56) CONNECT tunnel failed, response 403` →
          HTTP 000, re-measured from this container 19 Sep 2026. Our pinned Pipecat contains
          exactly one Plivo REST endpoint (the hangup), so every other method, path and body
          would be invented — which hard rule 11 forbids more firmly than it forbids a gap.

        **THE RECONCILIATION THAT IS OURS IS A DIFFERENT ONE, AND IT IS WIRED.** Noticing
        that a call started and never settled needs no independent authority:
        `pipeline.reconcile_outstanding_calls` alarms `calls_never_finished` on a call left
        non-terminal, `dispatcher.report_stalled_pipeline` alarms `postcall_pipeline_stalled`
        on a terminal call whose pipeline never ran, and `admin/health.calls_unmetered` stops
        the account board for a completed call with no `usage_events` row. What none of them
        may do is INVENT the minutes — a call whose content we never received cannot be
        metered from nothing, and a fabricated quantity on an append-only ledger is worse
        than a call we failed to bill. Detect and alert are ours; the connected minute is the
        carrier's and always was.

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

    #: EMPTY, and the annotation is load-bearing on every adapter: without
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

    def __init__(
        self,
        *,
        store: PipecatControlPlane | None = None,
        carrier: CarrierClient | None = None,
    ) -> None:
        self._store: PipecatControlPlane = store if store is not None else SqlControlPlane()
        self._pinned_carrier = carrier
        self._capabilities_override: EngineCapabilities | None = None

    @property
    def _carrier(self) -> CarrierClient:
        """The injected carrier, else the one the live `Settings.carrier` names.

        Resolved per operation rather than at construction: `get_engine` caches one adapter
        per process, so a carrier captured here would keep dialling on the old carrier after
        an operator moved the switch, which `core/platform_config` promises takes effect on
        the next dial. Each operation binds the result to a local once, so its name, its
        refusal and its requests all belong to the same carrier.
        """
        return self._pinned_carrier if self._pinned_carrier is not None else get_carrier()

    @property
    def capabilities(self) -> EngineCapabilities:
        """The descriptor for the carrier in force now (`capabilities_for_carrier`)."""
        if self._capabilities_override is not None:
            return self._capabilities_override
        return capabilities_for_carrier(self._carrier.name)

    @capabilities.setter
    def capabilities(self, value: EngineCapabilities) -> None:
        # `VoiceEngine.capabilities` is a settable attribute; a set pins the descriptor.
        self._capabilities_override = value

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
        cannot honour. The handoff arm is a BACKSTOP rather than the ordinary path:
        `agents/handoff.spec_for` now sends no destination to an engine that can transfer
        by neither mechanism, so a `handoff` arriving here came from a config built some
        other way — and is refused by name rather than dropped (capability descriptor).
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
        raise capability_unverified(
            title="This voice platform holds no LLM credential of ours",
            detail=(
                "The voice platform in this deployment runs inside our own software and "
                "reads its model keys from its own container's secret set, so there is no "
                "separate credential store to install one into."
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

        1. **No worker has attested the current version yet.** A real answer, not a
           failure: an agent that has been published and never dialled has no witness yet.
           The compliance fields read back `None` with `_readable=False`, which is
           precisely the tri-state's meaning ("the adapter could not FIND it"), and
           `verification.judge` scores the publish `unreadable` rather than applied. That
           is the correct direction to fail in. An attestation of an OLDER version made
           before the current one was published is this case too: every session reads the
           published config afresh, so it says nothing about what the next one will load.
           Reporting its script instead scored every prompt-changing republish of a
           dialled agent `not_applied`, which `publish_agent` rolls back.
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
        if (
            attested is not None
            and attested.agent_config_version_id != held.agent_config_version_id
            and attested.observed_at <= held.published_at
        ):
            # A session that began before the current version was published. A session
            # that loaded another version AFTER it was published is kept: that worker is
            # running something other than what we published, which is the finding.
            attested = None
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
        # `or ""` is the shape `cartesia.py` already uses (it maps the empty string
        # through its table and lands on `failed`), so this is the
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
    # The call group and the binding group go through `engine/carrier.py`. The numbers
    # group refuses on every carrier: we do not buy numbers through an API (D-596), which
    # is a product decision rather than unread evidence.

    def _ready_carrier(self, operation: str) -> CarrierClient:
        """The carrier for this operation, or its refusal to perform `operation`."""
        carrier = self._carrier
        refusal = carrier.unavailable(operation)
        if refusal is not None:
            raise refusal
        return carrier

    async def start_outbound_call(
        self, ref: EngineAgentRef, to: E164, ctx: CallContext
    ) -> CallHandle:
        """Dial through the carrier, presenting the caller id the dispatch resolved.

        THE ORDER IS THE POINT. The compliance floor first (a no-op on `owned_runtime`,
        where the prompt is agent state the worker attests, and asked anyway so the floor
        stays on every adapter's dial path); then the caller id, so a context carrying one
        on a carrier that cannot present it is refused by `caller_id` (D-420); then whether
        the carrier can dial at all; then the facts this request needs. Every refusal up to
        the carrier request is raised before a byte leaves this process, so its code is in
        `agents.service.DIAL_NOT_PLACED_CODES`.

        The answer and status URLs carry OUR call id in the PATH, never the query: Vobiz
        signs the callback URL with its query stripped
        (`vobiz-findings/mirror/pages/concepts/validating-callbacks.md:35-52`).

        Returns `pipecat_call_ref(tenant, call_id)`, the handle the worker settles the call
        under, so `dispatch_call` stamps the same id the worker will write.
        """
        require_call_compliance_floor(engine=self, prompt_on_the_wire=ctx.system_prompt)
        if ctx.from_e164:
            require_capability("caller_id", engine=self)
        dialler = self._ready_carrier("place outbound calls")
        if not ctx.from_e164:
            # Vobiz dials only from a number the account rents: "Caller ID | Must use
            # Vobiz-rented Indian phone number" (`compliance/india/calling-regulations.md:35`).
            raise ProblemError(
                kind="dependency",
                code="engine_caller_id_not_configured",
                title="This agent has no number to call from",
                detail="An outbound call needs a registered number bound to the agent.",
                remediation=(
                    "Attach the client's registered number to this agent, then call again."
                ),
            )
        tenant_id = _tenant_of(ref)
        base_url = (get_settings().webhook_base_url or "").rstrip("/")
        if not ctx.call_id or tenant_id is None or not base_url:
            raise _dial_precondition_failed(
                missing="call id"
                if not ctx.call_id
                else "agent reference"
                if tenant_id is None
                else "public callback address"
            )
        agent = await self._store.runtime_agent(ref)
        if agent is None:
            raise _dial_precondition_failed(missing="published agent")

        carrier = dialler.name
        placed = await dialler.place_call(
            from_e164=ctx.from_e164,
            to_e164=to,
            answer_url=base_url + answer_path(carrier, ref, call_id=ctx.call_id),
            hangup_url=base_url + events_path(carrier, ref, call_id=ctx.call_id),
            ring_url=base_url + events_path(carrier, ref, call_id=ctx.call_id),
            time_limit_s=min(
                agent.config.max_call_duration_s + CARRIER_TIME_LIMIT_MARGIN_S,
                CARRIER_TIME_LIMIT_CEILING_S,
            ),
        )
        await self._store.record_dial(
            ref,
            call_id=ctx.call_id,
            carrier_call_id=placed.carrier_call_id,
            from_e164=ctx.from_e164,
        )
        log.info(
            "carrier_dial_accepted",
            extra={"call_id": ctx.call_id, "tenant_id": str(tenant_id), "carrier": carrier},
        )
        return pipecat_call_ref(tenant_id, ctx.call_id)

    async def end_call(self, call_id: str) -> RecallOutcome:
        """Hang the call up at the carrier.

        Always `UNKNOWN` when it does not raise. Vobiz's hang-up answers 204 whether the
        call was ringing or talking (`call/hangup-call.md:60`), so it never says the number
        was not rung — and `PREVENTED` is the one value a DNC recall may record that on. A
        call this engine holds no carrier id for is refused: a hang-up that reported success
        for a call it never reached is this method's one dangerous answer.
        """
        carrier = self._ready_carrier("stop a call in progress")
        carrier_call_id = await self._store.carrier_call_of(call_id)
        if carrier_call_id is None:
            raise ProblemError(
                kind="dependency",
                code="engine_rejected",
                title="There is no record of that call",
                detail="The voice platform holds no carrier record of that call.",
                failure_stage="CORE_LOGIC",
            )
        ended_now = await carrier.hang_up(carrier_call_id)
        log.info(
            "carrier_hang_up",
            extra={"carrier": carrier.name, "ended_now": ended_now},
        )
        return RecallOutcome.UNKNOWN

    async def transfer(self, call_id: str, to: E164, warm: bool) -> None:
        """Refuses by name, from the descriptor. `transfer` has no caller in the tree, and a
        live caller is handed to a person through `agents/transfer_providers` instead."""
        require_capability("transfer", engine=self)
        raise AssertionError("unreachable while `transfer` is False")  # pragma: no cover

    async def search_numbers(self, query: NumberSearch) -> Sequence[AvailableNumber]:
        """Refuses by name: **we do not buy numbers through an API** (D-596).

        Where a number is ours to supply it is a 140 or 1600 series number obtained by
        APPLICATION through the carrier and the regulatory process (founder, 13 Sep 2026).
        An empty list would read as "no inventory today" and put an operator on a screen
        that looks like it works and never will.
        """
        require_capability("numbers", engine=self)
        raise AssertionError("unreachable while `number_series` is empty")  # pragma: no cover

    async def provision_number(self, spec: NumberSpec) -> ProvisionedNumber:
        """Refuses every series, by name — see `search_numbers` (D-596)."""
        require_capability("numbers", engine=self)
        raise AssertionError("unreachable while `number_series` is empty")  # pragma: no cover

    async def release_number(self, number: ProvisionedNumber) -> None:
        """Refuses by name. Nothing here was ever bought, so there is no rental to stop, and
        answering with silence would let an offboarding record one as stopped."""
        require_capability("numbers", engine=self)
        raise AssertionError("unreachable while `number_series` is empty")  # pragma: no cover

    async def list_engine_numbers(self) -> Sequence[ProvisionedNumber]:
        """Refuses: the numbers ARE ours, and listing them is a carrier read not written here.

        **NOT D-596.** We hold numbers; what is missing is the reader. An empty list would
        be a claim that we checked — the answer `workers/number_rental.
        reconcile_engine_numbers` turns into "our database has forgotten nothing".
        """
        self._ready_carrier("list the numbers it holds")
        raise capability_unverified(
            title="The voice platform cannot do that yet",
            detail="This voice platform cannot list the numbers it holds yet.",
            remediation=(
                "The carrier documents a number listing "
                "(vobiz-findings/mirror/pages/account-phone-number.md:42-44) and its reader "
                "is not written. Compare the carrier console's number list by hand meanwhile."
            ),
        )

    async def bind_inbound_number(self, ref: EngineAgentRef, number: ProvisionedNumber) -> None:
        """Point the number at this agent's answer route at the carrier.

        `engine_number_ref` is the operator's record that the number is on the carrier
        account; without it the bind is refused by name rather than attempted, because
        "the carrier has never heard of this number" is a person's job to fix. Routing
        stays in the URL path we mint (D-603), never in a lookup by dialled number.
        """
        require_capability("inbound_binding", engine=self)
        if not number.engine_number_ref:
            raise _number_not_linked()
        binder = self._ready_carrier("point a number at an agent")
        base_url = (get_settings().webhook_base_url or "").rstrip("/")
        held = await self._held(ref)
        if not base_url:
            raise _dial_precondition_failed(missing="public callback address")
        carrier = binder.name
        binding_id = await binder.bind_number(
            number.e164,
            answer_url=base_url + answer_path(carrier, ref),
            hangup_url=base_url + events_path(carrier, ref),
            label=str(held.agent_id),
            known_binding_id=await self._store.number_binding(ref, e164=number.e164),
        )
        await self._store.record_number_binding(ref, e164=number.e164, binding_id=binding_id)

    async def unbind_inbound_number(self, number: ProvisionedNumber) -> None:
        """Detach the number from whatever application it answers on.

        A number the carrier has no record of from us (`engine_number_ref` unset) is
        already answered by nothing of ours, so there is nothing to undo and this succeeds.
        """
        require_capability("inbound_binding", engine=self)
        if not number.engine_number_ref:
            return
        await self._ready_carrier("release a number's routing").unbind_number(number.e164)


def _dial_precondition_failed(*, missing: str) -> ProblemError:
    """A dial refused before any request left this process, naming what was missing."""
    log.warning("carrier_dial_precondition_failed", extra={"missing": missing})
    return ProblemError(
        kind="dependency",
        code=CARRIER_DIAL_PRECONDITION_FAILED,
        title="The call could not be started",
        detail=f"The voice platform could not start this call: the {missing} is missing.",
        remediation="Contact us — this is a configuration problem on our side, not yours.",
    )


def _number_not_linked() -> ProblemError:
    return ProblemError(
        kind="dependency",
        code="engine_number_not_linked",
        title="This number is not known to the voice platform",
        detail=(
            "The voice platform has no record of this phone number, so no agent can be set "
            "to answer it."
        ),
        remediation=(
            "Record the number's reference from the carrier console on the number first, "
            "then assign the agent again."
        ),
    )


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


def _stored_latency(row: Any) -> CallLatency | None:
    """`call_engine_latency` back into the normalized shape, or `None` when no row exists.

    jsonb arrives decoded: SQLAlchemy's asyncpg dialect installs a jsonb codec on every
    connection, `text()` reads included. The row's CHECK guarantees `turns` holds objects of
    numbers, and `TurnLatency` ignores a key it does not declare.
    """
    if row is None:
        return None
    region, ttfa, turns, warnings = row
    return CallLatency(
        region=region,
        time_to_first_audio_ms=float(ttfa) if ttfa is not None else None,
        turns=[TurnLatency.model_validate(turn) for turn in turns],
        parse_warnings=[str(warning) for warning in warnings or ()],
    )


__all__ = [
    "CARRIER_DIAL_PRECONDITION_FAILED",
    "CARRIER_TIME_LIMIT_CEILING_S",
    "CARRIER_TIME_LIMIT_MARGIN_S",
    "CARRIER_UNVERIFIED_CODE",
    "PIPECAT_CAPABILITIES",
    "PIPECAT_VOBIZ_CAPABILITIES",
    "PipecatControlPlane",
    "PipecatEngine",
    "RuntimeAgent",
    "SqlControlPlane",
    "engine_agent_ref_for",
]
