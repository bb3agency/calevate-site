> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# How the pieces fit

> Workspace, agent, channel, contact — and which one owns what.

Four things, and most confusion later comes from mixing up two of them.

## Workspace

Your company. It owns billing, your team, your contacts and your WhatsApp
account. Everything is scoped to a workspace, and nothing crosses between two.

## Agent

One assistant, with its own knowledge, instructions, tools and channels. A
workspace can have several — a sales agent and a support agent, say.

<Warning>
  Agents do not share memory with each other. A customer who talks to your sales
  agent and your support agent is one **contact** in your inbox, but each agent
  only sees its own conversations. That is deliberate: two agents can be two
  brands, and one reading the other's transcripts would be a surprise nobody
  asked for.
</Warning>

## Channel

Where a customer talks to the agent: the **website widget**, **WhatsApp** or
**Telegram**. An agent has at most one of each.

Shopify, WordPress and PrestaShop are **not** channels. They are doors onto the
website widget — ways of getting it onto a page without editing theme code.

## Contact

A person. One contact can have several conversations across several channels,
and the agent will remember what was said on the others.

### How two channels become one person

This is the part worth understanding, because the obvious version of it leaks
data.

A person is joined across channels only on evidence **they did not give you**:

| Signal | Who vouches for it | Joins? |
| - | - | - |
| A signed customer id from your server | Your own server, by HMAC | Yes |
| The sender of a WhatsApp message | Meta delivered it from that number | Yes |
| The number a call arrives from | The caller's network | Yes |
| A number you imported, or sent us by API | **You** | Yes |
| A phone number typed into a chat | Nobody | **No** |

The last two rows are the same number and opposite answers, and that is the
whole design. A phone number is not a secret. If typing one into a chat were
enough to link records, anybody could type your customer's mobile and be handed
their WhatsApp history. The same number in your Contacts list joins fine —
because **you** put it there.

So the practical advice is: if you want website visitors recognised from their
phone number, upload them to your Contacts or send them through the API. A
number the agent was merely told is still saved, still shown in your inbox and
still callable. It just cannot decide who somebody is.

So: to have signed-in customers recognised, [your server signs their
id](/install/signed-in-customers). Everything else stays separate, and a
visitor who cannot be verified is treated as anonymous — which is the safe
default, not a degraded one.

<Note>
  **Telegram does not join.** There is no phone number unless the user shares a
  contact card, and matching on display name would merge two different people
  called Priya into one memory. Telegram conversations are read once a customer
  is linked by other means; they never do the linking.
</Note>

## What the agent remembers

Within a conversation, the recent history. Across conversations, a short digest
of what the same customer said on their **other** channels — so somebody who
asked on WhatsApp and then came to your website does not start again from
nothing.

That digest is deliberately small. It is capped at a handful of messages and
never includes your team's internal notes.

### How much of it the agent may use

Being recognised and being certain are not the same thing, and which one matters
more depends on your business. So this is a choice, not a default we made for
you. It lives on the **Actions** page under *Remembering them across channels*,
per agent.

<CardGroup cols={3}>
  <Card title="Use it">
    The agent reads what they said on their other channels and answers from it.
    Best when being recognised matters more than being certain — a restaurant, a
    shop, a booking line.
  </Card>

  <Card title="Mention it, then check">
    **The default.** The agent knows there is earlier history and asks them to
    confirm who they are before reading it.
  </Card>

  <Card title="Never, unless they signed in">
    Nothing from another channel is used, and the agent will not raise it. For
    clinics, lenders — anyone whose records should not be discussed with a voice
    on the phone.
  </Card>
</CardGroup>

On the default, a conversation sounds like this:

> **Them:** Hi, I messaged you about my delivery.
>
> **Agent:** I can see we have spoken before — can I just confirm the email
> address on your account?
>
> **Them:** [dana@example.com](mailto:dana@example.com)
>
> **Agent:** Thank you. You asked us to leave the parcel with the concierge
> rather than at the door, and the courier is re-attempting on Friday.

Three points worth knowing about that exchange:

* **Confirming means matching the email address *you* hold for them** — one you
  imported or sent by API. An address the agent was told earlier in the same
  conversation proves nothing, for the same reason a typed phone number does not
  link.
* **Three attempts, then it stops asking** for the rest of that conversation. A
  check that says "wrong, try again" forever is a way to guess.
* **Or a one-time code, if you turn that on** — see below.
* **Confirmation lasts for that conversation only.** Proving it is you today
  says nothing about who rings from that number tomorrow.

<Note>
  On **Never, unless they signed in**, only a customer already signed in on your
  own website counts as proven. Nothing said during the conversation will open
  it — which is the point of choosing it. That includes a one-time code: the
  setting means what it says.
</Note>

### Confirming with a one-time code

Asking for an email address is a check on what somebody **knows**, and an email
address is not really a secret — it is on your invoices, and whoever knows a
customer's mobile number usually knows their address too.

A one-time code is a check on what they **have**. Turn on *Confirm by one-time
code* under the same setting and the exchange becomes:

> **Them:** Hi, I messaged you about my delivery.
>
> **Agent:** I can see we have spoken before — I have sent a code to your
> WhatsApp on the number ending 4417. Can you read it back to me?
>
> **Them:** 394812
>
> **Agent:** Thank you. You asked us to leave the parcel with the concierge…

What to expect:

* **It goes to the number *you* hold for them**, never one they say in the
  conversation. If there is no such number, the agent falls back to asking for
  the email address.
* **You need an approved authentication template.** Meta writes the wording for
  these — see [One-time codes](/whatsapp/one-time-codes). Without one, the
  setting does nothing and the agent uses the email check.
* **Each code costs** the same as any authentication message, which is why the
  setting starts off. The agent will send at most **two per conversation**.
* **The code expires in ten minutes**, and three wrong answers stop the agent
  asking for the rest of that conversation — the same allowance the email check
  uses, shared, so trying both is not six goes at it.
* **The agent never knows the code.** It cannot read it out, and asking it to
  will not work: it can only send one and check one.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.