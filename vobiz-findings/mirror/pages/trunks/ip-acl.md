> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# IP Access Control Lists

> Manage IP-based authentication for your Vobiz SIP trunks using IPv4 whitelisting - restrict trunk access to known PBX and softswitch addresses.

Manage IP-based authentication for your SIP trunks using IP whitelisting.

## Introduction

IP Access Control Lists (IP ACLs) provide IP-based authentication for your SIP trunks. By whitelisting specific IPv4 addresses, you can allow calls from trusted sources without requiring username/password authentication. This is ideal for scenarios with static IP addresses such as PBX systems, SIP gateways, or carrier connections.

Multiple IP addresses can be whitelisted for a single trunk, allowing connections from different locations or devices. Each IP ACL entry can be individually enabled or disabled, providing flexible control over which sources can authenticate to your trunk.

<Note>
  **IPv4 Only:** Currently, IP ACL only supports IPv4 addresses. IPv6 support is not available at this time.

  **Static IPs Required:** IP-based authentication works best with static IP addresses. If your IP address changes frequently, consider using credential-based authentication instead.
</Note>

## Use Cases

* **Office PBX systems** - Perfect for on-premises PBX systems with static public IP addresses. Simplifies configuration by eliminating the need to manage credentials on the PBX.
* **SIP gateway integration** - Ideal for SIP gateways and Session Border Controllers (SBCs) that operate from known, fixed IP addresses. Provides faster authentication without credential exchange.
* **Carrier interconnections** - Commonly used for trunk connections with telecom carriers who provide calls from specific IP addresses. Standard practice in carrier-to-carrier peering.
* **Data center deployments** - Excellent for cloud or data center deployments where your infrastructure has dedicated static IPs. Reduces authentication overhead and improves performance.

## IP ACL vs Credentials

| Feature | IP ACL | Credentials |
| - | - | - |
| Best For | Static IP addresses | Dynamic IP addresses |
| Setup Complexity | Simple (no client config) | Moderate (configure username/password) |
| Security Level | Good (IP-based) | Better (cryptographic) |
| Performance | Faster (no auth exchange) | Slightly slower (auth required) |
| NAT Compatibility | Limited (public IP only) | Excellent (works anywhere) |
| Combined Use | Both can be used together for maximum security | Both can be used together for maximum security |

<Info>
  **Maximum Security:** For production environments, consider using both IP ACL and credentials together. This requires authentication from both a whitelisted IP address AND valid credentials, providing defense in depth.
</Info>

## Available Operations

1. [The IP ACL Object](/docs/trunks/ip-acl/ip-acl-object) - Learn about the structure and attributes of IP ACL objects
2. [Create IP ACL](/docs/trunks/ip-acl/create-ip-acl) - Whitelist a new IPv4 address for trunk authentication
3. [Retrieve All IP ACLs](/docs/trunks/ip-acl/retrieve-all-ip-acls) - List all IP ACL entries for a trunk with pagination support
4. [Update IP ACL](/docs/trunks/ip-acl/update-ip-acl) - Modify existing IP ACL properties like IP address, status, or description
5. [Delete IP ACL](/docs/trunks/ip-acl/delete-ip-acl) - Permanently remove an IP address from the whitelist

<Warning>
  **NAT Considerations:** If your SIP client is behind NAT, the source IP address will be the public IP of your router/firewall, not the private IP of the device.

  You can find your public IP by visiting services like `https://api.ipify.org`
</Warning>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.