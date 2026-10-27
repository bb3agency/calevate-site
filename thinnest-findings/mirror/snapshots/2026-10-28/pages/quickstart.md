> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Quickstart

> An agent answering on your website, from your own pages, in about ten minutes.

This gets you to a working agent on your own site. WhatsApp and Telegram come
after, and neither is required to start.

**1. Create an agent**

In the console, create a workspace and then an agent inside it. The agent's
name is what customers see in the widget header, so use the name you would
want a customer to read.

**2. Give it something to answer from**

Open **Knowledge** and add your material. The fastest start is a site crawl:
paste your homepage, choose a depth of 1 to 3 levels, and pick the pages you
actually want indexed before anything is ingested.

```
https://example.com
```

A crawl only follows links. If you have unlinked pages — a pricing page
reachable only from an email, say — add your `sitemap.xml` instead, which
reaches them.

> [!TIP]
>
> Add fewer, better pages first. Ten pages that answer real questions beat
> four hundred that mostly repeat your navigation.

**3. Tell it how to behave**

On **Settings**, write a business description — the facts the agent falls
back on when a search finds nothing — and your instructions for tone.

Set the reply language, or leave it on **match the customer** so it answers
in whatever language the customer wrote in.

**4. Try it in the Playground**

Ask it the three questions your customers actually ask. This is where you
tune instructions against a live reply rather than guessing.

Ask it something your material does **not** cover, too. It should say it
does not know. If it invents an answer instead, your business description is
doing too much work.

**5. Put it on your site**

Open **Channels** and copy your public key.

```html theme={null}
<script
  src="https://thinnest.ai/widget.js"
  data-key="pk_your_public_key"
  async
></script>
```

Paste it before the closing `</body>` tag on every page you want the agent
on. On Shopify, WordPress or PrestaShop, use the plugin instead — no code,
and it can recognise signed-in customers.

> [!NOTE]
>
> The public key identifies which agent answers. It authorises nothing and
> is meant to be visible in your page source.

**6. Watch the first real conversation**

**Inbox** shows every thread as it happens, and **Contacts** shows the
people behind them. When a conversation needs a person, anyone on your team
can take it over and the agent steps out of the way.

## Next

> **[Recognise signed-in customers](https://docs.thinnest.ai/install/signed-in-customers.md)**
>
> Four lines on your server, and a logged-in customer stops being a stranger.

> **[Add WhatsApp](https://docs.thinnest.ai/channels/whatsapp)**
>
> The same agent, answering on WhatsApp.

> **[Let it do things](https://docs.thinnest.ai/agent/actions.md)**
>
> Look up an order, call your API, hand off to your helpdesk.

> **[Send a broadcast](https://docs.thinnest.ai/whatsapp/broadcasts.md)**
>
> An approved template to people who opted in.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.