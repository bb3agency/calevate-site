> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Text the caller: WhatsApp and SMS from a call

> Two worked examples — an insurance line that sends a renewal link on WhatsApp, and a loan line that sends a documents list by SMS — during the call and after it.

A phone call is a bad place to read out a link. This guide sets up two agents
that do the sensible thing instead: they say what the customer needs, then
**send it** — on WhatsApp or as an SMS — and tell the customer it's on its way.

Both come ready-made. In **Agents**, choose **Start from a pre-built agent** and
pick **Insurance advisor** or **Loan enquiries**. Their instructions already
cover when to offer a message, to ask first, and to say it was sent only after it
was.

<Note>
  An agent sends messages in two ways, and these examples use both.
  **During the call**, it sends a message when the customer asks for something.
  **After the call**, it sends one more, the same message every time, for the
  calls you choose. See [Actions](/agent/actions) and
  [After the call](/agent/after-the-call).
</Note>

## What the agent can and can't send

It can send **only templates you prepared**, with the blanks filled in. It never
writes its own words into a WhatsApp or an SMS. That is a platform rule on
WhatsApp, and a regulator's rule (DLT) for SMS in India, so the messages you see
below are exactly what you approved.

| | WhatsApp | SMS |
| - | - | - |
| **What it is** | An approved **Utility** template | A **DLT**-approved template, sent through [your own provider](/channels/sms) |
| **Goes to** | The number the customer called from | The same number, Indian mobiles only |
| **Costs** | Charged like any WhatsApp template | Billed by your SMS provider, not from your wallet here |

## Example 1: an insurance line that sends a renewal link on WhatsApp

### The template

On [Templates](/whatsapp/templates), create a **Utility** template and get it
approved:

```text Name: renewal_link theme={null}
Hi {{1}}, here is the link to renew your {{2}} policy. Please keep your policy
number handy. Reply here if you need help.
```

