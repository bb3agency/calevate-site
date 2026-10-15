# Runbook — the auto-healer

What it is: one registry of repairs the platform makes on its own (D-701,
`apps/api/healer/playbooks.py`), a per-minute tick that advances every open incident
(`run_healer`), a scorer that turns real calls into per-agent health four times an hour
(`score_agent_health`), and an append-only ledger of everything either did
(`heal_actions`). The operator's screen is `/admin/ops/healer`; the client's is
Settings → Line protection.

Ground rules: ids, codes and counts only; never a caller's or an owner's number in a
ticket, a log or a screenshot (hard rule 6). Production SQL goes through the audited admin
path (SECURITY-COMPLIANCE.md "Admin access path") and is read-only unless a step below
says otherwise.

---

## 1. Read what it is doing

`/admin/ops/healer` lists every incident (unresolved first), every playbook with what it
does, how it proves the repair worked, its limits and whether it is paused, and the
ledger. An incident's states are `open` (detected), `mitigated` (acted, waiting to
verify), `escalated` (needs a person) and `resolved`.

The kill switches are console settings, changed on the configuration screen under
Auto-healer: `healer_enabled` (everything) and `healer_paused_playbooks` (comma-separated
playbook keys). The agent settings check (`engine_drift`) cannot be paused by either: the
same read-back silences an agent proven to have lost its truthful-answer rule.

## 2. A client's line is held (`agent_line_broken`)

Most of an agent's recent real calls failed or ended inside ten seconds. The playbook
`line_protection`:

1. repairs the agent's own settings, call-event endpoint and in-call actions once;
2. if calls still fail fifteen minutes later, holds the line: callers are handed to the
   client's backup phone where the voice platform can do it (on ThinnestAI the agent is
   paused and each of its numbers forwarded with `forwardTo`, cleared again on restore,
   D-743; `healer_forward_refused` if the platform will not ring that phone),
   otherwise they hear the neutral can't-take-your-call sentence; the agent's running
   campaigns are paused under `campaigns.paused_by_heal_id`; the client is told by
   dashboard notice, email and (once H-1 is closed) WhatsApp;
3. after at least thirty minutes, once the agent reads back cleanly and the platform has
   answered without errors for fifteen, gives the line back with a verified publish,
   resumes only the campaigns it paused, re-queues the attempts that failed during the
   incident, and watches the line for two hours;
4. if the line breaks again in that watch, holds it again and pages
   `healer_line_relapsed`; it will not give it back on its own after that.

To give a line back by hand: press "Mark as handled" on the problem on `/admin/ops/healer` (step-up). The
client can also press "Turn the line back on now" on their Line protection screen.

The agent's script is never touched by the healer. If the cause is the script, the client
has a proposal to restore the previous version (`heal_proposals`); read it with them.

## 3. Every line at once (`engine_platform_outage`)

Several clients' lines broke together, or the voice platform failed twice its spike
threshold of requests in ten minutes. There is no second voice platform to move calls to
(ThinnestAI is the only engine, D-763). The playbook
`engine_outage` posts "Calls are not connecting for some customers" on the status page,
holds every client's answering line, pauses every running campaign and pages. Every five
minutes it retries the holds the platform refused and checks for fifteen quiet minutes;
then it gives every line back and marks the status post resolved.

What you do: confirm with the voice platform's own status, and keep the status page title
honest (Incidents → the outage → status post). Do not resolve it by hand while the
platform is still failing: the holds would be lifted onto a dead platform.

## 4. An incident needs a person (`healer_needs_person`)

A playbook ran out of attempts (`outbox_replay`, `engine_webhooks`, `workspace_retry`,
`agent_repair`) or met something it never acts on (`money_review`). Read the incident's
ledger rows on `/admin/ops/healer`, fix the cause with the runbook for the alarm that woke
it (`runbooks/alarm-index.md`), then press "Mark as handled". "Check again now" runs its next step
on the next tick; it is refused (409 `heal_incident_not_retryable`) for a problem the healer
never acts on and for a repair switched off in configuration.

