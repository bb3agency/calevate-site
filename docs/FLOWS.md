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
   edited by admin; both notice sentences auto-inserted and not client-editable, each
   switched ON at birth and switchable by the client afterwards (D-163 — the truthful
   answer when a caller ASKS is not switchable by anyone); extraction schema
   pre-filled from vertical template, edited per client; voice/language/model picks.
5. **Knowledge**: paste text → chunk preview → admin approves → publish, which recompiles
   T0 and, on an engine with a built-in knowledge base, attaches the new version and
   detaches the superseded one. **On Bolna it REFUSES at the capability check before
   anything is withdrawn** (`kb/service.py`, `require_capability("knowledge_base")`,
   `BOLNA_CAPABILITIES.knowledge_base = False`, D-354): their create endpoint takes a PDF
   or a URL and has no text field, which is the only shape our approved-prose pipeline
   produces (`bolna-findings/mirror/pages/api-reference/knowledgebase/create.md:31-80`).
   Refusing before the detach is deliberate — the alternative takes a client's knowledge
   down in order to report that we could not replace it. So T0 is what a client's
   knowledge buys today (TRD §6.2). Same path and same limits as §7,
   which is the one description of it — PDFs and URLs are refused by name until an
   ingestion worker exists, and there is no embeddings job of ours (D-28/D-33).
6. **Number & compliance** (see §10 for the full model): **the CLIENT buys the DID on
   their own carrier account** and passes that carrier's KYC — Model B, and Calevate
   neither supplies nor resells it (`docs/legal/LEGAL-OPS-PLAYBOOK.md` §9;
   `PROVISIONING_IMPLEMENTED = False` is not an unbuilt adapter, it is a refused business
   model). They hand back the number and revocable API credentials; an operator RECORDS
   both with `POST /v1/admin/tenants/{tenant_id}/numbers`. Numbers are virtual (no SIMs),
   one-per-client mandatory, and the rental is billed to the client by their operator, not
   by us; an existing client number is handled by call-forwarding to the DID (porting only
   later, never in onboarding critical path). If outbound intended: classification decided,
   client registers as **Principal Entity** in their own name (~₹5,900, theirs to pay and
   theirs to file — we walk them through it and cannot file it for them), binds our TM-ID
   in the PE–TM chain, we accept it; DLT voice template content drafted by us and filed by
   them under their PE; series selected (140 promotional / 160-standard service). Blocked
   until Calevate's TM registration exists — wizard shows compliance status explicitly.
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
     (addresses in full, D-436, so an operator on the phone can read one back). It cannot
     be done by impersonation — D-22 makes that read-only —
     and the client-realm revoke has nobody to press it, since the owner invite is issued
     before anyone can sign in. A cancel that races an acceptance is refused (404): the
     person is a member now, and removing them is a different act.

Failure handling: every step idempotent; engine failures surface with retry; nothing
client-visible until step 8.

## 2. Client Auth & Access

**Auth is OURS — `apps/api/authn/` and nothing else.** This section described Clerk until
D-177; the vendor is deleted from the tree (D-165 designed the replacement, D-170 mounted
it, D-177 removed the old one), and the argument that made authentication worth owning is
unchanged and now cuts the other way: **RLS trusts `tenant_id` from a verified session, so
an auth defect is a cross-tenant breach** — which is precisely why the one dependency whose
outage is total should not be somebody else's. Full design: `docs/AUTH-MIGRATION.md`;
mechanism summary: TRD §2's Auth bullet.

Two realms, never sharing session logic: **admin realm** (invite-only; there is no
public door at all) and **client realm**. The credential is an opaque token in an
`HttpOnly` `__Host-` cookie, one name per realm, and the realm is inside the stored token
fingerprint so a client credential cannot be looked up as an admin one. There is no
`accounts.` hostname and no hosted vendor page: every screen in the flow is ours.

