# Cartesia — provenance, and one source that must not be trusted

## Reachability, established by testing (do not re-discover it)

| Host | Result |
|---|---|
| `docs.cartesia.ai`, `www.cartesia.ai`, `cartesia.ai` | **EGRESS_BLOCKED.** WebFetch and curl both refused (CONNECT → 403). |
| `github.com`, `raw.githubusercontent.com` | Reachable. `git clone --depth 1` works. |
| Web search | Works, and often quotes substantial content from the blocked pages. A quote is a **REPORTED-DOCS** snippet, never a page anyone here has read. |

## How each first-party repo was obtained

```
git clone --depth 1 https://github.com/cartesia-ai/line.git
git clone --depth 1 https://github.com/cartesia-ai/cartesia-python.git
git clone --depth 1 https://github.com/cartesia-ai/cartesia-js.git
git clone --depth 1 https://github.com/cartesia-ai/cartesia-mcp.git
git clone --depth 1 https://github.com/cartesia-ai/skills.git
```

`cartesia-ai/line` was at `3062c978a2408152c6338679baf57aa230c63596` ("Bump version to
0.2.16"), the same commit the adapter already cited. The rest were cloned at `main` on
18 Aug 2026.

## Why the generated clients outrank everything else reachable

`cartesia-python` and `cartesia-js` are **Stainless-generated**; every file begins
*"File generated from our OpenAPI spec by Stainless."* A generator emits one method per
operation and one model per schema, so the client is a faithful projection of the spec at
the moment it was generated. Two independent generators (Python and TypeScript) agreeing
on a path, a field name or a header value is the spec speaking, not a quirk.

This is why a *missing* operation carries weight here in a way it would not in a
hand-written SDK: the absence of `client.agents.create` in both generated clients is
evidence that the spec declares no create-agent operation.

## ⚠ `api-evangelist/cartesia-ai` — UNRELIABLE-THIRD-PARTY, do not use

`https://github.com/api-evangelist/cartesia-ai` ships what looks like an authoritative
set of per-API OpenAPI documents (`openapi/cartesia-ai-agents-api-openapi.yml`,
`…-calls-api-…`, `…-webhooks-api-…`, `…-knowledge-base-api-…`, and more), complete with
`info.version: 2026-03-01`, `servers: https://api.cartesia.ai`, and a `.refine-report.json`
describing a processing pipeline. It is tempting and it is wrong.

**It fails on the one thing we can independently check.** Its calls document declares
`GET /calls`, `POST /calls/outbound`, `GET /calls/{id}`, `POST /calls/{id}/cancel`,
`GET /calls/{id}/audio`, `POST /call-batches`. Cartesia's own generated clients call
`GET /agents/calls`, `GET /agents/calls/{call_id}` and
`GET /agents/calls/{call_id}/audio`, and the outbound-dialing docs snippet says
`POST /agents/calls`. Every path in the mirror is missing the `/agents` prefix, and its
outbound body (`{agent_id, to, from, metadata}`) does not match the reported shape
(`{agent_id, from_number_id, ringing_timeout_seconds, outbound_calls: [...]}`) either.

Where a document is demonstrably reconstructed rather than mirrored on the endpoints we
can verify, it cannot be evidence about the ones we cannot. It is recorded here **only**
so the next session recognises it and does not re-adopt it.

The one thing it corroborates, and only because it agrees with the official clients:
`Authorization: Bearer <sk_car_…>` plus a required `Cartesia-Version` header.

## Search snippets relied on (REPORTED-DOCS)

| Claim | Page the snippet came from |
|---|---|
| `POST https://api.cartesia.ai/agents/calls` with `from_number_id`, `agent_id`, `ringing_timeout_seconds`, `outbound_calls[{to_number, metadata}]`; headers `X-API-Key`, `Cartesia-Version: 2026-03-01` | `docs.cartesia.ai/line/integrations/telephony/outbound-dialing` |
| Webhook handlers should check an `x-webhook-secret` header; webhooks fire on call start / complete / fail and carry the full transcript | Cartesia docs (webhooks/observability) |
| The agents platform includes "a knowledge base of documents and folders" | Cartesia docs (agents) |
| Agents are developed locally and deployed with the `cartesia` CLI; one deployment active per agent | `cartesia.ai/blog/introducing-line-for-voice-agents`, `docs.cartesia.ai/line/cli` |
