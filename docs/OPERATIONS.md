# Calevate — Operations, Quality & Runbooks

Version 1.0

---

## 1. Environments

- **local**: docker-compose (pg+redis+minio), engine mocked via adapter fakes.
- **staging**: DO BLR small; engine (Bolna) staging agents + one test number; synthetic data only.
- **prod**: DO BLR; separate engine workspace/keys; promote-only config flow.

## 2. Engine Verification Session — now executed as the BOLNA PILOT (D-31) [do FIRST]

> D-31 (Aug 2026): ThinnestAI failed due diligence before this session ran; the
> checklist below is executed against Bolna as the pilot scorecard. Adaptations:
> item 1's HMAC criteria become source-IP-allowlist + dedupe + poller verification
> (Bolna webhooks are unsigned, at-most-once — TRD §5); item 5 empirically measures
> webhook loss behavior; item 8 adds: the BYOK platform fee in writing (target
> ≤ ~₹1.5/min), sub-account/agency terms, INR/GST billing, recording
> retention/deletion API, India data-residency terms, Bulbul V3 exposure, Gemini or
> OpenAI-compatible LLM support, Telugu quality of the multilingual KB mode.
> Items failing ⇒ the engine decision reopens (no fallback engine is designated — D-31).

Budget ~₹3–5k (Bolna gives $5 free signup credits + Sarvam's ₹1,000 free credits, so
most of this is real PSTN call spend). 5–7 working days alongside other work.
**H = hard gate (a red H reopens the engine decision); S = soft gate (shapes M1 scope).**

