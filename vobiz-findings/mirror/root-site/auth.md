# Vobiz Agent Authentication

> How an autonomous agent (or the developer driving one) obtains and uses credentials to call the Vobiz REST API on `api.vobiz.ai`.

Vobiz currently authenticates every API request with a static API key pair — `X-Auth-ID` and `X-Auth-Token` — issued from the [Developer Console](https://console.vobiz.ai). There is no OAuth 2.0 or OpenID Connect authorization-server flow yet; this document describes the API-key path in full so an agent can self-serve credentials without guessing.

## Discover

- API base URL: `https://api.vobiz.ai`
- OpenAPI spec: [https://vobiz.ai/openapi.json](https://vobiz.ai/openapi.json) (also at `https://vobiz.ai/swagger.json`)
- Auth scheme declared in the spec: two `apiKey`-type security schemes, `X-Auth-ID` and `X-Auth-Token`, both sent as request headers on every call.
- Documentation: [https://vobiz.ai/docs/account](https://vobiz.ai/docs/account)

## Pick a method

Only one credential type is currently supported:

| Identity type | Method | Status |
|---|---|---|
| `anonymous` | Not supported — every endpoint requires a signed-in account | n/a |
| API key pair | `X-Auth-ID` + `X-Auth-Token` headers | **Supported** (see below) |
| `identity_assertion` / OAuth bearer token | OAuth 2.0 authorization code / client credentials | **Not yet supported** |

## Register

1. Create a free account: [https://console.vobiz.ai/auth/signup](https://console.vobiz.ai/auth/signup). No credit card or sales call required.
2. Sign in to the [Developer Console](https://console.vobiz.ai) and open **Settings → API**.
3. The console issues one `X-Auth-ID` (your account SID) and one `X-Auth-Token` (your auth token) per account. Sub-accounts (see the Partner API) each get their own pair.

There is no separate `register_uri` endpoint for programmatic self-registration today — account creation happens through the Developer Console sign-up form above.

## Claim

Credentials are shown directly in the Developer Console UI immediately after signup and again any time under Settings → API — there is no separate claim step or claim token to redeem.

## Use the credential

Send both headers on every request:

```
X-Auth-ID: <your_account_sid>
X-Auth-Token: <your_auth_token>
```

Example:

```bash
curl https://api.vobiz.ai/api/v1/account \
  -H "X-Auth-ID: MA_XXXXXX" \
  -H "X-Auth-Token: your_auth_token"
```

A JWT Bearer token mode also exists for session-based flows: `Authorization: Bearer <jwt_token>`, obtained via the console's login session — see [Authentication](https://vobiz.ai/docs/api-reference/authentication) for details.

## Errors

- Requests missing either header return `401 Unauthorized`, and the response body names which header is missing or invalid.
- There is currently no `WWW-Authenticate` challenge header on 401 responses.

## Revocation

Rotate or revoke a compromised `X-Auth-Token` from the Developer Console under Settings → API. There is no separate `revocation_uri` API endpoint today — revocation is a console action, not a programmatic call.

## Related

- [Vobiz API documentation](https://vobiz.ai/docs/introduction)
- [OpenAPI specification](https://vobiz.ai/openapi.json)
- [agents.md](https://vobiz.ai/agents.md) — broader orientation for agents landing on vobiz.ai
- [llms.txt](https://vobiz.ai/llms.txt) — machine-readable resource index
