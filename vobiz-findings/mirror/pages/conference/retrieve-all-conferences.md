> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List All Conferences

> Retrieve the names of all ongoing conferences on your account, so you can look up details or perform operations on specific rooms.

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/
```

This endpoint returns the conference names currently reported for your account. Use the result as supplementary status information and maintain your own room registry for authoritative discovery and lifecycle tracking.

<Warning>
  **Known limitation:** This endpoint can return `200 OK` with an empty `conferences` array while conferences are active. Do not use it as the source of truth for monitoring, billing, cleanup, or destructive operations.
</Warning>

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Tip>
  **Use cases:** Supplement an operational dashboard, inspect room names returned by the API, or troubleshoot a conference already tracked by your application.
</Tip>

## Path parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your Vobiz account ID (e.g., `{auth_id}`) |

<Tip>
  **No request body or query parameters needed.** Simply use the GET method on the base conference endpoint.
</Tip>

## Response

The documented response contains conference names and an API request identifier.

```json Response - 200 OK (Multiple Conferences) theme={null}
{
  "conferences": [
    "Team Meeting",
    "Sales Call",
    "Customer Support Conference"
  ],
  "api_id": "API_REQUEST_ID"
}
```

```json Response - 200 OK (Empty Result) theme={null}
{
  "conferences": [],
  "api_id": "API_REQUEST_ID"
}
```

### Response Fields

* `conferences` - Array of conference names reported by the API. An empty array is inconclusive and does not prove that no conferences are running.
* `api_id` - Unique identifier for this API request

<Info>
  The response only includes conference names, not detailed information. The [Retrieve a Conference](/docs/conference/retrieve-conference) endpoint is also subject to a known response limitation.
</Info>

## Example Request

### List All Active Conferences

```bash cURL Request theme={null}
curl -X GET https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

### Get details for a reported conference

For each name returned by the API, you can request conference details. Do not use this flow as the only way to discover rooms; begin with the room registry maintained by your application.

<CodeGroup>
  ```bash Step 1: List all conferences theme={null}
  # Get list of conference names
  curl -X GET https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/ \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN"

  # Response: {"conferences": ["Team Meeting", "Sales Call"]}
  ```

  ```bash Step 2: Get details for specific conference theme={null}
  # Get details for "Team Meeting"
  curl -X GET https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/Team%20Meeting/ \
    -H "X-Auth-ID: YOUR_AUTH_ID" \
    -H "X-Auth-Token: YOUR_AUTH_TOKEN"

  # Response includes member count, runtime, and all participants
  ```
</CodeGroup>

<Warning>
  Do not use this endpoint alone for billing, cleanup, destructive operations, or authoritative room discovery. An empty result can occur while conferences are active.
</Warning>

<Tip>
  **Best Practices:**

  * Do not use this endpoint as the only source for dashboard or conference-state updates
  * Cache results to reduce API calls - refresh only when needed
  * Treat an empty conference array as inconclusive because active rooms may be omitted
  * Iterate through results to get detailed info only when needed
  * Implement rate limiting to avoid excessive API calls
  * Use WebSockets or webhooks for real-time updates instead of frequent polling
</Tip>

### Example: Dashboard Implementation

