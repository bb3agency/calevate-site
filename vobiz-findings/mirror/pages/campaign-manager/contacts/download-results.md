> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Download campaign results

> Export campaign contact outcomes as CSV, including partial exports while the campaign is still running.

```http theme={null}
GET https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/results
```

Returns contact outcomes as `text/csv`. Results are available while the campaign is running, so partial exports are supported.

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
  The campaign to export.
</ParamField>

## Example

```bash cURL theme={null}
curl "https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/results" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}" \
  -o campaign-results.csv
```

## CSV columns

```text theme={null}
row_number,to_number,from_number_used,status,call_uuid,duration,hangup_cause,attempt_number,answered_at
```

Contact statuses are `pending`, `dialling`, `answered`, `no_answer`, `busy`, `failed`, `retry_pending`, and `expired`.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.