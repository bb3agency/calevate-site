# `processor_erasure_overdue` — a copy we deleted everywhere we can reach, and one place we cannot

**You were paged because an erasure worked and is still not finished.**

Our Postgres rows are gone. Our object-storage bytes are gone. The certificate was issued.
And a vendor that handled the calls still holds its own copy, because it publishes no way
for us to delete one person's records.

This runbook is the manual half of that obligation. It is short on purpose: the work is
one email and one command, and the reason it needs a runbook at all is that an obligation
discharged by a human with no record is one that gets believed rather than done.

---

## 1. What is actually true right now (read this before you write to anyone)

Each task names a processor by ROLE. What each role holds, and what to ask for:

| Processor | Vendor | Holds | The ids quoted |
| --- | --- | --- | --- |
| `telephony` | The carrier our own call runtime used, removed by D-763 (named in its decision row, ROADMAP §6) | The caller's and the called number, its call detail records and the call audio, for calls placed on that runtime. Opened only for erased calls that carry a carrier call id, which ThinnestAI calls never do. | The carrier's own call ids (`calls.carrier_call_id`, the `CallUUID`). |
| `voice_engine` | The hosted voice platform that ran the call (ThinnestAI) | Its copy of the person's calls, conversations and recordings. Code asks for every deletion and closes the task itself (D-798, §6): each call's content is deleted (`DELETE /calls/{id}/content`) in whichever workspace holds it, and where the tenant has its own workspace the person's contact is erased there too (`DELETE /contacts/{id}`, D-691). The task is `confirmed` once ThinnestAI has confirmed every call and, for a contact, sent `contact.erased`. In our developer workspace the contact is shared with other businesses and is not erased; the task says `contact-not-asked`. A contact shown as `<id>=held` is waiting, by design, for our own copy of a connected call's recording inside the 90-day floor (D-810): the nightly retention sweep asks again and the contact is erased once the copy lands, the floor passes or the call ends unconnected (a booked dial the platform confirms it cancelled before ringing is closed as never connected at once, D-811). Such a task, and one whose call content deletion waits on the same rule (D-803), does not page `processor_erasure_overdue` until its floor date has passed (D-811; `list --all` shows the date); do not erase the contact by hand while it is held, because that deletes the only copy of a recording the floor keeps. | The vendor's call ids and the contact it deleted; for a tenant task, its agent ids and knowledge-base handles. |
| `speech`, `llm` | Sarvam; Azure OpenAI / OpenAI / Google | Call audio sent to our own runtime before D-763 and the transcripts the post-call extraction pass reads (speech); conversation turns and prompts (language). Opened on TENANT erasures only — a per-subject task could never be closed, since neither keys its records on an id we hold. | None. The request is "delete what you hold for this customer of ours". |

`docs/evidence/subprocessor-erasure-reach.md` is the evidence file for the speech and language
rows; it was written when the engine was Bolna (deleted by D-639), so its engine sections are
history.

**Do not tell a data principal a vendor's copy is gone until its task says `confirmed`.** That is the whole reason this record exists.

---

## 2. Triage — the two halves have different owners

The alert splits the count. Read it before doing anything:

| Half | Means | Who fixes it |
| --- | --- | --- |
| `unasked` | The erasure opened a task and **nobody sent the request**. | Us, today. Start here. |
| `unanswered` | We sent it; the vendor has not replied in 30 days. | Chase the vendor. |

---

## 3. Do the work

```
uv run python -m scripts.processor_erasure list
```

Prints every open task: the task id, which processor, how many days it has been open, and
**the vendor identifiers to quote**. Those ids are the point — a request that says "please
delete this person's calls" is unactionable at a support desk, and one that lists execution
ids is actionable.

**Send the request.** Nothing here mails anything, deliberately: a tool that can write to a
vendor on behalf of a compliance obligation is a blast radius rather than a control, and
the wording is yours. A minimal sufficient message:

> Under our data processing arrangement, please permanently delete all data associated with
> the following call ids, including call recording audio, call detail records, transcripts and
> any derived or extracted fields, and confirm in writing with the date of completion.
> `<ids from the list command>`

For a **tenant** task the request is "everything you hold for this customer of ours": quote
the ids the task carries (a carrier's call ids, a third-party engine's agent ids and
knowledge-base handles), or, for `speech`/`llm`, the account and the date range.

