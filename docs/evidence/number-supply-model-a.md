# Model A on the inbound leg: what was built, what stays shut, and the two clauses that must move

**Decision D-537, 4 September 2026.** The founder, after being shown the playbook's
warning, decided that **Calevate buys Indian DIDs through the voice engine**. The clinic
keeps its own published number and conditionally forwards it to ours; the client-facing
story is *"point your existing phone at this number."* The DID is never published.

This document is the evidence trail for that build. It records what is VERIFIED, what is
UNKNOWN and blocked outside this repository, and the exact wording changes two published
legal documents need — drafted here and **not published**, because published legal text is
the founder's to approve.

---

## 1. What is now built, and what refuses

| Layer | Before | Now |
|---|---|---|
| Port | no search method at all; `NumberSpec` could not name a number | `search_numbers`, `provision_number`, `release_number`, `list_engine_numbers`; `NumberSpec.e164` + `country`; `NumberSearch`, `AvailableNumber` |
| `BOLNA_CAPABILITIES.number_series` | `frozenset()` | `frozenset({"standard"})` — one member, measured |
| Adapter | `provision_number` raised unconditionally | four real methods against `/phone-numbers/{search,buy,all,{id}}` |
| `phone_numbers.engine_number_ref` | **no writer in production code** | written on purchase, and by `POST /v1/admin/numbers/tenants/{t}/{n}/engine-ref` |
| Recurring cost | `number_rental` in the unit enum, **no writer** | `billing/number_rental.py` + a monthly cron, idempotent per number per IST month |
| Going live | (nothing to gate) | `Settings.number_resale_authorization` — unset, so everything refuses |

**The one thing that is not built, deliberately:** a client cannot buy a number.
`POST /v1/numbers/purchase` still refuses, because §19 names *self-serve* as the unsafe
shape specifically. What the founder adopted is an operator-led supply.

## 2. Vendor facts, and where each was read

Every line below is VERIFIED-VENDOR-DOCS from the hash-pinned mirror at
`bolna-findings/mirror/`, read 4 Sep 2026. The vendor's doc host `www.bolna.ai` remains
egress-blocked from this container; nothing here was fetched live.

| Fact | Source |
|---|---|
| Four routes: `all`, `search`, `buy`, `DELETE {id}` | `api-reference/phone-numbers/overview.md:11-16` |
| Buy requires `country` (`US\|IN`) **and** `phone_number` (exact E.164) | `buy.md:54-77` |
| Buy `price` is **"in cents"** | `buy.md:113-117` |
| Buy carries `renewal` (bool) and **no recurring price** | `buy.md:78-135` |
| Buy returns `bolna_owned` | `buy.md:88-91` |
| Search `price` is **"in USD"** | `search.md:126-133` |
| Search `pattern` is a "3-character prefix" | `search.md:56-61` |
| Listing `price` is the **string** `"$5.0"`, "Monthly rental price" | `get_all.md:103-106` |
| Listing `rented` = "bought from Bolna" | `get_all.md:115-118` |
| Listing declares no parameters, answers a bare array | `get_all.md:29-51` |

### Three contradictions in the vendor's own pages, each handled and none papered over

1. **One price, three units** (USD / cents / `"$5.0"`). Each is read at the page that
   states it. Nothing is converted in an adapter; the rupee is struck once, monthly, in
   `billing/number_rental.py`. They reconcile only under "cents = USD minor units,
   divisor 100" — a reading, and gate 26 settles it against one real wallet debit.
2. **`vobiz` is in the buy REQUEST enum and not the RESPONSE enum** (`buy.md:67-73` vs
   `:118-124`), and the listing declares a third set. **No provider enum is validated
   anywhere.** Refusing an unexpected value would reject a purchase the vendor had already
   charged for — the one failure that costs money and cannot be retried. Gate 25c.
3. **Search parameters are declared `in: path` on a route with no path template**
   (`search.md:38-70`). Not expressible; sent as query, marked as a reading. Gate 25b.

And the id shape stays contradictory across three pages (dashed uuid / bare hex / a
ULID-looking value), which is exactly why `engine_number_ref` is stored verbatim and
validated nowhere. Gate 25.

## 3. THE TWO PUBLISHED DOCUMENTS THAT MUST MOVE — drafted, NOT published

Both changes are **required before an authorisation reference is recorded**, not after:
recording one while the Terms say the opposite would put the product and its contract in
direct contradiction. Neither draft narrates the entity's legal form.

### 3.1 Terms, clause 3 ("What we do not supply")

The clause today says, in full:

> "We do not supply the telephone number or the telephone connection either, and we do not
> resell either one. You take the connection with an Indian operator in your own name and
> on your own account, you remain the subscriber of record for it, and we operate on that
> account using credentials you issue to us and can withdraw."

The first sentence is no longer true of the inbound leg. **Minimum true replacement:**

> "We are not a telecommunications licensee and we do not provide the telecommunications
> service itself. For calls you make, you take the connection with an Indian operator in
> your own name and on your own account, you remain the subscriber of record for it, and we
> operate on that account using credentials you issue to us and can withdraw. For calls you
> receive, we may instead supply a number that answers on our platform: you keep your own
> published number and forward it to ours, we remain responsible for that number with the
> operator it comes from, and it is released when you leave. We do not sell or rent numbers
> as a service in their own right, and we do not supply a number for making calls."

Three properties that draft is chosen for: it distinguishes the two legs rather than
withdrawing the Model B promise, it does not claim the client is the subscriber of record
on a number they are not, and it says what happens on exit — which clause 11 already
promises for numbers generally.

### 3.2 Acceptable Use, §2.1 (registrations)

§2.1 today grounds the identity checks in "the terms of the connection you hold in your own
name". Under Model A on the inbound leg, an inbound-only client may hold no such
connection. **Minimum true addition**, as a new paragraph after the Telecommunications Act
paragraph:

> "Where we supply the number your calls arrive on, the connection behind it is held with
> an operator by us rather than by you. That changes who the operator's identity checks
> attach to, and it does not change anything in this section about making calls: every
> outbound registration below is still yours, and a number we supply is for receiving calls
> only."

**Both drafts need the founder's approval and, on 3.1, the advocate's** — gate 47 names
them as blockers on the same line as the reseller status.

## 4. What could not be verified, in the words hard rule 11 requires

* **UNKNOWN — `www.dot.gov.in` is egress-blocked from this container** (403 on CONNECT,
  measured 4 Sep 2026). DoT's revised OSP guidelines PDF could not be read. Web search
  surfaced only consultants' summaries of UL(VNO) licensing and the 2020 OSP repeal —
  **REPORTED, not primary**, and not usable for a compliance conclusion. The three
  questions this leaves open are written verbatim into gate 47.
* **UNKNOWN — no Bolna account is reachable from this container**, so not one call in the
  purchase path has run against the vendor. Gates 25, 25b, 25c, 25d and 26.
* **UNKNOWN — the forwarded-leg calling number.** If an Indian carrier presents the
  clinic's own number rather than the patient's on a forwarded leg, every inbound lead
  takes the clinic's number as the patient's. That is the audit's finding and it is a
  property of the client's carrier, not of this code. It costs one real forwarded test
  call and it is not yet a gate — it belongs to whoever runs the first clinic.
* **NOT ASSERTED — the monthly rental figure.** Nothing in this repository states what an
  Indian DID costs. The price that reaches the ledger is the one the vendor's own search
  returned and an operator accepted, echoed back on the purchase.