**Three ways into the client realm (D-34 — both motions supported):**
1. **Self-serve signup** — `POST /v1/auth/signup` creates the organization (name + slug
   validated against `reserved_slugs`), its receptionist agent, its extraction schema and
   its retention policies, and makes the caller the owner, with
   `plan_tier='self_serve'|'trial'`. **Read the caveat, because it is the one thing in this
   list that does not work end to end**: that route requires a caller who already holds a
   verified first-party session and no membership, and **the public account-creation door
   that would produce such a caller is NOT built** (AUTH-MIGRATION §11, C-11 — the vendor's
   hosted sign-up page used to stand in for it and went with the vendor). The
   `self_serve_signup_enabled` switch also defaults to **OFF**. `/signup`'s stranger panel
   says exactly this rather than linking to a door that is not there. **Google/social
   sign-in is not offered and is a decision, not a gap** — C-26, dropped in
   AUTH-MIGRATION §9 Q3: a first-party Google OIDC client is a week of work and a residency
   question of its own.
2. **Invitation — the path that works end to end today.**
   `POST /v1/auth/client/invitations/accept` takes `{token, password, name}` and, in ONE
   call, redeems the invitation, creates the credential, creates the membership and issues
   the session. It is one call where the Clerk-era flow took two, because there is no
   vendor to have made the account first — and it needs no address comparison at all:
   possession of a token emailed to that address IS the proof, which is also what sets
   `users.email_verified_at`. Token hash lookup, expiry + `used_at` check, **burned on
   success** with one `UPDATE … WHERE used_at IS NULL … RETURNING`, so exactly one of two
   concurrent submissions wins at the database; a resend retires the prior token. This is
   how MANAGED clients — and extra staff on any org — get in.
3. **Managed onboarding** — the admin wizard (§1) creates the org first, then invites the
   owner. Same invitation machinery as (2); the difference is who does the setup, not the
   auth path.

**The admin realm's first row is a script, not a screen.** `admin_users` is an ops-managed
allowlist that nothing reconciles from anywhere, and nothing in the repository used to
insert into it — so a fresh deploy came up green and 403'd every admin request.
`scripts/bootstrap_admin.py` closes it: it mails a single-use link, `POST
/v1/auth/admin/bootstrap/confirm` sets the password, and it refuses to run twice. Every
operator after the first is invited from the console by an existing one. Both halves are
audited (`auth.admin_bootstrapped`, `auth.admin_bootstrap_completed`) because it is the
most privileged act in a deployment's life.

