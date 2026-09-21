# Bolna-era residue audit — 21 Sep 2026

**Scope.** The founder found two Bolna-era residues in the ops console BY LOOKING AT A
SCREEN: an `elevenlabs` clone-provider option whose refusal copy sends an operator to
`https://platform.bolna.ai/voices`, and a "the voice platform no longer lists this voice"
state that only a vendor's second opinion can set. No gate saw either. This is the sweep
for what else is like them.

**Method.** Grep, then open and read each hit. Every claim below is cited to a file and
line read on 21 Sep 2026 and checked against the code, not against a comment. Findings are
ranked by what they cost, not by how many there are.

**Two exclusions applied throughout, per the brief and CLAUDE.md.** `apps/api/engine/
bolna.py` and its conformance tests are a live registered adapter (`build_engine` branches
on it, `calevate_shared.config.EngineName` = `{fake, bolna, cartesia, pipecat}`,
`config.py:85`) — its existence is by design. `bolna-findings/` is the hash-pinned
read-only mirror and is cited, never changed. Decision rows in `docs/ROADMAP.md` are
history. A Bolna reference that is a CITATION supporting a claim is not residue.

**Both engines are selectable today.** `Settings.engine` defaults to `"fake"`
(`packages/shared/src/calevate_shared/config.py:361`) and is per-environment. So "residue"
here means COPY OR BEHAVIOUR THAT IS UNCONDITIONAL WHERE THE FACT IS ENGINE-CONDITIONED —
not the mere presence of the word Bolna.

---

## 1. Operator- and client-facing text (the expensive category)

### 1.1 The public sales page promises in-call handoff, which the owned runtime refuses — and every other surface was already fixed

`apps/web/src/app/solutions/page.tsx:120`

> "It puts a caller through to one of your team when you have set up a handover list, and
> never outside the hours that person gave you."

Unconditional, on a public marketing page. `PIPECAT_CAPABILITIES.in_call_handoff` is
`False` (`apps/api/engine/pipecat.py:246`); the declaration's own note says the carrier
API that would do it is UNKNOWN here (`pipecat.py:200-206`). On that engine
`agents/handoff.spec_for` asks `transfer_providers.transfer_blocked_reason` and sends NO
destination (`apps/api/agents/handoff.py:312`), and the client's own handover screen is
told so — `GET …/handoff` calls `transfer_blocked_reason(get_engine())` and returns it as
`unavailable_reason` (`apps/api/agents/handoff_routes.py:243-275`).

WHO IS MISLED: a PROSPECT, before they are a client, reading a sales promise. This is the
withdrawn-voice bug one altitude up — copy that is true of a rented vendor and false of the
runtime we host — and it is the most expensive item in this audit because a person acts on
it commercially.

SMALLEST FIX: the same shape the console already uses. The page is static, so either cut
the sentence to what holds on every selectable engine, or drive it from a capability the
way `KbDriftOut.engine_supports_knowledge_base` (`apps/api/ops/routes.py:337`) and
`VerificationOut.publishable` (`apps/api/agents/publishing_routes.py:262`, derived at `apps/api/agents/publishing.py:852`) already do.

### 1.2 The same page says the agent looks nothing up mid-call, which the owned runtime does

`apps/web/src/app/solutions/page.tsx:128`

> "It does not look anything up mid-call. What it can say is compiled into the agent before
> the call."

`PIPECAT_CAPABILITIES.knowledge_base` is `True` (`apps/api/engine/pipecat.py:241`) and the
worker registers an in-process pack search as a CALL TOOL —
`build_knowledge_tool(...)` is in the tool list at
`apps/voice-worker/voice_worker/pipeline.py:1405`. `BOLNA_CAPABILITIES.knowledge_base` is
also `True` (`apps/api/engine/bolna.py:3694`, D-488). So the sentence is false on both
engines a deployment can actually run.

This one errs in the safe direction commercially and the unsafe direction legally: it is a
statement to the public about what reaches a caller, made by a product whose knowledge
path is a human approval gate. WHO IS MISLED: a prospect, and anyone quoting the page back
at us.

