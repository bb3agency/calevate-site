> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Send a message

> POST /api/v1/messages — one approved template to one customer. The send API for your own software; no agent needed.

<Note>
  **No agent needed.** This is how your own CRM or software starts a WhatsApp
  conversation — pick **WhatsApp API** at signup, connect your number, create an
  API key and call it. When the customer writes back, their messages go to your
  platform and you answer with
  [Reply to a conversation](/api-reference/reply-to-conversation). See
  [Connect External Agent/CRM](/whatsapp/external-agents).
</Note>

```http theme={null}
POST /api/v1/messages
Authorization: Bearer ta_live_…
Content-Type: application/json
Idempotency-Key: order-10432-confirmation
```

```json theme={null}
{
  "to": "919876543210",
  "template": "order_confirmation_v1",
  "variables": ["Priya", "#10432", "Tuesday"],
  "buttonVariables": ["10432"]
}
```

## Body

<ParamField body="to" type="string" required>
  The customer's number. E.164 — **include the `+` and the country code** (a leading `00` works too). Without a `+`, a number of ten digits or fewer is read as an Indian number and `91` is added, so a number from anywhere else sent bare would go to the wrong country. Spaces are fine.

  Normalised the same way the contact importer does, so `+91 98765 43210` and
  `919876543210` are the same customer rather than two.
</ParamField>

<ParamField body="template" type="string" required>
  The name of an **approved** template on your account.
</ParamField>

<ParamField body="variables" type="string[]">
  Values for `{{1}}`, `{{2}}` … in the body, **in order**.
</ParamField>

<ParamField body="buttonVariables" type="string[]">
  The value for a link button's blank. Separate on purpose — Meta wants it in a
  different component, and sending it in `variables` breaks both the words and
  the link.
</ParamField>

<ParamField body="headerMediaUrl" type="string">
  The picture for a template whose header is an image, video or document.

  **Required on every send for those templates.** WhatsApp does not reuse the
  file the template was approved with — that one exists for the review — so a
  media template sent without a picture is refused with `409`.

  Leave it out and the template's own stored picture is used. Send one and it
  wins, which is usually what you want here: the photograph on "your order has
  shipped" is that customer's parcel, not a stock image kept on the template.

  WhatsApp fetches it itself, so it has to be a public address.
</ParamField>

<ParamField body="language" type="string">
  Which approved language version to send, exactly as approved — `en_US`, `hi`.

  Leave it out and you get the oldest approved version, which is the one that
  existed when you wrote the integration. That is deliberate: adding a language
  in the console must never change what a working integration sends.

  Ask for one that is not approved and the `404` names the ones that are, in an
  `available` array, so you can fix it from the response.
</ParamField>

<ParamField body="formData" type="object">
  Pre-fills a form the template opens. Only keys the form declared as
  pre-fillable reach the screen; anything else is ignored rather than refused.
</ParamField>

<Note>
  **A template is identified by its name**, not by an id — so the name is
  stable across edits, and names are per account, which is why another
  business's template is invisible to you.
</Note>

## Response

```json theme={null}
{ "ok": true, "messageRef": "wamid.HBgLOTE5…" }
```

`messageRef` is WhatsApp's own receipt for the message. It is what delivery and
read reports are reported against, and what to quote if you ever have to ask
what happened to one.

A repeat of an idempotency key that already succeeded answers identically, with
one field added and a header alongside it:

```json theme={null}
{ "ok": true, "messageRef": "wamid.HBgLOTE5…", "deduplicated": true }
```

```
Idempotent-Replayed: true
```

Every refusal is `{ "error": "…" }` with the status from
[Errors](/api-reference/errors) — and the sentence is meant to be read, not
matched on, because it names the specific thing that was wrong.

<Warning>
  `ok: true` means WhatsApp **accepted** it — not that it arrived. Delivery
  and read are reported afterwards and appear in the inbox.
</Warning>

## Free plan

