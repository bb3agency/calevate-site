> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Concurrency Management for Organizations

> Understand how Bolna allocates outbound call concurrency across an organization and its sub-accounts using guaranteed minimums and maximum caps.

## Overview

An organization has a pool of outbound call concurrency to share across its **main account** and any **sub-accounts**. Bolna divides that pool using two settings on each account:

<CardGroup cols={2}>
  <Card title="Guaranteed minimum" icon="lock">
    Concurrency **reserved** for an account — it can always run at least this many calls, even when the rest of the organization is busy.
  </Card>

  <Card title="Maximum cap" icon="arrow-up-right-dots">
    The **ceiling** an account can reach. Leave it unset to make the account **elastic** — free to burst into the organization's unused capacity.
  </Card>
</CardGroup>

Together these let you guarantee critical workloads a floor of capacity while still letting quieter accounts borrow spare capacity when it's available.

<Tip>
  Concurrency management applies to organizations with sub-accounts, an Enterprise feature. Reach out at [enterprise@bolna.ai](mailto:enterprise@bolna.ai) to get set up.
</Tip>

## The organization envelope

Your organization's envelope is provisioned by Bolna:

* **Organization maximum** — the hard ceiling on total simultaneous outbound calls across the main account and every sub-account combined. The organization never exceeds this.
* **Organization guaranteed minimum** — the capacity Bolna guarantees your organization as a whole, even when the wider platform is under load.

You then distribute that envelope across your accounts. Each account gets its own `min_concurrency` (its guaranteed floor) and an optional `max_concurrency` (its cap).

## Per-account settings

| Setting           | Meaning                          | Notes                                                                                                               |
| ----------------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `min_concurrency` | Guaranteed floor for the account | `0` means no guarantee — the account only runs calls when spare capacity is available                               |
| `max_concurrency` | Hard cap for the account         | Omit (or `null`) for **elastic** — the account can burst up to the organization maximum. `0` **pauses** the account |

The main account and each sub-account each carry their own pair of values.

## How calls are allocated

Each scheduling cycle, Bolna decides how many new calls to start per account:

<Steps>
  <Step title="Guarantees first">
    Every account is brought up to its guaranteed minimum before any spare capacity is handed out. Calls already in progress are never dropped to make room.
  </Step>

  <Step title="Spare capacity is shared fairly">
    Whatever is left in the organization pool is shared among the accounts that still have calls waiting, in proportion to their guarantees — so an account with a larger floor also gets a larger share of the surplus.
  </Step>

  <Step title="Bursting up to the cap">
    A capped account bursts up to its `max_concurrency`; an elastic account (no max) can keep climbing until the organization pool is full.
  </Step>

  <Step title="Excess is queued, never dropped">
    Calls that don't fit this cycle stay queued and dial automatically as in-flight calls finish. Inbound calls are never queued.
  </Step>
</Steps>

## Telephony providers and your concurrency

Queued calls are tracked **per telephony provider**, so congestion on one provider stays contained to that provider:

* **An account's capacity is split evenly across its providers.** Dialing is not first-come-first-served across an account's whole queue: its share of the pool is divided equally between the providers it has calls waiting on, and any share a provider can't use passes to the others. Within a single provider, calls dial in the order they were queued.
* **One busy provider doesn't stall the others.** If a provider is temporarily out of capacity, your accounts keep dialing their queued calls on every other provider at their usual share of the pool.
* **Your own provider credentials don't share capacity.** Calls placed on an account's [own provider account](/docs/providers) are limited by that account's guarantee and cap alone — never by how busy the provider is for other Bolna customers.

For example, an account allowed 700 concurrent calls with 15,000 calls queued on one provider and 15,000 on another runs 350 on each, both dialing continuously, rather than draining the first queue before starting the second.

<Note>
  [SIP trunking (BYOT)](/docs/sip-trunking/introduction) is the exception to the point above: those calls run on Bolna's SIP infrastructure, so they share platform capacity even though the trunk is yours.
</Note>

<Note>
  When a telephony provider is saturated platform-wide, Bolna temporarily rations each organization toward its **guaranteed minimum** on **that provider only**: floors are still honored and every other provider keeps bursting, until the saturated provider frees up.
</Note>

## Configuration rules

When you set or change limits, Bolna validates the whole account set so guarantees and caps stay consistent with the organization envelope:

* The sum of all account **minimums** must not exceed the organization's guaranteed minimum.
* The sum of all **capped** account maximums must not exceed the organization maximum. Elastic accounts (no max) are not counted toward this sum.
* For any account, `min_concurrency` must not exceed `max_concurrency`.

An edit that breaks a rule is rejected with a `400` explaining which sum was exceeded, for example:

```json theme={"system"}
{
  "message": "Sum of account minimums (60) exceeds the org minimum (50) by 10; lower an account minimum first."
}
```

## Worked example

An organization with a maximum of **100** concurrent calls, distributed across three accounts:

| Account       | `min_concurrency` | `max_concurrency` | Behavior                                                  |
| ------------- | ----------------- | ----------------- | --------------------------------------------------------- |
| Main          | 20                | *(elastic)*       | Always has 20; can burst toward 100 when capacity is free |
| Sales (sub)   | 30                | 50                | Always has 30; bursts up to 50                            |
| Support (sub) | 10                | 30                | Always has 10; bursts up to 30                            |

* **Only Sales is busy:** Sales runs up to its cap of 50; the remaining capacity stays available for the other accounts.
* **All three busy, demand over 100:** each account first gets its guarantee (20 + 30 + 10 = 60), then the remaining 40 is shared in proportion to those guarantees, up to each account's cap. Anything that still doesn't fit queues and dials as calls finish.
* **One provider saturated:** the organization is rationed toward its guaranteed minimum on that provider — the guarantees above are preserved — while calls on the organization's other providers keep bursting normally.

## Who can manage it

Only **organization admins** can set or change account concurrency, from the dashboard or the API. Sub-account members cannot.

## Setting concurrency

<CardGroup cols={2}>
  <Card title="Create a sub-account" icon="plus" href="/docs/api-reference/sub-accounts/create">
    Set `min_concurrency` and `max_concurrency` when creating a sub-account.
  </Card>

  <Card title="Update a sub-account" icon="pen" href="/docs/api-reference/sub-accounts/patch_update">
    Change an existing sub-account's guarantee or cap.
  </Card>
</CardGroup>

For the broader account tiers (trial, paid, enterprise), see [Concurrency tiers](/docs/outbound-calling-concurrency).
