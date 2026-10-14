> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Your prices

> Set your own prices on top of ours, get paid into your own Razorpay account, and keep the difference.

You decide what your clients pay. They pay it **to you**, through your own
Razorpay account. We charge **you** our prices for the same usage, from your
balance, as it happens. The difference is yours, straight away — we never hold
or pass on your clients' money.

Everything is set under **White label → Prices**.

## Connect your Razorpay

<Steps>
  <Step title="Get your keys">
    In Razorpay, open **Account & Settings → API keys** and generate a key. You
    get a **key id** (`rzp_live_…`) and a **key secret**.
  </Step>

  <Step title="Paste both halves">
    Under **Get paid by your clients**, paste them and press **Connect**. They
    are checked with Razorpay before they are saved, and the secret is never
    shown again.
  </Step>
</Steps>

There is no webhook to set up: every payment is confirmed with Razorpay
directly, and one your client's browser did not report back is picked up within
minutes.

<Note>
  Use your **live** keys — test keys cannot take real payments and are refused.
  You can replace your keys at any time (after regenerating them, for
  instance). While any client pays you a monthly plan, you cannot disconnect
  Razorpay or connect a **different** account: their plans live in this one.
</Note>

Without Razorpay you can still bill clients however you like and fund them by
hand with **Add credit** — see [Clients](/white-label/clients).

## Usage prices

A **percent on top of our price**, for each kind of usage:

| Usage | Your client pays |
| - | - |
| Voice calls | our per-minute price + your % |
| Phone numbers | our monthly rent + your % |
| WhatsApp messages | our per-message price + your % |
| AI replies | what each reply costs + your % |

Leave a box empty to sell at our price. As you type, the page shows what your
clients will pay against what you pay — for example *Standard voice: ₹2.28 /
min (you pay ₹1.90)*. Every price your clients see — on their Billing page, the
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
of the month it paid for, and the client then moves to pay-as-you-go.

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

## What your clients see

Their **Billing** page shows their balance (and, on the trial, what is left of
it), an **Add money** button once you have connected Razorpay, and
pay-as-you-go, Pro and Scale at your prices. Checkout opens on **your** Razorpay account under your name.

## When your balance runs out

Your clients' usage — their free trials included — is charged to your balance.
When your available balance reaches zero, **your clients' calls, campaigns,
trials and new phone numbers stop**,
and their Billing page says service is paused. You are warned when your
balance runs low and again when it is empty. Add money to your own balance as
usual and everything resumes.

## Good to know

* **Rupees only** for client payments through your Razorpay.
* **Tax on your sale is yours** — we add none to what your clients pay you.
  Set your prices with that in mind.
* **History** — your own billing history lists each client's usage and plan
  fees by client name, at our prices; each client's history shows its charges
  at yours.

## Not available yet

* Your own plans with your own feature limits — clients get Pro or Scale
  features.
* Yearly plans for clients.
* Client payments in dollars.
* Automatic top-up for clients.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.