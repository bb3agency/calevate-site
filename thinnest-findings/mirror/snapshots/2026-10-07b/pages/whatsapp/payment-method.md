> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Adding a payment method in Meta

> Why Meta blocks your number for a payment method, where to add a card, which cards work, and what happens next.

If you connected **your own WhatsApp Business Account**, Meta charges WhatsApp's
message fees to a card on your Meta account. Until that card works, Meta blocks
the messages your business starts. You may see this on Connect WhatsApp:

> There is an error with the payment method. This will block business initiated
> conversations. Please add a new payment method to the account.

It's quick to fix, and nothing in ThinnestAI needs to change.

## Why it happens

Meta and ThinnestAI send separate bills ([how the two bills work](/meta/windows-and-pricing)):

| What | Who charges it | Paid from |
| - | - | - |
| WhatsApp's per-message fee | Meta | The card on your **Meta** account |
| Our 10% platform fee | ThinnestAI | Your ThinnestAI balance |

Your ThinnestAI balance can't pay Meta. With no working card, Meta blocks the
conversations **you start**: templates and broadcasts. Replies to customers who
messaged you first, inside the 24-hour window, keep working.

## Which account to add it to

The card goes on the **Meta business** that owns your WhatsApp Business Account,
not on your personal Facebook profile.

* The business is usually named after you or your company. It's the one you
  chose, or created, in Meta's popup when you connected WhatsApp.
* If you manage several businesses in Meta, the card must be on the one that
  holds this WhatsApp account. A card on another business doesn't count.

## Where to add it

1. Open **[business.facebook.com/latest/billing\_hub/payment\_methods](https://business.facebook.com/latest/billing_hub/payment_methods)**,
   signed in with the Facebook account you used to connect WhatsApp.
2. At the top left, check that the **business that owns your WhatsApp account** is
   selected. Switch to it if not.
3. Click **Add payment method**.
4. Choose your country and currency (for India: India, INR), then enter your card
   and business details.
5. Save. If Meta asks which payment method your WhatsApp account should use,
   choose this card.

## Which payment methods work

* A **credit or debit card**. Visa and Mastercard work most reliably.
* The card must allow **online and international transactions**. Many Indian
  cards have these switched off by default; turn them on in your bank's app or
  net banking before adding the card. A card with them off is accepted at first,
  then fails when Meta charges it, and the block comes back.
* Meta lists the options available for your country when you click **Add**.

## What happens next

* Once Meta accepts the card, the block usually lifts **within minutes**.
* Then **open or reload Connect WhatsApp** in ThinnestAI. That's when we ask Meta
  for your account's status: the warning clears straight away, and your
  messages go out normally.
* You don't need to reconnect your number or change anything in ThinnestAI.

<Note>
  **"I've added it" on Connect WhatsApp is a reminder, not a check.** We can't see
  your Meta payment details, so ticking it only stops us asking. Whether Meta can
  actually charge your card is what decides if messages go out, and if it can't,
  the warning comes back on its own.
</Note>

## Also worth doing: business verification

Meta may also show your business as **not yet verified**. That doesn't block
you, but until it's done Meta limits how many new people you can message each
day. Start it in Meta Business Settings → **Security Centre** → **Start
verification**; you'll need your business documents. See
[Business verification](/meta/verification) for what Meta asks for.

## Still blocked?

If the warning is still there when you reload Connect WhatsApp **an hour** after
adding a working card,
use **Contact support** (the help icon at the top of the app) and we'll check your
account's status with Meta.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.