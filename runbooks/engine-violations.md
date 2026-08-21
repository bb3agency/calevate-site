# Runbook — the voice platform has flagged our account: `engine_violation_open`

Symptom: a page reading `[calevate/<env>/workers] engine_violation_open`, with a count of
open compliance flags, how many tenants they touch, the age of the oldest and up to five
violation ids.

**This is not an outage and you cannot fix it with a deploy.** Bolna has recorded one or
more VIOLATIONS against the account through which every client's regulated Indian calling
runs, and nothing has been submitted against them. The remedy is a person reading the
flagged call and submitting evidence. Nothing in this repository can do that, deliberately
— `apps/api/engine/violations.py` argues why an automated submitter would be worse than
none.

Ground rules: audited admin path for any production SQL (SECURITY-COMPLIANCE.md
§"Admin access path"); read-only. **Nothing you copy out of the vendor console into a
ticket may carry a phone number or transcript text** (hard rule 6) — and note that the
vendor's evidence file paths END IN THE RECIPIENT'S PHONE NUMBER, which is why our own
records carry a boolean and never the URL.

---

## 0. What we know, and what the vendor has never told us

Read this before you act, because three things you will want are not documented anywhere
and guessing at them is how this becomes a real problem.

| Question | The answer we have |
|---|---|
| What raises a violation? | Their MCP tool list calls them "content policy, regulatory, or fraud" flags. **No trigger is documented** — complaint, carrier report, automated scan and manual review are all consistent with the pages. |
| Is there a deadline? | **None is published.** `POST /violations/submit` "updates the violation status and attaches the uploaded file" and no page names a window. The alarm reports the AGE of the oldest flag precisely because we cannot compare it to anything. |
| What happens if we ignore one? | **Unstated.** The nearest published enforcement is their FAQ's "Agent is restricted due to disallowed content", which is at least proof the vendor does restrict accounts over compliance findings. Assume calling can be suspended until told otherwise. |
| What do `accepted` and `rejected` mean? | **Unknown, and do not guess.** The words could describe the flag being upheld or our evidence being accepted — opposite meanings. Only `pending` is unambiguous, and it is the only status the sweep interprets. |

All four are open questions for the vendor (OPERATIONS §2 gate 9v), and the evidence
behind every line is in `docs/evidence/bolna-compliance-residency.md` §1.

---

## 1. Find out whose calls were flagged

The alert names up to five ids. The full list, with attribution:

```
uv run python -c "
import asyncio
from apps.api.engine import get_engine
async def main():
    listing = await get_engine().list_violations(status='pending')
    for v in listing.violations:
        print(v.violation_id, v.status, v.engine_agent_ref, v.engine_call_id, v.raised_at)
asyncio.run(main())
"
```

`engine_agent_ref` is the vendor's agent id and OUR key into `engine_agent_routes`, which
names the tenant:

```sql
SELECT tenant_id, agent_id, active
FROM engine_agent_routes
WHERE engine_agent_ref = '<engine_agent_ref>';
```

No row means the agent was deleted at the vendor or predates the route — the alert counts
that as unattributed. The flag is still ours; find the call by `engine_call_id`
(`calls.engine_call_id`, which is the vendor's `execution_id`).

**A flag against a withdrawn route is not a false alarm.** It names a call we really
placed for a client we have since offboarded, and the account it was placed on is still
ours.

---

## 2. Decide what actually happened, then submit

1. Pull the call. `engine_call_id` → the call row → the transcript (`text_redacted` by
   default; raw text needs `calls:read_raw` and writes an `audit_log` row — SEC-COMP §4).
   Read what the agent actually said.
2. Check the two disclosures. Every agent has both sentences on file and the truthful
   answer directive is appended to every prompt server-side (hard rule 5). If the flag
   alleges an undisclosed AI or an unrecorded recording, the drift sweep
   (`engine_agent_drift_detected`) and `agents/verification.py` are where you prove what
   was published.
3. Check the compliance gate. If it is an outbound campaign, `launch_blockers` recorded
   what was true at launch — PE registration, TM link, DLT template, number series,
   consent, calling window.
4. **Submit from the vendor console**, quoting the `violation_id`. Attach what you found
   in step 1–3. Our side has no submit path and must not grow one.
5. Tell the client if their call is the subject. A flag against their agent is a fact
   about their business, and clause 6 of the DPA is not the only reason to say so.

If the agent really did something it should not have, the fix is upstream of this runbook:
the prompt, the extraction schema or the campaign classification. Say which in the ticket.

---

## 3. The two sweep alarms

`engine_violation_sweep_incomplete` (WORKER_DELIVERY) — the walk could not promise it saw
every flag: our page cap stopped it, `has_more` stuck, or the flag was missing from the
response. **The open count is a floor.** Re-read the list in the vendor console before
telling anyone the account is clean.

`engine_violation_sweep_abandoned` (WORKER_TERMINAL) — the hourly sweep failed all three
attempts. Same two causes as `engine_drift_sweep_abandoned`: credentials or vendor
availability. Until it succeeds, nothing is watching this channel; the next successful
tick catches up in full, because the job is a read with no cursor.

Silence from all three is only meaningful if the sweep is actually running. It logs
`engine_violation_sweep` on every tick with the counts, and reports itself skipped by name
(`no_violations_surface`, `no_credentials`) rather than passing quietly when it cannot ask.