SMALLEST FIX: replace with the constraint that IS true and is the one the product sells —
a caller only ever hears knowledge a human approved and published
(`apps/api/kb/service.approve_source`, `publish_source`).

### 1.3 A pipecat refusal tells an operator the worker reads keys from the secrets manager; it reads them from its process environment

`apps/api/engine/pipecat.py:1173-1176`

> detail: "The voice platform in this deployment runs inside our own software and **reads
> its model keys from the secrets manager**, so there is no separate credential store to
> install one into."

The docstring immediately above it (`pipecat.py:1148-1158`) records that this exact claim
was found wrong on 15 Sep 2026 — *"`voice_worker/boot.py` reads every key from its own
PROCESS ENVIRONMENT, injected by the Pipecat Cloud secret set… `PLATFORM_KEK` must never be
in that image"* — and the `remediation` below it was rewritten accordingly ("Rotate the
model key in TWO places", `:1178-1184`). The `detail` was not. Verified at source:
`apps/voice-worker/voice_worker/boot.py:330,396` read `os.environ`; nothing in
`apps/voice-worker/` opens `platform_secrets`.

WHO IS MISLED: an operator rotating a model key, who reads the detail, believes the
secrets manager is the single source, and stops before the second step the remediation
names. The two halves of one error message contradict each other.

SMALLEST FIX: one line — "reads its model keys from its own container's secret set".

### 1.4 The KB out-of-sync runbook tells an operator a capability is absent that has been live since D-488

`runbooks/kb-out-of-sync.md:118-140`

> "Then read the engine's own listing for that agent — **IF THE ENGINE HAS ONE. ON BOLNA IT
> DOES NOT, AND THIS STEP IS NOT AVAILABLE (D-354).**" … "`BOLNA_CAPABILITIES.knowledge_base`
> is now `False` and `list_kb` REFUSES by name" … "**What to do instead, on Bolna:** identify
> from the vendor console" … "In-call retrieval is OURS regardless (the D-28 managed vector
> service…)".

Three claims, all false today. `BOLNA_CAPABILITIES.knowledge_base` is `True`
(`apps/api/engine/bolna.py:3694`); D-488 built a real `attach_kb`/`detach_kb`/`list_kb`.
D-502 reversed D-28 — the store is `pgvector` in the Postgres this repo already runs, and
`apps/workers/kb_embeddings.py` exists and is registered
(`apps/workers/settings.py:132`).

WHO IS MISLED: an operator IN AN INCIDENT, which is the worst moment to be told a
diagnostic step is unavailable when it is the step that answers the question. They will go
to a vendor console instead of running `list_kb`.

SMALLEST FIX: delete the D-354 paragraph and point step 1 at `list_kb`, with the
`kb-orphans` route for the account-level half; correct "the D-28 managed vector service" to
the pgvector store.

### 1.5 The alarm index's voice-catalogue remediations name a Sarvam model this product no longer ships

`runbooks/alarm-index.md:211` (`voice_catalogue_empty`)

> "the sync filters on `TTS_MODEL_LIFECYCLE`, so an account that dropped `bulbul:v3` reads
> as empty here even while its other voices are fine."

`bulbul:v3` left `TtsModel` and `TTS_MODEL_LIFECYCLE` on 18 Sep 2026 with the Sarvam TTS
leg (D-629); `tests/model_lifecycle_guard_test.py:665` asserts its absence and
`tests/voice_tier_test.py:143` asserts it is not in `get_args(TtsModel)`.

WHO IS MISLED: an operator paged at the one moment the catalogue is empty, sent to check a
vendor account for a model we withdrew. Same row also opens with `BOLNA_API_KEY`
unconditionally; that is correct on `bolna` and meaningless on `pipecat`, where
`PipecatEngine.credential_env_keys` is `()` (`apps/api/engine/pipecat.py:881`) — though on
that engine the sync is now a stated no-op (§2.1) so the alarm cannot fire. The `bulbul:v3`
half is wrong on every engine.

SMALLEST FIX: strike the `bulbul:v3` clause; name the credential per engine or say "the
engine credential for this deployment".

