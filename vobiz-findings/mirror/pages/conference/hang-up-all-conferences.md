> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Hang Up All Conferences

> Immediately disconnect every participant across all ongoing conferences on your account in a single request.

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/
```

This endpoint requests termination of all ongoing conferences for your account in one operation.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account ID (e.g., `{auth_id}`)
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Warning>
  **Warning:** This is a destructive operation that affects all active conference instances in your account. The current conference instances end and their members disconnect. A later call using `<Conference>` with the same name can create a new conference instance.
</Warning>

<Warning>
  The conference list can omit active rooms. Do not use an empty `conferences` array as a safety check before calling this endpoint. Maintain your own room registry when you need to review the affected conferences.
</Warning>

<Tip>
  **Use Cases:** System maintenance, emergency shutdown, end-of-day cleanup, security incidents, platform-wide service termination, testing/development environment resets.
</Tip>

## Path parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your Vobiz account ID (e.g., `{auth_id}`) |

<Tip>
  **No request body needed.** Simply use the DELETE method on the base conference endpoint to terminate all conferences.
</Tip>

## Request Body

```json JSON theme={null}
{}
```

No request body parameters required. Send an empty JSON object.

## Response

The endpoint acknowledges the account-wide termination request with an empty response.

```text Response - 204 No Content theme={null}
HTTP Status Code: 204
```

<Tip>
  **Request scope:**

  1. The request targets every active conference in the account.
  2. It does not support selecting individual room names.
  3. Participants do not receive an advance notification from this endpoint.
</Tip>

<Info>
  A `204 No Content` response acknowledges the request. Confirm the result using your own room and call-state tracking.
</Info>

## Example Request

### Hang Up All Conferences

```bash cURL Request theme={null}
curl -X DELETE https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

<Warning>
  **Common Use Cases:**

  * **System maintenance:** Clear all conferences before scheduled maintenance window
  * **Emergency shutdown:** Immediately terminate all services during critical incidents
  * **End of day cleanup:** Automatically close all conferences at business closing time
  * **Testing environment:** Reset test environment by clearing all active conferences
  * **Security response:** Terminate all conferences during security breach response
  * **Resource management:** Force-close abandoned conferences consuming resources
</Warning>

<Warning>
  **Important Warnings:**

  * **Current instances end:** Members disconnect, but a later call using `<Conference>` with the same name can create a new conference instance
  * **No selective termination:** ALL conferences are affected, not just specific ones
  * **Immediate effect:** Disconnection happens instantly without warning to participants
  * **Production caution:** Use extreme caution in production environments
  * **No participant notification:** Participants receive no advance notice
</Warning>

<Tip>
  **Best Practices:**

  * **Track rooms independently:** Use your application's room registry to determine what may be affected
  * **Notify participants:** Send announcements to conferences before terminating (if time allows)
  * **Implement confirmation:** Require double-confirmation in UI before executing
  * **Log operations:** Always log when this endpoint is called and by whom
  * **Restrict access:** Limit this API call to admin-level accounts only
  * **Schedule carefully:** Use during off-peak hours when possible
  * **Alternative approach:** Consider terminating conferences individually when selective control is needed
</Tip>

### Example: Confirmation with application-tracked rooms

Pass room names from your application's state. Do not populate this list from the conference list endpoint immediately before deletion because that endpoint may omit active rooms.

```javascript JavaScript with Confirmation theme={null}
async function hangUpAllConferences(conferences) {
  // Step 1: Use room names tracked by your application
  // Step 2: Show confirmation
  if (conferences.length === 0) {
    console.log('No active conferences to terminate');
    return;
  }

  const confirmed = confirm(
    `WARNING: This will terminate ${conferences.length} active conferences.\n` +
    `Conferences: ${conferences.join(', ')}\n\n` +
    'All participants will be disconnected immediately.\n' +
    'The current conference instances will end.\n\n' +
    'Are you sure you want to continue?'
  );

  if (!confirmed) {
    console.log('Operation cancelled by user');
    return;
  }

  // Step 3: Log the operation
  console.log('Terminating all conferences:', conferences);

  // Step 4: Execute termination
  const response = await fetch(
    'https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/',
    {
      method: 'DELETE',
      headers: {
        'X-Auth-ID': '{auth_id}',
        'X-Auth-Token': 'YOUR_AUTH_TOKEN'
      }
    }
  );

  if (response.status === 204) {
    console.log(`Termination request accepted for ${conferences.length} tracked conferences`);
  }
}

// Usage: Call with room names from your application state
// hangUpAllConferences(['TEAM_ROOM', 'SUPPORT_ROOM']);
```

<Info>
  **Alternative: Selective Termination**

  If you need more control, consider terminating conferences individually using the [Hang Up a Conference](/docs/conference/hang-up-conference) endpoint. This allows you to selectively terminate specific conferences while leaving others active.
</Info>


## OpenAPI

````yaml DELETE /api/v1/Account/{auth_id}/Conference/
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
    delete:
      tags:
        - Conferences
      summary: Delete all conferences
      description: Terminate all active conference rooms.
      operationId: delete-all-conferences
      parameters:
        - $ref: '#/components/parameters/AuthId'
      responses:
        '204':
          description: All conferences terminated
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