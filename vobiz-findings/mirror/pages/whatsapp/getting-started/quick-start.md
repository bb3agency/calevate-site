> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Quick Start Guide

> Get up and running with Vobiz WhatsApp Business in under 5 minutes - connect your first channel and send messages via console and API examples.

[← Back to Prerequisites](/docs/whatsapp/getting-started/prerequisites)

### Time to Complete

**5 minutes** if you have all [prerequisites](/docs/whatsapp/getting-started/prerequisites) ready.

### What You'll Learn

* How to connect a WhatsApp Business channel
* How to send messages via the console
* How to send messages via the API
* How to receive and respond to messages

## Step 1: Connect Your Channel

First, let's connect your WhatsApp Business number to Vobiz. We'll use the BYON (Bring Your Own Number) method for this guide.

### 1. Navigate to Channels

1. Log in to the [Vobiz Console](https://console.vobiz.ai).
2. Go to **Messaging → Channels** in the left sidebar.
3. Click the **Connect Channel** button.

### 2. Choose Connection Mode

Select **Bring Your Own Number (BYON)** from the three options.

### 3. Enter Your Credentials

Fill in the following information from your Meta Business Manager:

* **WABA ID** - Your WhatsApp Business Account ID (found in Meta Business Manager).
* **Phone Number ID** - The ID of your phone number (from WhatsApp Manager).
* **Access Token** - System user access token with WhatsApp permissions.
* **Display Name** - Your business name as it will appear to customers.

**Need help finding these?** Check the [detailed BYON guide](/docs/whatsapp/channels/byon) for step-by-step instructions with screenshots.

### 4. Verify Your Phone Number

After submitting your credentials, you'll need to verify your phone number via OTP:

1. Choose verification method: **SMS** or **Voice call**.
2. Enter the 6-digit code you receive.
3. Click **Verify**.

### 5. Success!

Once verified, your channel will be connected and appear in your channels list.

<Check>
  You should now see your WhatsApp channel in the Channels list with a "Connected" status. The channel card will show your business name, phone number, and connection details.
</Check>

## Step 2: Send Your First Message

Now let's send a message! We'll show you two ways: using the Vobiz Console (no code) and using the API (for developers).

### Option A: Send via Console (No Code)

1. Go to **Messaging → Inbox**.
2. Click the **New Message** button or select an existing conversation.
3. Enter the recipient's phone number in E.164 format (e.g., `+1234567890`).
4. Type your message in the text box.
5. Click **Send** or press Enter.

**Tip:** You can also send images, videos, documents, and other media by clicking the attachment icon.

### Option B: Send via API (For Developers)

Use the Send Message API to programmatically send WhatsApp messages from your application:

```bash theme={null}
curl -X POST https://api.vobiz.ai/api/v1/messaging/messages \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "channel_id": "8f1c2d3e-4a5b-6c7d-8e9f-0a1b2c3d4e5f",
    "waba_id": "123456789012345",
    "to": "+1234567890",
    "type": "text",
    "text": {
      "body": "Hello! This is my first WhatsApp message from Vobiz!"
    }
  }'
```

**Replace these values:**

* `MA_XXXXXXXX` - Your Vobiz Auth ID (from the console, **Settings → API**). It starts with `MA_`.
* `YOUR_AUTH_TOKEN` - Your Vobiz Auth Token (a Bearer JWT also works).
* `channel_id` - The UUID of your connected channel.
* `waba_id` - Your WhatsApp Business Account ID.
* `+1234567890` - Recipient's phone number in E.164 format (leading `+`).

**Example response (`201 Created`):**

```json theme={null}
{
  "id": "8f1c2d3e-4a5b-6c7d-8e9f-0a1b2c3d4e5f",
  "channel_id": "0a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d",
  "to": "+1234567890",
  "type": "text",
  "status": "pending",
  "meta_message_id": "wamid.HBgM...",
  "created_at": "2026-03-19T10:30:00Z",
  "text": {
    "body": "Hello! This is my first WhatsApp message from Vobiz!"
  }
}
```

<Check>
  If you get a `201` response, your message was accepted! The `status` field
  starts at `pending` and moves through `sent` → `delivered` → `read`
  (or `failed`). Check your WhatsApp to see it delivered.
</Check>

<Warning>
  **24-Hour Window** - You can only send **template messages** to users who haven't messaged you in the last 24 hours. For the first message, make sure you're messaging a number that has initiated contact, or use a pre-approved template.
</Warning>

## Step 3: Receive Messages

When customers message your WhatsApp number, you'll see them in the Vobiz inbox in real-time.

### Via Console

1. Go to **Messaging → Inbox**.
2. Incoming messages appear in the conversation list on the left.
3. Click a conversation to view the message thread.
4. Reply directly in the text box at the bottom.

**Real-time updates:** The inbox updates in real-time via WebSocket, so you'll see new messages instantly without refreshing.

## Step 4: Set Up Webhooks (Optional)

For developers: Set up webhooks to receive real-time notifications when messages arrive, get delivered, or are read.

### Quick Webhook Setup

1. Go to **Messaging → Webhooks**.
2. Click **Create Webhook**.
3. Enter your webhook URL (must be publicly accessible and HTTPS).
4. Select the events you want to receive (e.g., `message.inbound`, `message.status`).
5. Copy the signing secret to verify webhook payloads (the `X-Webhook-Signature` header).
6. Click **Save**.

**Example webhook payload (`message.inbound`):**

```json theme={null}
{
  "type": "message.inbound",
  "timestamp": "2026-03-19T10:35:00Z",
  "channel_id": "0a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d",
  "message": {
    "id": "9b2c3d4e-5f6a-7b8c-9d0e-1f2a3b4c5d6e",
    "from": "+1234567890",
    "type": "text",
    "text": {
      "body": "Hi, I need help with my order"
    },
    "timestamp": "2026-03-19T10:35:00Z"
  }
}
```

**Learn more:** Check out the [Webhooks documentation](/docs/whatsapp/webhooks) for detailed guides on implementing webhook handlers, verifying signatures, and handling different event types.

## Congratulations!

You've successfully connected your WhatsApp channel and sent your first message. Here's what to explore next:

* [Create Message Templates →](/docs/whatsapp/messaging/templates) - Learn how to create approved templates for notifications and marketing messages.
* [Master the Inbox →](/docs/whatsapp/messaging/inbox) - Learn to manage conversations and reply to customers.
* [Explore the API →](/docs/whatsapp/api) - Full API documentation for developers.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.