# Bolna telephony, number lifecycle, inbound linkage and SIP trunking — audited against the mirror

**Scope.** Every page under `bolna-findings/mirror/pages/guides/telephony/` (18),
`api-reference/phone-numbers/` (5), `api-reference/sip-trunks/` (9), `sip-trunking/` (5),
`api-reference/inbound/` (3), plus `guides/inbound/buying-phone-numbers.md`,
`guides/inbound/truecaller-verification.md` and `supported-telephony-providers.md` — 43
pages, read end to end. `guides/inbound/obtaining-regulated-phone-numbers.md` was read for
its PROVISIONING and API content only; its compliance content is another lane's.

**Evidence rule.** Every claim below cites `bolna-findings/mirror/pages/<path>:<line>` and
quotes the line. Where the vendor contradicts itself the contradiction is REPORTED, not
resolved — this repository has been burned three times (D-31, D-32, D-350) treating vendor
prose as specification.

**Headline.** Three of the four things this audit went looking for were already right, and
the fourth was a one-word omission with a real operator cost. TRD §5's telephony matrix and
FLOWS §10's DLT role model survive contact with the vendor's own pages almost exactly,
including the ₹5,900 PE-registration figure. The defect found and fixed is that
`NUMBER_PROVIDER=plivo` — the carrier Bolna names for the 160-series, and the one our own
engine adapter hardcodes into every published agent — was reported to operators as an
*unsupported vendor*. Truecaller and the $5/month number rental are founder/ops items, and
one of them carries an outage mode we do not model.

---

## 1. The carrier↔series map: CONFIRMED, and it is a table rather than prose

The single most load-bearing fact in this lane. `guides/inbound/obtaining-regulated-phone-numbers.md:13-16`:

```
| Number Series  | Use Case                                                   | Telephony Provider |
| **140-series** | Telemarketing and promotional calls                        | Vobiz              |
| **160-series** | Transactional and service calls (banking, insurance, etc.) | Plivo              |
```

This **confirms** two claims our tree already makes and that I had hypothesised were wrong:

- `docs/TRD.md:215-216` — "DLT-aware (their regulated-numbers runbook: 140 via Vobiz, 160
  via Plivo)". Exact match. **No gap.**
- `apps/api/engine/bolna.py`, the comment above `_agent_body`'s `tools_config.input`/`output`
  block justifying the hardcoded telephony provider, "with Plivo the 160-series (transactional) carrier … A 140-series promotional
  agent belongs on Vobiz". Exact match. **No gap.**

I went into this expecting to find that comment unsupported. It is supported, by a table,
and it is now cited from a test rather than only from a comment.

### 1a. What the API can and cannot provision — the distinction our docs blur

There are **two different Indian number classes** on this platform and only one of them has
an API:

| Class | How obtained | Cost | API? |
|---|---|---|---|
| Geographic DID (`+91<STD>…`) | `POST /phone-numbers/buy`, or the dashboard | $5/month | **Yes** |
| 140 / 160-series | Manual: DLT PE registration → documents to Bolna → carrier allocation → header + template approval | not stated | **No** |

Evidence for the second row, `guides/inbound/obtaining-regulated-phone-numbers.md`:

- `:60` — "a payment link for **₹5,900** will be generated on the portal. Complete the
  payment to finalize your Principal Entity registration."
- `:52` — "Contact [compliance@bolna.ai](mailto:compliance@bolna.ai) to solicit a sample LOA."
- `:102` — "Share your **Certificate of Incorporation (COI)** and **GST Certificate** with
  Bolna for Plivo KYC verification."
- `:110` — "Provide your **PE-ID**, **TM-ID**, and **compliance application name** to Bolna"
- `:114` — "Plivo will verify the submitted details and allocate the 160-series number"
- `:117` — "The allocated numbers will **not be active** at this stage."
- `:134` — "Once the template is approved, your 160-series numbers will be **active**"

Evidence for the first row, `guides/inbound/buying-phone-numbers.md`:

- `:9` — "Buy dedicated phone numbers directly from the Bolna dashboard. Each number costs
  **\$5/month**, billed as a recurring subscription from your Bolna wallet balance."
- `:73` — "Indian numbers require compliance verification. When you select **India**, the
  purchase flow changes: the **Pattern** field is replaced by a **Region** selector"
- `:77-82` — "Plivo … Regions: Karnataka (80), Maharashtra (22)" / "Vobiz … Regions:
  Karnataka (80), Gujarat (79), NCR (11)"
- `:85` — "The region code appears after `+91` in the phone number. For example, a
  Karnataka number looks like `+9180XXXXXXXX`."
- `:114` — "Indian numbers require compliance approval. You may need to submit identity
  documents before your number is activated."

**The ₹5,900 figure is independently confirmed.** `docs/FLOWS.md:439-440` already says "PE
registration ~₹5,900 first TSP". The vendor's own guide names the same number on the same
portal. That is a genuine corroboration of a cost assumption in our blueprint, from a source
we had not read when it was written.

**FINDING — `docs/FLOWS.md:423-425` is now wrong in one sentence.** It reads:

> "**No physical SIMs.** All numbers are virtual DIDs provisioned via API (Exotel / Vobiz /
> Plivo, connected to the engine …)"

"provisioned via API" is true for geographic DIDs and **false for the 140- and 160-series**,
which are the only two series our `NUMBER_SERIES` enum names beside `standard`. There is no
endpoint for them anywhere in the mirror; the process is documents-to-a-mailbox plus DLT
portal steps. FLOWS.md is being edited by another agent in this run, so the exact replacement
text is proposed in §7 rather than applied.

