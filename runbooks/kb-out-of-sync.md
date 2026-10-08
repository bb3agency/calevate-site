# Runbook — publishing knowledge is refused: `kb_engine_out_of_sync`

Symptom: an operator presses Publish on an approved knowledge source
(`POST /v1/admin/tenants/{tenant_id}/kb/{source_id}/publish`, admin realm,
`agents:write`) and gets one of two business-rule refusals instead of a new live version.
The client is usually looking at it, because the thing they wanted published is a price
list.

**Both refusals mean the same disease and have different cures, and the wrong cure leaves
the agent quoting the old prices.** Read the whole runbook before acting on either.

Why the refusal exists at all. The engine calls in `publish_source`
(`apps/api/kb/service.py`) are NOT in the database transaction, and they cannot be. So a
COMMIT that fails after a successful attach discards every row while the engine keeps the
document. What that leaves behind is a client whose agent answers from a version our
tables say is not live, a superseded version our tables say IS live under a handle the
engine already deleted, and a document nobody can address again — billed for as long as
the account exists. Nothing in our code can prevent that. These two checks detect it on
the next attempt and stop, instead of attaching a second copy on top.

**The publish ordering is the reason the stakes are what they are, and it REVERSED in
D-488 — read this before diagnosing anything below.** The new copy is now ATTACHED first
and every superseded copy is withdrawn after, because a real attach is an upload plus an
indexing wait the vendor gives no bound for, and detaching first would leave the agent
answering T4 "I don't know" for the whole of it on every republish. "Every superseded
copy" includes this source's own previously attached one, because `attach_kb` is a CREATE
that mints a fresh handle every time and de-duplicates nothing.

**What that means for you at 3am:** the window is now an OVERLAP, not a gap. For the
length of one detach round trip — or permanently, if the process died in between — the
agent can retrieve from BOTH versions. So the symptom of a half-finished publish is an
agent giving inconsistent answers, not an agent giving none, and the first question is
which of the leftovers is the version the client approved.

**A re-publish of unchanged content uploads nothing**, keyed on a SHA-256 of the rendered
document stored beside the handle. So "just press Publish again" is safe in a way it was
not before: it will not mint a second copy of text that is already attached.

Ground rules: audited admin path for any production SQL (SECURITY-COMPLIANCE.md
§"Admin access path"); read-only. Nothing on this path touches a phone number or a
transcript — knowledge sources are the client's own business text — but the same rule
applies to anything you copy out of a KB document into a ticket.

---

## Which refusal do you have?

| code | Title | What we know |
|---|---|---|
| `kb_engine_out_of_sync` | "The voice platform holds knowledge we cannot account for" | The engine is serving one of the client's agents **at least one document no row of ours mentions** |

`kb_engine_ref_unknown` ("The live version cannot be withdrawn") is no longer raised (D-689).
Knowledge belongs to the client and is one copy per agent, so a live version with no claim on
one agent is a copy that agent has not been given yet — the catch-up gives it one — and a
copy the engine holds without a claim is case B below.

It is logged with ids only — at ERROR with `agent_id` and a COUNT of unaccounted handles
(never the handles themselves). It leaves everything unchanged: nothing was detached,
nothing was attached on any agent, the previously approved version is still live and every
agent still answers.

Since D-689 a publish attaches the new copy to EVERY published agent of the client before it
withdraws any old copy, and the check runs per agent: the refusal names the first agent
whose vendor copy list we cannot account for, and the whole publish refuses.

---

## B. `kb_engine_out_of_sync` — the engine holds something we cannot account for

### 1. Understand what was compared

`_reconcile_engine_state` asks the engine for every handle attached to this agent and
subtracts the set we believe in — every non-null `engine_kb_ref` across **all** of that
agent's sources, not just this named one (`_recorded_handles_of_agent`). An agent's KB is
several named sources, and "can we account for everything the engine is holding" is a
question no single name can answer.

