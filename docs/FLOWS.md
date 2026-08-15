# Calevate — Core Flows

Version 1.0. Each flow lists: trigger → steps → failure handling → owner surface.
URLs: admin console = admin.calevate.tech; client app = app.calevate.tech/c/<slug>/…

---

## 1. Client Onboarding (Admin Wizard)

Trigger: Sri opens Admin → New Client. Draft state saved at every step (resume anytime).

1. **Profile**: business name → slug auto-generated (immutable; reserved-word check),
   vertical template pick (clinic | real_estate | insurance | education | custom),
   billing email, owner contact.
   - **A name we cannot build a URL from is ASKED about, never guessed.** `slugify` folds
     everything outside `[a-z0-9]` away, so every character of a Telugu or Devanagari
     business name disappears — which on a Telugu-first product (D-36) is the ordinary
     case. It used to substitute the constant `client`: the FIRST such business silently
     took `/c/client`, immutable and in every URL their staff types, and the SECOND was
     refused `slug_taken`, a 409 naming a slug nobody had entered. Both the wizard and
     the self-serve form now answer `slug_not_derivable` with the `slug` field named, and
     both screens ask for it before the POST. Transliteration is the nicer answer and is
     not available (no ASCII-folding library is installed and adding one to the tenant
     path is a hard-rule-9 decision, not a slug fix).
   - **The account and the record of who created it commit together.** The audit row is
     the birth transaction's last write via `create_organization(on_created=…)` — the
     same hook self-serve signup uses — rather than a second transaction that could fail
     on its own and leave a client account nobody recorded creating.
   - **Two operators racing one slug get one account.** The availability probe runs in
     its own transaction and can be passed by both; the UNIQUE index is the arbiter, and
     its violation is translated back into the same 409 the probe would have given.
2. **Plan**: setup fee, retainer, included minutes, overage rate, hard caps → plans row.
3. **Intake (the real work)**: guided form collecting business hours, address/branches,
   services + prices, top FAQs, staff names/pronunciations, booking rules, escalation
   contacts, languages. Output feeds T0 compiled context + KB seed + prompt generation.
4. **Agent draft**: system prompt generated from intake (template + LLM assist), reviewed/
   edited by admin; disclosure line auto-inserted (non-removable); extraction schema
   pre-filled from vertical template, edited per client; voice/language/model picks.
5. **Knowledge**: paste text → chunk preview → admin approves → publish, which attaches
   it to the engine KB (adapter) and recompiles T0. Same path and same limits as §7,
   which is the one description of it — PDFs and URLs are refused by name until an
   ingestion worker exists, and there is no embeddings job of ours (D-28/D-33).
6. **Number & compliance** (see §10 for the full model): inbound DID provisioned via
   adapter API (no SIMs — numbers are virtual, ~₹/hundreds/month rental, one-per-client
   mandatory); existing client number handled by call-forwarding to the DID (porting only
   later, never in onboarding critical path). If outbound intended: classification decided,
   client's own **PE registration** initiated (~₹5,900, we handle it — part of setup fee),
   DLT voice template drafted/submitted, series selected (140 promotional / 160-standard
   service). Blocked until Calevate's TM registration exists — wizard shows compliance
   status explicitly.
7. **Test-call sign-off [GATE]**: "Call me" button dials admin's phone with the draft
   agent; regression mini-suite (happy path + interruption + tool call + disclosure check)
   must pass; latency numbers recorded. Only then: Publish (staging → live promote).
   - **The GATE is not built and the PUBLISH is.** `POST /v1/admin/tenants/{id}/agents/
     {id}/publish` had been mounted and reachable for weeks with no caller in either
     realm — every other publish path is a RE-publish guarded on the agent already being
     live, so an agent minted by step 1 could not be put on the engine from any screen.
     The console's "Voice platform" panel (`/admin/tenants/…/agents/…/prompt`) is that
     caller. It says in as many words that it publishes and signs nothing off: the test
     call and the regression suite are pilot gate work and **externally blocked** on the
     engine and DID vendor accounts, not on code here.
   - **An agent with no script is refused, never placeholdered.** `publish_agent` used to
     substitute `"You are a helpful receptionist."` for a missing prompt — an English
     sentence with no hours, prices or business name, on a Telugu clinic's line, behind a
     200 that read `live` on every screen after it. It now answers `agent_has_no_script`
     and writes nothing (no engine ref, no routing row). Step 3 is what clears it.