**PE/TM, one point for the compliance lane.** `obtaining-regulated-phone-numbers.md:110`
asks the *account holder* to supply "**PE-ID**, **TM-ID**". Bolna's guide is written for a
single business calling on its own behalf. In our model (`docs/FLOWS.md:436-441`) the client
is the PE and Calevate is the TM, so the pair handed to Bolna per number is *the client's
PE-ID and Calevate's TM-ID* — two parties, one form field each. Nothing in the mirror
contradicts our model; nothing in it anticipates our model either. Reported to Lane D rather
than acted on.

---

## 2. THE DEFECT FIXED — `NUMBER_PROVIDER=plivo` was refused as an unsupported vendor

`apps/api/campaigns/provisioning.py` keeps two deliberately distinct operator-facing reason
codes, and the module says why: *"'you named a vendor we do not support' and 'you named the
right vendor and we never wrote the client' are different operator problems with different
fixes."*

`KNOWN_PROVIDERS` was `("exotel", "vobiz")`. So:

- `NUMBER_PROVIDER=plivo` → `provider_not_implemented:plivo` — "we do not support that vendor"
- and yet Plivo is the carrier Bolna allocates every 160-series number through (§1), **and**
  the provider `apps/api/engine/bolna.py::BolnaEngine._agent_body` hardcodes into
  `tools_config.input/output.provider` for every agent we publish.

An operator who set the setting *correctly* was told the setting was wrong, and pointed at
the one fix that could not help. The vendor is supported; the **adapter** is what is missing,
which is precisely the distinction the second reason code exists to carry.

Corroborating citations for the membership decision:

- `api-reference/phone-numbers/buy.md:67-73` — request `provider` `enum: [twilio, plivo, vobiz]`
- `api-reference/phone-numbers/search.md:53-57` — same three-value enum
- `supported-telephony-providers.md:31-33` — Plivo / Exotel / Vobiz each "India", each
  "Inbound ✅ Yes | Outbound ✅ Yes | Bring Your Own Account ✅ Yes"
- `supported-telephony-providers.md:34` — Twilio's countries are "United States, United
  Kingdom, Singapore, Australia, etc." — India is **not** among them, which is why `twilio`
  stays out of `KNOWN_PROVIDERS`.
- `supported-telephony-providers.md:32` — Exotel stays IN, but as a different kind of entry:
  Bolna's purchase API cannot broker an Exotel number (it is absent from both enums above),
  while Exotel is a first-class bring-your-own-account integration. The constant answers
  "which vendor may sell **this deployment** a number", not "which vendor Bolna will buy one
  from", so an Exotel number bought from Exotel and connected via
  `guides/telephony/exotel-connect-provider.md` is exactly what it describes.

### Files changed

**`apps/api/campaigns/provisioning.py`** — `KNOWN_PROVIDERS` gains `"plivo"`; the constant's
comment now carries the carrier table, the citation for each name, and the reason `twilio` is
excluded. The module docstring's parenthetical was updated to match.

**`packages/shared/src/calevate_shared/config.py`** — the `number_provider` comment said "A
name outside {exotel, vobiz}". That set no longer existed; a comment naming a stale set is the
D-103/D-105 defect class, so it was corrected in the same change rather than left to drift.

**`tests/telephony_provisioning_test.py`** (new) — pins the tuple to the vendor's carrier
table rather than to itself. Asserts a **superset**, not equality, so that adding a vendor is
not an edit to a test with no opinion about it. Three checks: the transcribed table only names
series our `NUMBER_SERIES` enum has (guard on the guard); every regulated-series carrier is in
`KNOWN_PROVIDERS`; and — read through the ONE selector rather than asserted twice — each
carrier resolves to `no_provisioning_adapter:<name>` and never to `provider_not_implemented`.

**Behaviour delta is operator-facing only.** Every path still refuses;
`PROVISIONING_IMPLEMENTED` is untouched at `False`, no purchase succeeds, nothing is written,
and no client-visible response changes. Only the logged reason changes, and only for the
vendor that was being misreported.

### Sabotage verification

Break — `plivo` removed from `KNOWN_PROVIDERS`, nothing else touched:

```
SABOTAGED: plivo removed from KNOWN_PROVIDERS
E       AssertionError: 160-series carrier 'plivo' must refuse as a missing adapter,
                        got 'provider_not_implemented:plivo'
E       assert 'provider_not...emented:plivo' == 'no_provision...adapter:plivo'
E         - no_provisioning_adapter:plivo
E         + provider_not_implemented:plivo
=========================== short test summary info ============================
FAILED tests/telephony_provisioning_test.py::test_every_regulated_series_carrier_is_a_configurable_provider
FAILED tests/telephony_provisioning_test.py::test_a_carrier_resolves_to_the_missing_adapter_and_not_to_an_unknown_vendor[160-plivo]
2 failed, 2 passed, 1 warning in 0.31s
```

Restore:

```
96:KNOWN_PROVIDERS: Final[tuple[str, ...]] = ("exotel", "plivo", "vobiz")
4 passed, 1 warning in 0.27s
```

`uv run ruff check --fix` + `ruff format`: "All checks passed! / 3 files left unchanged".
`uv run mypy apps packages`: "Success: no issues found in 237 source files".

---

## 3. Number lifecycle and the money — what leaks, and when

The four endpoints (`api-reference/phone-numbers/overview.md:11-16`):

```
GET    /phone-numbers/all
GET    /phone-numbers/search
POST   /phone-numbers/buy
DELETE /phone-numbers/{phone_number_id}
```

`search` takes `country` `enum: [US, IN]` and an optional 3-character `pattern`
(`search.md:38-47`). `buy` requires `country` + `phone_number` and takes `provider`
(`buy.md:75-77`). `delete.md:7` — "Delete a purchased phone number **to stop billing** and
remove it permanently from your active inventory."

### 3a. The $5/month is real, recurring, and lands on CALEVATE's wallet

