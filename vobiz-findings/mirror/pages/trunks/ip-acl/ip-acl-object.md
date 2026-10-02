> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# The IP ACL Object

> Complete field reference for the Vobiz IP ACL object - covers ip_address, enabled flag, UUID, and ISO 8601 timestamps for SIP trunk IP allowlists.

The IP ACL object represents a whitelisted IPv4 address that can authenticate to a trunk without requiring credentials. Each IP ACL entry is associated with a trunk and contains the IP address along with optional metadata such as description and enabled status.

<Note>
  **IPv4 Only:** The `ip_address` field only accepts IPv4 addresses in standard dotted-decimal notation (e.g., 192.168.1.1). IPv6 addresses are not currently supported.

  **Public IPs:** Ensure you whitelist the public IP address, not private/internal IPs. For devices behind NAT, use the router's public IP address.
</Note>

## Attributes

| Field | Type | Description |
| - | - | - |
| `id` | string (UUID) | Unique identifier for the IP ACL entry. Automatically generated upon creation. |
| `account_id` | string | Account this IP ACL entry belongs to. |
| `ip_address` | string | IPv4 address or CIDR block in dotted-decimal notation (e.g., `192.168.1.0/24`). Required. Must be a valid IPv4 address or CIDR range. |
| `description` | string | Optional description with context about the IP address, such as "Office static IP" or "PBX server". |
| `enabled` | boolean | Whether the IP ACL entry is active and can be used for authentication. Default: `true`. |
| `created_at` | string (ISO 8601) | Timestamp when the IP ACL entry was created. Format: `YYYY-MM-DDTHH:mm:ssZ` (UTC). |
| `updated_at` | string (ISO 8601) | Timestamp of the last update to the IP ACL entry. Format: `YYYY-MM-DDTHH:mm:ssZ` (UTC). |

## Example

### IP ACL Object Response

A typical IP ACL object returned by the API:

```json IP ACL Object theme={null}
{
  "id": "aabbccdd-1234-5678-90ab-cdef12345678",
  "account_id": "",
  "ip_address": "192.168.1.0/24",
  "description": "Office IP",
  "enabled": true,
  "created_at": "2026-03-18T14:41:41Z",
  "updated_at": "2026-03-18T14:41:41Z"
}
```

<Info>
  **Best Practices:**

  * Only whitelist IP addresses you control and trust
  * Use descriptive descriptions to identify each IP's purpose
  * Regularly audit your IP ACL list and remove unused entries
  * For dynamic IPs, consider using credential authentication instead
  * Test connectivity after adding new IP addresses
  * Disable rather than delete entries when temporarily blocking access
</Info>

<Warning>
  **Finding Your Public IP:** To check your public IP address, run `curl https://api.ipify.org` from your command line or visit the URL in your browser.
</Warning>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.