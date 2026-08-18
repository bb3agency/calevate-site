# Cartesia adapter — reconciliation against primary sources (D-270 … D-273)

**Date**: 18 Aug 2026. **Subject**: `apps/api/engine/cartesia.py` and everything keyed to
it. **Sources**: `docs/vendor/cartesia/` — read that first; this file records what changed
and what did not.

## Why this was possible now and not before

`docs.cartesia.ai` is still egress-blocked. What changed is that `github.com` is not, and
Cartesia publishes **Stainless-generated clients** — `cartesia-python` and `cartesia-js`,
both headed *"File generated from our OpenAPI spec by Stainless"*. A generated client is a
machine translation of the spec: one method per operation, one model per schema. So it
answers the control-plane questions the Line runtime SDK never could, and a *missing*
operation in it is evidence rather than silence.

Cross-checking Python against TypeScript is what turns a generator quirk into a spec fact.
Where the two agree, this document treats it as VERIFIED-SDK.

## The table

| # | Assumption as it stood | Evidence class now | What changed |
|---|---|---|---|
| 1 | `Cartesia-Version: 2026-04-03`, "which their harness sends on every call setup" | **VERIFIED-SDK — wrong, twice** | `API_VERSION` → `2026-08-14`. `2026-04-03` is `line/voice_agent_app.py:129`, returned by OUR agent to their harness in the `POST /chats` body; it versions the in-call websocket protocol, not the REST API. Test asserts the literal. |
| 2 | Auth is `X-API-Key` (REPORTED) | **VERIFIED-SDK — superseded** | `Authorization: Bearer <key>`, as both generated clients build for every operation incl. `client.agents.*`. `X-API-Key` is published in Cartesia's own skills repo but beside older version pins. Sending both was rejected: two credential headers hide which one was honoured. |
| 3 | `POST /agents` creates an agent (INFERRED) | **CONTRADICTED** | No `create` method in either generated client; agents are deployed from git via the `cartesia` CLI. Behaviour unchanged (the port requires the method) — relabelled CONTRADICTED, with the real path written down. Gate 19(a). |
| 4 | The agent object carries `system_prompt`, `introduction`, `model`, `language`, `webhook_url` | **CONTRADICTED / partly fixed** | `PATCH /agents/{id}` accepts exactly `{description, name, tts_language, tts_voice}`. `language` → `tts_language` (fixed); invented `webhook_url` removed (fixed); `system_prompt`/`introduction`/`model` kept and labelled, because removing them breaks the conformance suite's hard-rule-5 clauses for a reason unrelated to our mapping. Gate 19(a). |
| 5 | `PATCH /agents/{id}` is the update verb (INFERRED) | **VERIFIED-SDK — right** | No change. The reasoning (partial body must not clear unnamed fields) was right for the right reason. |
| 6 | `DELETE /agents/{id}` — "NO PUBLIC DOCUMENTATION FOUND" | **VERIFIED-SDK — the route exists** | Finding withdrawn. The remaining assumption is narrower: what a REPEAT delete answers, sharpened by `AgentSummary.deleted_at` hinting at soft deletion. |
| 7 | `GET /agents/{id}` can read the prompt/greeting/model back | **CONTRADICTED** | `AgentSummary` has none of them. Against a real account every publish scores `unreadable`. Relabelled; behaviour unchanged. Gate 19(a). |
| 8 | Call id is `agent_call_id` | **VERIFIED-SDK — wrong** | `AgentCall.id`. `_CALL_ID_KEYS` reordered so the verified name leads. |
| 9 | Timestamps are `started_at`/`created_at`/`ended_at` | **VERIFIED-SDK — wrong** | `start_time`/`end_time`. Fixed, old names kept as fallbacks. Without this every real snapshot had no timestamps. |
| 10 | Numbers are top-level `from_number`/`to_number` | **VERIFIED-SDK — wrong** | Nested `telephony_params.{from,to}`. Fixed. Open question recorded, not invented away: their docs call `from` the AGENT's number and `to` the CALLER's, which reads inverted on an inbound call, and there is no `direction` field. Gate 19(d). |
| 11 | `duration_seconds` / `duration` on the call | **VERIFIED-SDK — no such field** | Derived from `end_time - start_time`, only when both are present. |
| 12 | Statuses are an open telephony vocabulary | **VERIFIED-SDK** | The enum is `active`/`completed`/`failed`/`cancelled`. `cancelled` mapped explicitly to `failed` **and added to `_TERMINAL_RAW`** — the real defect: a cancelled call was non-terminal for ever, re-polled every tick, never reaching the post-call pipeline. |
| 13 | Transcript entries are `{role, content}` | **VERIFIED-SDK — wrong** | The utterance is `text`; `content` is never populated. And `role == "system"` is a LOG row (`log_event`/`log_metric`), not speech — it was being filed into client transcripts as a caller utterance. Now skipped, and not counted as unparsed. |
| 14 | `GET /agents/calls?start_time=…` is a global, time-filtered listing | **VERIFIED-SDK — wrong on both counts** | `agent_id` is REQUIRED and no time filter exists. Rewritten: fan out over `GET /agents` (`{"summaries": […]}`), page each agent with `limit=100`/`starting_after`, ask `expand=transcript`, apply `since` client-side (their order is start-time DESC, so the walk stops at the window edge). |
| 15 | Pagination is unpublished, so a full page is "suspected truncation" | **VERIFIED-SDK — published** | Cursor pagination with no `has_more`. `_LISTING_PAGE_SUSPECT` is gone; completeness is now decided by a real walk with `page_cap_reached` / `next_link_no_progress` reasons. |
| 16 | Recording URL on the call object | **VERIFIED-SDK — no such field** | Audio is an authenticated download at `/agents/calls/{id}/audio`, which our fetcher holds no credential for. Left unread rather than filled with a URL that 401s. Gate 19(b). |
| 17 | Cost is unsourced; capture one real call and read it off | **VERIFIED-SDK — there is nothing to read** | No cost/currency field anywhere on the call, and usage is an ACCOUNT meter (`GET /usage/credits`, daily, grouped by capability/model/voice/api_key). `_cost` returning `None` is now the answer, not a deferral; the hole is commercial (a rate card), not an endpoint. |
| 18 | `POST /agents/calls/{id}/end` (INFERRED) | **still INFERRED, and weaker** | The generated clients expose only three call operations, all GET. In `line`, a call is ended from INSIDE by the agent yielding `EndCallOutput`. Left inferred rather than made to refuse, because `end_call` has no `EngineCapabilities` member to refuse through. Gate 19(b). |
| 19 | `POST /agents/calls` places outbound calls | **REPORTED-DOCS only** | Unchanged. Absent from both generated clients; the shape comes from one search snippet. `from_number_id` corroborated as a real concept by `GET /agents/{id}/phone-numbers` returning `{id, number}`. Gate 19(b). |
| 20 | `/agents/{id}/documents` CRUD (INFERRED from the sourced query path) | **still INFERRED, and weaker** | Neither generated client has a documents resource at all. Also newly noted: even the SOURCED query path authenticates with a per-call agent JWT, not the account key this adapter holds. Unchanged; `knowledge_base=True` stands because retrieval demonstrably exists. Gate 19(f). |
| 21 | `webhook_auth="hmac"` — "their webhooks are signed (TRD §10.5)" | **REPORTED-DOCS, and probably not an HMAC** | **Deliberately unchanged.** Webhooks exist (`AgentSummary.webhook_id`, VERIFIED-SDK); no SDK carries a scheme; one snippet describes an `x-webhook-secret` SHARED SECRET header. `WebhookAuthMethod` is `hmac\|source_ip\|none`, so there is no truthful third value, and `hmac` is the only one that fails CLOSED in both halves. Comments in the adapter and in `WEBHOOK_AUTH_BY_ENGINE` now say exactly this. Gate 19(e). |
| 22 | `stt="engine"`, `tts="engine"`, `llm="ours"` | **VERIFIED-SDK — stands** | `PATCH` accepting `tts_voice` does not make TTS ours: the value is a Cartesia voice id addressing Sonic, and nothing in D-36's Bulbul catalogue names one. No flag weakened. |
| 23 | `number_series=frozenset()`, `transfer=False` | **unchanged** | Both still correct and still for the reasons already recorded. |

