> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# DTMF

> Send DTMF tones programmatically to an active call to automate IVR navigation, enter access codes, or drive automated phone menus.

DTMF (Dual-Tone Multi-Frequency) is the tone generated whenever a key is pressed during an active call. Use this resource to send DTMF digits programmatically - the most common use case is automating digit entry to a receiver in an outbound call.

<Info>
  **Use case:** Automatically navigate IVR menus, enter access codes, or provide automated responses to phone systems without manual input.
</Info>

## API endpoint

```http theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/DTMF/
```

## Key features

<CardGroup cols={2}>
  <Card title="All DTMF digits" icon="keyboard">
    Send any DTMF digit including 0–9, `*`, and `#` for complete IVR navigation.
  </Card>

  <Card title="Leg selection" icon="git-fork">
    Choose which call leg (caller or callee) receives the DTMF tones.
  </Card>

  <Card title="Real-time sending" icon="zap">
    Send digits instantly during active calls for immediate interaction.
  </Card>

  <Card title="Automation ready" icon="bot">
    Perfect for automated call flows, IVR navigation, and programmatic call control.
  </Card>
</CardGroup>

## Common use cases

* **IVR menu navigation** - Automatically navigate through IVR menus by sending the appropriate menu selections.
* **Access code entry** - Enter conference codes, PIN numbers, or access codes without manual input.
* **Automated survey responses** - Submit automated responses to phone surveys or feedback systems.
* **Account verification** - Automatically enter account numbers or verification codes during calls.
* **Call control** - Send control codes to phone systems that accept DTMF commands.

## Available operations

<Card title="Send digits on a call" icon="send" href="/docs/call/dtmf/send-digits">
  `POST` - Send DTMF digits to an active call. Specify the digits to send and which call leg should receive them.
</Card>


## OpenAPI

````yaml POST /api/v1/Account/{auth_id}/Call/{call_uuid}/DTMF/
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
  /api/v1/Account/{auth_id}/Call/{call_uuid}/DTMF/:
    post:
      tags:
        - DTMF
      summary: Send DTMF tones
      description: >-
        Send DTMF (keypad) tones on an active call. Use `w` for 0.5s pause, `W`
        for 1s pause.
      operationId: send-dtmf
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: call_uuid
          in: path
          required: true
          schema:
            type: string
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - digits
              properties:
                digits:
                  type: string
                  example: 1w2W3
                leg:
                  type: string
                  enum:
                    - aleg
                    - bleg
                    - both
                  default: aleg
            example:
              digits: '1234'
              leg: aleg
      responses:
        '200':
          description: DTMF sent
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