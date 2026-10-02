> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# WhatsApp Message Templates

> Create and submit WhatsApp message templates on Vobiz for Meta approval - required for all outbound business-initiated messages outside the 24-hour window.

[← Back to Messaging](/docs/whatsapp/messaging)

### Why Templates?

Meta requires template approval to prevent spam and ensure businesses send only relevant, valuable messages to customers. Templates can be used for notifications, customer support, marketing, and authentication messages.

### Template Use Cases

* Order confirmations and shipping updates
* Appointment reminders and confirmations
* Payment receipts and billing notifications
* Account alerts and security notifications
* Marketing promotions (with opt-in)

## Template Categories

Meta categorizes templates based on their purpose:

### UTILITY

Transactional messages providing important updates about ongoing transactions or customer accounts.

**Examples:**

* Order status updates
* Delivery notifications
* Account changes
* Payment confirmations

### MARKETING

Promotional messages including offers, announcements, and product recommendations.

**Examples:**

* New product launches
* Seasonal promotions
* Event invitations
* Flash sales

<Note>
  Marketing templates have stricter approval requirements and quality rating impacts.
</Note>

### AUTHENTICATION

One-time passcodes (OTP) for user authentication and verification.

**Examples:**

* Login verification codes
* Password reset codes
* Two-factor authentication

<Note>
  Authentication templates have expedited approval and special button types.
</Note>

## Creating Templates

### Via Vobiz Console

1. **Navigate to Templates** - Go to **Messaging → Templates** and click **Create Template**.
2. **Basic Information** - Enter the template name (lowercase, no spaces, use underscores), category (Utility, Marketing, or Authentication), and language (60+ supported).
3. **Template Content** - Compose your message with optional header (text/image/video/document), required body (max 1,024 characters), optional footer, and up to 3 buttons.
4. **Add Variables** - Use `{{1}}`, `{{2}}`, etc. for dynamic content.
5. **Submit for Approval** - Review and submit to Meta for approval.

### Via API

```bash theme={null}
curl -X POST https://api.vobiz.ai/api/v1/messaging/channels/{channelId}/templates \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "order_confirmation",
    "category": "UTILITY",
    "language": "en",
    "components": [
      {
        "type": "HEADER",
        "format": "TEXT",
        "text": "Order Confirmed!"
      },
      {
        "type": "BODY",
        "text": "Hi {{1}}, your order #{{2}} has been confirmed and will be delivered by {{3}}."
      },
      {
        "type": "FOOTER",
        "text": "Thank you for shopping with us!"
      },
      {
        "type": "BUTTONS",
        "buttons": [
          {
            "type": "URL",
            "text": "Track Order",
            "url": "https://example.com/track/{{1}}"
          }
        ]
      }
    ]
  }'
```

## Template Components

### Header (Optional)

Add visual impact with:

* **Text** - Bold heading (60 characters max).
* **Image** - JPEG or PNG (max 5MB).
* **Video** - MP4 (max 16MB).
* **Document** - PDF (max 100MB).

### Body (Required)

Main message content:

* Up to 1,024 characters.
* Supports variables `{{1}}` through `{{9}}`.
* Markdown formatting: `*bold*`, `_italic_`.
* Line breaks supported.

### Footer (Optional)

Small text at bottom:

* Up to 60 characters.
* No variables allowed.
* Often used for disclaimers or opt-out info.

### Buttons (Optional)

Up to 3 buttons. Choose from:

* **Quick Reply** - User taps to send predefined text back. Example: `{ type: 'QUICK_REPLY', text: 'Yes, confirm' }`.
* **URL** - Opens a website (can include variables). Example: `{ type: 'URL', text: 'View', url: 'https://...' }`.
* **Phone Number** - Initiates a phone call. Example: `{ type: 'PHONE_NUMBER', text: 'Call Us', phone: '+1234567890' }`.
* **Copy Code** *(Authentication only)* - One-tap to copy OTP code. Example: `{ type: 'COPY_CODE', example: '123456' }`.

### Example Template Structure

```json theme={null}
{
  "name": "order_confirmed",
  "category": "UTILITY",
  "language": "en",
  "components": [
    {
      "type": "HEADER",
      "format": "TEXT",
      "text": "Order Confirmed"
    },
    {
      "type": "BODY",
      "text": "Hi {{1}}, your order #{{2}} has been confirmed!\n\nEstimated delivery: {{3}}\n\nWe'll send you updates as your order ships."
    },
    {
      "type": "FOOTER",
      "text": "Reply STOP to unsubscribe"
    },
    {
      "type": "BUTTONS",
      "buttons": [
        {
          "type": "URL",
          "text": "Track Order",
          "url": "https://example.com/track/{{1}}"
        },
        {
          "type": "QUICK_REPLY",
          "text": "Contact Support"
        }
      ]
    }
  ]
}
```

## Approval Process

All templates must be approved by Meta before use. The approval process typically takes a few hours to 24 hours.

### Approval Timeline

1. **Submitted** - Template sent to Meta for review.
2. **`PENDING_REVIEW` (1–24 hours)** - Meta reviews content for policy compliance.
3. **`APPROVED`** - Template ready to use in campaigns and messages.

### Common Rejection Reasons

* **Spelling/grammar errors** - Templates must be professionally written.
* **Unclear purpose** - Message intent must be obvious.
* **Misleading content** - No deceptive or false information.
* **Poor variable usage** - Variables must make sense in context.
* **Policy violations** - Content violates WhatsApp Business Policy.
* **Marketing as utility** - Don't categorize promotional content as utility.

### Resubmitting Rejected Templates

If your template is rejected, review the rejection reason, make the necessary corrections, and resubmit. You can edit and resubmit templates any number of times.

## Using Templates

### Send Template via Console

1. Open a conversation in the inbox.
2. Click the template icon in the message composer.
3. Select an approved template from the list.
4. Fill in variable values.
5. Preview and send.

### Send Template via API

```bash theme={null}
curl -X POST https://api.vobiz.ai/api/v1/messaging/messages \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "channel_id": "0a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d",
    "waba_id": "123456789012345",
    "to": "+1234567890",
    "type": "template",
    "template": {
      "name": "order_confirmed",
      "language": {
        "code": "en"
      },
      "components": [
        {
          "type": "body",
          "parameters": [
            { "type": "text", "text": "John" },
            { "type": "text", "text": "12345" },
            { "type": "text", "text": "March 25, 2026" }
          ]
        },
        {
          "type": "button",
          "sub_type": "url",
          "index": 0,
          "parameters": [
            { "type": "text", "text": "12345" }
          ]
        }
      ]
    }
  }'
```

## Template Best Practices

* **Use clear, concise language** - Write professionally with proper grammar. Avoid abbreviations, slang, or overly casual language.
* **Provide context with variables** - Include sample values when submitting to show Meta how variables will be used. Example: `"Your order {{1}}"` with sample `"Your order #12345"`.
* **Choose the right category** - Utility for transactional, Marketing for promotional. Miscategorization leads to rejection.
* **Add value with every message** - Templates should provide clear value: updates, important information, or requested content.
* **Include opt-out information** - For marketing templates, include clear opt-out instructions in the footer.
* **Test before mass sending** - Send test messages to verify variables populate correctly before using in campaigns.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.