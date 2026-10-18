# Calevate — Core Flows

Version 1.0. Each flow lists: trigger → steps → failure handling → owner surface.
URLs: admin console = admin.calevate.tech; client app = app.calevate.tech/c/<slug>/…

---

## 1. Client Onboarding (Admin Wizard)

Trigger: Sri opens Admin → New Client: one screen, one "Create and invite" (D-695). The client's own part is the business setup, saved per step and resumable from their dashboard.

1. **Profile** (D-695: the operator enters ONLY this): business name → slug auto-generated
   (immutable; reserved-word check), vertical template pick (clinic | real_estate |
   insurance | education | custom), and the owner's name, email and mobile. ONE action,
   "Create and invite", creates the account AND the owner's invitation and queues its email
   in one transaction (`POST /v1/admin/tenants` requires `owner`); a failure leaves nothing,
   so no account can exist that nobody was invited into. The owner's name and mobile ride on
   the invitation and fill their account when they accept. No voice workspace is made at
   creation. Nothing about the business itself is asked here.
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
3. **Business setup, by the CLIENT (D-695; was the operator's "intake")**: on first login the
   owner is taken to `/c/{slug}/setup`, a guided wizard with one topic per step — hours
   (closed is an answer, distinct from not answered), addresses/branches, services +
   prices (digit strings), common questions, staff names and how to say them, booking
   rules, people who can take a call (Indian mobiles), languages — every step skippable. The
   languages are where a new agent's reply languages start; each agent's own list is changed
   on that agent, and a later change here does not rewrite existing agents (D-815).
   Progress is stored server-side per client (`business_profiles.setup_*`); a checklist
   on the dashboard resumes any step and folds away when everything is answered or
   skipped and nothing blocks going live, or when hidden. The same facts are edited later
   under Settings → Business profile, by the owner or by an operator in view-as. ONE
   profile per client: every agent's [T0 FACTS] is compiled from it and every save
   re-syncs every agent (facts and, on ThinnestAI, the facts document) with no publishing
   by anyone. An agent cannot go LIVE until the profile has hours, an address, a service
   and someone to take calls (`business_profile_incomplete`, with links to each step).
4. **Agent draft**: system prompt generated from the business profile (template + LLM assist), reviewed/
   edited by admin; both notice sentences auto-inserted and not client-editable, each
   switched ON at birth and switchable by the client afterwards (D-163 — the truthful
   answer when a caller ASKS is not switchable by anyone); extraction schema
   pre-filled from vertical template, edited per client; voice/language/model picks.
5. **Knowledge**: paste text → chunk → approved on submission when the account's own people
   add it (D-658; an operator's seed or a view-as submission still waits for an admin) →
   publish by the `publish_kb_source` worker job, which recompiles
   T0 and, on an engine with a built-in knowledge base, ATTACHES the new version and only
   then detaches the superseded one. **That ordering is the product of D-488 and it
   reversed D-41's**: a real attach is an upload plus an indexing wait no vendor bounds, so
   detaching first would leave the agent answering "I don't know" for the whole of it on
   every republish. The window is therefore an OVERLAP, not a gap. D-488 also reversed
   D-354, which had declared the capability absent because the vendor's create route takes
   a PDF or a URL and our approved-prose pipeline produced only text
   (`bolna-findings/mirror/pages/api-reference/knowledgebase/create.md:31-80`): the
   PUBLISHER now renders the approved prose into the document the route takes
   (`KBSourceRef.document`, rendered in `apps/api/kb/` where the approval gate can see it),
   and the agent linkage is written where it lives, on the agent. An adapter handed no
   document still refuses by name rather than uploading something nobody approved. Same
   path and same limits as §7, which is the one description of it — the PASTE box takes
   text and nothing else (`kb/service.SUPPORTED_SUBMISSION_KINDS`), while files and links
   come in through `POST /v1/kb/uploads` (D-534) and are embedded by
   `apps/workers/kb_embeddings.py` into the `kb_chunks` pgvector store (D-502, which
   reversed D-28) — a store that serves the dashboard copilot and the CRM paths and is
   never on the audio path.
6. **Number & compliance** (see §10 for the full model): the client buys its numbers through
   our purchase flow, in its own business name, in its own ThinnestAI customer workspace
   (D-693; THINNEST-INTEGRATION §3a). Buying needs the account open, the workspace active, a
   verified KYC record (document review or DigiLocker, D-692, D-696), the workspace's
   business-details application `accepted`, and an attested client price; the vendor's
   monthly price is our cost and is never shown as the client's, and the client pays our
   price monthly from its wallet (D-665). An existing client number is handled by
   call-forwarding to the agent's number (porting only later, never in the onboarding
   critical path). Outbound needs a verified KYC record and an accepted no-cold-calls pledge,
   not DLT (D-692, D-762); inbound is never gated. The wizard shows compliance status
   explicitly.
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
     be done by impersonation — the invitation surface is `admin:tenants`, which D-587
     leaves withheld from a view-as session because it is an operator-console authority
     rather than something inside the client's account —
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
- **Self-serve accounts start restricted (R-11):** calling is gated until the business is
  KYC-verified and the owner has accepted the no-cold-calls pledge. Platform-fixed calling
  hours and DNC scrub on every dispatch path apply to both motions and are not
  user-editable. There is **no manual review of the first campaign** (D-783, founder,
  15 Oct 2026, superseding D-51): once those gates pass, a self-serve or trial account's
  campaigns launch without a person at Calevate reading them.
  - As built (D-47), the verification is of the **business**, not of a number:
    `kyc_records` holds one row per tenant and the dial gate refuses a `self_serve`/`trial`
    tenant with `kyc_missing`/`kyc_not_verified`. It is not what gets them a number — they
    buy that from their own operator, who runs its own KYC first — and our record exists so
    our gate is not looser than the carrier's. Inbound answering is never gated.
  - The D-51 manual-review hold (`first_campaign_reviews`) was removed by D-783. The
    table is kept, unread and unwritten, until a later release drops it (hard rule 8).

## 3. Inbound Call Lifecycle

ThinnestAI hosts the agent and the call (D-678, D-682; `docs/THINNEST-INTEGRATION.md`), so no
server of ours is on the audio path. The agent and the number live in the client's own
ThinnestAI customer workspace (D-693); the number is ThinnestAI's own, bought from the
client's Numbers page in the client's business name and pointed at the agent by us
(THINNEST-INTEGRATION §3a-§3b). The number answers with the agent: the route is the agent the
number is attached to.

caller dials the client's number → ThinnestAI answers with the published agent →
1. **Knowing the caller.** Before the agent answers, ThinnestAI calls the agent's
   `voice.callStartUrl`, which is our caller lookup (`POST /v1/worker/engine-lookups/thinnest`,
   `worker/engine_lookups.py`, D-716). It is verified with the v2 webhook signature and
   answered within 0.8 s with up to 20 short variables from our CRM for that tenant, or none.
2. **Opening.** The agent's `greeting` is its first words, verbatim: the notices switched
   on, then the script's opening line (`compose_first_utterance`, D-669, D-708). The
   notices and the opening line are separate things: the two switches decide only whether
   the AI disclosure and the recording notice are said before the opening line, never
   whether the opening line is said. A new agent volunteers neither notice (both toggles
   default OFF since D-669); a client switches either on per agent (D-163). With both
   notices off the greeting is the opening line alone; an outbound call's `purpose` is the
   same words with the call's `{{variables}}` filled in. The instructions are
   `compose_engine_prompt`'s, with the business facts moved into one knowledge document
   (founder, 6 Oct 2026). Whatever the toggles say, the agent answers truthfully when a
   caller asks whether it is an AI or whether the call is recorded (hard rule 5): the
   truthful-answer floor and `CONFIDENTIALITY_RULE` are in the prompt and are read back at
   publish and by the drift sweep. There is no output guard on this engine
   (SECURITY-COMPLIANCE §6.1).
3. **Conversation.** The agent answers from the client's knowledge, attached to every one of
   its agents in ThinnestAI's knowledge base (D-689). Unknown or out-of-scope questions
   (T4): the agent says it does not know, offers a call-back, and the call is tagged. Its
   in-call actions (opt-out, call-back, call-back cancel, hand-over request) are ThinnestAI
   custom actions calling the api at `ENGINE_ACTIONS_BASE_URL` with the agent's own secret
   header (`worker/engine_actions.py`), each run once per call and arguments (D-736). There
   is no live transfer: a hand-over is recorded for the client, not bridged.
4. **After the hangup.** ThinnestAI posts signed `call.completed` and `call.analysed` to
   voice-runtime `/hooks/v1/engine/thinnest`, which verifies the HMAC against the agent's
   sealed secret, dedupes in the inbox, acks under 500 ms and queues the sealed body for
   the worker (hard rule 3). The worker writes the call row and the transcript (redacted as
   on every engine), runs our extraction, CRM and leads, meters the minutes at the
   operator-attested rate in 30-second pulses (hard rule 7), debits the wallet at the
   client rung the publish stamped, and fans out the client webhooks.
5. **The recording.** ThinnestAI's `recording.url` is a signed link that expires (30 or 75
   days, THINNEST-INTEGRATION §1), so the pipeline's first step copies the audio into our
   `recordings/` (`engine/recording_source.py`), sets `calls.recording_url` and fans out
   `call.recording_ready` to endpoints opted into recording links (WEBHOOKS §1). Our copy is
   kept 90 days (`workers/retention.py`, seeded `recording` policy). ThinnestAI's own copy
   follows its retention; a contact erasure in the client's own workspace removes it (§9).
