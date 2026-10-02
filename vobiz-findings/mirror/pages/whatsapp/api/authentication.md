> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# API Authentication

> Authenticate every Vobiz WhatsApp API request using X-Auth-ID and X-Auth-Token headers - find your credentials in the Vobiz Console and secure them server-side.

### Authentication Method

Vobiz uses custom HTTP headers for authentication. Every API request must include both `X-Auth-ID` and `X-Auth-Token` headers. A `Bearer` JWT (`Authorization: Bearer <token>`) issued at login is also accepted in place of the header pair.

## Getting Your API Credentials

Follow these steps to obtain your API credentials from the Vobiz Console:

1. **Log in to the Vobiz Console** - Navigate to [console.vobiz.ai](https://console.vobiz.ai) and sign in.
2. **Navigate to API Settings** - Go to **Settings → API** in the left sidebar.
3. **View Your Credentials** - Your Auth ID and Auth Token are shown here.
4. **Copy Your Credentials** - Copy both the Auth ID and Auth Token to use in your application.

<Warning>
  Treat your Auth Token like a password. Keep it secure and never expose it in client-side code.
</Warning>

### Understanding Your Credentials

* **`X-Auth-ID`** *(Account Identifier)* - Your account's authentication ID. Starts with the `MA_` prefix and identifies your account. Example: `MA_XXXXXXXX`.
* **`X-Auth-Token`** *(Secret Key)* - Your secret authentication token. Keep this secure! Send it in the `X-Auth-Token` header alongside your Auth ID.

## Making Authenticated Requests

Include both authentication headers in every API request:

### Required Headers

| Header | Value | Required |
| - | - | - |
| `X-Auth-ID` | Your Auth ID (`MA_…`) | Required |
| `X-Auth-Token` | Your Auth Token | Required |
| `Content-Type` | `application/json` | For POST/PUT |

<Note>
  You may instead authenticate with a JWT obtained at login by sending an `Authorization: Bearer <token>` header. The `X-Auth-ID` / `X-Auth-Token` pair is the recommended method for server-to-server integrations.
</Note>

### Common Authentication Errors

* **`401 Unauthorized`** - Missing or invalid Auth ID / Auth Token (or invalid Bearer token).
* **`403 Forbidden`** - Valid credentials but insufficient permissions for the requested resource.
* **Missing headers** - Both `X-Auth-ID` and `X-Auth-Token` must be present (unless using a Bearer token).

## Code Example

An authenticated request using cURL:

```bash cURL theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/messaging/channels/whatsapp" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: <your-auth-token>" \
  -H "Content-Type: application/json"
```

Using a Bearer JWT instead:

```bash cURL theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/messaging/channels/whatsapp" \
  -H "Authorization: Bearer <your-jwt>" \
  -H "Content-Type: application/json"
```

## Security Best Practices

* **Use environment variables** - Store your Auth ID and Token in environment variables (e.g. `VOBIZ_AUTH_ID`, `VOBIZ_AUTH_TOKEN`). Do not hardcode them in your source code.
* **Never commit credentials** - Add credential files to `.gitignore` to prevent accidentally committing them to version control.
* **Use server-side only** - Never expose your Auth Token in client-side code (browsers, mobile apps). All API calls should be made from your backend servers.
* **Use HTTPS** - Always make API requests over HTTPS. The Vobiz API does not support unencrypted HTTP connections.

## Related Topics

* [API Overview →](/docs/whatsapp/api)
* [Send Message API →](/docs/whatsapp/api/send-message)
* [Channels API →](/docs/whatsapp/api/channels)
* [Webhook Events →](/docs/whatsapp/webhooks/events)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.