# The copilot as an agent — architecture and staged plan

**Status:** adopted 31 Aug 2026 (D-484). Phases 1-4 BUILT and merged the same day; phase 5
(the loop/streaming decision) remains open — see §6.
**Scope:** the in-app assistant (`apps/api/copilot/`, both realms). It does NOT change the
in-call agent, which already has this shape and is the model being copied.

> **Evidence note, up front.** `ai.google.dev`, `www.anthropic.com`, `mlflow.org` and
> `www.philschmid.de` are **egress-blocked from this container** (measured 31 Aug 2026).
> Everything below marked REPORTED comes from search-result excerpts, not the pages behind
> them. Under hard rule 11 that is good enough to *design* from and never good enough to
> pin a wire format on. The wire facts this repo actually stands on are the ones
> `apps/workers/chat.py` proves against live endpoints, and they are cited as such.

---

## 1. The gap this closes

The copilot today is a **form-filler**. One tool (`set_fields`), scoped to the current
screen, a four-turn loop, and no memory beyond the open conversation. Asked "how many leads
came in this week?" it can only answer from whatever the browser happened to put in the
SCREEN STATE block — so in practice it fills fields, and the user sees "Filled 21 fields"
when they wanted an answer.

What the product needs is an assistant that can:

| | Today | Target |
|---|---|---|
| Answer about the screen | yes | yes |
| Answer about the **business** | no | read tools |
| **Do** a job | writes form state only | write tools, behind confirmation |
| Know what is happening **now** | screen block only | screen + live business state |
| Remember what happened **before** | nothing | episodic + semantic memory |

The in-call agent already works this way — system prompt, conversation, tools. This is that
architecture brought to the dashboard, under the same discipline.

---

## 2. The five layers

### 2.1 Tools