6. **Reconciliation.** ThinnestAI attempts each delivery once and switches an endpoint off
   after five failures, so a sweep settles any call from their call list that we have not,
   and another switches a disabled endpoint back on with an alarm.
7. SLO: lead + summary visible in client dashboard < 2 min after hangup.

After-hours: agent runs 24/7 by default; "after_hours" flag set from business_hours →
dashboard "after-hours captured" metric; escalation rules can differ after hours.
Closed account: closing an account detaches every number from its agent
(`agents/lifecycle.release_account_numbers`) and the undo re-attaches them (D-671, §9).
Repeat callers: what the agent knows about a caller reaches it at call start through the
lookup in step 1, never mid-call.

## 4. Instant Lead Callback (Webhook-in → Outbound)

Trigger: Meta Lead Ads / website form / Sheets/Zoho webhook hits our per-client ingest URL.
1. Verify per-endpoint secret; validate mapping → create leads row (source=webhook).
2. Compliance pre-checks: DNC scrub, calling hours, caps, consent provenance flag on the
   form (form must state a call will be made). A lead refused only for the clock —
   `calling_hours`, `platform_maintenance` or `big_red_switch` (`ingest.WINDOW_REFUSALS`)
   — is kept and its call booked as a `scheduled_callbacks` row: the next 09:00 IST, the
   maintenance window's announced end, or one `callbacks.service.RETRY_AFTER` re-check under
   the halt (D-666). The call-back goes through the gate again when it fires; a
   person-level refusal (DNC, consent) books nothing. The ingest answer carries
   `callback_at`.
