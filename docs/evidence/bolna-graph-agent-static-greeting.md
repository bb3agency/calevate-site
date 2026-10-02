# Bolna graph agents — the static-greeting hybrid, evaluated (7 Sep 2026)

**Question under evaluation.** Would moving an agent from Bolna's `simple_llm_agent`
(one system prompt — what `engine/bolna.py::_agent_body` builds today) to a `graph_agent`
whose GREETING and GOODBYE are **static nodes** (audio pre-rendered at save, played from
cache) and whose middle is one LLM node, cut per-call TTS cost and first-word latency
enough to be worth a new agent shape?

**Verdict: DO NOT MIGRATE YET. Migrate only if all four conditions below are met by a
live check, not by another docs pass.** The three engineering conditions came out of the
Comet research thread and stand; the fourth is this repo's own and is not optional:

1. A live execution log shows the WELCOME MESSAGE being billed as synthesizer characters
   (`cost_breakdown.synthesizer > 0` on a call whose only spoken text was the greeting).
   If the welcome is already free/cached, the static node buys nothing on the greeting.
2. `GET /agent/{id}` returns the graph (`llm_agent.llm_config.nodes`) so a publish can
   READ BACK what it wrote. Without that, the compliance invariant cannot be verified
   against the engine (hard rule 5) and the migration is refused on that ground alone.
3. A static node on our TTS actually builds its cache on save (observable: the first call
   after save plays the greeting with no `synthesizer` cost).
4. A decision-log entry (ROADMAP §6) stating HOW `compose_engine_prompt`'s invariants are
   enforced and verified PER NODE — `docs/evidence/bolna-platform-changelog.md` §4 refused
   graph agents on exactly this ground and that refusal is still in force.

Everything below is the evidence, by class. **VERIFIED-VENDOR-DOCS** = the hash-pinned
mirror at `bolna-findings/mirror/pages/` (`MANIFEST.json`, per-page SHA-256), cited
`file:line`. **REPORTED** = relayed by the Comet browser thread from the live dashboard or
from pages it could fetch; not re-read here. **UNKNOWN** = nobody has a source.

---

## 0. The mirror already holds every page Comet could not load

