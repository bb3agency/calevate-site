> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Insights

> What your calls came to: how they ended, the objections, why the no's were no's, what is broken on the customer's side, and a follow-up list for the team.

"Calls connected" says a call happened. **Insights** says what it came to, and what to do next.

## Switch it on

Call insights are off until you switch them on, for each agent: **Agents** → the agent → **Voice** → **Call insights**.
After each answered phone or WhatsApp call, the call is read once and noted (Playground, share-link and website
calls are not read, so your own tests are never counted):

* **How it ended** — converted, interested, call back, promise to pay, not interested, no decision, wrong person, do
  not call. *Converted* means the customer agreed to what the call was for: bought, booked, paid, signed up.
* **The objections** — in the customer's own words ("The EMI is too high", "Call me after salary day"), each with its
  kind: price, timing, trust, not a fit, no need, not their decision, uses someone else.
* **Why a no was a no** — price, timing, trust, not a fit, already has one.
* **What is broken on your side** — a payment link that does not open, a double charge, an app login that fails.
* **The next step** — a callback, a promised payment, details to send, a visit, or a lead ready for sales, with the
  day (and time) agreed.

Missed calls and calls where the customer never spoke are not read.

## The Insights page

**Insights** in the sidebar, for the last 7, 30 or 90 days, for every agent or one:

* **Answered calls read**, **Converted** (and its share), and how many are **to follow up**.
* **How calls ended**, **Why the no's were no's**, the **objections** by kind and the ones said most often, and what is
  **broken on the customer's side**, with examples.
* **The follow-up list** — every next step not yet done, the oldest due first, overdue ones in red. **Open** goes to the
  conversation; **Done** takes it off the list for everybody. Each contact shows once, with the step their latest
  call settled: a later call replaces an earlier step.

**Download CSV** on the Insights page saves the range and agent you are looking at, one row a call: when it was
read, the contact, the agent, how it ended, why not, the objections and issues, the next step and its day, and whether
the step is open, done or replaced by a later call.

## On each call

Open a call in **Usage** and its first tab shows the summary and the insight: how it ended, why not, the objections,
problems on the customer's side, and the next step.

Through the API and webhooks, `insights` comes on `call.analysed`, Get Call and Get Call Analysis: `outcome`,
`noReason`, `objections` and `issues` (each `{ text, kind }`), and `nextStep` (`kind`, `at`, `note`, `status`,
`followedUpAt`). `status` is `open` while the step is on the follow-up list, `done` once someone marked it Done, and
`replaced` when a later call with the same contact settled a newer step. `insights` is `null` when the agent's Call
insights is off, or for a call that was not read.

Only what the customer actually said is noted: nothing is guessed, and a date the call did not settle is left empty.
When a call's content is deleted, its insights go with it.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.