> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Contacts API

> Create, update, tag, and delete WhatsApp contacts on Vobiz, or import thousands of contacts at once via CSV bulk upload for campaign targeting.

**Base URL:** `https://api.vobiz.ai/api/v1/messaging`

**Authentication:** every request requires `X-Auth-ID: MA_XXXXXXXX` and `X-Auth-Token: <token>` headers (a `Authorization: Bearer <JWT>` header is also accepted). Send `Content-Type: application/json` on requests with a body. Get your credentials from [console.vobiz.ai](https://console.vobiz.ai).

## Endpoints overview

| Method | Endpoint | Description |
| - | - | - |
| `GET` | `/api/v1/messaging/contacts` | List contacts (paginated) |
| `GET` | `/api/v1/messaging/contacts/{id}` | Get a single contact |
| `POST` | `/api/v1/messaging/contacts` | Create a new contact |
| `PUT` | `/api/v1/messaging/contacts/{id}` | Update a contact |
| `DELETE` | `/api/v1/messaging/contacts/{id}` | Delete a contact |
| `POST` | `/api/v1/messaging/contacts/import` | Bulk import from CSV |

## List contacts

```http theme={null}
GET https://api.vobiz.ai/api/v1/messaging/contacts
```

Returns a paginated list of contacts. Filter by name/phone with `search`, or filter by `tag`.

<ParamField query="page" type="integer" default="1">
  Page number.
</ParamField>

<ParamField query="limit" type="integer" default="25">
  Records per page.
</ParamField>

<ParamField query="search" type="string">
  Search by name or phone number.
</ParamField>

<ParamField query="tag" type="string">
  Filter by tag name.
</ParamField>

```bash cURL theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/messaging/contacts?page=1&limit=25&search=Rahul&tag=vip" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}"
```

```json 200 OK theme={null}
{
  "items": [
    {
      "id": "9b8a7c6d-5e4f-4a3b-2c1d-0e9f8a7b6c5d",
      "account_id": "MA_XXXXXXXX",
      "phone_number": "+919876543210",
      "name": "Rahul Sharma",
      "tags": ["vip"],
      "custom_attributes": { "company": "Acme" },
      "last_active_at": "2026-03-17T14:22:00Z",
      "created_at": "2026-03-01T10:00:00Z",
      "updated_at": "2026-03-01T10:00:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "limit": 25,
  "has_more": false
}
```

## Get contact

```http theme={null}
GET https://api.vobiz.ai/api/v1/messaging/contacts/{id}
```

Returns the full profile for a single contact by ID.

```bash cURL theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/messaging/contacts/9b8a7c6d-5e4f-4a3b-2c1d-0e9f8a7b6c5d" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}"
```

## Create contact

```http theme={null}
POST https://api.vobiz.ai/api/v1/messaging/contacts
```

Create a single contact. Attach `tags` and `custom_attributes` for filtering and campaign targeting. Returns `201 Created`.

<ParamField body="phone_number" type="string" required>
  Phone number in E.164 format (e.g. `+919876543210`).
</ParamField>

<ParamField body="name" type="string" required>
  Contact name.
</ParamField>

<ParamField body="tags" type="string[]">
  List of tag strings.
</ParamField>

<ParamField body="custom_attributes" type="object">
  Arbitrary key/value metadata for the contact.
</ParamField>

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/messaging/contacts" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+919876543210",
    "name": "Rahul Sharma",
    "tags": ["vip"],
    "custom_attributes": { "company": "Acme" }
  }'
```

## Update contact

```http theme={null}
PUT https://api.vobiz.ai/api/v1/messaging/contacts/{id}
```

Update a contact's name, tags, or custom attributes. All fields are optional; send only what you want to change. Returns `200 OK`.

<ParamField body="name" type="string">
  Updated contact name.
</ParamField>

<ParamField body="tags" type="string[]">
  Updated list of tag strings.
</ParamField>

<ParamField body="custom_attributes" type="object">
  Updated key/value metadata.
</ParamField>

```bash cURL theme={null}
curl -X PUT \
  "https://api.vobiz.ai/api/v1/messaging/contacts/9b8a7c6d-5e4f-4a3b-2c1d-0e9f8a7b6c5d" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Rahul Kumar",
    "tags": ["vip", "premium"]
  }'
```

## Delete contact

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/messaging/contacts/{id}
```

Permanently delete a contact from your account. Returns `204 No Content`.

```bash cURL theme={null}
curl -X DELETE \
  "https://api.vobiz.ai/api/v1/messaging/contacts/9b8a7c6d-5e4f-4a3b-2c1d-0e9f8a7b6c5d" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}"
```

## Import contacts (CSV)

```http theme={null}
POST https://api.vobiz.ai/api/v1/messaging/contacts/import
```

Bulk-import contacts from a CSV file using `multipart/form-data`. Send the file under the form field named `file`. The CSV must include `phone_number` and `name` columns; `tags` (comma-separated) is optional. Returns `200 OK` with a summary.

**CSV format:**

```csv theme={null}
phone_number,name,tags
+919876543210,Rahul Sharma,"vip,enterprise"
+919123456789,Priya Nair,"new"
```

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/messaging/contacts/import" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}" \
  -F "file=@/path/to/contacts.csv"
```

```json 200 OK theme={null}
{
  "total": 2,
  "created": 1,
  "updated": 1,
  "failed": 0,
  "errors": []
}
```

When some rows fail, `errors` lists each one:

```json 200 OK (with errors) theme={null}
{
  "total": 3,
  "created": 1,
  "updated": 1,
  "failed": 1,
  "errors": [
    {
      "row": 3,
      "phone_number": "98765",
      "reason": "invalid phone_number: must be E.164 format"
    }
  ]
}
```

<Note>
  Do not set `Content-Type` manually when using `-F` - curl sets the correct `multipart/form-data` boundary automatically.
</Note>

## Contact object

<ResponseField name="id" type="string">
  Unique contact identifier (UUID).
</ResponseField>

<ResponseField name="account_id" type="string">
  Your Vobiz account ID (`MA_XXXXXXXX`).
</ResponseField>

<ResponseField name="phone_number" type="string">
  Phone number in E.164 format.
</ResponseField>

<ResponseField name="name" type="string">
  Contact name.
</ResponseField>

<ResponseField name="tags" type="string[]">
  List of tags assigned to the contact.
</ResponseField>

<ResponseField name="custom_attributes" type="object">
  Arbitrary key/value metadata.
</ResponseField>

<ResponseField name="last_active_at" type="string">
  Timestamp of the contact's most recent activity (RFC3339 UTC). May be omitted if the contact has had no activity.
</ResponseField>

<ResponseField name="created_at" type="string">
  Creation timestamp (RFC3339 UTC).
</ResponseField>

<ResponseField name="updated_at" type="string">
  Last update timestamp (RFC3339 UTC).
</ResponseField>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.