- `buying-phone-numbers.md:121` — "All phone numbers cost **\$5/month** as a recurring
  subscription. The amount is deducted automatically from your Bolna wallet balance each
  month on the renewal date."
- `buying-phone-numbers.md:124` — "Phone number charges are **separate** from call charges.
  The \$5/month covers only the number itself."
- `buy.md:99-102` — `renewal: boolean, example: true` — "Indicates if the phone number
  subscription will auto-renew."
- `get_all.md:88-91` — `renewal_at`, "Human readable renewal date"
- `get_all.md:103-106` — `price: type: string`, "Monthly rental price of the phone number",
  `example: $5.0`

**Is margin leaking today? No — and the reason is narrow.** `usage_events` already has the
unit type (`apps/api/billing/models.py:100`, `number_rental` in `CLIENT_BILLED_UNIT_TYPES`)
and it has **no writer**. `docs/evidence/deepdive-money.md:330-333` justified that:

> "**`number_rental` has no writer**, and that is not the D-181 shape: numbers are recorded
> by an operator (`agents.service.provision_number` INSERTs a row an admin typed), not
> purchased through an API, so the rental is arranged and paid out of band."

That justification is still true **and it is now conditional on a fact rather than on a
design**. It holds exactly as long as nobody buys a number through Bolna. The moment
`POST /phone-numbers/buy` is called once, $5/month begins draining a Calevate wallet with no
`usage_event` behind it and no client attribution — hard rule 7's "costs recorded per
usage_event with our unit_cost_paid" with nothing recording them. That is a **founder/ops
decision, not an engineering task**: it needs a Bolna account with a funded wallet, which
does not exist in this repository. The gate text is in §7.

Two things to get right when it lands, both already decided by our own code:

1. **A `number_rental` row carries no `call_id`.** Both partial unique indexes already handle
   it (`tests/usage_events_unique_index_test.py:186-193`, `tests/cost_partition_test.py:174`),
   so the writer needs an idempotency key of its own shape, not a new index.
2. **The figure is USD and must go through `_to_inr`.** `buying-phone-numbers.md:7` — "$5/month
   per number"; `search.md:127` — "Price of the number in USD."

### 3b. An unexpected corroboration for the cost-unit assumption (gate 7)

`apps/api/engine/bolna.py`'s `_ASSUMED_MINOR_UNITS_PER_MAJOR` block carries a marked assumption — `_ASSUMED_CURRENCY = "USD"`
and `_ASSUMED_MINOR_UNITS_PER_MAJOR = 100` — because the vendor contradicts itself: the OAS
says `total_cost` is "in cents" while `references/execution-payload.md` says "account
currency". OPERATIONS §2 gate 7 scores both halves.

The phone-number schemas describe **one price, the same $5, three times**, and they are
mutually consistent only under exactly the reading our constants take:

| Page | Field description | Example |
|---|---|---|
| `search.md:124-127` | "Price of the number in **USD**." | `5` |
| `buy.md:113-117` | "Price for the phone number **in cents**." | `500` |
| `get_all.md:103-106` | "Monthly rental price of the phone number" | `$5.0` |

500 cents = $5.00 = 5 USD. So on this surface the same spec author uses "cents" to mean **USD
minor units, divisor 100**, and quotes the account in **dollars** — printing the `$` sign
outright in `get_all`. That does not *prove* anything about `AgentExecution.total_cost`, which
is a different schema on a different endpoint, and it must not be written up as if it did. It
does mean the "cents ⇒ USD ⇒ /100" reading is now the vendor's demonstrated house convention
on a neighbouring resource rather than a precedence rule applied to two documents that
disagree. Proposed comment text in §7; not applied, because `engine/bolna.py` is being edited
concurrently by other lanes in this run and the change is comment-only.

### 3c. A documented vendor inconsistency — REPORTED, NOT RESOLVED

`telephony_provider` is enumerated three different ways on the same resource:

- `buy.md:118-125` (response) — `enum: [twilio, plivo, vonage, telnyx]`
- `get_all.md:107-113` (response) — `enum: [twilio, plivo, vonage]`
- `buy.md:67-73` / `search.md:53-57` (request) — `enum: [twilio, plivo, vobiz]`

`vobiz` cannot be *requested* into a response enum that does not contain it, and `vonage` /
`telnyx` cannot be requested at all. `sip-trunk` is a fourth value the SIP pages use for the
same field (`api-reference/sip-trunks/add_number.md:104-107`, "example: sip-trunk"). **No
value is inferred from this.** Any adapter that ever parses `telephony_provider` must treat it
as an open string, not a closed set — the failure mode of guessing is a rejected payload on a
number we have already paid for.

### 3d. Two `/call` request shapes in the same doc set — REPORTED, NOT RESOLVED

Not my endpoint, but found here and worth handing on:

- `guides/telephony/plivo-outbound-calls.md:75-78` and `exotel-outbound-calls.md:88-91` —
  `{"agent_id": …, "recipient_phone_number": "+91…"}`
- `sip-trunking/byot-outbound-calls.md:46-53` — `{"agent_id": …, "recipient": {"phone_number":
  …, "name": …}, "from_number": …}`

Same `POST https://api.bolna.ai/call`. Likewise the telephony provider is set two ways:
`tools_config.input/output.provider` on the v1 create-agent body
(`plivo-outbound-calls.md:49-57`) versus `agent_config.telephony_provider` on
`PATCH /v2/agent/{agent_id}` (`byot-outbound-calls.md:27-34`). Flagged to whichever lane owns
`_agent_body` and the dial path; nothing changed here on the strength of it.

---

## 4. Inbound linkage — the seam is real and it is not wired

`api-reference/inbound/overview.md:11-14`:

```
POST /inbound/setup
POST /inbound/unlink
```

Note the page is filed as `agent.md` but the path is `/inbound/setup`; the guides link it as
`/docs/api-reference/inbound/agent`. Use the path, not the filename.

