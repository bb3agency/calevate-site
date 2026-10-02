> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Credentials

> Manage SIP credentials for username and password authentication on your Vobiz trunks - create, list, rotate, and revoke credentials per trunk.

Manage SIP credentials for username/password authentication on your trunks.

## Introduction

Credentials provide username/password-based authentication for your SIP trunks. Each credential consists of a unique username and password combination that SIP clients can use to authenticate when making or receiving calls through your trunk.

Multiple credentials can be created for a single trunk, allowing different users, devices, or applications to connect with separate authentication details. This provides flexibility in managing access and tracking usage across different endpoints.

<Info>
  **Security Note:** Passwords are write-only and never returned in API responses. Once set, passwords cannot be retrieved - only updated or reset.

  **Best Practice:** Use strong passwords (minimum 8 characters) with a mix of uppercase, lowercase, numbers, and special characters. Rotate credentials regularly for enhanced security.
</Info>

## Use Cases

* **Dynamic IP environments** - Perfect for remote workers, mobile devices, or any scenario where the source IP address changes frequently. Username/password authentication works regardless of network location.
* **Multi-user access** - Create separate credentials for different users or departments, making it easier to track usage and manage access permissions independently.
* **SIP client integration** - Configure softphones, desk phones, or PBX systems with unique credentials for reliable authentication without IP whitelisting requirements.
* **Combined authentication** - Use credentials alongside IP ACL for maximum security - requiring both valid credentials AND whitelisted IP addresses for authentication.

## Available Operations

1. [The Credential Object](/docs/trunks/credentials/credential-object) - Learn about the structure and attributes of credential objects
2. [Create Credential](/docs/trunks/credentials/create-credential) - Add new SIP credentials to a trunk with username and password
3. [Retrieve All Credentials](/docs/trunks/credentials/retrieve-all-credentials) - List all credentials associated with a trunk with pagination support
4. [Update Credential](/docs/trunks/credentials/update-credential) - Modify existing credential properties like password, status, or description
5. [Delete Credential](/docs/trunks/credentials/delete-credential) - Permanently remove credentials from a trunk

<Tip>
  **Quick Start:** Begin by reviewing the credential object structure, then create your first credential to start authenticating SIP clients to your trunk.
</Tip>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.