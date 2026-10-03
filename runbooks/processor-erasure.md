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
| `telephony` | Vobiz (Plivo if a deployment was switched to it) | The caller's and the called number, its call detail records, and the call audio, which streams through it in both directions. Its API reference documents reading and exporting call records and recordings and **no delete route** (`vobiz-findings/mirror/pages/cdr/*.md`, `recording.md:65-73`); its console shows recordings for the last 30 days. | The carrier's own call ids (`calls.carrier_call_id`, the `CallUUID`). |
| `voice_engine` | A third-party engine a deployment ran calls on (`ENGINE=cartesia`). Never opened for Pipecat calls: our own runtime's record is in our database and the erasure already reached it. | The vendor's execution record of each call. | The vendor's execution ids; for a tenant task, its agent ids and knowledge-base handles. |
| `speech`, `llm` | Sarvam; Azure OpenAI / OpenAI / Google | Audio and transcript (speech), conversation turns (language). Opened on TENANT erasures only — a per-subject task could never be closed, since neither keys its records on an id we hold. | None. The request is "delete what you hold for this customer of ours". |

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
