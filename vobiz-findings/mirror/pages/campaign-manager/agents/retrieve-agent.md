> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Retrieve a campaign agent

> Fetch a single Campaign Manager agent by ID, including its answer and hangup webhook configuration and static SIP headers.

```http theme={null}
GET https://api.vobiz.ai/api/v1/account/{account_id}/campaign/agents/{agent_id}
```

Returns the full configuration of one agent.

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

<ParamField path="agent_id" type="string" required>
  ID of the agent, returned by [Create an agent](/docs/campaign-manager/agents/create-agent).
</ParamField>

## Example

```bash cURL theme={null}
curl "https://api.vobiz.ai/api/v1/account/{account_id}/campaign/agents/{agent_id}" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}"
```

## Response

```json 200 OK theme={null}
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
  "created_at": "2026-08-28T09:14:22Z",
  "updated_at": "2026-08-28T09:14:22Z"
}
```

An agent that does not exist for the authenticated account returns `404`.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.