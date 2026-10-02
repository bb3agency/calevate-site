> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz API Authentication – X-Auth-ID & X-Auth-Token

> Authenticate Vobiz API requests with X-Auth-ID and X-Auth-Token headers, or use a supported account Bearer access token for capacity subscription endpoints.

Most Vobiz REST API requests use the account Auth ID and Auth Token headers. The CPS and concurrency capacity endpoints also accept an account access token in the standard Bearer header.

<Info>
  **Account API credentials:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
</Info>

## Where to find your credentials

After signing in to the [Vobiz Console](https://console.vobiz.ai), your **Auth ID** and **Auth Token** are displayed directly on the main dashboard. Copy both - you'll pass them as headers on every API call.

<Frame>
  <img src="https://mintcdn.com/vobizai/cPP2drhQ7lKsmogc/images/console-new-ui/dashboard.png?fit=max&auto=format&n=cPP2drhQ7lKsmogc&q=85&s=8cdde70ab01f733540987bb4b4700a09" alt="Vobiz dashboard showing Auth ID, Auth Token, and account balance" width="2936" height="1482" data-path="images/console-new-ui/dashboard.png" />
</Frame>

Your Auth ID looks like `MA_XXXXXXXX`. Treat your Auth Token like a password - anyone with both values can act on your account.

## Making an authenticated request

```bash cURL theme={null}
curl -X GET https://api.vobiz.ai/api/v1/auth/me \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

A successful call to `/auth/me` returns your full account object, including verification status and pricing tier - a good way to confirm your credentials work before building further. See [Retrieve Account Details](/docs/account/retrieve-account) for the full response shape.

## Bearer access tokens for capacity endpoints

The [capacity pricing preview](/docs/account/channel-pricing-preview) and [capacity purchase](/docs/account/channel-subscriptions) endpoints also accept an account access token:

```http theme={null}
Authorization: Bearer <ACCESS_TOKEN>
```

This Bearer-token option applies only where an endpoint explicitly documents it. Continue using `X-Auth-ID` and `X-Auth-Token` for other Vobiz API operations.

For the full error response format and all status codes, see [Error Handling](/docs/errors).

## Security notes

* Never expose `X-Auth-Token` in client-side code (browser JS, mobile apps). Route API calls through your own backend.
* Protect Bearer access tokens with the same controls as the account Auth Token.
* If a token is compromised, regenerate it from the Console dashboard immediately - the old token stops working as soon as you do.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.