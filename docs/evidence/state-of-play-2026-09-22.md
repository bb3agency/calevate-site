# State of play — 22 September 2026

What is true, what is decided, and what is waiting on a person. Written so the next
session (or the next morning) does not re-derive any of it.

**Evidence classes used throughout**, per hard rule 11: VERIFIED-VENDOR-DOCS (read at a
named URL or pinned mirror), VENDOR-PUBLISHED (the vendor states it; relayed by the
founder from a primary page), REPORTED (a third party says so), UNKNOWN (nobody has
looked, or the host is unreachable). A figure without a class is a figure nobody should
act on.

---

## 1. What is running

`main`, `production` and the feature branch are all on
`15501441b19cc2132538d7f71c99455d51af6551`. CI green. That sha carries a green coverage
ratchet (7 guarded surfaces at their floor, 11,467 tests).

**Two commits are finished and NOT pushed**, both waiting on one ratchet run:

| | |
|---|---|
| `bb3c870` | the audit row that opens every outbound dial was never written |
| `099d800` | FBIL going quiet is not FBIL's contract moving |

The deploy command in use, which is the form the exports must take — they are hostnames
and paths, deliberately not in `.env`, and the script never sources it:

```
sudo -u calevate bash -lc 'cd /var/www/calevate && export ROOT_DOMAIN=calevate.tech \
  TLS_LIVE_DIR=/etc/letsencrypt/live/calevate.tech \
  ORIGIN_CERT_PATH=/etc/ssl/calevate/origin.pem \
  ORIGIN_KEY_PATH=/etc/ssl/calevate/origin.key && \
  scripts/vps-deploy.sh --dry-run --all --expected-sha <40-char sha>'
```

---

## 2. Defects found and fixed, ranked by what they would have cost

**Every call ran with no opt-out, callback, cancel or handoff.** `CallRunner` gates the
four in-call tools on `isinstance(self._api, CallToolApiClient)`; production booted
through `boot.open_runtime`, which built the BASE class. The subclass passed every type
check and the gate silently handed back `None`. A caller saying *"take me off your list"*
reached nothing — no suppression row, no DNC entry, and a model left to improvise a
reassurance. Hard rule 5 and SEC-COMP §2.3, on the one act a caller is most entitled to.

The test that should have caught it read `runtime.py` as TEXT and asserted the string
`"CallToolApiClient.from_config("` appeared in it. It does — inside a door production
never opens. **Asserting that somebody wrote a line is not the claim that the line runs.**

**The autodialler notice wrote no audit row** while its own comment said *"the operator
is named in the audit row either way."* That declaration opens every outbound dial for an
account; every sibling compliance mutation audits itself. Fixed with actor and caller IP,
in the same transaction as the row.

**A worker running an unpublished script reached one log line.** On `owned_runtime` there
is no vendor to ask what an agent is running, so the witness is the worker's own
attestation. A mismatch scored `unreadable`, which the reconciliation sweep excludes from
its alarm by name — bucketed identically to "nobody has ever dialled this agent". It now
pages.

**Three alarm remediations pointed at an unmounted route.** `GET /v1/ops/kb-orphans` was
named in `alarm-index.md` three times and twice inside the worker, and no router served
it. `account_kb_report` was already public with the stated reason *"the ops route calls it
too"* — about a route that did not exist. Now mounted.

**CI had been red since 19 September and the backend suite never ran.** MinIO deleted
`minio/minio` from Docker Hub; the pull failed in under a second, which aborted the step
under `bash -e` before the health poll could report, and migrate/seed/tests were SKIPPED.
Six guardrails then failed with causes that read like real findings. None was. Repointed
to `quay.io/minio/minio` in CI and in `docker-compose.yml`.

**The public `/solutions` page promised a live transfer the engine cannot do**, and after
one rewrite still said *"the enquiry reaches whoever is on duty"* — on an owned runtime
the roster is never read and a call-back rings THE CALLER back.