`agent.md:36-55` — required body is `agent_id` (uuid) + `phone_number_id`, where
`phone_number_id` is documented as "Telephone number `id` from [Phone number list API]".
`byot-inbound-calls.md:57-58` — "**One number, one agent:** A phone number can only be mapped
to one agent at a time. Mapping it to a new agent automatically unmaps it from the previous
one."

**Against our model.** `apps/api/agents/models.py:380-397` gives `phone_numbers` both
`agent_id` and `engine_number_ref`. The linkage exists *in our database* and is never
asserted against the engine: `packages/shared/src/calevate_shared/engine.py`'s `VoiceEngine` protocol declares
`provision_number` and there is no link/unlink member on the port, so nothing in this
repository has ever called `/inbound/setup`. An inbound receptionist therefore answers only if
a human performed the linkage in Bolna's dashboard.

That is **not a new finding and not mine to fix** — `docs/PRODUCTION-READINESS.md:876-891`
already files `phone_numbers.engine_number_ref` as a write-only column (P4.4) whose fix is
`UNWIRED_BASELINE`, "closing when `PROVISIONING_IMPLEMENTED` does". What this audit adds is
the *content* that column will hold: **Bolna's `phone_number_id` is the only handle
`/inbound/setup` and `/inbound/unlink` accept**, so `engine_number_ref` is exactly that id and
nothing else. Recording that here means the day the seam closes, nobody has to re-derive it.

Two vendor facts that constrain the eventual writer:

- `agent.md:56-63` — `allow_multiple`, "Only applicable for **Plivo** phone numbers."
- `agent.md:64-68` — `ivr_config`, "Optional IVR configuration for **Plivo** phone numbers."

**AMBIGUITY, REPORTED.** `guides/telephony/twilio-inbound-calls.md:55-58` states: "Inbound
Agent functionality using APIs currently requires connecting your **Twilio account**." The
same API's own schema documents two Plivo-only options and `byot-inbound-calls.md:30-47` uses
it for `sip-trunk` numbers. Either the Twilio note is stale or `/inbound/setup` is
provider-conditional in a way no page states. **Whether `/inbound/setup` accepts a Plivo,
Vobiz or Exotel number is not established by these pages and is not guessed here** — it is a
gate (§7). It matters more than it looks: Plivo is our 160-series carrier, and if inbound
linkage is Twilio-only by API then every Indian inbound number is a manual dashboard step
forever.

### Per-provider inbound mechanics (all differ; none is uniform)

- **Twilio** (`twilio-inbound-calls.md:35`) — paste the agent's inbound URL into the number's
  Webhook URL, "**Make sure the HTTP Method is POST**".
- **Plivo** (`plivo-inbound-calls.md:19-33`) — create an **XML Application** in the Plivo
  console, put the inbound URL in both `Primary Answer URL` and `Hangup URL`, then assign the
  number to that application (`:46`).
- **Exotel** (`setup-exotel-app-for-inbound-calls.md:58-62`) — build an App Bazaar app with a
  **Voicebot** component pointed at `https://api.bolna.ai/inbound_call`, `:64` enable "Record
  this", `:85` add a **Connect** app with Primary URL
  `https://api.bolna.ai/exotel_connect_transfer` for transfers, `:114` connect the Exophone to
  the app, `:124` then retrieve the generated **App ID**.
- **Vobiz** — **no inbound page exists.** See §5.

---

## 5. Vobiz inbound: the vendor now claims it and still publishes no procedure

`docs/TRD.md:213-215` says: "Vobiz (connect + outbound only — no inbound guide; the
inbound-DID plan must confirm Vobiz inbound at pilot or shift inbound DIDs to Exotel)".

**Half of that is still exactly right and half has moved.**

- Still right: `guides/telephony/` contains `vobiz-connect-provider.md` and
  `vobiz-outbound-calls.md` and **no** `vobiz-inbound-calls.md`. Verified by directory listing.
- Moved: `supported-telephony-providers.md:33` now asserts the capability in a table —
  "| [Vobiz](/docs/vobiz) | India | ✅ Yes | ✅ Yes | ✅ Yes |" (Inbound / Outbound / BYOA) — and
  `guides/telephony/vobiz.md:22-24` carries a card "Accept incoming calls using Vobiz" whose
  href is the *generic* `/docs/guides/inbound/receiving-incoming-calls`, not a Vobiz page.

So the status is no longer "unconfirmed" and is not "confirmed" either: **the vendor asserts
the capability in a matrix and publishes no provider-specific procedure for it**, while
publishing one for each of the other three. Proposed TRD sharpening in §7. The operational
consequence is unchanged — an inbound-DID plan that assumes Vobiz inbound still has no
runbook to follow.

---

## 6. SIP trunking / BYOT — read in full; recommendation is "not ours", with the cost of changing that

All 14 pages read. Nothing built. The question asked was whether BYOT is relevant to us at
all, and the honest answer is **not yet, and the reason is not effort**.

**What BYOT is.** `sip-trunking/introduction.md:11` — "Bring Your Own Telephony (BYOT) lets
you connect any standards-compliant SIP trunk to the Bolna platform. Instead of using Bolna's
built-in telephony providers (Twilio, Plivo, etc.), you can use your existing SIP trunk
provider, your own phone numbers, and your own calling rates." Auth is `userpass` or
`ip-based` (`:44-45`). Nine API endpoints, full CRUD on trunks plus add/list/remove numbers
(`api-reference/sip-trunks/overview.md:13-27`).

**Why it is not ours today, in one line:** a BYOT trunk is a *client's own carrier
relationship*, and our entire DLT posture is built on the opposite — `docs/FLOWS.md:427-429`,
"**One number set per client — mandatory** … DLT ties outbound numbers to one business
identity + its templates". A client-brought trunk carries numbers we did not provision,
whose 140/160 classification we cannot verify, whose DLT header and template registrations we
have not seen, and which our compliance gate would have to take on trust. That is a
compliance decision before it is an engineering one, and hard rule 5 forbids the shape where
it becomes a bypass.