3. Dial through `agents.service.dispatch_call`, the one dial path: held off while the engine's
   `429` hold-off runs (`engine_rate_limited`), then, under one advisory lock in the intent
   transaction, refused with `carrier_lines_busy` if the outbound pool is full
   (`engine/dial_lines.py`). The agent opens with the lead's context ("you enquired about…").
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

**Concurrency reservation (our dispatcher).** ThinnestAI's simultaneous-call ceiling covers
inbound and outbound together across the whole account (OPERATIONS §2 gate T-7), so one
client's campaign must never starve another's inbound receptionist, and the reserve is ours
to hold (D-663). `apps/workers/campaign_dispatch.py` budgets, in order: (1) the account's
lines, `Settings.thinnest_max_concurrent_calls` (`engine/dial_lines.engine_concurrency_cap`;
the fake engine uses `carrier_concurrency`); (2) minus the inbound reserve,
`inbound_reserved_lines` lines (unset: `max(1, ceil(lines × inbound_reserve_ratio))`), never
zero — at ThinnestAI's 5, three outbound and two kept for callers
(`engine/dial_lines.outbound_line_pool`); (3) the tenant's plan `concurrency_ceiling`,
clamped to that pool; (4) the campaign's slider, at most the tenant ceiling. That is the
BUDGET. The ENFORCEMENT is inside every dial's intent transaction
(`agents.service.dispatch_call`): one advisory lock counts our own outbound calls holding a
line — inbound calls are invisible to us until they end, which is what the reserve is for —
and refuses with `carrier_lines_busy` before the INSERT. That covers the dials the tick does
not make (the "call this lead" button, lead ingest, call-backs). The call row's status is the
hold, so nothing has to release a line; a Redis counting semaphore was rejected because a
lost release leaks a line until a TTL. A `429` from ThinnestAI holds every dial off for its
`Retry-After` (`start_dial_backoff`, at most 15 minutes), account-wide, rather than being
re-asked once per claimed contact.

**The client's campaign controls, results and reasoned pauses (D-773).** The Campaigns page
lives at real addresses: `/c/{slug}/campaigns` (paged list, status filter, search),
`/campaigns/new`, `/campaigns/{id}` and `/campaigns/{id}/edit`.

- **Controls.** A draft is edited (`PATCH`), has never-tried people removed, or is deleted
  (kept as `cancelled` when calls or evidence rows name it). Stop moves running, paused or
  scheduled to `cancelled` and drops the repeat; nobody else on the list is called.
  Duplicate makes a new draft from the settings, optionally with the people never reached
  (finished or stopped campaigns only). People come from a CSV or paste, or from CRM leads
  picked by stage, source and date; the server reads the numbers.
- **Results.** Each person's outcome is read from the contact and its last call (connected,
  no answer, busy, voicemail, failed, do not call, calling, not called), with tries used and
  the next try. The totals are pickup rate, average connected call, outcome tags,
  sentiment, leads and hot leads, opt-outs and the credit the calls took.
