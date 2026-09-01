"""Conformance fixtures: every adapter runs the SAME suite.

The suite lives in `packages/shared` on purpose — it tests the CONTRACT, not an
implementation, so it belongs next to the Protocol rather than inside `apps/api`.
Bolna is exercised against a transport stub (`httpx.MockTransport`) fed payload
shapes captured from their docs; the fake engine runs as itself. Neither test touches
the network — `make conformance` must be runnable on a plane.

Adding an engine = adding one entry to `ENGINE_IDS` and a factory below. If the new
adapter cannot pass unchanged, the contract is wrong or the adapter is leaking.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.engine import bolna as bolna_module
from apps.api.engine import cartesia as cartesia_module
from apps.api.engine.bolna import BolnaEngine
from apps.api.engine.cartesia import CartesiaEngine
from apps.api.engine.fake import (
    DICTATED_SPEECH_CAPABILITIES,
    EXTERNAL_DEPLOYMENT_CAPABILITIES,
    FakeEngine,
)
from calevate_shared.engine import VoiceEngine

#: FOUR SUBJECTS, THREE OF THEM REAL ADAPTERS (D-93).
#:
#: `cartesia` is the second real vendor and the first that DISAGREES with us: it dictates
#: its own STT and TTS, signs its webhooks, and provisions no Indian number class. It is
#: what makes "the contract is vendor-neutral" a measurement rather than a hope — that
#: claim and "the contract is Bolna-shaped" are indistinguishable while only one vendor
#: exists. Its stub below is fed the same shapes the adapter documents, at the same
#: evidence standing, so the suite proves OUR mapping and our contract; it proves nothing
#: about Cartesia, and `apps/api/engine/cartesia.py` says so at every line.
#:
#: `fake-restricted` is retained as the FAST TEST DOUBLE for the same capability profile:
#: the `FakeEngine` class running an engine-dictates-speech, no-knowledge-base,
#: signed-webhook descriptor, with no transport stub to maintain. It drives those paths
#: in unit tests cheaply, and it keeps the `hmac` branch executable with a verifier that
#: actually verifies (the Cartesia adapter's fails closed, by design, because its scheme
#: is unsourced).
#: `fake-deployed` is the FIFTH subject and the only one that satisfies the ALTERNATIVE
#: half of hard rule 5 (D-280/D-282): an engine whose agents are deployed elsewhere, whose
#: `create_agent`/`get_agent` refuse by name, and which carries our prompt onto every call
#: through `CallContext.system_prompt`. `cartesia` is the same SHAPE and cannot do the
#: second half — its outbound body has no prompt field, so it refuses every dial — so
#: without this fixture the branch where an externally-deployed engine actually dials
#: would be contract nothing executes. Same argument as `fake-restricted`, about a bigger
#: difference: a capability profile needs no vendor account and no imagined vendor JSON.
ENGINE_IDS = ["fake", "fake-restricted", "fake-deployed", "bolna", "cartesia"]

# A completed execution in the shape the vendor's own OpenAPI document declares
# (`AgentExecution`, D-350): cent-denominated costs with the five-key per-leg breakdown,
# prefix-tagged transcript text, recording nested under `telephony_data`.
#
# `telephony_data.call_type` IS THE DIRECTION, and this fixture used to carry a top-level
# `"direction": "inbound"` instead (D-359). No such field exists on `AgentExecution`; it
# was invented here at the same time as the adapter's read of it, from the same guess, so
# the stub and the adapter agreed and this suite confirmed the agreement while every real
# inbound call would have normalized as outbound. The old key is deliberately NOT kept: a
# fixture that carries both cannot tell which one the adapter read.
BOLNA_COMPLETED: dict[str, Any] = {
    "id": "exec_abc123",
    "agent_id": "agent_xyz",
    "status": "completed",
    "created_at": "2026-08-10T09:15:00Z",
    # `updated_at`, NOT `ended_at` (D-361). The vendor's execution object carries exactly
    # two timestamps — `created_at` and `updated_at` — and `ended_at` is in neither the
    # pinned OAS nor `references/execution-payload.md`. This fixture used to carry the
    # invented spelling, which is the `direction` mistake in a second place: the adapter
    # reads `ended_at or updated_at`, the stub supplied `ended_at`, so the suite exercised
    # a branch no live payload can take and the branch that ALL of them take was never run.
    "updated_at": "2026-08-10T09:16:35Z",
    "conversation_duration": 95,
    "total_cost": 8.5,
    "cost_breakdown": {
        "platform": 5.0,
        "network": 1.5,
        "llm": 0.0,
        "synthesizer": 1.4,
        "transcriber": 0.6,
    },
    "telephony_data": {
        "call_type": "inbound",
        "from_number": "+919876543210",
        "to_number": "+911140000000",
        "recording_url": "https://s3.us-east-1.amazonaws.com/bolna/exec_abc123.wav",
    },
    "transcript": (
        "assistant: Namaskaram, idi Sunrise Clinic AI assistant. Ee call record avutundi.\n"
        "user: Naaku appointment kavali.\n"
        "assistant: Tappakunda, ee roju evening 6 gantalaku doctor available unnaru.\n"
        "user: Sare, naa peru Ravi."
    ),
    "extracted_data": {},
}


# A completed Line call in the shape Cartesia's OWN GENERATED CLIENT declares (D-270).
# Every key below is read at source in `cartesia-python/src/cartesia/types/agents/
# agent_call.py` and `.../agent_transcript.py`, so unlike the rest of this file's Cartesia
# fixtures it is not our inference reflected back at us — it is a machine translation of
# their OpenAPI spec. `docs/vendor/cartesia/calls-and-transcripts.md` carries the citation.
#
# What is ABSENT is as load-bearing as what is present, and each absence is a fact:
#   * no cost/currency of any kind — usage is an account-level daily credit meter, so the
#     adapter reports no cost and that is the answer rather than a deferral;
#   * no duration field — the adapter derives it from the two instants;
#   * no recording URL — audio is an authenticated download at `/agents/calls/{id}/audio`;
#   * no `direction` — there is nothing to read, so the adapter's default stands.
#
# `start_time` is minted RELATIVE TO NOW because the vendor offers no server-side time
# filter, so `list_executions` must apply `since` itself; a fixture frozen in the past
# would put every row outside every window and make the listing clauses pass vacuously.
def _cartesia_completed(call_id: str = "cart_call_1") -> dict[str, Any]:
    started = datetime.now(UTC) - timedelta(minutes=5)
    return {
        "id": call_id,
        "agent_id": "agent_xyz",
        "status": "completed",
        "start_time": started.isoformat().replace("+00:00", "Z"),
        "end_time": (started + timedelta(seconds=95)).isoformat().replace("+00:00", "Z"),
        "summary": "Caller asked for an appointment.",
        "telephony_params": {"from": "+919876543210", "to": "+911140000000"},
        "transcript": [
            {
                "role": "assistant",
                "text": "Namaskaram, idi Sunrise Clinic AI assistant.",
                "start_timestamp": 0.0,
                "end_timestamp": 3.2,
            },
            {
                "role": "user",
                "text": "Naaku appointment kavali.",
                "start_timestamp": 3.9,
                "end_timestamp": 5.4,
            },
            # A `system` row is a LOG entry, not speech — their own field documentation
            # says so. It is here because without it nothing proves the adapter refuses to
            # file instrumentation into a client's transcript as a caller utterance.
            {
                "role": "system",
                "start_timestamp": 5.5,
                "end_timestamp": 5.5,
                "log_event": {"event": "kb_lookup", "metadata": {}, "timestamp": 5.5},
            },
        ],
    }


# How many calls the FAKE engine is seeded with to saturate its listing. It is also that
# engine's configured page size, so one more call than this is a truncated window.
FULL_LISTING_PAGE = 10

#: How many executions the Bolna stub holds when the suite wants a TRUNCATED listing.
#: One more than the adapter can reach: it pages `_LISTING_PAGE_SIZE` rows at a time and
#: stops at `_LISTING_MAX_PAGES`, so this is the smallest store it provably cannot finish.
#: Derived from the adapter's own constants rather than typed, for `CARTESIA_FULL_PAGE`'s
#: reason — a hand-copied number stops saturating the moment either constant moves, and a
#: saturation fixture that no longer saturates fails nothing.
BOLNA_SATURATION_ROWS = bolna_module._LISTING_PAGE_SIZE * bolna_module._LISTING_MAX_PAGES + 1


def _bolna_handler(*, listing_rows: int = 1) -> Callable[[httpx.Request], httpx.Response]:
    """A stub of their API, built fresh per engine so each test gets clean vendor state.

    **THE AGENT STORE NOW CARRIES THE KNOWLEDGE REFERENCE, AND THIS DOCSTRING USED TO SAY
    IT DELIBERATELY DID NOT (D-459).** It read: "Nothing in Bolna's published
    documentation says the agent carries one or what it would be called ... inventing a
    `rag_id` field here would make the suite assert our own guess back at us." The mirror
    says where it lives — `tasks[].tools_config.llm_agent.llm_config.vector_store
    .provider_config.vector_ids` (`bolna-findings/mirror/pages/api-reference/agent/v2/
    get.md:806-817,1164-1195`) — so it is no longer a guess, and NOT modelling it would
    make every KB clause pass vacuously. The stub stores what a `PUT` sends and returns it
    on a `GET`, which is the whole mechanism `attach_kb`/`detach_kb`/`list_kb` rest on.

    THE `PUT` REPLACES THE WHOLE OBJECT, exactly as the vendor documents (*"replaces the
    entire agent configuration"*, `.../agent/v2/patch_update.md:9`). That is not a detail
    of the fixture: it is what makes `update_agent`'s read-then-write provable here — an
    adapter that stopped preserving the vector ids would wipe the agent's knowledge on the
    next republish, and this stub is where that is caught.

    The knowledge-base routes are STATEFUL on purpose. A stub that answered every
    `POST /knowledgebase` with the same `rag_id` and every `DELETE` with 200 would let
    an adapter that never detaches anything sail through the suite — the exact defect
    the KB clause exists to catch. So this keeps a store: creates mint distinct ids and a
    distinct `vector_id`, the listing reflects it, and deleting an id the store does not
    hold 404s, which is what their `rag_id`-addressed CRUD API does.

    IT ANSWERS THE FIRST READ WITH `processing`, ON PURPOSE. Their create response says
    *"Initially the status would be `processing`"* and carries no `vector_id`
    (`.../knowledgebase/create.md:105-127`), and an adapter that returned on the create
    would have uploaded a document nothing can retrieve from. Making the FIRST
    `GET /knowledgebase/{rag_id}` say `processing` is what forces the wait to exist.
    """
    #: The numbers this stub has been asked to dial, so each dial gets its own execution
    #: id. See the `POST /call` branch.
    placed: list[str] = []
    #: Every execution id this stub has minted or listed. The `GET /executions/{id}`
    #: branch answers 404 for anything else — see there.
    executions: set[str] = set()
    #: THE CALLER ID EACH DIAL ASKED FOR, so `GET /executions/{id}` can echo it back as
    #: `telephony_data.from_number` (D-420). Without this the suite could not tell an
    #: adapter that SENDS `from_phone_number` from one that drops it: `start_outbound_call`
    #: returns a handle and nothing else, which is the same blind spot the per-call prompt
    #: has. Echoing the value a vendor was given is what a real one does — the number the
    #: callee saw is a property of the execution.
    dialled_from: dict[str, str] = {}
    #: `phone_number_id → agent_id` — this stub's inbound routing table (D-420). Stateful
    #: for the reason the agent store is: a stub that answered every `POST /inbound/setup`
    #: with 200 would let an adapter that binds nothing pass the clause that checks it.
    inbound: dict[str, str] = {}
    # The AGENT store, and it is stateful for the same reason the KB routes are: a stub
    # that answered every `GET /v2/agent/{id}` with the body of the last write would let
    # an adapter that echoes what it was handed pass the read-back clause, which is the
    # one defect that clause exists to catch. So writes are filed under an id derived
    # from the agent's NAME — stable across a re-create (the ref-stability clause needs
    # that) and distinct per agent (the read-back clause needs that) — and the GET
    # returns the stored object in the `{"agent_id": ..., "data": {...}}` envelope their
    # OSS server's `GET /all` is documented to use.
    #
    # PRE-SEEDED with the agent `BOLNA_COMPLETED` names. The listing is now per agent and
    # is discovered through `GET /v2/agent/all` (D-353), so an account with no agents lists
    # nothing — which would make every listing clause pass vacuously on a stub that had not
    # been asked to create one first.
    agents: dict[str, dict[str, Any]] = {str(BOLNA_COMPLETED["agent_id"]): {}}
    # THE CREDENTIAL STORE (D-404), and it is stateful and REPLACE-IN-PLACE — keyed on
    # `provider_name` — because that is the semantics the adapter is built to VERIFY
    # rather than to assume. Their published spec documents `POST /providers` with a
    # status enum whose only member is `added`, so what a second write under one name does
    # is not written down. Modelling replacement here is what makes the conformance clause
    # assert the good case honestly; `tests/bolna_contract_test.py` drives the append case
    # against a stub that appends, which is the arm that must raise.
    #
    # Pre-seeded with an UNRELATED provider, because the store holds every vendor key the
    # account has: counting somebody else's `SARVAM` entry as a superseded copy of ours
    # would report append semantics on a store that replaced perfectly well.
    providers: dict[str, dict[str, str]] = {
        "SARVAM": {"provider_id": "prov_sarvam", "provider_name": "SARVAM"}
    }
    #: `rag_id -> row`, the account's knowledge bases. `reads` counts how many times each
    #: has been read back, so the first look can answer `processing` and the second
    #: `processed` — see the docstring.
    knowledge: dict[str, dict[str, Any]] = {}
    reads: dict[str, int] = {}

    def agent_id_for(body: dict[str, Any]) -> str:
        config = body.get("agent_config") or {}
        name = str(config.get("agent_name") or "")
        return "agent_" + hashlib.sha256(name.encode()).hexdigest()[:8]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/knowledgebase" and request.method == "POST":
            # MULTIPART, AND THE ASSERTIONS ARE THE POINT. The route takes a file or a
            # url and never JSON, so a stub that accepted anything would let the body that
            # shipped before D-354 — `{agent_id, name, text}` — pass again.
            assert request.headers["content-type"].startswith("multipart/form-data"), (
                "`POST /knowledgebase` is multipart/form-data, not JSON"
            )
            body = request.content
            assert b'name="file"' in body, "the upload must carry a `file` part"
            assert b'name="url"' not in body, "`file` or `url`, never both"
            assert b"%PDF" in body, "the file part must be the rendered document"
            assert b'name="language_support"' in body, (
                "`language_support` is fixed at upload and cannot be changed later"
            )
            rag_id = f"rag_{len(knowledge) + 1}"
            knowledge[rag_id] = {
                "rag_id": rag_id,
                "file_name": "calevate-kb.pdf",
                "vector_id": f"vec_{len(knowledge) + 1}",
                "status": "processing",
                "language_support": "multilingual",
            }
            reads[rag_id] = 0
            # NO `vector_id` ON THE CREATE RESPONSE, which is what their spec declares
            # (`create.md:105-127`) and what makes the follow-up GET load-bearing.
            return httpx.Response(
                200,
                json={
                    "rag_id": rag_id,
                    "file_name": "calevate-kb.pdf",
                    "source_type": "pdf",
                    "status": "processing",
                    "language_support": "multilingual",
                },
            )
        if path == "/knowledgebase/all" and request.method == "GET":
            # A BARE ARRAY: `KnowledgebaseList` is `type: array` of `Knowledgebase`
            # (`get_knowledgebases.md:47-51`), which the adapter reads through
            # `vendor_request`'s top-level-array wrapper.
            return httpx.Response(200, json=list(knowledge.values()))
        if path.startswith("/knowledgebase/") and request.method == "GET":
            rag_id = path.rsplit("/", 1)[-1]
            row = knowledge.get(rag_id)
            if row is None:
                return httpx.Response(404, json={"error": "unknown knowledgebase"})
            reads[rag_id] += 1
            if reads[rag_id] > 1:
                row["status"] = "processed"
            return httpx.Response(200, json=row)
        if path.startswith("/knowledgebase/") and request.method == "DELETE":
            rag_id = path.rsplit("/", 1)[-1]
            if knowledge.pop(rag_id, None) is None:
                # Their delete must 404 an id we never issued, or `detach_kb` can never
                # be shown to have removed anything.
                return httpx.Response(404, json={"error": "unknown knowledgebase"})
            return httpx.Response(200, json={"message": "success", "state": "deleted"})
        if path == "/providers" and request.method == "GET":
            # `provider_value` comes back MASKED, exactly as their `Provider` schema shows
            # (`example: xxxxxxxaz`). Modelling the mask is the point: an adapter that
            # identified entries by their value would pass against a stub that echoed the
            # real one and fail on the first live rotation.
            return httpx.Response(
                200,
                json=[{**row, "provider_value": "xxxxxxxaz"} for row in providers.values()],
            )
        if path == "/providers" and request.method == "POST":
            body = json.loads(request.content or b"{}")
            name = str(body["provider_name"])
            assert body["provider_value"], "ProviderRequest requires a non-empty value"
            providers[name] = {
                # A NEW id on every write, which is what makes replacement observable:
                # the adapter's before/after comparison is on ids, so a stub that reused
                # one would look like an append and the clause would assert nothing.
                "provider_id": f"prov_{name.lower()}_{len(providers)}",
                "provider_name": name,
            }
            return httpx.Response(200, json={"message": "successful", "status": "added"})
        if path == "/v2/agent" and request.method == "POST":
            body = json.loads(request.content or b"{}")
            agent_id = agent_id_for(body)
            agents[agent_id] = body
            return httpx.Response(200, json={"agent_id": agent_id})
        if path.startswith("/v2/agent/") and request.method == "PUT":
            agent_id = path.rsplit("/", 1)[-1]
            if agent_id not in agents:
                return httpx.Response(404, json={"error": "unknown agent"})
            agents[agent_id] = json.loads(request.content or b"{}")
            return httpx.Response(200, json={"status": "ok"})
        if path == "/v2/agent/all" and request.method == "GET":
            # A BARE ARRAY, which is what `AgentListV2` is declared as in the vendor's
            # pinned OAS (`type: array` of `AgentV2`), each row carrying a top-level `id`.
            # The adapter's `_agent_refs` reads it through `_listing_rows`, which relies on
            # `vendor_request` wrapping a top-level array as `{"data": [...]}` — so this
            # shape is also what proves that wrapper is load-bearing rather than decorative.
            return httpx.Response(200, json=[{"id": agent_id} for agent_id in agents])
        if (
            path.startswith("/v2/agent/")
            and path.endswith("/executions")
            and request.method == "GET"
        ):
            # The vendor's REAL listing: per agent, paginated by `page_number`/`page_size`
            # with a `has_more` flag, filtered by `from`. Before D-353 the adapter called a
            # global `GET /executions?created_after=` that does not exist, and this stub
            # answered it — so the suite proved a route the vendor has never had.
            agent_id = path.split("/")[3]
            if agent_id not in agents:
                return httpx.Response(404, json={"error": "unknown agent"})
            assert request.url.params.get("from"), "the listing must be time-filtered"
            page_number = int(request.url.params.get("page_number", "1"))
            page_size = int(request.url.params.get("page_size", "20"))
            assert page_size <= 50, "the vendor's documented maximum page_size is 50"
            start = (page_number - 1) * page_size
            # Distinct ids: a listing whose rows all share one id would let an adapter that
            # de-duplicates too eagerly look like one that read a short page.
            rows = [
                {**BOLNA_COMPLETED, "id": f"exec_list_{i}", "agent_id": agent_id}
                for i in range(start, min(start + page_size, listing_rows))
            ]
            executions.update(str(row["id"]) for row in rows)
            return httpx.Response(
                200,
                json={
                    "page_number": page_number,
                    "page_size": page_size,
                    "total": listing_rows,
                    "has_more": start + page_size < listing_rows,
                    "data": rows,
                },
            )
        if path.startswith("/v2/agent/") and request.method == "GET":
            agent_id = path.rsplit("/", 1)[-1]
            stored = agents.get(agent_id)
            if stored is None:
                return httpx.Response(404, json={"error": "unknown agent"})
            return httpx.Response(200, json={"agent_id": agent_id, "data": stored})
        if path.startswith("/v2/agent/") and request.method == "DELETE":
            # STATEFUL, for the reason the GET above is: a stub that answered every
            # DELETE with 200 would let an adapter that removes nothing pass the delete
            # clause, which is the one defect that clause exists to catch.
            #
            # THE 404 ON A REPEAT IS THIS SUITE'S ASSUMPTION AS MUCH AS THE ADAPTER'S,
            # and `BolnaEngine.delete_agent` says so in the marked-assumption block: the
            # vendor documents 200 and 400 and nothing about a second delete. Encoding
            # 404 here proves our HANDLING of a 404 and proves nothing about Bolna —
            # exactly the standing every shape in this stub has (see `_cartesia_handler`).
            agent_id = path.rsplit("/", 1)[-1]
            if agents.pop(agent_id, None) is None:
                return httpx.Response(404, json={"error": "unknown agent"})
            return httpx.Response(200, json={"message": "success", "state": "deleted"})
        if path == "/call" and request.method == "POST":
            body = json.loads(request.content or b"{}")
            assert body["recipient_phone_number"].startswith("+"), "E.164 only"
            # A DISTINCT id per dial, derived from the number dialled. A stub that answered
            # every `POST /call` with one execution id made two calls indistinguishable, so
            # any clause about telling two executions apart — the archived document is the
            # first — could only ever be failed by the stub. Vendors mint one id per call;
            # a stub that does not is a stub that hides that class of defect.
            placed.append(body["recipient_phone_number"])
            execution_id = f"exec_abc{len(placed):03d}"
            executions.add(execution_id)
            # THE CALLER ID, RECORDED ONLY WHEN IT WAS SENT (D-420). Their documented body
            # makes `from_phone_number` optional and falls back to the platform's own pool
            # when it is absent, so an absent key is a real and different outcome — and a
            # stub that invented a value here would make "the adapter sent our number" and
            # "the adapter dropped it" identical again.
            caller_id = body.get("from_phone_number")
            if isinstance(caller_id, str) and caller_id:
                assert caller_id.startswith("+"), "E.164 only"
                dialled_from[execution_id] = caller_id
            return httpx.Response(200, json={"execution_id": execution_id})
        if path == "/inbound/setup" and request.method == "POST":
            # `{agent_id, phone_number_id}`, both required by their own OpenAPI block
            # (`api-reference/inbound/agent.md`). A missing key is a 400 here because it is
            # a 400 there — an adapter that posted a null `phone_number_id` must not sail
            # through the suite on a stub more forgiving than the vendor.
            body = json.loads(request.content or b"{}")
            number_id = body.get("phone_number_id")
            agent_id = body.get("agent_id")
            if not isinstance(number_id, str) or not isinstance(agent_id, str):
                return httpx.Response(400, json={"error": "agent_id and phone_number_id"})
            inbound[number_id] = agent_id
            return httpx.Response(
                200,
                json={
                    "url": f"https://api.bolna.ai/inbound_call?agent_id={agent_id}",
                    "phone_number": "+911140000000",
                    "id": number_id,
                },
            )
        if path == "/inbound/unlink" and request.method == "POST":
            # STATEFUL, and a number this stub does not hold answers 404 — the same
            # MARKED ASSUMPTION the `/call/{id}/stop` branch carries and for the same
            # reason: their spec documents 200 and 400 and says nothing about unlinking a
            # number that is not linked. What it proves is OUR handling (the adapter's
            # `absent_is_success`, i.e. that an offboarding step does not fail on a
            # postcondition already satisfied), never the vendor's behaviour.
            body = json.loads(request.content or b"{}")
            number_id = body.get("phone_number_id")
            if not isinstance(number_id, str):
                return httpx.Response(400, json={"error": "phone_number_id"})
            if inbound.pop(number_id, None) is None:
                return httpx.Response(404, json={"error": "unknown phone number"})
            return httpx.Response(200, json={"id": number_id, "phone_number": "+911140000000"})
        if path.startswith("/call/") and path.endswith("/stop"):
            # `POST /call/{execution_id}/stop` — the vendor's real stop route. Until D-353
            # both the adapter and this stub used `/executions/{id}/stop`, which is not a
            # path the vendor has, so the suite agreed with the adapter about a URL that
            # would have 404'd on the first live call.
            #
            # STATEFUL, for the reason the `GET /executions/{id}` branch below is (D-187).
            # This answered 200 for every id, so the `end_call` clause — "a call the
            # engine does not hold is reported" — could only ever be failed by the stub.
            #
            # MARKED ASSUMPTION, not a captured contract (D-31/D-32): the OAS documents
            # only 200 and 400 for this route and says nothing about an execution the
            # platform is not running; 404 is the REST default its sibling GETs give. What
            # this fixture proves is OUR mapping — that the adapter surfaces a refusal
            # rather than swallowing it. Whether the vendor refuses at all is pilot gate
            # 2's question, alongside the repeat-`delete_agent` assumption it already
            # carries.
            execution_id = path.split("/")[2]
            if execution_id not in executions:
                return httpx.Response(404, json={"error": "unknown execution"})
            return httpx.Response(200, json={"message": "done", "status": "stopped"})
        if path.startswith("/executions/"):
            # The id is ECHOED from the path. Answering with the fixture's own id for any
            # id asked about is the `get_agent` echo defect wearing a different route: it
            # makes one execution's document indistinguishable from another's, which the
            # archive clause exists to refuse.
            #
            # STATEFUL, for the reason the agent GET above is: a stub that answered 200
            # for an id nobody ever placed could not fail the "unknown execution is
            # reported" clause, which is the one clause that catches an adapter
            # fabricating a call. Every id this handler has minted or listed is known;
            # nothing else is.
            execution_id = path.rsplit("/", 1)[-1]
            if execution_id not in executions:
                return httpx.Response(404, json={"error": "unknown execution"})
            document = {**BOLNA_COMPLETED, "id": execution_id}
            caller_id = dialled_from.get(execution_id)
            if caller_id is not None:
                document["telephony_data"] = {
                    **BOLNA_COMPLETED["telephony_data"],
                    "from_number": caller_id,
                }
            return httpx.Response(200, json=document)
        return httpx.Response(404, json={"error": "not found"})

    return handler


#: How many calls a saturated Cartesia listing returns per page. Equal to the adapter's
#: `_LISTING_PAGE_SIZE` on purpose: that constant is the `limit` the adapter asks for, and
#: a page that comes back FULL is the only thing that makes it ask for another one, so
#: restating the number here would let the two drift and quietly stop exercising the walk.
CARTESIA_FULL_PAGE = cartesia_module._LISTING_PAGE_SIZE


def _cartesia_handler(*, listing_rows: int = 1) -> Callable[[httpx.Request], httpx.Response]:
    """A stub of Cartesia Line's control plane, at the adapter's own evidence standing.

    **THIS STUB PROVES NOTHING ABOUT CARTESIA.** It is built from the same sources the
    adapter cites — the OSS SDK for the host, version and document endpoint; a search
    summary for the outbound-call shape; RESTful inference for the rest — so it can only
    ever confirm that our mapping is self-consistent. That is exactly what the Bolna stub
    does (its `GET /v2/agent` shape is equally hand-maintained), and it is the whole
    reason `OPERATIONS §2` keeps vendor behaviour as pilot GATES rather than tests.
    What it DOES prove is worth having: that a vendor with a different capability profile
    can satisfy this contract without any clause bending to accommodate it.

    STATEFUL agent and document stores, for the reasons the Bolna stub is stateful: a stub
    that echoed the last write would let an echoing `get_agent` pass the read-back clause,
    and one that answered every DELETE with 200 would let a `detach_kb` that removes
    nothing sail through.
    """
    #: SEEDED WITH ONE AGENT, which the Bolna stub does not need and this one does.
    #: `GET /agents/calls` requires an `agent_id`, so `list_executions` fans out over
    #: `GET /agents` — and on this platform an account HAS agents whether or not our API
    #: client made them (they are deployed from git repositories). An empty account would
    #: make every listing clause pass vacuously with zero rows, which is the shape of stub
    #: this suite refuses everywhere else.
    agents: dict[str, dict[str, Any]] = {"agent_deployed": {"name": "deployed-from-repo"}}
    documents: dict[str, dict[str, dict[str, Any]]] = {}
    placed: list[str] = []
    #: The Bolna stub's `executions`, same reasoning — see its `GET /executions/{id}`.
    calls_placed: set[str] = set()

    def agent_id_for(body: dict[str, Any]) -> str:
        # Derived from the NAME: stable across a re-create (the ref-stability clause needs
        # that) and distinct per agent (the read-back clause needs that).
        return "agent_" + hashlib.sha256(str(body.get("name") or "").encode()).hexdigest()[:8]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        body = json.loads(request.content or b"{}") if request.content else {}

        # The version pin is not decoration: assert it is sent on EVERY request, so a
        # future edit that drops the header fails here rather than on a vendor's next
        # breaking release. The auth header is asserted in the form their generated
        # clients actually send (`Authorization: Bearer …`), not merely as "present".
        assert request.headers.get("Cartesia-Version") == cartesia_module.API_VERSION
        assert (request.headers.get("Authorization") or "").startswith(
            f"{cartesia_module.AUTH_SCHEME} "
        )

        # THE CALL ROUTES COME FIRST. `/agents/calls` has the same shape as
        # `/agents/{id}`, so a generic agent match placed above would swallow it and
        # answer 404 for every listing — which is exactly what it did.
        if path == "/agents/calls" and method == "POST":
            assert body["outbound_calls"][0]["to_number"].startswith("+"), "E.164 only"
            assert body.get("from_number_id"), "a caller id must be named"
            # One id per dial, for the reason the Bolna stub mints one: a stub that cannot
            # tell two calls apart makes every clause about two calls unfailable.
            placed.append(body["outbound_calls"][0]["to_number"])
            call_id = f"cart_call_{len(placed)}"
            calls_placed.add(call_id)
            return httpx.Response(200, json={"outbound_calls": [{"agent_call_id": call_id}]})
        if path == "/agents/calls" and method == "GET":
            # THE PUBLISHED LISTING CONTRACT, asserted rather than tolerated (D-270).
            # `agent_id` is `Required[str]` in their params type, so a listing without one
            # is a 4xx at the vendor and must be a failure here — the previous stub
            # answered a global, unfiltered listing that the real API cannot serve, which
            # is how the adapter came to send an invented `start_time` for months.
            query = request.url.params
            agent_id = query.get("agent_id")
            assert agent_id, "`agent_id` is required on GET /agents/calls"
            assert query.get("expand") == "transcript", (
                "without `expand=transcript` the vendor returns no transcript, and the "
                "poller is the path with no webhook behind it to supply one"
            )
            limit = int(query.get("limit") or 0)
            assert 1 <= limit <= 100, "`limit` ranges between 1 and 100"
            # Cursor by call id, their `starting_after`. Ids carry an ordinal so the stub
            # can continue a walk; a stub that ignored the cursor and re-served page one
            # would make the no-progress branch unreachable.
            after = query.get("starting_after")
            first = int(after.rsplit("_", 1)[-1]) + 1 if after else 0
            rows = [
                _cartesia_completed(f"{agent_id}_c_{i}") for i in range(first, first + listing_rows)
            ]
            calls_placed.update(str(row["id"]) for row in rows)
            # `{"data": [...]}` and NO `has_more`: their page model derives the next cursor
            # from the last row's id, so shortness is the only end-of-window signal.
            return httpx.Response(200, json={"data": rows})
        if path == "/agents" and method == "GET":
            # `{"summaries": [...]}` — read at source in `types/agent_list_response.py`.
            # This is what makes the per-agent listing reachable at all.
            return httpx.Response(
                200,
                json={"summaries": [{**stored, "id": ref} for ref, stored in agents.items()]},
            )
        if path.startswith("/agents/calls/") and path.endswith("/end"):
            # STATEFUL for the Bolna stub's `/stop` reason, and a marked assumption for
            # the same reason (D-187): nothing sourced says what Line answers for a call
            # it is not running, and the `end_call` clause is unfailable while the stub
            # says 200 to every id.
            call_id = path.rsplit("/", 2)[-2]
            if call_id not in calls_placed:
                return httpx.Response(404, json={"error": "unknown call"})
            return httpx.Response(200, json={"status": "ended"})
        if path.startswith("/agents/calls/") and method == "GET":
            # Echo the id asked about, and STATEFUL — see the Bolna stub's `/executions/`
            # branch for both halves of the argument.
            call_id = path.rsplit("/", 1)[-1]
            if call_id not in calls_placed:
                return httpx.Response(404, json={"error": "unknown call"})
            return httpx.Response(200, json=_cartesia_completed(call_id))
        if path == "/agents" and method == "POST":
            agent_id = agent_id_for(body)
            agents[agent_id] = body
            documents.setdefault(agent_id, {})
            return httpx.Response(200, json={"id": agent_id})
        if path.startswith("/agents/") and path.count("/") == 2 and method == "PATCH":
            agent_id = path.rsplit("/", 1)[-1]
            if agent_id not in agents:
                return httpx.Response(404, json={"error": "unknown agent"})
            agents[agent_id].update(body)
            return httpx.Response(200, json={"id": agent_id})
        if path.startswith("/agents/") and path.count("/") == 2 and method == "GET":
            agent_id = path.rsplit("/", 1)[-1]
            stored = agents.get(agent_id)
            if stored is None:
                return httpx.Response(404, json={"error": "unknown agent"})
            return httpx.Response(200, json={"agent": {**stored, "id": agent_id}})
        if path.startswith("/agents/") and path.count("/") == 2 and method == "DELETE":
            # Stateful, and the documents store goes with the agent: an agent object that
            # survived only as a bag of documents would let `get_agent` keep answering.
            agent_id = path.rsplit("/", 1)[-1]
            if agents.pop(agent_id, None) is None:
                return httpx.Response(404, json={"error": "unknown agent"})
            documents.pop(agent_id, None)
            return httpx.Response(200, json={"status": "deleted"})
        if path.endswith("/documents") and method == "POST":
            agent_id = path.split("/")[2]
            store = documents.setdefault(agent_id, {})
            doc_id = f"doc_{len(store) + 1}"
            store[doc_id] = {"id": doc_id, "title": body.get("title")}
            return httpx.Response(200, json={"id": doc_id})
        if path.endswith("/documents") and method == "GET":
            agent_id = path.split("/")[2]
            return httpx.Response(
                200, json={"documents": list(documents.get(agent_id, {}).values())}
            )
        if "/documents/" in path and method == "DELETE":
            agent_id, doc_id = path.split("/")[2], path.rsplit("/", 1)[-1]
            if documents.get(agent_id, {}).pop(doc_id, None) is None:
                # Their delete must 404 an id we never issued, or `detach_kb` can never be
                # proven to have removed anything (the clause that makes it mean something).
                return httpx.Response(404, json={"error": "unknown document"})
            return httpx.Response(200, json={"status": "deleted"})
        return httpx.Response(404, json={"error": "not found"})

    return handler


#: A stub of ONE vendor route, written by the clause that needs it rather than by this
#: file. The stubs above model a vendor BEHAVING; these model one misbehaving.
VendorHandler = Callable[[httpx.Request], httpx.Response]

#: How to point ONE HTTP-speaking adapter at a transport of the clause's choosing.
#:
#: Everything else in this file hands out adapters wired to a WELL-BEHAVED stub, so every
#: clause in the suite measured a happy path plus the handful of 404s the stubs are
#: stateful enough to produce. The failure paths an adapter meets in production — a
#: throttle, a gateway error, a socket that never answers, a 200 carrying a WAF challenge
#: — had no fixture at all, and that is how the two real adapters came to disagree about
#: all of them (D-240): `bolna` retried a 429 and reported it `transient`, `cartesia`
#: reported the same 429 as a flat rejection with no backoff; `bolna` refused a 2xx it
#: could not parse, `cartesia` turned it into `{}` and built an `ExecutionSnapshot` out of
#: nothing.
#:
#: A RECIPE PER ADAPTER rather than one generic builder, because the credential, the base
#: URL and the version pin are exactly the per-vendor half `engine/vendor_http.py`
#: deliberately does not hold. Each call builds a FRESH adapter, so a transport wired to
#: answer 429 forever cannot leak into the next clause's subject.
TRANSPORT_RECIPES: dict[str, Callable[[VendorHandler], VoiceEngine]] = {
    "bolna": lambda handler: BolnaEngine(
        api_key="test-key",
        fx_rate=Decimal("88.00"),
        client=httpx.AsyncClient(
            base_url="https://api.bolna.ai", transport=httpx.MockTransport(handler)
        ),
    ),
    "cartesia": lambda handler: CartesiaEngine(
        api_key="test-key",
        from_number_id="num_test",
        client=httpx.AsyncClient(
            base_url=cartesia_module.BASE_URL,
            headers={
                # `AUTH_HEADER`, not the old `API_KEY_HEADER`: D-271 moved the adapter
                # to `Authorization: Bearer` after reading both generated clients.
                cartesia_module.AUTH_HEADER: (f"{cartesia_module.AUTH_SCHEME} test-key"),
                cartesia_module.VERSION_HEADER: cartesia_module.API_VERSION,
            },
            transport=httpx.MockTransport(handler),
        ),
    ),
}


@pytest.fixture(params=sorted(TRANSPORT_RECIPES))
def ladder(request: pytest.FixtureRequest) -> Callable[[VendorHandler], VoiceEngine]:
    """One HTTP-speaking adapter, over whatever transport the clause hands it."""
    return TRANSPORT_RECIPES[str(request.param)]


@pytest.fixture
def transport_recipe_ids() -> frozenset[str]:
    """Which adapters the transport-ladder clauses actually ran against."""
    return frozenset(TRANSPORT_RECIPES)


@pytest.fixture
def http_speaking_engine_ids() -> frozenset[str]:
    """Which adapters in the roster reach their vendor over HTTP.

    Every real adapter does, by definition. `FakeEngine` is the one subject that does not,
    because it IS the vendor — so it is identified by its TYPE rather than by its name,
    and a third vendor added to `ENGINE_IDS` lands in this set automatically. That is what
    makes the roster clause in `contract_test.py` bite rather than pass vacuously.
    """
    return frozenset(eid for eid in ENGINE_IDS if not isinstance(make_engine(eid), FakeEngine))


def make_engine(engine_id: str, *, listing_rows: int = 1) -> VoiceEngine:
    if engine_id == "fake":
        return FakeEngine(listing_page_size=FULL_LISTING_PAGE)
    if engine_id == "fake-restricted":
        return FakeEngine(
            listing_page_size=FULL_LISTING_PAGE,
            capabilities=DICTATED_SPEECH_CAPABILITIES,
            # Its own name, not "fake": `WEBHOOK_AUTH_BY_ENGINE` is keyed by name and
            # this instance authenticates differently, so sharing a name would make that
            # table ambiguous — and the table is what the voice-runtime receiver reads.
            name="fake-restricted",
        )
    if engine_id == "fake-deployed":
        return FakeEngine(
            listing_page_size=FULL_LISTING_PAGE,
            capabilities=EXTERNAL_DEPLOYMENT_CAPABILITIES,
            # Its own name for `fake-restricted`'s reason: `WEBHOOK_AUTH_BY_ENGINE` is
            # keyed by name, and two instances answering to one name while declaring
            # different capabilities make that table ambiguous.
            name="fake-deployed",
        )
    if engine_id == "cartesia":
        return CartesiaEngine(
            api_key="test-key",
            # A caller id must be NAMED for an outbound call to be placeable at all —
            # the adapter refuses without one rather than dialling from whatever the
            # account happens to hold first. The stub asserts it arrives.
            from_number_id="num_test",
            client=httpx.AsyncClient(
                base_url=cartesia_module.BASE_URL,
                headers={
                    cartesia_module.AUTH_HEADER: f"{cartesia_module.AUTH_SCHEME} test-key",
                    cartesia_module.VERSION_HEADER: cartesia_module.API_VERSION,
                },
                transport=httpx.MockTransport(_cartesia_handler(listing_rows=listing_rows)),
            ),
        )
    return BolnaEngine(
        api_key="test-key",
        fx_rate=Decimal("88.00"),
        client=httpx.AsyncClient(
            base_url="https://api.bolna.ai",
            transport=httpx.MockTransport(_bolna_handler(listing_rows=listing_rows)),
        ),
    )


@pytest.fixture(params=ENGINE_IDS)
def engine(request: pytest.FixtureRequest) -> VoiceEngine:
    return make_engine(request.param)


def saturated(engine: VoiceEngine) -> VoiceEngine:
    """Drive an adapter's `list_executions` to a FULL page — the truncation case.

    Every adapter reaches it differently and none of them may EXPOSE how (hard rule 2):
    the Bolna stub answers with exactly a page's worth of rows and no metadata at all
    (the worst case, since Bolna publishes no pagination contract), and the fake engine
    is given more calls than its page size. What the contract test asserts afterwards is
    identical for both — the caller is TOLD the answer may be short.

    A function rather than only a fixture because the adapter audit
    (`tests/engine_audit_test.py`) runs these clauses against saboteur adapters outside
    pytest's fixture machinery, and a clause it cannot set up is a clause no saboteur can
    ever fail.
    """
    if isinstance(engine, FakeEngine):
        # A FRESH instance of the same adapter class, never the one passed in: seeding
        # eleven calls into a shared engine would change what every other clause sees,
        # and a suite whose clauses interfere is one that fails in definition order.
        #
        # It carries the ORIGINAL's capabilities and name. Rebuilding with the defaults
        # would silently hand the truncation clause a fully-capable engine while the
        # parameter id still said `fake-restricted` — a saboteur could then hide in the
        # one clause whose subject is constructed rather than passed in.
        saturated_fake = type(engine)(
            listing_page_size=FULL_LISTING_PAGE,
            capabilities=engine.capabilities,
            name=engine.name,
        )
        for i in range(FULL_LISTING_PAGE + 1):
            saturated_fake.seed_inbound_call(
                call_id=f"exec_seed_{i}",
                agent_ref="fakeagent_seed",
                from_e164="+915000000001",
                to_e164="+911140000000",
            )
        return saturated_fake
    if isinstance(engine, CartesiaEngine):
        return make_engine("cartesia", listing_rows=CARTESIA_FULL_PAGE)
    assert isinstance(engine, BolnaEngine), f"no saturation recipe for {type(engine).__name__}"
    return make_engine("bolna", listing_rows=BOLNA_SATURATION_ROWS)


@pytest.fixture(params=ENGINE_IDS)
def saturated_engine(request: pytest.FixtureRequest) -> VoiceEngine:
    return saturated(make_engine(str(request.param)))


@pytest.fixture
def declared_agent_hostings() -> frozenset[str]:
    """Every `agent_hosting` value the roster actually declares.

    Built here rather than in the clause because `ENGINE_IDS` and `make_engine` live here:
    the clause asks which shapes are exercised, and this answers it from the same roster
    every other fixture is parametrised over, so the two cannot describe different suites.
    """
    return frozenset(make_engine(eid).capabilities.agent_hosting for eid in ENGINE_IDS)


@pytest.fixture
def engine_id(request: pytest.FixtureRequest) -> str:
    return str(request.node.callspec.params["engine"])