**THERE IS NO SECOND IDENTITY SYSTEM TO KEEP IN STEP, AND THAT IS THE POINT OF D-177.**
This section used to describe a `users` mirror fed by vendor webhooks, an
`organization*` event we deliberately ignored, and a reconcile-on-first-token fallback for
the race between a vendor minting a session and its webhook arriving. **All three are
gone with the vendor**: `tenancy/clerk_webhooks.py` and `core/clerk_identity.py` do not
exist, there is no eventually-consistent feed, and the row and the session are created in
the same transaction as each other. Tenant birth stays what D-10 made it — a single
Postgres transaction (org + retention policies + agent + extraction schema + tier + owner
membership + audit row) — and there is no longer a distributed one anywhere near it.
D-37's load-bearing half **stands**: our Postgres is the system of record, our
`organizations.id` is the tenant key RLS uses, and never derive `tenant_id` from a
client-supplied value — only from the verified session, resolved against our own tables.
D-124's mirror race is deleted rather than superseded; there is nothing left to race.

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
    `kyc_records` holds one row per tenant and the dial gate refuses a `self_serve`/`trial`
    tenant with `kyc_missing`/`kyc_not_verified`. It is not what gets them a number — they
    buy that from their own operator, who runs its own KYC first — and our record exists so
    our gate is not looser than the carrier's. Inbound answering is never gated.
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
   (calendar), `transfer_call` (to client staff during business hours — NOT YET ENABLED,
   see below), `add_to_dnc`, `end_call`.
   **`transfer_call` is the one item on that list this system does not have today, and
   "warm" was a claim nothing supported.** Bolna's built-in is real and its name matches
   (`key: transfer_call`, an agent-level tool with a config-supplied destination — OAS
   `TransferCallTools`/`TransferCallToolParams`), but **the vendor documents warm vs cold
   nowhere**: no page in their mirrored doc set uses the words warm, cold, attended, blind
   or consultative about a transfer, so whether the caller is held while staff are briefed
   is unknown, not chosen. Three things must be settled before it is offered, and none is
   a flag flip — OPERATIONS §2 gate 18, and `docs/evidence/bolna-tools-integrations.md`
   for the evidence: (a) whether our AI-disclosure and recording obligations follow the
   caller across the handoff, since the human who picks up is not covered by the sentence
   the agent already spoke; (b) the transferred leg is a SEPARATE object with its own
   `recording_url` and its own `cost` (`transfer_call_data`), so retention, DPDP erasure
   and metering all need it and none of them reaches it today — `engine/bolna.py`
   `_check_transfer_leg` pages if one ever appears; (c) whether the destination becomes
   engine config per agent rather than one of our columns.
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
Failure: engine down ⇒ number's fallback route = client's own phone (configured on the
client's carrier account); our webhook down ⇒ **assume the event is LOST at the webhook layer**
(this said "Bolna has no delivery retries — D-31" as a fact; it is not one. D-352 showed
the OSS single-POST deliverer is a different program from the hosted one, their skills
repo says the hosted platform retries on non-2xx, and their own hosted webhook page
`bolna-findings/mirror/pages/guides/post-call/polling-call-status-webhooks.md` says
**nothing at all** about retries, signing or guarantees — one uncorroborated source either
way, so we design for loss and claim neither); the 10-min List-Executions reconciliation poller is the
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
- **Recurrence IS built** (`POST /v1/campaigns/{id}/recurrence`, `campaigns/scheduling.py`
  decision 1), and this line used to say the opposite — which is the reading a client's
  screen and this document disagreed on. The shape is WEEKDAY + TIME (`{"days": [1-7],
  "at": "HH:MM IST"}`), deliberately not RRULE and not day-of-month, because "the 31st of
  every month" has no answer four months a year and a recurrence a client cannot predict
  dials when they did not expect it. Three bounds go with it, each argued at the code: a
  MISSED occurrence is skipped and never caught up (a worker down from Monday to
  Wednesday must not fire three campaigns into one minute); a recurrence whose time of
  day is outside the platform calling window is refused at creation rather than quietly
  reinterpreted; and the `kind` discriminator still REFUSES any value it has no reader
  for, so a schedule shape a future build writes cannot be fired once and look finished.
  The gate runs at every occurrence, through the same `launch_campaign`.

**Concurrency reservation (our dispatcher — the platform has no native reserved-inbound
feature):** the platform account's line pool is shared across ALL tenants, so one client's
campaign must never starve another's inbound receptionist. ⚠ **THE VENDOR'S DOCS SAY THE
SECOND HALF OF THAT SENTENCE CANNOT HAPPEN, AND WE ARE NOT ACTING ON PROSE.** The
"no native reserved-inbound feature" half is confirmed — no such setting exists anywhere
in `bolna-findings/mirror/`. But the org envelope is scoped to *outbound*
(`enterprise/concurrency-management.md:33`) and two pages say inbound is never admitted
against it: *"Inbound calls are never queued"* (`:65`) and *"**No concurrency limits** -
inbound calls are never restricted or queued"*
(`pricing/outbound-calling-concurrency.md:26-28`). If that survives contact with a
saturated media plane, `inbound_reserve` costs us 4 of 10 lines for nothing and the
outbound pool goes 6 → 10, a 67% throughput gain **free**. It is exactly the class of
vendor claim D-31/D-32/D-350 exist for — a statement about admission control — so it is
an OBSERVATION TO MAKE at pilot gate 13 (hold N outbound calls at the ceiling, place an
inbound call to a platform number, see whether it connects), not a change to make from a
page. Two more facts from the same pages that our dispatcher does not model: surplus
outbound work is **queued, not rejected** (`pricing/outbound-calling-concurrency.md:41`) —
so an over-high `platform_lines_total` is a COMPLIANCE defect, not a throughput one, because
the surplus dials out of a vendor queue we cannot see or DNC-scrub after `check_dispatch`
has already cleared it; and *"An account's capacity is split evenly across its providers"*
(`enterprise/concurrency-management.md:73`), so the moment we dial through both Plivo and
Vobiz with work waiting on each, our effective ceiling on each is HALF the pool. The
dispatcher has no notion of a provider. Both are gate 13.
The dispatcher enforces, in
order: (1) `platform_lines_total` (from verification item 8, config value — **and the
vendor publishes this number on a read endpoint, `GET /user/me` →
`concurrency: {max, current}`, `api-reference/user/info.md:78-87`, so it should be READ
rather than typed: the paid tier "scal[es] automatically with monthly usage",
`pricing/outbound-calling-concurrency.md:19`, i.e. a correct constant decays without a
deploy**); (2)
`inbound_reserve` (default 30% of pool, min 4 lines) — outbound dispatch may only use
`total − reserve`; (3) per-tenant `concurrency_ceiling` (plan field, default ≤ 10);
(4) per-campaign concurrency slider ≤ tenant ceiling; (5) the platform's outbound
call-creation rate limit — **published, and this line used to say it was not**: `POST
/call` is **500 requests/minute**, counted per ORGANIZATION and shared across every user
in it, with a 429 on breach (`bolna-findings/mirror/pages/api-reference/rate-limiting.md:18-27`);
what remains unpublished is dispatch PACING, which is a different quantity (the limit
bounds our request rate, not how fast the platform dials) — the dispatch loop paces dial
requests across ALL tenants to stay under whatever the documented/measured limit is. Dispatch loop: before each dial, check active-call count from live engine
events against (2)+(3); over-limit contacts stay queued — and that genuinely does mirror
platform behaviour: *"Outbound calls that don't fit your concurrency limit are **queued,
not rejected**"* (`pricing/outbound-calling-concurrency.md:41`). Also respect the secondary
ceilings: Sarvam BYOK-tier model concurrency and the Azure TPM/RPM quota in `eastus2`
— the dispatcher's effective pool is MIN of those with (1) (config values, reviewed when
any vendor plan changes). **"SIP trunk channels" was the third term here and it is
removed**: we run no trunk, and a BYOT trunk would not add an independent ceiling anyway —
*"those calls run on Bolna's SIP infrastructure, so they share platform capacity even
though the trunk is yours"* (`enterprise/concurrency-management.md:80`).

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
(`RETRY_BACKOFF_S` in `apps/workers/outbound_webhooks.py`), and the ingest job — the one
that copies the recording — waits on the **same 30s/120s ladder** (`RETRY_BACKOFF_S` in
`apps/workers/pipeline.py`, one entry shorter than the budget because the last attempt has
nothing after it). So the outside edge of "not yet definitely lost" is 150s of backoff plus
three attempts, not 60s. **Not everything is retried**: transport failures, 5xx, 408, 425 and
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
  publish DOES verify is the half it can see: the withdrawal of every superseded copy is
  confirmed (below), and the T0 recompile mints a new prompt version carrying the newly
  live facts. `tests/kb_flow_promises_test.py` fails the day this paragraph and the code
  disagree.

