> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Get SIP Trunk

> Get a single SIP trunk with full details including gateways, IP identifiers, and phone numbers. Look up any trunk by its ID.



## OpenAPI

````yaml GET /sip-trunks/trunks/{trunk_id}
openapi: 3.1.0
info:
  title: Bolna API
  description: >-
    Use and leverage Bolna Voice AI using APIs through HTTP requests from any
    language in your applications and workflows.
  license:
    name: MIT
  version: 1.0.0
servers:
  - url: https://api.bolna.ai
    description: Production server
security:
  - bearerAuth: []
paths:
  /sip-trunks/trunks/{trunk_id}:
    get:
      description: >-
        Get a single SIP trunk with full details including gateways, IP
        identifiers, and phone numbers
      parameters:
        - in: path
          name: trunk_id
          required: true
          schema:
            type: string
          description: The unique trunk ID
      responses:
        '200':
          description: SIP trunk details
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/SIPTrunkResponse'
        '404':
          description: trunk not found
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    SIPTrunkResponse:
      type: object
      description: SIP trunk object returned by the API.
      properties:
        id:
          type: string
          description: Unique SIP trunk identifier.
        name:
          type: string
          description: Human-readable trunk name.
        provider:
          type: string
          description: >-
            SIP provider name (e.g., twilio, plivo, zadarma, telnyx, vonage,
            custom).
        description:
          type: string
          description: Optional trunk description for internal reference.
        auth_type:
          type: string
          enum:
            - userpass
            - ip-based
          description: Authentication method used for this trunk.
        auth_username:
          type: string
          description: SIP username (present only for userpass trunks).
        gateways:
          type: array
          description: Ordered list of SIP gateways used for registration and call routing.
          items:
            $ref: '#/components/schemas/SIPTrunkGateway'
        ip_identifiers:
          type: array
          description: >-
            IP ranges associated with this trunk (used only for ip-based
            authentication).
          items:
            $ref: '#/components/schemas/SIPTrunkIPIdentifier'
        phone_numbers:
          type: array
          description: Phone numbers (DIDs) registered on this trunk.
          items:
            $ref: '#/components/schemas/SIPTrunkPhoneNumberResponse'
        allow:
          type: string
          description: Comma-separated codecs to allow.
        disallow:
          type: string
          description: Comma-separated codecs to disallow.
        transport:
          type: string
          enum:
            - transport-udp
            - transport-tcp
            - transport-tls
          description: SIP transport used by the trunk.
        direct_media:
          type: boolean
          description: Whether RTP is routed directly between endpoints (typically false).
        rtp_symmetric:
          type: boolean
          description: Enables symmetric RTP to handle NAT.
        force_rport:
          type: boolean
          description: Forces responses to the source port to handle NAT.
        media_encryption:
          type: string
          enum:
            - 'no'
            - sdes
          description: >-
            RTP encryption mode. "no" for plain RTP, "sdes" for SRTP via SDES
            (TLS trunks only).
        media_encryption_optimistic:
          type: boolean
          description: >-
            When media_encryption=sdes, whether to fall back to clear RTP if the
            carrier does not offer crypto.
        qualify_frequency:
          type: integer
          description: SIP OPTIONS ping interval in seconds.
        inbound_enabled:
          type: boolean
          description: Whether inbound calling is enabled.
        outbound_leading_plus_enabled:
          type: boolean
          description: Whether to prepend a leading + to outbound dialed numbers.
        is_active:
          type: boolean
          description: Whether the trunk is active.
        created_at:
          type: string
          format: date-time
          description: ISO timestamp when the trunk was created.
        updated_at:
          type: string
          format: date-time
          description: ISO timestamp when the trunk was last updated.
    Error:
      required:
        - error
        - message
      type: object
      properties:
        error:
          type: integer
          format: int32
        message:
          type: string
    SIPTrunkGateway:
      type: object
      required:
        - gateway_address
      properties:
        gateway_address:
          type: string
          description: Hostname or IP of the SIP gateway
          example: sip.zadarma.com
        port:
          type: integer
          default: 5060
          description: SIP port
          example: 5060
        priority:
          type: integer
          default: 1
          description: Gateway priority (lower = higher priority)
          example: 1
    SIPTrunkIPIdentifier:
      type: object
      required:
        - ip_address
      properties:
        ip_address:
          type: string
          description: IP address or CIDR range for IP-based authentication
          example: 15.207.90.192/31
    SIPTrunkPhoneNumberResponse:
      type: object
      description: Phone number (DID) registered on a SIP trunk.
      properties:
        id:
          type: string
          description: Unique phone number identifier.
        phone_number:
          type: string
          description: The DID phone number stored on the trunk.
        name:
          type: string
          description: Optional label for the phone number.
        byot_trunk_id:
          type: string
          description: The SIP trunk ID that this phone number belongs to.
        telephony_provider:
          type: string
          description: Provider type for BYOT numbers.
          example: sip-trunk
        deleted:
          type: boolean
          description: Whether the phone number is deleted.
        created_at:
          type: string
          format: date-time
          description: ISO timestamp when the phone number was created.
        updated_at:
          type: string
          format: date-time
          description: ISO timestamp when the phone number was last updated.
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````