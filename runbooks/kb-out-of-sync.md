# Runbook — publishing knowledge is refused: `kb_engine_out_of_sync` / `kb_engine_ref_unknown`

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

**The publish ordering is the reason the stakes are what they are.** Every copy the
engine holds is DETACHED before the new one is attached — including this source's own
previously attached copy, because `attach_kb` is a CREATE that mints a fresh handle on
every call and de-duplicates nothing. Attach-first would leave a window, or a permanent
state, in which the agent can answer from either version. One request of "I don't know"
(T4 refuse-and-escalate) during the gap is the cheaper failure; a stale price is a quote
the client is then held to.

Ground rules: audited admin path for any production SQL (SECURITY-COMPLIANCE.md
§"Admin access path"); read-only. Nothing on this path touches a phone number or a
transcript — knowledge sources are the client's own business text — but the same rule
applies to anything you copy out of a KB document into a ticket.

---

## Which refusal do you have?

| code | Title | What we know |
|---|---|---|
| `kb_engine_ref_unknown` | "The live version cannot be withdrawn" | There is a live version of this named source in OUR tables and we have **no handle for it**. We cannot remove what we cannot address |
| `kb_engine_out_of_sync` | "The voice platform holds knowledge we cannot account for" | The engine is serving this agent **at least one document no row of ours mentions** |

`_require_addressable` runs first, deliberately: when both are true, the missing-handle
diagnosis is the more specific one and is the one an operator should be handed. That
ordering is asserted — with a case where both conditions really do hold at once, and with
the two remediations checked for not having converged — by
`tests/kb_flow_promises_test.py::test_when_both_diagnoses_hold_the_operator_is_handed_the_specific_one`.
If you are reading this because the code sent you the OTHER refusal, that test is where to
look first: the swap is a one-line edit and it is exactly the failure this section warns
about.

Both are logged with ids only — `kb_engine_ref_unknown` at WARNING with `source_id`,
`kb_engine_out_of_sync` at ERROR with `agent_id` and a COUNT of unaccounted handles
(never the handles themselves).

Both leave everything unchanged. Nothing was detached, nothing was attached, the
previously approved version is still live and the client's agent still answers. That is
the one reassuring sentence in this runbook and it is true in both cases.

---

## A. `kb_engine_ref_unknown` — we cannot address the live version

### 1. Find the version and confirm the handle really is missing

The handle lives in `kb_documents.meta ->> 'engine_kb_ref'` on the **`idx = 0` row** of a
source, and nowhere else (`_remember_engine_kb_ref`).

```sql
-- Tenant-scoped session. The named source's live version(s) and their handles.
SELECT s.id, s.name, s.version, s.status, s.is_active, s.published_at,
       d.meta ->> 'engine_kb_ref' AS engine_kb_ref
FROM kb_sources s
LEFT JOIN kb_documents d ON d.source_id = s.id AND d.idx = 0
WHERE s.agent_id = :agent_id
  AND s.name = (SELECT name FROM kb_sources WHERE id = :source_id)
ORDER BY s.published_at DESC NULLS LAST;
```

The row you are looking for is `is_active = true`, `id <> :source_id`, and
`engine_kb_ref IS NULL`. Normally there is exactly one live version per (agent, name);
the code treats it as a list because "exactly one" is an invariant it enforces, not one
it may assume while enforcing it.

`engine_kb_ref IS NULL` means two different things depending on whose row it is, and this
is the distinction to keep straight:

- on a **different** version that is still live — the engine is serving something we
  cannot name. That is this refusal;
- on the version being **published** — we have attached nothing yet. That is every first
  publish and proceeds silently.

Only versions published before the handle was recorded can reach this state.

### 2. Withdraw the stale copy on the engine side — by hand, once

There is no code path for this, and deliberately so: a code path would have to guess
which of the engine's documents is the stale one, and guessing wrong deletes a live
knowledge base.

