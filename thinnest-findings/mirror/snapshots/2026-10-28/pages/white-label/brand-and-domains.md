> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Brand and domains

> Put your name, logo and colour on everything, serve it from your own domain, and bring your own sign-in check and email sender.

## Your brand

**White label → Brand**: your product name, logo and colour. Every client
workspace wears it — the console, the sign-in page, share links, invitations
and notification email. Change it and every client sees the change.

## Help and support

Under **Brand → Help and support**, give your clients somewhere to go:

* **Help centre link** — the Documentation button in the console header and
  every "read more" link go here. Use your own help pages.
* **Support email** — named wherever your clients are told to contact support,
  including their Billing page.

Leave a box blank and that link or line is simply not shown on your domains.
Your clients are never sent to us.

## Your sign-in page

Under **Brand → Sign-in page**, choose how the page your clients sign in on
looks — sign in, sign up and password reset, on all your domains:

* **Side by side** — the form on the left, your picture filling the right half.
* **Centred** — the form in a card over your picture, full screen, on every
  device including phones.
* **Picture with highlights** — your picture fills the screen with your mark at
  the top left and, at the bottom, a headline (up to 80 characters) over up to
  three short points with ticks (up to 40 characters each). The form floats in a
  card on the right. Phones show the form only, without the words.

Upload a picture (PNG, JPEG or WebP, up to 2.5 MB; a landscape photo of about
1920 × 1080 works best). Without one, side by side keeps the default panel, and
centred and picture with highlights use your brand colour. **Remove picture**
goes back to the default. Your headline and points are kept if you switch to
another layout and back.

### Your privacy policy and terms

Under **Brand → Privacy policy and terms**, add links to your own privacy policy
and terms (full `https://` addresses). Sign-up asks your clients to agree to
what you list, and the sign-in page shows the same links beneath the form. They
open in a new tab. Leave both blank and sign-up asks for nothing. Our own
privacy page is never shown on your domains.

**Forgot password?** on the sign-in page sends a reset link in your name, from
your sender if you connected one, that opens on your domain to choose a new
password.

## No domain yet? Use a preview address

Under **White label → Domains → Preview address**, press **Create my preview
address**. You get a free address like `yourname.preview.thinnest.ai`, ready at
once — no DNS to set up.

It works exactly like a connected domain: your brand on every page, sign-in,
invitations to clients, and sign-up if you switch it on. Use it to try your
console, demo it, and start your first clients.

> [!NOTE]
>
> Our name is in a preview address, so connect your own domain before you go
> live with clients. The first visit to a new preview address can take a few
> seconds while its HTTPS certificate is issued.

## Your domain

**White label → Domains** puts the product on your own address, such as
`app.yourcompany.com`.

**1. Add the address**

Type or paste it, and choose which workspace it opens: your main workspace,
or one of your clients.

**2. Publish two DNS records**

The page shows both, ready to copy:

* a **TXT** record that proves the domain is yours;
* an **A** record that points the address at us.

Add them where your domain's DNS is managed (your registrar, Cloudflare and
so on).

**3. Verify**

Press **Verify**. If a record has not appeared yet, the page says which one —
DNS changes can take a while to spread.

**HTTPS is automatic.** The certificate for your address is issued the first
time it is visited after it is verified, and renewed for you. There is nothing
to upload.

> [!NOTE]
>
> An address can open one workspace at a time. One already in use elsewhere
> has to be removed there first; if it is held by a workspace outside your
> account, the page shows the record that proves it is yours.

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

With **Let people sign up here** off, your address is by invitation only. The
sign-up page asks for an invitation instead of a form, and the sign-in page
doesn't offer "Sign up". A person you've invited still signs up from the link
in their invitation, with the email address you invited.

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