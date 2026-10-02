> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# The Trunk Object

> Explore the Vobiz SIP Trunk object schema - SIP domain, auth mode, credentials, IP ACLs, origination URIs, rate limits, and all fields returned by the API.

The Trunk object represents a SIP trunking connection in your account. A trunk provides the foundation for voice communication by managing authentication, rate limiting, and routing configuration. Each trunk can have multiple credentials, IP access control lists, and origination URIs to support various use cases.

<Note>
  **Auto-Generated SIP Domain:** When a trunk is created, Vobiz automatically generates a unique SIP domain in the format: `trunkId.sip.vobiz.ai`. This domain is used for inbound call routing to your trunk.
</Note>

## Attributes

| Field | Type | Description |
| - | - | - |
| `trunk_id` | string (UUID) | Unique identifier for the trunk. Automatically generated upon creation. |
| `account_id` | string | Account identifier (`auth_id`) that owns this trunk. |
| `name` | string | Descriptive name for the trunk. Required. Maximum 255 characters. |
| `trunk_domain` | string | Auto-generated SIP domain in the form `<uuid>.sip.vobiz.ai`. |
| `trunk_status` | string | Status of the trunk. Common values: `active`, `inactive`. |
| `secure` | boolean | Whether the trunk uses TLS/SRTP. Default: `false`. |
| `trunk_direction` | string | Direction of calls. One of `inbound`, `outbound`, `both`. |
| `concurrent_calls_limit` | integer | Maximum number of simultaneous calls allowed. Default: `10`. |
| `cps_limit` | integer | Calls-per-second rate limit to prevent flooding. Default: `2`. |
| `description` | string | Optional description with additional context about the trunk's purpose or configuration. |
| `transport` | string | SIP transport protocol. One of `udp`, `tcp`. |
| `recording` | boolean | Whether call recording is enabled on the trunk. |
| `enable_transcription` | boolean | Whether call transcription is enabled. |
| `pii_redaction` | boolean | Whether PII redaction is applied to transcripts. |
| `webhook_method` | string | HTTP method used for trunk webhooks. e.g., `POST`. |
| `recording_webhook_enabled` | boolean | Whether the recording webhook is enabled. |
| `credential_uuid` | string (UUID) | UUID of the credential attached to the trunk (outbound trunks). |
| `primary_uri_uuid` | string (UUID) | UUID of the primary origination URI (inbound trunks). |
| `inbound_destination` | string | Destination for inbound call routing (inbound trunks). |
| `created_at` | string (ISO 8601) | Timestamp when the trunk was created. Format: `YYYY-MM-DDTHH:mm:ssZ` (UTC). |
| `updated_at` | string (ISO 8601) | Timestamp of the last update to the trunk. Format: `YYYY-MM-DDTHH:mm:ssZ` (UTC). |

## Example

A typical trunk object returned by the API:

```json Trunk Object theme={null}
{
  "trunk_id": "aabbccdd-1234-5678-90ab-cdef12345678",
  "account_id": "MA_XXXXXXXX",
  "name": "Acme Production Trunk",
  "trunk_domain": "aabbccdd-1234-5678-90ab-cdef12345678.sip.vobiz.ai",
  "trunk_status": "active",
  "secure": false,
  "trunk_direction": "both",
  "concurrent_calls_limit": 10,
  "cps_limit": 2,
  "description": "",
  "transport": "udp",
  "recording": false,
  "enable_transcription": false,
  "pii_redaction": false,
  "webhook_method": "POST",
  "recording_webhook_enabled": false,
  "created_at": "2026-05-12T05:11:52.054462Z",
  "updated_at": "2026-05-12T05:11:52.054462Z"
}
```

<Info>
  **Rate Limiting:** The `concurrent_calls_limit` and `cps_limit` protect your trunk from overload and help manage costs.

  **Timestamps:** All timestamps are in UTC timezone following ISO 8601 format.
</Info>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.