The refusal counts the leftovers. It does not name them, in the log or the response.

**Evidence, not a dependency.** A listing we could not obtain proves nothing either way,
so a failed `list_kb` is logged as `kb_reconcile_unavailable` (with the exception TYPE
only) and **stepped over** — the publish proceeds. Refusing on "we did not manage to
look" would turn one flaky vendor read into an outage of the approval workflow. So the
absence of this refusal is not proof of sync; only its presence is proof of divergence.

### 2. Enumerate both sides

Ours:

```sql
-- Every handle we believe this agent has attached, and which source it belongs to.
SELECT s.id AS source_id, s.name, s.version, s.is_active,
       d.meta ->> 'engine_kb_ref' AS engine_kb_ref
FROM kb_documents d
JOIN kb_sources s ON s.id = d.source_id
WHERE s.agent_id = :agent_id
  AND d.idx = 0
  AND d.meta ->> 'engine_kb_ref' IS NOT NULL;
```

Theirs: the engine's listing for `agents.engine_agent_ref`, with the same two caveats as
case A step 2.

The unaccounted handles are the set difference. Each one is a document the agent can
retrieve from, that we cannot address, and that is billed for as long as the account
exists.

### 3. Decide what each leftover is — before deleting any of it

There are only three plausible origins, and telling them apart decides the order of
operations:

> **⚠ THE PUBLISH ORDER REVERSED (D-488) AND TWO OF THESE THREE ORIGINS CHANGED WITH
> IT.** Publishing now ATTACHES the new version before it withdraws the superseded ones,
> because a real attach is an upload plus an indexing wait and detaching first would leave
> the agent with no knowledge for the whole of it. The consequence for this runbook: a
> crashed publish now leaves BOTH versions attached rather than only the new one, and
> there is no longer a re-attach path to produce a re-minted copy of the previous text.

- **A crashed publish, before the withdrawal.** The attach succeeded and the process died
  (or the COMMIT failed) before the superseded copy came down. The agent is holding BOTH
  versions and can answer from either — this is the origin to look for FIRST, because it
  is the only one where the client is being given stale answers right now. The leftover is
  the NEW version's document, unrecorded; the OLD one is still recorded and still live.
- **A crashed publish, after the withdrawal.** The old copy is gone, the new one is up,
  and the COMMIT failed. The leftover is the NEW version's document — the one the client
  approved — with our tables still naming the handle that was deleted.
- **A rolled-back attach that could not be undone.** When a detach fails, `_undo_attach`
  removes the copy the publish just added so the agent is left exactly as it was. If that
  removal ALSO failed it is logged as `kb_left_attached`, and the leftover is the NEW
  version's document beside a previous version that is still correct and still recorded.
- **Someone attached something by hand** — in a vendor's console where the engine is a
  vendor's, or straight into the engine-side store where the runtime is ours.

Read the leftover document's content and match it against `kb_documents.content` for the
candidate versions, exactly as in case A step 2. **The direction of the fix is not the
same in all three**, which is why guessing here is the one step that can leave the agent
quoting old prices:

| Origin | What the leftover is | Right move |
|---|---|---|
| Crashed publish, before the withdrawal | BOTH versions live; the NEW one unaddressable | **Most urgent — the agent is quoting two prices.** Delete the unaddressable copy on the engine, then re-run Publish: our tables still name the OLD handle, so the re-publish withdraws it properly and attaches a fresh, recorded copy |
| Crashed publish, after the withdrawal | The approved NEW text, live on the engine, unaddressable | Delete it on the engine, then re-run Publish. The re-publish attaches a fresh, recorded copy of the same approved text — and `_detach_superseded` now treats our stale handle as already withdrawn rather than refusing, so the retry works |
| Rolled-back attach (`kb_left_attached`) | The NEW text, beside a PREVIOUS version that is still correct and still recorded | Delete the NEW copy on the engine. Do NOT re-run Publish until the reason the detach failed is understood — it will fail the same way |
| Hand-attached | Unknown provenance, unapproved | Delete it. Nothing unapproved may reach a client's agent (FLOWS §7) — that is the whole point of the approval gate |

