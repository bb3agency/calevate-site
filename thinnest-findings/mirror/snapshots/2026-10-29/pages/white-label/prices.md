> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Your prices

> Set your own prices on top of ours, get paid into your own payment account, and keep the difference.

You decide what your clients pay. They pay it **to you**, through your own
payment account: Razorpay for a reseller billed in India, Dodo Payments for one
[billed outside India](https://docs.thinnest.ai/workspace/regions.md). We charge **you** our prices for the same usage, from your
balance, as it happens. The difference is yours, straight away — we never hold
or pass on your clients' money.

Everything is set under **White label → Prices**.

## Connect your Razorpay

No Razorpay account yet? [Create one here](https://rzp.io/rzp/j599idX), then
come back to these steps. The same link is on the **Get paid by your clients**
card until you connect.

**1. Get your keys**

In Razorpay, open **Account & Settings → API keys** and generate a key. You
get a **key id** (`rzp_live_…`) and a **key secret**.

**2. Paste both halves**

Under **Get paid by your clients**, paste them and press **Connect**. They
are checked with Razorpay before they are saved, and the secret is never
shown again.

There is no webhook to set up: every payment is confirmed with Razorpay
directly, and one your client's browser did not report back is picked up within
minutes.

> [!NOTE]
>
> Use your **live** keys — test keys cannot take real payments and are refused.
> You can replace your keys at any time (after regenerating them, for
> instance). While any client pays you a monthly plan, you cannot disconnect
> Razorpay or connect a **different** account: their plans live in this one.

## Paid through Dodo (international)

If you are billed outside India, you connect **your own Dodo
Payments account** under **White label → Prices → Get paid by your clients**.
Your clients then add money on their Billing page into your account. Dodo
Payments is the seller on that checkout, so your clients see your account's
business name on the payment page and on their card statement — not ours.

**1. Get a key**

In Dodo Payments, open **Developer → API keys** and create a key.

**2. Paste it**

Paste it under **Get paid by your clients** and press **Connect**. It is
checked with Dodo Payments before it is saved, and it is never shown again.

A test key takes test cards only; connect your live key before your clients pay.
Prices and payments are in US dollars.

## Without a payment account

If you connect no payment account, your clients are **never stopped for their
own balance**: their usage is charged to **your** balance at our prices as it
happens, and what they owe you shows as their balance, at your prices, for you to
collect however you like. Your own balance still has to cover it. You can still
add money to a client by hand with **Add credit** — see
[Clients](https://docs.thinnest.ai/white-label/clients.md).

## Usage prices

A **percent on top of our price**, for each kind of usage:

| Usage | Your client pays |
| - | - |
| Voice calls | our per-minute price + your % |
| Phone numbers | our monthly rent + your % |
| WhatsApp messages | our per-message price + your % |
| AI replies | what each reply costs + your % |

Leave a box empty to sell at our price. As you type, the page shows what your
clients will pay against what you pay — for example *Premium voice: ₹2.40 /
min (you pay ₹2.00)*. Every price your clients see — on their Billing page, the
voice picker, phone numbers, broadcast estimates, their usage and history — is
yours.

### The top-up fee

When a client adds money, a fee is added at checkout: **our fee for the
client's plan plus the extra percent you set**. All of it goes to you, with the
rest of the payment.

## Plans

Your clients are customers just like you are ours. Each client has its own
plan — never yours — and can subscribe to **Pro** or **Scale** at your price:
our monthly price plus the amount you set.

Each month a client pays for its plan:

* the client's plan price comes back to it as **usage credit** for that month,
  spent at your prices;
* we charge **you** our monthly price, and give it back to you as credit for
  that client's usage that month — so you are not charged twice for the same
  usage.

A client can cancel from its Billing page; the plan keeps working until the end
of the period it paid for, and the client then moves to pay-as-you-go.

### Yearly

Tick **Offer yearly billing too** and your clients can also pay for Pro or
Scale a year at a time: our yearly price (twelve months of our monthly price)
plus the amount you set for the year. That amount is separate from the monthly
one, so a yearly discount of your own is up to you.

A year is paid up front, and works like a month, for a year:

* the client gets **the whole year's usage credit** at once, which lasts the
  year;
* we charge **you** our yearly price, and give it back as cover for that
  client's usage for the year.

## Your own plans

Instead of offering Pro and Scale, you can sell plans of your own. Under
**Prices → Your plans**, **Add a plan** and set:

* **Name** and **description** — what your clients see.
* **Built on** — Pro or Scale. This is what we charge you for each month a
  client pays: our monthly price for that plan, and you get the same amount
  back as cover for that client's usage.
* **Price** — what your client pays you each month, into your Razorpay.
* **Price a year** (optional) — sell the plan yearly too. A year gives the
  client twelve months of the plan's usage credit at once, and we charge you
  our yearly price for the plan it is built on. Leave it blank to sell the plan
  monthly only.
* **Usage credit** — what the client gets back each month to spend at your
  prices. It can be more or less than the price.
* **Limits** — agents, team members, calls at once and cloned voices. Each can
  only be lower than the plan it is built on; leave a box blank to keep that
  plan's number. **0 cloned voices** switches voice cloning off.
* **Features** — switch off **Studio voices**, **Projects & teams** (Scale
  only) or **Voice campaigns** for that plan.

Once you offer a plan, your clients see **only your plans** on their Billing
page, not Pro and Scale. Changing a plan's limits or features reaches every
client on it straight away; a new price or credit applies to new subscriptions.
**Stop offering** hides a plan from new clients; clients already on it keep it
until they cancel.

## Free trial

A new client starts on a **free trial**, as new accounts with us do. You decide
what it includes:

* **Voice minutes** — once per client (ours: 25).
* **AI replies** — each month while the client is on the trial (ours: 200).
* **WhatsApp messages** — once per client (ours: 200).

**You pay our price for every trial minute, reply and message**; the client
pays nothing. Turn the trial off and new clients start on pay-as-you-go
instead. A client leaves the trial when it first adds money (or you add credit
to it), or when it subscribes to a plan. Changes to the trial apply to new
clients and to clients still on their trial.

## Voices your clients can choose

Under **White label → Prices → Voices your clients can choose**, switch either
voice tier off — **Premium** or **Studio** — to hide it from your clients. They
won't see it when choosing a voice, and can't pick one from it. Keep at least
one on.

An agent that already uses a voice from a tier you switch off keeps it, so
nothing stops working. Switching **Studio** off also turns voice cloning off
for your clients, because a cloned voice is a Studio voice.

## What your clients see

Their **Billing** page shows their balance (and, on the trial, what is left of
it), an **Add money** button once you have connected Razorpay, and
pay-as-you-go, Pro and Scale at your prices (or only your own plans, once you
offer any), with a yearly option where you sell one. Checkout opens on **your**
Razorpay account under your name.

Under **Billing → History → Payments**, each client sees every payment it made
to you, top-ups and plan periods, with the amount, the date, your name and the
Razorpay reference. That is its receipt, and it can print the page. A tax
invoice for the sale is yours to issue: we do not raise one for a client.

## When your balance runs out

Your clients' usage — their free trials included — is charged to your balance.
When your available balance reaches zero, **your clients' calls, campaigns,
trials and new phone numbers stop**,
and their Billing page says service is paused. You are warned when your
balance runs low and again when it is empty. Add money to your own balance as
usual and everything resumes.

## Earnings

**White label → Earnings** shows, month by month for the last twelve months:

* **Clients paid you**: their top-ups (what they paid, fee included) and their
  plan payments, into your Razorpay.
* **We charged you**: what left your balance for them: their usage at our
  prices (less what their plan's cover already paid), their free trials, and
  our price for each plan period.
* **Net**: the difference, before Razorpay's own fees and your tax.
* **Usage margin**: their usage at your prices less our price for it, which is
  what your markups earn.

Money your clients have paid but not yet spent is counted when they pay, so the
page also shows how much they hold unspent today. Credit you add to a client by
hand is money you collected yourself: it is not counted as paid, but its usage
is charged to you as it happens. Months run on UTC.

## Good to know

* **Your currency.** Your clients pay in your account's currency. In India
  that is rupees; outside India, US dollars.
* **Tax on your sale is yours** — we add none to what your clients pay you.
  Set your prices with that in mind.
* **History** — your own billing history lists each client's usage and plan
  fees by client name, at our prices; each client's history shows its charges
  at yours.

## Automatic top-up for clients

On their Billing page, a client's owner or admin can switch on **automatic
top-up**: when the balance falls below an amount they choose, the amount they
choose is charged to a card or UPI Autopay they authorise once, into your
Razorpay, at most twice a day. Setting it up takes their first top-up at the
checkout, which is the authorisation. Three failed charges in a row switch it
off and say so on their Billing page.

Automatic charges need **recurring payments** switched on for your Razorpay
account. It is a separate approval from Razorpay, so ask them to enable
recurring (subsequent) payments before your clients rely on it. Automatic top-up
is for rupee accounts only.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.