**Record that you sent it:**

```
uv run python -m scripts.processor_erasure sent <task-id> --reference "<their ticket id>"
```

`--reference` is optional. A vendor who answers an email with an email gives no ticket id,
and inventing one is worse than the gap.

**Record what they said:**

```
uv run python -m scripts.processor_erasure answered <task-id> --outcome confirmed --note "..."
uv run python -m scripts.processor_erasure answered <task-id> --outcome refused  --note "..."
```

---

## 4. If the answer is `refused`

**This is not a failure for you to fix, and it is the most valuable thing anyone will learn
on this axis.** A vendor who says they cannot delete one caller's executions has confirmed
that the gap is structural, not procedural.

Two things follow, both outside this repository:

1. **Put it in front of whoever is negotiating the contract.** OPERATIONS §2 **gate 36** is
   the DPA deletion clause, and `docs/evidence/subprocessor-erasure-reach.md` §6 carries the
   exact wording it must contain. A refusal is the evidence that makes that clause a
   blocker rather than a nicety.
2. **Tell the client honestly.** The certificate's limitations register already says a copy
   exists and that removing it is a written request; a refusal means that request has been
   answered "no", and the client is entitled to know that before they answer their data
   principal.

---

## 5. What this runbook deliberately does not do

* **It does not escalate.** Four states, one direction, no ladder. If a task sits refused,
  the answer is a contract, not a workflow.
* **It does not let you close a task you did not act on.** `sent` only moves an `open`
  task and `answered` only moves a `requested` one, so re-running a command cannot reset a
  clock or launder a task somebody already answered.
* **It does not touch the certificate.** A certificate is a statement of what was true when
  it was issued and nothing back-fills it (hard rule 4). The task is the living record; the
  certificate stays as issued.

---

## 6. ThinnestAI: call content and call retention (D-798)

ThinnestAI deletes one call's recording, transcript, summary and collected fields on request
and keeps only the billing record (`thinnest-findings/mirror/snapshots/2026-10-15/pages/
api-reference/post-call/delete-call-content.md:443-589`). Three things ask for it, each
through the outbox job `delete_engine_call_content`:

* the nightly retention sweep, for calls past the shorter of the tenant's recording and
  transcript periods;
* a DPDP erasure, for the subject's calls;
* a tenant erasure, for every call the platform still holds for that client.

Each call records `engine_content_delete_requested_at`, `engine_content_deleted_at` and
`engine_content_recordings_pending`. A call still live or booked (409) is asked again in 30
minutes; anything not settled a day later is queued again by the retention sweep.

**A `voice_engine` task stuck in `requested`.** Ask, for the tenant:

```sql
SELECT engine_call_id, engine_content_delete_requested_at, engine_content_deleted_at,
       engine_content_recordings_pending
FROM calls WHERE split_part(engine_call_id, '@', 1) = ANY(<the task's vendor_refs>);
```

* `deleted_at` empty: the deletion has not succeeded. Read `engine_call_content_delete_failed`
  and the `engine_error` log lines for that tenant.
* `recordings_pending` above 0: ThinnestAI retries those files nightly; the backstop asks
  again each day and the task closes when it reaches 0.
* every call settled and the task's reference shows a contact above 0: ThinnestAI has not
  sent `contact.erased` for it. It can take three nights for a recording still being written.
  Past that, ask their support, then record the answer by hand (§3).

**Call retention.** Every workspace's `callRetentionDays` is the shorter of the tenant's
recording and transcript periods, capped at the plan's `planRetentionDays` (30 on
pay-as-you-go; `workspace/update-workspace.md:528-599`), never left unset, because unset keeps
transcripts with no end. Our developer workspace gets the new-tenant defaults. It is set when
a client's workspace is provisioned (`sync_engine_retention`) and read back hourly
(`sweep_engine_retention`). On `engine_workspace_retention_drift`, read the tenant's
`tenant_engine_workspaces.retention_error_code`: `engine_rejected` with a 403 is a key that is
not a full key; with a 400, a number above the plan's window (the plan changed; the next run
reads the new window); `engine_bad_response` means the platform answered with
another number, which is a question for their support.
