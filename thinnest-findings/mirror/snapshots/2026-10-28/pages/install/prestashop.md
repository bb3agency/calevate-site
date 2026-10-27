> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# PrestaShop

> A proper module — survives a theme change, and signs your customers.

Tested against PrestaShop 1.7 and 8.x, which share the hook set this uses.

## Install

**1. Download the module**

Get `thinnestai.zip` from your agent's **Channels** page.

**2. Upload it**

**Modules → Module Manager → Upload a module**, choose the zip, then
**Install**. No FTP, no theme editing.

**3. Configure**

Open **Configure** and paste your public key.

**4. Clear the cache**

**Advanced Parameters → Performance**. PrestaShop caches aggressively and
the widget will not appear until you do.

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

> [!NOTE]
>
> The secret never reaches the page; only an HMAC of the customer id does. Leave
> it empty and the widget still works, with visitors anonymous.

The customer's email and name are also sent, unsigned and deliberately so: they
decide what your inbox calls somebody, while the **id** is what decides which
history the agent may read.

## Uninstalling

Uninstall from the Module Manager. Your key and identity secret are deleted with
it.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.