**Six dependency advisories, two critical** (`next` < 15.5.24). Cleared; lockfile went
511 → 511 resolutions with no new packages.

---

## 3. Verified facts

### FX

**The pull works.** Every five minutes, successfully. Money converts at the published
rate; `Settings.usd_inr_rate` is only the fallback for when none is fresh.

**FBIL has published nothing since 2026-09-11** — VENDOR-MEASURED from the VPS (their
endpoint returns `[]` for 19–22 Sep) and corroborated by Frankfurter's view of them
(`stale_publication, as_of 2026-09-11`). **UNKNOWN — why.** `www.fbil.org.in` is
egress-blocked from the build container.

The rate in force therefore comes from `frankfurter:default`, the third rung. That is the
aggregator's own default, not the Indian benchmark administrator's number — which matters
because `LIST_PRICE_USD_INR` and the rate-card convention rest on "a published Indian
reference rate".

**What was actually broken was the refusal, not the fetch.** It reported
`unusable_response / no_usd_record` with every counter zero — a CONTRACT-shaped message
for a feed that had gone quiet. `FBIL_WINDOW` was `MAX_QUOTE_AGE * 2` (ten days) against
an eleven-day gap, so the window opened one day after the last publication and the array
was genuinely empty. Fixed: window widened to thirty days so a stale record still ARRIVES
and is refused as stale with its date, and an empty array now has its own code
(`nothing_published_in_window`) naming the window it asked about.

**The "takes effect after a restart" badge was true of an engine we no longer run.**
`usd_inr_rate` is `on_restart` because ONE reader copies it at construction — a rented
engine's adapter. `PipecatEngine` takes no `fx_rate` at all. The classification STAYS
(it is correct for Bolna, and the opposite error is the dangerous one); the caveat now
says which engines it applies to and where to look instead.

### Gemini

**The Google retirement email does not apply to this product.** It scopes itself in its
own second line to *Gemini Enterprise Agent Platform*. We call
`generativelanguage.googleapis.com/v1beta/openai` — AI Studio's Developer API.

**On our surface, neither model we run has an announced shutdown.** VENDOR-PUBLISHED,
`ai.google.dev/gemini-api/docs/deprecations`, read by the founder 22 Sep 2026:
`gemini-2.5-flash` — *no shutdown date announced*; `gemini-2.5-flash-lite` — *no shutdown
date announced*. The one row on that page carrying a date (`gemini-2.5-flash-image`,
2026-10-02) names an identifier that appears **nowhere in this tree** — every Gemini id we
name was enumerated to check.

If this leg ever moves to Vertex, the Enterprise Agent Platform dates become ours
(20 Oct 2026 public retirement; 28 Jan 2027 Flash Lite; 31 Mar 2027 Flash and Pro).

**The migration path is the hard part, not the deadline.** Every `gemini-3.*` is refused
on the vendor's own statement that Gemini 3 Flash models *"do not support full
thinking-off"* — a candidate with no content is dead air on a phone call. `gemini-3.6-flash`
is the recorded exception: the trap is eliminated there and it is noted at ~150ms TTFT.
And if Gemini vanished entirely the product would not stop — Azure and OpenAI-direct are
already selectable.

### Carrier

| | Plivo | Exotel |
|---|---|---|
| Per-minute | **₹0.38** VERIFIED from their own page 17 Sep — **but** a third-party blog says ₹0.60 on 22 Sep. **UNRESOLVED**, and `www.plivo.com` is egress-blocked here | **UNKNOWN.** No published rate card; KYC/sales-gated. Their own blog quotes ₹0.60–1.00 outbound, ₹0.30–0.50 inbound — marketing, not a quote |
| Streaming | **₹0.00, included** (their own India pricing page) | **NOT FOUND** anywhere. AgentStream docs publish latency figures and no price |
| Number rental | ₹200/mo | ~₹499/mo Exophone |

Exotel KYC is **green** (co-worker verified and added to the account, 21 Sep).

---

## 4. The margin arithmetic