- **Retries.** 1–5 tries per person and the gap before each, chosen per campaign.
- **Automatic pauses say why.** A paused campaign carries `pause_reason`: a person,
  maintenance, the healer, a complaint spike, out of credit, or the spending cap. The
  dispatcher pauses a running campaign at the spending cap or out of credit before it
  claims anyone. A top-up that crosses zero resumes `out_of_credit` campaigns by itself;
  a spending-cap pause waits for the client to press Resume. A complaint-spike pause
  shows the opt-outs in the ledger's redacted words, and Resume is refused until the
  client confirms they reviewed them.
- **Running but not calling.** A running campaign the gate would refuse shows "Not
  calling" with each reason and its fix (`campaigns.service.not_calling_reasons`), and one
  outside its hours says it is waiting for them. "Up to N at once" is the slider under the
  plan ceiling and the line pool (`effective_concurrency`).

## 6. Post-Call Pipeline (worker jobs, keyed by call_id, idempotent)

fetch_recording → redact_transcript → extract(schema) → upsert_lead(+repeat-caller flag on
phone match) → meter_usage(write unit rows + update spend_state) → notify(hot-lead rules:
e.g., status hot OR urgency=emergency ⇒ WhatsApp+email to owner within 2 min) →
resolve_campaign_contact → outbound_sync(call.completed via the outbox, D-23).
The pipeline's first stage copies ThinnestAI's expiring `recording.url` into our storage
(`engine/recording_source.py`, §3 step 5).
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