| # | Gate | Pass criteria |
|---|---|---|
| 1 H | Webhook trust | Register a tunnel URL as the agent's `webhook_url`; run calls. Confirm deliveries arrive ONLY from 13.203.39.153 and our allowlist (nginx + in-app) rejects anything else; confirm dedupe on execution_id; confirm the payload matches Get Execution. Docs claim no signing — if a signature header exists, capture it and update TRD §5. |
| 2 H | Full API provisioning | Via API only, no dashboard: create agent → update prompt → attach number → start call (`POST /call`) → `GET /executions/{id}`. Confirm /v2 agent paths, `user_data` context injection round-trips into the prompt, and `scheduled_at` works. |
| 3 H | Telugu quality (BYOK) | Sarvam Saaras V3 STT + Bulbul V3 TTS on OUR keys. 10-utterance Telugu script on real PSTN: names/numbers ≥90% correct; Telugu-English code-mixed handled. Confirm **Bulbul V3 (not v2) is selectable**. |
| 4 H | Real-call latency | 10 PSTN calls: voice-to-voice p50 ≤ 1.1s, p95 ≤ 1.8s (stopwatch + recording analysis). **Vendor latency claims are marketing — their site says "<300ms" undefined; plan only against our own measurement.** Record first-greeting delay after pickup separately (cold-start hides there). **Also capture `latency_data` from Get Execution as an adapter fixture and record whether it AGREES with the stopwatch.** Their docs describe `time_to_first_audio` plus per-component transcriber/llm/synthesizer blocks — unverified against a live account, and a different set of numbers from voice-to-voice turn latency, which would be our own arithmetic aligning three components. This capture is what re-opens durable per-call latency storage: `calls.latency` was dropped (`f1a7c39d5be2`) rather than filled with pipeline timings that are not the caller's experience, and the storage shape gets chosen from the payload we actually receive. Note the documented `transcriber.turns` entries carry recognised TEXT — hard rules 5/6 apply to wherever it lands. |
| 5 H | Telugu turn-taking [NEW, D-32] | Barge-in mid-sentence, and end-of-utterance on slow/hesitant Telugu speech: does the agent cut callers off, or leave dead air? Endpointing is an ORCHESTRATION-layer property — BYOK models do NOT fix it. Measure, never assume. |
| 6 H | Webhook loss behavior | Kill the receiver mid-call: call continues; observe whether ANY retry arrives (docs + OSS code say none). Then confirm the List-Executions poller recovers every missed execution — it is the guarantee of record, so its recovery must be proven, not assumed. **And settle its PAGINATION, which recovery alone cannot.** Bolna documents none and publishes no OpenAPI spec, so `BolnaEngine.list_executions` follows only a continuation the payload itself hands it (`next`/`next_page_url`, same-origin, bounded to 20 pages) and never a guessed `?page=`/`?cursor=` — a parameter the vendor ignores re-reads page one forever. Where it cannot rule out a further page it returns `ExecutionListing.complete=False` and the poller alerts (`reconciliation_listing_incomplete`). Three things to record, all from ONE raw `GET /executions` body captured as a fixture: **(a)** the account's own execution count for the window from the dashboard, passed as `--attest gate6.executions_in_window=<n>` — more than we listed is proof of truncation and the gate goes red; **(b)** the number of rows a saturated request returns, i.e. the page size (the adapter currently GUESSES this from round numbers — `bolna._LISTING_PAGE_SIZES`); **(c)** whether the body carries `next`/`next_page_url`/`has_more`/`total`, and if it offers an opaque cursor instead of a link, the exact parameter name that consumes it. Until (b) and (c) exist, a complete-looking listing on a quiet pilot window is NOT RUN, never a pass. |
| 7 S | Post-call data fidelity | `completed` (not `call-disconnected`) carries total_cost + cost_breakdown, recording_url, extracted_data. Verify currency (USD cents), transcript parses into TranscriptTurn, and time-to-`completed` (~2–3 min claimed) against our 2-min lead SLO. |
| 8 S | KB + campaigns + tools + H1 handling [expanded, D-33] | Upload a Telugu FAQ to the rag_id KB (multilingual mode); measure retrieval quality + latency on-call. **Telugu is NOT named in their multilingual mode (Hindi/Tamil are) and the mode is immutable at KB creation** — if Telugu retrieval is poor, the external custom-function route is the fallback (TRD §6.2), so measure both in the same session. Test a custom function to our endpoint and record the tool-call p95 (**no timeout is documented — the ceiling is unmeasured**). Create a 10-contact batch; verify retry policy + per-contact statuses. **KB lifecycle, the two questions D-41's detach contract cannot answer from docs — Bolna publishes no OpenAPI spec, so the row shapes are hand-maintained claims:** (a) does `GET /knowledgebase/all` carry the AGENT LINKAGE we filter on? Our single account holds every tenant's agents, so `list_kb` attributes strictly — a row that does not name the agent is not counted, which means a missing linkage field silently reports every agent as having no knowledge base. (b) does `DELETE /knowledgebase/{rag_id}` also clear the AGENT's reference to it, or does the agent config keep a dangling `rag_id`? If the latter, detach grows a second call (an agent update) — it does NOT become optional. Capture both responses as adapter fixtures. **In-call working memory (H1, TRD §6.1):** does Bolna truncate or summarise conversation history at a window limit, and does it enable provider context caching on BYOK keys? Both drive the LLM leg on long calls. |
| 9 H | Compute region + residency [NEW, D-32] | Where does the call actually execute? (Recordings sit on S3 us-east-1 — storage ≠ compute, but both matter.) Get India data-residency terms + price in writing. This is the one axis where LiveKit beats Bolna on verified evidence today. |
| 10 H | Agency model | Confirm in writing that multiple end-clients under one account is permitted. **Verify the sub-accounts tier discrepancy**: the pricing page lists "Sub-accounts access" under Pilots, the docs call it Enterprise-only. If Pilots includes it, our tenancy model lands far earlier. |
| 11 H | The humans | Open two support threads (one technical, one commercial) during the pilot; record response time and answer quality. **This is the gate ThinnestAI failed** — a good product with unresponsive people is the same trap twice. |
| 12 H | Commercials in writing | **(a) the BYOK platform fee — the single number that decides ₹3–3.6/min; target ≤ ~₹1.5/min**; (b) whether volume tiers apply to BYOK; (c) INR/GST invoicing; (d) price-change notice period (60–90 days); (e) data-export commitment on exit; (f) recording retention + DPDP deletion API; **(g) is the built-in KB (`rag_id`) billed separately, or included in the platform fee? No KB line appears on the pricing page — we have INFERRED "included" and that inference is load-bearing for TRD §6.2 (D-33). Get it in writing, including any per-document/storage/query charge.** Anchors: their published bundled rate is 6.00¢→4.51¢/min; Vapi's comparable orchestration tax is ₹4.40/min (D-32). **OBSERVED Aug 2026, still ungated: the BYOK platform fee shows as 2¢/min ≈ ₹1.76 in the Bolna dashboard.** That is inside TRD §10's assumed ₹1.50–2.00 band but ~17% ABOVE this gate's ≤₹1.50 target, so the observation does NOT close (a) — a dashboard figure is not a commercial term, and the gap is worth ₹5,200/month at 20k platform-min and ₹15,600 at 60k (TRD §10.4). Open the negotiation on the ₹1.50 number with those two figures in hand. |
| 13 S | Concurrency ceiling | Pilots advertises 100 concurrent and two customers run 250+ in production (D-32); confirm OUR ceiling, behavior at the limit (queue vs reject + error shape), and the outbound dispatch rate limit (unpublished — measure it; it becomes our dispatcher config, FLOWS §5). Also ask Sarvam (BYOK-tier model concurrency) and Exotel/Vobiz (SIP trunk channels). Effective ceiling = MIN of all three — record all three. |

Parallel ask to Sarvam (not a Bolna gate, but it moves our cost model more than the
platform choice does): **is the Sarvam LLM genuinely free per token** — permanent,
promotional, or rate-limited? If durable it removes the R-04 Gemini-3.x step
(~₹0.55–0.65/min). Also pin Bulbul V3's "beta pricing" (₹30/10k chars) — beta prices move.

### Running it — 1, 2, 6 run on credentials alone; 4, 7, 8, 13 run on an inputs file; 3, 5, 9-12 are human

The table above is the specification; `scripts/pilot/` is the part of it a machine can
decide. Start with the shopping list, on day one and not on day three:

