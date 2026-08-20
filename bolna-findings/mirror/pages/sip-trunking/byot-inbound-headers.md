> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Custom SIP headers on inbound BYOT calls

> Map custom SIP headers (X-CALLERNO, X-UCID, …) on inbound BYOT trunk calls into Bolna agent prompt variables, and use a header value as the lookup key into your CSV / API / Sheet data source.

## What this does

When you bring your own SIP trunk, your carrier often attaches **custom headers** to inbound `INVITE` messages — caller ID values, session IDs, account references, transfer hints. SIP header variables let your agent declare which of those headers it cares about and what to call them inside the prompt.

```
INVITE sip:+91XXXXXXXXXX@asterisk SIP/2.0
…
X-CALLERNO: 0XXXXXXXXXX
X-UCID:     XXXXXXXXXXXXXXXXX
X-ACCOUNT:  <account_id>
```

Map each header to a prompt variable on the agent and reference it with `{...}`:

```text theme={"system"}
You are calling on behalf of {account}. The caller is {caller_no}. Their
session ID is {ucid} — never read it out loud.
```

<Info>
  This feature is only active when the agent's telephony provider is **SIP Trunk**. Twilio, Plivo, Exotel and Vobiz inbound calls ignore it — for those providers, all per-call context already arrives through the provider's own webhooks.
</Info>

***

## When to use it

<CardGroup cols={2}>
  <Card title="Per-call data from the carrier" icon="signal-stream">
    Your carrier sends per-call metadata (campaign ID, line ID, agent transfer flag) on every INVITE and you want the LLM to use it.
  </Card>

  <Card title="CSV / API lookup keyed by a header" icon="key">
    The number in the `From:` SIP URI is not the lookup key your data is organized around — it's a different field on the INVITE (e.g. `X-CALLERNO`, `X-ACCOUNT`).
  </Card>
</CardGroup>

***

## Configure the agent

Two fields on the agent control the behaviour. Both are optional and independent — an agent with neither set behaves exactly as before.