Comet's final pass reported eight `graph-agent/*` URLs as 404/failed-fetch and left their
UNKNOWNs open. **All eight are in the mirror**, so most of them close from evidence we
already had (§2–§8 below). The one that does not is OSS `task_manager.py` /
`openai_llm.py` (Comet's "A5"), which is not a docs page and is not mirrored.

| Comet: "did not load" | Mirror path | Closes? |
| --- | --- | --- |
| `graph-agent/router-nodes` | `graph-agent/router-nodes.md` | Yes — §4 |
| `graph-agent/variables` | `graph-agent/variables.md` | Partly — §3 (the `static_message` half stays UNKNOWN) |
| `graph-agent/validation` | `graph-agent/validation.md` | Editor half yes; API 4xx half no — §5 |
| `graph-agent/import-export` | `graph-agent/import-export.md` | Yes — §6 |
| `graph-agent/version-history` | `graph-agent/version-history.md` | Yes — §6 |
| `graph-agent/managing-nodes` | `graph-agent/managing-nodes.md` | Field NAMES yes; JSON KEYS no — §7 |
| `graph-agent/managing-transitions` | `graph-agent/managing-transitions.md` | Present; not needed for this question |
| `graph-agent/using-the-editor` | `graph-agent/using-the-editor.md` | Present; not needed for this question |

Lesson for the next research pass: **grep the mirror before sending a browser agent to the
vendor's host.** Their host is egress-blocked from the container and flaky from a browser;
the mirror is neither.

---

## 1. What we build today, and where the greeting lives

- Our adapter builds a `simple_llm_agent` with one `conversation` task
  (`docs/evidence/bolna-request-contract.md:88` — `agent_type` enum is
  `[simple_llm_agent, knowledgebase_agent, graph_agent]`, VERIFIED `create.md:614-620`).
- The greeting is `agent_welcome_message` = `cfg.opening_line`
  (`apps/api/engine/bolna.py:3143`). It is what the greeting judge in
  `apps/api/agents/verification.py:101` reads back to verify the AI-disclosure sentence
  (D-163, hard rule 5).
- ⚠ **`agent_welcome_message` is NOT declared in the vendor's `GET /agent` schema**
  (`api-reference/agent/get.md:55-90` declares `id`, `agent_name`, `agent_type`,
  `agent_status`, `created_at`, `updated_at`, `tasks`…). `docs/OPERATIONS.md:230-236`
  already carries this as an open item: if the welcome does not come back on GET,
  `_agent_greeting` reports `unreadable` forever and no publish can verify the disclosure
  sentence. **This is the same read-back problem condition 2 above depends on**, one level
  up: the schema does not declare `llm_agent.llm_config` or `nodes` either.
- `welcome_message_delay` exists: "Delay in milliseconds before the agent plays the
  welcome message" (`api-reference/agent/create.md:352-359`, VERIFIED).

---

## 2. Static nodes — VERIFIED (`graph-agent/static-nodes.md`)

- **What it is** (`:9`): "A static node pre-renders the audio for that message when the
  agent is saved and plays it back from cache at runtime. No LLM call. No TTS call."
- **Vendor's own latency/cost table** (`:15-18`): LLM node "~800ms (LLM + TTS + audio)",
  cost "LLM tokens + TTS characters"; static node "~50ms (cached audio)", cost "Zero".
  **Evidence class for those numbers: VENDOR-PUBLISHED, unmeasured by us.** They may not
  be restated as our latency or our saving (hard rule 11).
- **Shape** (`:24-37`): `"node_type": "static"`, `"static_message": "<text>"`, plus
  `edges`. `node_type` defaults to `"llm"` (`:43`).
- **When the cache is built** (`:162-166`): "generated when you save the agent, using the
  agent's configured TTS voice… If you change `static_message` later, re-save the agent
  so the cache regenerates." → a publish that changes the greeting must be a SAVE (a
  `PUT`/`PATCH` of the agent), and nothing tells us the cache is rebuilt synchronously
  before the response — **UNKNOWN whether the first call after save can race the render.**
- **Multilingual** (`:55-80`, and changelog `july-2026.md:102-110`, 9 Jul 2026):
  `static_message` may be a `{ "language_code": "text" }` map; one cached clip per
  language "each rendered with that language's voice"; follows language auto-switch; a
  language with no dedicated voice "falls back to the agent's primary voice". Same map
  format as `call_hangup_message` and `check_user_online_message` (`:72`). Telugu would be
  `te` **only if** the multilingual config uses ISO-639-1 — the page says "the same
  two-letter language codes as your agent's multilingual configuration" and does not list
  them; Comet REPORTED `te` from the live Audio tab.
- **Silence replay** (`:11`, `:44`, `:91`): `repeat_after_silence_seconds` on static OR
  LLM nodes; exposes `_silence_repeats` for expression edges to escalate after N silent
  rounds. A static node replays the same cached clip at zero cost.

**Consequence for the hybrid.** A fixed clinic greeting that names the clinic and states
"this is an AI" is exactly the "always say the same thing" case the page is written for —
IF the text contains no per-call variable. See §3.

---

## 3. Variables — VERIFIED (`graph-agent/variables.md`), one half still UNKNOWN

- Substitution is documented for **node prompts, the welcome message, and edge
  conditions** (`:7`, `:9`, `:15`). Values come from `context_data` "passed when the call
  was created or filled in by inline data extraction" (`:9`). Rule-edge expressions use
  the bare name, braces are for text only (`:36`).
- Built-ins populated by the platform (`:67-83`): `recipient_data.current_hour /
  _minute / _weekday / _day / _month / _year / _date / _time / timezone / user_number`,
  `detected_language`, `_node_turns`, `_total_turns`.