### 1.6 The KB-orphan remediation sends an operator to a vendor console that does not exist on the owned runtime

`runbooks/alarm-index.md:331` (`engine_kb_orphans_detected`)

> "a hand-made upload in the vendor console" … "An `unrecorded` object is safe to delete at
> the vendor ONCE that client's live version is confirmed good" … "suspect an agent
> deletion at the vendor".

This alarm IS reachable on `pipecat`: `knowledge_base=True`, `list_account_kb` is
implemented (`apps/api/engine/pipecat.py:1104-1121`), and the daily sweep's only guard is
"the engine has no knowledge base at all" (`apps/workers/kb_orphans.py:64-70`). On that
engine the "vendor" is our own object table and there is no console, no status page and no
vendor-side DELETE. Row `:330` has the same shape ("the bound is in `engine/bolna.py`",
"check their status page") but cannot fire there — `complete=True` is a fact on one query
(`pipecat.py:1112-1113`) — so it is engine-specific rather than wrong.

WHO IS MISLED: an operator acting on a DPDP-relevant finding, hunting for a console.

SMALLEST FIX: give the row the two-engine answer — at a vendor, the console; on the owned
runtime, the object rows our own attach path wrote — since `GET /v1/ops/kb-orphans` already
names the handles either way.

### 1.7 The voice-catalogue worker's terminal alert offers a "built-in seed" that was deleted, and a credential one engine does not have

`apps/workers/voice_catalogue.py:104-113`

> "The last synced catalogue **(or the built-in seed)** is still being offered… Check the
> engine credential, then POST /v1/ops/voices/refresh."

The same module's own docstring says the opposite twelve lines up: *"a process with no
cached rows offers NO voices and says so on every picker (D-588 deleted the compiled seed
that used to answer here)"* (`voice_catalogue.py:24-26`). `apps/api/ops/routes.py:1106-1109`
carries the corrected reading; this string did not get it.

WHO IS MISLED: an operator who believes a fallback catalogue is serving clients when none
is. SMALLEST FIX: drop the parenthesis.

### 1.8 The catalogue-refresh route still tells an operator to clone a voice in "the voice platform's Playground"

`apps/api/ops/routes.py:1120-1129` (OpenAPI `description`, which also ships to the browser
via `apps/web/src/lib/api/schema.d.ts:6735`)

> "Use it after importing or cloning a voice in the voice platform's **Playground**"

"Playground" is Bolna's word for the screen that holds the Voice Lab
(`bolna-findings/mirror/pages/clone-voices.md`, cited at
`apps/api/agents/voice_admission.py:131`). On `pipecat` this route is a stated no-op —
`sync_voice_catalogue` returns `skipped_reason` when
`lists_voices_independently()` is False (`apps/api/agents/voice_sync.py:295-305`) — so the
description promises an operator a refresh that cannot happen, and names the place to do
the work as a platform this deployment does not use.

The route's rendered NOTE is already correct (`_voice_refresh_note`'s skipped arm,
`apps/api/ops/routes.py:1188-1194`), which is what makes the description the leftover.

SMALLEST FIX: neutral wording in the description ("after importing or cloning a voice with
your TTS vendor, or adding one with Add Voice"), since the note already tells the operator
what actually happened.

### 1.9 Legal register §3.1 states a Bolna residency caution as a fact about "the voice platform"

`apps/web/src/lib/legal/subprocessors.ts:775-790`

The subsection id is `bolna-residency` but the heading and callout read unconditionally —
"3.1 Where the voice platform runs the call, and why that is not India" / "Assume the call
itself is handled outside India" — while the register's own Pipecat Cloud row says the
conversation runs in a container of ours "where a deployment is set to use it"
(`subprocessors.ts:306-320`).

WHO IS MISLED: a client's counsel, in the safe direction (the caution overstates exposure
rather than understating it), which is why this is ranked here and not higher. It is still
a present-tense claim about a vendor that may not be on their call.

SMALLEST FIX: scope the heading and callout to the Bolna row by name, as the id already
does.