8. **Invite client**: creates invitations row → email with single-use 72h link →
   client sets password → membership(owner) created → lands on dashboard tour.
   - **One live token per address, in BOTH realms.** The two refusals — the address is
     already on the team, and an unused invitation for it already exists — belong to
     `admin.service.create_invitation`, the one statement that mints the row, rather than
     to the client-realm caller that used to hold them. The wizard's Create-invite button
     pressed twice was putting two live owner credentials for one account into one inbox.
   - **A CLOSED account can be given no key, and can have none redeemed into it.**
     `admin.service.assert_account_open` is asked at both ends — the one statement that
     mints the row and the one that burns it — because a rule enforced at only one end of
     an invitation is a rule with a hole in it. A churned or soft-deleted tenant answers
     409 `account_closed` (the dial gate's own rule name for the same state); a tenant id
     that names nothing answers 404, where it used to be an FK violation escaping as a
     500. A refused redemption rolls back, so the invitee's single-use link is still
     redeemable. **`suspended` is deliberately NOT refused**: suspension stops outbound
     dialling only, and an account suspended over non-payment is exactly when someone
     needs to add the person who will pay.
   - Because the refusal is real, the console has the exit: `GET`/`DELETE
     /v1/admin/tenants/{id}/invitations[/{id}]` list and cancel the unredeemed links
     (addresses masked). It cannot be done by impersonation — D-22 makes that read-only —
     and the client-realm revoke has nobody to press it, since the owner invite is issued
     before anyone can sign in. A cancel that races an acceptance is refused (404): the
     person is a member now, and removing them is a different act.

Failure handling: every step idempotent; engine failures surface with retry; nothing
client-visible until step 8.

## 2. Client Auth & Access

Auth is Clerk (D-37 — reaffirmed against self-building; the decisive argument is that
RLS trusts `tenant_id` from a verified session, so an auth defect is a cross-tenant
breach). Two Clerk applications, never sharing session logic: **admin realm**
(invite-only, signup DISABLED) and **client realm** (self-serve signup enabled).
Custom domain `accounts.calevate.tech` so the flow is ours end to end.

**Three ways into the client realm (D-34 — both motions supported):**
1. **Self-serve signup** — email/password or **Google OAuth** → Clerk creates the user →
   our webhook mirrors it into `users` → org-create step (name + slug, validated against
   `reserved_slugs`) → `organizations` row with `plan_tier='self_serve'` → owner membership.
2. **Admin invite link** — admin console issues an invitation for an existing or new org;
   accept path: token hash lookup, expiry + `used_at` check, **burn on success**; resend
   invalidates the prior token. This is how MANAGED clients (and extra staff on any org)
   get in.
3. **Managed onboarding** — the admin wizard (§1) creates the org first, then invites the
   owner. Same invitation machinery as (2); the difference is who does the setup, not the
   auth path.

**There is no Clerk ORGANIZATION to keep in step.** Creating a client touches Clerk's
`users` mirror and nothing else: D-10's tenancy is flat and admin-driven, so
`clerk_webhooks.py` acknowledges `organization*` events and ignores them rather than
inventing a tenant from an upstream one. Tenant birth is therefore a single Postgres
transaction (org + retention policies + agent + extraction schema + tier + owner
membership + audit row), not a two-system distributed transaction — the only cross-system
ordering left is that the `user.created` mirror must land before an invite can be
accepted or a self-serve org created.

**Clerk ↔ our DB (D-37):** Clerk authenticates; it does **not** own our data model.
Webhooks (`user.created/updated/deleted`, `organizationMembership.*`) mirror identities
into `users` / `memberships`; our `organizations.id` remains the tenant key that RLS uses.
Never derive `tenant_id` from a client-supplied value — only from the verified session's
org claim, resolved against our own tables.

**Never emailed:** credentials. Invitations carry a single-use token, nothing more.

- Login → org resolution → redirect to `/c/<slug>/dashboard`. Direct hits to `/c/<slug>/*`
  without a session → login with return-to. A user in multiple orgs gets an org switcher.
- Roles: owner sees everything incl. billing; staff sees dashboard/calls/leads only,
  redacted transcripts, no exports of raw data.
- **Self-serve accounts start restricted (R-11):** calling is gated until the org has a
  KYC-verified number, and the **first campaign of every self-serve account is held for
  manual review**. Platform-fixed calling hours and DNC scrub on every dispatch path apply
  to both motions and are not user-editable.
  - As built (D-47), the verification is of the **business**, not of a number:
    `kyc_records` holds one row per tenant, the dial gate refuses a `self_serve`/`trial`
    tenant with `kyc_missing`/`kyc_not_verified`, and — because buying a number is gated
    for every tier — a number this org holds was necessarily bought under a cleared
    verification. Inbound answering is never gated.
  - **The manual-review hold ships** as `first_campaign_reviews` — one decision per
    TENANT, not a flag on a campaign row. The gate asks about the account, so a second
    campaign launched while the first is held is refused by the same rule, and deleting
    the held campaign does not release anything; the campaign an operator actually read
    is recorded as evidence (`reviewed_campaign_id`, `ON DELETE SET NULL`). Absence of a
    row means held — there is no `pending` state to disagree with it. Refusals appear in
    the launch preview and at dispatch as `first_campaign_review_pending` /
    `first_campaign_review_rejected`, so a withdrawn release stops a RUNNING campaign at
    the next tick. Released once, no later campaign is refused on this rule: the
    requirement is review of the FIRST campaign, and the ordinary gates carry the rest.

## 3. Inbound Call Lifecycle

caller dials client number → engine answers with agent →
1. Disclosure line (AI + recording notice) plays first — always.
2. T0 context already in prompt; conversation proceeds; tools available per agent:
   `search_knowledge_base` (our RAG endpoint / engine KB in v1), `book_appointment`
   (calendar), `transfer_call` (warm to client staff during business hours),
   `add_to_dnc`, `end_call`.
3. Unknown/out-of-scope (T4): agent says it doesn't know, offers callback, tags call.
4. voice-runtime receives interim events (call.started etc.) → creates calls row
   (status in_progress) → live tile on dashboards.
5. terminal-status webhook (Bolna: fires on status transitions; UNSIGNED — verify
   source IP + dedupe per TRD §5) or poller detection → wait for/confirm `completed`
   status (cost, recording_url and extracted_data are null before it, ~2–3 min
   post-disconnect) → Get Execution fetch (transcript, recording URL, USD-cent cost
   breakdown → INR conversion) → persist → enqueue post-call pipeline (TRD §8):
   recording copy (runs FIRST regardless — engine URL longevity is not our system of
   record) → redaction → extraction → lead upsert → metering → notifications.
   Repeat-caller context: the engine's incoming-call webhook lets our response inject
   caller context (name, prior interactions, lead fields) into the conversation — the
   lookup must answer in well under their ~5s webhook budget.
6. SLO: lead + summary visible in client dashboard < 2 min after hangup.
After-hours: agent runs 24/7 by default; "after_hours" flag set from business_hours →
dashboard "after-hours captured" metric; escalation rules can differ after hours.
Failure: engine down ⇒ number's fallback route = client's own phone (configured at
provisioning); our webhook down ⇒ **the event is LOST at the webhook layer (Bolna has
no delivery retries — D-31)**; the 10-min List-Executions reconciliation poller is the
guarantee of record and recovers every missed event.

## 4. Instant Lead Callback (Webhook-in → Outbound)

Trigger: Meta Lead Ads / website form / Sheets/Zoho webhook hits our per-client ingest URL.
1. Verify per-endpoint secret; validate mapping → create leads row (source=webhook).
2. Compliance pre-checks: DNC scrub, calling hours, caps, consent provenance flag on the
   form (form must state a call will be made).
3. Adapter start_outbound_call with CallContext {lead name, form fields} → agent opens
   with context ("you enquired about…").
4. Speed-to-lead metric recorded (form_ts → dial_ts; target < 60s).
5. No-answer → retry policy (respecting hours) → after exhaustion: WhatsApp/SMS follow-up
   template + needs_follow_up lead status.

## 5. Bulk Campaign Lifecycle

Draft (CSV upload → dedupe → validation report) → Compliance gate (SEC-COMP §3; launch
button disabled with reasons listed until green) → Schedule/launch →
Running (live progress: dispatched/connected/failed/no-answer; concurrency slider ≤ plan
ceiling; pause/resume) → per-contact retries per policy → Completed (batch analytics:
pickup %, avg duration, interaction level, outcome distribution; leads flowed into CRM).
Mid-campaign safeties: complaint-spike alarm (pause + notify), cap breach ⇒ auto-pause,
big red switch halts all tenants' outbound.

**Scheduled start (`campaigns.schedule`, `apps/api/campaigns/scheduling.py`).** A client
may set a ONE-TIME future start instead of pressing Launch: `POST
/v1/campaigns/{id}/schedule` moves `draft → scheduled` and the dispatch tick fires it.
Three rules, all of them consequences of things stated elsewhere in this document:

- **The compliance gate runs when the schedule FIRES, through the same
  `launch_campaign` the button calls — never at the moment the date was picked.** A
  campaign scheduled on Friday and started on Monday may have crossed a DNC addition, a
  spend cap, a KYC expiry, a withdrawn DLT template or the big red switch; a gate passed
  on Friday proves nothing about Monday (hard rule 5). A start the gate refuses is
  retried each tick for 24 hours, its blocker rules shown on the campaign screen, and
  then returned to `draft` rather than starting late.
- **Starting is not dialling.** A start at 22:00 IST is accepted and makes the campaign
  `running`; `calling_hours` and the per-dial gate then hold every contact until 09:00,
  exactly as they do for a campaign launched by hand at 22:00. The schedule endpoint
  returns `first_dial_not_before` so the client is told which hour that is.
- **Recurrence is NOT built.** The column carries a `kind` discriminator and the
  dispatcher refuses any value but `one_time`, so a recurring schedule cannot be fired
  once and look finished.

**Concurrency reservation (our dispatcher — the platform has no native reserved-inbound
feature):** the platform account's line pool is shared across ALL tenants, so one client's
campaign must never starve another's inbound receptionist. The dispatcher enforces, in
order: (1) `platform_lines_total` (from verification item 8, config value); (2)
`inbound_reserve` (default 30% of pool, min 4 lines) — outbound dispatch may only use
`total − reserve`; (3) per-tenant `concurrency_ceiling` (plan field, default ≤ 10);
(4) per-campaign concurrency slider ≤ tenant ceiling; (5) the platform's outbound
call-creation rate limit — Bolna's is unpublished (pilot measures it; recorded as a
config value) — the dispatch loop paces dial requests across ALL tenants to stay
under whatever the measured/contracted limit is. Dispatch loop: before each dial, check active-call count from live engine
events against (2)+(3); over-limit contacts stay queued (mirrors platform queuing
behavior). Also respect the secondary ceilings: Sarvam
BYOK-tier model concurrency and SIP trunk channels — the dispatcher's effective pool is
MIN of all three (config values, reviewed when any vendor plan changes).

