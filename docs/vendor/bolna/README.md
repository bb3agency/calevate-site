# Bolna — harvested vendor evidence

Bolna is the primary voice engine (D-31). The adapter (`apps/api/engine/bolna.py`) was
written largely from reasoning and said so, in blocks marked MARKED ASSUMPTION and
UNVERIFIED. This directory is where the reasoning got replaced with sources, so the next
reader inherits **evidence rather than conclusions** (CLAUDE.md, quality bar).

## The four evidence classes, and why the label is the point

A conclusion filed under the wrong class is worse than no conclusion — that is the exact
defect D-31/D-32 exist to prevent. Every fact in this directory carries one of:

| Class | Means | Worth |
|---|---|---|
| **VERIFIED-OAS** | Read in the vendor's own pinned OpenAPI document (`hosted-oas.md`). | The strongest class available without an account: first-party, versioned, machine-checkable, and about the **hosted** contract. Where it and a vendor prose file disagree, the vendor's own repo says the spec wins. |
| **VERIFIED-VENDOR-REPO** | Read in a prose file of `bolna-ai/skills` — the SKILL.md set and `references/`. | First-party and current, but prose. Carries operational facts the spec has no slot for: rate limits, webhook retry behaviour, source IP, provider matrix. |
| **VERIFIED-OSS** | Read at source in `bolna-ai/bolna`, the open-source self-hosted framework. | Authoritative for how the engine **behaves** — call flow, transcript construction, config validation. **Not proof of the hosted REST contract, and demonstrably misleading about it**: its one-shot webhook delivery is where this repo's false "webhooks are at-most-once" claim came from (D-352). Ranks BELOW the two above. |
| **STILL UNVERIFIED** | Needs a live account. | Nothing. Each one is a named gate in OPERATIONS §2. |

`REPORTED-DOCS` — "from a WebSearch result summary quoting the hosted docs" — is
**retired** (D-350). Everything it used to carry is now readable first-hand in the two
first-party repositories above, and a search snippet is not evidence when the document
itself is one `curl` away.

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

## Network constraint under which this was gathered — and the mistake it covered for

`docs.bolna.ai`, `www.bolna.ai`, `docs.bolna.dev` and `api.bolna.ai` are all refused by
this environment's egress proxy (gateway 403 on CONNECT, for `curl` and `WebFetch` alike).
That is still true, re-measured 18 Aug 2026, and it is why every LIVE gate in OPERATIONS §2
remains open.

**What it does not excuse (D-350).** This section previously concluded "no hosted
documentation page in this repository has been read by anyone here", and thirty-one places
in the tree turned that into "Bolna publishes no OpenAPI spec". The vendor publishes a
full OpenAPI 3.1.0 document — on GitHub, which is reachable, and which this very directory
proves is reachable. A blocked HOST was allowed to stand in for an absent DOCUMENT. Before
filing any vendor fact as UNVERIFIED, check whether the vendor publishes it somewhere else
you can reach: their GitHub org, their SDK packages, PyPI, npm.

## Files

| File | What it holds |
|---|---|
| `hosted-oas.md` | **VERIFIED-OAS.** The hosted OpenAPI spec: where it is, its checksum, the complete endpoint inventory, and the facts it settles. Pinned to `bolna-ai/skills@28b24aa`. Read this first. |
| `oss-harvest.md` | VERIFIED-OSS facts, each with the file it was read in. Pinned to `bolna-ai/bolna@cd2e192600ae94daeeb627d26c604b69cfc50de4`. |
| `hosted-reported.md` | The retired REPORTED-DOCS harvest, kept for provenance. Where it and `hosted-oas.md` disagree, `hosted-oas.md` wins. |

The reconciliation — every assumption, its evidence class, and what changed in the code —
is `docs/evidence/vendor-bolna-reconciliation.md`.
