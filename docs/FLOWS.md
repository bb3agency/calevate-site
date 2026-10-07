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
   **Testing is the one exception (D-662):** the founder's own Vobiz account holds the test
   numbers and pays Vobiz (Model A for that account only), recorded with provider `vobiz`.
   Client traffic waits on Vobiz's written consent (OPERATIONS §2 gate V-10) and on gate 47.
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

The owned runtime (D-592) on Vobiz (D-662). Three boxes take part: the carrier, voice-runtime
on our VPS, and the voice worker on Pipecat Cloud `ap-south` (PIPECAT-MIGRATION §8).

caller dials the client's number → the number's Vobiz Application fetches its answer URL →
1. **Answer document** (`apps/voice-runtime/carrier_routes.py`). The URL names the agent
   (`calevate_shared.carrier.answer_path`): the route is the URL, never the dialled number
   (D-603). The request must come from Vobiz's published range, carry our `callback_key`
   secret, and verify any signature it carries (D-673, SECURITY-COMPLIANCE §5). The reply
   is XML: when the agent was published with `call_is_recorded`, a `<Record
   recordSession="true" redirect="false" playBeep="false" finishOnKey="*">` first
   (D-668/D-670), then a bidirectional `<Stream>` to `PIPECAT_STREAM_BASE_URL` with the
   agent ref in the path and the caller's number SEALED on the query (D-649). No database
   is read.
2. **Session.** The worker reads `GET /v1/worker/session/{ref}` from the api, which serves
   the published config, and refuses a closed, erased or pre-D-546 `churned` account's
   agent with `worker_account_closed` (D-671); a suspended account still answers. Caller
   memory, when the agent has it on, arrives from `POST /v1/worker/agents/{ref}/caller-memory`
   (D-641).
3. **Opening.** The worker speaks the published `opening_line` verbatim before the model's
   greeting (D-654). A new agent volunteers neither the AI disclosure nor the recording
   notice (both toggles default OFF since D-669), so it opens with the greeting only; a
   client switches either on per agent (D-163). Whatever the toggles say, the agent answers
   truthfully when a caller asks whether it is an AI or whether the call is recorded
   (hard rule 5, `compose_engine_prompt`).
4. **Conversation.** Tools the model may call: `search_knowledge_base` (the agent's
   knowledge pack, held in the worker's memory, PIPECAT-MIGRATION §8.1),
   `record_do_not_call`, `book_callback`, `cancel_callback`, `request_human_handoff` and
   `end_call`. The four that write go to `/v1/worker/calls/{id}/tools/*` on the api, which
   writes inside the request (D-650). A handover answers `not_available` unless
   `carrier_transfer_enabled` is on (off by default, D-662); when on, Vobiz transfers the
   caller to an Indian number on the agent's handover roster (SECURITY-COMPLIANCE §5).
   Unknown or out-of-scope questions (T4): the agent says it does not know, offers a
   call-back, and the call is tagged. The worker posts who is speaking for the live console
   (D-656). Every sentence the model writes passes `PromptLeakGuard` before the voice
   speaks it: an attempt to get the agent to reveal its instructions is declined by the
   prompt's `CONFIDENTIALITY_RULE`, and a sentence that would reproduce them anyway is
   replaced by one decline and the rest of that turn dropped (D-674).
5. **After the hangup.** Transcript turns reach the api during the call in observation
   batches (`/v1/worker/calls/{id}/observations`); after the pipeline drains, the worker
   posts its settlement (`/v1/worker/calls/{id}/settlement`):
   final status, carrier call id and per-leg metered quantities. The api writes the `calls` row,
   prices the minutes from the published config (D-648) and puts ONE `post-call:{call_id}`
   outbox row on the books, which runs the post-call pipeline (§6). Vobiz's hangup callback
   reaches voice-runtime, is acked under 500 ms into the inbox, and
   `workers/carrier_events.ingest_carrier_event` advances the call's status and queues the
   CDR read, whose cost becomes OUR cost for the carrier leg as one compensating row
   (`ux_usage_events_carrier_cdr`). The recording arrives separately: Vobiz's `RecordStop`
   names its recording id, `workers/carrier_recordings.py` copies the audio into our
   `recordings/` and sets `calls.recording_url`, fans out `call.recording_ready` to
   endpoints opted into recording links (WEBHOOKS §1), and the 20-minute sweep deletes
   Vobiz's copy a day after ours is stored (D-670). Our copy is kept 90 days
   (`workers/retention.py`, seeded `recording` policy).
6. SLO: lead + summary visible in client dashboard < 2 min after hangup.
After-hours: agent runs 24/7 by default; "after_hours" flag set from business_hours →
dashboard "after-hours captured" metric; escalation rules can differ after hours.
Closed account: closing an account detaches every number from its agent at the carrier
(`agents/lifecycle.release_account_numbers`) and the undo re-attaches them; the session
refusal in step 2 is the backstop (D-671, §9).
Failure: an answer the carrier cannot fetch or a worker that cannot start leaves the caller
with whatever the carrier does on failure (OPERATIONS §2 V-series); a missed hangup callback
does not leave the call open, because the worker's settlement carries its final status.

### 3a. The same call on `ENGINE=thinnest` (D-678, D-682)

ThinnestAI hosts the agent and the call (`docs/THINNEST-INTEGRATION.md`), so voice-runtime
answers nothing and no worker of ours is on the line. The number is ThinnestAI's own, rented
and pointed at the agent in their console (Vobiz is never used on this engine).

caller dials the client's number → ThinnestAI answers with the published agent →
1. **Opening.** The agent's `greeting` is our opening line, verbatim (D-669); the
   instructions are `compose_engine_prompt`'s, with the business facts moved into one
   knowledge document (founder, 6 Oct 2026). The truthful-answer floor and
   `CONFIDENTIALITY_RULE` are in the prompt and were read back at publish; there is no
   output guard on this engine (SECURITY-COMPLIANCE §6.1 item 4).
2. **Conversation.** The agent's in-call actions (opt-out, call-back, call-back cancel,
   hand-over request) are ThinnestAI custom actions calling the api at
   `ENGINE_ACTIONS_BASE_URL` with the agent's own secret header; they reuse the same service
   functions the Pipecat worker's tools call. There is no live transfer: a hand-over is
   recorded for the client, not bridged.
