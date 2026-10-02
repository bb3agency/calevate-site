> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Hang Up a Call

> Terminate an active Vobiz call by UUID - hang up the A-leg, B-leg, or full bridged session instantly with a DELETE request that triggers CDR generation.

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/
```

Terminate an active call by hanging up one or both call legs. You can hang up the caller (A leg), the callee (B leg), or both legs simultaneously. The call is terminated immediately and a final CDR is generated.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Warning>
  This permanently terminates the call. This action cannot be undone.
</Warning>

<Note>
  Hanging up a call triggers the `hangup_url` callback if one was configured when the call was initiated, allowing you to perform cleanup or logging.
</Note>

<ParamField header="X-Auth-ID" type="string" required>
  Your Vobiz account ID, for example `MA_XXXXXXXX`.
</ParamField>

## Path parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your Vobiz account ID (e.g., `{auth_id}`). |
| `call_uuid` | string | Yes | Unique identifier of the call to hang up. |

<ParamField path="auth_id" type="string" required>
  Your Vobiz account ID. Use the same value in `X-Auth-ID`.
</ParamField>

<ParamField path="call_uuid" type="string" required>
  Unique identifier of the call to hang up.
</ParamField>

## Request Parameters

<Note>
  **No Request Body Required:** This endpoint does not require any request body parameters. Simply send a DELETE request to the endpoint URL.
</Note>

## Response

Returns a confirmation that the hangup request was processed.

```text Response - 204 No Content theme={null}
No Content
```

<Note>
  **After Hangup:** The call's final CDR will show `hangup_source` as "API" and the `hangup_cause_code` will indicate a programmatic termination (typically code 16: NORMAL\_CLEARING).
</Note>

## Example Request

```bash cURL theme={null}
curl -X DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

### Use Cases

* Terminate abandoned or idle calls to prevent billing
* Implement time-based call limits for compliance
* End calls based on external triggers (e.g., fraud detection)
* Implement emergency call termination features
* Clean up stale call sessions during maintenance

<Tip>
  To retrieve the final call details after hanging up, use the [Retrieve a Call](/docs/call/retrieve-live-call) endpoint with the call UUID. The CDR will include final duration and billing information.
</Tip>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.