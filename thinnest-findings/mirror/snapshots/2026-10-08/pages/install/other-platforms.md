> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Wix, Squarespace, Webflow and anything else

> The script tag, where it goes on each platform, and which ones can recognise a customer.

Every platform with a "custom code" box works. A plugin for these would be a
worse version of a feature they already have.

## Where the snippet goes

<AccordionGroup>
  <Accordion title="Wix" icon="w">
    1. **Settings → Custom Code → Add Custom Code**
    2. Paste the snippet, apply it to **All pages**
    3. Place it in **Body - end**
  </Accordion>

  <Accordion title="Squarespace" icon="square">
    1. **Settings → Advanced → Code Injection**
    2. Paste the snippet into the **Footer** box
  </Accordion>

  <Accordion title="Webflow" icon="w">
    1. **Project settings → Custom code**
    2. Paste into **Footer code**
    3. **Publish**
  </Accordion>

  <Accordion title="Anything else" icon="code">
    Paste it just before the closing `</body>` tag on every page you want the
    agent on.
  </Accordion>
</AccordionGroup>

```html theme={null}
<script
  src="https://thinnest.ai/widget.js"
  data-key="pk_your_public_key"
  async
></script>
```

## Can it recognise signed-in customers?

Three answers, not two. The rule is one thing: signing needs code running on the
server that **renders the page**, holding a secret the visitor never sees.

| Platform | Signed-in customers | Why |
| - | - | - |
| WordPress / WooCommerce | **Yes, today** | The plugin does it |
| PrestaShop | **Yes, today** | The module does it |
| Any site with a backend | **Yes** | [Four lines on your server](/install/signed-in-customers) |
| Wix | **Possible, with work** | Velo gives you a Node backend and a Secrets Manager, so a small backend function can sign the member id. Not from the custom-code box |
| Shopify | **Possible, with work** | Needs a [Shopify App Proxy](/install/shopify), which is on our list |
| Squarespace | **No** | Runs no code on the server. Code Injection reaches the browser only, and a secret in the browser is a secret every visitor has |
| Webflow | **No** | Custom code runs in the browser only. Nothing there can hold a signing secret |

<Note>
  On the two "No" platforms, visitors stay anonymous to the agent. Everything
  else works normally — the agent answers, captures leads and escalates exactly
  as it does anywhere else.
</Note>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.