> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Console Walkthrough

> A screenshot-by-screenshot walkthrough of connecting a WhatsApp Business channel in the Vobiz Console - embedded signup with Meta, creating a template, running a campaign, and fixing the errors Meta returns along the way.

This walkthrough follows the **embedded signup** path - Meta's hosted onboarding flow, reached from **Connect with Provider** in the console. It is the fastest way to attach a number, because Meta creates the WhatsApp Business Account and issues the access token for you.

If you would rather enter your WABA ID, Phone Number ID, and access token by hand, use **Manual Setup** instead and follow the [BYON guide](/docs/whatsapp/channels/byon).

<Note>
  Before you start, have a phone number that can receive SMS or a voice call and is **not** currently registered on the WhatsApp or WhatsApp Business consumer app. See [Prerequisites](/docs/whatsapp/getting-started/prerequisites).
</Note>

## Connect a channel

<Steps>
  <Step title="Open Messaging in the console">
    Everything WhatsApp lives under **Messaging** in the console sidebar. Start at the overview, then open **Inbox**.

    ```text URL theme={null}
    https://console.vobiz.ai/app/messaging/overview
    ```

    Until a channel exists, the Inbox shows an empty state. Click **Connect Channel**.

    <Frame caption="Messaging → Inbox with no channel connected yet">
      <img src="https://mintcdn.com/vobizai/EZZXn_pZueq_Lc5K/images/whatsapp/connect-first-channel.png?fit=max&auto=format&n=EZZXn_pZueq_Lc5K&q=85&s=830a3961b066796db702569fd7e77077" alt="Empty Inbox state reading Connect your first WhatsApp channel, with a Connect Channel button" style={{maxWidth: '620px', margin: '0 auto', display: 'block'}} width="984" height="670" data-path="images/whatsapp/connect-first-channel.png" />
    </Frame>

    The same **Connect Channel** button is on **Messaging → Channels** at `https://console.vobiz.ai/app/messaging/channels`.
  </Step>

  <Step title="Choose the connection method">
    Choose **Connect with Provider** to use Meta's hosted flow.

    <Frame>
      <img src="https://mintcdn.com/vobizai/EZZXn_pZueq_Lc5K/images/whatsapp/connect-channel.png?fit=max&auto=format&n=EZZXn_pZueq_Lc5K&q=85&s=74257b062baab3a483fed7d4fb9116d6" alt="Connect Your Business Channel dialog with Connect with Provider and Manual Setup options" width="1096" height="830" data-path="images/whatsapp/connect-channel.png" />
    </Frame>
  </Step>

  <Step title="Log in to Facebook">
    A Facebook popup opens. Sign in with the account that **administers your Meta Business Account** - a personal account with no admin role on the business will get through login and then stall at the next screen.

    <Frame caption="Meta's login popup, opened by Connect with Provider">
      <img src="https://mintcdn.com/vobizai/EZZXn_pZueq_Lc5K/images/whatsapp/facebook-login.png?fit=max&auto=format&n=EZZXn_pZueq_Lc5K&q=85&s=c4819b3af9b472faee94afee83cb4552" alt="Facebook login popup window showing email address and password fields, a Log in button, and a Create new account option" style={{maxWidth: '420px', margin: '0 auto', display: 'block'}} width="1198" height="1589" data-path="images/whatsapp/facebook-login.png" />
    </Frame>

    <Tip>
      If the popup never appears, your browser blocked it. Allow popups for `console.vobiz.ai` and click **Connect with Provider** again.
    </Tip>
  </Step>

  <Step title="Grant access to Meta">
    Meta asks you to connect your business account to Vobiz. Review the Cloud API terms and click **Continue**.

    <Frame>
      <img src="https://mintcdn.com/vobizai/2P4BW4Ksaz1drCG8/images/whatsapp/meta-consent.png?fit=max&auto=format&n=2P4BW4Ksaz1drCG8&q=85&s=894e4ebb83742708aabd8801ab52c138" alt="Meta onboarding dialog asking to connect your business account to Vobiz" width="551" height="660" data-path="images/whatsapp/meta-consent.png" />
    </Frame>
  </Step>

  <Step title="Add your WhatsApp number">
    Select **Enter a new phone number**, pick the country code, and type the number you want to use for WhatsApp Business. Click **Next**.

    <Frame>
      <img src="https://mintcdn.com/vobizai/EZZXn_pZueq_Lc5K/images/whatsapp/add-phone-number.png?fit=max&auto=format&n=EZZXn_pZueq_Lc5K&q=85&s=604909e03916864242691bc011c4617b" alt="Meta dialog for adding a WhatsApp phone number with country code and number fields" width="1388" height="390" data-path="images/whatsapp/add-phone-number.png" />
    </Frame>

    <Warning>
      A WhatsApp number can be attached to exactly one provider at a time. If the number is already live with another provider, deregister it there first.
    </Warning>
  </Step>

  <Step title="Verify the number">
    Meta sends a six-digit code and defaults to **text message**.

    <Frame caption="Meta's verification step, defaulting to SMS">
      <img src="https://mintcdn.com/vobizai/2P4BW4Ksaz1drCG8/images/whatsapp/verify-phone-number.png?fit=max&auto=format&n=2P4BW4Ksaz1drCG8&q=85&s=708196898f5a0e319d653a1d3896dd6d" alt="Meta verify your phone number step showing six verification code boxes and a note that you can request a new code and change your verification method in 56 seconds" style={{maxWidth: '620px', margin: '0 auto', display: 'block'}} width="1100" height="410" data-path="images/whatsapp/verify-phone-number.png" />
    </Frame>

    **If you are verifying a Vobiz number, SMS will not arrive** - a Vobiz DID is a cloud number with no SIM behind it. Wait out the countdown, use **change your verification method**, and pick **Phone call** instead.

    You then need somewhere to answer that call. Open the [Vobiz WebRTC Playground](https://rtc-demo.vobiz.ai), connect it with your Auth ID and Auth Token, and attach the number to the playground application - the browser tab rings and reads you the code.

    <Card title="How to Receive an Inbound Call in Your Browser" icon="phone-arrow-down-left" href="/docs/guides/receive-inbound-call">
      Step-by-step: connect the playground, attach your DID, and answer the verification call in a browser tab. Set this up **before** you request the call.
    </Card>
  </Step>

  <Step title="Confirm the channel is connected">
    When Meta finishes, the dialog closes and your channel appears in **Messaging → Channels** with a **Connected** status, showing your display name and phone number.
  </Step>
</Steps>

## Collect your API credentials

Everything in the console is also available over the REST API. Your **Auth ID** and **Auth Token** are on the console dashboard, and the same pair authenticates both the Voice and WhatsApp APIs.

<Frame>
  <img src="https://mintcdn.com/vobizai/EZZXn_pZueq_Lc5K/images/whatsapp/api-credentials.png?fit=max&auto=format&n=EZZXn_pZueq_Lc5K&q=85&s=20790dc1c9bcc1769986b340448f9e93" alt="API credentials card on the Vobiz dashboard showing Auth ID and a masked Auth Token" width="858" height="552" data-path="images/whatsapp/api-credentials.png" />
</Frame>

Send them as `X-Auth-ID` and `X-Auth-Token` headers on every request:

```bash theme={null}
curl https://api.vobiz.ai/api/v1/messaging/channels/whatsapp \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: <your-auth-token>"
```

The `id` in that response is your `channel_id` - you need it to send messages and to create campaigns. See [API Authentication](/docs/whatsapp/api/authentication).

<Warning>
  The Auth Token is a secret. Keep it server-side, store it in an environment variable, and never ship it in client-side code.
</Warning>

## Where everything lives

Once the channel is connected, the rest of the product sits under **Messaging** in the sidebar.

<Frame>
  <img src="https://mintcdn.com/vobizai/2P4BW4Ksaz1drCG8/images/whatsapp/messaging-nav.png?fit=max&auto=format&n=2P4BW4Ksaz1drCG8&q=85&s=9011ccb86c94da106540a8a10f8ac13f" alt="Vobiz console sidebar showing the Messaging section with Overview, Inbox, Campaigns, Contacts, Channels, Templates, Webhooks, and Quick Replies" width="640" height="726" data-path="images/whatsapp/messaging-nav.png" />
</Frame>

A good order to work through it:

1. **Templates** - get one approved, because your first message to any new contact must be a template.
2. **Contacts** - add the people you want to reach, and tag them. Campaigns target by tag.
3. **Campaigns** - send an approved template to a tagged audience.
4. **Inbox** - handle the replies. A reply opens the 24-hour window, so you can answer with free-form text.
5. **Quick Replies** - saved responses agents insert by typing `/` in the composer.
6. **Webhooks** - forward `message.inbound` and `message.status` events to your own server.

## Send your first message

With the number verified, three screens take you from an empty account to a delivered message.

<Steps>
  <Step title="Create a template">
    Go to **Messaging → Templates** and click **Create Template**.

    ```text URL theme={null}
    https://console.vobiz.ai/app/messaging/templates
    ```

    <Frame caption="Create Message Template">
      <img src="https://mintcdn.com/vobizai/EZZXn_pZueq_Lc5K/images/whatsapp/create-template.png?fit=max&auto=format&n=EZZXn_pZueq_Lc5K&q=85&s=02db51c57a308013ece109f2c4661b47" alt="Create Message Template dialog with fields for template name, category, language, optional header, body with numbered placeholders, optional footer, a live message preview, and a Submit for Review button" style={{maxWidth: '560px', margin: '0 auto', display: 'block'}} width="946" height="1576" data-path="images/whatsapp/create-template.png" />
    </Frame>

    Name it in `lowercase_snake_case`, pick the category that matches what the copy actually does, and use numbered placeholders - `{{1}}`, `{{2}}` - in the body. Click **Submit for Review**.

    Meta reviews it, not Vobiz. Approval usually takes minutes; the categories and the rejection reasons are covered in [Fixing the errors Meta returns](#fixing-the-errors-meta-returns) below.
  </Step>

  <Step title="Add a contact">
    Go to **Messaging → Contacts** and click **Add Contact**.

    <Frame caption="Add Contact">
      <img src="https://mintcdn.com/vobizai/EZZXn_pZueq_Lc5K/images/whatsapp/add-contact.png?fit=max&auto=format&n=EZZXn_pZueq_Lc5K&q=85&s=88f66214cb3a94ffac2f1272f710a0a9" alt="Add Contact form with a country code selector, phone number field, name field, and a tags field with an Add button" style={{maxWidth: '560px', margin: '0 auto', display: 'block'}} width="1048" height="480" data-path="images/whatsapp/add-contact.png" />
    </Frame>

    Pick the country code, enter the number, and give the contact a name.

    <Tip>
      Add tags now, even for a single test contact. Campaigns target by tag, so an untagged contact list cannot be broadcast to later.
    </Tip>
  </Step>

  <Step title="Send the message">
    Go to **Messaging → Inbox** and start a **New Conversation**.

    ```text URL theme={null}
    https://console.vobiz.ai/app/messaging/inbox
    ```

    <Frame caption="New Conversation - start with an approved template">
      <img src="https://mintcdn.com/vobizai/2P4BW4Ksaz1drCG8/images/whatsapp/new-conversation.png?fit=max&auto=format&n=2P4BW4Ksaz1drCG8&q=85&s=680aa283476b75b46591e674532b4202" alt="New Conversation dialog with a recipient field, a matched contact card showing a name, number and tags, and a template selector below" style={{maxWidth: '620px', margin: '0 auto', display: 'block'}} width="1190" height="640" data-path="images/whatsapp/new-conversation.png" />
    </Frame>

    Type the recipient's number, pick the matching contact, choose an **approved** template, and fill in any variables it declares.

    <Note>
      Your first message to any contact must be a template. Free-form text is only allowed inside the 24-hour window that opens when the contact replies to you.
    </Note>
  </Step>
</Steps>

<Check>
  The conversation opens in the Inbox and the message shows a delivery status. If it shows as failed instead, the reason will be one of the errors below.
</Check>

## Fixing the errors Meta returns

Templates and sends are approved by Meta, not by Vobiz, so the rules below come from the WhatsApp Business Platform. These three account for almost every failure on a new account.

### "This template is named after a sample template"

<Frame>
  <img src="https://mintcdn.com/vobizai/2P4BW4Ksaz1drCG8/images/whatsapp/template-name-error.png?fit=max&auto=format&n=2P4BW4Ksaz1drCG8&q=85&s=8810d66bf8dc5f2571131a7e2d1507d7" alt="Create Message Template form showing a Meta error that the template name is reserved for a default sample template" width="1088" height="1678" data-path="images/whatsapp/template-name-error.png" />
</Frame>

Every WhatsApp Business Account is created with a sample template called `hello_world`, so Meta reserves that name and returns subcode `2388155` if you try to reuse it.

Pick a different name in `lowercase_snake_case` - for example `order_update_v1`.

<Tip>
  That reserved `hello_world` template is already **approved** on your account. Run **Sync templates** to pull it into Vobiz, and you have a guaranteed-working template to test your first send with - no parameters, language `en_US`.
</Tip>

### A template is rejected within seconds

<Frame>
  <img src="https://mintcdn.com/vobizai/2P4BW4Ksaz1drCG8/images/whatsapp/template-rejected.png?fit=max&auto=format&n=2P4BW4Ksaz1drCG8&q=85&s=282161f917b97c2bf1b0a83bb1396c08" alt="Template list showing a template with Utility category in Rejected status" width="2000" height="460" data-path="images/whatsapp/template-rejected.png" />
</Frame>

An instant rejection - no review queue - almost always means the **category does not match the content**. Meta classifies the copy automatically and rejects the submission when it disagrees with the category you picked.

| Category | What belongs in it |
| - | - |
| `UTILITY` | A transaction or account event the customer triggered: order confirmations, shipping updates, appointment reminders, receipts. |
| `MARKETING` | Promotions, offers, newsletters, announcements, and **generic welcome or greeting messages**. |
| `AUTHENTICATION` | One-time passcodes only. Gets the `COPY_CODE` button and expedited review. |

A plain "welcome to our service" message has no transaction behind it, so it belongs in `MARKETING`. Submitting it as `UTILITY` is the single most common cause of an instant rejection.

Two more things to check before you resubmit:

* **Use numbered placeholders.** Meta expects `{{1}}`, `{{2}}` in the body - not named ones like `{{name}}`.
* **Provide example values.** A template with a variable and no sample value is rejected.

Rejected names cannot be reused, so submit the corrected template under a new name.

### A campaign completes, but the message failed

<Frame>
  <img src="https://mintcdn.com/vobizai/EZZXn_pZueq_Lc5K/images/whatsapp/campaign-failed.png?fit=max&auto=format&n=EZZXn_pZueq_Lc5K&q=85&s=0f207b576ef608118e562fd9ae8084f4" alt="Campaign details panel showing status Completed with one recipient, zero sent, and one failed" width="1078" height="1436" data-path="images/whatsapp/campaign-failed.png" />
</Frame>

**Completed** means the campaign finished working through its recipient list - it is not a success count. Read the four counters below it. In the panel above, `Sent` is `0` and `Failed` is `1`, which means the message was rejected before WhatsApp ever accepted it.

The per-recipient reason is on the campaign recipients endpoint, in the `error_code` and `error_desc` fields:

```bash theme={null}
curl "https://api.vobiz.ai/api/v1/messaging/campaigns/{campaign_id}/recipients?status=failed" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: <your-auth-token>"
```

| Error code | Meaning | Fix |
| - | - | - |
| `131042` | Business eligibility - no payment method on the WABA | Add a payment method in Meta Business Manager under your WhatsApp Account's billing settings. Meta requires one on file before any send, even inside the free conversation tier. |
| `132001` | Template name or language does not exist | Check the language code on the template. A template registered as `en` will not match a send that asks for `en_US`. |
| `132000` | Parameter count mismatch | The template body expects more variables than the campaign supplied, or a mapped contact field was empty. |
| `133010` | Phone number not registered for the Cloud API | Finish number registration in Meta, then reconnect the channel. |
| `131026` | Recipient cannot receive the message | The destination number is not on WhatsApp. |

<Tip>
  **A 60-second way to tell account problems from template problems.** Send the pre-approved `hello_world` template to your own number. If it also fails, the problem is account-level - usually `131042` or `133010`, and nothing is wrong with your template. If it goes through, the problem is in your own template's language code or variables.
</Tip>

## Next steps

* [Receive an Inbound Call in Your Browser →](/docs/guides/receive-inbound-call) - answer the voice verification call on a Vobiz number with no handset.
* [Create Message Templates →](/docs/whatsapp/messaging/templates) - categories, components, and the approval process.
* [Using the Inbox →](/docs/whatsapp/messaging/inbox) - conversations, canned responses, and the 24-hour window indicator.
* [Send Message API →](/docs/whatsapp/api/send-message) - send text, media, and templates programmatically.
* [Webhooks →](/docs/whatsapp/webhooks) - receive inbound messages and delivery status on your own server.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.