- The Variables panel is editor-only test data: "saved locally per agent (they don't
  affect the saved agent payload)" (`:57`).
- **`static_message` is NOT in the list of places a `{variable}` substitutes, on this page
  or on `static-nodes.md`.** And the mechanism argues against it: a clip rendered at SAVE
  time cannot contain a value that only exists at CALL time. So:
  **UNKNOWN — does `{variable}` inside `static_message` substitute, render literally, or
  fail validation?** Do not design a static greeting that needs the caller's name or a
  per-call slot. A clinic-name greeting is fine because the clinic name is constant per
  agent (one agent per tenant per number).

---

## 4. Router nodes — VERIFIED (`graph-agent/router-nodes.md`; changelog `july-2026.md:130-138`, 2 Jul 2026)

- "Silent dispatch nodes… It never speaks" (`:7-9`); must not set `prompt` or
  `static_message` (`:72`, `:169`).
- Edge evaluation order and cost (`:21-24`): expression edges in `priority` order —
  "Instant, no LLM call"; then intent edges — "One routing call". **"At most one
  routing-LLM call per turn"** (`:30`); a purely deterministic chain "resolves in ~0ms
  with no LLM call at all" (VENDOR-PUBLISHED number).
- Routing LLM defaults (`graph-agent/introduction.md:111-114`): `routing_provider`
  defaults to `groq` when a Groq key is configured, otherwise `openai`; `routing_model`
  defaults to `gpt-4.1-mini` on OpenAI and Azure, `llama-3.3-70b-versatile` on Groq;
  `routing_max_tokens` 250 (non-GPT-5) / 150 (GPT-5); `routing_reasoning_effort` GPT-5
  only. The response LLM "takes the same `llm_config` fields as a simple agent" (`:116`),
  so `ModelConfig.llm_traps` (temperature `1` on GPT-5) applies unchanged.
- **Not needed for the hybrid.** Greeting → conversation → goodbye is a linear graph; a
  router adds a second LLM vendor (Groq by default if a key is ever installed) for nothing.
  Recorded so nobody re-researches it.

---

## 5. Validation — editor half VERIFIED, API half UNKNOWN (`graph-agent/validation.md`)

- The EDITOR validates before every save; "**errors** that block saving and **warnings**
  that you can acknowledge" (`:9`); save with errors "is blocked and an error toast
  describes the issue" (`:18`); warnings "do not affect runtime behaviour" (`:65`).
- The page describes the dashboard. **UNKNOWN — whether `POST /agent` / `PUT /agent`
  with an invalid graph returns a 4xx, and what body.** We provision by API, not by
  dashboard (OPERATIONS gate 2), so this is the half that matters and it is unclosed.
  Close it by sending a deliberately invalid graph (e.g. a router with a `prompt`) to the
  API and recording the status and body.

---

## 6. Import/export and version history — VERIFIED

- **Exported JSON "is the complete agent payload — the same structure you'd send to the
  Agents API"** (`graph-agent/import-export.md:48`), including "All nodes and their
  prompts, settings, and overrides" (`:51`). Useful as a **one-off discovery tool**: build
  the hybrid once in the editor, export, and read the exact JSON keys that §7 leaves
  UNKNOWN. Import "replaces the entire current graph" (`:30`).
- **Version history is per AGENT, not per node** (`graph-agent/version-history.md:9`:
  "Every time you save a graph agent, the platform creates a version snapshot"; rows show
  version name, saved-at, `current` status, tags — `:25-30`). Restore is one click per
  version (`:34-37`). Comet's "per-node version" UNKNOWN closes as **no**.

---

## 7. Per-node LLM overrides — field NAMES verified, JSON KEYS unknown (`graph-agent/managing-nodes.md`)

