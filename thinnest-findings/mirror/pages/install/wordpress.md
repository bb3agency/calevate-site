> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# WordPress and WooCommerce

> One file, three steps, and signed-in customers recognised.

WooCommerce runs on WordPress, so this is the same plugin for both — there is
nothing WooCommerce-specific to install.

## Install

<Steps>
  <Step title="Download the plugin">
    Get `thinnest-ai.php` from your agent's **Channels** page.

    It is a single file. WordPress accepts a single-file plugin dropped straight
    into `wp-content/plugins/`, which is a much shorter path than unzipping an
    archive into the right folder over FTP.
  </Step>

  <Step title="Upload and activate">
    Put it in `wp-content/plugins/`, then **Plugins → activate ThinnestAI**.
  </Step>

  <Step title="Paste your public key">
    **Settings → ThinnestAI**, and paste the public key from your Channels page.

    The field refuses anything that is not a real key rather than storing a typo
    — a mistyped key would otherwise render a broken tag on every page of your
    site with nothing to say why.
  </Step>
</Steps>

The agent is now on every page.

## Recognise signed-in customers

This is what the plugin can do that a pasted script tag cannot.

Add your **identity secret** — from the same Channels page — in
**Settings → ThinnestAI**. WordPress already knows who is reading the page, and
the plugin signs that user's id server-side.

The result: a logged-in customer's site chat, their WhatsApp messages and their
history become one customer in your inbox, instead of a stranger every time.

<Info>
  **The secret never reaches the page.** Only an HMAC of the user id does, and a
  digest of one id tells an attacker nothing about any other.

  Leave the field empty and everything else still works — visitors are simply
  anonymous, which is the safe default rather than a broken state.
</Info>

## What the plugin deliberately does not do

* No tracking, no phoning home, no version check. It emits one script tag. A
  plugin that talks to its vendor on every page load is one a security review
  removes.
* No admin notices, no upsell, no dashboard widget.
* No jQuery, no dependencies, no build step.

## Uninstalling

Deactivate and delete as normal. Your key and identity secret are removed with
it — leaving a signing secret in the options table of a site that uninstalled us
is not ours to decide to keep.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.