```javascript JavaScript Dashboard Logic theme={null}
// Fetch all active conferences
async function getActiveConferences() {
  const response = await fetch(
    'https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/',
    {
      headers: {
        'X-Auth-ID': '{auth_id}',
        'X-Auth-Token': 'YOUR_AUTH_TOKEN'
      }
    }
  );

  const data = await response.json();
  if (data.conferences.length === 0) {
    console.warn('The API returned no room names; confirm against application state');
  }
  return data.conferences; // Array of conference names
}

// Get details for each conference
async function getConferenceDetails(conferenceName) {
  const encodedName = encodeURIComponent(conferenceName);
  const response = await fetch(
    `https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/${encodedName}/`,
    {
      headers: {
        'X-Auth-ID': '{auth_id}',
        'X-Auth-Token': 'YOUR_AUTH_TOKEN'
      }
    }
  );

  const data = await response.json();
  return data.error ? null : data;
}

// Supplement your application-tracked state with API-reported room names
setInterval(async () => {
  const conferences = await getActiveConferences();
  console.log(`Conference names returned by API: ${conferences.length}`);

  // Get details for each
  for (const name of conferences) {
    const details = await getConferenceDetails(name);
    if (details) {
      console.log(`${name}: ${details.conference_member_count} members`);
    } else {
      console.warn(`Details are currently unavailable for ${name}`);
    }
  }
}, 15000);
```


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/Conference/
openapi: 3.0.3
info:
  title: Vobiz API
  description: >
    The Vobiz API lets you make calls, manage phone numbers, configure SIP
    trunks, 

    and access account data programmatically.


    **Base URL:** `https://api.vobiz.ai`


    **Authentication:** Most requests require `X-Auth-ID` and `X-Auth-Token`
    headers.

    Selected account endpoints also accept an account access token as a Bearer
    token.

    Obtain account credentials from your [Vobiz
    Console](https://console.vobiz.ai).
  version: '1.0'
  contact:
    email: support@vobiz.ai
    url: https://vobiz.ai
servers:
  - url: https://api.vobiz.ai
    description: Production
security:
  - AuthID: []
    AuthToken: []
tags:
  - name: Account
    description: Manage your account details and credentials
  - name: Balance
    description: Retrieve balance and transaction history
  - name: Calls
    description: Make and manage outbound calls
  - name: Live Calls
    description: Retrieve and control in-progress calls
  - name: CDR
    description: Call detail records and history
  - name: Sub-Accounts
    description: Create and manage sub-accounts
  - name: Phone Numbers
    description: Manage phone numbers on your account
  - name: Trunks
    description: Configure SIP trunks for inbound and outbound calling
  - name: Conference
    description: Manage conference calls and members
  - name: Applications
    description: Manage voice and messaging applications with webhook URLs
  - name: Endpoints
    description: Manage SIP endpoints for IP phones, softphones, and SIP clients
  - name: Partner API
    description: >-
      Reseller and white-label endpoints for managing customer sub-accounts,
      balance transfers, transactions, CDRs, and DIDs across your partner
      ecosystem
  - name: Sub-Account KYC
    description: >-
      Per-sub-account KYC verification (PAN, GST, CIN, Aadhaar, DigiLocker) and
      hosted email/redirect KYC sessions. Authenticated as the parent main
      account.
  - name: Sub-Account KYC (Test Mode)
    description: >-
      Mock KYC endpoints that never call the upstream provider. Drive verified /
      failed / pending / error outcomes with magic inputs for integration
      testing.
  - name: Bulk Operations
    description: >-
      Endpoints that act on many records in one request. These accept the
      request, process it in the background, and deliver the result by email.
paths:
  /api/v1/Account/{auth_id}/Conference/:
    get:
      tags:
        - Conferences
      summary: List conferences
      description: >-
        Retrieve conference room names reported by the API. An empty array is
        inconclusive and can occur while conferences are active. Maintain your
        own room registry for authoritative discovery, billing, cleanup, and
        destructive workflows.
      operationId: list-conferences
      parameters:
        - $ref: '#/components/parameters/AuthId'
      responses:
        '200':
          description: List of conferences
          content:
            application/json:
              example:
                conferences: []
                api_id: API_REQUEST_ID
              schema:
                type: object
                properties:
                  api_id:
                    type: string
                  conferences:
                    type: array
                    items:
                      type: string
                    description: >-
                      Conference names reported by the API. An empty array is
                      inconclusive.
                required:
                  - api_id
                  - conferences
components:
  parameters:
    AuthId:
      name: auth_id
      in: path
      required: true
      description: Your account Auth ID
      schema:
        type: string
        example: MA_XXXXXX
  securitySchemes:
    AuthID:
      type: apiKey
      in: header
      name: X-Auth-ID
      description: Your Vobiz account Auth ID
    AuthToken:
      type: apiKey
      in: header
      name: X-Auth-Token
      description: Your Vobiz account Auth Token

````

This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.