```
uv run python -m scripts.pilot reachability   # can this machine reach api.bolna.ai at all?
make pilot-preflight     # uv run python -m scripts.pilot preflight
make pilot               # DRY RUN of gates 1, 2, 6 — places no calls, spends nothing
```

**Run the reachability probe first.** It needs no key, no credit and no number, and it
answers the one question that invalidates the whole session: a sandboxed or corporate
network that refuses the CONNECT to `api.bolna.ai` blocks every API gate, for a reason
that has nothing to do with Bolna. (The environment this harness was written in is
exactly such a network.) It is also the first row of the preflight; exit 4 means
unreachable, and skipping it with `--no-network` reports it UNVERIFIABLE rather than
assuming it is fine.

Preflight names every missing credential and prerequisite, which gates each one blocks,
and where to get it; it reports a key as present or absent and never prints one. `make
pilot` executes gates **1** (webhook trust), **2** (API provisioning) and **6** (webhook
loss + poller recovery) through the `VoiceEngine` adapter — never raw HTTP, because the
pilot's job is to verify the adapter we will ship, not a curl that bypasses it.

Placing real calls requires an explicit opt-in and a ceiling, and refuses to run against
a production-shaped configuration:

```
uv run python -m scripts.pilot run --gates 2 --to +91XXXXXXXXXX \
    --yes-place-real-calls-and-spend-money --max-calls 2 --out pilot-results.json
```

Gate 1 needs the raw deliveries your tunnel received (`--webhook-capture <file>`,
repeatable); gate 6 needs the execution ids whose webhook you dropped
(`--missed-execution <id>`) plus what you saw with your own eyes
(`--attest gate6.call_continued=yes`, `--attest gate6.retries_observed=0`) — those two
are recorded as operator attestations, never as measurements — and the dashboard's own
execution count for the same window (`--attest gate6.executions_in_window=<n>`), which is
the ONE independent check on whether List-Executions truncated: our own listing cannot
testify about what it left out. **Exit 2 means "nothing
went red and nothing was verified either"**; only exit 0 is a pass. Every gate result is
PASS, FAIL or **NOT RUN**, and NOT RUN never renders as green.

What the harness found before any credentials existed, and what it therefore cannot do:

