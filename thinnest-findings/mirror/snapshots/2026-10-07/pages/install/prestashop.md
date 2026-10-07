> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# PrestaShop

> A proper module — survives a theme change, and signs your customers.

Tested against PrestaShop 1.7 and 8.x, which share the hook set this uses.

## Install

<Steps>
  <Step title="Download the module">
    Get `thinnestai.zip` from your agent's **Channels** page.
  </Step>

  <Step title="Upload it">
    **Modules → Module Manager → Upload a module**, choose the zip, then
    **Install**. No FTP, no theme editing.
  </Step>

  <Step title="Configure">
    Open **Configure** and paste your public key.
  </Step>

  <Step title="Clear the cache">
    **Advanced Parameters → Performance**. PrestaShop caches aggressively and
    the widget will not appear until you do.
  </Step>
</Steps>

## Why a module rather than a paste

PrestaShop's own advice for third-party scripts is to edit `footer.tpl`. That
loses the widget the day you change theme, and needs FTP or the file editor to
undo.

A module survives a theme change, switches off from the back office, and can do
the one thing a paste cannot: sign the logged-in customer server-side.

## Recognise signed-in customers

Add your **identity secret** — from the same Channels page — in **Configure**.

A signed-in customer is then recognised across your shop and WhatsApp as one
person with one history.

<Info>
  The secret never reaches the page; only an HMAC of the customer id does. Leave
  it empty and the widget still works, with visitors anonymous.
</Info>

The customer's email and name are also sent, unsigned and deliberately so: they
decide what your inbox calls somebody, while the **id** is what decides which
history the agent may read.

## Uninstalling

Uninstall from the Module Manager. Your key and identity secret are deleted with
it.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.