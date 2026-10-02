> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Create a campaign agent

> Create a reusable Campaign Manager agent that defines the answer URL, hangup URL, and static SIP headers used for every call in a campaign.

```http theme={null}
POST https://api.vobiz.ai/api/v1/account/{account_id}/campaign/agents
```

An agent is a reusable webhook configuration shared by multiple campaigns. It defines what Vobiz calls when a contact answers and, optionally, when the call ends.

<Info>
  **Authentication required**

  * `X-Auth-ID` — your Vobiz account ID
  * `X-Auth-Token` — your Vobiz auth token
</Info>

<ParamField path="account_id" type="string" required>
  Your Vobiz account ID. Use the same value in `X-Auth-ID`.
</ParamField>

<ParamField header="X-Auth-ID" type="string" required>
  Your Vobiz account ID, for example `MA_XXXXXXXX`.
</ParamField>

<ParamField body="name" type="string" required>
  Agent name. Unique per account, maximum 100 characters.
</ParamField>

<ParamField body="answer_url" type="string" required>
  HTTPS URL called when the contact answers. Must return Vobiz XML.
</ParamField>

<ParamField body="answer_method" type="string" default="POST">
  HTTP method for `answer_url`. `GET` or `POST`.
</ParamField>

<ParamField body="hangup_url" type="string">
  URL called when the call ends.
</ParamField>

<ParamField body="hangup_method" type="string" default="POST">
  HTTP method for `hangup_url`. `GET` or `POST`.
</ParamField>

<ParamField body="static_headers" type="array">
  Array of `{ key, value }` objects sent as SIP headers on every call placed by this agent.
</ParamField>

## Example

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/account/{account_id}/campaign/agents" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Appointment Reminder Agent",
    "answer_url": "https://example.com/answer",
    "answer_method": "POST",
    "hangup_url": "https://example.com/hangup",
    "hangup_method": "POST",
    "static_headers": [
      { "key": "X-Campaign-Type", "value": "reminder" },
      { "key": "X-Version", "value": "1" }
    ]
  }'
```

## Response

```json 201 Created theme={null}
{
  "id": "9f1c4b6a-2f0e-4a3d-8b21-6c5f0d9a7e42",
  "name": "Appointment Reminder Agent",
  "answer_url": "https://example.com/answer",
  "answer_method": "POST",
  "hangup_url": "https://example.com/hangup",
  "hangup_method": "POST",
  "static_headers": [
    { "key": "X-Campaign-Type", "value": "reminder" }
  ],
  "created_at": "2026-08-28T09:14:22Z"
}
```

Save the returned `id` and pass it as `agent_id` when you [create a campaign](/docs/campaign-manager/campaigns/create-campaign).

<Note>
  A launch takes a frozen agent snapshot. Editing an agent does not change campaigns that are already `running` or `queued` — the next launch uses the updated values.
</Note>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.