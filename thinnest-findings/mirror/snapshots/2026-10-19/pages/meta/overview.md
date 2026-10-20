> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Meta's rules, in one place

> What WhatsApp allows, who decides it, and which limits are ours versus Meta's.

Most of what you can and cannot do on WhatsApp is decided by Meta, not by us.
Reading this section once will save you a rejected template, a paused number, or
a campaign that costs three times what you expected.

<Note>
  **Where a rule comes from matters.** If a limit is ours, we can change it. If
  it is Meta's, nobody in this building can — and the only useful response is to
  work with it. Each page here says which.
</Note>

## The four rules that shape everything

<CardGroup cols={2}>
  <Card title="The 24-hour window" icon="clock" href="/meta/windows-and-pricing">
    A customer messages you; you get 24 hours of free-form replies. Outside it,
    only an approved template reaches them.
  </Card>

  <Card title="Every template is reviewed" icon="clipboard-check" href="/meta/template-review">
    Meta approves or rejects each one, usually in minutes. Rejection has
    specific, fixable causes.
  </Card>

  <Card title="Quality is scored, continuously" icon="gauge" href="/meta/quality-and-limits">
    Blocks and reports lower your rating. A low rating pauses templates and caps
    how many people you can reach.
  </Card>

  <Card title="Verification gates the rest" icon="badge-check" href="/meta/verification">
    Business verification unlocks higher limits, one-time passwords and
    publishable forms.
  </Card>
</CardGroup>

## The shape of it

```
Customer messages you
        │
        ├── within 24 hours ──► the agent replies freely, in its own words
        │                        (free until 1 Oct 2026, then charged per reply)
        │
        └── after 24 hours ───► only an APPROVED TEMPLATE reaches them
                                  │
                                  ├── marketing        → charged, opt-out applies
                                  ├── utility          → charged, opt-out does not
                                  └── authentication   → charged, needs verification
```

## What Meta decides

| | Who decides | Can we change it |
| - | - | - |
| Whether a template is approved | **Meta** | No |
| How many people you can message a day | **Meta**, by tier | No — but tiers rise |
| Whether your number is restricted | **Meta**, from quality signals | No |
| What a message costs | **Meta**, by category and country | No |
| Whether marketing reaches an opted-out contact | **Us**, enforcing your consent | It is enforced where it cannot be bypassed |
| How many tools an agent may use | **Us** | Yes, and it is a quality decision |

## The one mistake that costs the most

<Warning>
  **Mis-categorising marketing as utility.** It looks like a way to reach people
  who opted out, and it works exactly once.

  Meta scores template categories against their actual content. A promotional
  message submitted as utility is rejected as `TAG_CONTENT_MISMATCH` if you are
  lucky, and lowers your quality rating if it slips through and gets reported.
  Enough of that and your number is restricted — which costs you the channel,
  not just the campaign.

  Utility means order confirmations, delivery updates and receipts. If you would
  call it a campaign, it is marketing.
</Warning>

## Where to go next

<CardGroup cols={2}>
  <Card title="Windows and pricing" icon="indian-rupee-sign" href="/meta/windows-and-pricing">
    What is charged, what is free, and the 72-hour free entry point.
  </Card>

  <Card title="Template review" icon="file-check" href="/meta/template-review">
    Writing one that gets approved, and fixing one that did not.
  </Card>

  <Card title="Quality and limits" icon="chart-line" href="/meta/quality-and-limits">
    Ratings, tiers, pauses and how to climb.
  </Card>

  <Card title="Business verification" icon="building-columns" href="/meta/verification">
    What it unlocks and how long it takes.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.