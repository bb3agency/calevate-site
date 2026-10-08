> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Answer "where is my order?"

> A worked example: your API, one action, and an agent that stops saying it doesn't know.

"Where is my order" is the single most common message any shop receives, and
knowledge alone can never answer it — the answer is in your database, not on
your website.

By the end of this you will have an agent that looks the order up and answers,
and refuses to do it for a stranger.

<Steps>
  <Step title="Build an endpoint that takes an order number">
    Keep it narrow. This will be called by a model on behalf of a member of the
    public, so it should do exactly one thing.

    ```js Express theme={null}
    app.post("/agent/order-status", express.json(), async (req, res) => {
      // Shared secret, checked before anything else.
      if (req.get("X-Agent-Secret") !== process.env.AGENT_SECRET) {
        return res.status(401).json({ error: "unauthorised" });
      }

      const { orderNumber, email } = req.body ?? {};
      if (!orderNumber || !email) {
        return res.status(400).json({ error: "orderNumber and email required" });
      }

      // BOTH must match. See the warning below — this line is the whole
      // security model of this endpoint.
      const order = await db.orders.findOne({
        number: String(orderNumber).replace(/^#/, ""),
        email: String(email).toLowerCase().trim(),
      });

      if (!order) {
        // Deliberately identical whether the order does not exist or the email
        // does not match. Anything else tells a stranger which orders are real.
        return res.json({ found: false });
      }

      return res.json({
        found: true,
        status: order.status,
        carrier: order.carrier ?? null,
        trackingUrl: order.trackingUrl ?? null,
        expected: order.expectedLabel ?? null,
      });
    });
    ```

    <Warning>
      **Require two facts, not one.** An order number alone is guessable — they
      are usually sequential. Asking for the number *and* the email on the order
      means a stranger typing `#10432` learns nothing.

      Return the same `found: false` for "no such order" and "wrong email". A
      different response for each is an oracle for which order numbers exist.
    </Warning>
  </Step>

  <Step title="Add it as an action">
    On the agent's **Actions** page, add a custom HTTP action.

    | Field | Value |
    | - | - |
    | Name | `order_status` |
    | Method | `POST` |
    | URL | `https://shop.example.com/agent/order-status` |
    | Header secret | `X-Agent-Secret: …` |

    Describe it in the words the model needs:

    ```
    Look up a customer's order. Requires BOTH the order number and the email
    address on the order. If the customer has given only one, ask for the other
    before calling this. Returns found: false when the pair does not match —
    say you could not find it and ask them to check both, never say the order
    does not exist.
    ```

    <Tip>
      That last sentence is worth writing. Without it a model will helpfully
      report "that order doesn't exist", which is both wrong and an information
      leak.
    </Tip>
  </Step>

  <Step title="Try it in the Playground">
    Test all four cases, not just the happy one:

    | You say | It should |
    | - | - |
    | "Where is order 10432?" | Ask for the email on the order |
    | Order number + correct email | Give the status |
    | Order number + wrong email | Say it could not find it — **not** that the order exists |
    | "Where is my order?" | Ask for both |
  </Step>

  <Step title="Ship it">
    The action works identically on WhatsApp and Telegram — you configured it
    once, on the agent.
  </Step>
</Steps>

## Doing better: skip the questions entirely

If the customer is [signed in and verified](/install/signed-in-customers), your
server already knows who they are. Send their customer id along with the request
and the agent can list *their* recent orders without asking anything.

That is the difference between a bot that interrogates people and one that
recognises them.

## What good looks like

<Accordion title="A real exchange">
  ```
  Customer   where's my order

  Agent      Happy to check. What's the order number, and the email address
             you used?

  Customer   10432, priya@example.com

  Agent      Order #10432 shipped on Monday with BlueDart and is due Tuesday.
             Tracking: https://…
  ```
</Accordion>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.