Give it a **link button** to your renewal page, with a **fixed** address (a
button address with a blank in it can't be filled by an agent). Then open the
approved template and tick **Agents may send this during a call or chat**.

### The agent

Start from **Insurance advisor**, then on its **Actions** page switch on **Send the
customer a WhatsApp**.

### What the call sounds like

```text theme={null}
Agent    Shield Insurance — how can I help?
Caller   Mera health policy renew karna hai.
Agent    Of course. Can I have your policy number, or the registered mobile number?
Caller   Registered number is nine eight seven six…
Agent    Thank you. And the date of birth on the policy?
Caller   Twelve March, nineteen eighty-four.
Agent    That matches. Your renewal is due on the twentieth. Shall I send the
         renewal link on WhatsApp?
Caller   Haan, bhej do.
         → the agent sends "renewal_link" with {{1}} = Rahul, {{2}} = health
Agent    Done — it's on WhatsApp now. Anything else?
```

What the customer receives on WhatsApp:

> Hi Rahul, here is the link to renew your health policy. Please keep your policy
> number handy. Reply here if you need help.
>
> **\[ Renew now ]**

Two things worth noticing. The agent **asked first** and sent only after a clear
yes. And it said "on WhatsApp now" only after the send succeeded. If the send
fails, the agent says so and offers to have a colleague send it, instead of
pretending.

### And after the call

Add a second message that goes out after every answered call. In the **After the
call** card on the agent's Actions page:

* **Send after:** *Calls somebody answered*
* **WhatsApp template:** a Utility template such as `thanks_for_calling`:

```text Name: thanks_for_calling theme={null}
Hi {{1}}, thanks for calling {{2}} on {{3}}. Your request is noted — reply here
and we will help you further.
```

* **Blanks:** *Customer's first name*, *Business name*, *Date of the call*

An after-call template needs no tick. You choose it, so it's sent only to the
people and calls you set.

## Example 2: a loan line that sends a documents list by SMS

### Set up SMS first

SMS in India needs a registered sender ID and templates, and your own provider.
See [SMS](/channels/sms) for each step
and the provider list, including the **PE–TM chain** step that, if skipped, gets
every message dropped.

On the SMS page, add a template exactly as your DLT portal approved it:

```text Name: loan_documents — Category: Service (implicit) theme={null}
Dear {#var#}, thank you for contacting Sunrise Finance. Your documents list and
apply link: {#var#}
```

The second blank holds at most **30 characters**, so use a short link like
`sunrise.in/apply`. Tick **Agent may send this during a call or chat**, then **send a
test** to your own mobile to check the provider, sender ID and DLT ids work together.

### The agent

Start from **Loan enquiries**, then on its **Actions** page switch on **Send the
customer an SMS**.

### What the call sounds like

```text theme={null}
Agent    Sunrise Finance — how can I help?
Caller   I want to know about a personal loan.
Agent    Happy to help. May I take your name?
Caller   Priya Nair.
Agent    Thanks, Priya. How much are you looking for?
Caller   Around three lakh.
Agent    Got it — three lakh. Are you salaried or self-employed?
Caller   Salaried.
Agent    Thank you. The lender confirms the rate after checking your documents.
         Shall I text you the documents list and the apply link?
Caller   Yes please.
         → the agent sends "loan_documents" with {#var#} = Priya, sunrise.in/apply
Agent    Sent to your mobile. A colleague can call you back today — what time suits?
```

What Priya receives:

> Dear Priya, thank you for contacting Sunrise Finance. Your documents list and
> apply link: sunrise.in/apply

Notice what the agent **didn't** do: it didn't promise approval, quote a rate it
wasn't given, or ask for a PAN or Aadhaar number on the call. Those rules are in
the prebuilt agent's instructions.

### And after the call

Send **every** caller one more message, in **both** channels. In **After the
call**, choose *Every call*, a WhatsApp Utility template and an SMS template. For
example the WhatsApp one:

```text Name: enquiry_noted theme={null}
Hi {{1}}, thanks for contacting {{2}}. Your enquiry is noted and a colleague will
call you back. Reply here if anything changes.
```

and the SMS one (DLT-approved):

```text Name: callback_noted theme={null}
Dear {#var#}, your enquiry with {#var#} is noted. A colleague will call you back.
```

Both blanks are filled from *Customer's first name* and *Business name*. The same
caller gets **at most one of each a day**, even if they ring three times, and
nobody on your do-not-contact list gets either.

## Checklist before going live

<Steps>
  <Step title="Connect what you'll send through">
    WhatsApp connected, and for SMS your [provider](/channels/sms) with a passing
    **test**.
  </Step>

  <Step title="Get the templates approved">
    WhatsApp templates approved as **Utility**; SMS templates approved on DLT.
  </Step>

  <Step title="Tick the ones the agent may use mid-call">
    On the WhatsApp template and the SMS template. After-call templates don't
    need a tick.
  </Step>

  <Step title="Switch the tools on, per agent">
    **Send the customer a WhatsApp** and **Send the customer an SMS**, on the
    agent's Actions page. They start off.
  </Step>

  <Step title="Call it yourself first">
    From your own phone. Check what arrives, that it arrives once, and that the
    agent says it was sent only after it was.
  </Step>
</Steps>

## If it didn't send

| What you see | Usually means |
| - | - |
| The tool says **not ready** on the Actions page | Nothing is ticked, the provider isn't connected, or the only ticked templates have a link blank |
| The agent offers to send, then says it couldn't | An unapproved template, an SMS your provider refused, or a number it can't use. The agent tells the customer plainly and offers another way. Try it in a test call to hear which |
| A web call sent nothing | A call with no phone number has nowhere to send to. The agent says so |
| No after-call message | The call didn't match **Send after**, the number was on the do-not-contact list, or it already got one in the last 24 hours |
| SMS refused by the provider | The text here differs from the DLT template, or your provider isn't in your PE–TM chain. See [SMS](/channels/sms#when-something-goes-wrong) |

## From the API

Everything here is also in the [API](/api-reference/sms/get-sms-provider):

```bash theme={null}
# Allow an agent to send a WhatsApp template in a call (needs a full key)
curl -X PATCH https://app.thinnest.ai/api/v1/templates/renewal_link \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{ "agentMaySend": true }'

# Allow an agent to send an SMS template in a call
curl -X PATCH https://app.thinnest.ai/api/v1/sms/templates/$TEMPLATE_ID \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{ "agentMaySend": true }'
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.