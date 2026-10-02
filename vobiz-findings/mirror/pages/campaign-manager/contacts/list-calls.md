> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List campaign call attempts

> Retrieve the per-attempt call log for a campaign, joining campaign call records with CDR data, using page and per_page pagination.

```http theme={null}
GET https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/calls
```

Returns every call attempt for the campaign, joining the campaign call map with CDR data.

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
  The campaign whose attempts you want to inspect.
</ParamField>

<ParamField query="page" type="integer" default="1">
  Page number. This endpoint uses 1-based paging, unlike the `offset` style used elsewhere.
</ParamField>

<ParamField query="per_page" type="integer" default="20">
  Results per page. Maximum `200`.
</ParamField>

<ParamField query="status" type="string">
  Filter attempts by status.
</ParamField>

<ParamField query="search" type="string">
  Searches both the `to` and `from` numbers.
</ParamField>

## Example

```bash cURL theme={null}
curl "https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/calls?page=1&per_page=20" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}"
```

<Note>
  Campaign-side attempt data is returned even when the CDR service has no matching row yet, so a very recent attempt still appears. Save a returned `call_uuid` to correlate the attempt with CDRs or with [Call lookup](/docs/campaign-manager/capacity/call-lookup).
</Note>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.