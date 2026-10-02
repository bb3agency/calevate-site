> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz WhatsApp Business API Reference

> Use the Vobiz WhatsApp Business API reference to send messages and manage channels, contacts, templates, campaigns, conversations, calls, and webhooks.

This reference covers the Vobiz WhatsApp Business API. For programmable voice, SIP trunks, phone numbers, recordings, and account APIs, use the [main Vobiz API reference](/docs/api-reference).

## API Features

* **RESTful design** - Intuitive, predictable endpoints.
* **Secure authentication** - Header-based access control.
* **JSON responses** - Easy to parse and integrate.
* **Comprehensive docs** - Detailed examples for all endpoints.

## Base URL

All API requests should be made to the following base URL:

```http theme={null}
https://api.vobiz.ai/api/v1/messaging
```

### API Versioning

The API version is included in the URL path (`/v1/`). When we release breaking changes, we'll create a new version (v2, v3, etc.) while maintaining support for older versions.

## Authentication

The Vobiz API uses header-based authentication with two required headers for every request:

* **`X-Auth-ID`** - Your account's authentication ID (`MA_…`), found in the Vobiz Console under **Settings → API**.
* **`X-Auth-Token`** - Your secret authentication token. Keep this secure and never expose it in client-side code.

A JWT obtained at login is also accepted via the `Authorization: Bearer <token>` header.

### Security Best Practices

* Never commit API credentials to version control.
* Use environment variables to store credentials.
* Only make API calls from server-side code, never from browsers.
* Use HTTPS for all API requests (HTTP is not supported).

[View Full Authentication Guide →](/docs/whatsapp/api/authentication)

## API Endpoints

The Vobiz API is organized into logical endpoint groups. All paths are relative to the base URL `https://api.vobiz.ai/api/v1/messaging`.

### Messaging

Send WhatsApp messages.

| Method | Path | Description |
| - | - | - |
| `POST` | `/messages` | Send a message |

[View Messaging API →](/docs/whatsapp/api/send-message)

### Channels

Manage WhatsApp Business channels.

| Method | Path | Description |
| - | - | - |
| `POST` | `/channels/whatsapp` | Create channel |
| `GET` | `/channels/whatsapp` | List channels |
| `POST` | `/channels/whatsapp/embedded-signup` | Complete embedded signup |
| `PUT` | `/channels/whatsapp/{id}` | Update channel |
| `DELETE` | `/channels/whatsapp/{id}` | Delete channel |

[View Channels API →](/docs/whatsapp/api/channels)

### Numbers

Search, order, and verify WhatsApp numbers.

| Method | Path | Description |
| - | - | - |
| `GET` | `/numbers/whatsapp/availability` | Check number availability |
| `POST` | `/numbers/whatsapp/orders` | Order a WhatsApp number |
| `POST` | `/numbers/whatsapp/bring-your-own/verify` | Verify a BYON number |
| `POST` | `/numbers/whatsapp/bring-your-own/confirm` | Confirm a BYON number |

[View Numbers API →](/docs/whatsapp/api/numbers)

### Conversations

List conversations and paginate message history.

| Method | Path | Description |
| - | - | - |
| `GET` | `/conversations` | List conversations |
| `GET` | `/conversations/{id}/messages` | List messages in a conversation |

[View Conversations API →](/docs/whatsapp/api/conversations)

### Contacts

CRUD contacts and bulk import from CSV.

| Method | Path | Description |
| - | - | - |
| `GET` | `/contacts` | List contacts |
| `GET` | `/contacts/{id}` | Get a contact |
| `POST` | `/contacts` | Create a contact |
| `PUT` | `/contacts/{id}` | Update a contact |
| `DELETE` | `/contacts/{id}` | Delete a contact |
| `POST` | `/contacts/import` | Bulk import contacts |

[View Contacts API →](/docs/whatsapp/api/contacts)

### Templates

List, create, and sync Meta-approved message templates.

| Method | Path | Description |
| - | - | - |
| `GET` | `/channels/{channelId}/templates` | List templates |
| `POST` | `/channels/{channelId}/templates` | Create a template |
| `POST` | `/channels/{channelId}/templates/sync` | Sync templates from Meta |

[View Templates API →](/docs/whatsapp/api/templates)

### Campaigns

Create and manage broadcast campaigns to segmented audiences.

| Method | Path | Description |
| - | - | - |
| `GET` | `/campaigns` | List campaigns |
| `POST` | `/campaigns` | Create a campaign |
| `GET` | `/campaigns/{id}` | Get a campaign |
| `POST` | `/campaigns/{id}/pause` | Pause a campaign |
| `POST` | `/campaigns/{id}/resume` | Resume a campaign |
| `POST` | `/campaigns/{id}/cancel` | Cancel a campaign |
| `DELETE` | `/campaigns/{id}` | Delete a campaign |
| `GET` | `/campaigns/{id}/recipients` | List campaign recipients |

[View Campaigns API →](/docs/whatsapp/api/campaigns)

### Canned Responses

Manage saved reply shortcuts for agents.

| Method | Path | Description |
| - | - | - |
| `GET` | `/canned-responses` | List canned responses |
| `POST` | `/canned-responses` | Create a canned response |
| `DELETE` | `/canned-responses/{id}` | Delete a canned response |

[View Canned Responses API →](/docs/whatsapp/api/canned-responses)

### Calls

Initiate and manage WhatsApp voice calls.

| Method | Path | Description |
| - | - | - |
| `POST` | `/calls/whatsapp` | Initiate a WhatsApp call |
| `POST` | `/calls/whatsapp/action` | Perform a call action |
| `GET` | `/calls/whatsapp/logs` | List call logs |

[View Calls API →](/docs/whatsapp/api/calls)

### Webhook Subscriptions

Manage Vobiz webhook subscriptions.

| Method | Path | Description |
| - | - | - |
| `POST` | `/webhooks` | Create a webhook subscription |
| `GET` | `/webhooks` | List webhook subscriptions |
| `DELETE` | `/webhooks/{id}` | Delete a webhook subscription |

[View Webhooks API →](/docs/whatsapp/api/webhooks)

### Realtime

Connect to the realtime WebSocket for live message and conversation updates:

```http theme={null}
wss://api.vobiz.ai/api/v1/messaging/ws
```

## API Documentation

* [Authentication Guide →](/docs/whatsapp/api/authentication)
* [Send Message API →](/docs/whatsapp/api/send-message)
* [Channels API →](/docs/whatsapp/api/channels)
* [Webhooks Documentation →](/docs/whatsapp/webhooks)
* [Message Templates Guide →](/docs/whatsapp/messaging/templates)
* [Channel Setup Guide →](/docs/whatsapp/channels/byon)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.