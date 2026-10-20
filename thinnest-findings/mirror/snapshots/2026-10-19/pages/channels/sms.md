> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# SMS

> Let your agent text customers in India — through your own SMS provider, under your own DLT sender ID.

Your agent can send a customer an SMS **while it is talking to them** (a booking
link mid-call, an address they asked for) and **after the call ends** (a thank-you
with your booking link, or a "sorry we missed you"). See
[Actions](/agent/actions#reaching-the-customer-on-a-different-channel) and
[After the call](/agent/after-the-call).

**SMS goes through your own provider account.** You connect your SMS provider, it
sends under your own sender ID, and **it bills you directly**. Nothing for SMS is
taken from your wallet here.

<Note>
  **SMS reaches Indian mobile numbers only.** Every business SMS in India has to
  follow the DLT rules below, and those apply to Indian numbers. For customers
  elsewhere, use [WhatsApp](/channels/whatsapp).
</Note>

## What DLT asks of you first

India's telecom rules (TRAI's DLT) mean an operator only delivers a business SMS
that matches what you registered in advance. You register once on any one DLT
portal (Jio, Airtel, Vi, BSNL…), and it works on every network. If your business
already sends OTPs or order updates, you probably have all of this.

| You need | What it is | Where it comes from |
| - | - | - |
| **Entity (PE) ID** | Your business's registration on DLT, usually 19 digits | Your DLT portal, once your business is approved |
| **Sender ID (header)** | The six letters the message shows as coming from, like `ACMEIN` | Registered on your DLT portal |
| **Templates** | The exact words of each message, with `{#var#}` wherever the text changes | Registered and approved on your DLT portal; each gets a **DLT template ID** |
| **Your provider in your PE–TM chain** | Telling DLT which provider sends for you | Your DLT portal — add your provider's telemarketer ID |

<Warning>
  **Do the PE–TM chain step, or every message is dropped.** Since 2024 operators
  reject a message unless your DLT registration names the provider that delivered
  it. Your provider's support team will give you their telemarketer ID if it is
  not below.
</Warning>

## Providers you can connect

| Provider | You'll need | Templates also need | Telemarketer ID |
| - | - | - | - |
| **MSG91** | Auth key | MSG91's own template ID (from its dashboard) | `1302157225275643280` |
| **Exotel** | Account SID, API key, API token, region (`in` or `sg`) | — | ask Exotel |
| **Gupshup Enterprise SMS** | User ID, password | — | ask Gupshup |
| **Infobip** | Your API base URL (like `xxxxx.api.infobip.com`), API key | — | `110200001152` |
| **Vonage** | API key, API secret | — | ask Vonage |
| **Fast2SMS** | API key | Fast2SMS's own message ID (from its DLT manager) | ask Fast2SMS |

MSG91 and Fast2SMS send by **their own** copy of each template, so you add the
template on their dashboard too and paste their ID here. The others send your
template's text along with your DLT IDs.

Using a different provider? Tell us which one. We add a provider once we can test
its DLT sending API against its own documentation.

## Connect

<Steps>
  <Step title="Open Settings → SMS provider">
    Only owners and admins can change it.
  </Step>

  <Step title="Choose your provider and paste its keys">
    Then enter your **DLT sender ID (header)** and your **DLT entity (PE) ID**.
    Keys are sealed as soon as they arrive and never shown again. To change one
    field later, leave the secret blank and the saved one is kept.
  </Step>

  <Step title="Add your templates">
    Under **DLT templates**, add each template you want the agent to use:

    * **Name** — your own, like `booking_link`. The agent sees it, so make it say what the message is for.
    * **Text** — copied from your DLT portal **exactly**, with `{#var#}` where it varies.
    * **DLT template ID** — the number your DLT portal gave it.
    * **Category** — Transactional, or Service (implicit or explicit). Promotional templates can't be sent by an agent.
    * **Agent may send this during a call or chat** — tick it for the templates you want the agent to be able to use mid-call. New templates start unticked. The **after the call** message doesn't need the tick.
    * **MSG91 template ID / Fast2SMS message ID** — only with those two providers.

    The page shows how many blanks the template has and how many SMS it will be
    sent as.
  </Step>

  <Step title="Send a test">
    Under **Send a test**, send one template to your own mobile. A success marks
    the provider **Working**; a refusal shows the provider's reason, so you can fix
    it before a customer is waiting.
  </Step>
</Steps>

## Writing templates the agent can use well

Each `{#var#}` takes **at most 30 characters** when it is sent, so keep the
moving parts short: a first name, a date, a short link.

```text Good theme={null}
Hi {#var#}, thanks for calling Acme Clinic. Book your visit here: {#var#}
```

```text Good theme={null}
Your appointment at Acme Clinic is on {#var#} at {#var#}. Reply on WhatsApp to change it.
```

```text Won't work well theme={null}
{#var#}
```

A template that is nothing but a blank was never going to pass DLT, and the agent
cannot write free text into an SMS anyway. Every message is one of your approved
templates, with only the blanks filled in.

<Note>
  **Plain English fits 160 characters in one SMS.** Hindi, other Indian scripts
  and emoji fit 70, so the same message may be sent as two or three SMS, and your
  provider charges for each one.
</Note>

## Using it

* **During a call or chat** — tick the templates the agent may use, then turn on
  **Send the customer an SMS** on the agent's **Actions** page. See [Actions](/agent/actions#reaching-the-customer-on-a-different-channel).
* **After a call** — choose an SMS template in the **After the call** card on the
  same page. See [After the call](/agent/after-the-call).

Every SMS the agent sends shows up as a note in that conversation, so your team can
see what went out.

## When something goes wrong

| What you see | Usually means |
| - | - |
| The provider's test fails with a DLT or template error | The text here doesn't match the DLT template word for word, or the DLT template ID is wrong |
| The test succeeds but nothing arrives | Your provider isn't in your PE–TM chain yet, or the sender ID isn't approved for that template |
| "SMS can only be sent to an Indian mobile number" | The customer's number is a landline or outside India |
| "MSG91 needs the MSG91 template ID" | Add the template on MSG91's dashboard too, and paste its ID |
| Can't change a template's text | An agent sends it after calls and fills a different number of blanks. Change that agent's **After the call** first |

## From the API

Everything above is also in the API: [SMS](/api-reference/sms/get-sms-provider).

```bash theme={null}
curl -X POST https://app.thinnest.ai/api/v1/sms/templates \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "booking_link",
    "body": "Hi {#var#}, thanks for calling Acme Clinic. Book your visit here: {#var#}",
    "dltTemplateId": "1207169876543210987",
    "category": "service_implicit"
  }'
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.