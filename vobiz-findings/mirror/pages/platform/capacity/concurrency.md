> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Concurrency - Buy Simultaneous Call Capacity

> Buy concurrent-call capacity in the Vobiz Console - what concurrency controls, the busy-signal symptom of hitting the ceiling, how the blocks-of-ten pricing works, and how to preview the monthly cost before you purchase.

**Concurrency** is the maximum number of live calls your account can hold at the same time. Every active conversation - inbound or outbound - occupies exactly one channel. It caps how many calls run at once, not how fast new ones start; that second limit is [CPS](/docs/platform/capacity/cps).

Open it from **Capacity → Concurrency** in the left sidebar.

<Frame caption="Concurrent Calls - purchase panel and explainer">
  <img src="https://mintcdn.com/vobizai/xJ7rEflWHk5qgI_w/images/platform/capacity/concurrency-purchase.png?fit=max&auto=format&n=xJ7rEflWHk5qgI_w&q=85&s=fa408da7deaf2e553365b37a98082d51" alt="Concurrent Calls page with a Purchase Concurrent Calls card showing a quantity stepper in blocks of ten, an estimated monthly cost, a pricing bracket table with units, price per unit and subtotal, and a Buy Concurrent Calls button, beside a What is Concurrency explainer card describing simultaneous active channels and when to increase them" style={{maxWidth: '900px', margin: '0 auto', display: 'block'}} width="2000" height="1009" data-path="images/platform/capacity/concurrency-purchase.png" />
</Frame>

## When to raise concurrency

Once you hit the concurrency ceiling, new callers receive a busy signal. Scale it to match contact-centre headcount or campaign volume - one channel per agent or per simultaneous outbound leg, plus headroom for peaks.

Inbound traffic is the case to watch: a busy signal is invisible in your own logs but very visible to the customer who got it. Check live utilisation against the ceiling with the [Concurrency API](/docs/account/concurrency), which returns `concurrent_calls`, `max_concurrent`, and `utilization_pct`.

## Buying capacity

| Control | What it does |
| - | - |
| **Quantity** | Stepper in **blocks of 10**, minimum 10. The − and + buttons move a full block at a time. |
| **Estimated monthly cost** | Recalculates as you step the quantity, before you commit to anything. |
| **Bracket table** | The pricing tier applied to your selection - the bracket, the units bought, the price per unit, and the subtotal. |
| **Buy Concurrent Calls** | Purchases the capacity and starts a monthly subscription. |

Capacity is **purchased in blocks of 10 and billed monthly**. The first month is charged on purchase, and the subscription then renews on its own cycle until you cancel it from [My Subscriptions](/docs/platform/capacity/subscriptions).

<Note>
  The prices in the screenshot belong to one account's pricing tier. Your own rate appears in the bracket table as you change the quantity, and [Preview capacity pricing](/docs/account/channel-pricing-preview) returns the same figure over the API without charging anything.
</Note>

## Buy it over the API

<CardGroup cols={2}>
  <Card title="Preview capacity pricing" icon="calculator" href="/docs/account/channel-pricing-preview">
    Calculate the monthly price for a concurrency quantity without creating a subscription.
  </Card>

  <Card title="Purchase capacity" icon="cart-shopping" href="/docs/account/channel-subscriptions">
    Create the subscription with `resource_type: "concurrent_calls"` and a quantity.
  </Card>

  <Card title="Check live concurrency" icon="gauge-high" href="/docs/account/concurrency">
    Read current channel usage and headroom in real time.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.