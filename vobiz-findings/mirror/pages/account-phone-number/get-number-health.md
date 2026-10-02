> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Get Number Health Dashboard

> Retrieve the health and analytics dashboard for a Vobiz number - status, spam flag, and call metrics (total/answered calls, answer rate, minutes) with a daily time series of snapshots.



## OpenAPI

````yaml GET /api/v1/account/{auth_id}/numbers/{e164}/health
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
  /api/v1/account/{auth_id}/numbers/{e164}/health:
    get:
      tags:
        - Phone Numbers
      summary: Get number health dashboard
      description: >
        Returns the health & analytics dashboard for one of your numbers:
        current

        status, spam flag, and call metrics over the selected window (total and

        answered calls, answer rate, minutes, average duration) plus a
        per-period

        time series of snapshots.
      operationId: get-number-health
      parameters:
        - $ref: '#/components/parameters/AuthId'
        - name: e164
          in: path
          required: true
          description: The number in E.164, URL-encoded (use %2B instead of +).
          schema:
            type: string
            example: '%2B919876543210'
        - name: granularity
          in: query
          required: false
          description: Snapshot granularity.
          schema:
            type: string
            enum:
              - daily
              - hourly
            default: daily
        - name: days
          in: query
          required: false
          description: Size of the window (in days) for the summary and snapshots.
          schema:
            type: integer
            default: 30
            example: 30
      responses:
        '200':
          description: Number health dashboard
          content:
            application/json:
              schema:
                type: object
                properties:
                  e164:
                    type: string
                    example: '+919876543210'
                  status:
                    type: string
                    example: active
                  usage_status:
                    type: string
                    description: Reputation/usage rating for the number.
                    example: unrated
                  is_spam:
                    type: boolean
                    example: false
                  granularity:
                    type: string
                    example: daily
                  summary:
                    type: object
                    properties:
                      period_days:
                        type: integer
                        example: 30
                      total_calls:
                        type: integer
                        example: 0
                      answered_calls:
                        type: integer
                        example: 0
                      answer_rate:
                        type: number
                        example: 0
                      total_minutes:
                        type: number
                        example: 0
                      avg_duration:
                        type: number
                        example: 0
                  snapshots:
                    type: array
                    items:
                      type: object
                      properties:
                        id:
                          type: string
                          example: bd41d44b-7217-4a78-9261-588fb1b41c25
                        ts:
                          type: string
                          format: date-time
                          example: '2026-06-04T00:00:00Z'
                        total_calls:
                          type: integer
                          example: 0
                        answered_calls:
                          type: integer
                          example: 0
                        failed_calls:
                          type: integer
                          example: 0
                        answer_rate:
                          type: number
                          example: 0
                        total_duration:
                          type: number
                          example: 0
                        avg_duration:
                          type: number
                          example: 0
                        total_minutes:
                          type: number
                          example: 0
        '404':
          description: Number not found
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
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
  schemas:
    Error:
      type: object
      properties:
        api_id:
          type: string
        error:
          type: string
        message:
          type: string
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