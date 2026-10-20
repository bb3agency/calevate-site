> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Recognise signed-in customers

> Four lines on your server, and a logged-in customer stops being a stranger.

Optional, and the single highest-value thing you can add after the widget
itself. With it, a customer who is logged in to your site is recognised by the
agent — their website chat, their WhatsApp messages and their history become one
customer in your inbox.

Without it, every visitor is anonymous. That is the safe default, not a broken
one.

## Why a signature is required

Anyone can put anything in a POST body. If an unsigned user id were enough to
bind somebody to stored history, a stranger could read another customer's
conversations by guessing their user id.

So the claim is signed with a secret only your server and we hold, and we
recompute it before acting on it. A claim that does not verify is **dropped** —
never downgraded to "probably them".

## The recipe

Your identity secret is on the agent's **Channels** page. Keep it on your
server; it must never reach the browser.

<CodeGroup>
  ```js Node theme={null}
  import { createHmac } from "node:crypto";

  const hmac = createHmac("sha256", process.env.THINNEST_IDENTITY_SECRET)
    .update(String(user.id))
    .digest("hex");
  ```

  ```python Python theme={null}
  import hmac, hashlib, os

  digest = hmac.new(
      os.environ["THINNEST_IDENTITY_SECRET"].encode(),
      str(user.id).encode(),
      hashlib.sha256,
  ).hexdigest()
  ```

  ```php PHP theme={null}
  $hmac = hash_hmac('sha256', (string) $user->id, getenv('THINNEST_IDENTITY_SECRET'));
  ```
</CodeGroup>

Then render it into the widget tag:

```html theme={null}
<script
  src="https://thinnest.ai/widget.js"
  data-key="pk_your_public_key"
  data-user-id="42"
  data-user-hmac="a3f1…"
  data-user-email="priya@example.com"
  data-user-name="Priya"
  data-user-phone="+919876543210"
  async
></script>
```

If your site is a single-page app, call `ThinnestAgents.identify({…})` after
sign-in instead.

## Which fields do what

| Field | Signed | What it decides |
| - | - | - |
| `data-user-id` | **Yes** | Which history the agent may read. This is the one that matters |
| `data-user-hmac` | — | The signature over the id |
| `data-user-email` | No | What your inbox calls them |
| `data-user-name` | No | What your inbox calls them |
| `data-user-phone` | **Under the same signature** | Joins their WhatsApp messages to the same customer |

Only the **id** is signed as an identity. Name and email are written to the
record but never used to find one, so changing a display name does not mean
re-signing anything.

<Warning>
  **The phone number is the field that makes WhatsApp join up**, and it is
  exactly why the whole claim has to be signed. A phone number is trivially
  guessable, so an unsigned one would hand a stranger the matching WhatsApp
  history. Leave it out and everything else still works.
</Warning>

## Per channel, not per workspace

The secret belongs to a channel. If you run a brochure site and a logged-in app,
install two widgets with two secrets — a key lifted from the brochure site must
not be able to assert identities against the app.

## Common mistakes

<AccordionGroup>
  <Accordion title="Signing something other than the id">
    The digest must be of the **user id alone**. A digest of the secret itself is
    a constant and verifies nothing.
  </Accordion>

  <Accordion title="Computing the HMAC in the browser">
    That publishes the secret to every visitor, and the secret is the only thing
    stopping anyone forging any customer's identity.
  </Accordion>

  <Accordion title="Sending an id with no signature">
    It is treated as unverified and bound to nothing. The widget works; the
    customer stays anonymous, and it looks exactly like a working feature.
  </Accordion>
</AccordionGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.