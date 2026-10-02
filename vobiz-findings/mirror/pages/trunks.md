> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz SIP Trunking API – Enterprise Voice & Elastic SIP Trunks

> Create and manage elastic SIP trunks on Vobiz - auto-provisioned SIP domains, IP or credential auth, CPS throttling, and priority failover routing for enterprise voice across 130+ countries.

Manage SIP trunks for enterprise voice communications. Create trunks with automatic SIP domain provisioning, configure authentication methods, and set up outbound routing for scalable telephony infrastructure.

<Info>
  **What is a SIP Trunk?**

  A SIP trunk is a virtual connection that enables voice communication over IP networks. Each trunk serves as a dedicated voice gateway with its own authentication, rate limits, and routing configuration. Vobiz automatically provisions each trunk with a unique SIP domain and integrates it with Kamailio for robust SIP routing and authentication.

  * **Auto-generated SIP domains:** Each trunk gets a unique domain like `trunkId.sip.vobiz.ai`
  * **Flexible authentication:** Support for both username/password and IP-based authentication
  * **Rate limiting:** Configure concurrent call limits and calls-per-second (CPS) throttling
  * **Outbound routing:** Define origination URIs with priority-based failover and load balancing
</Info>

## Key features

* **Dual authentication** - Choose between username/password credentials or IP whitelisting. Combine both methods for maximum security.
* **Intelligent routing** - Configure multiple origination URIs with priority-based failover and weight-based load balancing for resilient outbound calling.
* **Rate limiting** - Protect against traffic spikes with configurable concurrent call limits and calls-per-second (CPS) throttling.
* **Kamailio integration** - Seamless integration with Kamailio SIP proxy for robust routing, authentication, and load balancing infrastructure.

## Trunk Management

The core trunk operations allow you to create, configure, and manage your SIP trunks. Each trunk acts as an independent voice gateway with its own configuration and rate limits.

* [The Trunk Object](/docs/trunks/trunk-object) - Complete structure and attributes of a trunk
* [Create a Trunk](/docs/trunks/create-trunk) - Provision a new SIP trunk with auto-generated domain
* [Retrieve a Trunk](/docs/trunks/retrieve-trunk) - Get details of a specific trunk by ID
* [Retrieve All Trunks](/docs/trunks/retrieve-all-trunks) - List all trunks with pagination support
* [Update a Trunk](/docs/trunks/update-trunk) - Modify trunk configuration and rate limits
* [Delete a Trunk](/docs/trunks/delete-trunk) - Permanently remove a trunk and its resources

## Credentials

Credentials provide username/password authentication for your SIP trunk. You can create multiple credentials per trunk for different devices or use cases. Passwords are securely hashed and never returned in API responses after creation.

[View Credentials Documentation](/docs/trunks/credentials)

## IP Access Control Lists

IP Access Control Lists (IP ACLs) enable IP-based authentication by whitelisting specific IPv4 addresses. Devices calling from whitelisted IPs can use the trunk without password authentication. This is ideal for PBX systems, SIP gateways, and carrier interconnections with static IP addresses.

[View IP ACL Documentation](/docs/trunks/ip-acl)

## Origination URIs

Origination URIs define where outbound calls from your trunk should be routed. Configure multiple URIs with priority-based failover (lower priority tried first) and weight-based load balancing (higher weight receives more traffic). This enables resilient, distributed call routing with automatic failover.

[View Origination URI Documentation](/docs/trunks/origination-uri)

## Webhooks

Configure a webhook URL on your trunk to receive real-time HTTP callbacks for call events. Vobiz sends notifications when a call is initiated (admitted or rejected) and when a call ends (hangup with full duration, cost, and quality metrics). Webhooks are sent asynchronously and never delay the SIP call flow.

[View Webhook Documentation](/docs/trunks/webhook)

## Authentication Methods

### Username/Password

SIP digest authentication using credentials. Ideal for devices with dynamic IP addresses or mobile softphones. Kamailio validates credentials against the subscriber database.

* Works from any IP address
* Multiple credentials per trunk
* Secure password hashing

### IP Whitelisting

IP-based authentication without passwords. Best for PBX systems, SIP gateways, and carrier connections with static IP addresses. Provides higher security for production deployments.

* No password required
* Enhanced security
* Requires static IP addresses

## SIP Call Log Error Statuses

The table below describes common SIP error statuses you may encounter when reviewing call logs. Use them to troubleshoot connection, routing, and endpoint issues.

| Status Code | Description / Cause |
| - | - |
| `NORMAL_CLEARING` | One of the parties hung up normally. Standard end-of-call status. |
| `USER_BUSY` | The called party is busy (e.g., already on another call or declined). |
| `NO_ANSWER` | The called party did not answer within the specified timeout period. |
| `ORIGINATOR_CANCEL` | The caller cancelled the call before it was answered. |
| `CALL_REJECTED` | The call was explicitly rejected - possibly due to blocking rules, spam filtering, or the destination refusing the connection. |
| `REJECTED` | General rejection; the SIP endpoint refused the incoming INVITE. |
| `INVALID_NUMBER` | The dialed number format is invalid or does not exist. |
| `UNALLOCATED_NUMBER` | The dialed number is valid but not allocated to any active subscriber. |
| `SERVICE_UNAVAILABLE` | The destination service is temporarily unavailable (SIP 503). |
| `SERVER_ERROR` | An internal server error occurred while processing or routing the call. |
| `MEDIA_TIMEOUT` | No RTP media packets received - likely a firewall or network dropout. |
| `PROTOCOL_ERROR` | A SIP protocol violation or malformed SIP message during call setup. |
| `NETWORK_OUT_OF_ORDER` | A severe network failure prevented the call from reaching its destination. |
| `DESTINATION_OUT_OF_ORDER` | The destination endpoint cannot accept the call, often indicating an offline server. |
| `NORMAL_TEMPORARY_FAILURE` | Generic temporary routing failure; retrying may succeed. |
| `SWITCH_CONGESTION` | The SIP switch is at capacity and cannot handle the request. |
| `UNKNOWN` | An error not mapped to any standard SIP error or ISUP release cause code. |

## Getting Started

### Quick Setup Guide

1. **Create a Trunk** - Use the [Create Trunk](/docs/trunks/create-trunk) endpoint to provision a new SIP trunk. You will receive a unique SIP domain and trunk ID.
2. **Configure Authentication** - Add [credentials](/docs/trunks/credentials) for password authentication or configure [IP ACLs](/docs/trunks/ip-acl) for IP-based authentication.
3. **Set Up Routing** - Configure [origination URIs](/docs/trunks/origination-uri) to define where outbound calls should be routed. Set priorities for failover and weights for load balancing.
4. **Test Your Trunk** - Configure your SIP client with the trunk's domain and credentials, then make a test call to verify everything is working correctly.

## What to do next

* **Connect Vapi or Retell** - Route your trunk directly into an AI voice agent platform. [Learn more](/docs/integrations) (5 min)
* **Buy a phone number** - Attach a DID number to your trunk for inbound calling. [Reference](/docs/account-phone-number)
* **Set up webhooks** - Get real-time HTTP callbacks for call start, answer, and hangup events. [Reference](/docs/trunks/webhook)
* **SIP trunking concepts** - How SIP auth, NAT traversal, and codec negotiation actually work. [Learn more](/docs/concepts/sip-trunking) (10 min read)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.