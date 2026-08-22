# `processor_erasure_overdue` — a copy we deleted everywhere we can reach, and one place we cannot

**You were paged because an erasure worked and is still not finished.**

Our Postgres rows are gone. Our object-storage bytes are gone. The certificate was issued.
And the voice platform that carried the calls still holds its own copy of the recording and
the transcript, in the US, because it publishes no way for us to delete one person's calls.

This runbook is the manual half of that obligation. It is short on purpose: the work is
one email and one command, and the reason it needs a runbook at all is that an obligation
discharged by a human with no record is one that gets believed rather than done.

---

## 1. What is actually true right now (read this before you write to anyone)

`docs/evidence/subprocessor-erasure-reach.md` is the full evidence file. The three
sentences you need:

* Every `DELETE` route the vendor documents was enumerated across all 335 mirrored pages.
  **Ten routes. Nine delete configuration objects.** The Executions surface is four GETs
  and the Calling surface is one POST — nothing deletes an execution, a recording or a
  transcript.
* The tenth, `DELETE /v2/agent/{agent_id}`, deletes an agent *and* "ALL agent data
  including all batches, all executions". That is the right instrument for a **tenant**
  erasure and the wrong one for a **subject** erasure, where it would destroy every other
  caller's records and take the client's live receptionist off the air.
* The vendor states **no retention period** for those copies — their own documentation says
  "contact support for retention policy". So the copy does not age out on any clock we know.

**Do not tell a data principal the vendor's copies are gone until the task says
`confirmed`.** That is the whole reason this record exists.

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
> the following execution ids, including call recording audio, transcripts and any derived
> or extracted fields, and confirm in writing with the date of completion.
> `<ids from the list command>`

For a **tenant** task the refs are agent ids, and the request is different — ask them to
delete the agents, which their own documentation says removes all batches and executions
with them. That one they can actually do today.

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
