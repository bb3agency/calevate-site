> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Real-Time Event Injection

> Drive graph agent transitions and proactive agent speech from external events via REST, without waiting for the user to speak.

Speech is one input to a graph agent. Events are the other. When a customer opens a payment link, completes a form, or finishes a transaction on your website, you want the agent to react immediately rather than wait for the user to say something.

Event injection adds a REST endpoint, `POST /v1/call/{run_id}/events`, that lets your backend push named events into a live call. A matching event edge transitions the conversation and triggers proactive agent speech, all in under a second.

***

## Configuring an event edge

Add edges with `condition_type: "event"` and an `event_name`. They are ignored during normal speech routing, so they coexist freely with LLM and expression edges on the same node.

```json theme={"system"}
{
  "id": "awaiting_payment",
  "prompt": "User is completing payment via {method}. Reassure them.",
  "edges": [
    {
      "to_node_id": "confirmation",
      "condition_type": "event",
      "event_name": "payment_completed"
    },
    {
      "to_node_id": "payment_failed",
      "condition_type": "event",
      "event_name": "payment_failed"
    }
  ]
}
```

A node can mix all three edge types: event edges (fire on external signal), expression edges (fire on context variables), and LLM edges (fire on user speech). Whichever input arrives first drives the transition.

### Edge field reference

| Field            | Type      | Required | What it does                                                                          |
| ---------------- | --------- | -------- | ------------------------------------------------------------------------------------- |
| `condition_type` | `"event"` | Yes      | Marks this edge as event-triggered. Skipped during speech routing.                    |
| `event_name`     | string    | Yes      | The event name to match (e.g. `"link_opened"`, `"payment_completed"`).                |
| `to_node_id`     | string    | Yes      | Target node for the transition.                                                       |
| `priority`       | number    | No       | If multiple event edges match the same name, lower priority fires first. Default `0`. |

***

## Firing an event

```bash theme={"system"}
curl -X POST https://api.bolna.ai/v1/call/{run_id}/events \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "event": "link_opened",
    "properties": { "step": "verify" }
  }'
```

```
202 Accepted
{ "status": "accepted", "event": "link_opened", "run_id": "..." }

404 Not Found
{ "detail": "No active call found for this run_id" }
```

* `run_id` is returned by `POST /call` for outbound calls or arrives in your webhook for inbound calls.
* Fire-and-forget. The endpoint returns 202 as soon as the event is published.
* `properties` are merged into the agent's `context_data`, so they become available as `{variable}` substitution in node prompts and as `variable` references in expression edges.

***

## What happens when an event arrives

| Scenario                                                  | Behaviour                                                                                                                                                        |
| --------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Event matches an edge on the current node                 | Properties merged into `context_data`, transition fires, agent speaks proactively.                                                                               |
| Event doesn't match any edge                              | Properties still merged into `context_data`. No speech, but the next LLM call sees the new context.                                                              |
| Agent is currently speaking                               | Buffered at a safe point, processed after the current utterance finishes.                                                                                        |
| User is speaking when the event resolves                  | Node transitions, but proactive generation is **skipped**. The user's in-progress utterance routes on the new node. Prevents the agent from interrupting itself. |
| LLM is generating a response                              | Buffered until generation completes.                                                                                                                             |
| Two events arrive rapidly                                 | Processed sequentially in arrival order.                                                                                                                         |
| Event transitions to a static node                        | Cached audio plays in \~50ms. Zero LLM cost.                                                                                                                     |
| Event arrives on a node with no event edges for that name | No transition. Properties still merge into `context_data` silently.                                                                                              |

***

## How proactive speech stays natural

When an event drives a transition, the agent must speak without the user saying anything. Two design choices make this feel natural rather than scripted:

1. Event `properties` are merged into `context_data`, so the new node's `prompt` can reference them via `{variable}` substitution.
2. The conversation history is **not** polluted with fake user messages. The agent simply produces a new assistant turn on the new node.

The result: a transcript that reads as consecutive assistant messages, exactly as a human agent would speak after seeing a screen update.

***

## Latency

| Target node type | Latency               | Cost             |
| ---------------- | --------------------- | ---------------- |
| LLM node         | \~800ms (LLM + TTS)   | LLM tokens + TTS |
| Static node      | \~50ms (cached audio) | Zero             |

If a confirmation message never changes, point your event edge at a [static node](/docs/graph-agent/static-nodes) for the fastest possible response.

***

## Worked example: payment confirmation

The agent waits while the user completes a payment on the bank's website. Your backend fires `payment_completed` when the gateway confirms.

### Graph config (3 nodes)

```json theme={"system"}
[
  {
    "id": "awaiting_payment",
    "prompt": "Payment initiated. Reassure the user while it processes. Amount: {payment_currency} {payment_amount}.",
    "repeat_after_silence_seconds": 20,
    "edges": [
      {
        "to_node_id": "confirmation",
        "condition_type": "event",
        "event_name": "payment_completed"
      },
      {
        "to_node_id": "payment_failed",
        "condition_type": "event",
        "event_name": "payment_failed"
      }
    ]
  },
  {
    "id": "confirmation",
    "node_type": "static",
    "static_message": "Payment confirmed! Thank you. Have a great day.",
    "edges": []
  },
  {
    "id": "payment_failed",
    "prompt": "Payment failed: {error_reason}. Apologise briefly and offer to retry.",
    "edges": []
  }
]
```

### Backend code

```python theme={"system"}
import requests

def fire_event(run_id, event, properties=None):
    requests.post(
        f"https://api.bolna.ai/v1/call/{run_id}/events",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={"event": event, "properties": properties or {}},
    )

# Payment gateway webhook handler
fire_event(run_id, "payment_completed", {"ref": "TXN-98765"})
```

The `confirmation` node is static, so the user hears the confirmation in \~50ms with no LLM call. The `payment_failed` node uses `{error_reason}` from the event's `properties` to give the user a specific message.

<Tip>
  Add more event edges (`details_verified`, `payment_initiated`, etc.) to walk the user through a longer flow. The pattern stays the same: one edge per event name, one HTTP call per step.
</Tip>

***

## Notes on timing

* Events never interrupt active speech. They are queued until the agent is at a safe point (no audio playing, no response in flight) and processed then.
* If the user is mid-utterance when the event lands, the node transitions but the agent does not speak proactively. The user's utterance routes on the new node, so the agent's first words still feel responsive.
* The `run_id` is all you need. The same endpoint works regardless of where the call is running.
