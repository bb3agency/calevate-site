> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Retrieve a Conference

> Fetch live details of a named Vobiz conference via GET - runtime, member count, mute/deaf states, call UUIDs, and join times for multi-party calls globally.

```http theme={null}
GET https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/{conference_name}/
```

Retrieves the details of a particular conference by its name. The response includes the conference runtime, member count, and detailed information about each member currently in the conference.

<Warning>
  **Known limitation:** A live conference can return `200 OK` with `{"error":"failed"}` instead of conference details. Check the response body before using it, and capture `ConferenceMemberID` from conference `enter` callbacks when you need to target a member.
</Warning>

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Tip>
  **Use Cases:** Monitor active conferences, check participant status, verify member states (muted/deaf), track join times, and gather call UUIDs for further operations.
</Tip>

## Path parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `auth_id` | string | Yes | Your Vobiz account ID (e.g., `{auth_id}`) |
| `conference_name` | string | Yes | Name of the conference to retrieve |

<Tip>
  **No request body needed.** Simply use the GET method with the conference name in the URL path.
</Tip>

## Response

When available, the response contains conference details and active members.

The current failure response for a live conference is:

```json Response - 200 OK theme={null}
{
  "error": "failed",
  "api_id": "API_REQUEST_ID"
}
```

An ended or unknown conference returns `404 Not Found` with `{"error":"conference not found"}`.

```json Response - 200 OK theme={null}
{
  "conference_name": "My Conf Room",
  "conference_run_time": "590",
  "conference_member_count": "1",
  "members": [
    {
      "muted": false,
      "member_id": "17",
      "deaf": false,
      "from": "CALLER_NUMBER",
      "to": "VOBIZ_NUMBER",
      "caller_name": "John",
      "direction": "inbound",
      "call_uuid": "CALL_UUID",
      "join_time": "590"
    }
  ],
  "api_id": "API_REQUEST_ID"
}
```

### Response Fields

* `conference_name` - Name of the conference
* `conference_run_time` - Duration in seconds since conference started
* `conference_member_count` - Number of active members
* `members` - Array of member objects with detailed information
* `api_id` - Unique identifier for this API request

<Info>
  **Member Information:** Each member object includes their ID, mute/deaf status, caller details, direction (inbound/outbound), call UUID, and join time. See [The Conference Object](/docs/conference/conference-object) documentation for detailed attribute descriptions.
</Info>

## Example Request

### Retrieve Conference by Name

```bash cURL Request theme={null}
curl -X GET https://api.vobiz.ai/api/v1/Account/{auth_id}/Conference/My%20Conf%20Room/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN"
```

Conference names with spaces must be URL-encoded (space becomes `%20`).

### Response with Multiple Members

```json JSON Response theme={null}
{
  "conference_name": "Team Meeting",
  "conference_run_time": "1200",
  "conference_member_count": "3",
  "members": [
    {
      "muted": false,
      "member_id": "45",
      "deaf": false,
      "from": "CALLER_NUMBER_1",
      "to": "VOBIZ_NUMBER",
      "caller_name": "Alice Johnson",
      "direction": "inbound",
      "call_uuid": "CALL_UUID_1",
      "join_time": "1200"
    },
    {
      "muted": true,
      "member_id": "46",
      "deaf": false,
      "from": "CALLER_NUMBER_2",
      "to": "VOBIZ_NUMBER",
      "caller_name": "",
      "direction": "outbound",
      "call_uuid": "CALL_UUID_2",
      "join_time": "900"
    },
    {
      "muted": false,
      "member_id": "47",
      "deaf": false,
      "from": "CALLER_NUMBER_3",
      "to": "VOBIZ_NUMBER",
      "caller_name": "Bob Smith",
      "direction": "inbound",
      "call_uuid": "CALL_UUID_3",
      "join_time": "300"
    }
  ],
  "api_id": "API_REQUEST_ID"
}
```

<Warning>
  **Common Use Cases:**

  * **Monitor conference status:** Check how long a conference has been running
  * **Verify participants:** See who is currently in the conference
  * **Check member states:** Identify which members are muted or deaf
  * **Track join times:** Determine when each participant joined
  * **Get call UUIDs:** Retrieve call UUIDs for further call operations
  * **Dashboard display:** Show real-time conference information in admin panels
</Warning>

<Tip>
  **Best Practices:**

  * URL-encode conference names that contain spaces or special characters
  * Do not rely on this endpoint as the only source for dashboard updates
  * Capture member IDs from conference `enter` callbacks when performing member operations
  * Use call\_uuid to correlate conference members with CDR records
  * Handle 404 responses gracefully - conference may have ended between requests
</Tip>


## OpenAPI

````yaml GET /api/v1/Account/{auth_id}/Conference/{conference_name}/
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
  /api/v1/Account/{auth_id}/Conference/{conference_name}/:
    get:
      tags:
        - Conferences
      summary: Retrieve a conference
      description: >-
        Retrieve a specific conference room. A live conference can currently
        return a 200 response with an error payload instead of conference
        details.
      operationId: get-conference
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: conference_name
          in: path
          required: true
          schema:
            type: string
            example: My Conf Room
      responses:
        '200':
          description: Conference details or the current live-retrieval failure payload
          content:
            application/json:
              schema:
                oneOf:
                  - title: Conference details
                    type: object
                    properties:
                      conference_name:
                        type: string
                      conference_run_time:
                        type: string
                        description: Conference runtime in seconds
                      conference_member_count:
                        type: string
                      members:
                        type: array
                        items:
                          type: object
                          properties:
                            muted:
                              type: boolean
                            member_id:
                              type: string
                            deaf:
                              type: boolean
                            from:
                              type: string
                            to:
                              type: string
                            caller_name:
                              type: string
                            direction:
                              type: string
                            call_uuid:
                              type: string
                            join_time:
                              type: string
                      api_id:
                        type: string
                    required:
                      - conference_name
                      - conference_run_time
                      - conference_member_count
                      - members
                      - api_id
                  - title: Current live-retrieval failure
                    type: object
                    properties:
                      error:
                        type: string
                        enum:
                          - failed
                      api_id:
                        type: string
                    required:
                      - error
                      - api_id
              examples:
                success:
                  summary: Successful conference object
                  value:
                    conference_name: My Conf Room
                    conference_run_time: '590'
                    conference_member_count: '1'
                    members:
                      - muted: false
                        member_id: '17'
                        deaf: false
                        from: CALLER_NUMBER
                        to: VOBIZ_NUMBER
                        caller_name: CALLER_NAME
                        direction: inbound
                        call_uuid: CALL_UUID
                        join_time: '590'
                    api_id: API_REQUEST_ID
                currentFailure:
                  summary: Current failure response for a live conference
                  value:
                    error: failed
                    api_id: API_REQUEST_ID
        '404':
          description: Conference not found
          content:
            application/json:
              schema:
                type: object
                properties:
                  error:
                    type: string
                  api_id:
                    type: string
                required:
                  - error
                  - api_id
              example:
                error: conference not found
                api_id: API_REQUEST_ID
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