# Bolna — harvested vendor evidence

Bolna is the primary voice engine (D-31). The adapter (`apps/api/engine/bolna.py`) was
written largely from reasoning and said so, in blocks marked MARKED ASSUMPTION and
UNVERIFIED. This directory is where the reasoning got replaced with sources, so the next
reader inherits **evidence rather than conclusions** (CLAUDE.md, quality bar).

## The three evidence classes, and why the label is the point

A conclusion filed under the wrong class is worse than no conclusion — that is the exact
defect D-31/D-32 exist to prevent. Every fact in this directory carries one of:

| Class | Means | Worth |
|---|---|---|
| **VERIFIED-OSS** | Read at source in `bolna-ai/bolna`, the open-source self-hosted framework. | Authoritative for how the engine **behaves** — call flow, execution lifecycle, transcript construction, provider config, config validation. **Not proof of the hosted REST contract.** |
| **REPORTED-DOCS** | From a WebSearch result summary quoting the hosted docs. | Suggestive. Never proof. Cited as a search snippet, never as though the page had been read. |
| **STILL UNVERIFIED** | Needs a live account. | Nothing. Each one is a named gate in OPERATIONS §2. |

## The category error this directory exists to prevent

`bolna-ai/bolna` on GitHub is the **open-source self-hosted framework**. Its `API.md`
documents `/agent` and `/all`. The **hosted platform our adapter targets** is
`https://api.bolna.ai` with `/v2/agent`, `/call`, `/executions/{id}`, `/executions`,
`/knowledgebase` — a different surface. The hosted platform is built on that codebase,
which makes the OSS repo strong evidence about semantics and data shapes and **no
evidence at all** about the hosted route contract.

The sharpest illustration is in `oss-harvest.md` under *Agent lifecycle*: their OSS server
**intends** to answer 404 for a missing agent and, because of a swallowed `HTTPException`,
**actually** answers 500. VERIFIED-OSS told us the intended semantics and simultaneously
showed the implementation missing them. That is the whole reason the class exists.

## Network constraint under which this was gathered

`docs.bolna.ai`, `www.bolna.ai` and `api.bolna.ai` are all refused by this environment's
egress proxy (`EGRESS_BLOCKED`) — including the `www.bolna.ai/docs/...` path, which was
tried once and refused. So **no hosted documentation page in this repository has been read
by anyone here.** `github.com` is reachable, which is why the OSS harvest is a full clone
read at source rather than a summary.

## Files

| File | What it holds |
|---|---|
| `oss-harvest.md` | VERIFIED-OSS facts, each with the file it was read in. Pinned to `bolna-ai/bolna@cd2e192600ae94daeeb627d26c604b69cfc50de4`. |
| `hosted-reported.md` | REPORTED-DOCS facts, each with the search query and the URL the snippet described. |

The reconciliation — every assumption, its evidence class, and what changed in the code —
is `docs/evidence/vendor-bolna-reconciliation.md`.
