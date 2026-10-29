> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Workflows

> Call, message and follow up with each contact over days — and let AI read every call and pick what happens next.

A workflow takes one contact at a time through a journey you draw: Agent calls them, AI reads the call and decides
how it went, the workflow waits, sends a WhatsApp or an SMS, calls again — whatever you connect. Each contact goes
through on their own, at their own pace, and you can see where every one of them is.

Open **Workflows** in the sidebar, then **Create workflow**:

* **Describe it, and AI builds it.** Say what should happen in a few sentences — *"When someone gets the tag new-lead,
  Riya calls them. If they're interested, send the brochure on WhatsApp and tell the sales team…"* — and AI draws the
  workflow, choosing your agents and templates by name. It is saved as a draft: look it over, fill what is marked in
  red (a template's blanks, an agent it could not tell apart), then publish. It can start on a date too (*"call
  patients the day before their visit"*) and add an **Extract details** step.
* **Start from a ready-made one**: qualify new leads, call back missed calls, appointment reminders, clinic
  appointment confirmations, payment reminders, document chase, win back old customers.
* **Start from a blank canvas.**

> [!NOTE]
>
> A workflow never changes an agent. A call it places is that agent's call in every way — its instructions, voice,
> steps and actions. The workflow decides only **when** to call or message and **what follows**. If you never use
> Workflows, nothing about your agents changes.

## What starts it

The **Start when** card at the left of the canvas:

| Start when | What happens |
| - | - |
| **Contacts I choose** | Press **Start** and pick a contact group, or everyone with a tag. |
| **A tag is added** | The moment a contact gets the tag, from the Contacts page or a workflow. |
| **A call ends** | After a phone or WhatsApp call — answered, missed, or cut off part-way — on any agent, or one you choose. **Which calls**: calls to your number (the default), calls Agent made (campaigns, callbacks), or both. A campaign call nobody picked up is never a missed call unless you choose it. Website and Playground conversations don't count, and neither does a call where Agent flagged the caller as spam. |
| **A form is sent** | When someone sends one of your WhatsApp forms. |
| **Your system asks** | Your CRM, website or app starts one contact through it — see [below](#start-it-from-your-system). |
| **A date on the contact** | Days before or after a date the contact holds — a visit, a renewal, a birthday — at the time you choose, in the contact's own clock. See [below](#start-on-a-date). |
| **An incoming webhook** | Any tool — a form builder, your shop, Zapier — posts to this workflow's own address. No API key, no fixed format. See [below](#start-from-a-webhook). |
| **On a schedule** | Every day, a weekday each week, or a day each month, at a time in your workspace's clock, for a contact group or everyone with a tag. |

Add **Only if…** to take through only the contacts who match — a tag, their name, email, phone or language, or
one of their own details.

Contacts without a phone number are skipped, and nobody is ever in the same workflow twice at once.

### Start from a webhook

Choose **An incoming webhook** and the card shows the workflow's own address. Paste it into your tool as where to send,
then tell the card where things are in what it sends:

* **Phone** (required), and optionally the **name** and **email**: a path into what the tool posts — `customer.phone`,
  `data.0.mobile`. Send a test from your tool and press **Refresh**: the card then suggests the paths it saw, with
  their values. A form post's field names (`customer.phone`) work as they are.
* **Keep a detail on the contact**: more of what it sends, saved as the contact's details (`visit_date` from
  `booking.date`), for **A date on the contact**, a **Conditional**, or `{{contact.visit_date}}`.

It takes JSON or a form post, up to 64 KB. A number without its country code takes your workspace's country. A new
number becomes a contact; a name or email fills a gap but never overwrites one you have. The address is the key: keep
it secret, and **Make a new address** if it leaks — the old one stops at once. One address starts at most 1,000 runs an
hour. Your tool gets `201` when a run started, `200` when they are already going through it, `202` when the workflow is
not live (what it sent is still kept for the mapping), `422` when there was no phone number where the card looks.

### Start on a date

Choose **A date on the contact**, name the detail that holds the date (`visit_date`), how many days before or after it,
and the time: *1 day before visit\_date, at 10:00*. Each contact whose date falls due is started that day, once the
time comes.

* **The contact's own clock.** 10:00 is 10:00 where they are, worked out from their number, as calling hours are. A
  number from a country spanning several time zones (the US) starts once it is 10:00 at the far end; a number that says
  nothing about where it is uses your workspace's clock.
* The detail holds a date written `2026-11-02` (year, month, day). **Extract details** saves dates that way, and
  **importing contacts** turns a column of dates like `02/11/2026` into it: day first, or month first for a file
  imported for US and Canadian numbers, unless a date in the column settles it (25/12 can only be day first). A column
  with anything in it that is not a real date is kept exactly as it was. Through the API, send `2026-11-02`.
* **Once for each date.** A contact is started once per date, whatever **Settings** says about going through again; a
  new date (next month's visit) starts them again. A run still going holds a new one back.
* Only on the day. If a date is changed to one that is already past, nobody is started for it.

## The blocks

Drag a block from the **Blocks** list onto the canvas, or click it. Draw from a block's right-hand dot to the next one.
Everything about a block is set on the block itself. **Tidy up**, at the top right of the canvas, lays every block out
left to right in the order the workflow runs, with a decision's answers top to bottom as you listed them.

| Block | What it does |
| - | - |
| **Call** | Agent calls the contact, from Agent's own number, inside the call window you set, with retries after busy, no answer or failed. Fill Agent's variables from the contact or from earlier blocks. |
| **Send WhatsApp** | Sends an approved template from your WhatsApp number, with its blanks filled. A reply reaches the agent that answers that number. |
| **Send SMS** | Sends a DLT template through your own SMS provider. |
| **AI decides** | AI reads a call and picks one of the answers you name — *Interested*, *Call back later*, *Not interested* — each with its own path. Below the confidence you set, it takes **Unsure**. |
| **Extract details** | AI reads a call and saves what the customer said into the contact's own details — a budget, a visit date, yes or no to a question. Name each detail and say what it is. |
| **Conditional** | Checks a rule — how a call went, an API's answer, a contact's details or tags — and goes **Match** or **No match**. |
| **Await** | Waits for a time (15 minutes, a day…), until a date and time, or for something to happen: they reply on WhatsApp, send a form, call you, get a tag, or your system sends an event. It takes **Arrived** when it happens and **Timeout** if it does not within the time you give it. |
| **Action** | Sends to, or reads from, your CRM or any API. Later blocks can use its answer. It goes **Success** on an answer in the 200s and **Failed** on any other answer or none; leave Failed unconnected and the run carries on down Success. |
| **Send to CRM** | Saves the contact in the CRM one of your agents has connected — [Zoho, Bigin or HubSpot](https://docs.thinnest.ai/agent/crm.md) — filling the fields pinned there from the contact and earlier blocks. It updates their record when one matches, else makes one. **Saved** or **Failed**; Failed left unconnected goes on as Saved. |
| **Book on calendar** | Books a meeting on the calendar one of your agents has connected — [Cal.com or Calendly](https://docs.thinnest.ai/agent/calendar.md) — at a time the run holds (`{{contact.visit_at}}`, or `2026-11-02 10:30`), in your workspace's clock (the contact sees it in theirs), for the contact's email. **Booked**; **Link instead** when the calendar cannot book directly (Calendly's free plan): the one-time link is `{{block.link}}`, for a WhatsApp after it; **Failed**. A booking's open exits end the run: it never goes on as if booked. |
| **Update contact** | Adds or removes tags, sets one of the contact's details (empty clears it), and can **assign** their conversations to a teammate or a **team** (Settings → Teams: the member with the fewest conversations assigned gets it), as the inbox does — they are told, and it shows under **Mine**. A tag added here starts and stops sequences and workflows just as one added by hand. |
| **Tell the team** | Your owners and admins, or a **team** you choose (Settings → Teams), get a notification, and an email if their notification settings send one. A team with nobody in it tells the owners and admins instead. |
| **Split test** | Sends each contact down one of two to four paths at random, by share — to find out which works better. |

### How sure AI decides should be

**Review decisions** on an **AI decides** block lists its recent answers on real calls — what AI said, how sure it
was, and the call's summary (switch on *Summarise each call* on the agent to see it). Mark the right answer for each,
or *A person should decide* when none fits.
From your marks it finds the lowest bar at which AI was right often enough — pick 90, 95, 98 or 99% — and says what
that means: *at 82% sure, AI settles 400 of 500 on its own, at least 98% right; 100 go to Unsure, for a person*.
**Use** sets it as the block's bar; publish to use it, and wire **Unsure** to a person (**Tell the team**, or
**Update contact** → assign).

The bar is set cautiously: twenty right answers out of twenty do not prove 99%, so a small sample earns a modest bar
and more marks earn a surer one. At least ten marked answers are needed before a bar is offered.

### A contact's own details

Besides a name, email, phone, language and tags, a contact keeps its own details — `budget`, `visit_date`, `doctor`.
They come from:

* **Extract details**, which saves what the customer said on a call;
* **Update contact**, which sets one, filled from anything earlier in the workflow;
* **Importing contacts**: every column of your file besides the number, name, email and language is kept under its
  header (*Appointment Time* becomes `appointment_time`). A blank cell keeps what the contact already had;
* the [contacts API](https://docs.thinnest.ai/api-reference/contacts/update-contact.md), as `fields`;
* **An incoming webhook**, from what the tool posts.

A later block reads one as `{{contact.budget}}`, and a **Conditional** checks it as a contact field. Calls an agent
places fill its `{{visit_date}}` from the contact too, on any call, not only a workflow's; a caller ringing in is not
given them. Names are written
in lower case with underscores; a contact holds up to 30, each up to 300 characters. They show under the contact's name
in **Contacts**.

When a call starts the workflow, **AI decides**, **Extract details** and **Conditional** can read that call too: choose
*The call that started this run*. Its outcome is *answered*, *no answer*, *busy*, *voicemail* or *failed* (cut off part-way). Agent
answers every call to your number, so a caller who needs ringing back is one whose outcome is anything but
*answered* — the **Call back missed calls** starter checks exactly that.

### Filling blanks

Anywhere you fill a blank or a variable, type text or pick a value: the contact's name, phone or email, an earlier
call's **summary** or **outcome**, or an earlier action's answer.

In an **Action**, values are written safely for where they go: encoded in the address (a `+` in a phone number stays a
`+`), escaped inside a JSON body (a quote in somebody's name can't break it), and kept to one line in a header.

## Settings

**Settings** in the builder's header:

* **Stop a contact's run when** they reply on WhatsApp, or get a tag you name (say, *booked*). Anyone who asks not to be
  contacted, or is on your do-not-call list, is always stopped.
* **Goal** — the AI decides answer that counts as success. The **Workflows** page shows how many runs reached it.
* **A contact can go through it again**: never, after their last run ends, or 30 days after it.
* **Quiet hours** — no calls or messages between these times, in the contact's own time (read from their number;
  for a country with several time zones, it must be outside quiet hours in all of them). A Call block's call window
  is the contact's time too.
* **End a run after** a number of days (up to 30).
* **Start at most** a number of contacts an hour. The rest wait their turn at Start and go in as room opens — for a
  big list, a busy webhook or a schedule over thousands. Test runs are never held back.

## Publish, test and start

* **Publish** saves a new version. Runs already going finish on the version they started on. If something would stop
  the workflow working — a call with no agent, an unapproved template, a blank left empty — it is marked in red under
  **to check**, and Publish waits until it is fixed. Amber items are worth a look but don't stop you.
* **Test** runs the canvas as it is now — saved or not — on your own phone. Tick **Skip waits** to turn a day's wait
  into seconds. Tests make real calls and send real messages. For a workflow that starts when a call ends, choose
  how that call went — missed, answered, cut off or busy — and the test begins as if it had.
* **Start** (for *Contacts I choose*) picks the group or tag and starts them.
* **Runs** shows the latest contacts and, for each, what happened block by block. The download button gives every
  run as a CSV: who, the block they are on or ended on, whether they reached the goal, when, and why it ended.
* **History** lists the published versions. **Restore** brings one back as the draft, canvas and settings; nothing
  changes for contacts until you publish it.
* **Results** puts the last 30 days on the canvas: how many reached each block, and how many took each AI answer.

## Start it from your system

Set **Start when** to **Your system asks** — the card then shows the exact address to call, with this workflow's id
and a copy button — and publish. Then call
[Start a Workflow Run](https://docs.thinnest.ai/api-reference/workflows/start-a-workflow-run.md) with a full API key:

```bash theme={null}
curl -X POST https://app.thinnest.ai/api/v1/workflows/wf_…/runs \
  -H "Authorization: Bearer ta_live_…" \
  -H "Content-Type: application/json" \
  -d '{ "to": "+91 98765 43210", "name": "Asha", "variables": { "order": "10432" } }'
```

* A number you have never sent before becomes a new contact, so a fresh lead can go straight in.
* `variables` are this run's own values: a blank written `{{contact.order}}` fills from `order`.
* `started: false` (not an error) means they are already going through it, or the workflow's settings don't let them
  go through it again.

### Clinic appointment confirmations

The ready-made **Clinic appointment confirmations** workflow sends a WhatsApp reminder, waits three hours for a reply,
and calls the patient if none comes. AI then sorts the call into **Coming**, **Moved** or **Cancelled**: confirmed and
cancelled patients are tagged, your front desk is told about a moved visit or a freed slot, and a patient who could not
be reached gets a text. For the call, pick the pre-built **Appointment confirmations** agent (**Agents** > **Start from a
pre-built agent**): it checks it is speaking to the patient before it mentions the visit, rebooks from your open times,
and never gives medical advice.

Start it the day before each visit with the visit's time and doctor. Import tomorrow's patients with an
*Appointment Time* and a *Doctor* column and start it for them, or have your clinic system start each one:

```bash theme={null}
curl -X POST https://app.thinnest.ai/api/v1/workflows/wf_…/runs \
  -H "Authorization: Bearer ta_live_…" \
  -H "Content-Type: application/json" \
  -d '{ "to": "+91 98765 43210", "name": "Asha", "variables": { "appointment_time": "tomorrow at 11 am", "doctor": "Dr Menon" } }'
```

* [List Workflows](https://docs.thinnest.ai/api-reference/workflows/list-workflows.md) gives every workflow's id and what starts it;
  [Get a Workflow](https://docs.thinnest.ai/api-reference/workflows/get-a-workflow.md) gives its blocks and, for one your system starts, the
  address to send runs to.
* **Tell a waiting run what happened.** An Await set to *Your system sends an event* waits for an event you name, such
  as `payment_received`. Send it with [Send a Workflow Event](https://docs.thinnest.ai/api-reference/workflows/send-a-workflow-event.md):

  ```bash theme={null}
  curl -X POST https://app.thinnest.ai/api/v1/workflows/events \
    -H "Authorization: Bearer ta_live_…" \
    -H "Content-Type: application/json" \
    -d '{ "to": "+91 98765 43210", "event": "payment_received" }'
  ```

  Only events sent after the run reached the Await count.
* From an AI assistant, the MCP tools `list_workflows`, `start_workflow_run` and `send_workflow_event` do the same. The SDKs have
  `workflows.list`, `workflows.get`, `workflows.startRun` and `workflows.sendEvent`.

## Good to know

* Calls and messages are billed exactly as any other call or message. AI decides is not charged.
* Calls keep the usual calling hours in the contact's own time, your plan's lines, and your balance. When every line
  is busy, contacts wait their turn rather than fail.
* On a call a workflow places, the agent's own **[After the call](https://docs.thinnest.ai/agent/after-the-call.md)** messages are not sent — the
  workflow decides what follows, so the contact never gets both.
* **Pause** a workflow from its menu on the Workflows page: contacts wait where they are until you resume it.
  **Delete** stops every run still going.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.