| Field                  | Type   | Purpose                                                                                                                                                                                                                                     |
| ---------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sip_header_variables` | object | Map of `{"<SIP-header-name>": "<prompt-variable-name>", …}`. Each header that arrives on the INVITE is renamed to your declared variable name and merged into `recipient_data` before the prompt is rendered.                               |
| `ingest_lookup_key`    | string | Name of a SIP header whose **value** should be used as the lookup key for your CSV / API / Google-Sheet data source, instead of the caller's phone number. Falls back to the phone number if the header isn't present on the specific call. |

<Tabs>
  <Tab title="Dashboard">
    Open the agent, switch to the **Call** tab, and set **Telephony Provider** to *SIP Trunk*. The **SIP Header Variables** section appears in the inbound settings card.

    1. For each header your carrier sends, add a row: header name on the left (case-sensitive, e.g. `X-CALLERNO`), prompt variable name on the right (e.g. `caller_no`).
    2. If you want the data-source lookup to use a header value instead of the caller's phone number, pick that header from the **Ingest lookup key** dropdown. The dropdown is populated from the headers you just declared.
    3. Save.
  </Tab>

  <Tab title="API">
    ```bash theme={"system"}
    curl -X PATCH "https://api.bolna.ai/agent/$AGENT_ID" \
      -H "Authorization: Bearer $API_KEY" \
      -H "Content-Type: application/json" \
      -d '{
        "agent_config": {
          "sip_header_variables": {
            "X-CALLERNO": "caller_no",
            "X-UCID":     "ucid",
            "X-ACCOUNT":  "account"
          },
          "ingest_lookup_key": "X-CALLERNO"
        }
      }'
    ```

    To clear either field, send `null`.
  </Tab>
</Tabs>

***

## Worked example

A carrier sends this INVITE for every inbound call:

```
INVITE sip:+91XXXXXXXXXX@asterisk SIP/2.0
…
X-CALLERNO: 0XXXXXXXXXX
X-UCID:     XXXXXXXXXXXXXXXXX
X-ACCOUNT:  <account_id>
X-DID:      91XXXXXXXXXX
```

The agent is configured as:

```json theme={"system"}
{
  "sip_header_variables": {
    "X-CALLERNO": "caller_no",
    "X-UCID":     "ucid",
    "X-ACCOUNT":  "account"
  },
  "ingest_lookup_key": "X-CALLERNO"
}
```

…with a CSV uploaded under **Database for inbound phone numbers**:

```csv theme={"system"}
contact_number,first_name,plan
0XXXXXXXXXX,Ramesh,Pro
08860123456,Anita,Basic
```

On the next inbound call, Bolna will:

1. Read `X-CALLERNO`, `X-UCID`, `X-ACCOUNT` from the INVITE.
2. Look up the CSV row where `contact_number = 0XXXXXXXXXX` (the `X-CALLERNO` value, not the SIP `From` number).
3. Render the prompt with `caller_no = 0XXXXXXXXXX`, `ucid = XXXXXXXXXXXXXXXXX`, `account = <account_id>`, `first_name = Ramesh`, `plan = Pro`.

<Warning>
  The lookup is an **exact string match**. If your carrier sends `X-CALLERNO: 0XXXXXXXXXX` (with leading zero, no country code) your CSV's `contact_number` column has to use that exact same form. Bolna does not normalize or strip prefixes.
</Warning>

***

## How CSV / API enrichment interacts with header pass-through

Both can be active on the same agent. The merge order is:

1. **Header pass-through** runs first — the declared variables land in `recipient_data`.
2. **CSV / API / Sheet enrichment** runs second, using `ingest_lookup_key`'s value (or the caller's phone number if unset), and **overrides** any header-supplied variable with the same name.

CSV is authoritative on collisions because it's the data your team manages by hand. Use SIP headers for "what the carrier knows about this specific call" and CSV/API for "what your business knows about this customer."

***

## Tips and gotchas

<AccordionGroup>
  <Accordion title="Header names are case-sensitive">
    SIP allows mixed case but most carriers send `X-FOO` exactly as configured. Inspect a packet capture or your trunk provider's documentation, then copy the header name verbatim into `sip_header_variables`. `X-CALLERNO` and `x-callerno` are not the same.
  </Accordion>

  <Accordion title="Missing headers do not fail the call">
    If a declared header is absent on a specific call, that prompt variable renders as the empty string. The call still goes through. If you depend on a header for the lookup key but it's missing, Bolna logs a warning and falls back to the caller's phone number.
  </Accordion>

  <Accordion title="Use {…} placeholders in the prompt">
    Reference declared variables with curly braces: `{caller_no}`, `{ucid}`, `{account}`. The same syntax works in welcome messages, system prompts and webhook URLs.
  </Accordion>

  <Accordion title="Other telephony providers ignore these fields">
    `sip_header_variables` and `ingest_lookup_key` are only consulted when the agent's telephony provider is `sip-trunk`. Setting them on a Twilio or Plivo agent is harmless but has no effect.
  </Accordion>
</AccordionGroup>

***

## Related features

<CardGroup cols={2}>
  <Card title="Identify incoming callers" icon="filter-list" href="/docs/customizations/identify-incoming-callers">
    Match inbound calls to user records via CSV, API, or Google Sheets.
  </Card>

  <Card title="BYOT setup" icon="phone-volume" href="/docs/sip-trunking/byot-setup">
    Connect your carrier's SIP trunk to Bolna.
  </Card>

  <Card title="BYOT inbound calls" icon="phone-arrow-down-left" href="/docs/sip-trunking/byot-inbound-calls">
    Receive inbound calls on your trunk and route them to agents.
  </Card>

  <Card title="Using context" icon="brackets-curly" href="/docs/guides/prompting/using-context">
    Pass dynamic variables into prompts at call time.
  </Card>
</CardGroup>
