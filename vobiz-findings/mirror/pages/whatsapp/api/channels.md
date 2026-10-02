> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Channels API

> Create, update, and remove WhatsApp Business channels on Vobiz - connect your WABA, manage display names, and rotate access tokens via REST API.

**Base URL:** `https://api.vobiz.ai/api/v1/messaging`

**Authentication:** every request requires `X-Auth-ID: MA_XXXXXXXX` and `X-Auth-Token: <token>` headers (a `Authorization: Bearer <JWT>` header is also accepted). Send `Content-Type: application/json` on requests with a body. Get your credentials from [console.vobiz.ai](https://console.vobiz.ai).

## List WhatsApp channels

```http theme={null}
GET https://api.vobiz.ai/api/v1/messaging/channels/whatsapp
```

Returns all WhatsApp channels connected to your Vobiz account.

```bash cURL theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/messaging/channels/whatsapp" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}"
```

```json 200 OK theme={null}
{
  "items": [
    {
      "id": "2f8892e1-59b7-40a2-b518-e7a7c31a754d",
      "account_id": "MA_XXXXXXXX",
      "waba_id": "1911116896216319",
      "phone_number_id": "974161339121558",
      "phone_number": "+15551234567",
      "number_onboarding_mode": "bring_your_own",
      "number_provider": "meta_direct",
      "number_order_id": null,
      "verification_status": "verified",
      "display_name": "My Business",
      "business_profile": "Retail and support line",
      "status": "active",
      "created_at": "2026-03-01T10:00:00Z",
      "updated_at": "2026-03-01T10:00:00Z"
    }
  ]
}
```

## Create WhatsApp channel

```http theme={null}
POST https://api.vobiz.ai/api/v1/messaging/channels/whatsapp
```

Connect a new WhatsApp Business number using your WABA credentials from Meta Business Manager. Returns `201 Created` with the new channel.

<ParamField body="waba_id" type="string" required>
  WhatsApp Business Account ID from Meta.
</ParamField>

<ParamField body="phone_number_id" type="string">
  Phone Number ID from Meta. Required unless `number_onboarding_mode` is `buy_from_vobiz`.
</ParamField>

<ParamField body="phone_number" type="string" required>
  Phone number in E.164 format (e.g. `+15551234567`).
</ParamField>

<ParamField body="number_onboarding_mode" type="string" required>
  One of `buy_from_vobiz`, `bring_your_own`, or `embedded_signup`.
</ParamField>

<ParamField body="number_provider" type="string" required>
  Number provider, e.g. `meta_direct`.
</ParamField>

<ParamField body="number_order_id" type="string">
  UUID of a completed Vobiz number order. Optional.
</ParamField>

<ParamField body="access_token" type="string" required>
  Meta system-user access token (starts with `EAA…`). Stored securely and never returned in responses.
</ParamField>

<ParamField body="display_name" type="string" required>
  Business display name shown to your customers.
</ParamField>

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/messaging/channels/whatsapp" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "waba_id": "1911116896216319",
    "phone_number_id": "974161339121558",
    "phone_number": "+15551234567",
    "number_onboarding_mode": "bring_your_own",
    "number_provider": "meta_direct",
    "access_token": "EAAx...",
    "display_name": "My Business"
  }'
```

```json 201 Created theme={null}
{
  "id": "2f8892e1-59b7-40a2-b518-e7a7c31a754d",
  "account_id": "MA_XXXXXXXX",
  "waba_id": "1911116896216319",
  "phone_number_id": "974161339121558",
  "phone_number": "+15551234567",
  "number_onboarding_mode": "bring_your_own",
  "number_provider": "meta_direct",
  "number_order_id": null,
  "verification_status": "pending",
  "display_name": "My Business",
  "business_profile": "",
  "status": "active",
  "created_at": "2026-03-01T10:00:00Z",
  "updated_at": "2026-03-01T10:00:00Z"
}
```

## Embedded signup

```http theme={null}
POST https://api.vobiz.ai/api/v1/messaging/channels/whatsapp/embedded-signup
```

Complete channel creation after the Meta Embedded Signup OAuth flow. Pass the authorization code returned by Meta. Returns `201 Created`.

<ParamField body="code" type="string" required>
  OAuth authorization code returned by Meta Embedded Signup.
</ParamField>

<ParamField body="waba_id" type="string" required>
  WhatsApp Business Account ID from Meta.
</ParamField>

<ParamField body="phone_number_id" type="string">
  Phone Number ID from Meta.
</ParamField>

<ParamField body="phone_number" type="string">
  Phone number in E.164 format.
</ParamField>

<ParamField body="number_provider" type="string">
  Number provider, e.g. `meta_direct`.
</ParamField>

<ParamField body="number_onboarding_mode" type="string">
  Onboarding mode, typically `embedded_signup`.
</ParamField>

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/messaging/channels/whatsapp/embedded-signup" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "code": "AQB...",
    "waba_id": "1911116896216319",
    "phone_number_id": "974161339121558",
    "phone_number": "+15551234567",
    "number_provider": "meta_direct",
    "number_onboarding_mode": "embedded_signup"
  }'
```

