> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List campaigns

> List active or archived outbound voice campaigns on your account with limit and offset pagination.

```http theme={null}
GET https://api.vobiz.ai/api/v1/account/{account_id}/campaigns
```

Returns active campaigns by default.

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

<ParamField query="archived" type="boolean" default="false">
  Set to `true` to list archived campaigns instead of active ones.
</ParamField>

<ParamField query="limit" type="integer" default="20">
  Number of campaigns to return per page.
</ParamField>

<ParamField query="offset" type="integer" default="0">
  Number of campaigns to skip before returning results.
</ParamField>

## Example

```bash cURL theme={null}
curl "https://api.vobiz.ai/api/v1/account/{account_id}/campaigns?limit=20&offset=0" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}"
```

```http Archived theme={null}
GET /api/v1/account/{account_id}/campaigns?archived=true&limit=20&offset=0
```

Archived campaigns are read-only. Their contacts, CDRs, and statistics remain available.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.