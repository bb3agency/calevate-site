> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Meta's rules, in one place

> What WhatsApp allows, who decides it, and which limits are ours versus Meta's.

Most of what you can and cannot do on WhatsApp is decided by Meta, not by us.
Reading this section once will save you a rejected template, a paused number, or
a campaign that costs three times what you expected.

> [!NOTE]
>
> **Where a rule comes from matters.** If a limit is ours, we can change it. If
> it is Meta's, nobody in this building can — and the only useful response is to
> work with it. Each page here says which.

## The four rules that shape everything

> **[The 24-hour window](https://docs.thinnest.ai/meta/windows-and-pricing.md)**
>
> A customer messages you; you get 24 hours of free-form replies. Outside it,
> only an approved template reaches them.

> **[Every template is reviewed](https://docs.thinnest.ai/meta/template-review.md)**
>
> Meta approves or rejects each one, usually in minutes. Rejection has
> specific, fixable causes.

> **[Quality is scored, continuously](https://docs.thinnest.ai/meta/quality-and-limits.md)**
>
> Blocks and reports lower your rating. A low rating pauses templates and caps
> how many people you can reach.

> **[Verification gates the rest](https://docs.thinnest.ai/meta/verification.md)**
>
> Business verification unlocks higher limits, one-time passwords and
> publishable forms.

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

> [!WARNING]
>
> **Mis-categorising marketing as utility.** It looks like a way to reach people
> who opted out, and it works exactly once.
>
> Meta scores template categories against their actual content. A promotional
> message submitted as utility is rejected as `TAG_CONTENT_MISMATCH` if you are
> lucky, and lowers your quality rating if it slips through and gets reported.
> Enough of that and your number is restricted — which costs you the channel,
> not just the campaign.
>
> Utility means order confirmations, delivery updates and receipts. If you would
> call it a campaign, it is marketing.

## Where to go next

> **[Windows and pricing](https://docs.thinnest.ai/meta/windows-and-pricing.md)**
>
> What is charged, what is free, and the 72-hour free entry point.

> **[Template review](https://docs.thinnest.ai/meta/template-review.md)**
>
> Writing one that gets approved, and fixing one that did not.

> **[Quality and limits](https://docs.thinnest.ai/meta/quality-and-limits.md)**
>
> Ratings, tiers, pauses and how to climb.

> **[Business verification](https://docs.thinnest.ai/meta/verification.md)**
>
> What it unlocks and how long it takes.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.