**What it would take, concretely, if a client demands it.** This is written down so the
answer is not re-derived under deadline:

1. `phone_numbers.provider` gains `sip-trunk` as a value, and `series` becomes
   *unverifiable-by-us* for those rows — which needs a distinct `dlt_status` state, not a
   reuse of `pending`, because "we have not registered it" and "we cannot see the
   registration" are different facts.
2. Trunk credentials are secrets per tenant (`auth_password`, `create.md:120-122`) — that is
   the secrets-manager path, never a column.
3. Our agent body would have to send `telephony_provider: "sip-trunk"`
   (`byot-outbound-calls.md:24`), which is the same per-agent telephony field D-357 already
   owns; BYOT does not create that gap, it widens it.
4. The compliance gate needs a rule for "number whose series we cannot verify", and the
   default must be refuse.

**Facts worth keeping even though nothing is built:**

- **A second Bolna IP exists and it is NOT a webhook source.** `byot-setup.md:18` — Bolna's
  SIP media server IP is `13.200.45.61`. Our webhook allowlist is
  `{"13.203.39.153", "13.126.9.249", "13.202.133.53"}`
  (`packages/shared/src/calevate_shared/config.py:139`). **`13.200.45.61` must never be added
  to it** — it is an origin for SIP/RTP toward a carrier, not a source of HTTP callbacks to
  us. Recording it here because the two look interchangeable in a hurry and one of them
  widens a trust boundary.
- Origination URIs are `sip:sip.bolna.ai:5060` (UDP/TCP) and
  `sip:sip.bolna.ai:5061;transport=tls` (`byot-setup.md:29-32`).
- Codec: `byot-setup.md:47` — "Bolna's SIP layer uses **G.711 u-law (ulaw)** audio by default
  … G.729 and other compressed codecs are not recommended."
- Media encryption: `byot-setup.md:354` — `media_encryption` `"no"` | `"sdes"`, and `"sdes"`
  **requires** `transport="transport-tls"`; `:374` documents the 422 by name. Default is plain
  RTP. If BYOT ever becomes real for an Indian client, plain RTP on the media leg is a
  DPDP-relevant fact somebody must sign off, not a default to inherit.
- `byot-setup.md:332` — "Bolna stores the number exactly as provided. When matching inbound
  calls, the platform performs a flexible lookup that checks both the number with and without
  a `+` prefix." Our convention is E.164 with `+` throughout, which is compatible; the
  `e164_check_enabled` flag defaults to **`false`** (`add_number.md:84-87`), i.e. the vendor
  does **not** validate format unless asked.
- `byot-inbound-headers.md:29` — custom SIP header mapping "is only active when the agent's
  telephony provider is **SIP Trunk**. Twilio, Plivo, Exotel and Vobiz inbound calls ignore
  it". So nothing in this feature family can leak into our current providers.
- `delete.md:31-33` — deleting a trunk "Permanently delete[s] a SIP trunk and all associated
  resources (gateways, IP identifiers, phone numbers)". Destructive and cascading.

**No gap found** against our tree on any of the 14 pages, because we implement none of it and
claim none of it. `packages/shared/src/calevate_shared/engine.py` lists a `numbers`
capability and `apps/api/engine/bolna.py`'s `BOLNA_CAPABILITIES` sets `number_series=frozenset()` — the port
already has no vocabulary for a trunk, which is the correct state for a feature we have
decided not to have.

---

## 7. Founder / ops decisions and proposed text

### 7a. Truecaller verification — FOUNDER/OPS, and it has an outage mode we do not model

Zero hits in our tree before this audit (only `docs/vendor/bolna/GAP-WORKLIST.md:126` names
it as a gap). It is **not configuration and cannot be wired**: there is no API endpoint for it
anywhere in the mirror, it is a dashboard form plus a human review.

- `truecaller-verification.md:11` — "Truecaller verification allows your **business name and
  logo** to be displayed on recipients' phones when your Voice AI agents make outbound calls."
- `:65-89` — the form: **Company Name**, **Category**, **Sub-category**, **Reason for
  Calling**, **Brand Icon**; `:94-95` — "**File format**: PNG only. **Dimensions**: Exactly
  **200 × 200 pixels**".
- `:189` — "Verification typically takes **1-3 business days**."
- `:200` — rejection reason: "**Company name mismatch** — name not matching your registered
  business."
- `:179-183` — "Truecaller verification is billed as per usage… Automatically deducted from
  your Bolna wallet balance; Billed monthly from the date of verification activation".
  **The price is not stated anywhere in the mirror.**
- `:207` — "Each number is verified and billed separately."

**Why it is a per-client item and not a platform one.** The verified identity displayed is the
*client's* business name and logo, and rejection turns on it "matching your registered
business" — i.e. it consumes the same registered-entity documents our KYC gate already
collects (`apps/api/compliance/kyc.py`). One Calevate-wide verification would display
Calevate's name on a client's outbound calls, which is the opposite of what the feature is
for and is arguably a misrepresentation to the callee. So: **per client, per number, priced
per number, at a price the vendor does not publish.**

**The outage mode, which is the part that would bite.** `:46` — "When a number is in the
**Delisting Pending** state, calls cannot be made from that number." And `:161` — "once opted
for delisting pending outbound **and inbound** calls on this number will be blocked." And
`:170-174` — "During the delisting process, your phone number **cannot be used for calls**.
This includes both outbound calls and batch campaigns. Make sure to: Remove the number from
any active Voice AI agents; Pause any scheduled batch campaigns using this number".

