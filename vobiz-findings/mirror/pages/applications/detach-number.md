> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Detach Number from Application

> Remove the link between a phone number and a voice application. The number stays in your account inventory but no longer routes incoming calls to the app.

Remove the link between a phone number and a voice application. After detaching, incoming calls to that number will no longer route through the application - the number remains in your account inventory and can be attached to a different application.

<Note>
  This operation lives under the **numbers** path (lowercase): `DELETE /api/v1/Account/{auth_id}/numbers/{number}/application`. Detach every number bound to an application before you [delete the application](/docs/applications/delete-application), otherwise the delete returns a `409`.
</Note>

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
</Info>

<ParamField header="X-Auth-ID" type="string" required>
  Your Vobiz account ID, for example `MA_XXXXXXXX`.
</ParamField>

## Path parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your account Auth ID |
| `number` | string | Yes | The E.164-formatted phone number to detach, **URL-encoded** (`+` → `%2B`). Example: `%2B1234567890` |

<ParamField path="auth_id" type="string" required>
  Your Vobiz account ID. Use the same value in `X-Auth-ID`.
</ParamField>

<ParamField path="number" type="string" required>
  The E.164-formatted phone number to detach, URL-encoded (`+` → `%2B`). Example: `%2B1234567890`.
</ParamField>

This endpoint takes no request body.

## Example request

```bash cURL theme={null}
curl -X DELETE "https://api.vobiz.ai/api/v1/Account/{auth_id}/numbers/%2B1234567890/application" \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

## Response

```json Success Response (200 OK) theme={null}
{
  "message": "Number detached from application",
  "number": "+919876543210",
  "application": {
    "answer_method": "POST",
    "answer_url": "https://example.com/answer",
    "api_id": "aabbccdd-1234-5678-90ab-cdef12345678",
    "app_id": "12345678901234567",
    "app_name": "Acme Voice Application",
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

* **Detaching a number with no application** is effectively a no-op - there is nothing to unlink.
* **Number not in your account** returns a `404`. URL-encode the number (`+` → `%2B`).
* Detaching does **not** release the number from your account; it only clears the routing binding. To stop incoming calls entirely, also release the number from inventory.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.