3. **After the hangup.** ThinnestAI posts signed `call.completed` and `call.analysed` to
   voice-runtime `/hooks/v1/engine/thinnest`, which verifies the HMAC against the agent's
   sealed secret, dedupes in the inbox, acks under 500 ms and queues the sealed body for
   the worker (hard rule 3). The worker writes the call row, the transcript (redacted as
   on every engine), runs our extraction, CRM and leads, meters the minutes at the
   operator-attested rate in 30-second pulses (hard rule 7), debits the wallet at the
   client rung the publish stamped (Clear, D-681), copies the recording into our
   `recordings/` (kept 90 days) and fans out the client webhooks, `call.recording_ready`
   included.
4. **Reconciliation.** ThinnestAI attempts each delivery once and switches an endpoint off
   after five failures, so a sweep settles any call from their call list that we have not,
   and another switches a disabled endpoint back on with an alarm.

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
3. Dial through `agents.service.dispatch_call`, the one dial path: paced to `carrier_cps`,
   then, under one advisory lock in the intent transaction, refused with
   `carrier_lines_busy` if the carrier's outbound pool is full (`carrier_lines_in_use()`,
   D-663), and refused with `number_not_on_carrier` if the caller ID is not on the active
   carrier. The agent opens with the lead's context ("you enquired about…").
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

**Concurrency reservation (our dispatcher).** The carrier account's lines are shared by
every tenant, inbound and outbound together, so one client's campaign must never starve
another's inbound receptionist. Vobiz refuses a dial over the account's concurrent-call
limit with `429` and turns an inbound caller away with SIP 503
(`vobiz-findings/mirror/pages/call/make-call.md:134`), so the reserve is ours to hold
(D-663). `apps/workers/campaign_dispatch.py` budgets, in order: (1)
`Settings.carrier_concurrency`, the account's lines (default 3, the founder's account as
read in the Vobiz console on 2 Oct 2026; OPERATIONS §2 gate V-5); (2) minus the inbound
reserve, `max(1, ceil(lines × inbound_reserve_ratio))`, never zero — at the defaults one
line for callers and an outbound pool of two (`engine/carrier_pacing.outbound_line_pool`);
(3) the tenant's plan `concurrency_ceiling`, clamped to that pool; (4) the campaign's
slider, at most the tenant ceiling. That is the BUDGET. The ENFORCEMENT is inside every
dial's intent transaction (`agents.service.dispatch_call`): dials are paced to
`carrier_cps` (default 1), then one advisory lock counts the calls holding a line on the
carrier in both directions (`carrier_lines_in_use()`) and refuses with
`carrier_lines_busy` before the INSERT. That covers the dials the tick does not make (the
"call this lead" button, lead ingest, call-backs). The call row's status is the hold, so
nothing has to release a line; a Redis counting semaphore was rejected because a lost
release leaks a line until a TTL. Only a `429` on call create is retried, and an unknown
dial outcome never is, because Vobiz documents no idempotency key (D-662). Secondary
ceilings — Sarvam STT concurrency and the LLM provider's rate limits — are not modelled by
the dispatcher.

## 6. Post-Call Pipeline (worker jobs, keyed by call_id, idempotent)

