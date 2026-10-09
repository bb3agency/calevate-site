# Runbook — a client's voice workspace (ThinnestAI customer workspace, D-693)

**For:** an operator who got `engine_workspace_plan_limit`,
`engine_workspace_provisioning_failed`, `engine_workspace_offboarding_failed`,
`engine_business_details_submit_failed`, `engine_business_details_lapsed`,
`engine_agent_retire_failed` or a purchase alarm, or a client who says its account "is being
set up" and cannot publish or buy a number. Applies to `ENGINE=thinnest` only; on any other
engine every route below answers that it does not apply.

Vendor paths are under `thinnest-findings/mirror/snapshots/2026-10-08/pages/`. Design:
`docs/THINNEST-INTEGRATION.md` §3a-§3b.

## What a client's workspace is

Every Calevate client has its own ThinnestAI **customer workspace**: a workspace we create
for it under our account (`POST /customers`), reached with our one API key plus the header
`Thinnest-Workspace: org_…` (`api-reference/customers.md:18-91`). The client's agents,
calls, recordings, numbers, contacts and do-not-call list live there, and its numbers are
rented in its own business name. Everything it uses is billed to OUR ThinnestAI balance
(`:185-189`).

Our own **developer workspace** holds our account and plan, the BYOK keys every client
workspace inherits, the platform voice catalogue and the admin's clones, and anything made
before D-693 that has not moved yet (agents not republished since; test numbers "held in the
platform account").

**Never point a client at the developer workspace.** Not as a workaround for a plan limit,
not to get a number out quickly, not by recording a client's agent or number there by hand.
A client's do-not-call push or contact erasure sent there would act on every legacy client
at once, and a number rented there is in Calevate's name. The code refuses it
(`engine/thinnest_workspace.workspace_headers`, `tenancy/engine_workspace.is_own_workspace`);
do not do it in the ThinnestAI console either.

## States

`tenant_engine_workspaces.status`, shown on the client's admin page:

| State | Means | What the client can do |
|---|---|---|
| (no row) / `not_provisioned` | Provisioning not queued yet: a tenant made before D-693, waiting for the daily backfill | Nothing on the voice platform; its screens say the account is being set up |
| `pending` | Queued; the job finds or creates the workspace | Same |
| `active` | The workspace exists and is the client's own | Publish agents; once business details are approved, buy numbers |
| `plan_limit` | Our ThinnestAI plan's customer limit is reached (402) | Same as `pending` |
| `failed` | Provisioning failed for another reason; the error code is on the page | Same as `pending` |
| `offboarding` | The account was closed; numbers being released, agents and customer deleted | Nothing (account closed) |
| `deleted` | Offboarding finished; the vendor erases the customer 30 days later | Nothing; restoring the account re-provisions |

Provisioning is the outbox job `provision_engine_workspace` (`apps/workers/engine_workspaces.py`),
queued when the tenant is created. It looks for a customer carrying our reference
`calevate-<tenant uuid>` (the customer's `externalId`) before creating one, so pressing
**Retry provisioning** never makes a second workspace; a deleted customer the vendor still holds is
restored rather than replaced. The daily `retry_engine_workspaces` queues every live tenant
with no row and every `pending`, `failed` or `plan_limit` one, at most 50 a day.

## Reading the pages

**Admin console → the client → Numbers → voice workspace panel** (`GET
/v1/admin/engine-workspaces/tenants/{id}`, `admin:tenants`): status, the `org_…` id, the last
error code and attempts, when it was provisioned, the business-details application (status,
review note, when sent and last checked), the purchase step the client is on and what blocks
it, the client's monthly number price, its numbers, and how many of its live agents are still
in the platform account (they move on their next publish). Buttons: **Retry provisioning**
(`…/provision`), **Send business details** (`…/business-details`), **Refresh status**
(`…/business-details/refresh`), **Offboard** (`…/offboard`, closed accounts only), and
the Numbers actions. Each button is audited.

**Ops console → voice workspaces summary** (`GET /v1/admin/engine-workspaces/summary`): the
plan as set in **ThinnestAI plan** (`thinnest_customer_plan`) and its cap, how many
workspaces count against it (active, offboarding, and deleted but not yet erased),
headroom, live tenants against workspaces provisioned, counts by status, tenants with no
workspace yet, and up to 50 clients that are waiting on the plan, failing, or never
provisioned, each with its error code.

## `plan_limit` — `engine_workspace_plan_limit`

Our plan decides how many customer workspaces we may hold: **3 on Free and pay-as-you-go,
100 on Pro, 1,000 on Scale, 10,000 on Enterprise**, and a deleted customer counts until it
is erased 30 days after deletion (`api-reference/customers.md:191-200`). Every tenant gets
one, test tenants included. Over the cap `POST /customers` answers 402 (`:62-66`;
`plan_limit` / `plan_required`, `api-reference/errors.md:156-157`).

1. Read the summary: is headroom 0? Count deleted-not-erased workspaces in it: closing a
   test tenant does not free a slot for 30 days.
2. Upgrade the plan in the ThinnestAI console (founder action; gate T-8), or get a written
   raise from ThinnestAI.
3. Set **ThinnestAI plan** (`thinnest_customer_plan`) in the ops console to the new plan.
   It only changes what our pages and alarms say; the vendor enforces the cap. Set it after
   the upgrade, never before.
4. Press **Retry provisioning** on each waiting client's admin page, or leave it to the daily sweep.
5. Check the client reads `active`, then that its business details were sent (below).

Do not delete another client's workspace to make room.

## `failed` — `engine_workspace_provisioning_failed`

The error code on the page says which:

- `engine_rejected` — ThinnestAI refused the request. The operator log line for the job
  carries the vendor's status and message (never shown to clients). Common causes: the API
  key is not a **full** key (creating a customer needs one, `customers.md:59-60`); our
  workspace uses white label (409, `:66`); a field refused (400).
- `engine_workspace_is_developer` — the vendor answered with OUR developer workspace's id
  for the client. Nothing was recorded. Check the customer list in the ThinnestAI console
  for a customer with `externalId` `calevate-<tenant uuid>`; set
  **ThinnestAI developer workspace id** (`thinnest_developer_workspace_id`) if it is empty
  (gate T-16), then **Retry provisioning**.
- an error type name (a timeout, a connection error) — the vendor was unreachable; the job
  retried and gave up. Check ThinnestAI's status and our egress, then **Retry provisioning**.

Fix the cause, then press **Retry provisioning**. The daily sweep also retries `failed`.

## Business details

India issues a number only to an approved business, one application per workspace
(`api-reference/phone-numbers/get-business-details.md:7`). We send the client's verified KYC
record (D-692): legal name, GST yes/no, and its one business certificate, with
`PUT /phone-numbers/business-details` (`send-business-details.md:7`). It is sent as soon as
the workspace is active AND the KYC record is verified, whichever happens second.

- **`engine_business_details_submit_failed`** — the send failed after the retries. Open the
  client's KYC page: the certificate must be PDF, JPG or PNG, at most 5 MB, filename at most
  99 characters (`send-business-details.md:7`). Then **Send business details**. A 409 from
  the vendor is not a failure: an application is already being checked or approved, and we
  read it back.
- **`engine_business_details_lapsed`** (`tenant_id` on the alarm) — the application is
  `rejected` or `suspended`. The review note is on the admin page and on the client's
  Numbers page. The client corrects its certificate under **Verify your business** (or an
  admin uploads the corrected one on the KYC page) and presses **Send the details again**; a resend
  after a rejection corrects the same application (`send-business-details.md:7`). An
  `expired` one is resent automatically by the daily `sweep_engine_workspaces`.
- **Stuck at `submitted`** — approval "usually takes a few minutes" (`:7`). Press **Check
  now**. Approval through the API for a customer workspace is untested live (gate T-20); if
  it does not land, record what the vendor shows and raise it with ThinnestAI. Do not submit
  the client's details in our developer workspace instead.

## Buying a number

Gates, in order: workspace `active`, KYC verified, business details `accepted` with
`canRent`, an attested client number price (gate 26). The client is charged our price (₹499
attested), never ThinnestAI's `monthlyPrice`, which is our cost.

- **`engine_number_rent_unfunded`** — ThinnestAI refused the rent with 402: our balance
  cannot pay the first month (`rent-phone-number.md:7`). Nothing was charged to the client.
  Top up the ThinnestAI balance; the client can buy again straight away.
- **`engine_number_purchase_unconfirmed`** (refusal) — the vendor's answer was lost. The
  client presses Buy again: the same request is resolved by reading the number back from the
  workspace and never rents a second number (gate T-19).
- A number rented in our developer workspace before D-693 is "held in the platform account":
  testing only (gate T-21). To take it back from a client, use **Release our record**, which
  detaches it and keeps it ours.

## Agent retire failure — `engine_agent_retire_failed`

An agent made before D-693 is recreated in its client's workspace on its next publish, under
a new vendor id; the old copy in our developer workspace is deleted afterwards by
`retire_moved_engine_agent`, which waits while a call is connected on it (what a delete does
to a live call is undocumented, gate T-17). The alarm means a call was still connected after
every retry, or the delete failed. The new agent is live and unaffected; the old copy answers
nothing new once its number moves.

1. In the ThinnestAI console (developer workspace, not the customer), find the old agent by
   the id in the operator log.
2. Wait until it has no call in progress, then delete it there.
3. Its webhook and actions go with it. Our old route row stays inactive.

## Offboarding

Closing an account queues `offboard_engine_workspace`: every rented number in the client's
workspace is released with `?confirm=release` — permanent, the number goes back to the pool,
and this month's rent is not refunded (`api-reference/phone-numbers/release-phone-number.md:7`)
— our rental stops, each agent's actions are retired and the agent deleted, then the
customer is deleted with `DELETE /customers/{id}`. The vendor refuses that delete with 409
while the customer still holds a rented number (`customers.md:142-146`), which is why the
numbers go first. After deletion requests into it answer 410, its webhooks are off, and it is
erased 30 days later; until then it can be restored (`:148-161`).

**`engine_workspace_offboarding_failed`.** The alarm says how many numbers were released
and agents deleted before it stopped. **A rented number left in the workspace is still
charged to us every month.**

1. Open the client's admin page: status `offboarding`, the error code, the numbers still
   held.
2. Press **Offboard** (refused unless the account is closed). Every step is safe to
   repeat: a released number and a deleted agent are skipped.
3. If it fails again, open that customer in the ThinnestAI console and release its numbers
   there (Phone Numbers → release, inside the customer, never in our developer workspace),
   then press **Offboard** so the agents and the customer are deleted and our rows
   follow.
4. The page reads `deleted` when done.

**Restoring a closed account** re-provisions: the job finds the deleted customer by our
reference and restores it if the vendor still holds it (within 30 days), else creates a new
one. Released numbers do not come back; the client buys new ones.

## Other alarms on this path

- `engine_workspace_byok_not_inherited` — with Studio on, a client workspace does not run on
  our voice key. Open that customer in the ThinnestAI console: its own-keys switch must be
  off with no keys of its own (`api-reference/bring-your-own-keys.md:129-133`). Then re-run
  **Enable Studio voices**, which reports how many workspaces inherit.
- `engine_action_workspace_mismatch` — an in-call action arrived naming another workspace
  than its agent's (`agent/custom-api.md:116-119`) and was refused. Republish the agent; if
  it recurs, look for a copy of the action on an agent that is not ours.