Go from one tool to a curated registry. The guidance the design follows (REPORTED, from
Anthropic's tool-writing guidance and MCP tool guides):

- **Namespace by resource** — `leads_search`, `calls_recent`, `campaigns_list`. Distinct
  names are how a model picks correctly between them.
- **High-leverage, not thin API wrappers.** One `leads_search` with real filters beats six
  endpoints transcribed one-for-one.
- **Token-efficient results** — cap rows, say when capped, and return **names, not UUIDs**.
  Agents reason better on `"Dr. Rao"` than on `a3f1…`; a uuid in a tool result is tokens
  spent to make the answer worse.
- **Errors steer** — a tool failure returns one sentence the model can act on. This is the
  error-ladder doctrine (BACKEND-PATTERNS §3) applied to a non-human caller.
- **Read and write are different animals** and are separated (§2.5).

**Non-negotiable, and the reason this is safe:**

1. **Every tool runs inside its own short-lived `tenant_session(tenant_id)`**, so RLS —
   not the prompt — enforces tenancy. The streaming route deliberately holds no pooled
   connection (`routes.py`, "NO `Depends(db)`"), and that stays true: a tool opens a
   session, answers, closes it.
2. **Permission is checked IN CODE inside the tool.** The agent is bounded by the
   permissions of the human who invoked it — the least-privilege posture the agent-security
   literature is unanimous on (REPORTED: Microsoft, AWS Well-Architected agentic lens).
   A sentence in a system prompt is not an access control and is never treated as one.
3. **The tool schema array is byte-identical on every request.** Prompt caching keys on a
   leading run of identical tokens; a per-screen or per-tenant tool schema is a cache hit
   rate of zero. `prompt.py`'s docstring already argues this for `set_fields` and it now
   binds the whole registry. Gate by refusing inside the tool, never by varying the schema.

### 2.2 Context — "what is being done now"

Assembled per request in three tiers, ordered static-first so the cache can pay for it:

1. **Static prefix** — `SYSTEM_PROMPT` + the tool array. Byte-identical, cacheable, and
   pinned by `prompt_test.py`.
2. **Live ambient block** — the screen (what we send today) plus the tenant's live state:
   calls today, hot leads waiting, holds, blocked campaigns. Still fenced and still labelled
   untrusted, exactly as SCREEN STATE is.
3. **Just-in-time retrieval** — everything else stays *out* and is fetched by a tool when
   the question needs it. The rule is **relocate, don't delete**: keep a pointer in context,
   pull the detail on demand. Stuffing the whole business into every prompt buys context
   rot and a bill.

### 2.3 Memory — "what has been done"

Three stores, deliberately not one:

- **Working memory** — the open conversation. Bounded; already exists.
- **Episodic** — what happened: past conversations, and *actions taken* ("12 Sep, owner
  paused the Kondapur campaign"). Postgres rows, tenant-scoped. ⚠ This said "with
  embeddings for recall" and the build corrected it — see §5: there is no embedding path in
  this repository to reuse, and the relevance channel is a Postgres `tsvector`.
- **Semantic** — durable distilled facts about this business ("the clinic shuts Sunday",
  "Dr. Rao is the senior doctor", "the owner writes in Telugu").

Two implementation rules carry most of the value:

- **Distil in a background worker after the session ends, on a cheap model.** Never during
  a live turn. Extraction during a turn buys latency the user feels and tokens you pay for
  twice; the ARQ post-call pipeline is the pattern to copy.
- **Do not go vector-only.** Vector stores are weak on exact sequence and time, and in
  production "irrelevant past state keeps outranking fresh context" (REPORTED). Retrieval
  is **hybrid**: recent-by-time *and* relevance, always tenant-scoped, with recency able to
  win. (Built stronger than "able to win" — see §5's second correction.)

### 2.4 The loop

Read tools change the loop's shape: today it ends on the first prose turn and only
continues on a fill refusal. It must now execute tools, feed results back, and continue, so
that `leads_search` → answer, and `leads_search` → `calls_recent` → answer, both work
(compositional calling). Independent calls in one turn run concurrently (parallel calling).

The turn cap rises to match. **The cap is not the safety valve** — the wall-clock deadline
and `MAX_ANSWER_TOKENS` are, and both already exist (the latter added 31 Aug 2026 because
the copilot previously had no ceiling on paid output at all).

### 2.5 Safety — enforced in code, never by the model

- **Reads run automatically. Writes propose.** A write tool returns a described action; the
  person confirms it in the UI; the server then performs it. Human-in-the-loop is *"a
  governance mechanism… enforced deterministically by the application layer or
  orchestrator, not delegated to the model, with escalation triggers defined in code"*
  (REPORTED: Microsoft Security, 2026). We put the trigger in code.
- **Irreversible or regulated actions always confirm** — launching a campaign, adding to
  DNC, closing an account, anything spending money.
- **The compliance gate is never bypassed.** A write tool calls the same gated service
  function a human's click calls, so the DLT gate, DND scrub and consent checks apply
  automatically. Hard rule 5 forbids a bypass, and an agent path is the most tempting
  bypass anyone will ever be asked to write.
- **Every agent action is audit-logged**, reusing `core/auth.py::record_admin_tenant_read`'s
  sibling machinery (D-483).

---

## 3. Three constraints from THIS codebase

**① The Gemini leg cannot stream tool calls.** `chat.py` records it as VERIFIED-LIVE: the
compat endpoint `generativelanguage.googleapis.com/v1beta/openai/chat/completions` answers,
the native `:generateContent` surface 404'd, and the leg runs **non-streamed only** because
Gemini's streamed tool-call deltas carry a `None` `index` that breaks accumulation. So an
agent loop on a client's own Gemini key is non-streamed; Azure streams with tools. **This
is an open product decision** (§5), not a thing to paper over.

**② Tenancy and permissions are already solved.** Use `tenant_session` + the existing
`requires()` machinery. Nothing new is needed and nothing new should be invented.

**③ Money and metering already work.** `CopilotSpend` meters every turn; more turns cost
more, and the ledger will show it. No new billing path — hard rule 7 stands.

---

## 4. What the research says to avoid

- **Do not summarize by default.** The 2026 finding that overturns the habit: with prompt
  caching, keeping the history is often *cheaper, faster and better at remembering* than
  compacting it (REPORTED). Compaction should answer a named constraint, not be the
  default. Gemini's implicit caching discounts cached tokens ~90% above a ~1,024-token
  floor on Flash (REPORTED) — which rewards exactly the static-first ordering §2.2 sets.
- **Watch context rot** — quality falls as input grows, on every model (REPORTED, Chroma).
  More context is not free accuracy; that is the argument for just-in-time retrieval.
- **Never let the model self-authorize.** Confirmation lives in code.

---

## 5. Staged plan

| Phase | What | State |
|---|---|---|
| **1** | **Read-tool registry** — `business_snapshot`, `leads_search`, `calls_recent`, `campaigns_list`, `agents_list`, each wrapping an existing tested service fn; the loop feeds results back and CONTINUES. `MAX_TURNS` 4→6, derived: six is where `MAX_TURNS * STREAM_IDLE_S <= TOTAL_BUDGET_S` stops holding, so the wall clock caps the loop rather than a round number. | **built** |
| **2** | **Live business state block** — calls today/7d, leads waiting by status, campaign counts, outbound blocker RULE NAMES, IST clock. Carries no tenant-authored string at all (integers and closed-set rule names only), so there is nothing to sanitize; ceiling proven under 800 bytes by construction, not estimated. Degrades to `<unavailable part=…/>`, never to zeros. | **built** |
| **3** | **Write tools that PROPOSE** — `lead_set_status`, `dnc_add`, `campaign_pause`. A proposal is a signed 5-minute JWT and no table; forgery, replay, cross-tenant and cross-actor each refused. Confirm executes through the SAME gated service function a click uses and writes an `audit_log` row. | **built** |
| **4** | **Memory** — `copilot_memories` (RLS in the same migration), hybrid recall with recency STRUCTURALLY guaranteed a seat, semantic distillation in an hourly ARQ job on a cheap model, wired into retention AND every erasure path. | **built** |
| 5 | Loop + the streaming decision (Azure-streamed vs Gemini-non-streamed) | **open** |

Phases 1-4 were built in parallel by four agents against this document as the shared
specification, then reconciled into one loop by hand. Three corrections the build made to
THIS document, recorded because the document was wrong and the code is right:

- **§2.3 said to reuse the existing embedding path. There isn't one.** Verified at build
  time: no `CREATE EXTENSION vector`, no vector column in any migration, no embedding call
  anywhere in `apps/`; `kb/models.py` says "No embedding column, by decision (D-28)".
  Recall is therefore Postgres `tsvector` (config `simple`, not `english` — English
  stemming drops Telugu tokens), with `_RECALL_SQL` shaped so a similarity retriever is one
  more CTE the day a provider exists. Standing one up would have meant a new vendor leg, a
  new credential and a reversal of D-28 — none of which a memory feature gets to decide.
- **`agents_list` shipped a day late, and the delay is the point.** Phase 1 dropped it
  rather than build it on either of the two available routes: there was no
  `agents/service.py::list_agents` — the roster query, its row mapper and the `AgentOut`
  model all lived inside `agents/routes.py` — so the tool could only have called a route
  handler from a service (a layering inversion) or kept a second copy of the SQL (D-103).
  It was closed by extracting the roster instead: `agents/schemas.py` (the wire model,
  `crm/schemas.py`'s shape) and `agents/roster.py` (the query, the mapper, `list_agents`,
  `agent_by_id`), with `agents/routes.py` left thin and the OpenAPI contract unchanged.
  `agents/service.py` was the obvious home and does not work — `AgentOut` reaches
  `compliance/disclosure.py` for `truthful_answer_rule`, which imports `compliance/optout`
  → `compliance/service` → `agents/service`, and the app failed to import. **The lesson
  the plan should carry: a "thin wrapper over an existing tested service fn" is only thin
  when the service fn exists**, and phase 1's refusal to fake one is why there is one
  spelling of that query today rather than two.

- **Recency is not a weight, it is a seat.** §2.3 said "recency able to win"; the built
  design is stronger — two retrievers with separate budgets, unioned, so similarity can
  never starve recency. The blend only ORDERS what both channels already found.

## 6. Open questions

- **⚠ PHASE 3 IS HALF-WIRED AT THE BROWSER, AND THE SERVER HALF IS COMPLETE.** The
  `event: proposal` frame is emitted, documented in the route description and in the
  OpenAPI, and `POST /v1/copilot/confirm` is mounted, permissioned and tested — but
  `apps/web/src/lib/copilot/stream.ts` handles `text`, `fill`, `done` and `error` and
  **drops every other event on the floor**, and nothing in `apps/web/src` posts a token
  back. So today a model that calls a write tool tells the person "I've suggested pausing
  that campaign", the proposal is emitted, and the person sees nothing — which is the exact
  failure the system prompt's "say you have suggested it, never that you have done it" was
  written to avoid, arriving by the other door. Nothing is unsafe: a proposal changes
  nothing and expires in five minutes. **What closes it** is one branch in `stream.ts`, a
  proposal card in `CopilotPanel.tsx` showing `title`, `summary` and `current → proposed`,
  and one mutation posting `token` to `/v1/copilot/confirm` — a frontend change, deliberately
  not made by the backend lane that found it (31 Aug 2026).

- **Streaming vs the client's own model** (§3①). Azure streams with tools; the client's own
  Gemini key does not. Whether the assistant streams is therefore currently a function of
  which leg answers, and that is a product decision nobody has made.
- **Gemini function-calling wire details are UNVERIFIED here** — Google's doc host is
  egress-blocked. We build to the OpenAI-compatible shape `chat.py` proves against the live
  endpoint, and nothing in this tree may assert Gemini's native `functionDeclarations`
  semantics until somebody reads the page or probes with a real key.
- **Memory retention and DPDP.** Episodic memory stores what a user did; semantic memory
  stores facts about their business. Both are personal data under the tenant's own
  retention policy and must inherit it — routed to the retention worker, not invented here.