## 6. Post-Call Pipeline (worker jobs, keyed by call_id, idempotent)

fetch_recording → redact_transcript → extract(schema) → upsert_lead(+repeat-caller flag on
phone match) → meter_usage(write unit rows + update spend_state) → notify(hot-lead rules:
e.g., status hot OR urgency=emergency ⇒ WhatsApp+email to owner within 2 min) →
resolve_campaign_contact → outbound_sync(call.completed via the outbox, D-23).
`embed_if_resolved(call corpus)` is M3, NOT in the shipped pipeline
(`apps/workers/pipeline.py` stops at outbound sync).
Retry budget: **3 attempts** — one number, `WORKER_MAX_TRIES` in
`apps/api/core/queue.py`, read by the ARQ worker and by the delivery worker's
exhaustion check. Outbound webhook deliveries wait **30s then 120s**
(`RETRY_BACKOFF_S` in `apps/workers/outbound_webhooks.py`); a failed recording copy
waits 30s flat. **Not everything is retried**: transport failures, 5xx, 408, 425 and
429 get the ladder, while any other 4xx is a verdict on the request — it stops on the
first attempt and is recorded `rejected {code}`, because retrying a 400 three times
only delays the verdict and triples load on an unhappy host. DLQ + Sentry alert on
exhaustion; pipeline lag dashboard.

