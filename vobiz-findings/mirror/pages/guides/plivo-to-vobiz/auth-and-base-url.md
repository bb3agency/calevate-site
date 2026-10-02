> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Authentication & base URL

> Migrate authentication and the API base URL from Plivo to Vobiz - swap the SDK package, switch raw HTTP to the X-Auth-ID and X-Auth-Token headers, and point your client at api.vobiz.ai.

If you already call Plivo, the move to Vobiz starts with two things: how you authenticate and where you send requests. This page covers both. Everything else - the call, recording, and account endpoints - is covered in [Endpoint mapping](/docs/guides/plivo-to-vobiz/endpoint-mapping).

The good news: the Vobiz SDK mirrors the Plivo SDK closely. You swap the package name, repoint your credentials, and most of your code keeps working. For raw HTTP, the only real change is how credentials are passed in headers.

## What changes

| Concept | Plivo | Vobiz |
| - | - | - |
| SDK package | `import plivo` | `from vobiz import Vobiz` (Python) / `@vobiz/sdk` (Node) |
| Client class | `plivo.RestClient(auth_id, auth_token)` | `Vobiz(api_key=AUTH_ID, auth_token=AUTH_TOKEN)` (Python) / `new VobizClient({ apiKey, authToken })` (Node) |
| Env vars | `PLIVO_AUTH_ID`, `PLIVO_AUTH_TOKEN` | `VOBIZ_AUTH_ID`, `VOBIZ_AUTH_TOKEN` |
| Raw HTTP auth | HTTP Basic (`auth_id:auth_token`) | `X-Auth-ID` + `X-Auth-Token` headers |
| Base URL | `https://api.plivo.com/v1` | `https://api.vobiz.ai/api/v1` |
| Resource path | `/Account/{auth_id}/Call/` | `/Account/{auth_id}/Call/` (unchanged) |

A few notes on the table:

* The Vobiz client takes the Auth ID as `api_key` and the Auth Token as `auth_token` (these map to the `X-Auth-ID` / `X-Auth-Token` headers). Unlike Plivo's `RestClient`, pass the credentials explicitly when constructing the client.
* Vobiz auth IDs are prefixed: `MA_` for a master account and `SA_` for a sub-account. Use the full prefixed value wherever you previously used a Plivo auth ID.
* The resource path keeps Plivo's PascalCase and trailing slash (`/Account/{auth_id}/Call/`). Only the host and version prefix change.

## SDK client init

Swap the package and your environment variables. The client object behaves the same way afterward.

<CodeGroup>
  ```python Python theme={null}
  import os

  # Before (Plivo)
  import plivo
  client = plivo.RestClient()  # reads PLIVO_AUTH_ID / PLIVO_AUTH_TOKEN

  # After (Vobiz)
  from vobiz import Vobiz
  client = Vobiz(
      api_key=os.environ["VOBIZ_AUTH_ID"],       # your Auth ID  -> X-Auth-ID
      auth_token=os.environ["VOBIZ_AUTH_TOKEN"], # your Auth Token -> X-Auth-Token
  )
  ```

  ```javascript Node theme={null}
  // Before (Plivo)
  const plivo = require('plivo');
  const client = new plivo.Client(); // reads PLIVO_AUTH_ID / PLIVO_AUTH_TOKEN

  // After (Vobiz)
  import { VobizClient } from '@vobiz/sdk';
  const client = new VobizClient({
    apiKey: process.env.VOBIZ_AUTH_ID,       // your Auth ID  -> X-Auth-ID
    authToken: process.env.VOBIZ_AUTH_TOKEN, // your Auth Token -> X-Auth-Token
  });
  ```

  ```bash cURL theme={null}
  # Before (Plivo) - set your credentials
  export PLIVO_AUTH_ID=XXXXXXXXXXXXXXXXXXXX
  export PLIVO_AUTH_TOKEN=your_token_here

  # After (Vobiz) - note the MA_ / SA_ prefix on the auth ID
  export VOBIZ_AUTH_ID=MA_XXXXXXXXXX
  export VOBIZ_AUTH_TOKEN=your_token_here
  ```
</CodeGroup>

## Raw HTTP request

