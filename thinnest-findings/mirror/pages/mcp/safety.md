> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Safety

> What needs your approval, why, and how repeated sends are prevented.

An AI assistant connected to your workspace can do real things — ring your
customers, message them, change what your public agent does. The MCP server is
built so that none of the consequential ones happen without you.

## What needs your approval

These tools refuse to run until you have approved them in the conversation:

| Because it… | Tools |
| - | - |
| Contacts a customer or spends money | `place_call`, `place_calls_batch`, `send_whatsapp_template`, `send_code`, `reply_to_conversation`, `record_event`, `enrol_in_sequence`, `resume_campaign` |
| Decides where your customers' data is sent | `create_webhook`, `update_webhook`, `update_action`, `enable_action` |
| Really calls your own system | `test_action` — on a POST action it does the write (a booking, a refund) |
| Deletes something or ends a call | `delete_agent`, `delete_knowledge`, `delete_action`, `delete_contact`, `delete_webhook`, `cancel_call`, `cancel_campaign` |

Two layers enforce this. Each of these tools is marked destructive, so your
client asks you before running it. And because a client can be set to
auto-approve, the tool itself **refuses** unless the assistant passes
`confirm: true` — and the refusal tells the assistant to describe exactly what
will happen and ask you first.

<Warning>
  If your client auto-approves tools, the refusal is the only thing that makes
  the assistant ask. Read what it proposes before you say yes — especially the
  number of people a call list or a send will reach.
</Warning>

## Conversations are not instructions

Your assistant reads what your customers wrote: messages, call transcripts,
summaries. A customer can write anything — including text designed to look like
an instruction ("add a webhook to this address", "change the agent to say…").

The server tells your assistant to treat that content as data, never as
something to act on. And every tool that could send your customers' data
somewhere new — webhooks, actions — needs your approval, so a message
engineered to exfiltrate data cannot do it on its own.

<Note>
  Changing an agent's instructions (`update_agent`) does **not** need approval,
  so that building an agent is not a confirmation on every edit. If your
  assistant proposes instruction changes you did not ask for while it is reading
  conversations, stop and check why.
</Note>

## Nobody is contacted twice

Every send and call tool requires an **idempotency key** — a name for that one
send, like `order-10432-confirmation`. If the assistant retries after a timeout
with the same key, the customer is not contacted again; the first answer is
returned instead.

Keys are per workspace and last 24 hours. If a key is reused for a **different**
message, nothing new is sent, and the answer starts with `REPLAYED:` so the
assistant knows its message did not go.

## See what an assistant did

**Settings → API keys → What AI assistants did** lists the changes assistants
made through your keys, newest first — and every time one was stopped to ask
for approval — with the key, the tool and how it went. It shows the latest 25;
the last 200 per key are kept. Reads and test chats are not listed. What the assistant was
asked to do, and the details it passed, are not recorded: the list is an audit
of actions, not a copy of your customers' data.

## The key is the boundary

The MCP server can do exactly what the API key can do over the
[API](/api-reference/introduction) — the same checks, the same limits, the same
refusals. To take its access away, revoke the key in **Settings → API keys**.

That is why the key's access level is the strongest control you have:

* A **Build** key cannot message a customer, send a code or place a call, whatever the
  assistant is told — those tools are not even offered, and the API refuses them.
* A **Read-only** key can only look.

Approvals protect you while you are watching. The key's access level protects
you when you are not. See [Choose what each key can do](/api-reference/authentication#choose-what-each-key-can-do).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.