A handed-over repair is still re-checked on its own cooldown (20 to 60 minutes, the
playbook's), not every six hours, and closes itself the moment the check passes; the screen
then says "Cleared on its own after it was handed to you". Failed re-checks of a
handed-over problem write no ledger rows. A problem closed after its alarm last fired is not
reopened by that alarm's quiet hour; only a fresh occurrence opens a new one (D-776).

## 4a. Ask Pip to fix it (D-776)

The healer is Pip's work. Every open problem on `/admin/ops/healer` has "Ask Pip to fix
this", which opens Pip with the problem's ref written in the ask box (nothing is sent until
you press Ask). Pip reads the problem (`healer_incidents`, `healer_incident`), explains it
and suggests one of three confirmed actions, each going through the screen's own code:

- `healer_retry`: "Check again now" (`ops:manage`, no step-up).
- `healer_resolve`: "Mark as handled" with your reason (`ops:manage`, the same step-up
  word `resolve_heal_incident:<id>`); the reason is written to the ledger.
- `healer_attest_rate`, money only: attests the voice platform's posted per-minute rate
  (`platform:config`, step-up `attest_engine_minute_price:<engine>:<rate>`, audit
  `platform.engine_minute_price_attested`, the same function as the Rates screen) and closes
  the money problems it explains in the same transaction.

**Money problems (`money_review`).** When the healer hands one over it stores its finding on
the incident (for example "3 of 14 charged calls differ since 09 Oct 19:12 IST. premium: we
hold ₹2.50/min, charges imply ₹2.75/min. One rate explains all. Alarm open.") and puts the
same sentence in the page email. It re-reads the evidence hourly and closes the incident
itself when the alarm is clear and the calls charged after the newest attestation all match
(for `engine_charge_unmatched`: when any call since it opened carries a charge). The
evidence is read only from our own rows: `calls.engine_charged_inr` (recorded by the charge
reconciler), the minute rows in `usage_events` and `platform_engine_minute_prices`
(`apps/api/healer/money.py`). Pip's `healer_money_review` lists the calls that differ and
the posted rate each charge implies. **An implied rate is evidence, never a figure to
attest.** Read the posted rate in the voice platform's console, type it to Pip, and confirm
with your second factor. Calls already metered are not re-priced (hard rule 4).

## 5. Founder actions before every part works

1. **Calevate's own WhatsApp (OPERATIONS gate H-1).** Create the WhatsApp Business account
   (the same Meta Cloud API account D-91 chose for hot-lead alerts), get the three utility
   templates in H-1 approved, then set in the console: the access token (Secrets), the
   sending number id, `whatsapp_provider` = meta_cloud_api, `whatsapp_enabled`, and
   `healer_founder_whatsapp` = your own number. Setting the number in the console is the
   record of your opt-in; a number that only exists in the server environment is not
   messaged. Until then pages and client notices go by email and dashboard, and
   `/admin/ops/healer` says so.
2. **status.calevate.tech (OPERATIONS gate H-2).** Add a DNS record for `status` pointing
   at the VPS (proxied, like the other hosts), make sure the origin certificate covers
   it, and add this server block beside the site's other blocks in
   `infra/nginx/calevate.conf.template`, then deploy:

   ```nginx
   server {
       listen 443 ssl;
       listen [::]:443 ssl;
       server_name status.${ROOT_DOMAIN};
       include /etc/nginx/snippets/calevate-tls.conf;
       include /etc/nginx/snippets/calevate-origin.conf;
       include /etc/nginx/snippets/calevate-headers.conf;
       location = / { rewrite ^ /status break; proxy_pass http://127.0.0.1:3000; include /etc/nginx/snippets/calevate-proxy.conf; }
       location ^~ /_next/ { proxy_pass http://127.0.0.1:3000; include /etc/nginx/snippets/calevate-proxy.conf; }
       location = /v1/public/status { proxy_pass http://127.0.0.1:8000; include /etc/nginx/snippets/calevate-proxy.conf; }
       location / { return 404; }
   }
   ```

   Check the upstream ports against the other blocks before deploying; they are written
   here as the defaults, not read from the live box. Until then the page is at
   `https://calevate.tech/status`.

## 6. Turning it off

Set `healer_enabled` to off on the configuration screen. Lines already held stay held
(the hold is the safe state); give each back from `/admin/ops/healer` with "Mark as handled" once
you are ready.
