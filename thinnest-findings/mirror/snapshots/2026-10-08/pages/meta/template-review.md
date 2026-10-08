> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Template review and approval

> How Meta reviews a template, why they get rejected, and how to fix each cause.

Every template is reviewed by Meta before it can be sent. Most are decided in
minutes; the rejections have specific, nameable causes, and almost all of them
are formatting rather than judgement.

## The process

<Steps>
  <Step title="You write it">
    Body text, a category, a language, and example values for every blank.

    <Note>
      Meta requires an **example value for every variable** at creation time.
      A template submitted with `{{1}}` and no sample of what `{{1}}` looks like
      is rejected before a human sees it.
    </Note>
  </Step>

  <Step title="Meta reviews it automatically">
    A machine-learning review decides most templates within minutes.
  </Step>

  <Step title="Or a human does">
    Anything the automated pass cannot triage is routed to a person, which can
    take up to 24–48 hours.

    <Tip>
      Submit templates **before** you need them. A campaign planned for Friday
      and a template submitted Friday morning is a campaign that may not go out.
    </Tip>
  </Step>

  <Step title="Approved, or rejected with a reason">
    Approved templates can be sent. Rejected ones cannot, and the reason code
    tells you what to change.
  </Step>
</Steps>

## Why templates get rejected

### `INVALID_FORMAT` — the most common, and always fixable

Nothing to do with your wording. Four causes:

| Cause | Wrong | Right |
| - | - | - |
| Template **starts** with a variable | `{{1}}, your order shipped` | `Hi {{1}}, your order shipped` |
| Template **ends** with a variable | `Your order will arrive {{2}}` | `Your order will arrive on {{2}}.` |
| Variables not sequential | `{{1}}, {{2}}, {{4}}` | `{{1}}, {{2}}, {{3}}` |
| Malformed braces | `{1}` or `{{1}` | `{{1}}` |

<Warning>
  **A template may not begin or end with a variable.** This one catches almost
  everybody, because it is not intuitive — the rule exists so a message cannot
  be made to look like it came from somebody else. Put a word before and after.
</Warning>

### `TAG_CONTENT_MISMATCH` — the category does not match the content

You submitted a promotional message as utility, or the language you declared is
not the language of the text.

Fix by re-categorising honestly. See [the categories
below](#choosing-the-right-category).

### `ABUSIVE_CONTENT` — a policy violation

Content that breaches Meta's Terms of Service, Commerce Policy or Business
Policy. In practice this catches:

* Threatening legal action, or threatening to publicly shame a customer
* Anything in a prohibited category — Meta's Commerce Policy bars a specific
  list including alcohol, tobacco, weapons, drugs and adult products
* Requesting sensitive information (full card numbers, passwords) in the message
  body

### Other frequent causes

<AccordionGroup>
  <Accordion title="A URL shortener">
    `bit.ly`, `tinyurl` and similar are frequently rejected — a shortened link
    hides the destination, and Meta treats that as a phishing signal. Use your
    own domain.
  </Accordion>

  <Accordion title="Placeholder text left in">
    `Hi {{1}}, welcome to [Company Name]` — the bracketed placeholder is not a
    variable and reads as an unfinished template.
  </Accordion>

  <Accordion title="A duplicate of an existing template">
    Same content under a different name.
  </Accordion>

  <Accordion title="Poor grammar or spelling">
    Rejected as low quality, particularly where it makes the sender look
    fraudulent.
  </Accordion>

  <Accordion title="Content the language does not match">
    A template declared `en` whose body is Hindi. Declare the language you
    actually wrote.
  </Accordion>
</AccordionGroup>

## Choosing the right category

| Category | For | Charged | Reaches an opted-out contact | Needs verification |
| - | - | - | - | - |
| **Marketing** | Offers, announcements, re-engagement, anything promotional | Yes | **No** | No |
| **Utility** | Order confirmations, delivery updates, receipts, appointment reminders — tied to a specific transaction the customer initiated | Yes | Yes, and must | No |
| **Authentication** | One-time passwords only | Yes | Yes | **Yes** |

<Warning>
  **The test for utility is "did the customer do something that makes this
  message expected?"** An order confirmation follows an order. A "we miss you"
  message follows nothing, and is marketing however you label it.
</Warning>

## Authentication templates are special

Meta writes and localises the wording for one-time passwords itself. The editor
copies Meta's text exactly rather than letting you write your own — rewording it
gets the template rejected.

Authentication templates are also gated behind [business
verification](/meta/verification).

## Limits on templates themselves

| | Limit | Whose |
| - | - | - |
| Template name | 512 characters, lowercase letters, numbers and underscores | Meta |
| Templates created per hour | 100 per WhatsApp account | Meta |
| Review time | Minutes, up to 24–48 hours for human review | Meta |

## Editing an approved template

Editing sends it back through review. The previous version keeps working until
the new one is decided, so an edit does not take a working template offline —
but a rejected edit means you are still on the old wording.

<Tip>
  For anything you send often, treat an approved template as immutable and
  create `..._v2` instead. That way a rejected change never blocks a working
  message, and you can compare how the two perform.
</Tip>

## After approval, it can still be taken away

Approval is not permanent. Meta keeps scoring how customers react, and a
template that gets blocked or reported can be paused and eventually disabled.
See [Quality and limits](/meta/quality-and-limits).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.