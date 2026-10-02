> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Delete a campaign agent

> Soft-delete a Campaign Manager agent. Agents with active campaigns are rejected until those campaigns finish, are cancelled, or are archived.

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/account/{account_id}/campaign/agents/{agent_id}
```

Archives the agent rather than hard-deleting its data. Archived agents disappear from [List agents](/docs/campaign-manager/agents/list-agents) but remain attached to historical campaigns.

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
curl -X DELETE \
  "https://api.vobiz.ai/api/v1/account/{account_id}/campaign/agents/{agent_id}" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}"
```

<Warning>
  Deleting returns `409` when the agent still has a `running`, `queued`, or `paused` campaign. Finish, [cancel](/docs/campaign-manager/controls/cancel-campaign), or [archive](/docs/campaign-manager/controls/archive-campaign) the dependent campaigns first.
</Warning>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.