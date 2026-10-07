> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Notifications

> Be told when a call comes in, without logging in — in the console, and by email from your own Resend.

Something happens — your agent answers a call, a template is rejected, Meta
restricts your number — and you find out by opening the console. These settings
change that: choose what you hear about, and have it reach an inbox your team
actually reads.

Find them under **Settings → Notifications**. Anyone in the workspace can see
them; only **owners and admins** can change them.

## Platform notifications

The bell and the feed in the console. Every category is on until you mute it.

| Category | What it tells you |
| - | - |
| **WhatsApp** | Restrictions, bans, review verdicts and sending limits from Meta. Muting these is rarely wise. |
| **Templates** | Approvals, rejections, quality scores and category changes. |
| **Broadcasts and calling campaigns** | When a WhatsApp broadcast or a voice calling campaign finishes, and when an unusual share of it failed. |
| **Calls** | Calls your agent answered or placed, and the ones nobody picked up. |
| **Inbox** | Conversations the agent handed to a person. |
| **Knowledge** | Documents that could not be indexed after repeated attempts. |
| **Plan and usage** | Approaching your included messages, and plan changes. |
| **Connections** | Webhooks, tools, Telegram and voice failing or being switched off. |
| **Members** | People accepting an invitation to the workspace. |

Muting hides a category from the feed and the bell. Nothing is deleted —
unmuting brings its history back. Anything **critical** is shown regardless: a
muted category cannot hide the news that Meta has banned your account.

### Calls

An answered call and a missed call are different things, so they look different:
an answered call is a record, and a call nobody picked up is a customer who
wanted something. Both inbound and outbound calls are covered.

<Note>
  **Calls placed by a calling campaign are not announced one by one.** A
  four-hundred-person campaign would otherwise be four hundred notifications,
  and four hundred emails if you had asked for them. The campaign reports its
  own result when it finishes — see
  [Voice campaigns](/channels/voice-campaigns).
</Note>

## Receive notifications to email

Notifications can also arrive by email, from **your own Resend account**, at
whatever addresses you choose. That means a shared inbox — `support@` or
`ops@` — rather than the personal addresses people sign in with.

### Connecting Resend

Open the **Receive notifications to email** tab and fill in:

* **Resend API key** — from your Resend dashboard, under API Keys. It is stored
  encrypted and is never shown again.
* **Send from** — an address on a domain you have **verified inside Resend**.
  Resend will refuse anything else.
* **Sender name** — optional; what the recipient sees in their inbox.
* **Send notifications to** — one address per line, up to ten. These do not
  have to belong to people who log in here.

When you press **Connect and send a test**, we send a real message to **every**
address you listed. **Nothing is saved unless Resend accepts it.** A key that
looks right but belongs to an unverified domain fails here, while you are looking
at the screen, rather than weeks later as silence.

"Accepted" is not quite "arrived". A message can still land in a spam folder or
bounce, and we cannot see that from here. If a test does not appear within a
minute, check that address's **spam** folder first, then open **Emails** in your
Resend dashboard — it shows each message as *Delivered*, *Bounced* or *Delayed*.
If one address works and another does not, the problem is that address, not your
setup.

<Tip>
  Give Resend a key with **full access** if you want it to be easy to diagnose
  this yourself. A key restricted to "sending access" is the safer choice and works
  perfectly for notifications — it just means we cannot look at delivery status for
  you.
</Tip>

### Choosing what is emailed

Once an account is connected, each category above gets a choice:

| Choice | You get emailed |
| - | - |
| **No email** | Never. The default for every category. |
| **Only urgent** | Only the ones that mean messages are not reaching customers. |
| **Every one** | Everything in that category. |

To be told about every call, set **Calls** to *Every one*.

<Note>
  **Nothing is emailed until you ask.** A workspace that has never opened this
  page receives no notification email. That is stricter than before — urgent
  Meta alerts used to arrive uninvited — so if you rely on those, set **WhatsApp**
  to *Only urgent*.
</Note>

### If you would rather not connect Resend

You do not have to. With nothing connected, anything you switch on still reaches
your owners and admins, sent by us. Connecting your own account only changes who
it comes from and where it goes.

### If your account stops working

If Resend starts refusing — a revoked key, a lapsed domain — the connection shows
the recent failures and the reason on the settings page. Notifications keep
arriving in the console. An account that has never had a successful test is never
used, and mail goes out through ours instead of being lost.

**Disconnect** removes the stored key entirely. Your choices about what to hear
about are kept.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.