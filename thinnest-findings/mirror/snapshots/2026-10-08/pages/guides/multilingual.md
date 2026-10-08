> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Serve customers in their own language

> One knowledge base, 37 languages — and how templates differ from chat.

Most platforms make you maintain a knowledge base per language. This one does
not, and the distinction between **chat** and **templates** is where the real
work is.

## Chat: nothing to do

Set the agent's reply language to **match the customer** and it answers in
whichever language they wrote in.

Your knowledge stays in one language. The agent translates as it answers.

If every customer uses the same language, choose that language instead. The
agent then answers **only** in it, and on a phone call the speech recogniser
listens for it, which stops a short reply from being heard as another language.
An agent has one language: to serve several, leave it on **match the
customer**.

<Tip>
  Write your material in whichever language you maintain best — usually English.
  Translating your knowledge base by hand produces drift: the Hindi version says
  ₹1,200 and the English one says ₹1,400, and nobody notices for months.
</Tip>

### The languages

37, including **all 22 of the Eighth Schedule** — Assamese, Bodo, Dogri,
Konkani, Maithili, Manipuri, Santali and the rest — each in its own script in
the picker, in one A–Z list.

## Templates: real work, and worth it

Chat translates on the fly. **Templates cannot** — every one is submitted to
Meta and approved in a specific language.

<Steps>
  <Step title="Set your contacts' languages">
    Each contact carries a language. Set it on import, or from the
    [Contacts](/agent/leads) page.

    <Note>
      A contact with **no** language set receives your default. So adding
      languages is always an improvement, never a prerequisite — nothing breaks
      for contacts you have not got to yet.
    </Note>
  </Step>

  <Step title="Create the variants">
    One template name, several languages. The editor can draft the translations
    for you, and the rule it holds to is strict:

    <Warning>
      **A translation that changes the placeholders is refused, never repaired.**

      If `{{1}}` and `{{2}}` swap order in the Hindi version, your customer gets
      the order number where their name should be. That is not a translation
      problem you want discovered by a customer, so a variant whose placeholder
      count or order differs from the original is rejected outright.
    </Warning>

    Always read the draft before submitting. It is a starting point, not a
    finished translation.
  </Step>

  <Step title="Send normally">
    Nothing changes at send time. Each contact receives the variant matching
    their language; anyone without one gets the default.

    The API takes no language parameter for the same reason — a template is
    identified by name, and its language is whatever it was approved in.
  </Step>
</Steps>

## A worked case

A Pune business with Marathi, Hindi and English-speaking customers:

| | Setup |
| - | - |
| Knowledge | English only, one copy |
| Reply language | Match the customer |
| Templates | `order_shipped_v1` in `en`, `hi`, `mr` |
| Contacts | Language set at import from the delivery address state |

A Marathi-speaking customer asks a question in Marathi and gets a Marathi answer
drawn from English material. Their shipping notification arrives as the approved
Marathi template. Nobody maintained a second knowledge base.

## Where it will not help

* **Authentication templates.** Meta writes and localises one-time password
  wording itself; rewording gets the template rejected.
* **Scanned documents in any language.** There is no OCR.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.