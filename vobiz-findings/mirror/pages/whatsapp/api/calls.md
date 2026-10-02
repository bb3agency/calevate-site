> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Calls API

> Initiate and manage WhatsApp Business voice calls programmatically via Vobiz - WebRTC-based signaling for inbound, outbound, and call state management over the internet.

<Note>
  WhatsApp Business Calling runs over WhatsApp's WebRTC infrastructure, not the PSTN. The recipient's device must support WhatsApp voice calls and be connected to the internet.
</Note>

**Base URL:** `https://api.vobiz.ai/api/v1/messaging`

**Authentication:** Every request requires `X-Auth-ID: MA_XXXXXXXX` and `X-Auth-Token: <token>` headers (a `Bearer` JWT is also accepted). Set `Content-Type: application/json` on requests with a body. Get your credentials from [console.vobiz.ai](https://console.vobiz.ai).

<ParamField header="X-Auth-ID" type="string" required>
  Your Vobiz account ID, for example `MA_XXXXXXXX`.
</ParamField>

## Endpoints overview

| Method | Endpoint | Description |
| - | - | - |
| `POST` | `/api/v1/messaging/calls/whatsapp` | Initiate a WhatsApp call |
| `POST` | `/api/v1/messaging/calls/whatsapp/action` | Manage a call (pre-accept/accept/reject/terminate) |
| `GET` | `/api/v1/messaging/calls/whatsapp/logs` | List call history |

## Initiate a WhatsApp call

```http theme={null}
POST https://api.vobiz.ai/api/v1/messaging/calls/whatsapp
```

Initiate an outbound WhatsApp voice call. Provide a WebRTC SDP offer.

<Note>
  This endpoint does **not** return an `sdp_answer`. The SDP answer from the recipient's device arrives asynchronously via the call webhook / WebSocket event once the call is answered.
</Note>

### Request body

| Field | Required | Description |
| - | - | - |
| `channel_id` | Yes | Channel (UUID) to call from |
| `to` | Yes | Recipient phone number (E.164, e.g. `+919876543210`) |
| `sdp_offer` | Yes | WebRTC SDP offer string |

<ParamField body="channel_id" type="string" required>
  Channel (UUID) to call from.
</ParamField>

<ParamField body="to" type="string" required>
  Recipient phone number in E.164 format, for example `+919876543210`.
</ParamField>

<ParamField body="sdp_offer" type="string" required>
  WebRTC SDP offer string.
</ParamField>

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/messaging/calls/whatsapp" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "channel_id": "3f1c9b7e-2d4a-4f6b-9c8e-0a1b2c3d4e5f",
    "to": "+919876543210",
    "sdp_offer": "v=0\r\no=- 0 0 IN IP4 0.0.0.0\r\n..."
  }'
