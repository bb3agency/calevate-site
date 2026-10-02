> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Update a campaign agent

> Partially update a Campaign Manager agent. Only the fields you send are changed; running campaigns keep the agent snapshot taken at launch.

```http theme={null}
PUT https://api.vobiz.ai/api/v1/account/{account_id}/campaign/agents/{agent_id}
```

Updates are partial — only the fields you supply change.

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

<ParamField body="name" type="string">
  New agent name. Unique per account, maximum 100 characters.
</ParamField>

<ParamField body="answer_url" type="string">
  HTTPS URL called when the contact answers.
</ParamField>

<ParamField body="answer_method" type="string">
  `GET` or `POST`.
</ParamField>

<ParamField body="hangup_url" type="string">
  URL called when the call ends.
</ParamField>

<ParamField body="hangup_method" type="string">
  `GET` or `POST`.
</ParamField>

<ParamField body="static_headers" type="array">
  Replaces the existing array of `{ key, value }` SIP headers.
</ParamField>

## Example

```bash cURL theme={null}
curl -X PUT \
  "https://api.vobiz.ai/api/v1/account/{account_id}/campaign/agents/{agent_id}" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}" \
  -H "Content-Type: application/json" \
  -d '{ "answer_url": "https://example.com/answer-v2" }'
```

<Warning>
  Campaigns that are already `running` or `queued` use the agent snapshot frozen at launch. Your edit applies to the next launch, not to work already in flight.
</Warning>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.