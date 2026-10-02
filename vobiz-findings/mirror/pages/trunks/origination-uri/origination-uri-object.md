> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# The Origination URI Object

> Complete field reference for the Vobiz Origination URI object - SIP URI format, priority, weight, transport protocol, enabled flag, and ISO 8601 timestamps.

The Origination URI object represents a SIP endpoint destination for outbound calls. Each URI specifies where your trunk routes outbound traffic, along with priority and weight settings that control failover behavior and load distribution.

<Note>
  **SIP URI Format:** Origination URIs must follow the standard SIP URI format: `sip:user@host:port` or `sip:host:port`

  **Examples:** `sip:provider@sip.example.com:5060`, `sip:192.168.1.100:5060`
</Note>

## Attributes

| Field | Type | Description |
| - | - | - |
| `id` | string (UUID) | Unique identifier for the origination URI. Automatically generated upon creation. |
| `account_id` | string | Account identifier associated with this origination URI. |
| `uri` | string | SIP URI destination. Required. Must follow the format `sip:user@host:port` or `sip:host:port` (e.g., `sip:provider@sip.example.com:5060`). |
| `priority` | integer | Routing priority (lower = higher priority). URIs with priority `1` are tried first; priority `2` serves as failover. Default: `1`. |
| `weight` | integer | Load balancing weight among URIs with the same priority. Higher values receive more traffic. Default: `10`. |
| `enabled` | boolean | Whether the URI is active and can be used for routing calls. Default: `true`. |
| `transport` | string | SIP transport protocol used to reach the URI. Common values: `udp`, `tcp`, `tls`. |
| `description` | string | Free-form description for the origination URI. May be empty. |
| `created_at` | string (ISO 8601) | Timestamp when the origination URI was created. Format: `YYYY-MM-DDTHH:mm:ssZ` (UTC). |
| `updated_at` | string (ISO 8601) | Timestamp of the last update to the origination URI. Format: `YYYY-MM-DDTHH:mm:ssZ` (UTC). |

## Example

### Origination URI Object Response

A typical origination URI object returned by the API:

```json Origination URI Object theme={null}
{
  "id": "aabbccdd-1234-5678-90ab-cdef12345678",
  "account_id": "",
  "uri": "sip:sbc1.example.com:5060",
  "priority": 1,
  "weight": 10,
  "enabled": true,
  "transport": "udp",
  "description": "",
  "created_at": "2026-05-10T10:45:30Z",
  "updated_at": "2026-05-10T10:45:30Z"
}
```

<Info>
  **Priority-Based Routing:** The system tries URIs in order of priority (lowest number first). If all priority 1 URIs fail, it attempts priority 2, and so on.

  **Weight-Based Load Balancing:** Among URIs with the same priority, traffic is distributed proportionally based on weight. A URI with weight 20 receives twice the traffic of one with weight 10.

  **Example:** With two URIs at priority 1 (weights 10 and 20), the first receives \~33% of traffic and the second receives \~67%.
</Info>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.