> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Prerequisites

> Complete every prerequisite for WhatsApp Business on Vobiz - Meta Business Account, verified phone number, and approved display name - in 15–30 minutes.

[← Back to Introduction](/docs/whatsapp/getting-started/introduction)

### Time Required

Setting up all prerequisites typically takes **15–30 minutes** if you don't have a Meta Business Account yet.

## 1. Meta Business Account

A Meta Business Account is required to use the WhatsApp Business API. This free account gives you access to Meta's business tools, including WhatsApp, Facebook, and Instagram.

### Creating a Meta Business Account

1. Go to [business.facebook.com](https://business.facebook.com) and log in with your personal Facebook account.
2. Click **Create Account** in the top right.
3. Enter your business name and details. Use your actual business name - you'll need to verify it later for production access.
4. Complete the verification process.

### Important Notes

* You need a personal Facebook account to create a Business Account.
* The business name should match your official business registration.
* For production use, Meta will require business verification (can take 1–3 days).

## 2. WhatsApp Business Account (WABA)

Within your Meta Business Account, create a WhatsApp Business Account (WABA). This is where you manage your WhatsApp phone numbers and settings.

### Creating a WABA

1. In Meta Business Manager, go to **WhatsApp Accounts** in the left menu.
2. Click **Add** and select **Create a WhatsApp Business Account**.
3. Follow the setup wizard to create your WABA.
4. Save your **WABA ID** - you'll need this for Vobiz.

**Finding your WABA ID:** Go to WhatsApp Manager → Settings → Business Info. Your WABA ID is displayed at the top (format: `123456789012345`).

## 3. Phone Number Requirements

You need a phone number to use with WhatsApp Business. The number must meet the following requirements:

### Phone Number Rules

* **Must be able to receive voice calls or SMS** - Used for verification via OTP (One-Time Password).
* **Cannot be registered with WhatsApp Business app or WhatsApp Messenger** - If it's currently in use, you'll need to deregister it first.
* **Must be in a supported country** - Most countries are supported. Check Meta's documentation for the full list.
* **Recommended: use a dedicated business number** - avoid using personal numbers for business communications.

### Option 1: Bring Your Own Number (BYON)

Use an existing phone number you already own.

* Free (no additional cost)
* Requires OTP verification
* Takes 5–10 minutes to set up

### Option 2: Buy from Vobiz

Purchase a new WhatsApp-capable number directly from Vobiz.

* Instant setup (no verification needed)
* Choose from available countries
* Monthly fee applies

## 4. Vobiz Account

An active Vobiz account is required to use the WhatsApp Business integration.

### What You'll Need

* **Active Vobiz account** - sign up at [console.vobiz.ai](https://console.vobiz.ai) if you don't have one.
* **API credentials (for developers)** - get your Auth ID (`MA_XXXXXXXX`) and Auth Token from the Vobiz Console under **Settings → API**.
* **Sufficient balance** - WhatsApp messages are charged per conversation; add credits to your Vobiz account.

## 5. Optional Requirements

These are optional but recommended for a better experience:

* **Meta App** *(for embedded signup)* - required only if you want to use Meta's embedded signup flow; you can also manually enter credentials.
* **Webhook endpoint** *(for developers)* - a publicly accessible endpoint to receive real-time notifications for incoming messages and events. You can set this up later.
* **Business verification** *(for production)* - Meta requires business verification for production use and higher message limits. This involves submitting business documents and takes 1–3 business days.

### Ready to Continue?

Once you have all the prerequisites in place, you're ready to connect your first WhatsApp channel.

[Continue to Quick Start Guide →](/docs/whatsapp/getting-started/quick-start)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.