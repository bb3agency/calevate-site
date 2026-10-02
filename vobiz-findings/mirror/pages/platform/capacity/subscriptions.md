> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# My Subscriptions - Manage Capacity Subscriptions

> Review and cancel the CPS and concurrency subscriptions on your Vobiz account - quantity, monthly cost, next billing date, and status for every active channel subscription.

**My Subscriptions** lists every capacity subscription on the account - each [CPS](/docs/platform/capacity/cps) and [Concurrency](/docs/platform/capacity/concurrency) block you have bought, what it costs, when it renews, and whether it is still active.

Open it from **Capacity → My Subscriptions** in the left sidebar.

<Frame caption="My Subscriptions - active and cancelled capacity subscriptions">
  <img src="https://mintcdn.com/vobizai/xJ7rEflWHk5qgI_w/images/platform/capacity/my-subscriptions_blur.png?fit=max&auto=format&n=xJ7rEflWHk5qgI_w&q=85&s=f68ff385eebe16ff9d8f9537751a729c" alt="My Subscriptions page with a search field and a table listing Concurrent Calls and Calls Per Second subscriptions, each row showing the resource type with its subscription ID, quantity in units, monthly cost, next billing date, an Active or Cancelled status, and a Cancel action" style={{maxWidth: '900px', margin: '0 auto', display: 'block'}} width="2000" height="1260" data-path="images/platform/capacity/my-subscriptions_blur.png" />
</Frame>

## Columns

| Column | What it tells you |
| - | - |
| **Resource Type** | **Concurrent Calls** or **Calls Per Second (CPS)**, with the subscription's own ID underneath - quote it in a support conversation about a specific charge. |
| **Quantity** | Units bought in that subscription. Capacity is cumulative: several blocks of the same resource type add up to your ceiling. |
| **Monthly Cost** | The recurring charge for that subscription alone. |
| **Next Billing** | Date and time of the next renewal. |
| **Status** | **Active** for a subscription that is billing and counting toward your ceiling, **Cancelled** for one that has been stopped. |
| **Action** | **Cancel** on active rows. Cancelled rows show `—`. |

Each purchase creates its own row, so buying capacity three times leaves three subscriptions rather than one line that grows - which is what lets you cancel part of your capacity without touching the rest.

## Cancelling

Click **Cancel** on the row you want to stop. Cancellation is available at any time and applies to that subscription only; every other block keeps running, and your ceiling drops by the cancelled quantity.

<Warning>
  Cancelling reduces the ceiling that capacity was holding up. Before cancelling concurrency, check live utilisation with the [Concurrency API](/docs/account/concurrency) - if peak usage is close to the current ceiling, the calls that no longer fit will get a busy signal.
</Warning>

Use the **Search subscriptions…** field to find a specific row by resource type or subscription ID when the list runs long.

## Related

<CardGroup cols={2}>
  <Card title="Buy CPS" icon="bolt" href="/docs/platform/capacity/cps">
    Raise call-initiation throughput in blocks of 3.
  </Card>

  <Card title="Buy Concurrency" icon="layer-group" href="/docs/platform/capacity/concurrency">
    Raise simultaneous live calls in blocks of 10.
  </Card>

  <Card title="Purchase capacity API" icon="code" href="/docs/account/channel-subscriptions">
    Create the same subscriptions programmatically.
  </Card>

  <Card title="Transactions" icon="receipt" href="/docs/account/transactions">
    Every debit on the account, including capacity renewals.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.