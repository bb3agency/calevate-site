> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Transfer a Call

> Redirect an active call to a new XML instruction URL mid-session using Vobiz - transfer the A-leg, B-leg, or full session for dynamic IVR call routing.

```http theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/
```

Transfer an in-progress call to a different URL for new call flow instructions. The new URL must return XML instructions that define the next steps for the call. Use this to implement call forwarding, IVR navigation, or dynamic call routing.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Warning>
  In PSTN transfer XML, set `<Dial callerId>` to a Vobiz number owned or authorized by your account. If you omit it, Vobiz derives the caller ID from the existing A-leg, which may not be authorized for the new outbound B-leg.
</Warning>

<Note>
  The call must be in an active state (in-progress) to be transferred. You can transfer both call legs independently using their respective UUIDs.
</Note>

<Warning>
  Transfer operations interrupt the current call flow and immediately execute the XML returned from the new URL. Ensure your transfer URL is accessible and returns valid XML.
</Warning>

## Path parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your Vobiz account ID (e.g., `{auth_id}`). |
| `call_uuid` | string | Yes | Unique identifier of the call to transfer. |

<ParamField header="X-Auth-ID" type="string" required>
  Your Vobiz account ID, for example `MA_XXXXXXXX`.
</ParamField>

<ParamField path="auth_id" type="string" required>
  Your Vobiz account ID. Use the same value in `X-Auth-ID`.
</ParamField>

<ParamField path="call_uuid" type="string" required>
  Unique identifier of the call to transfer.
</ParamField>

## Request Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `legs` | string | No | Which leg(s) of the call to transfer. Values: `aleg` (caller), `bleg` (callee), or `both`. Default: `aleg`. |
| `aleg_url` | string | No | URL to transfer the A leg (caller) to. Must return valid XML with call instructions. |
| `aleg_method` | string | No | HTTP method for `aleg_url`. Values: `GET`, `POST`. Default: `POST`. |
| `bleg_url` | string | No | URL to transfer the B leg (callee) to. Must return valid XML with call instructions. |
| `bleg_method` | string | No | HTTP method for `bleg_url`. Values: `GET`, `POST`. Default: `POST`. |

<ParamField body="legs" type="string" default="aleg">
  Which leg(s) of the call to transfer. One of `aleg` (caller), `bleg` (callee), or `both`.
</ParamField>

<ParamField body="aleg_url" type="string">
  URL to transfer the A leg (caller) to. Must return valid XML with call instructions.
</ParamField>

<ParamField body="aleg_method" type="string" default="POST">
  HTTP method for `aleg_url`. One of `GET` or `POST`.
</ParamField>

<ParamField body="bleg_url" type="string">
  URL to transfer the B leg (callee) to. Must return valid XML with call instructions.
</ParamField>

<ParamField body="bleg_method" type="string" default="POST">
  HTTP method for `bleg_url`. One of `GET` or `POST`.
</ParamField>

<Tip>
  **Transfer Leg Options:**

  * `aleg` - Transfers only the caller (A leg) to the new URL. Provide `aleg_url`.
  * `bleg` - Transfers only the callee (B leg) to the new URL. Provide `bleg_url`.
  * `both` - Transfers both legs to their respective URLs (requires both `aleg_url` and `bleg_url`).
</Tip>

<Note>
  Pass the `call_uuid` of the leg you are transferring in the path. The `legs` value tells Vobiz which side of that call to redirect. When transferring `aleg`, the B-leg keeps running its current flow (and vice versa) - use `both` to redirect the whole session at once.
</Note>

<Warning>
  Transfer is request-and-execute: as soon as the matching URL returns valid XML, the current flow is interrupted and the new XML runs immediately. If the URL is unreachable, times out, or returns invalid XML, the affected leg may be dropped. Host the transfer URL on reliable HTTPS infrastructure and return XML quickly.
</Warning>

## Response

Returns a success message confirming the call transfer request has been initiated.

```json Response - 202 Accepted theme={null}
{
  "api_id": "uuid-here",
  "message": "call transferred",
  "call_uuid": "call-uuid-here"
}
```

### Response Fields

| Field | Description |
| - | - |
| `api_id` | Unique identifier for this API request |
| `message` | Confirmation message indicating the transfer status |
| `call_uuid` | UUID of the call that was transferred |

## Error responses

| Status | Meaning | How to handle |
| - | - | - |
| `400 Bad Request` | No transfer URL supplied for the selected `legs` (e.g. `legs=both` without both `aleg_url` and `bleg_url`), or a malformed URL. | Send the URL(s) matching your `legs` value. |
| `401 Unauthorized` | Missing/incorrect auth headers, or a lowercase path. | Use both auth headers and the PascalCase path. |
| `404 Not Found` | The `call_uuid` is not an active call (already ended or never existed). | The call must be **in-progress** to transfer. Confirm with [Retrieve a Live Call](/docs/call/retrieve-live-call). |

<Note>
  This action only works on calls in the `in-progress` state. Queued or completed calls return `404`.
</Note>

## Example Request

<CodeGroup>
  ```json Transfer A Leg (Caller) Only theme={null}
  {
    "legs": "aleg",
    "aleg_url": "https://yourdomain.com/transfer_instructions/",
    "aleg_method": "POST"
  }
  ```

  ```json Transfer Both Legs theme={null}
  {
    "legs": "both",
    "aleg_url": "https://example.com/transfer/aleg",
    "aleg_method": "POST",
    "bleg_url": "https://example.com/transfer/bleg",
    "bleg_method": "POST"
  }
  ```

  ```bash cURL theme={null}
  curl -X POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/ \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "legs": "both",
      "aleg_url": "https://example.com/transfer/aleg",
      "aleg_method": "POST",
      "bleg_url": "https://example.com/transfer/bleg",
      "bleg_method": "POST"
    }'
  ```
</CodeGroup>

### Use Cases

* Implement call forwarding based on IVR input
* Route calls to different departments dynamically
* Play announcements or collect additional information mid-call
* Implement warm transfer scenarios with hold music
* Change call behavior based on external triggers or events

<Info>
  **XML Response Example:** Your transfer URL should return XML instructions like:

  ```xml theme={null}
  <Response>
    <Speak>Please hold while we transfer your call.</Speak>
    <Dial callerId="+14155551234">
      <Number>+14156667890</Number>
    </Dial>
  </Response>
  ```
</Info>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.