- gate 2's **`scheduled_at`** criterion is not expressible through `VoiceEngine.
  start_outbound_call`, and the Bolna adapter's `POST /call` body carries no such field.
  Gate 2 cannot report a full pass until the contract grows one.
- gate 2's **"attach number"** step cannot run through the adapter at all —
  `BolnaEngine.provision_number` raises `engine_capability_unverified` (M1 defers
  numbers to the telephony provider), so that step is a dashboard action, which is what
  "via API only, no dashboard" forbids.
- gate 2's **"update prompt"** can now be scored **APPLIED**, not only ACCEPTED. The
  contract grew a read-back (`VoiceEngine.get_agent` → `AgentSnapshot`), and gate 2 emits
  a second row, `update_prompt_applied`: `update_prompt` records that the vendor took the
  PUT, `update_prompt_applied` records that the agent the engine HOLDS carries the prompt
  we wrote (a marker in the prompt text, so the engine's own rendering — the prepended
  disclosure line — does not break the comparison). A 2xx write that changed nothing is
  now a red row instead of a green one, which matters most for the part of the prompt a
  client is legally answerable for. What it still does NOT prove is that a RUNNING call
  uses that prompt; the `user_data` round-trip row remains the live-call evidence, and
  the two are deliberately separate rows.
  **The read-back endpoint is itself an unverified vendor claim.** `GET /v2/agent/
  {agent_id}` was written from Bolna's OSS server (`bolna-ai/bolna` documents and
  implements `GET /agent/{agent_id}` returning the stored agent object) plus a search
  summary of their hosted v2 reference — their docs site could not be read directly, and
  they publish no OpenAPI spec. So record two things from the run: whether the GET
  answered 2xx at all, and whether the prompt came back where
  `bolna._agent_system_prompt` looks for it (`agent_prompts.task_1.system_prompt`). A 404
  there means OUR path is wrong, not that the vendor dropped the prompt — the row fails
  either way, which is the intended direction for an unverified endpoint.
- gate 8's **dangling-`rag_id`** question (D-41) is now askable through the adapter and
  is answered by the run rather than by a note. The read-back supplies gate 8's
  `agent_ref_reader` automatically (`knowledge.agent_ref_reader_from_engine`), so after
  the probe deletes the knowledge base it reads the AGENT object back and reports whether
  the handle survives. **What is still unknown is the field name**: nothing published
  says Bolna's agent object references a `rag_id` at all, so `bolna._AGENT_KB_REF_KEYS`
  is a guessed set of names and the adapter reports
  `AgentSnapshot.knowledge_base_refs_readable = False` when none of them appears. That
  declination is scored INCONCLUSIVE, never as a cleared reference — "we could not find
  the field" and "the reference was cleared" are opposite answers, and only one of them
  adds a second call to `detach_kb`. One captured agent payload settles it.
- gate 1's edge half (nginx rejecting a non-allowlisted source) needs an HTTP POST from
  another host against the deployed receiver; the harness exercises the in-app half only.
- gate 6's **pagination** criterion is now MEASURED as far as our side can measure it,
  and declared as an assumption for the rest. `list_executions` returns an
  `ExecutionListing`, not a bare list: `complete=False` plus a reason
  (`explicit_more` where the payload claims more, `full_page_suspected` where the row
  count lands exactly on a conventional page size, `page_cap_reached` where our own bound
  stopped a walk that was still producing, `next_link_loop` where a continuation URL
  repeated, `next_link_no_progress` where a new continuation re-served rows we already
  had, `empty_page_with_next` where a page carried no executions and still offered a
  continuation) is what the adapter says when it cannot vouch
  for the window, and `reconcile_executions` turns that into an alert, a metric
  (`reconciliation_listing_incomplete`) and a job result that does not read as a quiet
  tick. **What the pilot still has to settle is the vendor's behaviour itself** — whether
  Bolna paginates, at what size, and in what form. Nothing in-process can: a listing
  cannot report what it omitted, and a pilot window holds far too few executions to reach
  any plausible page size, so `complete=True` here means "nothing in the response
  suggested otherwise". The dashboard count (`gate6.executions_in_window`) is the only
  independent evidence, and until a saturated listing has been captured the page-size
  heuristic is a guess about round numbers rather than knowledge.
- gate 7's **currency** criterion is now answerable in part from our own snapshot.
  `BolnaEngine._cost` reads the currency the payload states and records
  `CostBreakdown.currency_stated` — True = the vendor said so, False = we fell back to
  the house assumption (`_ASSUMED_CURRENCY = "USD"` cents, read off docs.bolna.ai and
  never confirmed on a live account). A currency the adapter cannot convert is REFUSED
  rather than converted at the dollar rate, so a wrong cost basis cannot ship silently.
  The independent check remains the vendor's own reported total, supplied by the
  operator: a ratio of exactly 100 is the signature of the cents assumption being wrong,
  and every INR row inherits the factor. **What the pilot still has to settle is the
  `currency_stated=False` case** — if Bolna never names a currency, the assumption stays
  load-bearing and only the dashboard figure can falsify it.
- gate 7's **transcript** criterion now sees PARTIAL loss.
  `bolna.parse_transcript` returns `(turns, unparsed)` and the snapshot carries
  `transcript_lines_unparsed`, so a line the parser could not place — an unprefixed line
  before any turn exists, a prefix with an empty body — is counted rather than dropped.
  The harness scores any non-zero count, in addition to the total-failure signature (zero
  turns on a `completed` call that carried audio) and the per-turn structural defects. A
  COUNT, not the lines: transcript text does not cross the engine boundary except as a
  `TranscriptTurn` (hard rule 6).
- gate 7's **time-to-`completed`** has a post-hoc route, and it is an UPPER BOUND.
  `ExecutionSnapshot.billable_ready_at` carries the vendor's `completed_at` where the
  payload has one, otherwise the instant we OBSERVED the execution already complete —
  which is bounded by the poller's tick and by how long after the call anything looked,
  so it can only over-state. The harness therefore still prefers a LIVE poll from an
  operator-supplied disconnect instant when one is given. `now - ended_at` remains
  deliberately unused: it is a bound that grows with how long the operator took to run
  the harness.

**Which gates the harness can execute, precisely.** Nine of the thirteen are registered
in `scripts/pilot/`, in two classes, and the difference between them is what an operator
has to bring:

- **1, 2, 6 — credentials and a tunnel.** `make pilot` runs these and nothing else by
  default; they need the API key, and gates 1 and 6 additionally need the deliveries and
  execution ids named above.
- **4, 7, 8, 13 — plus one JSON inputs file each**, because their inputs are OBSERVED by
  a person rather than measurable from our side: gate 4's stopwatch samples and the
  pasted `latency_data`; gate 7's observed disconnect instant and the vendor's own cost
  figure off the dashboard (the dashboard figure is the only INDEPENDENT check on the
  currency: the adapter records whether the payload stated one, but where it did not,
  reading our own assumption back is the harness agreeing with itself);
  gate 8's Telugu retrieval scores, tool-call latencies, per-turn token counts and batch
  outcomes. Each reads `docs/evidence/gate<n>-inputs.json` (gate 4:
  `gate4-observations.json`), overridable with `CALEVATE_PILOT_GATE<n>_INPUTS`. **An
  absent file is NOT RUN with the path in the reason — never a pass, and never a zero.**
  Gate 13 also needs a call budget: it dials to find the ceiling.
- **3, 5, 9-12 are human and always will be**, and the harness says which kind rather
  than leaving a blank row: 3 and 5 are LISTENING gates (Telugu recognition quality;
  barge-in and end-of-utterance judged by ear), 9-12 are written answers and support
  threads. `--attest` records what a human observed, labelled as an attestation and never
  as a measurement.

Any gate with no implementation registered is still reported by number as NOT RUN, so a
slice that regresses out of the registry is visible rather than silently absent.

Deliverable: filled scorecard committed to `docs/evidence/bolna-pilot-scorecard.md`
(template in repo), with captured payloads saved as adapter fixtures. Passing closes the
D-31 gate and A-1/A-8; a red hard gate reopens the engine decision (no fallback engine
is designated — D-31).

## 3. Per-Client Regression & Eval Harness (the differentiator)

Principle (industry norm): run the suite on EVERY prompt/model/tool/KB change — a small
edit can break a working flow; behavioral coverage (task completed? interruption handled?
no hallucinated tool call?) is what generic uptime monitoring misses.

Structure per client:
- **Scenario suite** (start minimal, grow to 50–100): v1 mandatory five —
  (1) happy path (book/qualify end-to-end), (2) interruption/barge-in mid-sentence,
  (3) tool-call correctness (booking with valid slot), (4) out-of-scope ⇒ T4 refusal +
  follow-up tag, (5) compliance (disclosure spoken; DNC request honored; no cross-sell on
  service agent). Add per-vertical + red-team (injection attempts) as suite grows.
- **Fixtures**: 30+ recorded Telugu/Hindi/mixed utterances incl. hard names, numbers,
  addresses; replayed via engine web-call API or TTS-into-call.
- **Scoring**: transcription accuracy on entities; task success (assert on extraction
  output + tool calls); latency percentiles; LLM-judge rubric for tone/language.
- **Wiring**: suite runs in CI on prompt_versions publish and nightly against live config;
  red result blocks promote; report stored per run (client-shareable PDF = sales asset:
  "we regression-test your agent before every change").

## 4. Observability & Alerting

Dashboards: per-tenant call volume/answer rate/outcomes; latency stage breakdown
(stt/llm_ttft/tts_ttfa/turn p50/p95); post-call pipeline lag; webhook delivery health;
spend vs caps; KB retrieval hit-rates + knowledge-gap list (T4 queries).
LLM tracing (a trace per call, prompt version + token costs attached) is a **named gap,
not a component**: the Langfuse configuration was removed rather than left looking wired
(D-49, TRD §2), so nothing records per-call token cost or the latency breakdown today.

**Alerts, as built (D-49).** The sinks above were "WhatsApp/email to Sri" and for a long
while were neither — `alert()` wrote a structured ERROR log and stopped. It now still
writes that log FIRST and unconditionally (the durable record) and then delivers **by
email**, through the same transport as hot-lead notifications, on a daemon thread off the
request path. No WhatsApp sink: that is a BSP decision (see the open items in ROADMAP §6),
and a second delivery mechanism is a second thing to be broken on the night it is needed.

- **Configuration**: `ALERTS_EMAIL` plus an SMTP host. A non-local service booting with
  neither logs `alert_delivery_unconfigured`, and one with a recipient but no transport
  logs `alert_delivery_has_no_transport` — both at boot, so a deployment where alerts
  reach nobody fails §8's gate visibly rather than silently.
- **Noise bounds**: per-fingerprint repeat suppression keyed on `stage:code`, 15 minutes
  (Alertmanager's `repeat_interval`, tightened because there is one operator and no
  incident console), plus a global token bucket at 20/hour with a burst of 6. Both count
  what they drop and report the count in the next delivered body, so "still broken, 199
  times" never reads as "happened once". A FAILED delivery clears the suppression stamp —
  the window means "a human was told".
- **What it does not touch**: no outbox, no Redis, no database. The alarms that matter
  most are the ones saying those are broken.
- **What triggers one**: webhook failures > 3/5min; pipeline lag > 5 min; latency p95
  breach 15-min sustained; cap approaching (80%)/breached; complaint-spike on campaign;
  engine 5xx spike; nightly job failures; cert/domain expiry.
- **The host backup chain crosses a PROCESS boundary, not a vocabulary one.** Backups run
  on the host as `postgres`, outside every Python process, so they cannot CALL `alert()` —
  they emit the same shape (`failure_stage=HOST_BACKUP` with a stable code) to journald and
  stderr, and reach the same transport by subprocess: `notify.sh` → `alert-to-app.sh` →
  `python -m scripts.host_alert` → `alert()`. One vocabulary, one recipient, one transport,
  two ways in. `BACKUP_ALERT_COMMAND` defaults to that relay, so **a host that configures
  nothing still pages**; an override stays ONE command, because two delivery paths are two
  dedupe windows and the day one stops nobody notices.

  Each relay is a fresh process, so `alert()`'s in-memory suppression window cannot apply.
  The window is therefore a stamp file per fingerprint, with the INTERVAL imported from
  `alerting` rather than copied; a failed delivery does not open one, and an unwritable
  state directory fails OPEN. Without it, a broken chain checked every fifteen minutes is
  ~96 mails a day, which becomes a filter rule, which is an alarm reaching nobody again.

  What remains to do on the host is `ALERTS_EMAIL` plus readable `SMTP_*` — proved by
  `notify.sh probe "delivery test"` putting mail in a real inbox, since local delivery
  success is transport acceptance, not receipt.

- **The dead man is the harder half, and it is now built (D-54).** `backup-health.sh`
  checks the SCHEDULE (a timer missing, inactive, or armed and silent past its window —
  the failure `OnFailure=` structurally cannot see, because nothing ran so nothing failed)
  and its OWN heartbeat (a gap reported when it resumes, dated so an operator knows which
  nights to check). Neither survives the host being off or off-network, systemd not
  running, or the alert path being broken beyond us: each removes the observer along with
  the observed. So a run in which EVERY check passed pings a hosted dead-man check
  (Healthchecks.io, `BACKUP_HEARTBEAT_URL`, one GET, no payload) and **the external
  monitor pages when the pings stop**.

  **Read the polarity correctly, because it is the opposite of every other alarm here:**
  a failing run pings NOTHING, and neither does a dead box. Silence is the alarm. There is
  deliberately no failure ping — failure already has a path (journald + email), and a
  second one would mean two dedupe windows on one fact, while the failures worth having a
  dead man for cannot send anything at all.

  Configure the check at 15-minute period / 1-hour grace (three missed runs, the same
  number `MAX_HEALTH_GAP_S` uses) — see `infra/backup/README.md` §5. The URL is a
  CREDENTIAL: anyone holding it can silence the alarm, so it comes from the secrets
  manager, is never logged (operator output names a digest prefix), and unset means the
  heartbeat is a stated no-op rather than a silent pass. A heartbeat that cannot be sent
  is logged loudly as `backup_heartbeat_undelivered` and **does not** fail the backup or
  send mail — the consequence is the dead man firing, which is the correct outcome.
  What to do when it fires: `runbooks/backup-heartbeat-silent.md`.

## 5. SLOs (v1)

Lead visible post-hangup ≤ 2 min (99%); webhook ack < 500ms; dashboard p95 < 800ms;
voice p50 ≤ 1.1s; monthly voice-runtime availability 99.5%. Review monthly; tighten with
scale.

**`webhook_ack_slow` is usually a CAPACITY alert, not a bug (D-55).** The receiver's
per-delivery cost is fixed and asserted in CI; what moves the ack is how many deliveries
are in flight on one process, and `ack_p50 ≈ in-flight ÷ acks-per-second-per-process`
(≈250/s on the measurement host). A burst of them at the end of a campaign — 250 calls
hanging up together — is the designed shape of the traffic, not an incident. So triage in
this order:

1. **Is it wide or is it slow?** A FLAT distribution (p50 ≈ p95 ≈ max) is a queue: too
   many deliveries per process. A long tail with a normal p50 is a dependency —
   the `webhook.inbox_claim` span says which.
2. **Wide → add processes**, using the arithmetic and the connection budget in
   DEPLOYMENT §2a. It is a `--workers` change and a restart of one deployable, and
   voice-runtime's deploy is deliberately decoupled from `api` for exactly this.
3. **Nothing is dropped while you decide.** The 500ms budget is the alert; the 2-second
   `_DURABLE_DEADLINE_S` is the abandon, and past it the answer is a 503 and the
   reconciliation poller (D-31), never a false ack.
4. `webhook_claim_timeout` in the same window means the deadline IS firing — that is no
   longer a capacity warning, it is calls waiting on the 10-minute poller. Treat as an
   incident.

## 6. Routine Ops Calendar

Daily: alert triage; pipeline DLQ empty; spend anomalies. Weekly: regression nightly
results review; knowledge-gap report → KB updates; pipeline/latency trend. Monthly:
invoice run; margin per client; rate-card check. Quarterly: restore drill (prove RTO 4h/
RPO 15min) — `runbooks/backup-restore-drill.md`, alternating the R2 PITR chain and the
offsite dump chain, result recorded in `docs/evidence/`; access review; secret rotation;
regulation/pricing re-verify; adapter conformance run against Bolna (keep the exit door
oiled).

## 7. Runbooks (summaries; full steps in /runbooks)

**Written procedures.** Every fact in these is grep-verified against the tree, so where
one differs from a summary below, the runbook is the authority.

- **"Our calls have stopped"** — `runbooks/calls-stopped.md`. The ordered diagnostic for
  the eleven conditions behind one symptom: big red switch, load-shed mode, Calevate's own
  TM registration (blocks every tenant at once), the admin spend cap, the client's own
  spend cap, `spend_state.capped` and the trap in clearing it, an empty prepaid wallet,
  the client's PE registration + TM link, subscriber KYC (`self_serve`/`trial` only), the
  campaign's consent provenance, template, number or a DNC hit, and the first-campaign
  manual-review hold (D-51) — `self_serve`/`trial` only, refusing at launch AND at every
  dispatch tick as `first_campaign_review_pending` / `first_campaign_review_rejected`.
  The two human-decision holds share one step, which opens with the queue
  (`GET /v1/admin/compliance/holds`) because that answers "is a human the blocker?" for
  every account at once. Marks which of these a client can self-serve out of.
- **Campaign is not dialling** — `runbooks/campaign-stall.md`. The dispatcher's own
  failure modes: tick verdicts, line-pool exhaustion, per-tenant ceiling, contact states,
  the per-dial gate.
- **"You called someone who asked you not to"** — `runbooks/dnc-complaint.md`. DNC
  complaint or TRAI/DLT escalation; the answer is a timeline, not a fix.
- **Campaign follow-up never goes out** — `runbooks/campaign-escalation-refused.md`.
  `escalate_campaign_contact` refusals, split by the line the code itself draws: the ones
  that page a human (`no_provider_configured`, `provider_not_implemented`, template
  failures, ladder exhaustion) and the lawful ones that deliberately do not
  (`recipient_not_opted_in`, `whatsapp_disabled`, every `blocked_*` from the dispatch
  gate). Covers both states of the `messaging` consent purpose.
- **Top-ups and payments** — `runbooks/topup-payments.md`. `payment_capability()` and what
  each refusal means; server-side order creation is NOT implemented
  (`PROVIDER_CREATES_ORDERS = False`) and what to tell a client who wants to pay today;
  the Razorpay signing scheme and payload paths are UNVERIFIED against a live account, so
  the first real payment is an attended test, not a routine.
- **Knowledge base out of sync with the engine** — `runbooks/kb-out-of-sync.md`.
  `kb_engine_ref_unknown` vs `kb_engine_out_of_sync`: same disease, different cures, and
  the wrong cure leaves a client's agent quoting old prices. Includes the manual
  vendor-side withdrawal and its two unverified pilot-gate caveats.
- **Local database cannot reach head** — `runbooks/stale-dev-database.md`. The
  `credit_ledger` CONCURRENTLY unique index that cannot build over permanent pre-cutoff
  duplicates hard rule 4 forbids deleting; a fresh database and `make db-reset`; and why
  `alembic stamp` past it defeats the ancestry gate the index tests depend on.
- **The backup heartbeat went silent** — `runbooks/backup-heartbeat-silent.md`. The one
  alarm here that arrives as an ABSENCE: the external dead man (D-54) pages because pings
  stopped, which means the host is gone, systemd is gone, a backup check is failing, or
  the ping cannot leave — four different incidents behind one notification, ordered by how
  fast each is to rule out. Read this one BEFORE `database-restore.md`: the dead man says
  monitoring stopped, never that data is lost.
- **Restoring the production database** — `runbooks/database-restore.md`. Point-in-time
  recovery to a chosen instant (wal-g from R2), single-table recovery from the offsite
  encrypted dump, and the whole-VPS-is-gone path. Includes the six checks that prove a
  restore actually worked rather than merely completed, the `recovery_target_time`
  timezone-abbreviation trap, and the step everyone forgets: **a restore un-erases**, so
  DPDP erasures completed after the recovery target must be replayed from the preserved
  pre-restore cluster before anyone can reach the new one. **Never executed against a real
  cluster** — the mechanism in `infra/backup/` has been applied to nothing.
- **Quarterly restore drill** — `runbooks/backup-restore-drill.md`. The §6 quarterly item,
  made executable and recordable: alternating chains (R2 PITR one quarter, offsite dump the
  next), measured RTO/RPO, a deliberate induced archiving failure to prove the detector
  fires, and a record template committed to `docs/evidence/restore-drill-YYYY-QN.md`.
- **Object-store lifecycle rule** — `runbooks/object-lifecycle.md`. Applying and
  validating the recording-expiry policy, and what it does NOT prove.
- **Events not reaching a client's CRM** — `runbooks/webhook-delivery-failures.md`. Outbox
  → ARQ → delivery forensics, plus the client-side checks to hand them.
- **A deploy failed** — `runbooks/deploy-failed.md`. Ordered by WHICH step of
  `scripts/vps-deploy.sh` failed, because the recovery for a failed build and a failed
  container swap are different procedures. The section worth reading before you need it is
  §3: a failed migration leaves the database at the last revision that fully applied, the
  old containers can serve on it (hard rule 8 is what guarantees that), and **there is no
  automatic downgrade** — downgrading can drop a column something has already written to,
  so it is a judgement rather than a step. **Never executed**; nothing in this repo has
  been deployed to anything (DEPLOYMENT §4d).

**Summaries only** (no written runbook yet):

- **Every engine webhook is 401ing** (`webhook_source_rejected`): read the alert's
  `detail`, because the two reasons have different cures and the same symptom.
  `source ip not allowlisted` = the vendor renumbered; rotate `BOLNA_WEBHOOK_SOURCE_IPS`
  and restart voice-runtime (calls are not lost, the 10-minute poller carries them —
  D-31). `client ip not established` = **the EDGE is broken, not the vendor**: outside
  `APP_ENV=local` the receiver takes the client address from `CF-Connecting-IP` and from
  nothing else, refusing when it is absent or is not a single literal IP
  (`apps/voice-runtime/engine_intake.py::client_ip`). Two nginx facts must hold for that
  header to mean anything, and both live in `infra/nginx/snippets/`:
  `real_ip_header CF-Connecting-IP` + `real_ip_recursive on` + the `set_real_ip_from` CF
  ranges (`calevate-origin.conf`), and `proxy_set_header CF-Connecting-IP $remote_addr`
  (`calevate-proxy.conf`) so our own nginx — the single trusted hop — is what writes the
  header the app reads. Check those before touching the allowlist. A deployment that
  terminates TLS anywhere other than this nginx, or puts a second proxy in front of the
  container, breaks the hop count the control is built on and must update `client_ip`
  in the same change.
- **Engine outage**: numbers fail over to client phones (provisioned fallback); status
  banner in dashboards; reconcile calls post-recovery; if >4h, activate Bolna adapter for
  new calls (numbers re-point), inform clients.
- **Webhook signature failures**: treat as attack until proven config drift; block source,
  rotate secret, audit deliveries.
- **Data breach (suspected)**: contain (revoke keys, rotate, big red switch if needed) →
  scope via audit_log/webhook_deliveries → classify under DPDP → notify Board + affected
  principals per Rules timeline → postmortem in repo.
- **Runaway campaign**: auto-pause on cap/complaint alarm; verify DNC + template status;
  client comms template ready.
- **Deletion request**: FLOWS §9 procedure; 7-day internal SLA; proof certificate issued.
- **Model retirement (e.g., Gemini 2.5 on 16 Oct 2026)**: switch config on staging →
  full regression suite → promote per client → note in decision log.

## 8. Pre-Launch Checklist (client #1 goes live only when all green)

Entity decided → DLT PE registered (or inbound-only mode explicitly accepted) ·
engine verification scorecard passed · agent passed test-call gate + regression five ·
disclosure + consent verified on a real recording · caps set · backups verified ·
alerts firing to Sri's phone · client owner trained on Leads table (15-min session) ·
DPA + privacy notice signed · invoice template ready · **admin-realm MFA switched on in
the admin Clerk application**.

**Three of those items have a pass condition that deployed code does not satisfy on its
own**, stated here because they have previously been read as done:

- **Admin-realm MFA switched on** = a DASHBOARD change in the ADMIN Clerk application
  (the one whose publishable key is `NEXT_PUBLIC_CLERK_ADMIN_PUBLISHABLE_KEY`), not a
  deploy. The API already refuses any admin-realm session that did not complete a second
  factor (`core/auth.py::verify_token`, SEC-COMP §5), and that refusal is the enforcement
  — but it can only refuse; it cannot make Clerk OFFER a second factor. Two settings, and
  both must be checked by a human against a live tenant, because neither is observable
  from this repo:

  1. **Enable a second-factor strategy and require it** — turn on TOTP (authenticator
     app) and backup codes in the admin application's user-and-authentication settings,
     and turn on its "Require MFA" organization/instance setting so operators are walked
     through enrolment at sign-in. Without this, every operator meets `403 mfa_required`
     with no way to satisfy it: the console explains the refusal, and that is all it can
     do. Enrol the first superadmin BEFORE the setting goes live, or the first person to
     sign in is locked out of the console that would let them fix it.
  2. **Leave the admin application on the DEFAULT session-token claims.** The check reads
     the `fva` claim, which is present on the default token and absent from a custom JWT
     template that does not list it. A template that drops it fails closed —
     `403 mfa_claim_missing` on every admin route — which is the safe direction and an
     outage all the same. If a template is ever needed on this realm, `fva` goes in it.

  **Verification is a two-person, five-minute check against staging**, and it is the only
  proof that counts: sign in as an operator WITHOUT a second factor enrolled and confirm
  `GET /v1/ops/platform` answers 403 `mfa_required`; enrol, sign out, sign in again, and
  confirm the same call answers 200. Record the result in `docs/evidence/` the way the
  backup drill is recorded — an untested auth control is a claim, not a control.

  **NOT DONE, and deliberately**: requiring a FRESH second factor (Clerk reverification)
  for the high-risk actions BACKEND-PATTERNS §7 lists — the big red switch, cap raises,
  raw-transcript access. Those carry per-action `X-Confirm-Action` step-up today, which is
  a different control and is retained (SEC-COMP §5); raising a real reverification prompt
  needs a flow in `apps/web` that does not exist, and gating an incident lever on a prompt
  nobody can answer at 3am is how a control gets switched off. It needs a decision-log
  entry before it is built.

- **Backups verified** = `runbooks/backup-restore-drill.md` has PASSED once, with the
  record committed to `docs/evidence/`. The existence of `infra/backup/` does not tick it:
  nothing in that tree has been applied and no wal-g command has ever been run, so until a
  drill record exists the §5 RPO is a design intent rather than a measurement.
- **Alerts firing to Sri's phone** = `ALERTS_EMAIL` plus a reachable SMTP host in the
  environment, on the app hosts AND on the database host (where the same configuration is
  what lets the backup relay page). A service booting without them says so — see §4 — and
  local delivery success is transport acceptance, not receipt, so the proof is a probe
  message landing in a real inbox.

  **That gate covers alarms that are SENT. The dead man covers the ones that cannot be**
  (D-54), and it is armed separately: `BACKUP_HEARTBEAT_URL` set on the DATABASE host from
  the secrets manager, the vendor-side check created at 15-minute period / 1-hour grace
  with the notification going to the same person, and the drill's §7.8 proving both halves
  — a ping arriving when the chain is healthy, and the check going red after the pings are
  stopped on purpose. Unset is not a quiet default: `backup-health.sh` states it in the
  journal, and every backup can be perfect while nobody outside this host is watching.
