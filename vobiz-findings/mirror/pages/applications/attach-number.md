> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Attach Number to Application

> Link a Vobiz phone number to a voice Application so incoming calls and messages on that number are routed to the Application's configured webhooks.

Link a phone number from your account inventory to a voice application. After attaching, all incoming calls to that number are routed through the application's `answer_url` and `hangup_url` webhooks.

<Note>
  This operation lives under the **numbers** path (lowercase), not under `Application`: `POST /api/v1/Account/{auth_id}/numbers/{number}/application`.
</Note>

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<ParamField header="X-Auth-ID" type="string" required>
  Your Vobiz account ID, for example `MA_XXXXXXXX`.
</ParamField>

## Path parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your account Auth ID |
| `number` | string | Yes | The E.164-formatted phone number, **URL-encoded** (`+` → `%2B`). Example: `%2B1234567890` |

<ParamField path="auth_id" type="string" required>
  Your Vobiz account ID. Use the same value in `X-Auth-ID`.
</ParamField>

<ParamField path="number" type="string" required>
  The E.164-formatted phone number, URL-encoded (`+` → `%2B`). Example: `%2B1234567890`.
</ParamField>

## Body parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `application_id` | string | Yes | The `app_id` of the application to attach to this number. |

<ParamField body="application_id" type="string" required>
  The `app_id` of the application to attach to this number.
</ParamField>

## Example request

```bash cURL theme={null}
curl -X POST "https://api.vobiz.ai/api/v1/Account/{auth_id}/numbers/%2B1234567890/application" \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "application_id": "app_xxxxxxxxxxxx"
  }'
```

## Response

```json Success Response (200 OK) theme={null}
{
  "message": "Number attached to application",
  "number": "+919876543210",
  "application": {
    "answer_method": "POST",
    "answer_url": "https://example.com/answer",
    "api_id": "aabbccdd-1234-5678-90ab-cdef12345678",
    "app_id": "12345678901234567",
    "app_name": "Acme Corp",
    "application_type": "XML",
    "created_at": "2026-04-02 12:11:19.740666+00:00",
    "default_app": false,
    "default_endpoint_app": false,
    "enabled": true,
    "fallback_answer_url": null,
    "fallback_method": "POST",
    "hangup_method": "POST",
    "hangup_url": "https://example.com/answer",
    "log_incoming_message": true,
    "message_method": "POST",
    "message_url": null,
    "public_uri": false,
    "resource_uri": "/v1/Account/MA_XXXXXXXX/Application/12345678901234567/",
    "sip_transfer_method": "POST",
    "sip_transfer_url": null,
    "sip_uri": "sip:12345678901234567@app.vobiz.ai",
    "sub_account": null,
    "updated_at": "2026-04-02 12:11:19.740666+00:00"
  }
}
```

## Edge cases

* **Re-attaching an already-linked number** overwrites the previous binding and re-points routing to the new `application_id`. You do not need to detach first.
* **Number not in your account** or **unknown `application_id`** returns a `404`. Confirm the number is purchased to your account and the `app_id` exists with [list applications](/docs/applications/list-all-applications).
* **URL-encode the number.** A raw `+` in the path will not match; use `%2B` (for example `%2B14155551234`).
* New numbers created while an application has `default_number_app: true` are auto-attached to that application, so an explicit attach is only needed to override the default or attach an existing number.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.