Delisting takes 1-3 business days (`:215`). So a number can enter a multi-day state in which
**every dial fails and every inbound call is dropped**, triggered by a click in a dashboard we
do not own, with no webhook and no status field we could read. Our `phone_numbers.dlt_status`
enum (`pending`/`registered`/`blocked`) has no room for it, and our dispatcher would keep
handing that number to a campaign. **This is the one Truecaller fact that is not purely
commercial**, and the safe interim control is procedural, not code: nobody delists a number
that is attached to a live agent. Modelling it properly is not worth a column until a number
is actually verified — that needs the account and the price first.

**Founder decisions required, both blocked outside this repo:** (1) get Bolna to state the
Truecaller price per number per month; (2) decide whether it is absorbed, passed through at
cost, or a priced add-on — and if passed through, it is a `usage_events` unit like the rental
in §3a.

### 7b. Proposed OPERATIONS §2 gate rows (exact text — apply centrally)

```
| 21 H | **Can `/inbound/setup` link a NON-Twilio number, and what does the phone_number_id look like?** [NEW, telephony audit] | `api-reference/inbound/agent.md` documents `POST /inbound/setup` as `{agent_id, phone_number_id}` and documents two options as Plivo-only (`allow_multiple`, `ivr_config`), while `guides/telephony/twilio-inbound-calls.md:55-58` says "Inbound Agent functionality using APIs currently requires connecting your **Twilio account**." Those cannot both be current. **This decides whether inbound linkage can ever be automated for us**: Plivo is our 160-series carrier, and if the API is Twilio-only then every Indian inbound DID is a permanent manual dashboard step. Call `POST /inbound/setup` with an Indian Plivo number's id and record (a) whether it 200s, (b) the exact shape of `phone_number_id` — `get_all.md:65-68` types it `^[0-9a-fA-F]{32}$` (bare hex) while `agent.md:47-52` types the SAME field as a dashed uuid, and `byot-setup.md:318` returns a ULID-looking `01HQNUMBER111222333`. Whatever comes back is what `phone_numbers.engine_number_ref` must hold. |
| 22 H | **What does a phone number actually cost us per month, in what currency, and does Truecaller have a price?** [NEW, telephony audit] | `guides/inbound/buying-phone-numbers.md:121` says "$5/month … deducted automatically from your Bolna wallet balance each month on the renewal date", and `guides/inbound/truecaller-verification.md:179-183` says Truecaller is "billed as per usage … Billed monthly from the date of verification activation" **without ever naming a price**. Buy ONE Indian number and record: the wallet debit, its currency, the `renewal_at` value, and what `GET /phone-numbers/all` reports in `price` (a STRING, `example: $5.0`). Then ask Bolna, in writing, for the Truecaller per-number monthly charge. **Nothing writes `number_rental` today and that is correct only while we buy no numbers through Bolna** (`docs/evidence/deepdive-money.md:330`); this gate is what turns the writer on, and hard rule 7 applies to both charges. |
| 23 S | **Does a Truecaller "Delisting Pending" number appear as anything we can read?** [NEW, telephony audit] | `guides/inbound/truecaller-verification.md:161` — "once opted for delisting pending outbound and inbound calls on this number will be blocked" — for 1-3 business days (`:215`). No webhook, no documented field, and our `phone_numbers.dlt_status` has no such state. Check whether `GET /phone-numbers/all` exposes any verification status at all. If it does not, the control stays procedural (never delist a number attached to a live agent) and that belongs in a runbook, not a column. |
```

### 7c. Proposed ROADMAP §6 decision-log row (exact text — apply centrally)

```
| D-4xx | **`NUMBER_PROVIDER=plivo` — the carrier Bolna allocates every 160-series number through, and the one our own adapter hardcodes into every published agent — was refused to operators as an unsupported vendor** | `campaigns/provisioning.py::KNOWN_PROVIDERS` gains `"plivo"`, so the setting resolves to `no_provisioning_adapter:plivo` (the vendor is supported, the adapter is not written) instead of `provider_not_implemented:plivo` ("we do not support that vendor"). The two reason codes exist precisely to keep those apart and the wrong one sent an operator to change a setting that was already correct. `tests/telephony_provisioning_test.py` pins the tuple to the vendor's carrier table rather than to itself — a SUPERSET assertion, so adding a vendor is not an edit to a test with no opinion about it — and reads the result through the ONE selector rather than asserting the constant twice. `twilio` stays out (`supported-telephony-providers.md:34` lists its countries; India is not one). `exotel` stays in and is a different kind of entry: Bolna's purchase API cannot broker an Exotel number (`buy.md:67-73`, enum `twilio|plivo|vobiz`) but Exotel is a first-class bring-your-own-account integration (`supported-telephony-providers.md:32`), and this constant answers "which vendor may sell THIS DEPLOYMENT a number", not "which vendor Bolna will buy one from". No client-visible behaviour changes; `PROVISIONING_IMPLEMENTED` is untouched and every path still refuses. | Found auditing `bolna-findings/mirror/pages` in full. **The audit expected to find the opposite and did not**: `engine/bolna.py`'s `_agent_body` telephony comment claiming that Plivo is the 160-series carrier and Vobiz the 140-series carrier was treated as an unsourced premise going in, and `guides/inbound/obtaining-regulated-phone-numbers.md:13-16` states it as a table — so the comment was right, the constant beside it was wrong, and only the constant had no test. **Two facts the same page settles that our docs get wrong in one sentence each**: 140/160-series numbers have NO provisioning API at all (documents to compliance@bolna.ai, ₹5,900 DLT PE registration on the TATA portal, carrier allocation, then header and template approval), which contradicts `docs/FLOWS.md` §10's "All numbers are virtual DIDs provisioned via API"; and §10's ₹5,900 PE-registration figure is independently confirmed by the vendor at `obtaining-regulated-phone-numbers.md:60`. |
```