## What was deliberately NOT done, and why

* **The port was not changed.** `VoiceEngine` requires `create_agent` and a prompt
  read-back; Cartesia offers neither. Expressing that needs a new `EngineCapabilities`
  member, a conformance clause that respects it, a `FakeEngine` profile, and a publish
  path that degrades honestly. Doing it on the same afternoon the evidence arrived would
  be a large change to the one seam the whole engine story rests on, made against a vendor
  we have no account with. It is written down instead — in the module docstring, in TRD
  §10.5's correction 2, and as gate 19(a) — which is the difference between a deferral and
  a decision.
* **`WebhookAuthMethod` was not widened.** See row 21.
* **No capability flag was weakened to make anything pass.** The three that could have
  been (`knowledge_base`, `llm`, `tts`) are all unchanged.

## What proves the fixes

`tests/engine_capability_test.py` gained five clauses, each sabotage-verified — the fix
was reverted in place and the named test failed, then restored:

| Test | Sabotage that fails it |
|---|---|
| `test_cartesia_pins_the_rest_api_version_and_not_the_line_websocket_one` | `API_VERSION` back to `2026-04-03` |
| `test_cartesia_authenticates_the_way_cartesias_own_clients_do` | `AUTH_HEADER` back to `X-API-Key` |
| `test_cartesia_reads_the_call_object_cartesia_actually_returns` | either the `start_time`/`end_time` read or the `telephony_params` read reverted |
| `test_cartesia_treats_a_cancelled_call_as_over` | `cancelled` removed from `_TERMINAL_RAW` |
| `test_cartesia_transcript_reads_text_and_never_files_a_log_row_as_speech` | `content`-first lookup restored, or the `system`-role skip removed |
| `test_cartesia_lists_calls_the_only_way_the_vendor_allows` | `agent_id` swapped back for the invented `start_time` |

The conformance stub in `packages/shared/tests/engine_conformance/conftest.py` was moved to
the verified shapes at the same time — `{"data": […]}`, required `agent_id`, asserted
`expand=transcript`, `limit` bounds, cursor continuation, a seeded already-deployed agent,
and a `system` transcript row. It is still a stub of OUR mapping and proves nothing about
Cartesia; what it no longer does is prove our own inferences back at us on the fields where
real evidence now exists.

## Still unverified, and what settles each

All of it is one thing: **a Cartesia account**. Not a legal entity, not a regulator, not a
signed term — an API key. That is the single external blocker, and OPERATIONS §2 gate 19
is the checklist to run the hour it exists.