- Node roles and precedence (`:36-40`): Start > Closing > Function > Static > LLM.
- LLM-node overrides (`:111-120`): **Reasoning effort**, **Model & provider**,
  **Temperature** ("GPT-5 models accept only `1`"), **Max tokens** ("On GPT-5 models this
  budget is shared with reasoning tokens"). Agent-level settings are the default for nodes
  that do not override (`graph-agent/agent-setup.md:40,51`).
- **UNKNOWN — the JSON key names of those overrides.** `full-example.md:68-100` shows
  agent-level `llm_config.{model,max_tokens,temperature,provider,routing_*}` and nodes
  with only `id`, `prompt`, `edges`; no node carries an override. Close via §6's export.
- Not needed for the hybrid (one LLM node, agent-level model) — recorded to stop the
  question recurring.

---

## 8. Testing the hybrid — VERIFIED (`graph-agent/testing.md`)

- **Chat mode** (`:23-39`): text simulation, "shows which node is active" (`:32`),
  substitutes `{tokens}` in prompts and the welcome message from the Variables panel
  (`:35`); "does not test TTS voice quality, STT transcription accuracy, or audio latency"
  (`:39`). Zero TTS spend.
- **Call mode** (`:44-55`): a real outbound call, E.164 number, "consumes telephony and
  LLM credits. Save the agent before starting a call test" (`:55`).
- Comet REPORTED the checklist the page carries for what to confirm on a test: welcome
  with variables, routing, expression transitions, static nodes play the correct message,
  tools, silence auto-replay. Not re-read line-by-line here.

**First-call checklist for the hybrid (if conditions 1–4 are ever met):**
1. Chat with agent first — confirm the active-node label moves greeting → conversation →
   goodbye and that the goodbye node is reached on the hangup condition.
2. Save, then Get call from agent to a founder number.
3. Immediately `GET /executions/{id}` and record `cost_breakdown.synthesizer` (cents —
   `api-reference/executions/get_execution.md:268-271`) for a call that hung up after the
   greeting. That number is condition 1's instrument.
4. `GET /agent/{id}` and record whether `nodes` came back. That is condition 2.

---

## 9. The welcome message on a graph agent — and why condition 1 exists

- Graph agents have a welcome message that plays "when a call connects, before any node
  is active" and supports `{variable}` tokens (`graph-agent/agent-setup.md:21-33`).
- **No mirrored page says the welcome message is cached or pre-rendered.** The dashboard's
  "Preview welcome message" is REPORTED by Comet as a play-button preview, not a runtime
  cache. So today's `agent_welcome_message` is, on the evidence, synthesised per call —
  but that is an inference, and condition 1 turns it into a measurement before anyone
  spends engineering on a static node to replace it.
- If the welcome IS billed per call, the hybrid's cheapest form may be: **empty welcome
  message + static greeting node as the start node**, so the first thing the caller hears
  is the cached clip. Whether a graph agent accepts an empty/absent welcome is UNKNOWN.

---

## 10. TTS provider facts that bear on the cache

- Cartesia models (`providers/voice/cartesia.md:59-66`, VERIFIED): `sonic-3`,
  `sonic-3.5` ("recommended for production agents. 42 languages"), `sonic-preview`
  (Sonic 3.6 beta — "use `sonic-3.5` for production agents that need stable output").
  **Whether Telugu is among the 42 is NOT on the page — UNKNOWN.** Comet's condition 3
  named `sonic-3.5` because that thread was evaluating Cartesia; **our speech is Sarvam
  (D-36) and nothing here changes that.** The test that matters for us is a Sarvam Bulbul
  static node building its cache, not a Cartesia one.
- Hosted Audio tab TTS providers — Comet REPORTED (live dashboard): AzureTTS, Cartesia,
  ElevenLabs, Sarvam. The mirror's `agent-setup/audio-tab.md:107-113` confirms per-language
  TTS provider/model/voice selection and shows Sarvam / Bulbul v2 in its example, but the
  full provider list was not re-read from the mirror here. Treat the four-name list as
  REPORTED.

---

## 11. Why the repo refused graph agents, and what would have to change

`docs/evidence/bolna-platform-changelog.md` §4 ("Our adapter builds exactly that shape,
and it is the correct one") refuses graph agents because hard rule 5 requires
`compose_engine_prompt` to append the compliance invariants to **the** prompt and verify
them against the engine on every publish and drift sweep, and "a graph agent has *N*
per-node prompts". It ends: "Revisit only if a client needs deterministic multi-stage
routing, and then as a decision-log entry that says how the compliance invariant is
enforced per node."

Two facts from this pass change the SHAPE of that objection without removing it:

- `agent_information` is a "Global system prompt… Applied to every node"
  (`graph-agent/introduction.md:104`; `agent-setup.md:22` — "applied to every LLM call in
  this agent"). So the invariants could be appended ONCE, to `agent_information`, rather
  than to N node prompts — the enforcement half has a plausible single seam.
- The VERIFICATION half does not: `GET /agent` declares neither `agent_welcome_message`
  (already open, OPERATIONS §2 ~line 230) nor `llm_agent.llm_config`/`nodes`. If the
  graph does not come back on GET, no drift sweep can prove the engine still holds the
  invariant. That is condition 2, and it is the one most likely to fail.

A static GREETING node is, for hard rule 5, arguably an improvement: the AI-disclosure
sentence becomes a fixed clip the LLM cannot paraphrase away. But the invariant that must
survive is the in-conversation one ("answers truthfully when ASKED whether it is an AI"),
which lives in the LLM node, and that is where read-back matters.

---

## 12. Consolidated UNKNOWN register

| # | UNKNOWN | How to close | Cost |
| --- | --- | --- | --- |
| U1 | Is `agent_welcome_message` billed as synthesizer characters per call? | One live call, hang up after greeting, read `cost_breakdown.synthesizer` | one call's credits |
| U2 | Does `GET /agent/{id}` return `llm_agent.llm_config.nodes` for a graph agent? | Create one graph agent by API, `GET` it | free |
| U3 | Does a Sarvam Bulbul static node build its cache on save? Synchronously? | Save, call immediately, read `synthesizer` cost; repeat | one call |
| U4 | Does `{variable}` inside `static_message` substitute / render literally / fail? | Export a saved static node containing `{x}`; call it | one call |
| U5 | API-side validation: status and body for an invalid graph on `POST`/`PUT /agent` | Send a router with a `prompt` | free |
| U6 | JSON keys for per-node LLM overrides | Set one in the editor, export (§6) | free |
| U7 | Is Telugu among Cartesia sonic-3.5's 42 languages? | Cartesia's own language page — not mirrored | n/a for us (Sarvam) |
| U8 | Can a graph agent have an empty/absent welcome so the static start node speaks first? | Create one by API with no `agent_welcome_message` | free |
| U9 | OSS `task_manager.py` / `openai_llm.py` behaviour ("A5") | Read the OSS at a pinned commit — not in the mirror | reading time |
| U10 | Whether the mirror's `graph-agent/*` pages are current — the two pages Comet fetched live (`testing`, `using-context`) matched the mirror on every fact compared here, but the mirror carries its own fetch date, not today's | Re-fetch on the next mirror refresh | n/a |

Five of ten are free API calls. Per the tempo rule they are the next thing done when the
dashboard is open, not another research pass.

---

## 13. Decision

No code changes. No decision-log entry yet, because there is no decision — there is a
measurement (U1–U3) that has not been taken. The refusal in `bolna-platform-changelog.md`
§4 stands unchanged. Nothing in `apps/api/engine/bolna.py` moves. This document is the
place the answer to U1–U3 gets recorded; when it is, either this section becomes a
ROADMAP §6 entry with the per-node-invariant design, or it becomes one line: "measured,
not worth it".
