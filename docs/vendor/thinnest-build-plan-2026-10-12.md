# Build plan: ThinnestAI's 11-12 Oct answers, 12 Oct 2026

What we build from ThinnestAI's answers (`thinnest-replies-2026-10-12.md` §4 and §6), with the
founder's decisions of 12 Oct 2026. Each workstream ends with its own tests; the whole batch
ships after a green coverage ratchet (founder: "run it before the push").

## Founder decisions, 12 Oct 2026

| # | Question | Decision |
|---|---|---|
| F1 | Where agents answer | **Phone only.** Send `voice.surfaces: ["phone"]` on every agent and repair drift. Supersedes D-720's "information, never drift" for surfaces. |
| F2 | Top-up fee | **2.36%**, from Ashutosh's email of 12 Oct (VENDOR-STATED). Replace the 10% / 9% constants and correct past cost rows with compensating entries. |
| F3 | Voice settings a client may change | **"Are you still there?" prompt, filler lines, background office sound.** Everything else is a platform value. |
| F4 | End phrases | **Not used.** ThinnestAI matches them anywhere in what the caller says, so a short phrase could end a call mid-sentence. `endPhrases` is sent empty and drift-checked. |
| F5 | 20,000 limit | **Raise the limit and let pinned facts take up to 3,000 characters.** D-752 dropped no rule, so nothing is restored. |
| F6 | A client's own action in a test chat | **Answers success and writes nothing**, like do-not-call, call-back and cancel. |
| F7 | Call lines | **A cap per client, set by admin: paid 2, trial 1.** |
| F8 | Ratchet | **Green before the push.** |
| F9 | Silence prompt defaults | **Ask after 8 s, once; hang up after 20 s of silence.** Clients may change them. |
| F10 | Greeting | **Callers may interrupt the greeting** (`greetingUninterruptible: false` on every agent). |

Platform values sent on every agent (not client settings), so a console change reads as drift:
`interruptWords` 3, `holdShortSpeech` true, `neverInterrupt` false, `greetingUninterruptible`
false, `thinkingAtTurnEnd` false, `endPhrases` []. Filler timings stay ThinnestAI's defaults
(`thinkingDelayMs` 900, `thinkingRepeatMs` 2500), sent explicitly.

## Workstreams, in build order

**W1. Voice catalogue paging (bug).** `engine/thinnest.list_own_key_voices` walks every page of
`GET /byok/voices` and returns `complete`; `agents/hosted_voices` never withdraws a voice on a
partial listing (and alarms instead); our own clones are marked as ours. Tests: a two-page
listing, a partial listing that withdraws nothing, an own clone. 2-3 h.