Cost per call-minute, derived from the constants (not typed):

| Leg | Clear | Studio |
|---|---|---|
| Pipecat container ($0.01/min @ ₹95) | 0.9500 | 0.9500 |
| Sarvam STT | 0.5000 | 0.5000 |
| LLM (10-min call, worst point) | 0.2411 | 0.2411 |
| TTS | 1.4580 Gnani | 3.0888 Cartesia |
| **Subtotal, ex-carrier** | **₹3.1491** | **₹4.7099** |

Card: **Clear is flat ₹4.00** on all six packs; **Studio runs ₹7.00 → ₹5.50**.

| Carrier ₹/min | Clear @ ₹4.00 | Studio @ ₹7.00 | Studio @ ₹5.50 |
|---|---|---|---|
| 0.00 (today — the leg is unmetered) | 21.3% | 32.7% | 14.4% |
| 0.38 | 11.8% | 27.3% | 7.5% |
| 0.60 | 6.3% | 24.1% | 3.5% |
| 0.85 | **0.0%** | 20.6% | −1.1% |
| 1.00 | −3.7% | 18.4% | −3.8% |
| 1.50 | −16.2% | 11.3% | −12.9% |

**Break-even carrier rate: ≈₹0.85/min on Clear at ₹4.00, ≈₹0.79 on Studio at ₹5.50.**

Three things this table says that the console does not:

* **There is no carrier price at which Clear at ₹4.00 reaches the 20% target.**
* **The deepest Studio rung goes negative first** — the clients buying the biggest pack
  are the ones lost money on soonest.
* **None of it appears in the product.** The cost floors exclude telephony by decision
  (D-474), so every margin figure on the console today is the 0.00 row.

---

## 5. Open — founder's to decide

**Model A or Model B.** `LEGAL-OPS-PLAYBOOK.md:249` says do not rent numbers as a
proprietor with no corporate veil; `:621` says incorporate first and get written
VNO/reseller status. The published Terms (`terms.ts:196`) already tell every client they
hold their own account and *"remain the subscriber of record"*, and that text is
version-hashed. Meanwhile the code holds ONE Calevate-wide `PLIVO_AUTH_ID`, which is
Model A's shape. **A number for Calevate's own testing is explicitly NOT Model A**
(playbook §9.2) and needs no decision at all.

**The billable minute.** `PIPECAT-MIGRATION.md` §1.2 assigns it to the carrier's CDR;
D-474 says the client holds the carrier account and we may have no right to it. **On the
current model this product has no billable-minute producer of any kind** — every Pipecat
call bills the client zero minutes. We do have our own session clock; using it contradicts
the migration doc, and docs win, so it is flagged rather than taken.

**Whether Clear at ₹4.00 survives a real carrier bill.** See §4.

---

## 6. Open — needs a reading nobody here can take

| Question | What closes it |
|---|---|
| Plivo's current India rate — ₹0.38 or ₹0.60 | their own pricing page, in a browser |
| Exotel's per-minute rate, and whether AgentStream bills separately | a written quote; the account is KYC-green |
| Why FBIL stopped publishing on 11 Sep | `fbil.org.in` in a browser |
| Does the Plivo Voice API support a warm transfer | one question to Plivo; the adapter is declared and refusing until then |
| What a Pipecat "active minute" covers, and its rounding | the vendor |

---

## 7. The thing worth remembering

**Nobody has ever placed a real call on this product** (BLOCKER-1). Every panel, gate and
refusal is proven by tests and by reading both ends of a wire — never by a caller. The
in-call-tools defect above is what that costs: it survived eighteen days and a green test.

A first real inbound call on Calevate's own Exotel number needs no legal decision, and
would exercise: a pre-pipeline failure currently gives the caller **dead air and writes no
`calls` row**; the `developer`-role greeting may 400 on the Gemini leg; caller memory is
half-wired, so a memory-enabled agent says the sentence and recalls nothing.

That is the cheapest risk reduction available today.