A worker only gets a retry by raising `arq.Retry` — under arq 0.28 a plain `raise`
finishes the job on the first attempt, so `max_tries` counts nothing for it.

> ⚠ **The arq trap, kept here because it bit us once.** In arq 0.28 `max_tries` only
> bounds jobs that raise `arq.Retry`/`RetryJob`; a job that raises a plain exception is
> terminal on its FIRST attempt. For a while no job in `apps/workers` raised `arq.Retry`,
> so `raise` meant "give up", the `attempt >= MAX_ATTEMPTS` branch in
> `deliver_outbound_webhook` was dead code, and `outbound_webhook_exhausted` could not
> fire in production — a client's broken integration would go silently stale. The
> delivery worker and the recording copy now raise `Retry(defer=...)`, which is also
> where the backoff lives. Anything NEW that wants a retry must do the same; a plain
> `raise` is a deliberate "this is permanent", not a retry.

## 7. Knowledge Update Flow (client-initiated)

Client (owner) pastes text → chunk → side-by-side preview → client submits → admin
approve (or auto-approve toggle per client later) → version bump → T0 recompilation →
engine KB sync → live. Rollback = republish an earlier version (the archived row;
eligibility is `approved_at IS NOT NULL`, never the current `status`, or the recovery
path refuses the only rows it exists for).