1. **List what the engine holds for this agent.** You need the agent's engine handle
   first:

   ```sql
   SELECT id, name, status, engine_agent_ref FROM agents WHERE id = :agent_id;
   ```

   Then read the engine's own listing for that agent — **IF THE ENGINE HAS ONE. ON BOLNA
   IT DOES NOT, AND THIS STEP IS NOT AVAILABLE (D-354).**

   This runbook used to send you to `GET /knowledgebase/all` filtered to rows whose
   `agent_id` equals the agent's `engine_agent_ref`. **That procedure could never have
   worked and would have told you the engine holds nothing, for every agent, always.** A
   Bolna knowledge base object carries no agent field of any kind: an agent references a
   knowledge base through its OWN config (`llm_agent.llm_config.vector_store.
   provider_config.vector_ids`, keyed by `vector_id` — a different identifier from the
   `rag_id` the listing returns). The filter therefore matched nothing, and "no rows" reads
   identically to "this agent has no documents". That is the worst possible answer for
   THIS runbook, whose entire job is deciding whether the engine and our records disagree.

   `BOLNA_CAPABILITIES.knowledge_base` is now `False` and `list_kb` REFUSES by name rather
   than returning `[]`, precisely so this step fails loudly instead of lying to you.

   **What to do instead, on Bolna:** identify from the vendor console, matching on the
   document title — historically `attach_kb` sent `name = source.title`, which is
   `kb_sources.name`. In-call retrieval is OURS regardless (the D-28 managed vector service
   behind the RAG tool endpoint), so a Bolna-side knowledge base is not what a caller is
   actually retrieving from — check `kb_sources` and the vector service first.

   **On an engine that DOES list:** our single account holds every tenant's agents, so the
   adapter attributes strictly — a row that does not name the agent is not counted.

2. **Match, and be sure.** The stale copy is the one whose title is this source's `name`
   and whose content is the version our tables show as live. Read the document on the
   vendor side and compare it against what we hold before deleting anything:

   ```sql
   SELECT idx, left(content, 200) FROM kb_documents
   WHERE source_id = :live_source_id ORDER BY idx;
   ```

   If more than one candidate matches, **do not delete any of them.** You are now in case
   B as well, and B's step 3 is the right order of operations.

3. **Delete it on the engine** (`DELETE /knowledgebase/{rag_id}`). Whether that also
   clears the AGENT's reference to it, or leaves the agent config carrying a dangling
   `rag_id`, is the second half of pilot gate 8b and is **not verified**. Re-list
   afterwards and confirm the agent no longer holds it. If the agent still references a
   deleted id, the detach needs a second call (an agent update) and that is a finding for
   the scorecard, not something to improvise around.

4. **Re-run Publish.** Our tables were never touched, so there is nothing to repair on
   our side; with the engine no longer holding an unaddressable copy,
   `_require_addressable` finds only `NULL` on the source being published, which is the
   silent case.

### 3. If the copy cannot be found or cannot be deleted

Do not publish. The client's agent is currently answering from an approved version — the
state is stale but it is *coherent and human-approved*. Publishing over it produces two
live copies and an agent free to answer from either, which is the exact divergence the
approval gate exists to prevent.

Tell the client the update is held, why, and that their agent is still answering from the
version they approved. That is a better sentence than the one that follows a wrong price.

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

- **A crashed publish.** The attach succeeded and the COMMIT did not. Our tables kept
  pointing at the OLD handle (which the detach had already deleted) and never learned the
  new one. The leftover is the NEW version's document — the one the client approved.
- **A failed publish that re-attached.** `_reattach_after_failed_publish` puts the
  previous version's text back when the attach fails, deliberately without recording the
  new handle (the transaction is about to roll back, so any write here would roll back
  too). The leftover is the PREVIOUS version's document, re-minted under a handle nobody
  recorded. This is the intended residue and the docstring says so.
- **Someone attached something by hand** in the vendor console.

Read the leftover document's content and match it against `kb_documents.content` for the
candidate versions, exactly as in case A step 2. **The direction of the fix is not the
same in all three**, which is why guessing here is the one step that can leave the agent
quoting old prices:

| Origin | What the leftover is | Right move |
|---|---|---|
| Crashed publish | The approved NEW text, live on the engine, unaddressable | Delete it on the engine, then re-run Publish. The re-publish attaches a fresh, recorded copy of the same approved text — one short "I don't know" window, then correct |
| Failed publish, re-attached | The PREVIOUS approved text | Delete it, then re-run Publish. Same outcome |
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
| `agent_not_published` | The agent has no `engine_agent_ref`. Publish the agent before adding knowledge |
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