Client (owner, or staff the owner lets curate) pastes text → chunk → approved on
submission, with no human step (D-658) → `publish_kb_source` worker job (outbox, same
transaction as the submission) → version bump → engine KB sync → T0 recompilation → live.
A document or link takes the same path through `ingest_kb_source`, read first; text a
model read off a photograph is no longer held for the owner's confirmation. A submission
nobody in the account made — a view-as operator's, an intake seed, a NEW version the
re-scrape sweep submits for a changed page an OPERATOR linked — lands `pending_approval`
and waits for an admin (or, for an upload, the account's own confirm). A changed page a
MEMBER linked is approved in the linker's name and published the same way ("the client
linked the page, so its updates are theirs"). An automatic publish
never overwrites a later approved version of the same name
(`kb/service.publish_unless_superseded`); one refused because the agent is not yet
published is re-driven by `sweep_kb_uploads`. Rollback = republish an earlier version (the archived row;
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
overage + one-time lines) → bill of supply, no GST while unregistered (D-659) → send
(manual v1, Razorpay link) → paid/overdue states →
overdue ⇒ dunning emails; 15 days ⇒ soft-suspend outbound (inbound stays up); caps always
independent of billing status. A client-bought number's rental is a "Phone number rental"
line at the price frozen at purchase, one per number and period, written to
`one_time_charges` by the purchase and the daily renewal job (D-665); there is no monthly
invoice job, because invoices are derived on read.

This is the MANAGED motion. Prepaid credit — packs, lots, per-lot rates and the FIFO debit
— is §11, and no account is on both.

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
- **A closed account stops answering (D-671).** The close detaches every number from its
  agent (`agents/lifecycle.release_account_numbers`) and the undo re-attaches them; the
  numbers are not released, which stays the client's choice above. A detach that fails
  alarms per number (`engine_inbound_binding_failed`) and does not undo the close.
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
- **The voice platform's copy is deleted call by call** (D-798). Every erasure queues
  `delete_engine_call_content` for its calls (a tenant erasure for all of the client's),
  which deletes each call's recording, transcript, summary and collected fields at
  ThinnestAI in whichever workspace holds it. Deleting a person's contact still acts on a
  whole workspace (D-691), so a data principal's erasure also queues `erase_engine_contact`
  only in the client's own workspace; the `voice_engine` task closes itself when ThinnestAI
  has confirmed every call and, for a contact, sent `contact.erased`
  (THINNEST-INTEGRATION §6). Both deletions take the person's recordings at ThinnestAI, so
  both wait while a connected call inside the 90-day floor has no recording copy of ours:
  a call is marked and re-asked by the nightly sweep (D-803), and the contact is recorded
  as held on the task and queued again by the same sweep until the copy lands, the floor
  passes or the call ends unconnected (D-810, SEC-COMP §4). A booked dial the platform
  confirms it cancelled before ringing is closed as never connected at once, and a task
  is not overdue while every outstanding call it names waits inside its floor, but is once any
  one of them is ready and still outstanding (D-811, D-812). Our own copies are always
  erased by us. A `telephony`
  processor-erasure task is opened only for an erased call that carries a carrier call id,
  which a ThinnestAI call never does: such rows come only from test calls placed on our own
  runtime before D-763 (`runbooks/processor-erasure.md`).

## 10. Number Provisioning & DLT Roles (reference)

**No physical SIMs.** A client's numbers are ThinnestAI's own virtual numbers, rented in the
client's own ThinnestAI customer workspace and so in the client's business name (D-693),
carried by ThinnestAI's own telephony and recorded in `phone_numbers`. There is no carrier
account of ours. The mechanics — the workspace's business-details application, buying,
moving a number between workspaces, releasing, attaching a number to an agent and the daily
sweep — are THINNEST-INTEGRATION §3a. Numbers rented in our developer workspace before
D-693 are in Calevate's name and are for testing only (OPERATIONS §2 gate T-21).

**What a client pays.** ThinnestAI's `monthlyPrice` is OUR cost and is never shown as the
client's price (hard rule 7). The client pays our attested monthly price, its first period
collected in the purchase transaction and renewals billed after (D-665; the price is
OPERATIONS §2 gate 26). Releasing is permanent and the current period is not refunded, by
ThinnestAI or by us; both screens say so before the button.

**DLT (D-692, partly superseded by D-696 and D-762).** No client DLT and no Calevate
telemarketer registration: outbound needs a verified KYC record (document review or
DigiLocker) and an accepted no-cold-calls pledge, on every tier, and inbound is never gated.
The DLT tables, columns and functions stay (hard rule 8). Who is the DLT telemarketer and the
principal entity of record for a number on ThinnestAI is still asked of the vendor
(OPERATIONS §2 gate T-9). `docs/evidence/dlt-roles-and-operating-model-2026-09-18.md` carries
the regulatory reading behind the earlier role model (the KYC-versus-DLT distinction, and
the open question of where a Telemarketer ID attaches to a voice call). Two facts from TRAI's
own text still bind whatever the vendor answers: **1600xx is restricted to
RBI/SEBI/IRDAI/PFRDA-regulated entities and government** (TRAI clarification, 10 July 2026),
so ordinary SMB clients cannot have it; and a PE registration's ₹5,900 is **₹5,000 + 18% GST**
(`docs/LEGAL-SURFACE.md:1284`).

**One number set per client — mandatory**, because: (a) the inbound number IS the client's
public line; (b) a number is issued to one business identity, the client's own; (c)
tenancy, routing and analytics assume it.

**Existing business numbers:** default answer is call-forwarding from the client's known
number to the agent's number (zero disruption, day-one). Porting is a later, weeks-long
option — never inside onboarding.

## 11. Buying Credit and Paying for a Call (prepaid wallet, per-lot rates)

Trigger: a self-serve client's wallet is low, or is empty at signup. This is the flow
§8's monthly cycle does NOT cover — §8 is the managed motion's retainer, overage and
invoice; this is prepaid credit, and the two never meet on one account.

**The one sentence to hold on to: a credit is ₹1 and never expires, but a MINUTE has a
price, and that price belongs to the PURCHASE rather than to the account.** Where the card
discounts a bigger pack it does so as a falling rate, never as bonus credits (the D-728 card
is flat); and it is two rates,
because the voice tier is chosen per agent (D-547,
`docs/PLAN-CREDIT-LOTS-AND-VOICE-TIERS.md`). What carries the pair is the **lot** each
purchase opens (DATA-MODEL §8 `credit_lots`).

### The card

D-728 (founder, 11 Oct 2026): flat on every pack. `billing/credit_packs.PACK_CATALOGUE` is the
single source; BRD §6.1 carries the decision and the cost behind it.

| Pack | Amount | Clear ₹/min | Studio ₹/min |
|---|---|---|---|
| `starter` | ₹2,000 | 4.50 | 6.00 |
| `growth` | ₹5,000 | 4.50 | 6.00 |
| `scale` | ₹10,000 | 4.50 | 6.00 |
| `plus` | ₹15,000 | 4.50 | 6.00 |
| `pro` | ₹25,000 | 4.50 | 6.00 |
| `max` | ₹50,000 | 4.50 | 6.00 |

A **free amount** (any top-up ≥ `MIN_TOPUP_INR`) takes the rates of the largest pack whose
price is ≤ the amount, so ₹3,400 is priced at the ₹2,000 pack's rates and ₹4,999 is not
punished for being ₹1 short. Operator grants, trial credit and any legacy bonus row take
the `starter` rates — a gift is spent at the standard price, or a ₹50,000 grant would be a
cheaper minute than a ₹50,000 purchase.

### Buying

1. **Pick.** `GET /v1/billing/topups/packs` (and the unauthenticated `GET
   /v1/public/rate-card`) serve the card above; the top-up screen shows **both** rates and
   both talk-time figures per pack. There is no "extra credit" column any more, because
   there is no extra credit.
2. **Pay.** Razorpay order → checkout → capture webhook. Unchanged, and the reason it is
   unchanged matters: the payment leg is verified by signature and settled once, and the
   pricing change adds nothing to it. Gate 44 (OPERATIONS §2) is still the first REAL
   payment, and it is money rather than a test.
3. **Credit, then the lot, in ONE transaction.** The capture writes the `topup` ledger row
   through `record_entry` under the tenant's advisory lock, and the lot is opened in the
   same transaction, keyed to that row (`credit_lots.ledger_entry_id` UNIQUE). A ledger row
   with no lot, or a lot with no ledger row, is not a state this system can reach — which
   is what makes the balance and the sum of remaining credits provable against each other.
4. **What the lot freezes.** `clear_inr_per_min` and `studio_inr_per_min`, stamped from
   the card in force at that instant and immutable afterwards by trigger. Raising the card
   later records a NEW card; nothing already sold moves. That is the promise Terms §6.1
   carries, and it is the reason the flow is written this way rather than as a rate on the
   organisation.

### Paying for a call

5. **The call ends** and the post-call pipeline runs (§6). It already knows the billable
   minutes and the agent's rung — stamped at publish on the agent's route
   (`engine_agent_routes.engine_rate_key`), never re-derived from the voice at billing time.
6. **FIFO across lots.** The debit takes the OLDEST open lot first, decrementing under the
   same per-tenant lock the ledger takes, and closes a lot at zero. One `usage` ledger row
   is written per call, idempotent on `(tenant_id, 'usage', call_id)` — a replayed pipeline
   finds the row and consumes nothing a second time.
7. **The row says what it did.** `meta.lots` carries one entry per lot touched —
   `{kind: "call", lot_id, credits, minutes, inr_per_min, voice_tier}` — so the statement
   and the margin panel are re-derivable from the ledger alone, with no price recomputed
   from today's card. A split that bought RUPEES rather than minutes (the dashboard-AI
   block; the language-model surcharge that rides a call's own row) is
   `{kind: "ai_assist", lot_id, credits}` with the three minute-shaped keys ABSENT rather
   than null, so a reader totalling talk time filters `kind == "call"` and cannot add
   money to minutes (DATA-MODEL §8).
8. **What the client sees.** Balance in rupees, unchanged. Runway is now a PAIR — *"about
   N minutes on the Clear voice, M on the Studio voice"* — because one balance divided by
   one rate stopped being a true sentence. Below it, the open lots oldest-first with their
   two rates: *"3,200 credits at ₹4.70 / ₹6.50, then 2,000 at ₹5.00 / ₹8.00"*. A `usage`
   entry in the transactions list expands to its splits, and the usage panel reports the
   month per voice (`clear_minutes` / `studio_minutes` and their charges, read out of
   `meta.lots`).

   ⚠ **NO CLIENT-FACING SURFACE NAMES A VENDOR AS A PRODUCT TIER** (founder, 7 Sep 2026;
   D-679). The two voice qualities are **Clear** (ThinnestAI's own voices) and **Studio**
   (Cartesia on our key through ThinnestAI), defined once in `billing/rates.VOICE_TIER_LABELS`
   and SENT to the browser beside every per-tier figure — a second copy in TypeScript is how
   the two drift and a client meets both names. The fields named below spell the **rung**,
   not a vendor: `voice_tier`, `clear_inr_per_min`, `clear_minutes` are `clear`/`studio`
   (`billing/rates.py::VoiceTier`), and a lot's two rates were named by
   `alembic/versions/f1c40d8b6e93_voice_tiers_named_for_rungs.py`, which refuses against a
   non-empty table because they are frozen at purchase. An auditor reconciles a column
   against an invoice, so a money column must never be named for a supplier that can be
   swapped.

9. **Correcting a purchase.** An operator restating an UNDER-credited payment grows that
   payment's own lot (one bank transfer, one card, one lot). One taking credit BACK restates
   it downwards, flooring `credits_remaining` at zero and leaving any shortfall as overdraft
   — except when the purchase is reversed in FULL, which no lot can express (`credits_total
   > 0` is a CHECK), and which is spent off the FIFO queue at face value instead. A
   compensating credit that reverses a `usage` row has no lot to restate and opens a fresh
   one at the list rates. DATA-MODEL §8 carries the rule; `remove_credit_from_lots` is the
   one door.

### The two branches that are easy to forget

**A debit that SPLITS across two lots, at two different rates.** A client with 40 credits
left on a lot bought at ₹4.70 a Clear minute and 5,000 on a newer lot at ₹5.00 takes a
12-minute Clear call (an illustration: the D-728 card is flat, so today two lots differ in
rate only when bought under different cards or opened by an operator's override). The
oldest lot pays for 8.51 minutes and empties; the remaining 3.49
minutes are priced at ₹5.00 off the newer lot. One call, one `usage` row, TWO entries in
`meta.lots`, and the totals in the panel are the sum of the splits — never minutes × one
rate. It happens at every lot boundary where two rates differ, and it is the
reason no surface may reconstruct a charge by multiplying.

**A wallet driven NEGATIVE, and how it is repaid.** The dial gate refuses at a balance ≤ 0,
but a call already in progress can outrun the balance, and the wallet is allowed to go
negative rather than cut a live caller off mid-sentence. Those overdraft minutes are priced
at **the rate of the lot that ran out** — the last split's rate, recorded as the last entry
in `meta.lots` — because that is the price the client was last actually buying at, and it
is the reading prepaid telecom already uses. No lot is open while the balance is negative,
and none is opened by the repayment: the next credit-adding entry books
`min(credits, overdraft)` against the debt FIRST, and only the remainder opens a lot at the
new purchase's rates. So a ₹2,000 top-up onto a −₹300 wallet opens a ₹1,700 lot, and the
client is never quietly given ₹2,000 of cheap minutes to pay off a ₹300 hole.

### Failure handling

- Payment captured, lot not opened: cannot happen — one transaction. A capture that fails
  after the ledger write rolls back both, and Razorpay's retry re-drives it against the
  same idempotency key.
- Pipeline retried: the `usage` uniqueness makes the second attempt a no-op. Consumption is
  never idempotent by itself; the ledger row is what makes it so.
- Rate card changed mid-month: closed months and open lots are both untouched by
  construction (D-492). Nothing re-prices.
- **A voice is sold only on an attested price.** A Clear or Studio minute is offered only
  once the ThinnestAI rate for its rate key is attested (`billing/engine_minutes.
  engine_minute_is_billable`), and a Studio voice also needs the Cartesia price attested and
  our key installed. Until then the picker marks the voice unavailable with its named
  reason — the rule `offerable_models()` already applies to an LLM.
- **A refunded pack takes its bonus back** (D-672): `payments.credit_refund` writes, in the
  refund's transaction, a negative `bonus` row sized so that partial refunds summing to the
  payment take back exactly the bonus, and it may take the balance below zero. Moot for a
  pack bought today: every catalogue pack has `bonus_pct = 0` since D-547.
- **A client-bought number's rental is a wallet debit** (D-665): on the day the number is
  recorded and on each monthly renewal date (`workers/number_rental.renew_number_rentals`),
  at the price frozen at purchase, as its own "Phone number rental" line. A renewal the
  wallet cannot cover still lands as overdraft; an invoiced account gets an invoice line
  instead (§8); a closed account and a period that begins inside a trial are not charged.

Owner surfaces: client — `/c/<slug>/billing` (top-up, wallet, lots, transactions);
admin — `/admin/tenants/<id>/credits` (grants, restatements, the audited "sell this lot at
pack X's rates" override) and `/admin/spend` (Clear vs Studio minutes, revenue from the
splits, attributed TTS cost beside the plan fee).

## 12. Changing an Agent's Script with Pip (D-820)

Pip is the one AI assistant (founder, 18 Oct 2026). The Script page has no AI panel of its
own: its "Let Pip do it" controls prefill Pip's ask box, and the owner presses Ask there.

1. **Ask.** On the Script page, "Let Pip do it" opens a short strip: a field ("What should
   change?"), example requests, and "Let Pip draft the whole script". A hand-written script
   offers "Let Pip turn it into steps" instead, beside the text box too. Each prefills Pip
   with a request about this agent ("Change this agent's script: …"); nothing is sent until
   the owner presses Ask. Pip can be asked the same from any screen, naming the agent.
2. **Pip proposes, the owner confirms the spend.** Pip calls `agent_script_suggest`
   (`copilot/script_actions.py`, confirm tier) with the agent, the mode (`change`, `whole`
   after asking the five owner questions together, or `steps`) and the request. The planner
   refuses what the model can fix (a hand-written script asked for a change, no answers, a
   request still being written) and asks the AI allowance (`require_ai_assist`) before the
   card is shown. The card says it uses the AI allowance and that nothing in the script
   changes until the owner keeps it.
3. **Confirm.** The executor records the request on the agent (`agents.script_proposal`,
   `agents/script_proposals.request_proposal`, with the draft-or-live script it is made
   from) and queues `draft_script_proposal`; the audit row is `agent.script_assist` with
   `via: copilot`. Pip says the suggestion is being written and is reviewed on the Script
   page.
4. **Write.** The job (`workers/script_proposal.py`) claims the request once, writes it with
   `script_assist.draft_script` (edit, whole draft from the answers, or conversion), meters
   it under `script_draft` (a refused paid leg too), and stores it — or a failure note in the
   owner's words. A request discarded or replaced meanwhile is not written back.
5. **Review.** The Script page polls while it is written, then shows the tick-to-keep list
   (`ProposalReview`), listed against the script it was made from so a later edit is never
   offered back. A conversion lists any hand-written lines that fit nowhere and waits until
   they are read. "Add N to my draft" puts the kept parts in the working copy (with Undo) and
   clears the suggestion; Discard clears it. Nothing goes live until "Put it live".

Failure handling: a refusal at the card (allowance used up, AI paused) is relayed by Pip
with its remediation; a refusal or crash in the job is stored as the suggestion's note and
shown with Dismiss; a request still `drafting` after ten minutes reads as failed
(`script_proposals.DRAFTING_STALE_AFTER`). A suggestion that no longer fits (the script was
switched between steps and hand-writing since) offers Dismiss only.

Owner surfaces: client — Pip's panel and `/c/<slug>/agents/<id>/script`.

The Test section's fixes follow the same path (D-820): "Let Pip suggest fixes" (or "Let Pip
suggest a fix" on one failed test) prefills Pip; Pip proposes `agent_tests_fix`; confirming
queues the improve job (D-724/D-748), and the fixes are kept one by one in that section.

## 13. The Other AI Requests, through Pip (D-821)

Each screen keeps a "Let Pip do it" button that only prefills Pip, and the review of what
comes back. Pip proposes; the person confirms the card; the old button's own function runs.

- **Teach the agents (Knowledge base).** Type it or say it in the teach box (a voice note is
  heard and its words land in the box to check), or attach a photo or file in Pip, which reads
  it. "Let Pip teach it" → `knowledge_teach` → the words are sorted by the worker → the facts
  and rules wait in the teach box (`GET /v1/kb/teach/open`) for the owner to keep; nothing is
  saved before that. Answering a caller's question carries its `gap_id`, which closes it.
- **Draft the lead details (Lead details, custom business).** "Let Pip draft them" →
  `lead_fields_draft` → drafted once → the owner keeps them field by field ("Add N to my
  agents", or "Keep none"); kept fields go onto every agent without details of its own and are
  what a new agent starts with. A draft made automatically after a business-profile save waits
  for the same review.
- **A second reading of a call (call page).** "Let Pip write a second reading" →
  `call_summarise_again` → once confirmed, a fresh summary of the redacted transcript in Pip's
  confirmation, with the fallback disclosure when another model answered; nothing is stored.
  At the allowance ceiling the panel offers the wallet dialog.
- **Make this call a test (call page, D-822).** "Let Pip make this call a test" →
  `call_test_prepare` runs at once (no card, no AI, nothing charged) → the call page's test
  form opens with what the caller said (numbers hidden) and what the person told Pip the agent
  should do → they change anything and press "Save test", or "Discard". Nothing joins the
  agent's tests before Save; Pip's receipt carries an Undo until then. Anyone who may change
  agents (`agents:write`, so staff too) sees the button.
- **Refresh your examples (Business profile, D-827).** "Refresh now" → `business_copy_refresh`
  (owner, `org:manage`) → the allowance is checked at the confirm → the worker writes the
  account's examples again; the screen shows when they were last refreshed.

### 13a. The account's own examples (D-827)

Every client account gets example text written for its business: the placeholders and hints
of the per-trade table (`apps/web/src/lib/verticalExamples.ts`), suggested script steps with
an example line each, an example line for each step of the ready-made starters, caller-detail
suggestions and example questions. Headings and buttons are never generated.

1. **When.** At account creation (`admin/service._write_tenant_root` queues
   `generate_business_copy` through the outbox, for signup and the operator wizard alike);
   on "Refresh now" (Pip) and on an operator's "Write again at our cost"; and by the daily
   check (`sweep_business_copies`) for an account not on a trial whose last look is 15 days
   old, which writes new copy only when the inputs' fingerprint changed.
2. **From what.** The business profile, type, knowledge titles, pinned facts, lead details,
   agents, open knowledge gaps and callers' recent unanswered questions, all redacted. Gemini
   only, with no standby (the inputs include callers' questions; Sarvam ToS s.17.5).
3. **Where it shows.** `useVerticalExamples` lays the copy over the per-trade table key by
   key, so every placeholder screen reads it; the script builder offers the step names,
   example lines and caller-detail ideas; the Knowledge base offers an example question. The
   table answers until the first copy lands. A new agent made from a starter gets the starter
   lines in its empty example lines when its language matches; nothing a person typed is
   ever replaced, because the copy lives in its own row (`business_copies`).
4. **What it costs.** The tokens it used, on the client's AI allowance (`business_copy`), with
   the cached-input split; a trial's first copy and an operator's refresh are ours
   (`business_copy_absorbed`). At the ceiling the run stops (`allowance_used_up`) and the copy
   in use stays. A Gemini failure keeps the copy and raises `business_copy_unavailable`.

Failure handling: refusals the model can fix come back as Pip's sentence; a refusal at
Confirm (allowance used up, AI paused) is shown on the card with the server's remediation; a
failed sort shows in the teach box; a failed lead-details draft offers "Let Pip draft them"
again.

Owner surfaces: client — Pip's panel, `/c/<slug>/knowledge`, `/c/<slug>/settings/lead-details`,
`/c/<slug>/calls/<id>`.