**Three steps this line used to name are not in it, and each is absent for a different
reason.** They were removed rather than left as a flow nobody walks — a promised step
that does not exist is read by the next reader as a step somebody forgot to call.

- **"uploads doc / submits URL" and "parse".** Neither exists: `kb.service.submit_source`
  chunks the pasted body and nothing else. A submission naming `kind="url"` or `"file"`
  is now REFUSED by name (`kb_kind_unsupported`) instead of being accepted with its `uri`
  written to a column nothing reads. What closes it is TRD §6's offline ingestion worker —
  a URL fetcher with its own SSRF design, plus a document parser. **Externally blocked**:
  LlamaParse is the named parser candidate and no vendor account has been opened.
- **"embeddings".** D-28 moved retrieval to a managed API service and D-33 keeps v1's
  in-call retrieval on the ENGINE's built-in knowledge base, so there is no embedding step
  of ours to run — `attach_kb` hands the text over and the engine indexes it. Closes (as a
  real step) only if the D-28 bake-off puts in-call retrieval on the managed provider.
- **"regression smoke (3 canned questions answered from new content)".** This one cannot
  be built on our side at all, and the reason is the same one that leaves
  `kb_retrieval_logs` without a producer (`apps/api/kb/models.py`): **we have no way to
  ask the engine's knowledge base a question.** Retrieval happens inside the engine's
  pipeline (D-33); `VoiceEngine` exposes `attach_kb`/`detach_kb`/`list_kb` — ingestion and
  bookkeeping — and neither `CallEvent` nor `ExecutionSnapshot` carries a retrieval query,
  tier or score. The only instrument that would answer "is the new content retrievable"
  is a live PSTN call, which is pilot gate 8's Telugu retrieval probe
  (`scripts/pilot/knowledge.py::probe_telugu_retrieval`), not a per-publish step. What
  publish DOES verify is the half it can see: the detach is confirmed before the attach
  (below), and the T0 recompile mints a new prompt version carrying the newly live facts.
  `tests/kb_flow_promises_test.py` fails the day this paragraph and the code disagree.