fetch_recording → redact_transcript → extract(schema) → upsert_lead(+repeat-caller flag on
phone match) → meter_usage(write unit rows + update spend_state) → notify(hot-lead rules:
e.g., status hot OR urgency=emergency ⇒ WhatsApp+email to owner within 2 min) →
resolve_campaign_contact → outbound_sync(call.completed via the outbox, D-23).
On the owned runtime the pipeline never fetches the recording itself: the carrier reports it
after the hangup, `workers/carrier_recordings` copies it (§3 step 5), and the pipeline's
copy stage reads `calls.recording_url` as already copied (`engine/pipecat.py`,
`get_execution`).
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
  agent at the carrier and the undo re-attaches them; the numbers are not released, which
  stays the client's choice above. The worker's session read refuses any call that still
  reaches a closed or erased account's agent (`worker_account_closed`), and a hangup for an
  erased account writes no call row.
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
- **The carrier is reached by a task, and its recordings by a call** (D-664/D-668). Both
  erasures open a `telephony` processor-erasure task quoting `calls.carrier_call_id` and
  any carrier recording ids, because Vobiz's call records are erased by written request;
  the recordings themselves are deleted through Vobiz's recording DELETE. Refs minted by
  our own runtime (`pipecat:<tenant>:<id>`) name rows the erasure already reached and are
  left out of vendor tasks.

## 10. Number Provisioning & DLT Roles (reference)

**No physical SIMs.** All numbers are virtual DIDs (Exotel / Vobiz / Plivo), routed over
SIP, stored in `phone_numbers`.

⚠ **THIS PARAGRAPH AND THE CARRIER SPLIT BELOW WERE WRITTEN FOR THE BOLNA ERA AND MISLED A
READER ON 17 SEP 2026** — into believing Calevate provisions numbers and that outbound runs
on 140-series. Both were read off this page and taken as current, which is exactly the cost
of a stale blueprint. What the sentence used to carry: that the three providers were
"connected to the engine", with Bolna's own guides verified for each and Vobiz inbound only
ASSERTED in their capability matrix. **D-592 removed Bolna**, so there is no engine to
connect a number to — the worker is ours and the carrier (Vobiz, D-662) is reached directly.

**READ `docs/evidence/dlt-roles-and-operating-model-2026-09-18.md` BEFORE THIS SECTION.** It
carries the three models (A closed by UL-VNO licence text, BYON with no documented path,
B documented), the KYC-versus-DLT distinction, and the unresolved question of where a
Telemarketer ID attaches to a VOICE call — which nothing in this repository can answer and
which decides whether a ₹5,900 registration is spent at all.

**CALEVATE DOES NOT BUY, SELL, RENT, ALLOCATE OR PORT A NUMBER — MODEL B**
(`docs/legal/LEGAL-OPS-PLAYBOOK.md` §9). The client's entity is on the CAF and the carrier
KYC, the client is the subscriber of record and the PE on DLT, and we are the TM. The
client keeps its own carrier credentials. Model A — a pool of numbers in our name, allocated
to clients — reads as unlicensed telecom resale (UL-VNO is a licensed category) and is
refused outright for a proprietor with no corporate veil (`:249`). A client who asks us to
"just give them a number" is sent to Exotel/Plivo/Vobiz or lost as a deal (`:266`), and
opening a Calevate carrier account to park client traffic on is stop-list item 10. The
founder's own Vobiz account (D-662) is a TESTING account carrying the founder's own calls
only; client traffic on it waits on Vobiz's written consent (OPERATIONS §2 gate V-10), and
the client number browse/buy path (`campaigns/number_catalog.py`, D-537, whose rental D-665
collects) refuses every purchase while `number_resale_authorization` is unset (gate 47).

**And "provisioned via API" was never true of the regulated series anyway.** The 140- and
160-series numbers outbound campaigns run on have **no provisioning endpoint at all** —
`POST /phone-numbers/buy` cannot reach them. Getting one is a paperwork sequence a human
runs on the client's side: DLT Principal-Entity registration, documents to the carrier's
compliance address, carrier allocation, then header and template approval.

⚠ **THE CARRIER SPLIT BELOW IS BOLNA'S, NOT OURS, AND IT NO LONGER BINDS ANYTHING.** It
read: *"the carrier is not a preference either — it is fixed by the series, in the vendor's
own table: 140-series → Vobiz, 160-series → Plivo"*, sourced from
`bolna-findings/mirror/pages/guides/inbound/obtaining-regulated-phone-numbers.md`. That was
a fact about which carriers BOLNA could buy each series through, and Bolna is gone
(D-639). Our own Vobiz account (D-662) carries test calls on whatever series its numbers
are; which series a client's outbound numbers need is decided by TRAI's classification,
not by a carrier table. `campaigns/provisioning.KNOWN_PROVIDERS` still names three
carriers.

