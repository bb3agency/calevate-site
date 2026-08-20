> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List phone numbers with the Bolna CLI

> Use the bolna numbers list command to view every phone number on the account, with provider, linked agent, and renewal date.

List every phone number on the account. Returns the number, telephony provider, linked agent ID, rented status, price, and renewal date. Maps to the `list_phone_numbers` MCP tool.

## Syntax

```bash theme={"system"}
bolna numbers list [flags]
```

## Flags

| Flag                  | Description                              | Default  |
| --------------------- | ---------------------------------------- | -------- |
| `-h, --help`          | Show help for the command                | –        |
| `-q, --quiet`         | Print only the bare number per row       | Disabled |
| `-o, --output string` | Output format: `table`, `json`, or `csv` | `table`  |

## Example

```bash theme={"system"}
bolna numbers list
```

```
NUMBER          PROVIDER   AGENT                                  RENTED   PRICE    RENEWS
+14155559999    Twilio     3fa8b2e1-9c4d-4a2f-8b1e-6d5c3a9f7e02   yes      $5/mo    2026-08-14
+919812345678   Plivo      —                                      yes      $5/mo    2026-08-02
```

```bash theme={"system"}
# Numbers with no linked agent
bolna numbers list --output json | jq -r '.[] | select(.agent_id == null) | .number'
```

<Note>
  Buying a number or linking it to an agent for inbound calls is currently done through the [Phone Numbers API](/docs/api-reference/phone-numbers/overview) — `bolna numbers list` is read-only.
</Note>
