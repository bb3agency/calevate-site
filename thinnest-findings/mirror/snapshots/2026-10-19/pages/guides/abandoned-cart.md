> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Recover abandoned carts

> An event from your shop, a two-step sequence, and messages that stop when the customer buys.

The classic sequence, and a good first one because the success metric is
obvious.

## The shape

```
Customer abandons cart
        │
        ├─ after 1 hour  →  "Still thinking it over?"
        └─ after 24 hours →  "Your cart expires tonight"
                              │
                              └─ they buy → sequence stops
```

<Steps>
  <Step title="Write two templates">
    Both **marketing** category — this is promotional, and mis-categorising it
    to dodge consent rules is the fastest way to lose a WhatsApp number.

    `cart_reminder_1`:

    ```
    Hi {{1}}, you left {{2}} in your cart. Still interested?
    ```

    `cart_reminder_2`:

    ```
    Hi {{1}}, last chance — {{2}} is still waiting, and your cart clears
    tonight.
    ```

    Submit both and wait for approval. See [Templates](/whatsapp/templates).
  </Step>

  <Step title="Build the sequence">
    Two steps:

    | Step | Delay | Template |
    | - | - | - |
    | 1 | 1 hour | `cart_reminder_1` |
    | 2 | 24 hours | `cart_reminder_2` |

    Bind `{{1}}` to the contact's name and `{{2}}` to a value carried on the
    enrolment, so the message names the actual product.
  </Step>

  <Step title="Fire the event from your shop">
    ```js theme={null}
    async function cartAbandoned(cart) {
      // No phone, nothing to send to. Not an error.
      if (!cart.customer?.phone) return;

      await fetch("https://app.thinnest.ai/api/v1/events", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${process.env.THINNEST_API_KEY}`,
          "Content-Type": "application/json",
          // One enrolment per cart, however many times this fires.
          "Idempotency-Key": `cart-abandoned-${cart.id}`,
        },
        body: JSON.stringify({
          name: "cart_abandoned",
          contact: {
            phone: cart.customer.phone,
            name: cart.customer.firstName,
          },
          variables: {
            product: cart.items[0]?.title ?? "your items",
            cart_id: cart.id,
          },
        }),
      });
    }
    ```

    <Warning>
      **The idempotency key is doing real work here.** Cart-abandonment jobs
      typically run on a timer and will happily re-fire for the same cart every
      few minutes. Without a key derived from the cart, your customer gets the
      same reminder nine times.
    </Warning>
  </Step>

  <Step title="Stop it when they buy">
    The part people forget, and the one customers notice.

    ```js theme={null}
    async function orderPlaced(order) {
      await fetch("https://app.thinnest.ai/api/v1/events", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${process.env.THINNEST_API_KEY}`,
          "Content-Type": "application/json",
          "Idempotency-Key": `order-placed-${order.id}`,
        },
        body: JSON.stringify({
          name: "order_placed",
          contact: { phone: order.customer.phone },
        }),
      });
    }
    ```

    Configure the sequence to end on `order_placed`. Nothing is worse than
    "last chance, your cart clears tonight" arriving after somebody has paid.
  </Step>
</Steps>

## Consent

Checked at enrolment **and** again at each send. A customer who opts out on hour
one does not receive hour twenty-four — you do not have to handle that yourself.

## Timing

One hour and 24 hours are a sensible default rather than a law. Two rules worth
keeping:

* **Not immediately.** Somebody who wandered off to check a delivery date has
  not abandoned anything.
* **Two messages, not five.** The third reminder converts almost nobody and
  earns you a block, which costs you the channel for that customer permanently.

## Checking it worked

The sequence page shows enrolments, which step each contact is on, and who
completed or exited early. Against that, the **Analytics** conversation count
tells you how many replied — which is the number that actually matters.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.