```json 201 Created theme={null}
{
  "channel": {
    "id": "2f8892e1-59b7-40a2-b518-e7a7c31a754d",
    "account_id": "MA_XXXXXXXX",
    "waba_id": "1911116896216319",
    "phone_number_id": "974161339121558",
    "phone_number": "+15551234567",
    "number_onboarding_mode": "embedded_signup",
    "number_provider": "meta_direct",
    "number_order_id": null,
    "verification_status": "pending",
    "display_name": "My Business",
    "business_profile": "",
    "status": "active",
    "created_at": "2026-03-01T10:00:00Z",
    "updated_at": "2026-03-01T10:00:00Z"
  },
  "phone_number": "+15551234567",
  "display_name": "My Business"
}
```

## Update channel

```http theme={null}
PUT https://api.vobiz.ai/api/v1/messaging/channels/whatsapp/{id}
```

Update an existing channel's display name or refresh its Meta access token when the previous token expires. Both fields are optional; send only what you want to change. Returns `200 OK` with the updated channel.

<ParamField body="access_token" type="string">
  New Meta system-user access token (starts with `EAA…`).
</ParamField>

<ParamField body="display_name" type="string">
  Updated business display name.
</ParamField>

```bash cURL theme={null}
curl -X PUT \
  "https://api.vobiz.ai/api/v1/messaging/channels/whatsapp/2f8892e1-59b7-40a2-b518-e7a7c31a754d" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "display_name": "Updated Business Name",
    "access_token": "EAAx_new..."
  }'
```

## Delete channel

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/messaging/channels/whatsapp/{id}
```

Disconnect and remove a WhatsApp channel from Vobiz. Does **not** delete the WABA or phone number from Meta. Returns `204 No Content`.

<Warning>
  Deleting a channel stops all messaging for that number. Active conversations will be closed.
</Warning>

```bash cURL theme={null}
curl -X DELETE \
  "https://api.vobiz.ai/api/v1/messaging/channels/whatsapp/2f8892e1-59b7-40a2-b518-e7a7c31a754d" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}"
```

## Channel object

<ResponseField name="id" type="string">
  Unique channel identifier (UUID).
</ResponseField>

<ResponseField name="account_id" type="string">
  Your Vobiz account ID (`MA_XXXXXXXX`).
</ResponseField>

<ResponseField name="waba_id" type="string">
  WhatsApp Business Account ID from Meta.
</ResponseField>

<ResponseField name="phone_number_id" type="string">
  Phone Number ID from Meta.
</ResponseField>

<ResponseField name="phone_number" type="string">
  Connected phone number in E.164 format.
</ResponseField>

<ResponseField name="number_onboarding_mode" type="string">
  How the number was onboarded: `buy_from_vobiz`, `bring_your_own`, or `embedded_signup`.
</ResponseField>

<ResponseField name="number_provider" type="string">
  Number provider, e.g. `meta_direct`.
</ResponseField>

<ResponseField name="number_order_id" type="string">
  UUID of the associated Vobiz number order, if any. May be `null`.
</ResponseField>

<ResponseField name="verification_status" type="string">
  Meta verification state: `verified`, `pending`, or `rejected`.
</ResponseField>

<ResponseField name="display_name" type="string">
  Business display name shown to customers.
</ResponseField>

<ResponseField name="business_profile" type="string">
  Business profile description.
</ResponseField>

<ResponseField name="status" type="string">
  Channel status: `active`, `inactive`, or `suspended`.
</ResponseField>

<ResponseField name="created_at" type="string">
  Creation timestamp (RFC3339 UTC).
</ResponseField>

<ResponseField name="updated_at" type="string">
  Last update timestamp (RFC3339 UTC).
</ResponseField>

<Note>
  The `access_token` is stored securely and is **never** returned in any API response.
</Note>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.