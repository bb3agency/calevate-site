> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Call your own API

> Give the agent one narrow endpoint of yours, and every rule that keeps it safe.

A custom action is an HTTPS endpoint of yours that the agent can call
mid-conversation — an order lookup, a stock check, a booking.

It is the most powerful thing you can give an agent and the one with the
sharpest edges, because it is reachable from a public chat by a stranger who may
be trying to talk the model into using it.

## Defining one

| Field | What it is |
| - | - |
| **Name** | 3–40 characters: lowercase letters, numbers and underscores, starting with a letter |
| **Description** | What the model reads to decide whether to call this at all |
| **Method** | `GET` or `POST` |
| **URL** | Must be `https://`. May contain `{{placeholders}}` |
| **Parameters** | Each with a name and a description |
| **Body template** | For `POST`. JSON, with `{{placeholders}}` |
| **Header secret** | Sent on every call so your endpoint can verify it is us |

### The description is the whole thing

The model has nothing else to go on. It decides whether to call your action, and
with what, entirely from what you write here.

**Weak:**

```
Gets order info
```

**Strong:**

```
Look up a customer's order. Requires BOTH the order number and the email
address on the order — if the customer has given only one, ask for the other
before calling this. Returns found: false when the pair does not match: say you
could not find it and ask them to check both, never say the order does not
exist.
```

The second one tells the model when to call it, when *not* to, what it needs
first, and how to phrase the failure. Every sentence prevents a specific bad
answer.

<Tip>
  Write the description, then read it back as though you knew nothing about your
  own systems. Anything you had to already know is a sentence that belongs in it.
</Tip>

### Parameters need descriptions too

Every parameter must say what it is, or the model will invent a value. `order_id`
with no description gets filled with something plausible-looking and wrong.

## Placeholders

Use `{{parameter_name}}` in the URL or the body:

```
https://shop.example.com/api/orders/{{order_number}}
```

```json theme={null}
{ "orderNumber": "{{order_number}}", "email": "{{email}}" }
```

Two rules the editor enforces before you can save:

* **Every placeholder must have a parameter behind it.** A `{{order_id}}` with
  no matching parameter would reach your API as the literal text `{{order_id}}`
  — failing in a way that looks like your bug rather than ours.
* **The body must still be valid JSON once the blanks are filled.**

Values are escaped when substituted, so a customer cannot break out of a string
and reshape your request.

## Values the platform fills

Some placeholders are filled by us from the conversation, not by the model, so
a caller cannot talk the agent into sending a different one. They have a dot in
the name, and you do not declare them as parameters.

| Placeholder | Value |
| - | - |
| `{{call.id}}` | The call's id — the same id `GET /api/v1/calls` lists. Empty outside a call |
| `{{call.from}}` | The number the call came from, E.164. Empty outside a call |
| `{{call.to}}` | The number that was dialled, E.164. Empty outside a call |
| `{{call.direction}}` | `inbound` or `outbound`. Empty outside a call |
| `{{conversation.id}}` | The conversation (`conv_…`) |
| `{{contact.id}}` | The contact (`cust_…`) |
| `{{contact.phone}}` | The contact's phone number, E.164, when known |
| `{{agent.id}}` | The agent (`ag_…`) |
| `{{workspace.id}}` | The workspace (`org_…`) — useful when you run customer workspaces |

```
https://crm.example.com/calls/{{call.id}}/notes?caller={{call.from}}
```

* They work in the path, the query, the body and in header values. The host
  must be written out in full — a placeholder before the path is refused.
* Header values take only these, never a model parameter.
* An unknown one, such as `{{call.nope}}`, is refused when you save.
* On text chat (WhatsApp chat and web chat) the `call.*` values are empty; the rest still fill.
  Voice calls on every surface, WhatsApp calls and web voice included, fill them.
  A test from the editor or `POST …/actions/{id}/test` has no conversation, so
  only `{{agent.id}}` and `{{workspace.id}}` fill.

Every call also carries `X-Call-Id`, `X-Conversation-Id`, `X-Agent-Id` and
`X-Workspace-Id` headers (each only when known), so you get them without
editing a template. A header you set yourself with the same name wins, whatever its capitalisation
(`x-call-id` replaces `X-Call-Id`).

## Reserved names

These clash with the agent's built-in tools and are refused: `search_knowledge`,
`capture_lead`, `escalate_to_human`, `send_media`, `send_link`.

Anything else you connect is namespaced, so no third-party tool can impersonate
one of the agent's own.

## Security

<AccordionGroup>
  <Accordion title="HTTPS only, checked twice" icon="lock">
    Once when you save it — so you hear about an `http://` address while looking
    at the form — and again at call time.
  </Accordion>

  <Accordion title="The URL is resolved before we fetch it" icon="shield">
    Validated **and DNS-resolved**, so an address cannot be used to reach a
    private network from inside ours.
  </Accordion>

  <Accordion title="Your secret is encrypted and shown once" icon="key">
    Stored encrypted, not readable from the dashboard, and never displayed again
    after you save it.
  </Accordion>

  <Accordion title="Thirty calls per conversation, per hour" icon="gauge">
    Custom actions are the only tool that spends *your* money, so the cap is a
    per-conversation one. A conversation is the unit a visitor controls, so it is
    the unit that gets bounded — a workspace-wide cap would be one a single
    visitor could exhaust for everybody.

    Thirty is far above any honest conversation. Checking an order, a booking and
    a balance twice over is under ten.
  </Accordion>
</AccordionGroup>

## Writing the endpoint

Four rules, in order of how much trouble they save.

<Steps>
  <Step title="Check the shared secret first">
    Before parsing anything.

    ```js theme={null}
    if (req.get("X-Agent-Secret") !== process.env.AGENT_SECRET) {
      return res.status(401).json({ error: "unauthorised" });
    }
    ```
  </Step>

  <Step title="Require two facts, never one">
    An order number alone is guessable — they are usually sequential. Require the
    number **and** something only the real customer knows, like the email on the
    order.
  </Step>

  <Step title="Fail identically for &#x22;not found&#x22; and &#x22;wrong match&#x22;">
    ```js theme={null}
    // Same response either way. A different one for each is an oracle telling a
    // stranger which order numbers are real.
    if (!order) return res.json({ found: false });
    ```
  </Step>

  <Step title="Return the smallest useful object">
    Everything you return may end up spoken to the customer. Return the status
    and the tracking link, not the whole order record with the customer's address
    and payment details in it.

    ```js theme={null}
    return res.json({
      found: true,
      status: order.status,
      carrier: order.carrier ?? null,
      trackingUrl: order.trackingUrl ?? null,
    });
    ```
  </Step>
</Steps>

<Warning>
  **Never write an action that changes something irreversible.** Cancelling an
  order, issuing a refund, deleting a booking — these should not be one
  conversation away from a stranger who is good at persuasion. Read actions
  first; for writes, [escalate to a person](/agent/escalation) instead.
</Warning>

## When it fails

A timeout, a 500, or an unreachable host does not crash the conversation. The
agent is told the lookup failed and answers accordingly — normally by
[handing over to a person](/agent/escalation) rather than guessing.

Which is the argument for having escalation switched on wherever you have
actions: the failure mode of "I could not check that" is much better when there
is somebody to pass it to.

## Sending leads somewhere

The other direction: signed outbound webhooks to any HTTPS endpoint, fired when
something happens rather than when the model asks. That is the lane that reaches
Google Sheets, Zoho and effectively any CRM through Zapier or Make.

## A full worked example

[Answer "where is my order?"](/guides/order-status) builds one end to end — the
endpoint, the action config, the description text, and the four cases to test.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.