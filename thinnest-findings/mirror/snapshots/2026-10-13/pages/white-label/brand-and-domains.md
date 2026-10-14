> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Brand and domains

> Put your name, logo and colour on everything, serve it from your own domain, and bring your own sign-in check and email sender.

## Your brand

**White label → Brand**: your product name, logo and colour. Every client
workspace wears it — the console, the sign-in page, share links, invitations
and notification email. Change it and every client sees the change.

## No domain yet? Use a preview address

Under **White label → Domains → Preview address**, press **Create my preview
address**. You get a free address like `yourname.preview.thinnest.ai`, ready at
once — no DNS to set up.

It works exactly like a connected domain: your brand on every page, sign-in,
invitations to clients, and sign-up if you switch it on. Use it to try your
console, demo it, and start your first clients.

<Note>
  Our name is in a preview address, so connect your own domain before you go
  live with clients. The first visit to a new preview address can take a few
  seconds while its HTTPS certificate is issued.
</Note>

## Your domain

**White label → Domains** puts the product on your own address, such as
`app.yourcompany.com`.

<Steps>
  <Step title="Add the address">
    Type or paste it, and choose which workspace it opens: your main workspace,
    or one of your clients.
  </Step>

  <Step title="Publish two DNS records">
    The page shows both, ready to copy:

    * a **TXT** record that proves the domain is yours;
    * an **A** record that points the address at us.

    Add them where your domain's DNS is managed (your registrar, Cloudflare and
    so on).
  </Step>

  <Step title="Verify">
    Press **Verify**. If a record has not appeared yet, the page says which one —
    DNS changes can take a while to spread.
  </Step>
</Steps>

**HTTPS is automatic.** The certificate for your address is issued the first
time it is visited after it is verified, and renewed for you. There is nothing
to upload.

<Note>
  An address can open one workspace at a time. One already in use elsewhere
  has to be removed there first; if it is held by a workspace outside your
  account, the page shows the record that proves it is yours.
</Note>

### Several clients on one domain

Each client can have its own address (`acme.yourcompany.com`,
`beta.yourcompany.com`), or all of them can sign in on one address that opens
your main workspace — from there each person goes to the workspaces they
belong to.

### Letting clients sign up

On an address that opens your **main** workspace you can switch **sign-up**
on. Anyone who creates an account there becomes your client, in a new
workspace of their own. Sign-up cannot be switched on for an address that
opens a client's workspace.

## Sign-in protection

Password sign-in and sign-up are protected by a Cloudflare Turnstile check. On
your domain it has to be **yours**:

1. In Cloudflare, add a Turnstile widget and list your domains in it.
2. Under **White label → Brand → Sign-in protection**, paste its **site key**
   and **secret key**. They are checked with Cloudflare before they are saved.

Until it is connected, people cannot sign in with a password on your domain.

## Email from your domain

Invitations, sign-up and password emails, and notifications to your clients
come from **your** sender once you connect your own Resend account under
**Settings → Notifications**. Until then they are sent in your brand's name
from a neutral address, never from ours.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.