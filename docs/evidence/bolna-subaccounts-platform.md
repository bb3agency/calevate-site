# Bolna sub-accounts, concurrency, and the platform surfaces we have never heard of

**Audit date:** 20 Aug 2026 · **Evidence:** `bolna-findings/mirror/` (335 pages, mirrored
from `www.bolna.ai/docs/**`, 334 × 200 + one 404 on `api-reference/openapi.yml`) ·
**Scope read end to end:** `api-reference/sub-accounts/` (7), `graph-agent/` (17),
`cli/` (29), `build-with-ai/` (14), `sdks/web-call.md`,
`developer-resources/overview.md`, `agents-library.md`, `clone-voices.md`,
`import-voices.md`, plus `enterprise/` (8) and `pricing/` (3) for the concurrency question.

Every claim below cites a mirror path and quotes the line. Where the mirror does not
settle a question, this document says so instead of guessing — three of this repo's
decision-log entries (D-31, D-32, D-350) exist because vendor prose was once read as
specification.

> ### ⚠ THE EVIDENCE TREE WAS NOT IMMUTABLE — ROOT-CAUSED AND FIXED
>
> `bolna-findings/mirror/MANIFEST.json` records a `sha256` for all 335 fetched pages, which
> is the whole point of a mirror: it is supposed to be a fixed artefact a claim can be
> pinned to. **15 of the 335 were found off their recorded hash during this audit.**
>
> **Root cause: `ruff format` formats Python code blocks inside Markdown, and the evidence
> tree was inside ruff's file discovery.** So `uv run ruff check --fix . && uv run ruff
> format .` — the exact command CLAUDE.md's own Commands section tells every contributor
> and every agent in this wave to run — rewrote the vendor's code samples in place: quote
> normalisation, blank lines inserted between top-level defs, dict literals exploded across
> lines. Verbatim vendor evidence, silently restyled to our house rules, in a tree eight
> other lanes were citing at the same time.
>
> **Fixed in `pyproject.toml`:** `bolna-findings` added to `[tool.ruff] extend-exclude`,
> **plus `force-exclude = true`** — which is the half that actually matters, because ruff
> honours exclusions when walking a directory but ignores them for paths passed explicitly,
> and `.pre-commit-config.yaml` runs `ruff-format` as a hook, i.e. always with explicit
> paths. Without `force-exclude` the exclusion reads correctly and does nothing on every
> commit.
>
> **Guarded in `tests/vendor_evidence_guard_test.py`**, three assertions: the manifest still
> describes a populated tree (so the guard cannot pass vacuously), no page has drifted from
> its hash, and the formatter reports "No Python files found" when pointed straight at the
> mirror. Sabotage-verified in all three directions.
>
> **State at the end of this audit:** eight of the fifteen were restorable from git and a
> concurrent lane restored them while this was being written. **Seven remain mismatched at
> HEAD** — committed that way, so no working-tree revert reaches them — and are carried in
> the guard as an equality ledger that fails both on an eighth break and on an unrecorded
> repair:
>
> ```
> api-reference/agent/get_all_agent_executions.md     api-reference/executions/get_batch_executions.md
> api-reference/agent/v2/get_agent_execution.md       api-reference/executions/get_execution.md
> api-reference/agent/v2/get_all_agent_executions.md  api-reference/executions/get_executions.md
> api-reference/batches/executions.md
> ```
>
> They were recorded rather than repaired because two causes were thought to be mixed in
> and only the mirror's owner could separate them: a whitespace-only diff inside a code
> fence would be the formatter and the page should be restored from the vendor, while a
> prose diff might be a genuine re-fetch, in which case the page is right and the manifest
> entry is the stale half. All seven are execution/listing pages — the area several lanes
> of this wave were working in at once — which was worth knowing before assuming a single
> cause.
>
> #### ✅ SETTLED 22 Aug 2026 (A2 audit): the seven are NOT formatter damage, and the
> #### remedy above would have been harmful
>
> The measurement above stands — 15 pages were off their hash, and the ruff root cause and
> its fix are real for the eight that were restored. **The remaining seven have a
> different and entirely benign cause**, and it is settled rather than suspected:
>
> - `bolna-findings/` has exactly **one** commit, `5e18585` (20 Aug 2026, bb3agency),
>   titled *"fetched bolna docs md files (redacted example Twilio SIDs)"*, and
>   `git diff 5e18585 HEAD -- bolna-findings/` is **empty**. Nothing has edited the mirror
>   in-tree, ever — so the formatter, which ran during this audit wave, cannot be the cause
>   of a mismatch that has existed since the tree landed.
> - All seven are **exactly** their manifest byte length — seven files, zero delta. A
>   formatter does not preserve byte counts.
> - The seven are **exactly and only** the pages containing `AC` + 32 `X`, twice each: a
>   width-preserving redaction of a Twilio **Account** SID (`AC` + 32 hex) inside the
>   example recording URL `…s3.us-east-1.amazonaws.com/AC…/RE…`. No other page in the
>   mirror carries that token.
> - **Six of the seven contain no Python code fence at all**, and ruff formats Python
>   blocks. There was nothing in them for it to rewrite.
>
> **Consequence for citations: none.** The redaction substitutes within a line and adds no
> newline, so every `page:line` citation into these seven resolves to the line it always
> did. Re-resolved by hand this audit: `docs/evidence/bolna-response-contract.md:557` →
> `get_execution.md:285-294` (the `to_number`/`from_number` declaration — correct) and
> `docs/evidence/bolna-tools-integrations.md:124` → `get_agent_execution.md:270-328` (the
> `TransferCallData` block — correct, and it spans redacted line 316 without depending on
> it). `docs/evidence/bolna-executions-cost.md:466` already wrote `<redacted example SID>`.
> The `us-east-1` recording-residency finding also survives intact: the region label sits
> outside the redacted span.
>
> **The recorded remedy was the dangerous half.** "Restore them from the vendor" would
> re-insert a live vendor account identifier into a tracked file — the exact thing commit
> `5e18585` removed on purpose. And the seven can never be repaired to match the manifest,
> because the redacted SIDs are 32 hex characters that no longer exist anywhere.
>
> **What was actually wrong, and is now fixed.** `tests/vendor_evidence_guard_test.py`
> recorded the seven as `KNOWN_HASH_MISMATCHES`, a set of **paths** — which pins *that*
> they mismatch and nothing whatever about their bytes. So the seven pages two evidence
> documents cite by line number were the only seven in the mirror that a change could edit
> in silence. Demonstrated before the fix: a same-length edit inside `get_execution.md`
> left every assertion in that file green.
>
> That set is now `REDACTED_PAGES`, a table carrying each page's **as-fetched** hash (from
> the manifest, duplicated deliberately so doctoring one does not doctor the other), its
> **as-committed** hash, and its byte size — plus `REDACTION`/`REDACTION_COUNT`, so
> un-redacting a page fails with its own message instead of reading as a generic hash
> mismatch. Two further assertions were added: every non-redacted page must still match the
> manifest, and `llms.txt`/`llms-full.txt` — which `scripts/fetch_bolna_docs.py` writes
> **without** adding a manifest record at all — are pinned there because nothing else in
> the tree hashes them. Sabotage-verified in four directions.
>
> The manifest itself is **not** regenerated and the mirror is **not** edited: the manifest
> records what the vendor served, which is the one fact no later process can reconstruct.
>
> **No claim in this document rests on a mutated file.** Exactly one of the fifteen fell in
> this lane, `graph-agent/event-injection.md`, and its change was whitespace only
> (`git diff -w` empty), so the quoted prose is byte-identical; it has since been restored.
> Every sub-accounts, enterprise, pricing, CLI, build-with-ai, SDK and voice page cited
> below matches its recorded hash.

**What this audit changed in the tree**, all of it small and none of it in another lane's
files:

- `pyproject.toml` + `tests/vendor_evidence_guard_test.py` — the evidence mirror was being
  silently rewritten by our own formatter. Root cause, fix and guard in the box above.
- `runbooks/campaign-stall.md` §3a and §4a — operator procedure for the concurrency
  findings (§2.6, §2.7) and for the starvation mode in §2.3. No behaviour change.

**What it deliberately did NOT change.** The headline finding (§2.3) is a dispatcher
fairness defect whose durable fix is a plan-level commercial decision this lane was told
not to make; the two capability gaps (§2.6, §8) live in `packages/shared/.../engine.py`,
which Lane B owns. Both are recorded with the mechanism named rather than half-fixed.

---

## 1. Sub-accounts — the gate 10 answer

### 1.1 Are they Enterprise-gated?

**On the documentation side the answer is unanimous, and it is yes.** Eight independent
pages say so, five of them inside the API reference itself:

- `bolna-findings/mirror/pages/api-reference/sub-accounts/overview.md:10` —
  "This is an `enterprise` feature." (identically at `create.md:10`, `get_all.md:10`,
  `usage.md:10`, `all_usage.md:10`)
- `bolna-findings/mirror/pages/enterprise/sub-accounts.md:16` — "Sub-accounts is an
  Enterprise feature."
- `bolna-findings/mirror/pages/concepts/security.md:79` — "**Enterprise plans** support
  **sub-accounts**"
- `bolna-findings/mirror/pages/enterprise/concurrency-management.md:26` — "Concurrency
  management applies to organizations with sub-accounts, an Enterprise feature."
- `bolna-findings/mirror/pages/build-with-ai/mcp-tool-list.md:113` — "Enterprise feature —
  isolated workspaces with their own auto-provisioned API key (`sa-...`)"
- `bolna-findings/mirror/pages/getting-help.md:48` — routes "Enterprise plan,
  sub-accounts, on-premise deployments, data residency, custom pricing" to
  `enterprise@bolna.ai`

Two of the seven sub-account API pages carry **no** enterprise note —
`patch_update.md` and `delete.md`. That is an omission in their docs, not a second
answer: both restrict the operation to organization admins
(`patch_update.md:16` — "Only **organization admins** can update sub-accounts"), and an
organization is itself gated (`enterprise/organization.md:16` — "This is an Enterprise
feature.").

**The discrepancy gate 10 was chasing is NOT resolved by this mirror, and the gate text
should stop implying it can be.** The mirror covers `www.bolna.ai/docs/**` only — all 335
manifest URLs are under `/docs/` — and the claim on the other side of the contradiction
lives on the marketing pricing page at `bolna.ai/pricing`, which is not a docs URL and is
not mirrored. The docs even link out to it as a separate surface
(`pricing/call-pricing.md:110` — "Explore pay-as-you-go, **pilots**, and enterprise
plans"), confirming a Pilots tier exists while saying nothing about what it contains. So:
**the docs half of the contradiction is now settled and unanimous; the pricing-page half
is unread.** Someone must open `bolna.ai/pricing` in a browser, or ask
`enterprise@bolna.ai` directly.

### 1.2 What does it cost?

**No price appears anywhere in the mirror** — not in `enterprise/plan.md`, not in
`pricing/call-pricing.md`, not on any sub-account page. Every route ends at a human:
`enterprise/plan.md:45` — "reach out to us at enterprise@bolna.ai … for a customized
quote based on your requirements."

Worth flagging for whoever opens that negotiation: **`enterprise/plan.md`'s own list of
what Enterprise includes does not mention sub-accounts.** It names four things — elevated
concurrency (`:15`), priority processing (`:19`), Slack support (`:23`), volume discounts
(`:27`) — and sub-accounts is not among them, even though eight other pages point at this
page as the authority for the gating. Do not assume sub-accounts arrive with an Enterprise
contract; name them explicitly as a deliverable.

The same SKU carries two other things we already want, which is a negotiating asset rather
than three separate asks: **India data residency** (`enterprise/data-residency.md:17` —
"Data residency is an Enterprise feature", and `:12` — "**By default, all Bolna AI
services operate in United States (US)-hosted infrastructure**", which is gate 9's
subject) and **elevated concurrency** (gate 13's). Gates 9, 10 and 13 all terminate at the
same email and the same contract.

### 1.3 What a sub-account IS, and what it is not

| Property | Evidence |
|---|---|
| **Not a user.** A logical container, addressed by an API key. | `enterprise/sub-accounts.md:90` — "Sub-accounts are **not users** — they act as logical containers for agents, call logs, and usage separation." |
| **Key is auto-provisioned, `sa-` prefixed, and the sub-account cannot manage its own.** | `enterprise/sub-accounts.md:78` — "Sub-accounts themselves cannot generate or manage API keys."; `create.md:170` — `pattern: ^sa-[a-f0-9]{32}$` |
| **Isolation is agents + call logs. Phone numbers and providers stay shared.** | `enterprise/sub-accounts.md:100-101` — "isolation at the **agents and call logs** level. Shared resources such as **phone numbers and providers** remain available at the organization level" |
| **Billing consolidates at the org; visibility is per sub-account.** | `enterprise/sub-accounts.md:85` — "Billing is consolidated at the **organization level**, but with granular visibility into sub-account consumption" |
| **Only org admins create/update/delete; sub-account members cannot touch concurrency.** | `create.md:15`, `concurrency-management.md:119` |
| **Delete is total and irreversible.** | `delete.md:10` — "This deletes **ALL** the data for that sub-account's batches, executions and agents." |
| **Optional physically separate database per sub-account.** | `create.md:117-145` — `multi_tenant: boolean` plus `db_host`/`db_name`/`db_port`/`db_user`/`db_password` |

That last row deserves a sentence of its own. `multi_tenant: true` asks us to hand Bolna
**a database host, root user and root password** (`create.md:145` — `db_password …
description: Database root password for multi_tenant sub-account`) which they then store
and use. For a DPDP-bound product that is a data-processor arrangement of a completely
different shape from "we call their API", and the field is `db_user: … Database **root**
user`. If sub-accounts are ever adopted, `multi_tenant` stays `false` (its default) unless
somebody has done a full processor assessment. Not a decision to make by leaving a flag at
its default without noticing it exists.

### 1.4 Would per-sub-account usage feed our metering?

Partly, and less than it first looks.

`GET /sub-accounts/{id}/usage` and `GET /sub-accounts/all/usage` return, per sub-account:
`total_records`, `total_duration` (seconds), `total_cost`, `total_platform_cost`,
`total_telephony_cost`, a `status_map` of call outcomes, and per-provider breakdowns
`synthesizer_cost_map` / `transcriber_cost_map` / `llm_cost_map` including token counts
(`usage.md:93-197`). `all_usage.md` adds `sub_account_id` and `sub_account_name`
(`:159-165`).

Four things to be clear-eyed about before treating this as a metering source:

1. **The unit is cents, stated four times.** `usage.md:106` — "Total cumulative cost of
   executions **in cents**", and identically on `total_platform_cost` (`:111`) and
   `total_telephony_cost` (`:116`). This is a **third** first-party statement on the
   money-unit question gate 7 raised, and it agrees with the OpenAPI spec and with our
   adapter's `_ASSUMED_MINOR_UNITS_PER_MAJOR`. It does **not** close gate 7 — three
   documents saying cents is still not an observation of a server, and gate 7's test (one
   call, `total_cost` beside the dashboard charge) is unchanged.
2. **Cents of what currency is not stated.** No currency field appears anywhere in either
   usage schema. Gate 7's "record whether ANY currency field appears in the payload"
   applies here identically.
3. **The window is capped at 32 days.** `usage.md:36` — "Track usage for the sub-account
   upto 32 days". A monthly invoice fits; a re-derivation of an older period does not.
4. **It is a vendor-side aggregate, not a per-call ledger.** Our `usage_events` is an
   append-only per-call ledger with our own `unit_cost_paid` (hard rules 4 and 7). This
   endpoint would be a **reconciliation** input — vendor total vs our total for a tenant
   for a month — which is genuinely valuable and is a thing we cannot do at all today, but
   it is not a replacement for anything.

**Verdict on the metering question:** per-sub-account usage would give us a per-tenant
vendor-side control total we currently have no way to obtain. Today every tenant's spend
sits in one undifferentiated Bolna account and the only per-tenant attribution that exists
anywhere is ours (`engine_agent_routes` maps `(engine, engine_agent_ref) → tenant_id`).
That is a real reconciliation gap, and it is the second-strongest argument for
sub-accounts after §2.

### 1.5 Contradictions found in the vendor's own docs

Recorded rather than resolved, because two Bolna pages disagree and neither is
self-evidently the newer:

- **Does a sub-account have its own wallet?** `concepts/security.md:79` says "Each
  sub-account has its own agents, **phone numbers**, **wallet balance**, and API keys."
  Both halves of that are contradicted by the enterprise page:
  `enterprise/sub-accounts.md:101` says phone numbers "remain available at the
  organization level", and `:85` says "Billing is consolidated at the **organization
  level**"; `enterprise/organization.md:60` says "The organization's balance is shared
  across all users … deducted from this single, centralized balance." Three pages to one.
  **If we ever price sub-accounts as per-client prepaid wallets, this must be confirmed
  first** — the majority reading says there is one balance and one client can spend
  another's.
- **The sub-accounts API overview lists three endpoints and there are six.**
  `api-reference/sub-accounts/overview.md:17-19` lists only `POST /sub-accounts/create`,
  `GET /sub-accounts/all`, `GET /sub-accounts/:id/usage`. The sibling pages document
  `PATCH /sub-accounts/{id}`, `DELETE /sub-accounts/{id}` and
  `GET /sub-accounts/all/usage` as well. The overview page is stale; the per-endpoint
  pages are the ones to read.

---

## 2. Concurrency — the one with teeth

### 2.1 The vendor's model, stated exactly

An organization holds **one shared outbound pool** across its main account and every
sub-account:

> "**Organization maximum** — the hard ceiling on total simultaneous outbound calls across
> the main account and every sub-account combined. The organization never exceeds this."
> — `enterprise/concurrency-management.md:33`

Each account inside it carries a **floor** and an optional **cap**:

> "`min_concurrency` | Guaranteed floor for the account | `0` means no guarantee …
> `max_concurrency` | Hard cap for the account | Omit (or `null`) for **elastic** … `0`
> **pauses** the account" — `enterprise/concurrency-management.md:42-43`

And the allocation algorithm is published in four steps
(`enterprise/concurrency-management.md:51-67`):

1. "Every account is brought up to its guaranteed minimum before any spare capacity is
   handed out. Calls already in progress are never dropped to make room."
2. "Whatever is left in the organization pool is shared among the accounts that still have
   calls waiting, **in proportion to their guarantees**"
3. "A capped account bursts up to its `max_concurrency`; an elastic account (no max) can
   keep climbing until the organization pool is full."
4. "Calls that don't fit this cycle stay queued and dial automatically as in-flight calls
   finish. **Inbound calls are never queued.**"

Over-subscription is refused at configure time, not at dial time
(`concurrency-management.md:91-93`): the sum of minimums may not exceed the org minimum,
the sum of *capped* maximums may not exceed the org maximum (elastic accounts are not
counted), and per account `min ≤ max`. A violation is a `400` naming the sum
(`create.md:78` — "Sum of account minimums (60) exceeds the org minimum (50) by 10").

Baseline tiers, for scale: "Trial accounts — Up to **2 concurrent calls**", "Paid accounts
— Starts at **10 concurrent calls**, scaling automatically with monthly usage", "Inbound
calls — **No concurrency limits**" (`pricing/outbound-calling-concurrency.md:14-28`).

### 2.2 So: is the pool shared, and have we modelled it?

**Shared: yes. Modelled: yes — the parent's feared gap is not present.**
`apps/workers/campaign_dispatch.py:5-9` states the doctrine and the tick enforces it:

```
1. `platform_lines_total` (engine verification item 8, a config value for now)
2. minus `inbound_reserve` (default 30%, min 4 lines) → the OUTBOUND pool
3. per-tenant `concurrency_ceiling` (plans row, default 10)
4. per-campaign slider ≤ tenant ceiling
```

`_run_tick` computes `global_budget = max(0, pool - total_active)` platform-wide and
refuses to spend past it. So "one client's campaign starves another's inbound
receptionist" is a risk this repo already saw and already priced in.

What the mirror *does* falsify is four narrower things, and one of them is severe.

### 2.3 Finding A — we have caps, no floors, and the spend order never rotates. **SEVERE.**

This is the headline, and it is ours, not the vendor's.

Bolna's model is floor + cap. Ours is cap only: `plans.concurrency_ceiling` is a maximum,
and there is no column anywhere that guarantees a tenant a minimum. Worse, the shared
budget is spent **in a fixed order that is the same on every tick**:

- `_run_tick` builds `running` by walking `_tenants_with_work()` and then spends
  `global_budget` down that list, `break`ing when it reaches zero
  (`apps/workers/campaign_dispatch.py`, the loop at "Rule 1+2: what is left of the shared
  pool").
- `_tenants_with_work()` reads `dispatch_scan()`, whose plpgsql body is
  `FOR t IN SELECT DISTINCT r.tenant_id FROM engine_agent_routes r **ORDER BY 1** LOOP`
  (`alembic/versions/a8d4f21c9b06_*.py:142`).
- `tenant_id` is **uuid_v7**, which is time-ordered.

Therefore, under a saturated pool, the dial order is **oldest tenant first, on every tick,
forever**, and the newest tenant is served last every time. There is no rotation, no
proportional share, and no floor to fall back on. Client #12's campaign can be starved
indefinitely by clients #1–#3 while every tick reports a healthy `dialled=N`.

It is not hypothetical at pilot scale: the shipped constants are
`PLATFORM_LINES_TOTAL = 10` with `MIN_INBOUND_RESERVE = 4`, so the entire platform's
outbound budget is **6 lines**, while `DEFAULT_CONCURRENCY_CEILING` is **10** — a single
tenant's cap exceeds the whole pool. The first tenant in UUID order with a running
campaign and a slider ≥ 6 takes all of it.

**Why this is reported and not fixed here.** The durable fix is Bolna's own design — a
per-tenant guaranteed floor plus proportional sharing of the surplus — and a floor is a
plan field: it is a commercial promise ("your receptionist always has N lines"), it needs
a `plans` column with its migration and RLS, and it needs an admission rule that the sum
of floors cannot exceed the pool (exactly the `400` the vendor returns). That is a founder
decision with pricing consequences, which this lane was told not to make. The narrower
engineering-only patch — rotating the spend order — was considered and **rejected**: it
would be a second mechanism that the real fix has to remove, and this repo's standard is
one way per problem, migrate rather than accumulate. `runbooks/campaign-stall.md` §4a now
tells an operator how to recognise the symptom and what to do in the meantime.

**The reference algorithm to implement, when the floor lands**, is
`enterprise/concurrency-management.md:51-67` quoted in §2.1: floors first, surplus shared
in proportion to floors, capped per account, remainder queued. It is the established
answer to this exact problem, published by the vendor whose scheduler we sit in front of,
and matching it also means our two layers cannot disagree about who deserves capacity.

### 2.4 Finding B — the inbound reserve may be defending against a risk the vendor says does not exist

`docs/FLOWS.md:269-271` justifies `inbound_reserve` as "one client's campaign must never
starve another's inbound receptionist", and notes "the platform has no native
reserved-inbound feature". The second half is **confirmed** — there is no inbound
reservation setting anywhere in the mirror. The first half is **contradicted twice**:

> "**Inbound calls are never queued.**" — `enterprise/concurrency-management.md:66`

> "Inbound calls — **No concurrency limits** - inbound calls are never restricted or
> queued." — `pricing/outbound-calling-concurrency.md:26-28`

and the org envelope itself is scoped to outbound only ("total simultaneous **outbound**
calls", `:33`). On the documented contract, outbound cannot starve inbound because they do
not draw on the same admission control at all.

**What it costs us if true:** at the shipped constants the reserve is 4 of 10 lines, so
removing it takes the outbound pool from **6 to 10 — a 67% throughput increase, free.**

**Do not act on this from prose.** It is precisely the class of claim D-31/D-32/D-350
exist for, and "never restricted" is a statement about admission control that may not
survive contact with a saturated media plane. It belongs in gate 13 as an observation to
make during the pilot: hold N outbound calls at the ceiling and place an inbound call to a
platform number. Proposed wording in §11.

### 2.5 Finding C — capacity splits evenly per telephony provider, and our dispatcher has no notion of a provider. **UNMODELLED.**

> "**An account's capacity is split evenly across its providers.** Dialing is not
> first-come-first-served across an account's whole queue: its share of the pool is
> divided equally between the providers it has calls waiting on, and any share a provider
> can't use passes to the others." — `enterprise/concurrency-management.md:73`

With the worked example: "an account allowed 700 concurrent calls with 15,000 calls queued
on one provider and 15,000 on another runs 350 on each" (`:77`).

Our dispatcher computes one pool and one budget. It does not know which telephony provider
a contact's number will dial out on. The moment we run two — and the plan does; Plivo and
Vobiz both appear in Bolna's own India number set
(`build-with-ai/skills-reference.md`, `manage-phone-numbers` — "Search and buy US (Twilio)
or India (**Plivo, Vobiz**) phone numbers") — our effective concurrency on each is **half**
our ceiling while both have calls waiting. A 6-line pool becomes 3+3, and a campaign that
our arithmetic says will finish in an hour takes two.

There is a mitigating clause: "any share a provider can't use passes to the others"
(`:73`), so the split only bites when both providers have queued work. That is exactly the
case a busy evening produces.

**This one is ours and it is engineering, not commercial** — but it is not actionable until
gate 13 establishes how many providers we actually dial through, which is a pilot fact.
Recorded here and proposed as gate 13 text in §11.

### 2.6 Finding D — `PLATFORM_LINES_TOTAL` is typed in, and the vendor publishes it

`apps/workers/campaign_dispatch.py` holds `PLATFORM_LINES_TOTAL = 10` as a constant, and
`docs/DATA-MODEL.md:420-428` records the reasoning: the `engine_capacity` table is "NOT YET
CREATED", the constant is "deliberately a constant until the pilot produces real numbers,
so the measured value has exactly one place to land."

**The pilot is not needed for this number.** Bolna publishes it on a read endpoint:

> `GET /user/me` → `concurrency: { max: … "Maximum concurrency limit for the user
> account", current: … "Current concurrent calls from the user account" }`
> — `bolna-findings/mirror/pages/api-reference/user/info.md`, schema `User`

I reached this from my own lane: the CLI's `bolna whoami` prints "Concurrency   3 / 10
calls" (`cli/commands/whoami.md`) and states it "Maps to the `get_user_info` MCP tool",
which `build-with-ai/mcp-tool-list.md:` maps in turn to `/docs/api-reference/user/info`.

Two things follow:

- **`concurrency.max` should be read, not typed.** The tier moves without a deploy — "Paid
  accounts — Starts at 10 concurrent calls, **scaling automatically with monthly usage**"
  (`pricing/outbound-calling-concurrency.md:18`) — so a correct constant decays into a
  wrong one silently.
- **`concurrency.current` is a free cross-check on our own arithmetic.** Our `total_active`
  is derived from our `calls` table; the vendor's `current` is derived from theirs. A
  persistent gap is stranded rows, which is the exact condition
  `runbooks/campaign-stall.md` §3 sends an operator hunting for by hand.

**Why not wired here:** it needs a method on the `VoiceEngine` Protocol in
`packages/shared/src/calevate_shared/engine.py`, which is Lane B's file, plus a `fake`
implementation and a conformance case. Handing it over rather than reaching across.
Suggested shape: `async def get_account_capacity(self) -> EngineCapacity` returning a
normalized `(max_concurrent, current_concurrent, wallet_balance)` — normalized because
hard rule 2 says nothing outside `apps/api/engine/` may see a vendor payload, and the
dispatcher is in `apps/workers/`.

### 2.7 Finding E — over-limit outbound is QUEUED by the vendor, and that makes our global budget a compliance control

Gate 13 asks for "behavior at the limit (queue vs reject + error shape)". The docs answer
it, twice:

> "Outbound calls that don't fit your concurrency limit are **queued, not rejected**. They
> dial automatically as active calls finish, so a batch or campaign larger than your limit
> still runs end to end — it just paces itself."
> — `pricing/outbound-calling-concurrency.md:41`

> "Calls that don't fit this cycle stay queued and dial automatically as in-flight calls
> finish." — `enterprise/concurrency-management.md:66`

This is not a convenience. **If `PLATFORM_LINES_TOTAL` is ever set HIGHER than the account's
real ceiling, the failure is silent and lands on compliance, not throughput.** We would
hand Bolna more calls than it can run; it accepts all of them and queues the surplus; the
tick reports a healthy `dialled=N`; and the surplus dials later, from a vendor-side queue
we cannot see, cancel, or DNC-scrub. `compliance.service.check_dispatch` — the per-contact
gate that enforces the DNC list, the tenant's cap and the calling hour — runs at **dispatch**
time. A contact cleared at 20:55 IST and queued at the vendor can be dialled after 21:00,
outside the TRAI window that gate exists to enforce, with our own records showing it was
lawfully cleared.

The mitigation is what the dispatcher already does: stay under the pool. What changes is
the **status** of that arithmetic — it is not an optimisation, it is the calling-hours
control — and therefore the status of Finding D: reading the real ceiling from the vendor
is a compliance requirement, not a nicety. Written into `runbooks/campaign-stall.md` §3a.

One related fact worth having on file: a per-agent kill switch exists for exactly this
situation. `stop_agent_queued_calls` — "Cancel every queued or scheduled call for one
agent" (`build-with-ai/mcp-tool-list.md`, → `POST /v2/agent/{id}/stop`) — is the vendor-side
lever if the big red switch is ever thrown while a vendor queue is holding our calls.
Whether our big red switch reaches it is a question for the compliance lane, not this one.

### 2.8 Finding F — BYOT SIP does **not** buy independent capacity

TRD §10's effective pool is `MIN(platform lines, model concurrency, trunk channels)`, which
reads as though a SIP trunk is an independent ceiling. Two clauses say otherwise:

> "**Your own provider credentials don't share capacity.** Calls placed on an account's own
> provider account are limited by that account's guarantee and cap alone — never by how
> busy the provider is for other Bolna customers."
> — `enterprise/concurrency-management.md:75`

> "[SIP trunking (BYOT)](/docs/sip-trunking/introduction) is **the exception** to the point
> above: those calls run on **Bolna's SIP infrastructure**, so they **share platform
> capacity** even though the trunk is yours." — `enterprise/concurrency-management.md:80`

So the exemption applies to **API-key providers** (our own Twilio/Plivo/Exotel credentials),
**not** to a SIP trunk. If we take the Exotel/Vobiz SIP route, trunk channels are a *fourth*
constraint stacked on top of the platform ceiling rather than a way around it, and the MIN()
is still bounded by `concurrency.max`. Relevant to gate 13's "ask Exotel/Vobiz (SIP trunk
channels)" — the answer they give is a ceiling, not a bypass.

---

## 3. The gate 10 decision, stated but not made

Not this lane's call. What the evidence establishes, so the founder is choosing between
real options:

**For adopting sub-accounts as our per-tenant boundary:**
- Per-tenant vendor-side usage totals we have no other way to obtain (§1.4) — the first
  real reconciliation source for the money path.
- Per-tenant **guaranteed floors** at the vendor (`min_concurrency`), which is the thing
  our plans model cannot express at all (§2.3) — and adopting it would push the fairness
  problem down to a scheduler that already solves it.
- Vendor-native tenant attribution instead of our `engine_agent_routes` bridge.
- Independent audit trails per client (`enterprise/sub-accounts.md:111`), which is a
  DPDP-friendly story to tell a client.

**Against:**
- Enterprise SKU, unpriced, human-gated (§1.2) — it is not available to buy today, which
  makes it an external blocker in the CLAUDE.md sense (a signed commercial term), not an
  engineering task.
- Isolation is partial: phone numbers and providers stay org-level
  (`enterprise/sub-accounts.md:101`), so it does not isolate the thing a TRAI/DLT
  regulator cares most about — the calling number and its header registration.
- One shared balance (§1.5), on the majority reading.
- N sub-accounts means N API keys to store, rotate and scope in our secrets manager, and a
  key-per-tenant blast radius that our single-key model does not have.
- Our RLS-in-Postgres tenancy is unaffected either way. Sub-accounts would be a *second*
  tenancy boundary layered on the first — two ways to answer "which client is this?" — and
  this repo's standard says migrate rather than accumulate. Adopting them means moving
  `engine_agent_routes`' job to the vendor, not running both.

**The one question that would decide it quickly:** is `min_concurrency` available *only*
with sub-accounts, or can an Enterprise organization set a floor on its main account alone?
`concurrency-management.md:45` says "The main account and each sub-account each carry their
own pair of values", which suggests the main account has a floor too — but with one account
there is nothing to be guaranteed *against*. If per-tenant floors are the reason to buy,
that is the sentence to get in writing.

---

## 4. Graph agents — **not ours.** One follow-up worth taking.

17 pages read. The verdict is no, and the reasons are specific rather than
not-invented-here.

**What it is:** a node-based flow replacing one large prompt. Nodes carry their own prompt
and `edges`; a routing LLM picks an edge after each user turn, unless a deterministic
expression or unconditional edge matched first — "Expression and unconditional edges are
evaluated **before** the routing LLM runs. If a deterministic rule matches, the transition
fires instantly with zero latency and zero cost" (`graph-agent/introduction.md`). It ships
with a visual editor, a validator that blocks saving on 11 error classes
(`graph-agent/validation.md`), server-side version history on every save
(`graph-agent/version-history.md`), import/export as JSON (`graph-agent/import-export.md`),
router nodes, static nodes, and a REST event-injection endpoint
(`POST /v1/call/{run_id}/events`, `graph-agent/event-injection.md`).

**Why not ours — four reasons, in descending force:**

1. **It introduces a SECOND in-call LLM leg whose default provider is outside India.**
   "`routing_provider` | Provider for the routing LLM. **Defaults to `groq` when a Groq key
   is configured, otherwise `openai`**" and "`routing_model` | … Defaults to
   `gpt-4.1-mini` on OpenAI **and Azure**, `llama-3.3-70b-versatile` on Groq"
   (`graph-agent/introduction.md:111-112`). The routing LLM is called with the caller's
   utterance on **every turn**. On a residency-bound product that is a second inference
   surface to pin, and its default is a US provider. D-410 got the in-call leg onto Azure
   South India and `agents/service.py::in_call_llm` is "the ONE place the leg is decided
   for an agent"; a graph agent would silently create a second leg that function does not
   govern. (It is *pinnable* — Azure is named as a supported routing provider, which is one
   more corroboration that Azure is first-class — but "pinnable" and "pinned" are the
   distinction that costs a DPA.)
2. **Version history is a second source of truth for prompt versions.** "Every time you
   save a graph agent, the platform creates a version snapshot"
   (`graph-agent/version-history.md`), restorable from the dashboard. We already own prompt
   versioning, and our publish path verifies the compliance floor against the engine on
   every publish and every drift sweep (hard rule 5). A vendor-side restore button that
   swaps the live graph without going through `compose_engine_prompt` is a hole in that
   floor, not a feature.
3. **It is an editor-first product.** Router nodes are "configured through the agent JSON /
   API today. Visual editor support is coming" (`graph-agent/router-nodes.md`), the
   validator is described entirely as a toolbar button, and version history has no
   documented API. Our clients never touch the Bolna dashboard — everything is provisioned
   through our console. We would be buying the substrate and rebuilding the whole UI.
4. **Nothing our vertical templates need is missing today.** Calling-hours branching
   (`recipient_data.current_hour`) we enforce in the dispatcher, where it must be enforced
   for TRAI purposes anyway; retry escalation (`_node_turns`) is prompt-level; per-node RAG
   we do through our own tool endpoint (TRD §6.2, and `graph-agent/tools-and-rag.md`
   confirms Bolna's KB is the same `vector_id` mechanism D-354 already retired for us).

**The follow-up that IS worth taking — static nodes.** The claim is specific:

> | LLM node | ~800ms (LLM + TTS + audio) | LLM tokens + TTS characters |
> | Static node | **~50ms (cached audio)** | **Zero** |
> — `graph-agent/static-nodes.md`

> "A static node pre-renders the audio for that message when the agent is saved and plays
> it back from cache at runtime. No LLM call. No TTS call. No latency."
> — `graph-agent/static-nodes.md`

and it supports per-language variants: `static_message` may be a
`{ "language_code": "text" }` map, "the platform pre-generates a separate cached clip for
each language using that language's voice" (same page).

**Every agent we ship has exactly two sentences that never vary and are spoken on every
call**: `agents.ai_disclosure_line` and `agents.recording_notice_line` (hard rule 5, D-163)
— fixed text, per agent, per language, spoken at the top of every call. That is the static
node's ideal case: same words every time, latency at the most latency-sensitive moment of
the call (the opening), and Bulbul TTS characters we currently pay for on every single
call. At scale the saving is one TTS synthesis per call, forever, plus a faster open.

**But do not reach for graph agents to get it.** The right question is whether the
non-graph agent object has an equivalent — Bolna's plain agent already has
`agent_welcome_message` (`graph-agent/full-example.md`, `agent_config.agent_welcome_message`)
and the CLI treats it as a first-class field on any agent
(`cli/commands/agents-view.md` — "Returns name, status, **welcome message**, and system
prompt"). **Whether a plain agent's welcome message is pre-cached the way a static node is,
the mirror does not say.** That is the follow-up: one question to the vendor, or one
measurement in the pilot (time-to-first-audio on an agent whose welcome message is fixed).
If the answer is no, the trade is a 750ms opening latency saving against reason (1) above,
and it is not worth it. Recorded, not guessed.

**One more thing worth extracting from these pages even though the feature is not ours** —
`graph-agent/debugging.md` states: "The response LLM only sees the **most recent 50
messages** of conversation history." That is a direct answer to gate 8's open H1 question
(TRD §6.1: "does Bolna truncate or summarise conversation history?"). It is scoped to graph
agents on its face, so it is a strong hint rather than a settled answer for simple agents —
but it is the first number anyone in this tree has had, and gate 8 should test the same
question knowing 50 is the value to expect.

---

## 5. The CLI — **not a dependency, and mostly not an operator tool either.**

29 pages read. `bolna-cli` is "a single Go binary" installed with
`go install github.com/bolna-ai/cli/cmd/bolna@latest` (`cli/installation.md`), in **beta**
— "commands and flags may still change before a stable 1.0 release"
(`cli/introduction.md`). It adds no runtime dependency to this repo (it is a developer
laptop binary, never a service), so the "no Go in this repo" rule is not even engaged.

**Two commands are genuinely useful and safe, and should be in a runbook:**

- `bolna doctor` — checks "Config directory / OS keychain / API key configured / **Bolna
  API reachable** / **API key valid** / TUI support", with `--output json` for CI
  (`cli/commands/doctor.md`). Touches no customer data. This is the fastest possible
  answer to "is it us or is it them?" during an incident.
- `bolna whoami` — "Account / Email / **Balance** / **Concurrency   3 / 10 calls**"
  (`cli/commands/whoami.md`), `--json` for scripting. It is the manual read of the two
  numbers Finding D (§2.6) says we should be reading programmatically: the account ceiling
  and the live count.

**And four are a PII or compliance hazard that no runbook should recommend:**

- `bolna calls view <execution-id>` prints **the full transcript** to the terminal
  (`cli/commands/calls-view.md` — "the complete transcript rendered as Markdown"). Our own
  rule is that transcripts default to `text_redacted` in every API response and raw text is
  available only behind a role check **plus an `audit_log` write** (hard rule 5). The
  vendor CLI reads our single platform key, which is not tenant-scoped, so any operator
  holding `BOLNA_API_KEY` can read **any client's** raw transcript with no audit row
  anywhere. It is a clean side-channel around the exact control DPDP compliance rests on.
  Same objection to the TUI dashboard's "Call Detail — Full transcript for one call"
  (`cli/dashboard/overview.md`) and to `bolna calls list -q | xargs -I{} bolna calls view {}`,
  which the docs offer as an example (`cli/commands/calls-list.md`).
- `bolna call start <agent-id> --to <number>` places a **real outbound call**, and
  `--yes` skips the confirmation (`cli/commands/call-start.md`). It runs none of our gates:
  no DNC scrub, no calling-hours check, no consent provenance, no DLT template check, no
  spend cap, and the **big red switch does not reach it**. An operator dialling an Indian
  number this way is placing an unconsented commercial call under Calevate's own TM
  registration. This must be written down as forbidden, not merely left unrecommended.
- `bolna agents update <id> --prompt @file.md --yes` rewrites an agent's **system prompt**
  at the vendor, skipping our publish path entirely — "`--prompt string` | New system
  prompt. Pass `@file.md` to read it from a file", "`--yes` | Skip the confirmation prompt"
  (`cli/commands/agents-update.md`). Hard rule 5 puts the truthful-answer floor into every
  prompt through `compose_engine_prompt` and verifies it against the engine on every
  publish and every drift sweep. A CLI prompt write is precisely the withdrawal that rule
  forbids: the drift sweep would catch it (that is what `engine_agent_routes.drift_state`
  is for), but between the edit and the next sweep the agent answers calls without the
  floor, and no `audit_log` row explains why.
- `bolna agents delete <id> --yes` "Permanently delete an agent and its history … This
  cannot be undone" (`cli/commands/agents-delete.md`), orphaning our `engine_agent_ref` and
  the routing row every inbound call depends on.

**Verdict:** worth one short block in the runbooks naming `doctor` and `whoami` as the two
sanctioned commands and `call start`, `calls view`, `agents update` and `agents delete` as
forbidden, with the reasons above. Not worth installing on any server; note also that it is
at **v0.2.0** and pre-1.0 — "any release may include breaking changes"
(`cli/versioning.md`). I have not added that block myself — `runbooks/campaign-stall.md`
§3a and §4a were in scope for the concurrency finding, but "which vendor tools may an
operator run against production" is a security-policy statement that belongs with
SECURITY-COMPLIANCE's owner rather than being asserted by a triage lane. It is the one
piece of this report that should become a written rule rather than a note.

---

## 6. MCP server and Skills — **would have answered some of this wave's questions; cannot run here.**

`mcp.bolna.ai/api/mcp`, Bearer-token auth with a `bn-` or `sa-` key, **57 tools** of which
55 proxy the REST API and 2 read the docs (`build-with-ai/mcp-tool-list.md`,
`mcp-quickstart.md`). No key is stored server-side. Source at `github.com/bolna-ai/mcp`.

**Would it have answered this wave's questions directly?** Partly — and the part it would
*not* have answered is the important one:

- **Yes** for anything read-shaped: `get_user_info` gives §2.6's `concurrency.max` in one
  call; `list_sub_accounts` and `get_all_sub_accounts_usage` would have turned §1 from
  document-reading into observation; `search_docs` / `get_doc` is exactly this audit's
  method, automated.
- **No** for CLAUDE.md's one remaining marked assumption — which credential FIELDS Bolna's
  Azure provider expects. The tool list has `list_providers` ("Telephony, LLM, transcriber,
  and TTS providers connected to the account") and `remove_provider`, and **no
  add/create-provider tool at all**. So MCP can show the shape of an Azure provider that
  already exists; it cannot tell us what to POST to create one. CLAUDE.md's plan is still
  the right one and is unchanged: `GET /providers`, then `POST /providers`, then `GET`
  again.

**What it would take:** egress to `mcp.bolna.ai` that this environment does not have, plus
a real API key — and a key with **12 destructive tools** behind it, `start_outbound_call`
and `delete_sub_account` among them (`build-with-ai/mcp.md`). If it is ever connected, it
should be with a key we are willing to see spend money, on a session where the destructive
confirmations are actually read.

**Bolna Skills** (`npx skills add bolna-ai/skills`, 19 skills,
`build-with-ai/skills-reference.md`) is the same surface as a package of assistant
instructions rather than a server. Two lines from it are useful evidence in their own
right and cost nothing to record:

- `add-provider` — "Bring your own OpenAI, Anthropic, **Azure**, ElevenLabs, Cartesia,
  Sarvam, Deepgram, Twilio, Plivo, Vobiz, or Exotel credentials". Azure named as a
  first-class BYOK provider, alongside Sarvam and both of our candidate Indian telephony
  vendors. This corroborates CLAUDE.md's `provider: "azure"` routing from a source
  independent of the provider list and the agent dropdown.
- The `bolna-ai/skills` repo is public and its `add-provider` skill must contain the exact
  Azure credential field names. **That is a plausible path to closing the marked
  assumption without a console round trip** — one file in a public GitHub repo. Flagged for
  whoever has egress; not fetched here, because a guess sourced from an unread repo is the
  same defect as a guess sourced from nowhere.

**Not adopted, nothing to install.** Worth noting for the record that `AGENTS.md`
(`build-with-ai/agents-md.md`) is Bolna's own machine-readable gotcha list and is dense with
things this tree has learned the hard way — `scheduled_at` rejects a trailing `Z` with a
500, `POST /v2/agent` returns 201 not 200, "Wait for `completed`, not `call-disconnected`",
`toolchain.pipelines` is an array of arrays. Any future adapter work should read it first.

---

## 7. Web Call SDK — **the gate 8 idea is right and is blocked on the vendor.**

`@bolna/web-call` v3.0.0, browser WebRTC to a Bolna agent (`sdks/web-call.md`).

**The interesting use — running gate 8 probes without PSTN spend — is sound in principle.**
Gate 8 measures Telugu KB retrieval quality, retrieval latency, and custom-function tool-call
p95. None of those need a telephone: they need a live call with real STT → LLM → tool →
TTS. A browser call exercises all of it and skips the telephony leg's per-minute charge.
What it would **not** cover is anything telephony-shaped — DTMF, call transfer, the Indian
number series, `telephony_data` in the execution payload, and the webhook path itself — so
it complements the pilot rather than replacing it.

**It is blocked on two things, both external:**

1. **Not enabled.** "In beta and available for any account **on request**. Reach out on
   Slack or email support@bolna.dev to have it enabled." (`sdks/web-call.md`)
2. **The endpoint is not published.** Every code sample carries the same comment —
   `// illustrative URL: swap in your actual Bolna session-mint endpoint` — against
   `https://api.bolna.ai/v1/web-call/session`, three separate times in the page. The docs
   are explicitly telling us that URL is a placeholder. There is no `api-reference` page
   for it in the mirror. **We cannot implement this without asking**, and inventing the
   route would be the guess this repo has been burned on three times.

**Verdict:** viable, cheap, and worth exactly one line in the same email as gate 12's
commercial terms and gate 9's residency terms: *"enable Web Call on our account and send us
the session-mint endpoint."* Nothing to build until that comes back. The second use — a
sales demo surface on `calevate.tech` — is real but is a marketing decision, and it would
put a live agent behind a public button with no consent capture and no rate limit, which is
its own design problem.

Two facts from this page are useful regardless of whether we ever adopt it:

- **A platform-wide global cap exists above our account cap.** The `at_capacity` error
  carries `scope` of `"global"`, `"customer"`, or `"not_enabled"`, and "`\"customer\"` means
  your account's cap, `\"global\"` means **Bolna's platform-wide cap**" (`sdks/web-call.md`,
  FAQ). Our TRD's MIN() has no term for "the vendor's whole platform is full". It is
  probably not worth modelling, but it is worth knowing it can happen and what it looks
  like.
- **The key-handling design is the one to copy if we ever build a demo surface**: the
  browser never sees the API key, the backend mints a single-use ~120s credential. That is
  the correct pattern and we should not invent a different one.

---

## 8. Voice cloning and importing — **Sarvam is not a cloning provider. Lane B's call.**

Reporting, not editing: provider constants are Lane B's.

- **Cloning explicitly supports two providers, and neither is ours.** "Choose your voice
  cloning provider: **ElevenLabs** or **Cartesia**" (`clone-voices.md`, Step 2). Sample
  requirement is 1–2 minutes of clean audio.
- **Importing does not enumerate its providers.** `import-voices.md` Step 2 says only
  "Choose your voice provider from the list", and the page's own summary line says
  "voices from external providers (**like** ElevenLabs, Cartesia)" — "like" is not a list.
  One screenshot's alt text on that page describes "the Text-to-Speech section with
  **Sarvam** provider and Add Voice button", which suggests the Add Voice affordance is
  present while Sarvam is selected but proves nothing about which providers the import
  dialog offers. **Ambiguous; reported as ambiguous.**

**Why it matters to D-36:** our TTS ladder is Sarvam Bulbul v3 (v2 = value tier), and the
documented answer to "can this client have their own brand voice?" is, on the cloning path,
**no — not without changing TTS provider for that agent**, which changes the cost model, the
Telugu quality assumption and the residency story all at once. That is a product answer
somebody will be asked for by client #1, and it should be known before it is asked rather
than discovered in the meeting. If brand voice turns out to be a real ask, the question for
Lane B is whether an imported ElevenLabs/Cartesia voice can sit on one agent while the rest
of the fleet stays on Sarvam.

---

## 9. Agents Library — not a gap, but two useful facts

`agents-library.md` publishes 15 importable templates across e-commerce, BFSI, hospitality,
recruitment, ed-tech, health-tech and real estate — which is the same territory as our
vertical templates (Front Desk, Lead Qualification, Reminders, Salon Booking all appear by
name). Not ours to adopt: our templates carry the compliance floor, the extraction schema
that drives CRM columns, and the DLT-registered template linkage, none of which a Bolna
import has.

Two facts worth extracting:

- **Not one template is Telugu.** Every entry is "English" or "English + Hindi"
  (`agents-library.md`, Quick Reference table, all 15 rows). This is the third independent
  corroboration of gate 8's premise that Telugu is not a language Bolna leads with, and it
  raises rather than lowers the odds that TRD §6.2's external-custom-function fallback is
  the route we end up on.
- **Their India test numbers are Bangalore landlines** — `+918035317400`, `+918035317449`,
  `+918035317402` and so on, i.e. the `080` STD code, not a 140- or 160-series number.
  These are free live inbound agents anyone can call. That makes them a **zero-cost Telugu
  probe**: dial one and speak Telugu, and observe what the STT and the LLM do with it,
  before spending anything on gate 8. It says nothing about their outbound number-class
  compliance in India, which remains gate 12's business.

---

## 10. Handoffs to other lanes

| Finding | Lane / file | Status |
|---|---|---|
| Bolna sends webhooks from **three** IPs, not one (`build-with-ai/agents-md.md:44`, plus five other pages) | `packages/shared/.../config.py::DEFAULT_BOLNA_SOURCE_IPS` | **Already fixed by a sibling lane as D-412** while this audit was running. Corroborated independently here; no duplicate edit made. |
| `GET /user/me` returns `concurrency.{max,current}` and `wallet` (§2.6) | Lane B — needs a `VoiceEngine` Protocol method + `fake` + conformance | Open |
| Voice cloning is ElevenLabs/Cartesia only; import providers unenumerated (§8) | Lane B — provider constants | Open |
| Graph agents' routing LLM defaults to Groq/OpenAI, not Azure (§4 reason 1) | Residency / D-410 owner — informational unless graph agents are ever adopted | Open |
| "The response LLM only sees the most recent **50 messages**" (`graph-agent/debugging.md`) | Gate 8's H1 in-call-memory question (TRD §6.1) | Open — first number we have had |
| Usage endpoints say "in cents" four more times (§1.4) | Gate 7's money-unit question | Corroborating, does not close |
| `stop_agent_queued_calls` cancels vendor-queued calls per agent (§2.7) | Compliance lane — does the big red switch reach the vendor's queue? | Open |

---

## 11. Proposed gate text

### 11.1 Gate 10 — EXACT replacement row for `docs/OPERATIONS.md` §2

*Applied 20 Aug 2026, with one addition: gate 9's BYOK finding (D-415) means the ORG-level
provider store would carry the US-routing consequence to every sub-account at once.*

Replaces the current row verbatim. The old text sent a reader to verify a discrepancy that
the mirror has now half-settled, and pointed at the wrong half.

```
| 10 H | Agency model — and the **only** mechanism that can give one client a guaranteed floor | Confirm in writing that multiple end-clients under one Bolna account is permitted. **THE TIER DISCREPANCY IS HALF-SETTLED AND THE UNREAD HALF IS THE PRICING PAGE.** Their docs are now unanimous that sub-accounts are Enterprise-only — five of the seven `api-reference/sub-accounts/*` pages, `enterprise/sub-accounts.md:16`, `concepts/security.md:79`, `concurrency-management.md:26`, `mcp-tool-list.md:113` and `getting-help.md:48` all say it, with no dissent anywhere under `/docs/` (`docs/evidence/bolna-subaccounts-platform.md` §1.1). The "Sub-accounts access under Pilots" claim lives on `bolna.ai/pricing`, which is NOT a docs URL and is NOT in the mirror — so it is unread, not refuted. Open that page in a browser, or ask. **NO PRICE EXISTS ANYWHERE IN THEIR DOCS**, and `enterprise/plan.md`'s own feature list does not mention sub-accounts at all, so name them explicitly as a deliverable rather than assuming they ride along. **WHAT WE WOULD BE BUYING, precisely:** (a) per-tenant `min_concurrency` — a GUARANTEED FLOOR, which our `plans.concurrency_ceiling` (a cap) cannot express and which gate 13's finding says we need; (b) per-sub-account usage totals with a full cost breakdown, the first vendor-side control total our metering could reconcile against. **WHAT WE WOULD NOT BE BUYING:** phone numbers and providers stay ORG-LEVEL (`enterprise/sub-accounts.md:101`), so this does not isolate the calling number or its header registration; billing consolidates at the org and the balance is shared (`enterprise/organization.md:60`), contradicted only by `concepts/security.md:79` — get the wallet question in writing before pricing any client as a prepaid sub-account. **DO NOT SET `multi_tenant: true`**: it hands Bolna a database host and a ROOT user and password (`create.md:117-145`), which is a processor arrangement of a different shape and needs its own DPDP assessment. **ONE QUESTION SETTLES WHETHER IT IS WORTH BUYING AT ALL:** can an Enterprise organization set `min_concurrency` on its MAIN account without sub-accounts? If yes, we get the floor without the second tenancy boundary. This gate also shares a contract and an email with gates 9 and 12 — Enterprise is the same SKU that carries India data residency (`enterprise/data-residency.md:17`) and elevated concurrency; negotiate them once, not three times. |
```

### 11.2 Gate 13 — proposed ADDITIONS (append to the existing row; nothing there is retired)

*Applied 20 Aug 2026, appended verbatim in substance.*

```
**FOUR THINGS THE MIRROR NOW ANSWERS OR SHARPENS (docs/evidence/bolna-subaccounts-platform.md §2).** (a) **Queue vs reject is ANSWERED: queued.** "Outbound calls that don't fit your concurrency limit are queued, not rejected" (`pricing/outbound-calling-concurrency.md:41`). That makes an over-high `PLATFORM_LINES_TOTAL` a COMPLIANCE defect and not a throughput one — the surplus dials from a vendor queue we cannot see or DNC-scrub, after `check_dispatch` has already cleared it, so a contact cleared at 20:55 IST can dial after 21:00. Confirm the queue exists and measure how long it holds. (b) **THE CEILING NO LONGER NEEDS MEASURING — IT NEEDS READING.** `GET /user/me` returns `concurrency: {max, current}` (`api-reference/user/info.md`). Record `max` and compare it to `PLATFORM_LINES_TOTAL = 10`; compare `current` against our own `calls` count in the same instant, because a persistent gap is stranded rows. Note the tier moves without a deploy: "Paid accounts — Starts at 10 concurrent calls, scaling automatically with monthly usage". (c) **DOES OUR INBOUND RESERVE BUY ANYTHING?** Two pages say inbound is never restricted or queued and the org envelope is OUTBOUND-only (`concurrency-management.md:33,66`; `pricing/outbound-calling-concurrency.md:26-28`). If true, `inbound_reserve_ratio` costs us 4 of 10 lines for nothing — the pool goes 6 → 10, a 67% throughput gain. TEST IT, do not infer it: hold N outbound calls at the ceiling and place an inbound call to a platform number; it must connect. This is a vendor-prose claim about admission control and D-31/D-32/D-350 are what happens when one is believed. (d) **HOW MANY TELEPHONY PROVIDERS WILL WE DIAL THROUGH?** "An account's capacity is split evenly across its providers" (`concurrency-management.md:73`) — two providers with queued work means HALF our ceiling on each, and our dispatcher has no notion of a provider. And BYOT SIP is NOT an independent ceiling: "those calls run on Bolna's SIP infrastructure, so they share platform capacity even though the trunk is yours" (`:80`), so trunk channels stack ON TOP of the platform limit rather than bypassing it — which changes how TRD §10's MIN() should be read.
```

---

## 12. What this audit did not read

For honesty about coverage: all 70 pages of the assigned lane were opened — the 7
sub-account pages, all 17 graph-agent pages, all 29 CLI pages, all 14 build-with-ai pages,
`sdks/web-call.md`, `developer-resources/overview.md`, `agents-library.md`,
`clone-voices.md` and `import-voices.md` — plus `enterprise/` (8) and `pricing/` (3) for the
concurrency question. `cli/autocompletion.md`, `cli/versioning.md`, `cli/changelog.md`,
`cli/dashboard/keybindings.md`, `cli/commands/{login,logout,numbers-list,batches-list,
agents-overview,agents-list,calls-overview}.md`, `build-with-ai/{mcp-prompts,
mcp-example-app,supported-assistants,installation,setup,llms-txt}.md` were read for material
facts and produced none beyond what is recorded above.

`enterprise/on-premise-*.md`, `enterprise/indian-server-configuration.md` and
`pricing/preferred-models.md` were outside this lane and are not covered here even though
the first two touch gate 9 and the third touches gate 12.

Outside the mirror and therefore outside this audit: `bolna.ai/pricing` (the unread half of
§1.1), `github.com/bolna-ai/skills` (the possible answer to CLAUDE.md's marked assumption,
§6), and `github.com/bolna-ai/mcp`.
