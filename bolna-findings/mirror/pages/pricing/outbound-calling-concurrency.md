> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Account based concurrency tiers

> Learn how Bolna Voice AI account tiers affect outbound call concurrency. Explore limits, scaling tiers, and enterprise options for high-volume operations.

## What are concurrency limits in Bolna?

Concurrency limits determine how many **simultaneous outbound calls** your account can make at once. Higher call volumes automatically increase your concurrency tier, ensuring smooth operations for growing businesses.

<CardGroup cols={2}>
  <Card title="Trial accounts" icon="flask">
    Up to **2 concurrent calls**, restricted to verified phone numbers only.
  </Card>

  <Card title="Paid accounts" icon="credit-card">
    Starts at **10 concurrent calls**, scaling automatically with monthly usage.
  </Card>

  <Card title="Enterprise" icon="building" href="/docs/enterprise/plan">
    **Elevated concurrency levels** for high-volume operations. Calls over your limit are automatically queued.
  </Card>

  <Card title="Inbound calls" icon="phone-arrow-down">
    **No concurrency limits** - inbound calls are never restricted or queued.
  </Card>
</CardGroup>

<Note>
  You can read more about our enterprise offering here [Bolna enterprise](/docs/enterprise/plan).
</Note>

<Note>
  Running an organization with sub-accounts? See [Concurrency management](/docs/enterprise/concurrency-management) for how a shared concurrency pool is split across accounts using guaranteed minimums and maximum caps.
</Note>

## What happens to calls above your limit?

Outbound calls that don't fit your concurrency limit are **queued, not rejected**. They dial automatically as active calls finish, so a batch or campaign larger than your limit still runs end to end — it just paces itself.

### Each telephony provider queues independently

Your queued calls are tracked **per telephony provider**, so what happens on one provider doesn't affect the others:

<CardGroup cols={2}>
  <Card title="One busy provider won't stall the rest" icon="arrows-split-up-and-left">
    If one provider is temporarily out of capacity, your calls on the other providers keep dialing at your usual concurrency instead of waiting behind it.
  </Card>

  <Card title="Your own provider keys don't share capacity" icon="key">
    Calls placed on [your own provider account](/docs/providers) are limited only by your account concurrency — never by how busy that provider is for other Bolna customers.
  </Card>
</CardGroup>

<Note>
  Calls over [SIP trunking (BYOT)](/docs/sip-trunking/introduction) are the exception to the point above: they run on Bolna's SIP infrastructure, so they share platform capacity even though the trunk is yours.
</Note>

### How your limit is shared between providers

Dialing is **not** first-come-first-served across your whole queue. Your concurrency limit is **split evenly between the providers you have calls waiting on**, and any share a provider can't use passes to the others. Within a single provider, calls dial in the order they were queued.

**Example** — your limit is **700**, with **15,000** calls queued on provider A and **15,000** on provider B:

| Queued on  | Slots used |
| ---------- | ---------- |
| Provider A | 350        |
| Provider B | 350        |

Both providers dial continuously at 350 concurrent calls, each working through its own queue in order — so neither campaign has to wait for the other to finish. If provider A only had 200 calls waiting, it would use 200 slots and provider B would get the remaining 500.

Inbound calls are never queued, regardless of provider.

## How to check my account's concurrency limits?

<Steps>
  <Step title="Open Workplace settings">
    Go to your **Workplace settings** in the Bolna dashboard.

    <Frame caption="Open your Workplace settings page">
      <img src="https://mintcdn.com/bolna-54a2d4fe/DqJpudnR0YtgOS49/images/outbound_calling_concurrency/workplace_settings.png?fit=max&auto=format&n=DqJpudnR0YtgOS49&q=85&s=22a1966caf6334e5304f95080d5d356b" alt="Workplace settings navigation in Bolna dashboard to visit page for concurrency limits" width="960" height="700" data-path="images/outbound_calling_concurrency/workplace_settings.png" />
    </Frame>
  </Step>

  <Step title="View Account limits">
    See your **Account limits** to check your current concurrency tier and available slots.

    <Frame caption="See your account limits">
      <img src="https://mintcdn.com/bolna-54a2d4fe/DqJpudnR0YtgOS49/images/outbound_calling_concurrency/workplace_account_limits.png?fit=max&auto=format&n=DqJpudnR0YtgOS49&q=85&s=a7acb32f34ded94c499796608cef6f4b" alt="Account concurrency limits in Bolna showing concurrent call limits and tier-based calling capacity for Voice AI agents" width="1304" height="814" data-path="images/outbound_calling_concurrency/workplace_account_limits.png" />
    </Frame>
  </Step>
</Steps>

## Next steps

Ready to scale your calling operations? Explore related features:

<CardGroup cols={2}>
  <Card title="Batch Calling" icon="list-check" href="/docs/guides/outbound/batch-calling">
    Set up batch calling for high-volume campaigns
  </Card>

  <Card title="Outbound Calls" icon="phone-arrow-up-right" href="/docs/guides/outbound/making-outgoing-calls">
    Learn about making outbound calls efficiently
  </Card>

  <Card title="Enterprise Plan" icon="building" href="/docs/enterprise/plan">
    Explore elevated concurrency levels with our Enterprise plan
  </Card>

  <Card title="Call Details" icon="chart-bar" href="/docs/guides/prompting/using-extractions">
    Monitor call details and execution results
  </Card>
</CardGroup>

For custom concurrency needs, [contact our team](mailto:support@bolna.ai) to discuss your requirements.
