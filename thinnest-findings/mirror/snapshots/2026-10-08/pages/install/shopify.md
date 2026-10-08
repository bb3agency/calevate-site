> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Shopify

> A theme app embed — no code, no paste, and no theme edits to undo.

Shopify is the one platform where you install nothing separately: the widget
ships as a **theme app embed** inside our Shopify app.

## Turn it on

<Steps>
  <Step title="Online Store → Themes → Customise" />

  <Step title="App embeds">
    At the bottom of the left panel, switch on **ThinnestAI**.
  </Step>

  <Step title="Paste your public key">
    Into the block's setting, then **Save**.
  </Step>
</Steps>

An app embed applies to the whole theme rather than being dragged onto one
template, which is what a support widget wants. It also survives a theme change,
unlike a script pasted into `theme.liquid`.

<Note>
  The key is a setting rather than something we inject at install because a
  public key belongs to an **agent**, and you may have several. The theme editor
  is the only place you can say which one answers on this storefront.
</Note>

## Signed-in customers: not from the theme

<Warning>
  **A theme app embed cannot recognise your signed-in customers**, and it is
  worth explaining why rather than leaving you to wonder.

  Recognising a customer needs an HMAC of their id, computed with your identity
  secret. Liquid has no way to compute one, and there is nowhere in a theme
  extension to run code. Putting the secret in a theme setting would be worse
  than useless: a theme setting is readable by anyone who can view your page
  source, so publishing it would let any visitor forge any customer's identity.

  The tempting wrong answer is to emit the customer id **unsigned**. We do not.
  The server correctly treats an unsigned id as unverified and binds nothing to
  it — so it would do nothing at all while looking exactly like a working
  feature.
</Warning>

Doing it properly needs a Shopify App Proxy — a route under your own domain that
we serve, which can read the logged-in customer and sign. That is a piece of
work rather than a setting, and it is on our list.

If you need signed-in recognition on Shopify today, tell us: it moves up the
list when a real merchant is waiting on it.

## Your store's data is a different thing

Connecting **products, prices and order status** so the agent can answer "where
is my order" is not this. That lives on the **Actions** page, and it is a
separate connection.

Merchants look for it here, which is why it is mentioned here.

<Warning>
  Shopify does not support dynamic client registration, so connecting your store
  data currently requires registering an app on Shopify's side yourself. See
  [Actions](/agent/actions).
</Warning>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.