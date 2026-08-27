# Erasure reach, per sub-processor: what a DPDP §12 request can actually destroy

**Written 22 Aug 2026 (W5, D-433).** The question this document answers is narrower and
harder than "do we delete the data": *when a data principal exercises DPDP §12 and our
worker reports success, whose copies did that success actually reach?*

Every row carries an evidence class, and the classes are not decoration:

| Class | Means |
| --- | --- |
| **VERIFIED-VENDOR-DOCS** | Read in `bolna-findings/mirror/`, cited page:line, and the page's SHA-256 matches `MANIFEST.json`. |
| **VERIFIED-IN-REPO** | Read in this tree, cited file:line. |
| **REPORTED** | Believed on recall or third-hand summary. The vendor's own host was ATTEMPTED from here and refused. Never sufficient to narrow a certificate. |
| **UNKNOWN** | Nobody here has established it. Recorded as a hole rather than filled with a guess. |

**Egress, measured 22 Aug 2026, not assumed.** `www.bolna.ai`, `docs.sarvam.ai` and
`learn.microsoft.com` were each fetched from this container and each returned
`curl: (56) CONNECT tunnel failed, response 403`; the proxy's own status endpoint records
`"kind": "connect_rejected", "detail": "gateway answered 403 to CONNECT"`. So the only
vendor documentation readable here is the Bolna mirror. ⚠ **The SARVAM row was upgraded on
27 Aug 2026 without that changing** — the founder holds the account and read the Terms of
Service (v2.0, eff. 29 Jul 2026) and Privacy Policy at `www.sarvam.ai` and relayed them, so
that row is now VENDOR-PUBLISHED with a named reader and a date. The host is still refused
from this container; the evidence arrived by another route, and nothing here re-fetches it.
The Azure row is unchanged. Sarvam's and Azure's rows below were
therefore REPORTED or UNKNOWN, and that is a finding rather than an apology: **two
sub-processors that hold call content have no established retention or deletion policy in
this tree at all, and the erasure certificate does not currently mention either of them.**

**Mirror integrity, checked rather than trusted.** Every Bolna page cited below was hashed
and compared to `bolna-findings/mirror/MANIFEST.json`:

```
OK   api-reference/calls/overview.md               e1a845663e6c967c
OK   api-reference/executions/overview.md          f428d0773d100981
OK   concepts/security.md                          019f41cfd0effe23
OK   enterprise/data-residency.md                  496e92ac68c6c4e0
OK   enterprise/indian-server-configuration.md     39f5671e94ec4eb5
```

---

## 1. The enumeration: every `DELETE` Bolna documents, and what each one deletes

The starting suspicion was *"Bolna publishes no API that deletes a recording, a transcript
or an execution."* It was worth checking exhaustively rather than accepting, because the
answer turns out to be **half wrong, and the half that is wrong is the useful half.**

Enumerated by grepping the whole mirror for method+path declarations across all 335 pages,
then reading each `DELETE` page. The complete documented `DELETE` surface:

| Route | Deletes | Reaches call content? | Evidence |
| --- | --- | --- | --- |
| `DELETE /v2/agent/{agent_id}` | **the agent AND "all batches, all executions"** | **YES — see §2** | VERIFIED-VENDOR-DOCS `api-reference/agent/v2/delete.md:7,10` |
| `DELETE /providers/{provider_key_name}` | one stored BYOK credential | no | VERIFIED-VENDOR-DOCS `api-reference/providers/remove.md:13` |
| `DELETE /phone-numbers/{phone_number_id}` | a number registration | no | VERIFIED-VENDOR-DOCS `api-reference/phone-numbers/delete.md:13` |
| `DELETE /sip-trunks/trunks/{trunk_id}` | a SIP trunk | no | VERIFIED-VENDOR-DOCS `api-reference/sip-trunks/delete.md:13` |
| `DELETE /sip-trunks/trunks/{id}/numbers/{id}` | a number's trunk binding | no | VERIFIED-VENDOR-DOCS `api-reference/sip-trunks/remove_number.md:13` |
| `DELETE /dispositions/{disposition_id}` | a call-outcome label definition | no | VERIFIED-VENDOR-DOCS `api-reference/dispositions/delete.md:21` |
| `DELETE /knowledgebase/{rag_id}` | an uploaded knowledge base | client content, not caller content | VERIFIED-VENDOR-DOCS `api-reference/knowledgebase/delete.md:13` |
| `DELETE /batches/{batch_id}` | a batch — *"Delete a batch"*, scope of cascade **not stated** | UNKNOWN | VERIFIED-VENDOR-DOCS `api-reference/batches/delete.md:7,31` |
| `DELETE /sub-accounts/{sub_account_id}` | a sub-account | UNKNOWN (cascade unstated) | VERIFIED-VENDOR-DOCS `api-reference/sub-accounts/delete.md:16` |
| `DELETE /ambient-sounds/{sound_id}` | an uploaded background audio track | no | VERIFIED-VENDOR-DOCS `changelog/march-2026.md:17` |

