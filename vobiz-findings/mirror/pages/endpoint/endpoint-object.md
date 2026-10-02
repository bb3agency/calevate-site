> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# The Endpoint Object

> Schema reference for the Vobiz SIP Endpoint object: username, SIP URI, registration status, application binding, call permissions, and live sip_contact fields.

The Endpoint object represents a SIP endpoint in your account. Each endpoint has a unique identifier and can be registered on SIP clients to make and receive calls. The object structure varies slightly depending on whether the endpoint is currently registered.

<Note>
  **Registration Status:** When an endpoint is registered on a SIP client, additional fields like `sip_contact`, `sip_expires`, and `sip_user_agent` are included in the response.
</Note>

## Attributes

### Core Attributes

| Field | Type | Description |
| - | - | - |
| `endpoint_id` | string | Unique identifier for the endpoint. All endpoint API operations are performed using this identifier. |
| `username` | string | SIP username (unique per account). Only alphanumeric characters are accepted. |
| `alias` | string | Friendly name for the endpoint. Accepts alphabets (uppercase and lowercase), numbers (0-9), hyphen (-), and underscore (\_) only. |
| `sip_uri` | string | Full SIP URI of the endpoint. External users can call this endpoint on this SIP URI. Format: `sip:username@registrar.vobiz.ai` |
| `sip_registered` | string | Registration status as a **string** (`"true"` or `"false"`), not a boolean. `"true"` when a SIP client is actively registered, `"false"` otherwise. Compare against the string value. |
| `application` | object | Associated application details for call routing. Contains `app_id`, `app_name`, `answer_url`, and `answer_method`. `null` if no application is attached. |
| `resource_uri` | string | API resource URI for this endpoint. |
| `sub_account` | string | Sub-account `auth_id` if endpoint belongs to a sub-account. `null` for main account. |
| `created_at` | string (ISO 8601) | Creation timestamp. |
| `updated_at` | string (ISO 8601) | Last update timestamp. |

### Permission Attributes

| Field | Type | Description |
| - | - | - |
| `allow_voice` | boolean | Voice calls enabled (default: `true`). |
| `allow_message` | boolean | Messaging enabled (default: `true`). |
| `allow_video` | boolean | Video calls enabled (default: `false`). |
| `allow_same_domain` | boolean | Calls to same domain allowed (default: `true`). |
| `allow_other_domains` | boolean | Calls to other domains allowed (default: `false`). |
| `allow_phones` | boolean | Calls to phone numbers allowed (default: `true`). |
| `allow_apps` | boolean | Calls to apps allowed (default: `true`). |

### Registration Attributes (when registered)

| Field | Type | Description |
| - | - | - |
| `sip_contact` | string | SIP contact address of the registered client. Example: `192.168.1.100:5060` |
| `sip_expires` | string (ISO 8601) | Timestamp when the SIP registration expires. |
| `sip_user_agent` | string | User agent string of the SIP client. Example: `"Zoiper v5.4.5"` |
| `sip_registration` | object | Detailed registration information (retrieve endpoint only). Contains `contact`, `expires`, `user_agent`, `received`, and `path` fields. |

## Examples

### Unregistered Endpoint

Response when the endpoint is not currently registered on any SIP client:

```json Unregistered Endpoint Response theme={null}
{
  "api_id": "550e8400-e29b-41d4-a716-446655440000",
  "endpoint_id": "87654322",
  "username": "jane_smith",
  "alias": "Jane's Mobile",
  "sip_uri": "sip:jane_smith@registrar.vobiz.ai",
  "sip_registered": "false",
  "sip_contact": null,
  "sip_expires": null,
  "sip_user_agent": null,
  "application": null,
  "allow_voice": true,
  "allow_message": true,
  "allow_video": true,
  "allow_same_domain": true,
  "allow_other_domains": false,
  "allow_phones": true,
  "allow_apps": true,
  "sub_account": null,
  "resource_uri": "/v1/Account/{auth_id}/Endpoint/87654322/",
  "created_at": "2025-10-26T14:20:00Z",
  "updated_at": "2025-10-26T14:20:00Z"
}
```

### Registered Endpoint

Response when the endpoint is actively registered on a SIP client:

```json Registered Endpoint Response theme={null}
{
  "api_id": "550e8400-e29b-41d4-a716-446655440000",
  "endpoint_id": "87654321",
  "username": "john_doe",
  "alias": "John's Desktop Phone",
  "sip_uri": "sip:john_doe@registrar.vobiz.ai",
  "sip_registered": "true",
  "sip_contact": "192.168.1.100:5060",
  "sip_expires": "2025-10-28T11:30:00Z",
  "sip_user_agent": "Zoiper v5.4.5",
  "application": {
    "app_id": "12345678",
    "app_name": "Customer Service App",
    "answer_url": "https://example.com/answer",
    "answer_method": "POST"
  },
  "allow_voice": true,
  "allow_message": true,
  "allow_video": false,
  "allow_same_domain": true,
  "allow_other_domains": false,
  "allow_phones": true,
  "allow_apps": true,
  "sub_account": null,
  "resource_uri": "/v1/Account/{auth_id}/Endpoint/87654321/",
  "created_at": "2025-10-27T10:30:00Z",
  "updated_at": "2025-10-28T09:15:00Z"
}
```

<Info>
  The `password` field is write-only and never returned in API responses. Registration timestamps (`sip_expires`, `created_at`, `updated_at`) are in ISO 8601 format (UTC).
</Info>

## Registration and WebRTC

An endpoint is a SIP account. A client comes online by registering with the Vobiz SIP registrar.

| Client | Registrar / server | Transport | Authentication |
| - | - | - | - |
| Softphone or IP desk phone | `registrar.vobiz.ai` | UDP, TCP, or TLS | Endpoint `username` and `password` |
| Custom WebRTC SIP client | `registrar.vobiz.ai` | SIP over WebSocket | Endpoint `username` and `password` |

The SIP URI follows `sip:username@registrar.vobiz.ai`. SIP registration does not use your account Auth ID and Auth Token, and it does not require a separate JWT. The hosted [WebRTC Playground](/docs/integrations/webrtc-application-setup) is different: it uses your account Auth ID and Auth Token instead of SIP endpoint credentials.

Once registered, `sip_registered` flips to `"true"` and the live `sip_contact`, `sip_expires`, and `sip_user_agent` fields populate. When the registration lapses (no refresh before `sip_expires`) the endpoint goes back to `"false"` and those fields clear.

<Warning>
  Changing the endpoint `password` invalidates active registrations. Every client must re-register with the new credential or it drops off. The `username` is immutable - to rename, delete and recreate the endpoint.
</Warning>

## Locked vs editable fields

| Editable via [update](/docs/endpoint/update-endpoint) | Locked after creation |
| - | - |
| `password`, `alias`, `application`, `allow_voice`, `allow_message`, `allow_video` | `username`, `endpoint_id`, `domain`, `allow_same_domain`, `allow_other_domains`, `allow_phones`, `allow_apps` |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.