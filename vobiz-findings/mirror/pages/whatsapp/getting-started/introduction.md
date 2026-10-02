> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Introduction to WhatsApp Business

> Discover how the WhatsApp Business API works on Vobiz - enterprise messaging at scale in 130+ countries with templates, webhooks, and a no-code campaign builder.

## What is WhatsApp Business API?

The WhatsApp Business API is an enterprise solution that lets businesses communicate with customers at scale on WhatsApp. Unlike the WhatsApp Business app (designed for small businesses), the API provides:

* Programmatic access to send and receive messages
* Support for multiple agents and team collaboration
* Integration with existing business systems (CRM, helpdesk, etc.)
* Template-based messaging for notifications and marketing
* Webhook support for real-time event processing
* Unlimited message volume (within WhatsApp's rate limits)

### Reach 2+ Billion Users

WhatsApp has over 2 billion active users worldwide, making it one of the most effective channels for customer engagement. WhatsApp messages have a **98% open rate** - significantly higher than email or SMS.

## Why Use Vobiz WhatsApp?

Vobiz provides a complete WhatsApp Business platform that combines ease of use with powerful developer capabilities:

### For Business Users

* Easy-to-use web console for managing conversations
* Visual campaign builder (no coding required)
* Contact management with CSV import/export
* Template creation and approval tracking
* Real-time analytics and reporting

### For Developers

* Complete REST API with full documentation
* Real-time webhooks for event processing
* Support for all WhatsApp message types
* Programmatic campaign management
* Easy integration with existing systems

### All-in-One Platform

Unlike other WhatsApp providers, Vobiz integrates WhatsApp with voice (SIP), SMS, and AI in a single unified platform. Build multi-channel communication experiences without managing multiple vendors.

## Key Capabilities

* **Multi-channel connection** - Connect WhatsApp Business channels in three ways: BYON (use your existing phone number), buy a new WhatsApp-capable number from Vobiz, or link Meta-verified numbers instantly.
* **Rich messaging** - Send text, images, videos, documents, audio files, locations, and interactive messages (buttons, lists). Support for template messages approved by Meta for notifications and marketing.
* **Broadcast campaigns** - Create personalized template-based campaigns for thousands of contacts. Segment audiences by tags, schedule for optimal times, and track delivery, reads, and engagement in real-time.
* **Real-time integration** - Receive instant webhooks for incoming messages, delivery updates, and conversation events. Integrate WhatsApp into your CRM, helpdesk, or custom applications seamlessly.

## Common use cases

### Customer Support

Provide instant support via WhatsApp. Use AI chatbots for common queries, escalate complex issues to human agents, and maintain conversation history across sessions.

When a customer messages you, Vobiz delivers a `message.inbound` webhook to your endpoint. Reply by calling the send-message API:

```bash theme={null}
# Auto-respond to a customer message
curl -X POST https://api.vobiz.ai/api/v1/messaging/messages \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "channel_id": "0a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d",
    "waba_id": "123456789012345",
    "to": "+1234567890",
    "type": "text",
    "text": { "body": "Hi! How can I help you today?" }
  }'
```

### Marketing Campaigns

Send personalized promotional messages to segmented audiences. Track engagement, measure ROI, and optimize campaigns with real-time analytics.

Example: `"Hi {{1}}, your order {{2}} is ready for pickup!"` with 98% open rates.

### Transactional Notifications

Send order confirmations, shipping updates, appointment reminders, and payment receipts. Reduce no-shows and improve customer satisfaction with timely notifications.

### Lead Qualification

Engage website visitors via WhatsApp, collect lead information through conversational flows, and sync qualified leads to your CRM automatically.

## Next Steps

Now that you understand what Vobiz WhatsApp can do, here's how to get set up:

* [Check Prerequisites →](/docs/whatsapp/getting-started/prerequisites) - Review what you need before getting started (Meta Business Account, phone number, etc.)
* [Quick Start Guide →](/docs/whatsapp/getting-started/quick-start) - Connect your first channel and send messages in under 5 minutes.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.