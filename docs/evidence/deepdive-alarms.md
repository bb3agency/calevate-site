# Deep dive: alerting and observability — what was dead, and what now fires

*18 Aug 2026. Scope: the three OPERATIONS §4 alarms the 18 Aug register lists as OURS and
still open (complaint-spike, engine 5xx spike, cert expiry), the alarm/metric vocabulary
sweep in both directions, redaction on the alerting path, and whether an alert delivers.*

Every finding is labelled **PROVEN** (executed here) or **REASONED** (read).

Decisions taken: **D-202** (the sweep + the index + the metric recorders), **D-203**
(complaint spike), **D-204** (engine error spike), **D-205** (TLS expiry). Migration
`c4f70b1e28da`.

---

## 1. What was dead

**PROVEN.** Before this change, an AST walk of `apps/`, `packages/` and `scripts/` for
`alert()` call sites, `ProblemError(failure_stage=…)` constructors, ack-meter `*_code`
fields and the host chain's shell alarms found **113 alarm codes this platform can send to
a human** — and:

| | Count |
|---|---|
| Alarm codes the tree can raise | 113 |
| Of those, appearing in **no** document anywhere | **44** |
| §4 trigger-list entries with no call site | 3 of 8 |
| Metric names emitted **outside** the named recorders | 3 |

The three missing alarms are the register's item. The 44 are the mirror-image defect and
nobody had counted them: `retention_below_trai_floor` arriving on a phone at 3am, with
nothing anywhere to look it up in, costs an operator a code search before they can begin.

The §4 trigger list is where the first defect lived, and its shape is the reason it
survived: it was **prose naming no codes** — "complaint-spike on campaign; engine 5xx
spike; … cert/domain expiry" — so nothing mechanical could ever have checked it. D-183 had
already rewritten it to say which entries existed; a person had to read the tree to know.

**Three ad-hoc metrics** (PROVEN, by AST) contradicted `core/alerting.py`'s own docstring
("ad-hoc counters are not accepted"): `speed_to_lead_seconds` — FLOWS §4's 60-second
product claim — plus `dispatch_tick_seconds` and `campaign_dials`, all emitted with a raw
`metrics_log.info("metric", …)`. `speed_to_lead_seconds` also had a **second** recorder
function of its own in `ingest/service.py`, which is the "two ways to do one thing" defect
in the module that documents the one way.

---

## 2. What was wired

### 2.1 `campaign_complaint_spike` (D-203)

`apps/api/campaigns/complaint_spike.py`, called from `_dispatch_for_campaign` **before the
claim**, in the claiming transaction, beside the standing compliance gate.

**Condition.** Of this campaign's calls with `status='completed'` in the last 24 hours,
how many have a `consent_ledger` withdrawal against them. Fires when **both** `optouts ≥ 5`
and `optouts / connected ≥ 0.10`. Then: `record_compliance_block(rule="complaint_spike")`,
CAS `running → paused`, `audit_log` row (`campaign.paused`, `actor_type=system`), and the
alert.

**Threshold argument.**

- **5** is TRAI's own number used as a *ceiling*: five unique complaints inside ten days
  obliges the access provider to suspend the client's outgoing service (TCCCPR Second
  Amendment, in force 12 Feb 2025, tightened from ten-in-seven —
  <https://www.pib.gov.in/PressReleasePage.aspx?PRID=2102413>). What we can count is not
  complaints but the strict superset that precedes them: everybody who files one said it
  to the agent first. Five is therefore the first count provably in the same order of
  magnitude as the number that ends the client's ability to dial.
