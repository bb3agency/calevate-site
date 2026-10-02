> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List campaign contacts

> Browse a campaign's contacts with limit and offset pagination, filter by contact status, or search for a specific number.

```http theme={null}
GET https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/contacts
```

Browse contact state for a campaign.

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

<ParamField path="campaign_id" type="string" required>
  The campaign whose contacts you want to browse.
</ParamField>

<ParamField query="limit" type="integer" default="20">
  Number of contacts to return per page.
</ParamField>

<ParamField query="offset" type="integer" default="0">
  Number of contacts to skip before returning results.
</ParamField>

<ParamField query="status" type="string">
  Filter by contact state: `pending`, `dialling`, `answered`, `no_answer`, `busy`, `failed`, `retry_pending`, or `expired`.
</ParamField>

<ParamField query="search" type="string">
  Find a specific destination number.
</ParamField>

## Example

```bash cURL theme={null}
curl "https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/contacts?limit=20&offset=0&status=answered" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}"
```

The response is `{ objects, total }`, where `total` is the unpaginated count for the applied filters.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.