> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Inbox

> Every conversation, and how a person takes one over.

The inbox shows every conversation across every channel, as it happens.

## Finding a conversation

Press the search icon at the top of the list and type at least two characters.
The search covers **every conversation in the workspace**, not just the ones
already on screen, so you never have to scroll to load an old thread first.

It matches:

* the customer's **name**, **email** or **phone number** — a number can be typed
  with spaces, dashes or the country code, so `98765 43210` finds `+919876543210`;
* **any message** in the conversation, not just the latest — the matching line is
  shown in the list, so you can see why a conversation was found;
* for calls, the **number the call was with**, including people your calling
  campaigns rang;
* the **teammate** a conversation is assigned to.

Up to 50 matches are shown, newest first. If more conversations match, the list
says so; type more of the name or number to narrow it down. The tabs and filters
still apply to search results.

### Filtering

The filter button beside the search narrows the list by **channel**, **pinned**,
**from an ad** and **who it is assigned to**. Filters look through every
conversation in the workspace, not just the ones already on screen, and work
together with a search.

## Taking over

Anyone on your team can take a conversation over. The moment they do, **the
agent steps out** — it stops replying to that thread entirely.

That is not politeness. Two voices answering the same customer, contradicting
each other, is worse than a slower answer.

When a teammate replies, the agent later sees that reply as its own prior turn,
so it does not re-answer something a person just handled.

## Whose conversation is this?

Assign a thread to a teammate from the picker at the top of it, and it becomes
theirs — they get a **Mine** tab in the inbox listing everything assigned to
them, and everyone else can see at a glance who is dealing with it.

<Note>
  **Assigning is not the same as taking over**, and neither one implies the
  other.

  Taking over is a fact: somebody replied, so the agent stands down. Assigning
  is a decision about who is responsible, and you can make it before anyone has
  replied — the agent keeps handling the conversation until a person actually
  answers.

  So you can hand somebody a thread to keep an eye on without silencing the
  agent, and you can take a thread over without claiming it.
</Note>

**They are told.** The person you assign a conversation to gets a notification,
and it goes to them alone — nobody else on the team is told which of them is
dealing with a thread. Hand it on later and the next person is told too, so a
thread can move around the team without anyone having to be watching for it.

Assigning one to yourself sends nothing; you already know.

Set it back to **Unassigned** to put it back in the pool. That is how work gets
handed around rather than sitting with whoever happened to open it first.

<Tip>
  Above about three people sharing an inbox, this is the difference between a
  queue and a pile. Two people answering the same customer is the thing it
  prevents, and it prevents it earlier than taking over does.
</Tip>

## Saved replies

The answers you send twenty times a day — opening hours, refund timings, "could
you share your order number?" — kept in one place so everybody sends the same
sentence.

Open the saved-replies button under the reply box in the inbox. **Add** sits
beside the heading, and opens a form for the shortcut and the reply. Each saved
reply has a pencil to edit it and a bin to delete it, so a typo can be fixed
where you noticed it.

Choosing one adds it to whatever you have already typed rather than replacing
it, so you can write a line of your own and then reach for the policy.

<Tip>
  Write `{{name}}` where the customer's name should go. It is filled in when you
  insert the reply, so the same saved text reads as though you typed it — and
  for a website visitor who has never given a name it is quietly left out
  rather than sent as `{{name}}`.
</Tip>

<Note>
  Saved replies belong to the **workspace**, not to one person or one agent, and
  anybody on the team can add or edit one. That is the point: the value is that
  the refund policy does not drift between teammates.
</Note>

## Internal notes

You can leave a note on a conversation that the customer never sees. Notes are
your team talking **about** the customer, not to them, and they are never
replayed to the model — an agent that read one would believe it had said that
out loud.

## Statuses

| Status | Means |
| - | - |
| **Active** | The agent is handling it |
| **Escalated** | The agent asked for a person |
| **Human handling** | Somebody took over; the agent is silent |
| **Resolved** | Closed |

Assignment sits alongside these rather than among them: a conversation can be
active *and* assigned, or taken over by one person while assigned to another —
which is exactly what happens when somebody covers a colleague's thread.

## Media

## Whether you can reply freely

Above the reply box on a WhatsApp conversation, a line tells you where the
24-hour window stands, so you know before you type whether a free reply or a
form will go through.

| You see | It means |
| - | - |
| **Free replies and forms open · 14h 22m left** | Send anything. The count is in hours and minutes and updates while you have the thread open. |
| **Reply window closes in 42m** (amber) | The last hour. Finish what you are saying; after this only a template reaches them. |
| **WhatsApp closed this conversation 3h ago** | The window ran out. The reply box is replaced by a note; an approved template is the way back in. |
| **This customer hasn't messaged you** | No window has ever opened — you started this conversation with a template, and they have not written back. Forms and free replies open the moment they do. |

The customer messaging you again reopens the window immediately, for another 24
hours from that message.

### Sending a template from the conversation

When the reply box is replaced by one of those notes, **Send a template** sits
beneath it. It opens a list of your approved templates; choose one, fill in any
blanks it has, and it goes to that customer straight from the thread, where it
appears with a line saying it was sent from the inbox.

* **Every blank is yours to fill.** Nothing is pre-filled with the template's
  example values, so a customer is never greeted as somebody else.
* **A template with a picture at the top** uses the one saved with it. If none is
  saved, WhatsApp needs one on every send, so the dialog asks for its address.
* **A marketing template only goes to people who have not opted out.** Send it
  only to somebody who agreed to hear from you.

If you have no approved template yet, the same notes carry **Set up a template**,
which takes you to your Templates page.

## Whether a message arrived

Under each message the workspace sent, the inbox says what WhatsApp did with it.
"Sent" means we handed it to WhatsApp. That is not the same as delivered, and the
difference matters: WhatsApp accepts a message and then decides.

When it cannot deliver one, the message reads **Not delivered**, with WhatsApp's
own reason after it. A number that is no longer on WhatsApp, a picture WhatsApp
could not fetch, an account that is not allowed to start conversations — each
says so in its own words rather than leaving you to guess from silence.

<Note>
  **A message that was not delivered is not charged for.** WhatsApp bills for
  what it delivers, so when a failure comes back, the charge is credited to your
  balance and the line disappears from what you owe. You do not need to ask.
</Note>

Images sent by customers appear in the thread. On models that can see, recent
images are shown to the agent; older ones stay in the conversation as the
sentence they reduce to, because re-sending every photo on every turn would cost
a great deal for very little.

## Replying on WhatsApp

Inside the 24-hour window you can reply freely. Outside it, only an approved
template will reach the customer — the inbox will tell you which situation you
are in rather than letting you type into the void.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.