---

## 2. Behaviour correct for a vendor engine, wrong for an owned runtime

### 2.1 Already fixed, and the fixes are the model — recorded so nobody re-finds them

* `EngineCapabilities.lists_voices_independently()` derives the witness question from
  `agent_hosting` rather than adding a field
  (`packages/shared/src/calevate_shared/engine.py:490-513`), and
  `sync_voice_catalogue` returns a STATED NO-OP on it rather than pruning our own table
  against itself (`apps/api/agents/voice_sync.py:273-305`). ⚠ `voice_sync.py`,
  `voice_admission.py`, `voices.py`, `voice_curation.py`, `ops/voice_curation_routes.py`,
  `apps/web/.../ops/voices/page.tsx` and `lib/api/opsVoices.ts` were BEING EDITED by other
  agents while this audit ran; what they hold now is mid-edit and is not reported here as
  settled.
* `EngineDriftPanel.tsx:22` carries the owned-runtime reading.
* `agents/handoff_routes.py:243` asks the capability, so the CLIENT console is honest about
  handoff (which is what isolates §1.1 to the public page).

### 2.2 Checked and NOT residue — the KB orphan cross-check is still between two writers

`PipecatEngine.list_account_kb` reads the engine-side object table, `kb/orphans.py` compares
it against `kb_sources`, and the two are written by different paths — the attach path and
the publish path — so a crash between them still leaves the residue the sweep exists to
find (`apps/api/engine/pipecat.py:1104-1121`). This is NOT the "reads its own output back"
shape that made the voice sync circular. Recorded because it looks identical from a grep.

### 2.3 Checked and NOT residue — the engine drift sweep still has a witness

On `owned_runtime` `get_agent` answers from `agent_config_attestations`, recomputed by the
worker from the string in its own memory, never from the record the adapter wrote
(`apps/api/engine/pipecat.py:1186-1196`, module docstring `:18-24`). `workers/
engine_reconciliation.py` therefore still compares two independent answers.

### 2.4 A stale comment invites an engineer to re-fix something already fixed