### 7d. Proposed `docs/FLOWS.md:423-425` correction (exact replacement — apply centrally)

Replace:

> **No physical SIMs.** All numbers are virtual DIDs provisioned via API (Exotel /
> Vobiz / Plivo, connected to the engine — Bolna guides verified for all three; Vobiz
> inbound unconfirmed, TRD §5), routed over SIP, stored in `phone_numbers`.

With:

> **No physical SIMs.** All numbers are virtual DIDs (Exotel / Vobiz / Plivo, connected to
> the engine — Bolna guides verified for all three; Vobiz inbound is asserted in their
> capability matrix with no provider-specific guide published, TRD §5), routed over SIP,
> stored in `phone_numbers`. **Only geographic DIDs are provisioned via API** — `POST
> /phone-numbers/buy`, $5/month, Plivo or Vobiz, region-selected. **The 140- and 160-series
> have no API**: DLT Principal-Entity registration (₹5,900, TATA portal), documents to the
> engine vendor, carrier allocation, then header and template approval before the number is
> active (`bolna-findings/mirror/pages/guides/inbound/obtaining-regulated-phone-numbers.md`).

### 7e. Proposed `docs/TRD.md:213-215` sharpening (exact replacement — apply centrally)

Replace `Vobiz (connect + outbound only — no inbound guide; the inbound-DID plan must confirm
Vobiz inbound at pilot or shift inbound DIDs to Exotel)` with:

> Vobiz (connect + outbound guides published; **inbound asserted in their capability matrix
> — `supported-telephony-providers.md:33` — with no provider-specific inbound guide, where
> Twilio, Plivo and Exotel each have one**; the inbound-DID plan must still confirm Vobiz
> inbound at pilot or shift inbound DIDs to Exotel)

### 7f. Proposed addition to `apps/api/engine/bolna.py`'s `_ASSUMED_MINOR_UNITS_PER_MAJOR` comment (exact text — apply centrally; comment-only, deliberately not applied during a concurrent edit of that file)

```
#: **A NEIGHBOURING RESOURCE SHOWS THE HOUSE CONVENTION, and it is the one assumed here.**
#: The phone-number schemas describe ONE price — $5/month — three times, and they reconcile
#: only under "cents = USD minor units, divisor 100":
#:     search.md:124-127  "Price of the number in USD."               example 5
#:     buy.md:113-117     "Price for the phone number in cents."      example 500
#:     get_all.md:103-106 "Monthly rental price of the phone number"  example $5.0
#: (`bolna-findings/mirror/pages/api-reference/phone-numbers/`). This is NOT proof about
#: `AgentExecution.total_cost` — different schema, different endpoint, and saying otherwise
#: would repeat the D-350 mistake this block exists to prevent. What it changes is the
#: standing of the assumption: "cents ⇒ USD ⇒ /100" is now the vendor's demonstrated
#: convention on a resource where they also print the dollar sign, rather than a precedence
#: rule applied to two documents that contradict each other. Gate 7 still scores both halves.
```

---

## 8. Page-by-page verdict — "no gap found" stated explicitly

| Page | Verdict |
|---|---|
| `supported-telephony-providers.md` | **Gap → fixed** (§2, Plivo). Twilio-not-India and Exotel-BYOA confirmed our exclusions. |
| `guides/telephony/integrations.md` | No gap. Telephony cards for all four providers; also carries `platform.bolna.ai/auth/azure` for the Azure OpenAI connect flow — handed to the LLM lane, not acted on here. |
| `guides/telephony/exotel.md` | No gap. |
| `guides/telephony/plivo.md` | No gap. |
| `guides/telephony/vobiz.md` | No gap in our tree; the "Accept incoming calls" card links to a generic page (§5). |
| `guides/telephony/twilio.md` | No gap — we do not use Twilio and correctly do not list it. |
| `guides/telephony/exotel-connect-provider.md` | No gap. Credential set recorded: `:29` — "`API_KEY`, `API_TOKEN`, `ACCOUNT_SID`, `DOMAIN` and `PHONE_NUMBER`". We hold no Exotel account, so nothing to reconcile. |
| `guides/telephony/plivo-connect-provider.md` | No gap. |
| `guides/telephony/vobiz-connect-provider.md` | No gap. |
| `guides/telephony/twilio-connect-provider.md` | No gap. Notes `:12` credentials are stored "via [infisical](https://infisical.com/)" — a vendor sub-processor fact for the compliance lane. |
| `guides/telephony/exotel-outbound-calls.md` | No gap. `:60-68` confirms `tools_config.input/output.provider` is the telephony selector. |
| `guides/telephony/plivo-outbound-calls.md` | No gap; source of the `/call` shape divergence in §3d. |
| `guides/telephony/vobiz-outbound-calls.md` | No gap. |
| `guides/telephony/twilio-outbound-calls.md` | No gap. |
| `guides/telephony/twilio-inbound-calls.md` | **Ambiguity reported** (§4) — the Twilio-account-required note vs the API's Plivo-only options. |
| `guides/telephony/plivo-inbound-calls.md` | No gap. Manual XML-Application procedure recorded (§4). |
| `guides/telephony/setup-exotel-app-for-inbound-calls.md` | No gap. Endpoints recorded: `api.bolna.ai/inbound_call`, `api.bolna.ai/exotel_connect_transfer`. |
| `guides/telephony/setup-exotel-app-for-outbound-calls.md` | No gap. Endpoint `api.bolna.ai/exotel_callback`. |
| `guides/telephony/on-prem-twilio.md` | No gap — enterprise Twilio-in-your-own-cloud via a `bolnahq/twilio-app` docker image. Not India-capable, so not ours. `:45` — "Bolna will never have access to the recordings" is a residency-relevant claim for a product we do not use. |
| `api-reference/phone-numbers/overview.md` | No gap. |
| `api-reference/phone-numbers/search.md` | **Fact captured**: `country enum [US, IN]`, provider enum lacks `exotel`, price in USD. |
| `api-reference/phone-numbers/buy.md` | **Two facts + one inconsistency** (§3a, §3b, §3c). |
| `api-reference/phone-numbers/get_all.md` | **Fact captured**: `renewal_at`, `price` as a `$`-prefixed string, `rented` boolean. Id typed `^[0-9a-fA-F]{32}$` — see gate 21. |
| `api-reference/phone-numbers/delete.md` | No gap. `:7` "to stop billing" — deletion is the only documented way to stop the $5. |
| `api-reference/inbound/overview.md` | No gap. |
| `api-reference/inbound/agent.md` | **Seam identified, not wired** (§4). Filed as `agent.md`, path is `/inbound/setup`. |
| `api-reference/inbound/unlink.md` | No gap. Note `:37-47` requires only `phone_number_id`, while `byot-inbound-calls.md:66-72` sends `agent_id` too — harmless, reported. |
| `sip-trunking/introduction.md` | No gap — BYOT not ours (§6). |
| `sip-trunking/byot-setup.md` | No gap. IP `13.200.45.61` recorded with an explicit warning not to conflate it with the webhook allowlist. |
| `sip-trunking/byot-inbound-calls.md` | No gap. "One number, one agent" recorded. |
| `sip-trunking/byot-outbound-calls.md` | No gap; source of the second `/call` shape (§3d). |
| `sip-trunking/byot-inbound-headers.md` | No gap. `:29` confirms the feature cannot affect Twilio/Plivo/Exotel/Vobiz inbound. |
| `api-reference/sip-trunks/{overview,create,get,get_all,update,delete,add_number,list_numbers,remove_number}.md` (9) | No gap on any — we implement none of it and claim none of it. Field reference read in full; nothing in it contradicts anything we assert. |
| `guides/inbound/buying-phone-numbers.md` | **Money finding** (§3a) + the geographic-vs-regulated split (§1a). |
| `guides/inbound/truecaller-verification.md` | **Founder/ops item with an unmodelled outage state** (§7a). |

