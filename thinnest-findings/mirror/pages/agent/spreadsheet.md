> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Spreadsheet

> Your agent writes what it learns into your spreadsheet while it is still talking, and can look things up in it.

Someone rings and gives their name, their number and what they want. The agent
writes each answer into a row of your spreadsheet as it arrives, so a call that
ends after two questions still leaves those two answers behind. It can also look
somebody up — an order, a booking, a customer record — and answer from what you
already hold.

It works on every channel: website chat, WhatsApp, Telegram and phone calls.

We use **Grist**, a spreadsheet you can sign up for free at
[getgrist.com](https://www.getgrist.com). You connect your own account; we never
put your data in ours.

<Note>
  This is not the same as **Lead capture**, which stores names and numbers in your
  inbox here. This puts them in **your** spreadsheet, in columns you chose, where
  your team already works. You can have both on, and when you do the agent records
  the details in both places rather than choosing between them.
</Note>

## Connecting your spreadsheet

Go to **Actions**, find **Spreadsheet**, and click **Grist**.

<Steps>
  <Step title="Get an API key from Grist">
    In Grist, click your profile picture → **Account settings** → **Developer**,
    and create a key in the **API keys** section.

    It does not expire until you remove it, so unlike a calendar key there is
    nothing here that quietly stops working next year.
  </Step>

  <Step title="Paste it in">
    We call Grist once to check the key really belongs to someone. If it does
    not work you are told immediately.
  </Step>

  <Step title="Give us the document">
    Open the document in Grist, go to **Settings** and find the **API** section.
    Copy the **Document ID** from there.

    <Warning>
      The id in your browser's address bar is a **shorter** one, and the API
      cannot use it. If you paste that, we tell you so rather than letting you
      discover it as "document not found".
    </Warning>
  </Step>

  <Step title="Pick the table">
    We show you every table in the document with how many fields each has. Pick
    one. We then read that table's real column names and remember them.

    That is what the agent fills in. It cannot invent a column, and it cannot
    reach any other table or any other document.
  </Step>
</Steps>

## What the agent may do

Two switches, both **off** until you turn them on. Connecting your spreadsheet on
its own gives the agent nothing.

| Switch | What happens |
| - | - |
| **Fill in a row** | Writes what it has learned into your table — one row per conversation, filled in as the answers arrive |
| **Look something up** | Finds rows by matching one column exactly, so the agent can answer from what you already hold |

<Note>
  Every switch you turn on — here, on your calendar, anywhere — is described to
  the agent on **every turn of every call**. A handful is sharp and quick. A long
  list is a slower reply from an agent less sure which one you meant. Nothing
  stops you, so the restraint is yours.
</Note>

## Filling the lead's own row, not a new one

A lead list usually arrives with a row per person already in it — imported from
an ad, a form or a CSV — and the job of the call is to fill in the rest. Left
alone, every call adds a fresh line underneath and the row you already had stays
half empty.

On the spreadsheet card, pick the column that identifies each person under
**Update an existing row**, and how to compare it:

| Comparing as | Use it for | What matches |
| - | - | - |
| **Phone number** | Mobile numbers | The last ten digits, so `+91 98018 05137`, `919801805137` and `98018-05137` are one person |
| **Exact value** | An application id, an email, a name | The same text, ignoring case and spacing |

When a caller matches, their answers go into **that** row. When nobody matches,
a new row is added as before.

<Note>
  We never guess the column. A column called *Contact* might hold an email or a
  phone number, and a wrong guess writes one customer's answers over another's.
</Note>

### Filling in what the call already knew

On a campaign you already know things the customer is never asked — their name
and number came from your own list. A model told not to repeat those back never
volunteers them either, so they would stay blank.

**Fill from campaign variables** on the same card maps a column to a variable
your campaign supplies, one per line:

```
MOBILE_NO=phone
CANDIDATE_NAME=name
```

Anything the agent did learn wins; this only fills what was left blank.

## When to save: during the call, or after it

A switch on the spreadsheet card, and it only changes **phone calls**.

| | |
| - | - |
| **During the call** | Rows fill in as the customer answers, so the sheet is current while the call is still going. Each save costs the caller a short pause. |
| **After the call** | The agent just asks its questions. The whole conversation is read once it ends and the row is written in one go. |

Reading afterwards is usually the better call, and not only for the pause:

* An answer given in the first minute lands in the right column even if the
  question came in the fourth.
* Someone who corrects themselves — *"sorry, it's 42, not 41"* — is recorded
  once, correctly, instead of twice.
* A call that ends abruptly still leaves everything that was said.

What you give up is liveness: nothing appears until the call is over.

<Note>
  **Chat and WhatsApp always save as they go.** Nothing there ends the way a
  call does, so there is no "after" to wait for. The switch is about calls.
</Note>

## Save in the background

A switch on the same card. With it on, the agent **stops waiting for Grist**.

The answer is kept here the moment the customer gives it, and reaches your
spreadsheet within a minute. Nothing is lost if Grist is slow, and nothing is
lost if you have used up a free plan's calls for the month — the work waits and
goes through when it can.

**Turn it on if your agent answers the phone.** A caller hears every second the
agent spends waiting, and this removes all of them.

**Leave it off if you watch the sheet live** — during a campaign, say — and want
the row to appear as the words are spoken.

Either way the agent never claims something is saved when it is not.

## What your customer experiences

> **Them:** Hi, I'd like a quote for a kitchen.
> **Agent:** Of course. Can I take your name?
> **Them:** Priya Nair.
> **Agent:** Thanks Priya. And the best number to reach you on?

By the end of that call there is one row in your spreadsheet with both answers in
it, plus anything else you have columns for.

## A column for what happened

Make a column called **Summary** — or Notes, Remarks, Comments — and turn on
**Summarise each call** on the Voice page, and it fills with two or three
sentences about what the customer said and how the call ended.

It is the one column that is filled even when nothing else could be: somebody
who says only *"not interested, I'm busy"* answers no question on your list, and
that sentence is the whole useful record of the call.

<Warning>
  **Both halves are needed.** The switch is what starts it; making the column
  does not. And after adding any column in Grist, go back to the spreadsheet
  card and pick your table again — we cache the column list when you pin it, so
  a column added since is one the agent has never been told about.
</Warning>

## Things worth knowing

**One row per conversation.** Every answer goes into the same row, so you get one
line per customer rather than one line per thing they said.

**The agent fills in only what it was told.** A field it never heard is left
empty. It will not guess.

**Formula columns are read, not written.** Grist computes those itself. If
*every* column in the table is a formula we say so when you pick it — the agent
can read that table but cannot save anything into it.

**Looking something up is exact and case-sensitive.** `PRIYA` does not match
`Priya`. Use it for order numbers, phone numbers and reference codes, which is
what customers give verbatim anyway.

**It will not search for nothing.** If the agent has no value to match on it asks
the customer for one, rather than returning whatever happens to be at the top of
your table.

**At most five rows come back from a lookup.** More than that read aloud is a
paragraph nobody can follow on a phone.

<Warning>
  **If you rename or delete a column in Grist, tell us.** We remember your columns
  from when you picked the table. Rename one and saves start failing. Fixing it
  takes ten seconds: open the card and choose the table again.
</Warning>

**Free Grist has limits, and they are Grist's rather than ours.** A free site
allows **3,000 API calls a month** and **5,000 rows per document**. A busy phone
line can use those, and when they are gone Grist refuses — your card says so.
*Save in the background* handles the smaller bumps for you.

**Disconnecting keeps your data.** Rows already written stay in your spreadsheet;
they are your records, not ours to remove. Anything still queued and not yet
written is discarded, and we tell you how many that is before you are left
wondering.

## If it stops working

The card says **Needs attention** and shows what Grist said.

Usually it is one of three things: the key was removed in Grist, the document is
full or out of monthly calls, or a column was renamed. Create a new key and use
**Replace key** if it is the first — your switches and your chosen table are
remembered.

## Deliberately not included

The agent cannot reach **any other document or table**, even though your API key
could. It cannot **create or delete columns, tables or documents**, and it cannot
**delete rows**. It fills the one table you pointed it at, and reads from it.

Nobody phoning your business has a good reason to reshape your spreadsheet, and
the safest way to guarantee that is not to give the agent the ability at all.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.