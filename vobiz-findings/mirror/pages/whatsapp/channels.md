> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Channel Management

> Connect and manage WhatsApp Business channels on Vobiz - choose from multiple connection methods, run multiple channels, and monitor performance.

## What is a Channel?

A channel represents a WhatsApp Business phone number connected to Vobiz. Each channel can handle conversations, send messages, and run campaigns independently. You can connect multiple channels to manage different business lines, regions, or brands.

## Connection Methods

Choose the connection method that best fits your needs:

* **Bring Your Own Number (BYON)** - Connect an existing WhatsApp Business number using credentials from Meta Business Manager. Best when you already have a verified WABA. [Setup guide →](/docs/whatsapp/channels/byon)
* **Buy a new number from Vobiz** - Purchase a new WhatsApp-capable number directly from Vobiz with instant provisioning. Best for new deployments without an existing number.
* **Embedded Signup** - Use Meta's OAuth flow to onboard a WABA directly from your application. Best for SaaS apps onboarding many sub-merchants.

## Channel Types

### Production Channels

Fully verified WhatsApp Business channels used for live customer communications. These channels have higher rate limits and can send messages to any verified contact.

* Business verification required
* Higher messaging limits (1,000+ per day)
* Display name shows verified badge
* Can use all template categories

### Test/Sandbox Channels

Development channels for testing integrations and workflows before going live. Limited to verified test numbers.

* No business verification needed
* Limited to 50 messages per day
* Can only message verified test numbers
* Ideal for development and testing

## Managing Channels

Once connected, you can manage all aspects of your channels from the Vobiz Console:

### Channel Dashboard

The channels dashboard displays:

* **Connection status** - Active, disconnected, or pending verification.
* **Message limits** - Current usage vs. daily limits.
* **Quality rating** - Meta's quality score (Green, Yellow, Red).
* **Active conversations** - Number of ongoing 24-hour windows.
* **Recent activity** - Messages sent/received in last 7 days.

## Best Practices

* **Monitor quality rating** - Maintain a high quality rating by responding promptly to customers, avoiding spam, and ensuring your messages provide value. A low quality rating can result in reduced messaging limits.
* **Use separate channels for different purposes** - Create dedicated channels for different use cases (e.g., customer support, marketing, notifications) to better organize conversations and track performance.
* **Keep credentials secure** - Never share your WhatsApp API access tokens or credentials. Rotate tokens regularly and use webhook signature verification to ensure security.
* **Respect rate limits** - Each channel has daily messaging limits based on your quality rating and phone number tier. Exceeding these limits will result in failed message deliveries. Monitor your usage in the dashboard.

## Next Steps

* [Set up BYON channel →](/docs/whatsapp/channels/byon)
* [Start sending messages →](/docs/whatsapp/messaging)
* [Learn about the inbox →](/docs/whatsapp/messaging/inbox)
* [Manage templates →](/docs/whatsapp/messaging/templates)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.