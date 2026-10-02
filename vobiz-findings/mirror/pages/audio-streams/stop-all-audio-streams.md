> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Stop all Audio Streams

> Stop every active audio stream running on a Vobiz call in one DELETE request - ideal for pipeline cleanup at call end or before transferring to a new flow.

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/Stream/
```

This endpoint stops all active streams attached to a call at once. It is useful when you want to tear down every forked audio pipeline before hanging up the call, or when switching the call into a new flow. Streams that have already stopped are not affected.

<Note>
  Each stream closed this way fires its own `Event=StopStream` status callback (if `status_callback_url` was set on that stream) and closes its WebSocket. To stop a single fork while leaving others running, use [Stop a Specific Audio Stream](/docs/audio-streams/stop-audio-stream) instead.
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
| `auth_id` | string | Yes | Your account ID. |
| `call_uuid` | string | Yes | UUID of the call. |

<ParamField path="auth_id" type="string" required>
  Your Vobiz account ID. Use the same value in `X-Auth-ID`.
</ParamField>

<ParamField path="call_uuid" type="string" required>
  UUID of the call.
</ParamField>

This endpoint takes no request body.

## Response

Returns **HTTP 204 No Content** on success, even if the call currently has no active streams (the operation is idempotent).

## Example

```bash cURL theme={null}
curl -X DELETE 'https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/Stream/' \
  -H 'X-Auth-ID: {auth_id}' \
  -H 'X-Auth-Token: {auth_token}'
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.