**And the two surfaces that hold caller data publish no delete at all.** This is the part
of the original suspicion that stands, and it is worth stating as an enumeration rather
than an absence, so the next reader does not go looking again:

`api-reference/executions/overview.md:11-16` — the complete Executions surface:

```
GET /executions/:execution_id
GET /batch/:batch_id/executions
GET /v2/agent/:agent_id/executions
GET /executions/:execution_id/log
```

`api-reference/calls/overview.md:11-13` — the complete Calling surface:

```
POST /call
```

Four GETs and one POST. **There is no `DELETE /executions/{id}`, no route that deletes a
recording, and no route that deletes a transcript.** VERIFIED-VENDOR-DOCS.

---

## 2. The finding that changes the answer: agent-granular deletion exists

`api-reference/agent/v2/delete.md:7` (the page's own summary line):

> Use Bolna APIs to delete agents **and their related data**, ensuring proper cleanup of
> batches, **executions**, and configurations.

and its warning block, `:9-11`:

> This deletes **ALL** agent data including all batches, **all executions**, etc.

So the vendor *does* document a route that destroys executions. It is already implemented
in this tree — `apps/api/engine/bolna.py:2291-2352`, `delete_agent`, which even records
what it destroys ("*Their reference states this removes all of the agent's data including
its batches and executions*"). The consequence splits cleanly in two, and the split is the
whole point of this document:

**Per-subject erasure (DPDP §12): the route is unusable, and the gap is real.**
A §12 request names ONE data principal. `DELETE /v2/agent` is granular to an *agent*, so
using it to erase one caller would destroy every other caller's executions on that agent
and take the client's live receptionist off the air. There is no subject-granular
instrument. **For a per-subject erasure the original finding holds in full: Bolna's copy of
that caller's recording and transcript survives our worker, and no API we can call removes
it.** The only mechanism is a contractual/support request — and even that is REPORTED, in
the weak sense that `concepts/security.md:19` says *"contact support for retention policy"*
and nothing documents that support will act on a deletion request at all.

**Tenant erasure / offboarding: the route IS usable, and we do not call it.**
When a whole tenant is erased, every one of that tenant's agents is being abandoned
anyway. `DELETE /v2/agent` for each of them is exactly the right instrument and would
genuinely destroy the vendor-side executions. `apps/workers/retention.py:1763-1767`
considered it and rejected it:

> REJECTED: calling `VoiceEngine.delete_agent` from here. It exists and is idempotent by
> contract, but it is a third-party round trip inside the one transaction that must not
> half-commit... The vendor-side deletion stays `unconfirmed_pending_vendor_api`, which is
> what the certificate has always claimed and all it has ever been able to.

**The first sentence is right and the last one does not follow from it.** "We must not do
a vendor round trip inside this transaction" is an argument for doing it in a follow-on
job — the transactional outbox this repo already uses for exactly this (BACKEND-PATTERNS
§4) — not an argument that the deletion is impossible. Reporting it as
`unconfirmed_pending_vendor_api` states that the vendor API is unknown, when for this path
it is known, documented, implemented and idempotent. That is an over-claim of ignorance,
which is a real defect: it makes a reachable obligation look unreachable, so nobody
reaches it.

---

## 3. The per-sub-processor erasure-reach table

| Sub-processor | What it holds | Where | Retention | Deletion mechanism | Class |
| --- | --- | --- | --- | --- | --- |
| **Bolna** (voice engine) | call recording audio, full transcript, extracted fields — all on the "execution record" | **US** by default (`concepts/security.md:29`), and our BYOK architecture **forces** US: *"If you connect your own API keys for any provider... calls will automatically route through US servers regardless of other configuration settings"* (`enterprise/indian-server-configuration.md:67-69`) | **UNSTATED.** The vendor's own retention column reads *"Available in execution record; contact support for retention policy"* (`concepts/security.md:19`). We cannot say how long, and neither can they, in writing. | **per subject: NONE.** per agent/tenant: `DELETE /v2/agent` (§2). Whether it removes the recording OBJECTS as well as the execution rows is **UNSTATED**. | VERIFIED-VENDOR-DOCS, except the recording-object cascade (UNKNOWN) |
| **Sarvam** (Saaras STT · Bulbul TTS) | raw call audio in, recognised text out; and the first post-call extraction sends it the **raw, un-redacted transcript** (`apps/workers/extraction.py`, `GEMINI_EXTRACTION_DEFAULT is False`) | ⚠ **CORRECTED 27 Aug 2026 (D-476): NOT "India".** The vendor is an Indian COMPANY; its published privacy policy says personal data *"may be transferred to and processed in countries outside India"*, naming US cloud infrastructure (AWS/GCP/Azure) and EU model and security vendors, under SCCs / adequacy / DPAs. The India-storage carve-out covers voice biometric data in Content Studio and payment data, not Saaras/Bulbul API traffic. This cell read *"India (sovereign by vendor) — the residency claim is fine here"*, and it was not fine. **Erasure is still not residency.** | ⚠ **NO LONGER UNKNOWN, but published rather than negotiated.** Content (Inputs/Outputs): **30 days after last access** by default, described as *user-configurable* — nobody has located where that setting is changed, so do not record it as configured. Account & Profile: account + **90 days** unless earlier written deletion request. Voice Samples & Models: consent withdrawal + **30 days**. Security Incident Logs: **7 years**. | **Published, not an API.** *"We will delete data within 30 days of request verification"*, except where retention is required by law, where data is needed for ongoing legal proceedings, or where technical limitations prevent deletion (*"we will anonymize instead"*). No deletion ENDPOINT is known, called or recorded, and no subject-granular commitment exists — OPERATIONS §2 gate 40 is where the contractual version is negotiated, alongside gate 36. | VENDOR-PUBLISHED (Sarvam Privacy Policy and ToS v2.0 eff. 29 Jul 2026, read by the founder at `www.sarvam.ai` 27 Aug 2026 and relayed. ⚠ `sarvam.ai`/`docs.sarvam.ai` remain egress-blocked from this container — this was not fetched here) |
| **Azure OpenAI** (in-call LLM + dashboard AI) | prompts and completions — on the in-call leg that is **caller conversation**, turn by turn | resource pinned to South India (gates 20/20c); **the abuse-monitoring store's region is a separate question nobody here has asked** | **REPORTED:** Azure OpenAI retains prompts/completions up to **30 days** for abuse monitoring, reviewable by Microsoft staff, unless the subscription is approved for *modified abuse monitoring / limited access*. `learn.microsoft.com` is egress-blocked from here, so this is recall, not a reading. | **REPORTED: none customer-callable.** The documented remedy is the abuse-monitoring exemption application, i.e. **not deleting the copy but never making it** — which is the stronger control and is a form to file, not code to write. | REPORTED |
| **Our object storage** (R2/S3-compatible) | recording audio, archived raw engine payloads, delivered CRM webhook bodies | ours | per-tenant `retention_policies`, floored at 90 days for recordings | **full.** `_erase_recordings`, `_erase_engine_payloads` delete the bytes | VERIFIED-IN-REPO `apps/workers/retention.py` |
| **Our Postgres** | everything else | ours | per-tenant policies + the append-only ledgers hard rule 4 protects | **full**, minus the disclosed append-only exceptions already in the register | VERIFIED-IN-REPO |

---

## 4. The reverse direction: retention expiry never asks a vendor for anything

Checked, and the answer is uniform. `apps/workers/retention.py::apply_retention` sweeps
recordings, transcripts, leads, consent logs, `kb` and `engine_payload`. Every one of those
sweeps operates on **our** Postgres and **our** object storage. **No retention category
issues any vendor-side call, and there is no code path in this repository that asks any
sub-processor to delete anything on a retention clock.** VERIFIED-IN-REPO.

So a tenant whose recording policy is 90 days has our copy destroyed on day 90 and, on the
vendor's side, a copy with **no stated expiry at all** (`concepts/security.md:19`). The
90-day floor in `docs/` is a floor on *our* retention; it is not a ceiling anywhere.

**The recording-deletion path specifically, in both directions:**

* **Can the vendor's retention undercut our 90-day floor?** Possibly, and we would not
  know. The floor is a TRAI obligation we satisfy from our own copy, so a vendor who
  silently deleted at 30 days would not breach it *for us* — our copy is the record. This
  direction is therefore tolerable-but-unmonitored.
* **Can it outlast it?** Yes, and this is the direction that hurts. With retention
  "unstated", the vendor's copy can outlive both our floor and our tenant's policy
  indefinitely, which is a DPDP §8(7) storage-limitation exposure on data we are the Data
  Fiduciary for. **This is the direction the contract clause in §6 must close.**

---

## 5. What the certificate said before this change, and why it was an over-claim

`ERASURE_LIMITATIONS`/`ERASURE_EXCEPTIONS` in `apps/api/compliance/deletion.py` is a good
register — it is candid about backups, consent ledgers, the recording floor and the
knowledge base. It had two defects on this axis:

1. **A stale evidence claim.** It said the engine's *"deletion API is undocumented"*. After
   §1, that is false as framed: the documentation is complete, mirrored and hash-verified,
   and it documents **no subject-granular deletion** while documenting an agent-granular
   one. "Undocumented" invites the next reader to go looking; "enumerated and absent" tells
   them the question is closed and sends them to the contract instead.
2. **Two sub-processors missing entirely.** The register named the engine and stopped.
   Sarvam receives the raw transcript and Azure OpenAI receives the caller's conversation
   turn by turn, and a certificate that lists what it could not reach while omitting two
   processors that hold call content is exactly the "control that reports success for work
   it did not do" failure this repo exists to prevent.

---

## 6. The contract item — NOT closeable in code, and it must not be made to look like it is

The durable fix is a term in a signed Data Processing Agreement with **Bolna**, and
equivalents with **Sarvam** and **Microsoft**. This is blocked outside this repository on
*a signed commercial term with the vendor* — not on engineering time, not on a sprint. No
code in this tree can create it and none should pretend to.

`docs/LEGAL-SURFACE.md:137` (DP-11) already records the standing of this: *"MET as text,
UNMET as practice ... we owe the same to our sub-processors, and no vendor contract has
been signed."* The clause below is what that signature has to contain.

### The clause, written to be pasted into a contract

> **Deletion on Instruction.** Upon written instruction from the Controller identifying
> one or more Data Subjects, Executions, Agents or Accounts, the Processor shall
> permanently delete all Personal Data relating to the identified subject — including
> call recording audio, full and partial transcripts, extracted or derived structured
> fields, and any log or analytics record containing conversation content — from all
> production systems within **thirty (30) days**, and from all backup and archival media
> within a further **sixty (60) days**, and shall confirm each such deletion in writing
> with the date of completion and the identifiers deleted.
>
> **Subject-Granular Capability.** The Processor shall provide a means of deleting the
> Personal Data of an individual Data Subject that does not require deletion of the Agent
> or of other Data Subjects' records. Where no such means exists at the Effective Date,
> the Processor shall perform such deletions on written request within the period above.
>
> **Stated Retention.** The Processor shall state in writing the maximum period for which
> it retains call recordings, transcripts and derived data absent an instruction to
> delete, and shall not extend that period without ninety (90) days' notice.
>
> **Deletion on Termination.** Within thirty (30) days of termination the Processor shall
> delete all Personal Data and certify deletion in writing, save where retention is
> required by applicable law, in which case it shall state the law and the period.
>
> **Sub-processor Flow-Down.** The Processor shall impose these obligations on each of its
> own sub-processors and remain liable for their performance.

Three notes for whoever negotiates it, each of which is a thing this investigation found:

* **"Subject-Granular Capability" is the operative clause**, not the headline one. Without
  it we can only ever offer a data principal a deletion that also destroys the client's
  live agent, which is not an offer anyone can accept.
* **"Stated Retention" is worth as much as the deletion clause.** Today the answer is
  *"contact support for retention policy"* (`concepts/security.md:19`) — an unbounded
  retention we are the Data Fiduciary for. Negotiate the number, not just the process.
* **Ask where the recording bucket is while the DPA is open** (OPERATIONS §2 gate 9's item
  (iv)). Post-1-June-2026 the URL is an opaque `api.bolna.ai/recordings/call/{id}`
  pre-signed link, so the location is no longer observable by inspection and has to be a
  written answer.

**The Azure clause is different in kind and should not be drafted as a deletion term.**
The abuse-monitoring copy is best removed by not creating it: the remedy is Microsoft's
*modified abuse monitoring / limited access* approval for the subscription, which is a form
to file against the Azure subscription. That is an external blocker of the same class — it
needs an Azure subscription and Microsoft's approval, not code.
