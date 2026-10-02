> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# The Credential Object

> Explore the Vobiz SIP Credential object schema - credential_id, username, write-only password, enabled flag, trunk association, and ISO 8601 timestamps.

The Credential object represents a set of SIP authentication credentials (username and password) that can be used to authenticate calls on a specific trunk. Multiple credentials can exist for a single trunk, enabling different users, devices, or applications to connect with unique authentication details.

<Note>
  **Password Security:** The `password` field is write-only and is never returned in API responses. Once created, passwords cannot be retrieved - only updated.

  **Username Immutability:** The `username` cannot be changed after credential creation. To use a different username, create a new credential and delete the old one.
</Note>

## Attributes

| Field | Type | Description |
| - | - | - |
| `id` | string (UUID) | Unique identifier for the credential. Automatically generated upon creation. |
| `account_id` | string | Account (`auth_id`) that owns this credential. Credentials are account-scoped, not bound to a single trunk. |
| `username` | string | SIP username for authentication. Required. Must be unique within the account. Cannot be changed after creation. |
| `password` | string | SIP password for authentication. Required (minimum 8 characters). Write-only - returned as `<redacted>`, never the real value. |
| `realm` | string | SIP authentication realm in the form `{account_id}.sip.vobiz.ai`. Your SIP client must present this realm with the username and password during digest authentication. |
| `enabled` | boolean | Whether the credential is active and can be used for authentication. Default: `true`. |
| `created_at` | string (ISO 8601) | Timestamp when the credential was created. Format: `YYYY-MM-DDTHH:mm:ssZ` (UTC). |
| `updated_at` | string (ISO 8601) | Timestamp of the last update to the credential. Format: `YYYY-MM-DDTHH:mm:ssZ` (UTC). |

## Example

### Credential Object Response

A typical credential object returned by the API (password is not included):

```json Credential Object theme={null}
{
  "id": "aabbccdd-1234-5678-90ab-cdef12345678",
  "account_id": "MA_XXXXXXXX",
  "username": "sipuser_demo",
  "password": "<redacted>",
  "realm": "MA_XXXXXXXX.sip.vobiz.ai",
  "enabled": true,
  "created_at": "2026-04-22T08:51:47.813889Z",
  "updated_at": "2026-04-22T08:51:47.813889Z"
}
```

<Info>
  **Security Best Practices:**

  * Use strong passwords with at least 12 characters
  * Include uppercase, lowercase, numbers, and special characters
  * Rotate credentials regularly (quarterly recommended)
  * Disable unused credentials immediately rather than deleting them
  * Use descriptive usernames that identify the device or user
</Info>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.