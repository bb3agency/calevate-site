> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# After the call

> Send the caller a WhatsApp or an SMS when a call ends — a thank-you, a booking link, a sorry-we-missed-you.

When a call ends, the agent can send the caller a message: a WhatsApp, an SMS, or
both. It's the same message every time, from a template you chose, with blanks
filled from the call. Set it in the **After the call** card on the agent's
**Actions** page.

Things it's good for:

* **Answered calls** — "Thanks for calling, {name}. Book your visit here: …"
* **Missed calls** — "Sorry we missed you, {name}. Reply here or call us back on …"
* **Every call** — your address and opening hours, after anyone rings.

## Set it up

<Steps>
  <Step title="Have a template ready">
    * **WhatsApp:** an approved **Utility** template. See [Templates](/channels/whatsapp).
    * **SMS:** a DLT template, with your SMS provider connected. See [SMS](/channels/sms).
  </Step>

  <Step title="Choose which calls">
    **Send after**: *Calls somebody answered*, *Missed calls*, or *Every call*.
    A call that failed before it rang never gets one.
  </Step>

  <Step title="Choose the template, and fill its blanks">
    For each blank, choose what goes in it:

    | Choice | Fills with |
    | - | - |
    | Customer's first name | The caller's first name, or "there" if we don't know it |
    | Business name | Your workspace's name |
    | Agent's name | This agent's name |
    | Date of the call | Like "7 Oct", in your workspace's timezone |
    | Fixed text… | Whatever you type, like your booking link |

    An SMS blank holds at most 30 characters, so fixed text there is kept short.
  </Step>

  <Step title="Save">
    Choose **Don't send** for a channel to turn it off.
  </Step>
</Steps>

<Note>
  **A WhatsApp template with a blank in its link button can't be used here.** A
  button like `yoursite.com/{{1}}` needs a value for the blank, and nothing can
  fill it after a call. Those templates don't appear in the list, and saving one
  through the API is refused. Use a template whose link is fixed, or put the
  changing part in the message text.
</Note>

## What keeps it polite

* **Once per call.** A call that ends twice in our records still sends once.
* **Never to anyone on your do-not-contact list**, including someone who asked
  the agent on the call not to be contacted again.
* **At most once a day to the same number**, per channel. A caller who rings
  three times in a morning gets one message, not three.
* **Only to a number we know is theirs**, the one they called from or that we
  called. Never to a number someone said out loud on the call.
* **WhatsApp must be a Utility template.** Marketing templates are refused here.
  They need marketing consent, and Meta pauses them quickly when people don't
  want them.

## What it costs

* **WhatsApp** is charged like any other template you send. See
  [WhatsApp](/channels/whatsapp).
* **SMS** goes through your own provider, which bills you directly. Nothing is
  taken from your wallet here.

## Seeing what went out

Each WhatsApp appears in the customer's WhatsApp conversation, marked as sent by
the agent after the call. Each SMS appears as a note on the call's conversation.
A message that couldn't be sent (no WhatsApp on that number, a template no longer
approved, your SMS provider refused it) is simply not sent. The call itself is
unaffected.

## From the API

The same setting is `followUp` on [Update Post-call
Settings](/api-reference/post-call/update-post-call-settings). It needs a **full**
key, because it makes the agent message customers.

```bash theme={null}
curl -X PATCH https://app.thinnest.ai/api/v1/agents/ag_5cbb2cb9-41aa-4181-9e37-78914bd7b4f9/post-call \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "followUp": {
      "when": "missed",
      "whatsapp": {
        "templateId": "3f1c2b7e-9a41-4f0b-8e2d-5c6a7b8d9e01",
        "values": ["customer_name", "business_name"]
      },
      "sms": {
        "templateId": "8d2e4f6a-1b3c-4d5e-9f70-a1b2c3d4e5f6",
        "values": ["customer_name", "fixed:acme.example/book"]
      }
    }
  }'
```

`values` fill the template's blanks in order, one each. Anything you leave out of
`followUp` keeps what is saved, and a channel set to `null` stops it:

```json theme={null}
{ "followUp": { "sms": null } }
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.