**W2. Instructions limit 20,000 and pinned facts 3,000.** `engine/thinnest.INSTRUCTIONS_MAX_CHARS`
to 20,000 with the vendor answer as its source; `agents/prompt_routes` `max_length`;
`lib/api/prompts.ts`; `teach/pinned.MAX_PINNED_CHARS` 1,500 → 3,000; `tests/
thinnest_publish_limits_test`, `agent_prompt_budget_test` (owner reserve re-derived),
`prompt_size_test`; docs (THINNEST-INTEGRATION, the D-752 row's limit). The Script page meter
already reads the limit from the API. 2-3 h.

**W3. Phone only.** `voice.surfaces` sent on create and update, read back and repaired in the
settings sweep (`agents/engine_settings.AGENT_SETTING_LABELS` gains `surfaces`); "phone" is sent
only once a number is attached, since ThinnestAI refuses it otherwise (409
`phone_number_required`), so an agent with no number is sent `[]`. Whether `[]` is accepted,
and whether attaching a number later still adds "phone" by itself, is checked against the live
API reference before this is written; if either fails, the build stops and asks. `engine/thinnest.py`'s D-720
comment and the admin drift panel's "information only" note change. 1-2 h.

**W4. Top-up fee 2.36%.** One constant `THINNEST_TOPUP_FEE = 0.0236` (VENDOR-STATED, email
12 Oct 2026) replaces `THINNEST_PAYG_TOPUP_FEE` and `THINNEST_WALLET_TOPUP_FEE`; the Clear and
Studio cost floors re-derive from it; `engine_minutes.thinnest_topup_fee` stops depending on the
band; the plan-label map, keyed by fee value, becomes one label. Past rows: a compensating
`usage_events` row per call whose minute row carries a fee above 2.36% (negative amount = the
excess), appended under the tenant credit lock like the D-723 restatement (hard rule 4, no
UPDATE). The charge reconciler expects `costMicro × 1.0236`. Ops panel text, OPERATIONS T-14,
PLATFORM-CONFIG, ROADMAP row. Tests: floors, meter, restatement, reconciler. Half a day.

**W5. Test chats.** `worker/engine_actions` reads `X-Test-Chat: true`: do-not-call, call-back,
cancel and every client action answer success and write nothing, logged as a test; a request
with no `X-Call-Id` and no test marker keeps today's refusal. Tests per action. 2-3 h.

**W6. Renting a number safely.** `engine/thinnest_numbers` sends our purchase id as
`Idempotency-Key`; a 409 `idempotency_in_progress` is read as "maybe bought" and resolved by
reading the number back, never as "nothing bought". OPERATIONS T-19 closed. 1-2 h.

**W7. Voice settings.** The adapter sends, reads back and repairs the platform values above and
the three client settings; `agents/call_handling` grows the client settings on the D-751 pattern
(agent → account → Calevate default; `GET`/`PATCH /v1/agents/{id}/call-handling`,
`GET`/`PUT /v1/organization/call-handling`, admin twins):
- silence prompt: ask after N seconds (5-180, default 8), times (1-5, default 1), hang up after
  N seconds of silence (5-180, default 20), the client's own prompt line (up to 120 characters,
  empty = ThinnestAI's in the caller's language);
- filler lines: up to 8 lines of 60 characters, empty = ThinnestAI's;
- background office sound: off, "office" or "office-quiet", volume 0.05-1 (default 0.15).
A migration adds the columns to `agents` and `organizations` (reversible, RLS already on both).
The agent's Call handling page and Settings > Call handling get the controls, in plain words,
naming no vendor. A change queues the D-720 live apply. 1-2 days.

**W8. Model price bands from ThinnestAI.** `read_catalogue` reads `callTier` and
`callPricePerMinuteMicro`; the admin model list shows them and flags a recorded band that
disagrees. The operator-attested rate still bills (hard rule 7). Half a day.

**W9. Call lines per client.** Paying clients: `PATCH /customers/{id}` with `allottedCallLines`
(default 2) at provisioning and on change, read back and repaired. Trial accounts live in our
developer workspace, which `allottedCallLines` cannot split, so the trial cap of 1 is enforced
in our own dial gate (active calls per tenant). Admin client page: "Calls at once" field.
Migration for the per-client value. Half a day.

**W10. Docs.** OPERATIONS T-19 and T-28 answered; `workers/engine_charges.py`'s "UNVERIFIED"
usage-id note settled; Studio needs Pro; `gpt-oss-120b`; THINNEST-INTEGRATION's `endCallOnFinish`
line; fee text; ROADMAP decision rows for F1-F10. 1 h.

Not in this batch: test-chat cost metering (needs ThinnestAI's per-reply price),
`callInstructions` (needs their built-in rules' text), the Gemini ₹1 set-up (needs their API
answer and the founder), a sweep for agentless forwarded calls (D-743).

## Order of work and checks

W1 → W2 → W3 → W5 → W6 → W4 → W8 → W9 → W7 → W10, each with its targeted tests in a container
against the scratch database. Then lint, mypy, the OpenAPI snapshot, `check_list_bounds`,
`check_job_wiring`, the import contracts, the web typecheck and tests, the shipped-modules
import guard, and the full coverage ratchet. Two migrations (W7, W9) mean the deploy needs a
`pg_dump` first.

## After the deploy, on the VPS

- Every live agent re-publishes once (surfaces, voice settings, 20,000 limit).
- `scripts/prompt_size.py --all-live` shows the new limit.
- The fee restatement runs within the hour; its rows appear in `usage_events` with
  `meta.kind = 'engine_topup_fee_correction'`.
