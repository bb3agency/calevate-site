> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Build your own product on the API

> Give each of your customers their own agents, numbers and conversations — from your dashboard, with one key.

You run a product of your own and want AI agents inside it: each of your customers gets agents
that answer their chats and calls, and you build the screens. You never send your customers to
our console.

The pattern is three calls: make a **customer**, work **inside** it with a header, and hear about
**all** of them on one webhook.

## 1. Make a customer

When one of your customers signs up with you, create a workspace for them. Use your own id as
`externalId` so you can find it again, and send an `Idempotency-Key` so a retry never makes two.

```bash theme={null}
curl https://YOUR_APP/api/v1/customers \
  -H "Authorization: Bearer $KEY" \
  -H "Idempotency-Key: signup-4812" \
  -H "Content-Type: application/json" \
  -d '{ "name": "Acme Dental", "externalId": "acct_4812" }'
```

Keep the `id` it returns (`org_…`) next to your own record of the account.

## 2. Build their agent

Add `Thinnest-Workspace` with that id. Every endpoint now works inside that customer — agents,
knowledge, phone numbers, contacts, campaigns, conversations.

```bash theme={null}
curl https://YOUR_APP/api/v1/agents \
  -H "Authorization: Bearer $KEY" \
  -H "Thinnest-Workspace: org_1f2e…" \
  -H "Content-Type: application/json" \
  -d '{ "name": "Front desk" }'
```

Then give it something to answer from:

```bash theme={null}
curl https://YOUR_APP/api/v1/agents/ag_…/knowledge \
  -H "Authorization: Bearer $KEY" \
  -H "Thinnest-Workspace: org_1f2e…" \
  -H "Content-Type: application/json" \
  -d '{ "url": "https://acme-dental.example/faq" }'
```

## 3. Hear about every customer on one webhook

Register one webhook on your own workspace for all your customers' events:

```bash theme={null}
curl https://YOUR_APP/api/v1/webhooks \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{ "includeCustomers": true, "url": "https://you.example/hooks/agents" }'
```

Each delivery says which customer it is about in `data.workspaceId`, inside the signed body — so
you can route it to the right account.

## 4. Show them what they used

`GET /api/v1/customers/{id}` returns `spendThisMonthMicro` — what that customer's usage has cost
you this month — so you can show usage, or charge for it, in your own billing.

Everything your customers use is charged to your balance. Keep it topped up: when it runs out,
your customers' agents stop with you.

## Let your AI coding assistant do it

Connect the MCP server with the header and your assistant builds inside that customer:

```bash theme={null}
claude mcp add --transport http acme https://YOUR_APP/api/v1/mcp \
  --header "Authorization: Bearer $KEY" \
  --header "Thinnest-Workspace: org_1f2e…"
```

## When a customer leaves you

Release their phone numbers and disconnect WhatsApp, then delete the customer. You have 30 days
to restore it; after that everything is erased.

<Card title="Customers reference" icon="code" href="/api-reference/customers">
  Every field, status code and limit.
</Card>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.