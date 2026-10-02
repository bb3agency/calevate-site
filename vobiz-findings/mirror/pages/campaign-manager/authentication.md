> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Campaign API authentication

> Authenticate customer-facing Campaign Manager requests with API keys or a JWT, and understand how internal service endpoints are protected.

## Base URL

Every Campaign Manager request goes through the Vobiz API gateway:

```text theme={null}
https://api.vobiz.ai
```

<Warning>
  **Use `api.vobiz.ai`, not a service-specific host.** The campaign service runs behind an internal load balancer on private addresses and is not reachable from the internet. Requests to any other hostname will not resolve.
</Warning>

Every route is scoped to an account:

```text theme={null}
/api/v1/account/{account_id}/…
```

## Authentication methods

All customer-facing routes require authentication. The gateway validates credentials at the edge, and the campaign service re-checks them against the accounts database before serving the request. Choose either method — both are accepted.

<Tabs>
  <Tab title="API keys (recommended)">
    Send your account ID and auth token as headers on every request:

    ```http theme={null}
    X-Auth-ID: MA_XXXXXXXX
    X-Auth-Token: YOUR_AUTH_TOKEN
    ```

    Use the same account ID in the URL path and in `X-Auth-ID`. A mismatch between the path account and the authenticated account returns `401`.

    ```bash cURL theme={null}
    curl "https://api.vobiz.ai/api/v1/account/{account_id}/campaigns" \
      -H "X-Auth-ID: {account_id}" \
      -H "X-Auth-Token: {auth_token}"
    ```
  </Tab>

  <Tab title="JWT">
    If you already hold an account-service JWT (HS256), present it as a bearer token through the gateway instead of the key pair:

    ```http theme={null}
    Authorization: Bearer YOUR_JWT
    ```

    This is the path the Vobiz dashboard uses. For server-to-server integrations, prefer API keys — they do not expire mid-campaign.
  </Tab>
</Tabs>

<Warning>
  Store tokens in environment variables or a secret manager. Do not commit them, and do not send them from browser code.
</Warning>

## Using the API playground

Every Campaign Manager endpoint page on this site has a live playground. To make a real call:

<Steps>
  <Step title="Enter your token">
    Put your auth token in the **X-Auth-Token** field in the Authorization panel.
  </Step>

  <Step title="Enter your account ID twice">
    Set the same value in the `account_id` path parameter **and** the `X-Auth-ID` header field. Both are required — the request is rejected if either is missing.
  </Step>

  <Step title="Send">
    Requests go to `https://api.vobiz.ai`. Mintlify keeps your values as you move between endpoint pages.
  </Step>
</Steps>

## Internal endpoints

Service-to-service routes under `/internal/*` use a separate shared secret:

```http theme={null}
X-Internal-Key: YOUR_INTERNAL_KEY
```

These routes are reachable only inside the Vobiz VPC and are never exposed through the public gateway. Customers do not call them. Rotate the internal key separately from account credentials.

| Method | Path | Purpose |
| - | - | - |
| `POST` | `/internal/hangup` | Hangup callback from the dialler and media layer. |
| `GET` | `/internal/call-lookup/{call_uuid}` | Resolve a call UUID to its campaign and contact. |

The public equivalent of the second route is [`GET /campaigns/{campaign_id}/call-lookup/{call_uuid}`](/docs/campaign-manager/capacity/call-lookup), which is account-scoped and authenticated with your normal credentials.

## Health check

```text theme={null}
GET /status/
```

Returns `OK` when the service is live. It is unauthenticated and intended for monitoring, not for verifying your credentials — use any account-scoped `GET` for that.

## Content types

* Send `Content-Type: application/json` for JSON request bodies.
* Upload contacts as `multipart/form-data` with a file field named `file`.
* Results and CDR exports return `text/csv`.

## Authentication failures

| Code | Cause |
| - | - |
| `401` | Missing or invalid `X-Auth-Token`, missing `X-Auth-ID`, or an expired JWT. |
| `401` | The authenticated account does not match `{account_id}` in the path. |
| `404` | The resource exists but belongs to a different account. |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.