`apps/web/src/app/c/[slug]/agents/panels/handover.tsx:36-43` states as current: *"It is NOT
fixable here… `GET …/handoff` runs no `require_capability` and `HandoffOut` carries no
engine or capability field."* It does now — `handoff_routes.py:243` calls
`transfer_blocked_reason(get_engine())` and `:275` returns it. WHO IS MISLED: a future
engineer, into rebuilding a seam that exists. SMALLEST FIX: delete the paragraph (hard rule
13 — the correction's subject is gone).

---

## 3. Constants, enums, DB values, wire values

**Nothing found that is both unreachable and misleading, beyond the two already in flight.**

* `UNPUBLISHABLE_CLONING_PROVIDERS = frozenset({"elevenlabs"})`
  (`apps/api/agents/voice_admission.py:142`) is residue #1 and is being fixed by another
  agent; not re-reported.
* **`usage_events` / `credit_lots` historical voice-tier values are HISTORY, NOT RESIDUE,
  and must not be cleaned up.** `apps/api/db/registry.APPEND_ONLY_TABLES` names the ledgers
  and hard rule 4 makes them INSERT-only; migration `f1c40d8b6e93` renames the `credit_lots`
  rate columns and REFUSES against a non-empty table precisely because purchased rates are
  frozen. A row that says `voice_tier: "sarvam"` or a Bolna-era cost is what was true when
  it was written. `tests/spend_attribution_test.py:781-848` exists to prove such a row still
  renders its refusal rather than being rewritten.
* `bolna_api_key`, `bolna_llm_credential_name`, `BOLNA_WEBHOOK_SOURCE_IPS` and
  `WEBHOOK_AUTH_BY_ENGINE["bolna"]` are per-engine configuration for a selectable engine,
  read only when `ENGINE=bolna`. Not residue.

---

## 4. Docs asserting a Bolna fact in the present tense

One cluster, and it is the same fact in four places: **D-488 reversed D-354 in the code and
the reversal did not reach the blueprint.** `BOLNA_CAPABILITIES.knowledge_base` is `True`
(`apps/api/engine/bolna.py:3694`).

| File:line | What it asserts | Why it costs |
|---|---|---|
| `docs/FLOWS.md:43-46` | "**On Bolna it REFUSES at the capability check before anything is withdrawn** (`BOLNA_CAPABILITIES.knowledge_base = False`, D-354)" | `docs/` is authoritative per CLAUDE.md, so an agent implements against it |
| `docs/FLOWS.md:52` | "there is no embeddings job of ours (D-28/D-33)" | `apps/workers/kb_embeddings.py` exists and is registered (`apps/workers/settings.py:132`); D-502 reversed D-28 |
| `docs/TRD.md:784-786` | "**THE BUILT-IN KB IS NOT DRIVABLE THROUGH OUR PORT AND THE ENGINE DECLARES THE CAPABILITY ABSENT (D-354)**" | same |
| `docs/TRD.md:1005-1007, 1027-1030` | "T0 only today… D-354 then closed the engine's own route too, so today T3 has no home at all" | same; §6.2 is the section a KB change is planned from |
| `docs/PRODUCTION-READINESS.md:157-160` | "The capability is now declared absent and the methods refuse (D-354)." | a readiness document read as a state of the world |
| `apps/api/ops/routes.py:326-329` (comment) | "`BOLNA_CAPABILITIES.knowledge_base` is False (D-354…), so on the primary engine that early return is EVERY run" | the field beneath it is correct; only the justification is stale |

`docs/OPERATIONS.md:89` already carries the supersession in bold, and
`apps/web/tests/knowledgeClaims.test.ts:10-45` independently flagged `docs/TRD.md` §6.2 as
the stale half of a conflict on 15 Sep 2026 and — correctly, per CLAUDE.md — declined to
pick a winner. Nobody closed it. SMALLEST FIX: one edit per row, each replacing the D-354
sentence with D-488's state and the `docs/ROADMAP.md` D-488 row as the citation.

**Not reported as residue:** `runbooks/engine-violations.md`, `runbooks/campaign-stall.md`,
`runbooks/vendor-cost-unit.md`, `runbooks/object-lifecycle.md` and the OPERATIONS §2 gates
name Bolna as the engine a specific procedure applies to, with the mirror cited. That is a
citation supporting a claim, not an instruction to use a platform we left.

---

## 5. Could a gate have caught these two?

**Yes for one of them mechanically, yes for the other with a registry, and no for §1.1 by
any string rule.** The build already runs ~45 guardrails
(`.github/workflows/ci.yml`, the `Guardrail:` steps), and two of them are the exact
precedents to copy: `scripts/check_subprocessor_coverage.py` derives VENDOR IDENTITY from
`Settings` field shapes and adapter module names, parses the TypeScript register shallowly,
checks both directions, and exits 2 REFUSED when its own parse goes blind; and
`apps/web/tests/knowledgeClaims.test.ts` walks JSX string literals with the TypeScript
compiler API and asserts product claims against capability constants.

### Gate arm A — "operator- or client-facing copy names a platform the configured engine is not"

*Reads.* (1) Python string literals in copy positions only, by AST: the `detail=`,
`remediation=`, `title=` keywords of `ProblemError(...)` and `alert(...)`, the `summary=` /
`description=` keywords of a router decorator, and module-level `Final[str]` constants whose
name ends `_NOTE`/`_DETAIL`/`_REASON`. Docstrings and `#` comments are EXCLUDED — they are
where the citations legitimately live. (2) Every string and JSX text node under
`apps/web/src`, via the TypeScript compiler API, minus `lib/api/schema.d.ts` (generated).

*Asserts.* No such literal contains a token from `VENDOR_WORDS`, a small hand-maintained map
keyed by `get_args(EngineName)` — `bolna → {"Bolna", "bolna.ai", "Voice Lab", "Playground"}`,
`cartesia → {"Cartesia"}` … — unless the file is that engine's own adapter
(`apps/api/engine/<name>.py`) or its declared test. Plus the blind-spot arm:
refuse (exit 2) unless it parsed at least N literals on each side.

*What it would have said about residue 1:* `apps/api/agents/voice_admission.py:134 —
operator copy names "https://platform.bolna.ai/voices"; "bolna" is one engine of four and
this file is not its adapter.` It also catches §1.8 (`Playground`) here and now, and would
have caught the ElevenLabs refusal sentence the moment it was written.

*What it would have said about residue 2:* nothing. "The voice platform no longer lists this
voice on our account" names no vendor.

### Gate arm B — "a state is settable only by a capability the configured engine lacks"

*Reads.* A declared registry, `CAPABILITY_CONDITIONED_WRITES`, mapping a predicate on
`EngineCapabilities` to the symbols whose write it authorises — e.g.
`lists_voices_independently → {"withdrawn_at"}`, `knowledge_base → {"attach_kb",
"detach_kb", "list_kb"}` — plus the `apps/api` and `apps/workers` ASTs.

*Asserts.* Every function that writes a registered symbol must contain, on a dominating
branch, a call to that predicate or to `require_capability(<its field>)`. This is a
dominator check on one function body, not whole-program analysis, which is why it is cheap
and why it is honest about what it proves.

*What it would have said about residue 2:* `apps/api/agents/voice_sync.py —
sync_voice_catalogue writes `withdrawn_at` with no dominating
`capabilities.lists_voices_independently()`; on ENGINE=pipecat that prune arm stamps rows
the same function wrote.` That is exactly the bug, named before a screen showed it.

*The half that is NOT statically decidable* is whether the COPY about such a state has an
alternative branch. The tree already has the pattern that makes it decidable —
`KbDriftOut.engine_supports_knowledge_base` and `VerificationOut.publishable` put the
capability ON THE WIRE so the screen renders the server's answer — so the assertable form is
narrower and still worth it: a response model that carries a capability-conditioned state
must also carry the capability field, and the copy table keyed on it must have an entry for
BOTH outcomes (the `_VERIFY_HEADLINE` dict shape, `apps/api/agents/publishing.py:829-843`).

### Gate arm C — the cheapest one, and it closes §1.5 and §1.6

`scripts/check_alarm_wiring.py` already resolves every `alert()` call site and matches it to
its `runbooks/alarm-index.md` row, and already scans operator docs for dangling names. Add:
for each alarm, derive the set of engines that can raise it (the capability guard dominating
the call site, by arm B's machinery), and fail when the remediation cell names a lever no
engine in that set has — `BOLNA_API_KEY` where the set includes `pipecat`, "the vendor
console" where the set includes an `owned_runtime` engine. It would have failed on
`alarm-index.md:331` today.

### What no gate can catch, stated plainly

`solutions/page.tsx:120` — "It puts a caller through to one of your team" — names no vendor,
no symbol and no state. Matching it to `in_call_handoff` requires a human to write down that
this sentence IS that capability. That registry is precisely what
`apps/web/tests/knowledgeClaims.test.ts` is, and extending it to the handoff and mid-call
claims is the only mechanism available. A gate can enforce a registry; it cannot discover
that an English promise has become false.

---

## UNKNOWNs

* **UNKNOWN — `platform.bolna.ai`, `www.bolna.ai` and `docs.pipecat.ai` are egress-blocked
  from this container.** Nothing here asserts what any of those pages shows today. Every
  vendor fact above is cited to the pinned `bolna-findings/` mirror or to the installed
  pipecat wheel.
* **UNKNOWN — whether any deployment is currently running `ENGINE=pipecat`.** The default is
  `fake` (`config.py:361`) and the value is per-environment; no deployed value is readable
  from here. Every finding is therefore stated as "on that engine", not as "in production".
* **Mid-edit, not settled:** `apps/api/agents/voice_sync.py`, `voice_admission.py`,
  `voices.py`, `voice_curation.py`, `apps/api/ops/voice_curation_routes.py`,
  `apps/web/src/lib/api/opsVoices.ts`, `apps/web/src/app/admin/ops/voices/page.tsx` and
  their tests were being changed by other agents during this audit.