**Engine KB sync is ATTACH-then-detach, and a failed detach aborts the publish (D-41,
REVERSED BY D-488).** Archiving a row only changes our tables; what the caller hears is
what the ENGINE holds, so every superseded copy — including this source's own previously
attached one — is withdrawn as part of the publish, and a withdrawal that is not
confirmed aborts it. What changed in D-488 is the ORDER and not that rule. D-41 detached
first and priced the gap at "one request of silence", which was true while `attach_kb` was
a single call. On a real engine it is an upload plus an indexing wait the vendor publishes
no bound for (ours allows three minutes), so detaching first would leave the agent with no
copy of that source — answering T4 "I don't know" — for the whole of it, on every
republish. The engine references knowledge by a LIST, so an overlap is expressible and a
gap is not avoidable any other way.

**So the window MOVED rather than closed, and it is stated rather than implied: for the
length of one detach round trip the agent can retrieve from either version.** A stale
price for one round trip beats no answer for one round trip, and beats no answer for three
minutes by much more. If the detach fails, the copy the publish just attached is removed
again and the previously approved version — still attached, still the one a human signed
off — stays live; the client loses the update and is told so. Publishing over a version we
could not retract is still the defect, and dropping the old while publishing nothing is
still an outage.

**A re-publish of unchanged content uploads nothing.** There is no update route on the
engine's knowledge base, so `attach_kb` is a CREATE that mints a fresh handle every time
and de-duplicates nothing. The publisher keys on a SHA-256 of the rendered document stored
beside the handle, so a double-clicked Publish, a retry after a timeout and a rollback onto
the version already live cost nothing instead of stacking a second billed copy that the
first handle could never name again.

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
- **`organizations.deleted_at` is written by the tenant erasure, and by nothing else**
  (D-122). `POST /v1/admin/tenants/{id}/erasure` — admin realm, superadmin, step-up
  confirmed and bound to the tenant — files a `tenant_erasure_requests` row and queues
  `execute_tenant_erasure` in one transaction; the worker strips every call, turn,
  extraction, lead and delivered CRM body the tenant holds, destroys the recording bytes
  past the TRAI floor and schedules the rest in `recording_erasure_holds`, and marks the
  organisation deleted LAST, in the same transaction as the certificate. The account must
  already be `churned`: `deleted_at IS NOT NULL => status = 'churned'` is what lets the
  readers above filter on different columns and still agree, and
  `ck_organizations_deleted_implies_churned` is what holds it. It is NOT a
  `deletion_requests` row — that table is one data principal's DPDP §12 right, keyed by a
  phone number and surfaced in the client realm; this is the client organisation's
  instruction under DPDP §8, covering every subject at once. What it does not erase is
  stated in the certificate rather than hidden: the append-only ledgers, DNC entries, the
  knowledge base, the client's own users and memberships, and engine-side copies
  (`compliance/tenant_erasure.TENANT_ERASURE_LIMITATIONS`).

