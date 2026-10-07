> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# One-time codes

> OTP over WhatsApp — Meta writes the message, you choose how it behaves.

**One-Time Codes** in the sidebar is where you set up the template a login code
goes out on. It is deliberately not part of Templates, because almost nothing on
that page applies here.

## You do not write this one

An authentication template is the one kind whose words are not yours. Meta
writes them:

> **394812** is your verification code. For your security, do not share this code.
>
> *Expires in 10 minutes.*

You cannot change that wording, add your brand to it, or explain anything in it.
That is a mercy rather than a restriction — OTP is the one message where wording
is a liability, and Meta has already argued with every phishing pattern there
is.

What you choose is three things, and the preview beside them updates as you do.

<ParamField path="Expires after" type="1–90 minutes">
  Ten by default: long enough to find your phone, short enough that a screenshot
  in a group chat is worthless by the time it matters. WhatsApp says this line
  in the customer's own language, so it costs you no words.
</ParamField>

<ParamField path="Warn against sharing it" type="on / off">
  Appends *"For your security, do not share this code."* On by default.
</ParamField>

<ParamField path="How they get it into your app" type="Copy code / One-tap">
  * **Copy code** — they tap, then paste. Works everywhere, needs no
    integration, and is the right answer for almost everyone.
  * **One-tap autofill** — hands the code straight to your Android app. Needs
    your app's **package name and signing hash**, which the form asks for. Meta
    refuses the template without them, so you would otherwise find out at review
    rather than at login.

  There is no "no button" option, and that is Meta's rule rather than ours: a
  code template must carry exactly one button, of one of these two kinds.
</ParamField>

## Getting it approved

On the new-template page, press **Save & submit for review** to save it and send
it to Meta in one step. Or press **Save as draft** — a draft is ours, not
Meta's, and it cannot send anything — then open it later and press **Submit for
review**. Authentication templates are usually approved within minutes, because
Meta wrote the content and has little to argue with.

<Note>
  **Submit needs a connected number.** Meta reviews a template against your
  WhatsApp Business Account, so until one is connected there is nothing to
  submit it to — the button says so on hover.
</Note>

Once submitted, the settings lock. Meta reviewed a specific configuration and
the API offers no way to change it underneath them. To use different settings,
delete it and make another.

## Sending a code

From your own website's server, through the API. On any code template, press
**View embed code** — on the template's page, or in the **⋯** menu of its row in
the list. A window opens with the four steps (get an API key, make the code on
your server, send it, check it when the customer types it in) and code you can
copy in cURL, Node.js, Python and PHP, with your template's name already filled
in. See also [Send a one-time code](/api-reference/one-time-codes/send-one-time-code). The short
version:

```json theme={null}
POST /api/v1/codes
{ "to": "919876543210", "code": "394812" }
```

We do not generate, store, expire or check the code. That stays yours.

## Deleting one

Either from the row's **⋯** menu in the list, or from **Delete** on the
template's own page.

<Warning>
  **This removes it from Meta as well as from here**, and there are two
  consequences worth knowing before you click:

  * Anything calling the API with that template's name **stops working**.
  * Meta will **not let the name be used again for 30 days**. If you are
    replacing a template, give the new one a different name.
</Warning>

A draft that never reached Meta has neither consequence — nothing is using it,
and the name stays free.

## What this costs

Authentication is priced separately from marketing and utility, and a code sent
to another country costs many times a domestic one — on Meta's Indian card, more
than twentyfold. Your own figures are on the [usage page](/workspace/usage),
split by category and country, which is the only way anyone notices a login flow
that has quietly gone international.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.