> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Create SIP Trunk

> Create a new SIP trunk on Bolna and register it with your gateway details. Set up your trunk for inbound and outbound voice calling.

## Next steps

After creating your trunk, [add a phone number to it](/docs/api-reference/sip-trunks/add_number).


## OpenAPI

````yaml POST /sip-trunks/trunks
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
  /sip-trunks/trunks:
    post:
      description: Create a new SIP trunk and register it with Bolna's media layer
      requestBody:
        description: SIP trunk configuration
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/SIPTrunkCreateRequest'
            examples:
              userpass-example:
                summary: Username/Password authentication
                value:
                  name: Zadarma Production
                  provider: zadarma
                  description: Main trunk for outbound sales
                  auth_type: userpass
                  auth_username: <your-sip-username>
                  auth_password: <your-sip-password>
                  gateways:
                    - gateway_address: sip.zadarma.com
                      port: 5060
                      priority: 1
                  allow: ulaw,alaw
                  disallow: all
                  inbound_enabled: true
                  outbound_leading_plus_enabled: true
              ip-based-example:
                summary: IP-Based authentication
                value:
                  name: Plivo Elastic Trunk
                  provider: plivo
                  auth_type: ip-based
                  gateways:
                    - gateway_address: 21467306465797919.zt.plivo.com
                      port: 5060
                      priority: 1
                  ip_identifiers:
                    - ip_address: 15.207.90.192/31
                    - ip_address: 204.89.151.128/27
                  inbound_enabled: true
        required: true
      responses:
        '201':
          description: SIP trunk created successfully
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/SIPTrunkResponse'
        '400':
          description: validation error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    SIPTrunkCreateRequest:
      type: object
      required:
        - name
        - provider
        - auth_type
        - gateways
      properties:
        name:
          type: string
          description: Human-readable label. Must be unique per account.
          example: Zadarma Production
        provider:
          type: string
          description: >-
            SIP provider name (e.g. twilio, plivo, zadarma, telnyx, vonage,
            custom)
          example: zadarma
        description:
          type: string
          description: Optional description for internal reference
        auth_type:
          type: string
          enum:
            - userpass
            - ip-based
          description: Authentication method
          example: userpass
        auth_username:
          type: string
          description: SIP username. Required when auth_type is userpass.
        auth_password:
          type: string
          description: SIP password. Required when auth_type is userpass.
        gateways:
          type: array
          items:
            $ref: '#/components/schemas/SIPTrunkGateway'
          description: At least one gateway is required
        ip_identifiers:
          type: array
          items:
            $ref: '#/components/schemas/SIPTrunkIPIdentifier'
          description: Required when auth_type is ip-based
        allow:
          type: string
          default: ulaw,alaw
          description: Comma-separated codecs to allow
        disallow:
          type: string
          default: all
          description: Comma-separated codecs to disallow
        transport:
          type: string
          enum:
            - transport-udp
            - transport-tcp
            - transport-tls
          default: transport-udp
          description: SIP transport protocol.
        direct_media:
          type: boolean
          default: false
          description: RTP directly between caller and callee. Keep false.
        rtp_symmetric:
          type: boolean
          default: true
          description: Symmetric RTP. Required for NAT.
        force_rport:
          type: boolean
          default: true
          description: Force responses to source port. Required for NAT.
        media_encryption:
          type: string
          enum:
            - 'no'
            - sdes
          default: 'no'
          description: >-
            RTP encryption. Use "sdes" for SRTP. Requires
            transport=transport-tls.
        media_encryption_optimistic:
          type: boolean
          default: false
          description: >-
            When media_encryption=sdes, fall back to clear RTP if the carrier
            does not offer crypto in its SDP.
        qualify_frequency:
          type: integer
          default: 60
          description: SIP OPTIONS ping interval in seconds. 0 to disable.
        inbound_enabled:
          type: boolean
          default: false
          description: Set true to receive inbound calls on this trunk
        outbound_leading_plus_enabled:
          type: boolean
          default: true
          description: Prepend + to outbound dialed numbers
        phone_numbers:
          type: array
          items:
            $ref: '#/components/schemas/SIPTrunkPhoneNumberRequest'
          description: Optional phone numbers to add at creation time
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
    SIPTrunkPhoneNumberRequest:
      type: object
      required:
        - phone_number
      properties:
        phone_number:
          type: string
          description: The DID phone number to register
          example: '919876543210'
        name:
          type: string
          description: Optional human-readable label for the number
          example: Mumbai Support Line
        e164_check_enabled:
          type: boolean
          default: false
          description: Whether to enforce E.164 format validation
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