## 10. Number Provisioning & DLT Roles (reference)

**No physical SIMs.** All numbers are virtual DIDs (Exotel / Vobiz / Plivo, connected to
the engine — Bolna guides verified for all three; **Vobiz inbound is ASSERTED in their
capability matrix with no provider-specific guide published**, where Twilio, Plivo and
Exotel each have one — `bolna-findings/mirror/pages/supported-telephony-providers.md:33`,
TRD §5), routed over SIP, stored in `phone_numbers`.

**CALEVATE DOES NOT BUY, SELL, RENT, ALLOCATE OR PORT A NUMBER — MODEL B**
(`docs/legal/LEGAL-OPS-PLAYBOOK.md` §9). The client's entity is on the CAF and the carrier
KYC, the client is the subscriber of record and the PE on DLT, we are the TM, and Bolna
uses the client's own API credentials. Model A — a pool of numbers in our name, allocated
to clients — reads as unlicensed telecom resale (UL-VNO is a licensed category) and is
refused outright for a proprietor with no corporate veil (`:249`). A client who asks us to
"just give them a number" is sent to Exotel/Plivo/Vobiz or lost as a deal (`:266`), and
opening a Calevate carrier account to park client traffic on is stop-list item 10.

**And "provisioned via API" was never true of the regulated series anyway.** The 140- and
160-series numbers outbound campaigns run on have **no provisioning endpoint at all** —
`POST /phone-numbers/buy` cannot reach them. Getting one is a paperwork sequence a human
runs on the client's side: DLT Principal-Entity registration, documents to the carrier's
compliance address, carrier allocation, then header and template approval.

The carrier is not a preference either — it is fixed by the series, in the vendor's own
table (`bolna-findings/mirror/pages/guides/inbound/obtaining-regulated-phone-numbers.md`,
VERIFIED-VENDOR-DOCS): **140-series → Vobiz**, **160-series → Plivo**. TRD §5 carries the
same split, and `campaigns/provisioning.KNOWN_PROVIDERS` is the one list that names them.

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
first TSP, taken out by THEM on the registrar's portal under their own PAN/GST/Udyam; we
hold no DLT login of theirs and cannot file it, so onboarding walks them through it and
drafts the template content they file (playbook §10.4-10.5); **the figure is
independently corroborated by the engine vendor's own guide** — *"a payment link for
**₹5,900** will be generated on the portal"*,
`bolna-findings/mirror/pages/guides/inbound/obtaining-regulated-phone-numbers.md:60`). **Calevate
registers once as the Telemarketer (TM)** under our operating entity and is linked to each
client PE. Calevate's TM registration is therefore the single platform-level blocker
(Risk R-01, whose entity leg is closed — sole proprietor, ROADMAP D-461); each client's PE
registration is an onboarding step THEY complete.

**Existing business numbers:** default answer is call-forwarding from the client's known
number to the AI DID (zero disruption, day-one). Porting into the cloud provider is a
later, weeks-long option — never inside onboarding.

Failure route: every DID configured on the client's carrier account with a fallback
destination (client's own phone) for engine outage (see OPERATIONS runbooks).
