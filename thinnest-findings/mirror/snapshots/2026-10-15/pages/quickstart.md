> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Quickstart

> An agent answering on your website, from your own pages, in about ten minutes.

This gets you to a working agent on your own site. WhatsApp and Telegram come
after, and neither is required to start.

<Steps>
  <Step title="Create an agent">
    In the console, create a workspace and then an agent inside it. The agent's
    name is what customers see in the widget header, so use the name you would
    want a customer to read.
  </Step>

  <Step title="Give it something to answer from">
    Open **Knowledge** and add your material. The fastest start is a site crawl:
    paste your homepage, choose a depth of 1 to 3 levels, and pick the pages you
    actually want indexed before anything is ingested.

    ```
    https://example.com
    ```

    A crawl only follows links. If you have unlinked pages — a pricing page
    reachable only from an email, say — add your `sitemap.xml` instead, which
    reaches them.

    <Tip>
      Add fewer, better pages first. Ten pages that answer real questions beat
      four hundred that mostly repeat your navigation.
    </Tip>
  </Step>

  <Step title="Tell it how to behave">
    On **Settings**, write a business description — the facts the agent falls
    back on when a search finds nothing — and your instructions for tone.

    Set the reply language, or leave it on **match the customer** so it answers
    in whatever language the customer wrote in.
  </Step>

  <Step title="Try it in the Playground">
    Ask it the three questions your customers actually ask. This is where you
    tune instructions against a live reply rather than guessing.

    Ask it something your material does **not** cover, too. It should say it
    does not know. If it invents an answer instead, your business description is
    doing too much work.
  </Step>

  <Step title="Put it on your site">
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

    <Info>
      The public key identifies which agent answers. It authorises nothing and
      is meant to be visible in your page source.
    </Info>
  </Step>

  <Step title="Watch the first real conversation">
    **Inbox** shows every thread as it happens, and **Contacts** shows the
    people behind them. When a conversation needs a person, anyone on your team
    can take it over and the agent steps out of the way.
  </Step>
</Steps>

## Next

<CardGroup cols={2}>
  <Card title="Recognise signed-in customers" icon="user-check" href="/install/signed-in-customers">
    Four lines on your server, and a logged-in customer stops being a stranger.
  </Card>

  <Card title="Add WhatsApp" icon="whatsapp" href="/channels/whatsapp">
    The same agent, answering on WhatsApp.
  </Card>

  <Card title="Let it do things" icon="bolt" href="/agent/actions">
    Look up an order, call your API, hand off to your helpdesk.
  </Card>

  <Card title="Send a broadcast" icon="paper-plane" href="/whatsapp/broadcasts">
    An approved template to people who opted in.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.