Two corrections that followed from reading TRAI's own text rather than the vendor's table:
**1600xx is restricted to RBI/SEBI/IRDAI/PFRDA-regulated entities and government** (TRAI
clarification, 10 July 2026), so ordinary SMB clients cannot have it whatever a carrier
table says; and the ₹5,900 PE registration figure recorded in `docs/LEGAL-SURFACE.md:1284`
is **₹5,000 + 18% GST**, not a separate charge.

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

## 11. Buying Credit and Paying for a Call (prepaid wallet, per-lot rates)

Trigger: a self-serve client's wallet is low, or is empty at signup. This is the flow
§8's monthly cycle does NOT cover — §8 is the managed motion's retainer, overage and
invoice; this is prepaid credit, and the two never meet on one account.

**The one sentence to hold on to: a credit is ₹1 and never expires, but a MINUTE has a
price, and that price belongs to the PURCHASE rather than to the account.** A bigger pack
buys a cheaper minute — as a falling rate, not as bonus credits — and it is two rates,
because the voice tier is chosen per agent (D-547,
`docs/PLAN-CREDIT-LOTS-AND-VOICE-TIERS.md`). What carries the pair is the **lot** each
purchase opens (DATA-MODEL §8 `credit_lots`).

### The card

| Pack | Amount | Sarvam ₹/min | Cartesia ₹/min |
|---|---|---|---|
| `starter` | ₹2,000 | 5.00 | 8.00 |
| `growth` | ₹5,000 | 5.00 | 7.00 |
| `scale` | ₹10,000 | 4.85 | 6.75 |
| `plus` | ₹15,000 | 4.70 | 6.50 |
| `pro` | ₹25,000 | 4.60 | 6.25 |
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
   minutes and the agent's voice — the tier is a pure function of the chosen voice's
   provider, so an agent cannot hold a Cartesia voice and a Sarvam price.
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

   ⚠ **NO CLIENT-FACING SURFACE NAMES A VENDOR AS A PRODUCT TIER** (founder, 7 Sep 2026).
   The two voice qualities are **Clear** (spoken by Gnani Timbre v2.5) and **Studio**
   (Cartesia Sonic 3.5), defined once
   in `billing/rates.VOICE_TIER_LABELS` and SENT to the browser beside every per-tier
   figure — a second copy in TypeScript is how the two drift and a client meets both names.
   ⚠ **THIS PARAGRAPH SAID "Clear (Sarvam)" AND SAID EVERY FIELD "keeps the VENDOR
   spelling", AND BOTH ARE NOW WRONG** (corrected 19 Sep 2026). D-629 took Sarvam off the
   synthesis leg on 18 Sep 2026 — it is still the STT vendor on every call — and D-630
   renamed the money columns and wire fields to the RUNGS the next morning. So the fields
   named below keep the **rung** spelling, not a vendor's: `voice_tier`,
   `clear_inr_per_min`, `clear_minutes` are `clear`/`studio`
   (`billing/rates.py::VoiceTier`), and a lot's two rates were renamed by
   `alembic/versions/f1c40d8b6e93_voice_tiers_named_for_rungs.py`, which refuses against a
   non-empty table because they are frozen at purchase. What the paragraph was protecting is
   unchanged and is what the rename served: an auditor reconciles a column against an
   invoice, so a money column must never be named for a supplier that can be swapped.

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
left on a `plus` lot (₹4.70 Clear) and 5,000 on a newer `starter` lot (₹5.00) takes a
12-minute Clear call. ⚠ (This worked example said "Sarvam" for the rung; the rung is `clear`
since D-630, and both ₹ figures are from the card in force on 7 Sep 2026 — today's is Clear
flat ₹4.00, `billing/credit_packs.py::PACK_CATALOGUE`. It is kept at the old rates
deliberately: with Clear flat, no two packs price a Clear minute differently, so the split
this example exists to show could not be built from today's card at all.) The oldest lot pays for 8.51 minutes and empties; the remaining 3.49
minutes are priced at ₹5.00 off the newer lot. One call, one `usage` row, TWO entries in
`meta.lots`, and the totals in the panel are the sum of the splits — never minutes × one
rate. This is the ordinary case at every pack boundary, not an edge case, and it is the
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
- **A voice is sold only on an attested price.** On the owned runtime the worker calls
  Cartesia and Gnani directly (PIPECAT-MIGRATION §5), so OPERATIONS §2 gate 52 — the
  rented engine's wire shape for a Cartesia agent — went with Bolna (D-639). What still
  holds a voice back is `agents/voice_offer.tts_price_is_billable`: until the vendor's key
  is installed and an operator attests its price, the picker marks the voice unavailable
  with its named reason — the rule `offerable_models()` already applies to an LLM.
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
pack X's rates" override) and `/admin/spend` (Sarvam vs Cartesia minutes, revenue from the
splits, attributed TTS cost beside the plan fee).
