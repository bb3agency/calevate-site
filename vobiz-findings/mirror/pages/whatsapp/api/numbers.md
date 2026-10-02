> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Numbers API

> Search and purchase WhatsApp-capable numbers on Vobiz, or verify and connect an existing number via BYON - OTP-based ownership verification included.

**Base URL:** `https://api.vobiz.ai/api/v1/messaging`

**Authentication:** every request requires `X-Auth-ID: MA_XXXXXXXX` and `X-Auth-Token: <token>` headers (a `Authorization: Bearer <JWT>` header is also accepted). Send `Content-Type: application/json` on requests with a body. Get your credentials from [console.vobiz.ai](https://console.vobiz.ai).

## BYON verification flow

If you already have a WhatsApp Business number, the BYON (Bring Your Own Number) flow verifies ownership via OTP before connecting it to Vobiz.

<Steps>
  <Step title="Request OTP">
    Enter your phone number and select `sms` or `voice` verification with the [verify](#verify-byon-step-1) endpoint.
  </Step>

  <Step title="Confirm OTP">
    Receive the OTP code on your number and submit it to the [confirm](#confirm-byon-verification-step-2) endpoint.
  </Step>

  <Step title="Connect">
    Once verified, connect the number with [Create Channel](/docs/whatsapp/api/channels#create-whatsapp-channel).
  </Step>
</Steps>

## List available numbers

```http theme={null}
GET https://api.vobiz.ai/api/v1/messaging/numbers/whatsapp/availability
```

Search for WhatsApp-capable phone numbers available for purchase.

<ParamField query="country" type="string" required>
  ISO country code (e.g. `IN`, `US`).
</ParamField>

<ParamField query="region" type="string">
  State/region filter.
</ParamField>

```bash cURL theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/messaging/numbers/whatsapp/availability?country=IN&region=MH" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}"
```

```json 200 OK theme={null}
{
  "items": [
    {
      "e164": "+919876543210",
      "country": "IN",
      "region": "MH",
      "setup_fee": 500,
      "monthly_fee": 250,
      "currency": "INR"
    }
  ]
}
```

## Create number order

```http theme={null}
POST https://api.vobiz.ai/api/v1/messaging/numbers/whatsapp/orders
```

Purchase a new WhatsApp-capable phone number. After the order is fulfilled, use [Create Channel](/docs/whatsapp/api/channels#create-whatsapp-channel) to connect it to your WABA. Returns `201 Created`.

<ParamField body="country_code" type="string" required>
  ISO country code (e.g. `IN`).
</ParamField>

<ParamField body="region" type="string" required>
  State/region for the number.
</ParamField>

<ParamField body="number_type" type="string" required>
  Number type. Currently `local`.
</ParamField>

<ParamField body="preferred_number" type="string">
  Preferred number in E.164 format. Optional.
</ParamField>

<ParamField body="currency" type="string" required>
  Billing currency: `INR` or `USD`.
</ParamField>

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/messaging/numbers/whatsapp/orders" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "country_code": "IN",
    "region": "MH",
    "number_type": "local",
    "preferred_number": "+919876543210",
    "currency": "INR"
  }'
```

```json 201 Created theme={null}
{
  "id": "b3d1c4a2-5f6e-4a8b-9c0d-1e2f3a4b5c6d",
  "account_id": "MA_XXXXXXXX",
  "country_code": "IN",
  "region": "MH",
  "number_type": "local",
  "selected_phone_number": "+919876543210",
  "provider_order_id": "ord_meta_8841",
  "provider_name": "meta_direct",
  "status": "pending",
  "monthly_cost": 250,
  "setup_cost": 500,
  "currency": "INR",
  "failure_reason": null,
  "created_at": "2026-03-01T10:00:00Z",
  "updated_at": "2026-03-01T10:00:00Z"
}
```

### Number order object

<ResponseField name="id" type="string">
  Unique order identifier (UUID).
</ResponseField>

<ResponseField name="account_id" type="string">
  Your Vobiz account ID (`MA_XXXXXXXX`).
</ResponseField>

<ResponseField name="country_code" type="string">
  ISO country code.
</ResponseField>

<ResponseField name="region" type="string">
  State/region for the number.
</ResponseField>

<ResponseField name="number_type" type="string">
  Number type, e.g. `local`.
</ResponseField>

<ResponseField name="selected_phone_number" type="string">
  Allocated phone number in E.164 format.
</ResponseField>

<ResponseField name="provider_order_id" type="string">
  Upstream provider's order identifier.
</ResponseField>

<ResponseField name="provider_name" type="string">
  Upstream provider name.
</ResponseField>

<ResponseField name="status" type="string">
  Order status: `pending`, `completed`, `failed`, or `cancelled`.
</ResponseField>

<ResponseField name="monthly_cost" type="number">
  Recurring monthly cost.
</ResponseField>

<ResponseField name="setup_cost" type="number">
  One-time setup cost.
</ResponseField>

<ResponseField name="currency" type="string">
  Billing currency.
</ResponseField>

<ResponseField name="failure_reason" type="string">
  Reason the order failed, if `status` is `failed`. Otherwise `null`.
</ResponseField>

<ResponseField name="created_at" type="string">
  Creation timestamp (RFC3339 UTC).
</ResponseField>

<ResponseField name="updated_at" type="string">
  Last update timestamp (RFC3339 UTC).
</ResponseField>

## Verify BYON - step 1

```http theme={null}
POST https://api.vobiz.ai/api/v1/messaging/numbers/whatsapp/bring-your-own/verify
```

Initiate OTP verification for a number you already own. Choose `sms` or `voice` as the delivery method. Returns `200 OK`.

<ParamField body="phone_number" type="string" required>
  Phone number to verify, in E.164 format.
</ParamField>

<ParamField body="verification_method" type="string" required>
  OTP delivery method: `sms` or `voice`.
</ParamField>

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/messaging/numbers/whatsapp/bring-your-own/verify" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+919876543210",
    "verification_method": "sms"
  }'
```

```json 200 OK theme={null}
{
  "id": "a1c2e3f4-5678-49ab-bcde-f01234567890",
  "phone_number": "+919876543210",
  "status": "pending",
  "expires_at": "2026-03-01T10:10:00Z"
}
```

## Confirm BYON verification - step 2

```http theme={null}
POST https://api.vobiz.ai/api/v1/messaging/numbers/whatsapp/bring-your-own/confirm
```

Submit the OTP received in step 1 to complete verification. On success, the number is confirmed and ready to connect via [Create Channel](/docs/whatsapp/api/channels#create-whatsapp-channel). Returns `200 OK`.

<ParamField body="phone_number" type="string" required>
  Phone number being verified, in E.164 format.
</ParamField>

<ParamField body="otp_code" type="string" required>
  The OTP code received in step 1.
</ParamField>

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/messaging/numbers/whatsapp/bring-your-own/confirm" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: {auth_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+919876543210",
    "otp_code": "123456"
  }'
```

```json 200 OK theme={null}
{
  "status": "verified",
  "message": "Number verified successfully"
}
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.