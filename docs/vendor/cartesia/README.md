# Cartesia — harvested primary sources

**What this directory is.** Every fact this repository holds about Cartesia's hosted API,
with the source it came from and how strongly that source supports it. It exists because
`docs.cartesia.ai` and `cartesia.ai` are refused by this environment's egress proxy
(CONNECT → 403), so nobody here has read Cartesia's API reference, and the adapter in
`apps/api/engine/cartesia.py` was written from what could be reached. The next session
must inherit the EVIDENCE, not a previous session's conclusions.

## The evidence ladder used in every file here

| Class | Meaning | Weight |
|---|---|---|
| **VERIFIED-SDK** | Read in Cartesia's own published source, cited `repo/path:line`. For the generated clients this is a machine translation of Cartesia's OpenAPI document ("File generated from our OpenAPI spec by Stainless"), so it is the strongest evidence reachable from here. | Authoritative for the surface it covers. Silence is not proof of absence in general — but silence in a *generated* client is meaningful, because the generator emits every operation the spec declares. |
| **REPORTED-DOCS** | A search engine's summary of a page that could not be fetched. Nobody here has seen the page. | Suggestive. Never a basis for changing behaviour. |
| **UNRELIABLE-THIRD-PARTY** | A non-Cartesia mirror or reconstruction. See `sources.md` — one such mirror is demonstrably wrong about paths we can check. | Not evidence. Recorded only so the next session does not re-adopt it. |
| **STILL UNVERIFIED** | Needs a live Cartesia account. Each one is a named sub-check of OPERATIONS §2 gate 16. | Not a premise. |

## Sources actually read (all cloned from GitHub, which IS reachable)

| Repo | Commit / version | What it is | Standing |
|---|---|---|---|
| `cartesia-ai/line` | `3062c978a2408152c6338679baf57aa230c63596` (v0.2.16) | The Line voice-agent SDK — the agent PROGRAM that runs inside Cartesia's harness. | VERIFIED-SDK for the in-call protocol, the KB query endpoint and the API host. |
| `cartesia-ai/cartesia-python` | `main`, package v4.x | Official client, **Stainless-generated from Cartesia's OpenAPI spec**. Ships `api.md`, a complete generated reference. | VERIFIED-SDK, and the best source reachable for the agents control plane. |
| `cartesia-ai/cartesia-js` | `main`, package v4.x | The same spec generated for TypeScript. Used as a cross-check: where the two agree, it is the spec speaking rather than a generator quirk. | VERIFIED-SDK. |
| `cartesia-ai/cartesia-mcp` | `main` | Cartesia's own MCP server. Carries hand-written calls to endpoints the generated clients omit. | VERIFIED-SDK. |
| `cartesia-ai/skills` | `main` | Cartesia's own agent skills, including `skills/line-voice-agent/references/calls-api.md`. First-party prose in a first-party repo. | VERIFIED-SDK for the shapes it states outright. |

## Files

* `auth-and-versioning.md` — how a request authenticates and which API version it pins.
* `agents-control-plane.md` — the agent object, what can be written to it, and the fact that agents are not created over the API at all.
* `calls-and-transcripts.md` — the call object, its status vocabulary, its transcript shape and its pagination contract.
* `webhooks-cost-and-kb.md` — webhooks, how usage is metered, and what exists for documents.
* `sources.md` — provenance, including the mirror that must not be trusted.

## The one line a reader needs before touching the adapter

Cartesia Line is **not** a "POST a config, they run it" platform. An agent is a **deployed
program** built from a git repository through the `cartesia` CLI; the API can read agents,
rename them, set their TTS voice and language, delete them, and read their calls — and
that is the whole of the agent control plane the official clients expose. There is **no
create-agent endpoint, no prompt field, no greeting field and no model field on the agent
object.** That is a structural mismatch with the `VoiceEngine` port, not a gap in our
adapter, and `docs/evidence/vendor-cartesia-reconciliation.md` records what it costs.
