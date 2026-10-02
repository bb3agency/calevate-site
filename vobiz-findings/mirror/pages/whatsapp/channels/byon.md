> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Bring Your Own Number (BYON) Setup Guide

> Connect your existing WhatsApp Business number to Vobiz using BYON - step-by-step setup guide covering OTP verification, Meta Business Manager, and channel activation.

[← Back to Channel Management](/docs/whatsapp/channels)

### Time Required

**15–20 minutes** to complete all steps if you have Meta Business Manager access.

### Why Choose BYON?

* Keep your existing business phone number
* No additional number costs
* Full control over your WhatsApp Business Account
* Direct integration with Meta's platform

## Prerequisites

Before starting, ensure you have:

* **Meta Business Manager Account** - Create one at [business.facebook.com](https://business.facebook.com).
* **Phone Number** - A phone number that can receive SMS or voice calls for verification.
* **Admin Access** - Admin or Developer role in Meta Business Manager.
* **Vobiz Account** - Active account at [console.vobiz.ai](https://console.vobiz.ai).

<Note>
  The phone number you use cannot be currently registered with WhatsApp or WhatsApp Business app.
</Note>

## Step 1: Set Up Meta Business Manager

1. **Access Meta Business Settings** - Go to [business.facebook.com](https://business.facebook.com) and log in with your Facebook account.
2. **Create or Select Business** - If you do not have a business, click **Create Account** and fill in your business details. Otherwise, select your existing business from the dropdown.

## Step 2: Create a WhatsApp Business Account (WABA)

### 1. Navigate to WhatsApp Accounts

* Click on the menu icon in the top-left corner.
* Select **Accounts → WhatsApp Accounts**.
* Click the **Add** button.

### 2. Create WhatsApp Business Account

Fill in the following information:

* **WhatsApp Business Account Name** - Your business name.
* **Business Manager** - Select your business.
* **Time Zone** - Your business timezone.

### 3. Save WABA ID

After creation, you will see your **WhatsApp Business Account ID (WABA ID)**. Copy it - you will need it later to connect to Vobiz.

The WABA ID is a numeric value, typically 15–17 digits. Example: `102290129340398`.

## Step 3: Add and Verify Phone Number

### 1. Add Phone Number

* In your WhatsApp Business Account, click **Add phone number**.
* Enter your phone number in international format (e.g., `+1 234 567 8900`).
* Select verification method: **SMS** or **Voice call**.

### 2. Verify Phone Number

Enter the 6-digit verification code you receive via SMS or voice call.

<Check>
  Once verified, your phone number will show a green checkmark.
</Check>

### 3. Save Phone Number ID

Click on your phone number to view details. Copy the **Phone Number ID** - you will need it for Vobiz.

The Phone Number ID is a numeric value. Example: `106540932419283`.

## Step 4: Generate System User Access Token

### 1. Create System User

* Go to **Business Settings → Users → System Users**.
* Click **Add**.
* Enter a name (e.g., "Vobiz Integration").
* Set role to **Admin**.
* Click **Create System User**.

### 2. Assign WhatsApp Account to System User

* Click on your newly created system user.
* Click **Add Assets**.
* Select **WhatsApp Accounts**.
* Select your WhatsApp Business Account.
* Enable **Full control** permission.
* Click **Save Changes**.

### 3. Generate Access Token

* In the system user settings, click **Generate New Token**.
* Select your app (or create a new one if needed).
* Select the following permissions:
  * `whatsapp_business_messaging`
  * `whatsapp_business_management`
* Click **Generate Token**.

<Warning>
  Copy the access token immediately and store it securely. You will not be able to see it again. This token provides full access to your WhatsApp Business Account.
</Warning>

## Step 5: Connect to Vobiz

### 1. Open Vobiz Console

* Log in to [console.vobiz.ai](https://console.vobiz.ai).
* Go to **Messaging → Channels**.
* Click **Connect Channel**.
* Select **Bring Your Own Number (BYON)**.

### 2. Enter Connection Details

Fill in the form with the information you collected from Meta:

* **WABA ID** - Your WhatsApp Business Account ID from Step 2 (example: `102290129340398`).
* **Phone Number ID** - Your phone number ID from Step 3 (example: `106540932419283`).
* **Access Token** - System user access token from Step 4 (starts with `EAA...`).
* **Display Name** - How your business name appears to customers (example: `Acme Corp Support`).

### 3. Verify and Connect

Click **Connect Channel**. Vobiz will verify your credentials and establish the connection.

<Check>
  If all credentials are correct, your channel will be connected and appear in your channels list with a "Connected" status.
</Check>

## Troubleshooting

### "Invalid Access Token" Error

**Possible causes:**

* Token expired or was regenerated.
* Token does not have the required permissions.
* System user does not have access to the WhatsApp account.

**Solution:**

* Generate a new access token with correct permissions.
* Verify system user has "Full control" on the WhatsApp account.
* Ensure you copied the complete token without extra spaces.

### "Phone Number Not Found" Error

**Possible causes:**

* Incorrect Phone Number ID.
* Phone number not verified in Meta.
* Phone number not associated with the WABA.

**Solution:**

* Double-check the Phone Number ID from Meta Business Manager.
* Ensure phone number is verified (green checkmark).
* Confirm phone number is under the correct WABA.

### "WABA Not Accessible" Error

**Possible causes:**

* Incorrect WABA ID.
* WABA is suspended or restricted.
* System user does not have access.

**Solution:**

* Verify the WABA ID from Meta Business Settings.
* Check WABA status in Meta Business Manager.
* Ensure system user has been assigned to the WABA.

### Can't Generate Access Token

**Possible causes:**

* No app created in Meta for Developers.
* Insufficient permissions in Business Manager.

**Solution:**

* Create a Meta app at [developers.facebook.com](https://developers.facebook.com).
* Add WhatsApp product to your app.
* Ensure you have Admin role in Business Manager.

## Need More Help?

If you are still experiencing issues, our support team is here to help.

[Contact Support →](mailto:support@vobiz.ai)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.