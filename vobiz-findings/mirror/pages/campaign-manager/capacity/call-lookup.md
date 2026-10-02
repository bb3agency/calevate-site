> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Look up a campaign call

> Resolve a call UUID to its campaign and contact, and confirm that a campaign owns a given call.

```http theme={null}
GET https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/call-lookup/{call_uuid}
```

Resolves a call UUID to its campaign and contact. Use it to confirm that a campaign owns a given call before acting on a CDR or webhook.

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
  The campaign expected to own the call.
</ParamField>

<ParamField path="call_uuid" type="string" required>
  The call UUID, as returned by [List call attempts](/docs/campaign-manager/contacts/list-calls), a CDR record, or a campaign webhook.
</ParamField>

## Example

```bash cURL theme={null}
curl "https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/call-lookup/{call_uuid}" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}"
```

A call that does not belong to the campaign, or to the authenticated account, returns `404`.

<Note>
  The Vobiz CDR pipeline uses an internal equivalent of this route, `GET /internal/call-lookup/{call_uuid}`, which is authenticated with `X-Internal-Key` and is not reachable through the public gateway. See [Authentication](/docs/campaign-manager/authentication).
</Note>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.