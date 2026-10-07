> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Website widget

> The chat window on your own pages.

The widget is one script tag. It draws a launcher button, and the conversation
itself runs in an iframe on our origin.

## Install

```html theme={null}
<script
  src="https://thinnest.ai/widget.js"
  data-key="pk_your_public_key"
  async
></script>
```

Put it before the closing `</body>` tag on every page you want the agent on.
Your public key is on the agent's **Channels** page.

<Info>
  **The public key is meant to be visible.** It identifies which agent answers
  and authorises nothing. It is not your API key — that one can message your
  whole contact list and belongs in a server environment, never in HTML.
</Info>

On Shopify, WordPress or PrestaShop, use the plugin instead. Same widget, no
code, and it can recognise signed-in customers.

## Recognising signed-in customers

Add two attributes and your visitors stop being strangers:

```html theme={null}
<script
  src="https://thinnest.ai/widget.js"
  data-key="pk_your_public_key"
  data-user-id="42"
  data-user-hmac="a3f1…"
  data-user-email="priya@example.com"
  data-user-name="Priya"
  async
></script>
```

The HMAC is what makes it a claim rather than a guess. Without it the id is
treated as unverified and bound to nothing. [Full recipe, in Node, Python and
PHP](/install/signed-in-customers).

## What it renders

The widget is the richest channel: cards, carousels, buttons and forms all
render natively. Anything the agent shows here degrades sensibly on WhatsApp and
Telegram rather than arriving blank.

## Conversation history

A returning visitor sees their previous conversation. The reference is stored in
their browser, so it survives a page reload and a return visit, and it is
per-browser: the same person on their phone starts a new thread unless they are
[signed in and verified](/install/signed-in-customers).

## Branding

Free workspaces carry a "We run on ThinnestAI" line with a link. Paid plans do
not.

## Appearance

The launcher button, the agent's name and its logo are yours to set on the
agent's Settings page. The logo appears in the widget header and beside every
reply.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.