---

## 9. What I deliberately left alone, and why

- **`apps/api/engine/bolna.py::BolnaEngine._agent_body`'s hardcoded
  `"input"/"output": {"provider": "plivo", "format": "wav"}`.** The comment already names this as a gap and assigns it: "`AgentConfig`
  carries no telephony provider … which is a column, a UI control and a DLT-series decision,
  i.e. D-357, not a literal edited here." The vendor evidence *strengthens* that comment
  rather than changing it (§1), and a 140-series agent needing `vobiz` here is precisely
  D-357. Inventing the column mid-audit would be a second way to solve a problem that already
  has an owner.
- **`BOLNA_CAPABILITIES.number_series = frozenset()` in `apps/api/engine/bolna.py`.** Its stated reason —
  "Numbers come from the telephony vendor directly" — is now half-inaccurate, since Bolna does
  broker geographic DIDs. But the **value stays correct**: the series it would have to
  advertise are 140 and 160, and those have no API (§1a). It is arguably widenable to
  `{"standard"}`, and that is exactly the change the surrounding comment warns against —
  "the way this line gets reached is somebody widening the descriptor without writing the
  client". A decision-log entry, not a flag flip, and `packages/shared/.../engine.py` is
  another lane's file this run.
- **`phone_numbers.engine_number_ref`.** Already filed as P4.4 in
  `docs/PRODUCTION-READINESS.md:876-891` with a named fix. I added the vendor content it will
  hold (§4) and changed no code.
- **`NumberPurchaseIn.series` / `.city` (`provisioning_routes.py:64-65`).** The route's
  docstring argues the request shape is published early so "the shape a client codes against
  does not change on the day provisioning starts working". The evidence says it *will* have to
  change — Bolna's India flow takes a **region** from a fixed list (Karnataka 80 / Maharashtra
  22 / Gujarat 79 / NCR 11), not a free-text city, and takes no `series` at all
  (`buying-phone-numbers.md:73-111`). I did not change it, because the 140/160 path it is
  really for is the *manual* one, where a city may well be the right question; deciding that
  needs the account (gate 22), not an edit today. Recorded here so the day it is edited, the
  reason is on file.
- **`docs/FLOWS.md`, `docs/TRD.md`, `docs/ROADMAP.md`, `docs/OPERATIONS.md`, `CLAUDE.md`.**
  Exact proposed text in §7; not applied. FLOWS.md is being edited concurrently in this run.
- **Anything SIP.** Read in full, built nothing (§6), as instructed.

---

## 10. Verification record

- `uv run pytest tests/telephony_provisioning_test.py -q` → **4 passed**. Sabotage → **2
  failed, 2 passed** with a message naming the exact defect; restore → **4 passed**. Both
  outputs pasted in §2.
- `uv run pytest tests/kyc_gate_test.py -q -k "unimplemented or provider"` → **1 passed** —
  the one test in that file that exercises the constant I touched.
- `uv run ruff check --fix` + `uv run ruff format` on all three changed files → clean.
- `uv run mypy apps packages` → **Success: no issues found in 237 source files**.
- The full suite and `make coverage-ratchet` were **not** run, per instruction (ten agents on
  four vCPU).
- **Shared-store note, not a defect of this change:** running `tests/kyc_gate_test.py` in full
  produces 18 failures, all rooted in
  `psycopg.errors.CheckViolation: new row for relation "retention_policies" violates check
  constraint "ck_retention_policies_category_enum"`. That table is untouched by this change
  and `git status` shows nine other files modified by concurrent agents. This is CLAUDE.md's
  "dirty or stale store" case — a seed/schema mismatch on the shared database — and is
  reported rather than "fixed".
