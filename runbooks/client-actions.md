# Client in-call actions (D-700)

What a client's agent does in the client's own systems during a call: know the caller, find
free times and book, send a WhatsApp or a payment link, save the caller to their CRM or
sheet, call their own API. Built in `apps/api/actions/`; synced to ThinnestAI by
`apps/api/reliability/engine_actions.py`; reached mid-call through
`POST /v1/worker/engine-actions/{engine}/client/{name}` (and, on Pipecat,
`POST /v1/worker/calls/{engine_call_id}/tools/actions/{name}`), both ending in
`actions/in_call.run_in_call_action`.

## Before the first client uses one

1. OPERATIONS gates A-1..A-3: the Google, Zoho and HubSpot apps registered and their three
   settings each saved in the ops console. Until then each connect button reads "Not
   available yet" and nothing else breaks.
2. Google Sheets (D-703): OPERATIONS gate G-2 — the Sheets and Picker APIs enabled, the
   `drive.file` scope added, a website-restricted picker key and the project number saved.
   Each client then connects Google Sheets on their own Google account and picks each
   spreadsheet in Google's picker; nothing is shared by hand.
3. `ENGINE_ACTIONS_BASE_URL` is the API's public https address (the same one our four
   platform actions use).
4. Run gate A-7: one client action, end to end, on a real call.

Caller lookup: on calls the agent places it runs before the phone rings (`actions/pre_dial.py`); on calls that come in it is the agent's first action after its greeting (gate A-11).

## A client says "the agent said it can't do that"

1. Integrations → Connected accounts → **Check** on the account the action uses. A refusal
   there is the cause: reconnect it (sign in again, or paste a new key).
2. Agent → Actions → the action → **Runs**. The outcome of every run is listed: `Account not
   connected`, `Account refused the connection`, `Caller has not agreed to WhatsApp`, `Took
   too long` and so on.
3. Needs-attention shows "Action needs a connection" for an action whose connection is
   gone or whose latest run failed on it.
4. `Caller has not agreed to WhatsApp` is the law working: the caller has no messaging
   consent on file (`/c/<slug>/messaging-consent`). Not a fault.

## The agent never uses a new action

1. Is the master switch on and the action on? Only the owner can switch either on.
2. Is the agent live? A switched-on action reaches a live agent at once; a draft agent gets
   it when it is published.
3. More than four actions on one agent are refused by name (`client_actions_over_limit`,
   gate A-6).
4. The alarm `client_actions_not_synced` means ThinnestAI could not be updated; the drift
   sweep retries. Republishing the agent converges it at once.

## Disconnecting, archiving, closing

Disconnecting an account re-syncs every agent using it, so its actions leave the live
agents in the same request, and asks Google or Zoho to revoke our access (HubSpot: the
client uninstalls the app in HubSpot). Pausing or archiving an agent removes all its
actions, ours and the client's (`retire_agent_actions`). Closing an account deletes its
agents at ThinnestAI, which takes their actions with them.

## What is never done

- No action uses Calevate's own Razorpay keys: a payment link is created on the client's
  account with the client's keys, and no money touches ours.
- No WhatsApp goes to a number without the dispatch gate (DNC) and the caller's messaging
  consent, and never as free text: always an approved template.
- No SMS (WhatsApp only, founder decision; SMS needs DLT).
- Payment links do not run on a free-trial account (D-697).

## Not built yet: helpdesk tickets (Zendesk, Freshdesk)

A client who wants a support ticket opened when a caller reports a problem can do it today
without new code: send the call's lead through a signed webhook (Integrations) to Zapier,
Make or Pabbly, and let that create the ticket in Zendesk or Freshdesk. A direct helpdesk
action is deferred by the founder (9 Oct 2026) until a client asks for one; build it then
as one more action kind on the same executor (`actions/execution.py`), with the client's
own helpdesk credentials.
