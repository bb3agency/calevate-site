> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List campaign agents

> Retrieve every non-archived Campaign Manager agent on your account with limit and offset pagination.

```http theme={null}
GET https://api.vobiz.ai/api/v1/account/{account_id}/campaign/agents
```

Returns every non-archived agent on the account.

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

<ParamField query="limit" type="integer" default="20">
  Number of agents to return per page.
</ParamField>

<ParamField query="offset" type="integer" default="0">
  Number of agents to skip before returning results.
</ParamField>

## Example

```bash cURL theme={null}
curl "https://api.vobiz.ai/api/v1/account/{account_id}/campaign/agents?limit=20&offset=0" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}"
```

## Response

```json 200 OK theme={null}
{
  "objects": [
    {
      "id": "9f1c4b6a-2f0e-4a3d-8b21-6c5f0d9a7e42",
      "name": "Appointment Reminder Agent",
      "answer_url": "https://example.com/answer",
      "answer_method": "POST"
    }
  ],
  "total": 5,
  "limit": 20,
  "offset": 0
}
```

Archived agents are excluded. `total` reflects the unpaginated count.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.