```

```json 201 Created theme={null}
{
  "call_id": "d5e6f708-1920-4a3b-94c5-d6e7f8091022",
  "from": "+911140001234",
  "to": "+919876543210",
  "status": "initiated",
  "direction": "outbound"
}
```

## Manage call (actions)

```http theme={null}
POST https://api.vobiz.ai/api/v1/messaging/calls/whatsapp/action
```

Control an active or incoming call. Pass the `channel_id`, the `call_id`, and one of the four actions. For `accept` and `pre_accept`, include the WebRTC SDP answer in the `sdp` field.

### Request body

| Field | Required | Description |
| - | - | - |
| `channel_id` | Yes | Channel (UUID) the call belongs to |
| `call_id` | Yes | Call identifier |
| `action` | Yes | `pre_accept`, `accept`, `reject`, or `terminate` |
| `sdp` | Conditional | WebRTC SDP answer. Required for `accept` and `pre_accept` |

| Action | Description |
| - | - |
| `pre_accept` | Signal call preview before full accept (send SDP answer) |
| `accept` | Accept an incoming call (send SDP answer) |
| `reject` | Reject an incoming call |
| `terminate` | End an active connected call |

<CodeGroup>
  ```bash Accept an incoming call theme={null}
  curl -X POST \
    "https://api.vobiz.ai/api/v1/messaging/calls/whatsapp/action" \
    -H "X-Auth-ID: MA_XXXXXXXX" \
    -H "X-Auth-Token: {auth_token}" \
    -H "Content-Type: application/json" \
    -d '{
      "channel_id": "3f1c9b7e-2d4a-4f6b-9c8e-0a1b2c3d4e5f",
      "call_id": "d5e6f708-1920-4a3b-94c5-d6e7f8091022",
      "action": "accept",
      "sdp": "v=0\r\no=- 0 0 IN IP4 0.0.0.0\r\n..."
    }'
  ```

  ```bash Terminate a call theme={null}
  curl -X POST \
    "https://api.vobiz.ai/api/v1/messaging/calls/whatsapp/action" \
    -H "X-Auth-ID: MA_XXXXXXXX" \
    -H "X-Auth-Token: {auth_token}" \
    -H "Content-Type: application/json" \
    -d '{
      "channel_id": "3f1c9b7e-2d4a-4f6b-9c8e-0a1b2c3d4e5f",
      "call_id": "d5e6f708-1920-4a3b-94c5-d6e7f8091022",
      "action": "terminate"
    }'
  ```
</CodeGroup>

```json 200 OK theme={null}
{
  "call_id": "d5e6f708-1920-4a3b-94c5-d6e7f8091022",
  "action": "accept",
  "success": true
}
```

## List call logs

```http theme={null}
GET https://api.vobiz.ai/api/v1/messaging/calls/whatsapp/logs
```

Returns a paginated history of WhatsApp calls - inbound and outbound - with duration, outcome, and participant details. Filter with `direction` and `status`.

| Query param | Default | Description |
| - | - | - |
| `page` | `1` | Page number |
| `limit` | `25` | Page size |
| `direction` | - | `inbound` or `outbound` |
| `status` | - | Filter by call status |

```bash cURL theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/messaging/calls/whatsapp/logs?page=1&limit=25&direction=outbound&status=accepted" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}"
```

```json 200 OK theme={null}
{
  "items": [
    {
      "id": "e6f70819-2031-4b4c-95d6-e7f809102233",
      "account_id": "MA_XXXXXXXX",
      "channel_id": "3f1c9b7e-2d4a-4f6b-9c8e-0a1b2c3d4e5f",
      "meta_call_id": "wacid.HBgM...",
      "direction": "outbound",
      "from_number": "+911140001234",
      "to_number": "+919876543210",
      "status": "accepted",
      "call_type": "voice",
      "duration_seconds": 185,
      "started_at": "2026-03-25T14:00:00Z",
      "answered_at": "2026-03-25T14:00:04Z",
      "ended_at": "2026-03-25T14:03:05Z",
      "created_at": "2026-03-25T14:00:00Z",
      "updated_at": "2026-03-25T14:03:05Z"
    }
  ],
  "total": 12,
  "page": 1,
  "limit": 25,
  "has_more": false
}
```

## Call log object

| Field | Type | Description |
| - | - | - |
| `id` | UUID | Call log ID |
| `account_id` | string | Owning account (`MA_XXXXXXXX`) |
| `channel_id` | UUID | Channel the call belongs to |
| `meta_call_id` | string | Meta's call identifier |
| `direction` | string | `inbound` or `outbound` |
| `from_number` | string | Caller number (E.164) |
| `to_number` | string | Callee number (E.164) |
| `status` | string | `initiated`, `ringing`, `pre_accepted`, `accepted`, `rejected`, `terminated`, `failed`, or `missed` |
| `call_type` | string | Call type |
| `offer_sdp` | string | WebRTC SDP offer |
| `answer_sdp` | string | WebRTC SDP answer |
| `ice_candidates` | object | ICE candidate data |
| `started_at` | RFC3339 | Call start (UTC) |
| `answered_at` | RFC3339 | Call answered (UTC) |
| `ended_at` | RFC3339 | Call ended (UTC) |
| `duration_seconds` | int | Call duration in seconds |
| `hangup_cause` | string | Reason the call ended |
| `metadata` | object | Additional call metadata |
| `created_at` | RFC3339 | Creation timestamp (UTC) |
| `updated_at` | RFC3339 | Last update timestamp (UTC) |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.