- **10%** keeps the count honest at scale — five in a thousand conversations is a good
  list. Reference point: a measured 10,794-call cold outbound study reports **4.1%** of
  calls ending in a do-not-call request (<https://ccdocs.com/outbound-call-center/>). Our
  clients dial consented lists (the gate refuses a purchased one), so one in ten is about
  2.4× worse than cold-calling strangers.
- **24 hours** is one calling day; the platform window is 09:00–21:00 IST, so a spike
  stops today and tomorrow measures afresh. Measuring since launch would mean one bad
  morning could never be resumed; an hour is too short for a slow campaign to accumulate
  five of anything.
- **Both conditions, not either.** Count alone pages a large healthy campaign; rate alone
  pages a campaign that dialled four people and lost one.

**Why it pauses.** FLOWS §5 says "pause + notify" and D-149's dispatcher comment already
referred to the auto-pause as an existing safety. An alert that arrives while the campaign
keeps dialling watches the damage.

**Cost.** `ix_calls_campaign_started` (partial, `campaign_id IS NOT NULL`) — this is the
first query in the repo to filter `calls` by campaign, and it runs every 30 seconds per
running campaign.

### 2.2 `engine_error_spike` (D-204)

`apps/api/engine/health.py`, called from both adapters' `_request`: on `status >= 500`, and
on a transport failure. State: `platform_engine_health`, one upserted row per
`(engine, minute)`.

**Threshold: `3 × WORKER_MAX_TRIES + 1 = 10` in 5 minutes.** Derived, not chosen — one
unlucky operation already produces `WORKER_MAX_TRIES` failures by itself, so any threshold
at or below 3 pages for a single call. Written as arithmetic so widening the ladder moves
the threshold with it. Five minutes is the window §4 already uses for "webhook failures >
3/5min" (one window vocabulary, not two) and is ten dispatch ticks.

**Counting "unreachable" too is a deliberate departure from the doc's literal "5xx".** A
platform that is entirely down refuses connections rather than answering 502, so a strict
reading would have been silent through the total outage and loud only through the partial
one. Two columns (different first move for an operator), one alarm (a dial does not care).
429 is excluded — the vendor working as designed, with its own ladder.

**Postgres, not Redis.** Redis is present and `alert_admission` already counts in it — but
that counter may only ever *suppress* a page, and this one *creates* one. A counter that
can invent a page must be as durable as what it reports on.

### 2.3 `tls_certificate_expiring` / `tls_certificate_unreadable` (D-205)

`apps/workers/tls_expiry.py`, a daily cron at 04:05.

**Ours, and it is the whole of ours.** It handshakes with the **origin**
(`TLS_ORIGIN_ADDRESS`, new setting, default `host.docker.internal:443`) with the public
hostname from `WEBHOOK_BASE_URL` in SNI, verification off, and reads `notAfter` from the
DER. Alerts at **≤ 21 days**, and separately when the certificate cannot be read at all.

- **Not the public name**: Cloudflare proxies in Full (strict), so a handshake with
  `hooks.calevate.tech` returns *Cloudflare's* edge certificate — self-renewing, and valid
  for months after ours has died. The origin expiring shows up as a 526 while an
  outside-in check reports green.
- **Not the PEM file**: a file read proves certbot *wrote* a certificate; a handshake
  proves nginx is *serving* it. Those differ in exactly the failure
  `infra/nginx/README.md` §4.3 warns about (`certonly` never touches nginx).
- **21 days**: certbot renews at a third of the lifetime remaining — 30 days for a 90-day
  Let's Encrypt certificate — and tries twice a day, so 21 days is roughly eighteen failed
  renewals. Past any transient failure, three weeks of runway, and no later than the
  20-day notice **Let's Encrypt stopped sending on 4 June 2025**
  (<https://letsencrypt.org/2025/01/22/ending-expiration-emails/>) — which is why nothing
  else is watching.
- **Deviation from D-183**, which expected a systemd timer in `infra/`: nothing in `infra/`
  has ever been installed, so that would be an alarm that has never run. Argued in D-205.

---

## 3. The sweep, both directions

`scripts/check_alarm_wiring.py` — in `make guardrails` and in `.github/workflows/ci.yml`,
catalogued in ENGINEERING-PRACTICES §2, negative controls in
`tests/alarm_wiring_guard_test.py` (15 tests).

**Nothing is listed by hand.** The raised set is derived from five shapes, because
`alert()` is reached five ways and only the first is greppable:

1. a literal code;
2. an f-string's literal prefix (`unhandled_exception:<ExcType>`), which is what the alert
   fingerprint keys on anyway;
3. a `ProblemError` carrying a `failure_stage` — `core/errors.py` relays it into `alert()`
   verbatim, so `engine_rejected` and `engine_rate_limited` page a human from a
   constructor a hundred lines from any `alert(`;
4. a `*_code` on a module constant or a frozen ack meter (`meter.slow_code`,
   `meter.body_timeout_code`);
5. the **host backup chain in shell**, which cannot call `alert()` at all and reaches the
   same inbox through `notify.sh` → `host_alert.py`. An operator cannot tell the two apart
   when the mail arrives, so neither may the guard.

Two call sites whose code is genuinely a runtime value are named in `DYNAMIC_ALERT_SITES`
with the codes they raise and the reason — and **each claimed code is re-verified as a
literal in that file**, so a rename fails the build rather than silently emptying the
index (the `check_compliance_invariants` contract).

**Results, PROVEN, on the current tree:**

| Direction | Found | Disposition |
|---|---|---|
| Documented → never raised | 3 (`complaint-spike`, `engine 5xx spike`, `cert expiry`, as prose) | Wired (§2). §4's list now names codes and points at the index. |
| Documented → never raised, after the rebase | 4 (`clerk_webhook_unconfigured`, `clerk_webhook_bad_signature`, `clerk_mirror_failed`, `identity_mirror_pending`) | Removed from the index — Clerk left the tree with D-177/D-178. **The guard found these, not a person.** |
| Raised → undocumented | **44** at first run; then 4 more after the rebase (`engine_agent_route_withdrawn`, `reconciliation_probe_incomplete`, `tenant_spend_capped`, `tenant_spend_cap_approaching`) | All 113 now have an index row with a meaning and an action. |
| Metric emitted outside the recorders | 3 | Became `record_speed_to_lead`, `record_dispatch_tick`, `record_campaign_dials`; every call site moved in the same change; the duplicate recorder in `ingest/service.py` was deleted. |
| Runbook citations that resolve to no file | 0 after `runbooks/tls-expiry.md` landed | Checked every run. |
| Backticked names in the operator docs resolving nowhere | 10 raw, **8 false** | Two narrowings, argued in the code: `tests/` joins the corpus (runbooks legitimately cite tests), and a document's own fenced blocks resolve names for that document (a SQL alias). One composed leading word may be stripped, because `f"blocked_{rule}"` is a real string in a log and in no file. |

**It refuses rather than passing when it matches nothing** — separately for the Python
scan, the shell scan and the index parse.

The index (`runbooks/alarm-index.md`) is a **document**, not a generated file: a generated
table cannot carry "what to do", which is the only column that matters at 3am. What is
derived is the check, so the prose can be wrong about the world for exactly one CI run.

---

## 4. Redaction on the alerting path (hard rule 6)

**PROVEN, clean.** An AST walk of every `alert()` and `_record()` call site in `apps/`,
`packages/` and `scripts/` found **no PII-shaped keyword name** on any of them — the
vocabulary in use is `tenant_id`, `campaign_id`, `call_id`, `execution_id`, `lead_id`,
`contact_id`, `engine`, `provider`, `route`, `path`, `host`, `reason`, `kind`, `rule`,
counts and percentages. Every interpolated `detail` was read: counts, exception class
names, durations, our own engine names, our own reason codes.

Two carry an upstream string — `outbound_webhooks.py` (`result.error`) and `whatsapp.py`
(`result.reason`) — and both are covered by design rather than by luck: `alerting._body()`
puts `detail` and every id through `redact_mapping`, and `JsonFormatter` puts the log
record's extras through the same function, so **both roads out of the process are
redacted by one implementation**. The three new alarms carry ids and integers only, and
`test_the_alert_carries_ids_and_counts_and_never_a_number` asserts it for the one that
handles a person's number.

**Metric labels, PROVEN clean**: `provider`, `stage`, `reason`, `kind`, `rule`, `outcome`,
`blocked` — closed vocabularies, no free text.

**The Langfuse hook named in hard rule 6 does not exist**, and that is already recorded
rather than hidden: D-49 removed the configuration, and `core/observability.py` says so in
its own docstring. What replaced it is stronger and is real — `_RedactingSpanExporter`
applies `_redact_span` to **every** span leaving the process (not a hand-called function),
span attributes are an **allowlist** rather than a denylist, and `scrub_event` covers
Sentry's exception message and `logentry` as well as request/locals. That surface is
clean and covered by `tests/observability_config_honesty_test.py` (**PROVEN**, 34 tests
pass with the alerting suites).

---

## 5. Do the alerts DELIVER?

**PROVEN, on this machine**: `get_transport()` resolves to `console` and `alerts_email` is
unset, so locally an alert prints and reaches nobody. That is correct for a laptop and is
exactly the state the boot checks name (`alert_delivery_unconfigured`,
`alert_delivery_has_no_transport` with a reason).

**Wired and working, REASONED from the code plus PROVEN by the existing suites** (34 tests
in `alert_delivery_test.py`, `alert_multiprocess_test.py`,
`observability_config_honesty_test.py`): the log line first and unconditionally; the
delivery thread; per-fingerprint suppression and the token bucket, shared across processes
through Redis and failing open; the retry; the failed-delivery `_forget`; the host relay
`notify.sh` → `alert-to-app.sh` → `host_alert.py` → `alert()`.

**Externally blocked — nothing in this repo closes these:**

| What | Why it is not ours |
|---|---|
| **Resend account with a verified sender domain** | An unverified sender is refused per send (403 → `email_sender_rejected`). Boot cannot check it; only a real send can. Until it exists, every alarm above is a log line. |
| **`ALERTS_EMAIL` + `EMAIL_PROVIDER` + `RESEND_API_KEY` on the host** | Values from the secrets manager, placed by a human (DEPLOYMENT §6 tier 1). |
| **A Sentry project** | `sentry-sdk` is an opt-in dependency group and is **not installed here** (PROVEN). The DSN in the dev `.env` reaches nothing. |
| **The Healthchecks.io dead-man check** for the backup heartbeat | A hosted monitor and a credential. |
| **DOMAIN-registration expiry** | The registrar is the authority, the notice goes to the registrant, the remedy is a payment. Named in §4 as external rather than implied. |
| **A real certificate on a real host** | `tls_certificate_expiring` is fully wired and tested against a real TLS socket, but it measures nothing until there is an nginx serving a certbot lineage. The check is ours; the certificate is not. |

---

## 6. Sub-surfaces found CLEAN

- **Redaction on the alert and metric path** — no PII-shaped label anywhere (§4).
- **Sentry / OTel / span redaction** — allowlisted attributes, both exporters covered,
  readiness ladder that names a broken configuration by field at boot.
- **The alert delivery mechanics** — suppression, bucket, cross-process admission,
  fail-open Redis, retry, `_forget` on a failed delivery, host relay.
- **`FailureStage` discipline** — every new alarm uses an existing member; none needed a
  new one.

## 7. Still open, and whose it is

- **`latency p95 breach 15-min sustained`** — the one §4 trigger still unimplemented, and
  it is the one that genuinely needs the metrics pipeline DEPLOYMENT §8 defers: a
  percentile over a sliding window is not a counter, and computing it from the
  `webhook_ack_ms` / `tool_ack_ms` log lines would mean building the scraper inside the
  alarm. `webhook_ack_slow` and `tool_ack_slow` fire per breach today, which is the honest
  subset. Recorded in §4 rather than implied.
- **Everything in §5's external table.**