Plivo authenticates over HTTP Basic auth, passing `auth_id:auth_token`. Vobiz instead expects two dedicated headers - `X-Auth-ID` and `X-Auth-Token` - alongside `Content-Type: application/json`. The host and version prefix change; the resource path does not.

<CodeGroup>
  ```python Python theme={null}
  import os
  import requests

  # Before (Plivo) - HTTP Basic auth
  auth_id = os.environ["PLIVO_AUTH_ID"]
  auth_token = os.environ["PLIVO_AUTH_TOKEN"]
  url = f"https://api.plivo.com/v1/Account/{auth_id}/Call/"

  resp = requests.post(
      url,
      auth=(auth_id, auth_token),
      json={"from": "+911234567890", "to": "+919876543210"},
  )

  # After (Vobiz) - X-Auth-ID / X-Auth-Token headers
  auth_id = os.environ["VOBIZ_AUTH_ID"]      # e.g. MA_XXXXXXXXXX
  auth_token = os.environ["VOBIZ_AUTH_TOKEN"]
  url = f"https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/"

  resp = requests.post(
      url,
      headers={
          "X-Auth-ID": auth_id,
          "X-Auth-Token": auth_token,
          "Content-Type": "application/json",
      },
      json={"from": "+911234567890", "to": "+919876543210"},
  )
  ```

  ```javascript Node theme={null}
  // Before (Plivo) - HTTP Basic auth
  const authId = process.env.PLIVO_AUTH_ID;
  const authToken = process.env.PLIVO_AUTH_TOKEN;
  const basic = Buffer.from(`${authId}:${authToken}`).toString('base64');

  await fetch(`https://api.plivo.com/v1/Account/${authId}/Call/`, {
    method: 'POST',
    headers: {
      Authorization: `Basic ${basic}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ from: '+911234567890', to: '+919876543210' }),
  });

  // After (Vobiz) - X-Auth-ID / X-Auth-Token headers
  const vAuthId = process.env.VOBIZ_AUTH_ID; // e.g. MA_XXXXXXXXXX
  const vAuthToken = process.env.VOBIZ_AUTH_TOKEN;

  await fetch(`https://api.vobiz.ai/api/v1/Account/${vAuthId}/Call/`, {
    method: 'POST',
    headers: {
      'X-Auth-ID': vAuthId,
      'X-Auth-Token': vAuthToken,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ from: '+911234567890', to: '+919876543210' }),
  });
  ```

  ```bash cURL theme={null}
  # Before (Plivo) - HTTP Basic auth
  curl -X POST \
    "https://api.plivo.com/v1/Account/$PLIVO_AUTH_ID/Call/" \
    -u "$PLIVO_AUTH_ID:$PLIVO_AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"from": "+911234567890", "to": "+919876543210"}'

  # After (Vobiz) - X-Auth-ID / X-Auth-Token headers
  curl -X POST \
    "https://api.vobiz.ai/api/v1/Account/$VOBIZ_AUTH_ID/Call/" \
    -H "X-Auth-ID: $VOBIZ_AUTH_ID" \
    -H "X-Auth-Token: $VOBIZ_AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"from": "+911234567890", "to": "+919876543210"}'
  ```
</CodeGroup>

<Note>
  The request body and the `calls.create(...)` signature itself do not change as part of authentication. Parameter-level differences (field names, supported options) are covered in [Endpoint mapping](/docs/guides/plivo-to-vobiz/endpoint-mapping).
</Note>

## Reference

* Official Python SDK: [vobiz-ai/Vobiz-Python-SDK](https://github.com/vobiz-ai/Vobiz-Python-SDK)
* Raw-HTTP reference: [vobiz-ai/Vobiz-All-XML-python](https://github.com/vobiz-ai/Vobiz-All-XML-python)

## Next

<Columns cols={2}>
  <Card title="Endpoint mapping" icon="arrow-right-arrow-left" href="/docs/guides/plivo-to-vobiz/endpoint-mapping">
    Map Plivo call, recording, and account endpoints to their Vobiz equivalents.
  </Card>

  <Card title="Back to migration guide" icon="arrow-left" href="/docs/guides/plivo-to-vobiz">
    Return to the Plivo to Vobiz migration overview.
  </Card>
</Columns>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.