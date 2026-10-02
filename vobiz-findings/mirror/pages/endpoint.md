> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz Endpoint API

> Manage SIP endpoints on Vobiz for making and receiving calls from IP phones, mobile SIP clients, softphones, and any SIP-compliant device.

The Endpoint API allows you to create and manage SIP endpoints that can be used to make and receive calls through various devices and applications. Endpoints are essential for building communication systems with IP phones, softphones, and SIP clients.

<Info>
  **Note:** Each endpoint is assigned a unique SIP URI that external users can use to establish calls. Endpoints can be registered on SIP clients for real-time communication.
</Info>

## What is an Endpoint?

A Vobiz endpoint, also known as a SIP endpoint, can be any device or application that uses the Session Initiation Protocol (SIP) to perform communications operations:

* **IP Phones** - Hardware SIP phones that connect directly to your network.
* **Mobile Phones** - Mobile apps using SIP softphone applications.
* **Desktop Applications** - Web or desktop softphones using WebRTC or SIP clients.
* **Wireless Devices** - Any wireless SIP-compatible device on your network.

<Tip>
  **Use Cases:** Endpoints are commonly used for call center agents taking calls, business phone systems, customer support hotlines, and building custom VoIP applications.
</Tip>

## API Endpoint

**Base URL**

```http theme={null}
https://api.vobiz.ai/api/v1
```

**Endpoint Base URI**

```http theme={null}
https://api.vobiz.ai/api/v1/Account/{auth_id}/Endpoint/
```

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID (e.g., `{auth_id}`)
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

## Available Operations

| Operation | Method | Description |
| - | - | - |
| [The Endpoint object](/docs/endpoint/endpoint-object) | OBJECT | Complete structure and attributes of an Endpoint object. |
| [Create an endpoint](/docs/endpoint/create-endpoint) | POST | Create a new SIP endpoint for receiving and making calls. |
| [Delete an endpoint](/docs/endpoint/delete-endpoint) | DELETE | Permanently delete an existing endpoint. |
| [Retrieve an endpoint](/docs/endpoint/retrieve-endpoint) | GET | Get details of a specific endpoint including registration status. |
| [Update an endpoint](/docs/endpoint/update-endpoint) | POST | Update endpoint password, alias, or attached application. |
| [List all endpoints](/docs/endpoint/list-all-endpoints) | GET | Retrieve a list of all endpoints in your account. |

## SIP Configuration

After creating an endpoint, configure your SIP client with the following details to connect:

**Server Settings**

* **SIP Server:** `registrar.vobiz.ai`
* **Domain:** `registrar.vobiz.ai`
* **Transport:** UDP/TCP/TLS
* **Port:** 5060 (UDP/TCP), 5061 (TLS)

**Credentials**

* **Username:** `{endpoint_username}`
* **Password:** `{endpoint_password}`
* **Display Name:** `{alias}` (optional)

**Example Configuration:**

```text theme={null}
SIP URI: sip:john_doe@registrar.vobiz.ai
Username: john_doe
Password: SecurePassword123!
Server: registrar.vobiz.ai
Port: 5060
Transport: UDP
```

<Info>
  **WebRTC Configuration:** For WebRTC applications, use JWT token authentication. Connect to `wss://sip.vobiz.ai:7443` and authenticate using a JWT token obtained from the API.
</Info>

## Best Practices

* **Strong Passwords** - Use complex passwords with minimum 8 characters, including mix of letters, numbers, and symbols.
* **Unique Usernames** - Usernames must be unique within your account. Use descriptive names for easy identification.
* **Application Assignment** - Assign applications to endpoints for automatic call routing and handling.
* **Permission Control** - Only enable permissions (voice, video, messaging) that your endpoints actually need.
* **Monitor Registration** - Check `sip_registered` field regularly to verify endpoint connectivity and troubleshoot issues.
* **Token Rotation** - For WebRTC, use short-lived JWT tokens (1-4 hours) and rotate auth tokens periodically.
* **Sub-account Isolation** - Use sub-accounts to isolate endpoints for different customers or departments.
* **Delete Unused Endpoints** - Remove endpoints that are no longer in use to keep your account organized and secure.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.