In all three the leftover is deleted and Publish is re-run. What differs is what the
client's agent is saying **right now**, and therefore how urgent it is: in the first case
the agent is already correct and you are only repairing the bookkeeping; in the second it
is stale, and the client should be told before the fix, not after.

### 4. Repair, in this order

1. Delete each unaccounted handle on the engine, one at a time, re-listing between
   deletions so you can see the set shrink to exactly what our query in step 2 returned.
2. **Do not touch `kb_documents.meta` by hand.** `_remember_engine_kb_ref` is the only
   writer, and a handle typed in from a vendor console is a handle nobody verified — it
   turns a detected divergence into an undetected one.
3. Re-run `POST /v1/admin/tenants/{tenant_id}/kb/{source_id}/publish`. It re-runs the
   whole ordering: reconcile, detach everything addressable, attach, record the handle,
   archive the previous version, activate this one, recompile T0.
4. Confirm the publish took: `PublishOut` returns `{"source_id", "version", "status":
   "live"}` and the audit row `kb.published` names who did it. Then confirm the state:

   ```sql
   SELECT id, version, status, is_active, published_at
   FROM kb_sources WHERE agent_id = :agent_id AND name = :name
   ORDER BY published_at DESC NULLS LAST;
   ```

   Exactly one `is_active = true` with `status = 'approved'`; the rest `archived`.

### 5. What the re-publish also does, and what it does not

`publish_source` ends by recompiling T0 (`recompile_t0`) from `active_knowledge`, which
mints a **new prompt version** carrying the newly live facts. It never edits the live
prompt, and it re-publishes the agent to the engine **only if the agent is already live**
— a client publishing an FAQ must not promote a draft agent past its human sign-off
(FLOWS §1 step 7). If the block is unchanged it returns None and the rollback onto a
version already live stays free.

So a successful re-publish changes two things at the engine: what the agent can RETRIEVE,
and what its prompt SAYS. If the client reports the agent still quoting old prices after
a green publish, check the prompt version too, not only the KB.

---

## Related refusals you may hit on the same button

| code | Meaning |
|---|---|
| `kb_not_approved` | `approved_at IS NULL`, or `status` is not `approved`/`archived`. `archived` is allowed on purpose: FLOWS §7 rollback is republishing a version this same function archived |
| `kb_fan_out_incomplete` (alarm, not a refusal) | The new version reached some agents and others would not withdraw the old one (D-689). The publish succeeded; the catch-up converges the rest. See `runbooks/alarm-index.md` |
| `kb_detach_failed` | The engine did not confirm removal of the version being replaced. **Nothing changed — the previously approved version is still live.** Retrying costs nothing, because we have not attached anything yet. If it repeats, you are probably really in case A or B |
| `engine_bad_response` | The engine returned no usable knowledge base id from an attach. A response we cannot read a handle out of is a failure, not a success — treating it as one would attach text nobody can retract |

## What NOT to do

- **Never publish "anyway" past either refusal.** Both exist because the alternative is
  two live copies and an agent free to answer from the older one, with our tables
  reporting success.
- **Never write `engine_kb_ref` into `kb_documents.meta` by hand** to make a refusal go
  away. That is not a repair, it is a way of making the next divergence invisible.
- **Never delete a vendor-side document you have not matched against our content.** The
  one you cannot address may be the one the client is being answered from.
- **Never flip `kb_sources.is_active` or `status` with SQL.** `publish_source` is the only
  thing that sets `is_active`, and the activation restores `status` as well — a live
  version left marked `archived` is a row that contradicts itself on every screen that
  reads it.
- **Never conclude "in sync" from a clean `list_kb`.** The reconciliation can prove a
  divergence; it can never prove the absence of one, and it steps over its own failures
  on purpose.