**Engine KB sync is DETACH-then-attach, and a failed detach aborts the publish (D-41).**
Archiving a row only changes our tables; what the caller hears is what the ENGINE holds,
so the superseded version is withdrawn from the agent before the new one is pushed — push
first and the agent can answer from either version, and a rollback leaves every version
live at once. If the withdrawal is not confirmed, nothing is published and the previously
approved version stays live: publishing over a version we could not retract is the defect,
and dropping the old while publishing nothing is an outage. The ordering costs one gap —
between detach and attach the agent has no copy of that source and answers T4
"I don't know" — which is cheaper than a stale price the client is then held to.

## 8. Billing Cycle

Nightly rollup usage_events → month-to-date panel (client sees minutes used/remaining +
overage estimate; admin sees cost + margin). Month close: invoice draft (retainer +
overage + one-time lines) → GST → send (manual v1, Razorpay link) → paid/overdue states →
overdue ⇒ dunning emails; 15 days ⇒ soft-suspend outbound (inbound stays up); caps always
independent of billing status.

## 9. Offboarding / Deletion

Client churns: export bundle (leads CSV, transcripts redacted, recordings zip via
presigned) → retention countdown per policy → deletion_requests execution (our storage +
engine records via adapter) → proof certificate → org status churned; number released or
ported per client wish.

- **The countdown really does keep running.** `apply_retention` is deliberately
  unfiltered on `organizations.status` AND on `deleted_at`, so an offboarded client's
  recordings and leads age out on exactly the schedule their policies name. The obvious
  "skip dead tenants" optimisation would stop the sweep for the one account whose data
  MUST expire; both halves are pinned (`tests/tenant_birth_test.py` through the real
  `churned` transition, `tests/pipeline_audit_test.py` for the soft-deleted case).
- **`churned` is terminal and reversal is a new agreement**, not a button:
  `core/auth.py` already excludes a churned org from every membership resolution, the
  dial gate refuses it as `account_closed`, and the lifecycle route's `from_statuses` has
  no exit. A soft-deleted client is a 404 on that route rather than a 409 — it is not a
  client any more, and the directory route has always said so.
- **`organizations.deleted_at` still has no writer.** Every reader of it is correct and
  tested; nothing in `apps/` sets it, because tenant-level erasure has no execution path
  (`deletion_requests` is per data subject). Recorded with its remedy in
  `tests/tenant_birth_known_gaps_test.py`.

## 10. Number Provisioning & DLT Roles (reference)

**No physical SIMs.** All numbers are virtual DIDs provisioned via API (Exotel /
Vobiz / Plivo, connected to the engine — Bolna guides verified for all three; Vobiz
inbound unconfirmed, TRD §5), routed over SIP, stored in `phone_numbers`.

**One number set per client — mandatory**, because: (a) inbound number IS the client's
public line; (b) DLT ties outbound numbers to one business identity + its templates —
cross-client sharing is a compliance violation; (c) tenancy/routing/analytics assume it.

Typical allocation per client:
| Purpose | Series | DLT template needed | Cost note |
|---|---|---|---|
| Inbound receptionist | standard DID | No (receiving needs no template) | ₹0.4–0.9/min |
| Outbound service/transactional (reminders, confirmations) | 160/standard, registered | Yes | 45–65% answer rates |
| Outbound promotional (campaigns) | **140-series only** | Yes, approved | 8–20% answer rates — set client expectations |

**DLT role model:** each **client is the Principal Entity (PE)** for calls made on their
behalf (their identity, their templates, their consent records — PE registration ~₹5,900
first TSP, executed by us during onboarding as part of the setup fee). **Calevate
registers once as the Telemarketer (TM)** under our operating entity and is linked to each
client PE. Calevate's TM registration is therefore the single company-level blocker
(Risk R-01); each client's PE registration is an onboarding step.

**Existing business numbers:** default answer is call-forwarding from the client's known
number to the AI DID (zero disruption, day-one). Porting into the cloud provider is a
later, weeks-long option — never inside onboarding.

Failure route: every DID configured at provisioning time with a fallback destination
(client's own phone) for engine outage (see OPERATIONS runbooks).