The Free plan includes **200 WhatsApp messages, one time**, with none of our
charges — you pay Meta directly on your own account. Past that, sends are
refused with `402` until you switch to **Pay as you go** (no monthly fee).
Messages your customers send you are never counted.

## Idempotency

Send an `Idempotency-Key` header. A repeat of the same key sends nothing.

```
Idempotency-Key: order-10432-confirmation
```

A body field named `idempotencyKey` works too; the header wins if you send both.

<Warning>
  **Derive the key from the thing that happened, never from a random value.**
  The point is that your retry, your queue's redelivery and your colleague's
  manual re-run all produce the same key. A UUID generated per attempt is a key
  that never repeats and therefore never protects anything.
</Warning>

The claim is written **before** the send, which protects against the case that
actually happens: two retries arriving at once, rather than one after the other.
The second of the two gets `409` — *that key is already being processed* — and
not a second message. Retry after a moment and the answer will be waiting.

A **refusal** is remembered as well, and replayed as itself. If the first attempt
came back `409 template not approved`, so does the retry, rather than sending
once the template is approved an hour later under a key you thought was spent.

<Note>
  **Keys are honoured for 24 hours.** That is Stripe's window and long enough for
  any retry worth making. After it, the same string is a new request and sends
  again — so a key you reuse on a schedule, like `daily-digest-priya`, will send
  each day rather than replay for ever. That is usually what you want; it is
  worth knowing either way.
</Note>

## Worked example

<CodeGroup>
  ```bash cURL theme={null}
  curl -X POST https://app.thinnest.ai/api/v1/messages \
    -H "Authorization: Bearer $THINNEST_API_KEY" \
    -H "Idempotency-Key: order-10432-confirmation" \
    -H "Content-Type: application/json" \
    -d '{
      "to": "919876543210",
      "template": "order_confirmation_v1",
      "variables": ["Priya", "#10432", "Tuesday"]
    }'
  ```

  ```js Node theme={null}
  async function confirmOrder(order) {
    const res = await fetch("https://app.thinnest.ai/api/v1/messages", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${process.env.THINNEST_API_KEY}`,
        "Content-Type": "application/json",
        // Derived from the order, so a retry cannot double-send.
        "Idempotency-Key": `order-${order.id}-confirmation`,
      },
      body: JSON.stringify({
        to: order.customer.phone,
        template: "order_confirmation_v1",
        variables: [order.customer.firstName, `#${order.id}`, order.etaLabel],
      }),
    });

    if (res.status === 429) {
      const wait = Number(res.headers.get("Retry-After") ?? 60);
      throw new RetryableError(`rate limited, retry in ${wait}s`);
    }

    if (!res.ok) {
      // 400/401/404/409 are all "do not retry unchanged".
      throw new Error(`send failed: ${res.status} ${await res.text()}`);
    }

    return res.json();
  }
  ```

  ```python Python theme={null}
  import os, requests

  def confirm_order(order):
      res = requests.post(
          "https://app.thinnest.ai/api/v1/messages",
          headers={
              "Authorization": f"Bearer {os.environ['THINNEST_API_KEY']}",
              "Idempotency-Key": f"order-{order['id']}-confirmation",
          },
          json={
              "to": order["customer"]["phone"],
              "template": "order_confirmation_v1",
              "variables": [
                  order["customer"]["first_name"],
                  f"#{order['id']}",
                  order["eta_label"],
              ],
          },
          timeout=15,
      )

      if res.status_code == 429:
          raise Retryable(int(res.headers.get("Retry-After", 60)))

      res.raise_for_status()
      return res.json()
  ```
</CodeGroup>

## Asking for something back

A template can carry a button that opens a **form**. `formData` fills it in
before the customer sees it:

```json theme={null}
{
  "to": "919876543210",
  "template": "delivery_details_v1",
  "variables": ["Priya", "#10432"],
  "formData": { "order_number": "10432" }
}
```

An order number your system already knows should arrive typed in rather than
asked for. Only fields marked pre-fillable when the form was built accept a
value.

Answers return into the conversation and are stored against it, so they are
readable in the inbox and usable afterwards as structured data.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.