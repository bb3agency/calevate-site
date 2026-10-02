> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Upload campaign contacts

> Upload a contacts CSV to a campaign. A valid upload moves the campaign from draft to ready and detects custom columns as SIP headers.

```http theme={null}
POST https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/upload
```

Upload contacts after you create a campaign. A valid upload moves the campaign from `draft` to `ready`.

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
  The campaign that receives the contacts.
</ParamField>

<ParamField body="file" type="file" required>
  The contacts CSV, sent as `multipart/form-data` in a field named `file`.
</ParamField>

## Example

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/upload" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}" \
  -F "file=@contacts.csv"
```

## CSV columns

| Column | Required | Behaviour |
| - | - | - |
| `to` | Always | Destination number in E.164 format. |
| `from` | For `per_contact` strategy | Caller ID for this contact. |
| `answer_url` | No | Overrides the agent answer URL for this contact. |
| `hangup_url` | No | Overrides the agent hangup URL for this contact. |
| Any other column | No | Sent as a custom SIP header on the call. |

```csv Fixed strategy theme={null}
to,CustomerID,LeadScore
+919876543210,CUST_001,High
+919876543211,CUST_002,Medium
```

```csv Per-contact strategy theme={null}
to,from,answer_url,CustomerID
+919876543210,+912234567890,https://example.com/answer?id=asha,CUST_001
+919876543211,+912234567891,,CUST_002
```

The streaming parser handles BOM and CRLF line endings. There is no hard row limit, but uploads above 500,000 rows produce an advisory warning.

## Response

```json 200 OK theme={null}
{
  "valid_contacts": 980,
  "invalid_rows": 20,
  "total_rows": 1000,
  "custom_headers_detected": ["CustomerID", "LeadScore"]
}
```

<Warning>
  Re-uploading to a `ready` campaign **replaces every existing contact**. Upload is blocked with `409` while a campaign is `running`, `paused`, or `queued`.
</Warning>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.