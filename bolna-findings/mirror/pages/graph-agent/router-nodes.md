> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Router Nodes

> Silent dispatch nodes that route the caller to the right node in one turn, without speaking.

Some nodes in a flow only exist to decide where to go next: send VIP callers to a different greeting, classify a request into billing / support / sales, or branch on time of day before the conversation starts. A router node does exactly that and nothing else. It never speaks. On entry it evaluates its edges and transitions again, within the same turn, until it lands on a node that does speak.

This keeps routing logic in its own place in the graph instead of hiding it inside a conversational node's edges, and it lets you build a silent classifier or a pre-conversation dispatcher.

<Note>
  Router nodes are configured through the agent JSON / API today. Visual editor support is coming.
</Note>

## How a router node picks an edge

On entry, a router evaluates its edges in three phases and takes the first that resolves:

| Order | Edge type                                  | Cost                                             |
| ----- | ------------------------------------------ | ------------------------------------------------ |
| 1     | **Expression** edges, in `priority` order  | Instant, no LLM call                             |
| 2     | **Intent** edges, via one routing-LLM call | One routing call (same as normal intent routing) |
| 3     | The **unconditional** catch-all            | Instant fallback                                 |

Two things to keep in mind:

* **The catch-all is always a fallback.** Unlike a normal node, an unconditional edge on a router never pre-empts a matching expression edge, regardless of its `priority`. It is taken only when nothing else matches (including when the intent call finds no match).
* **At most one routing-LLM call per turn.** Every hop still checks its expression edges first; only the intent (LLM) call is capped. So if a router chains into another router that would also need an intent call, the second one takes its catch-all instead. A purely deterministic chain (expression + unconditional only) resolves in \~0ms with no LLM call at all.

A router always advances to a speaking node in the same turn, so a caller never hears dead air waiting on it.

<Note>
  `priority` orders edges **within a phase** (expression edges among themselves, intent edges among themselves). It cannot make an intent edge outrank an expression edge — expression edges are always checked first. If you want an intent decision to win a case, don't also give the router an expression edge that matches that case.
</Note>

## Configuring a router node

A router node is one entry in your agent's `nodes` array — the same array that holds every other node, under `llm_agent.llm_config`. See [Full example](/docs/graph-agent/full-example) for a complete agent payload, and [Edges & routing](/docs/graph-agent/edges-and-routing) for the expression syntax, operators, and built-in variables (like `_total_turns`) used below.

Set `node_type` to `"router"`, leave the prompt empty, and give it edges plus an unconditional catch-all:

```json theme={"system"}
{
  "id": "entry_dispatch",
  "node_type": "router",
  "description": "Send VIP callers to the VIP greeting, everyone else to the standard greeting.",
  "edges": [
    {
      "to_node_id": "vip_greeting",
      "condition_type": "expression",
      "expression": {
        "conditions": [
          { "variable": "recipient_data.customer_tier", "operator": "eq", "value": "vip" }
        ]
      }
    },
    { "to_node_id": "greeting", "condition_type": "unconditional" }
  ]
}
```

### Field reference

| Field         | Type       | Required | What it does                                                                                                       |
| ------------- | ---------- | -------- | ------------------------------------------------------------------------------------------------------------------ |
| `node_type`   | `"router"` | Yes      | Marks the node as a silent dispatcher.                                                                             |
| `edges`       | array      | Yes      | Expression, intent, and unconditional edges. Must include an unconditional catch-all. Event edges are not allowed. |
| `description` | string     | No       | The classification objective shown to the routing LLM when the router has intent edges (a router has no `prompt`). |

A router node must **not** set `prompt` or `static_message` — it never speaks. On expression and unconditional edges, the `condition` string is just a human-readable label; only `expression` (for expression edges) and `condition` text on intent edges affect routing.

## Intent routing on a router

An **intent edge** is an edge with a `condition` and no `condition_type` (the default edge type — see [Edges & routing](/docs/graph-agent/edges-and-routing)). A router can use intent edges to classify what the caller wants and dispatch silently. Because a router has no prompt, the routing LLM is guided by three things:

* Each intent edge's `condition` (and optional `function_description`) — the primary signal.
* The router's `description` — its overall objective.
* The agent-level `routing_instructions`, if set.

Do not put conversational instructions on a router. It never speaks and can only pick a transition, so prompt-like text there does nothing.

## Example: silent NLU dispatcher

Classify the caller's request and route to the right department. The escalation guard runs first (instant, no LLM), then the intent call, then the catch-all when the request is unclear.

```json theme={"system"}
{
  "id": "topic_router",
  "node_type": "router",
  "description": "Route the caller to billing, technical support, or sales.",
  "edges": [
    {
      "to_node_id": "human_handoff",
      "condition": "Conversation too long, escalate",
      "condition_type": "expression",
      "priority": 0,
      "expression": {
        "conditions": [
          { "variable": "_total_turns", "operator": "gte", "value": 12 }
        ]
      }
    },
    {
      "to_node_id": "billing",
      "condition": "The user asks about payments, invoices, or charges.",
      "parameters": { "billing_issue": "string" }
    },
    {
      "to_node_id": "tech_support",
      "condition": "The user reports a technical problem with their service."
    },
    {
      "to_node_id": "sales",
      "condition": "The user wants a new connection or a plan upgrade."
    },
    { "to_node_id": "clarify", "condition_type": "unconditional" }
  ]
}
```

What happens on a turn:

* If `_total_turns >= 12`, the expression matches first and routes to `human_handoff` with no LLM call.
* Otherwise one routing call classifies the reply into `billing`, `tech_support`, or `sales`. Intent edges can still extract `parameters` into context, exactly like normal intent routing.
* If the request is unclear, the catch-all routes to `clarify`, which asks the caller to say what they need.

## Example: pre-conversation dispatch

A router can be the start node. On the first turn it resolves before any conversational node runs, so the caller begins on the right node. Pre-conversation routing is deterministic (there is no reply to classify yet), so use expression and unconditional edges here.

```json theme={"system"}
{
  "current_node_id": "entry_dispatch",
  "nodes": [
    {
      "id": "entry_dispatch",
      "node_type": "router",
      "edges": [
        {
          "to_node_id": "hindi_greeting",
          "condition_type": "expression",
          "expression": {
            "conditions": [
              { "variable": "recipient_data.language", "operator": "eq", "value": "hi" }
            ]
          }
        },
        { "to_node_id": "greeting", "condition_type": "unconditional" }
      ]
    },
    { "id": "hindi_greeting", "prompt": "Greet the caller warmly in Hindi and ask how you can help.", "edges": [] },
    { "id": "greeting", "prompt": "Greet the caller warmly and ask how you can help.", "edges": [] }
  ]
}
```

Both target nodes are included so this validates and runs as-is — a router's edges must point to nodes that exist.

<Note>
  A router keys on call-time data. Pass it as `user_data` when you [start the call](/docs/api-reference/calls/make) — e.g. `{ "user_data": { "customer_tier": "vip", "language": "hi" } }` — and reference it in expressions as `recipient_data.customer_tier`, `recipient_data.language`, and so on. A value set in the agent's `context_data` acts only as a default; on a real call the call-time `user_data` is what's used.
</Note>

## Validation

A router node config is checked when the agent is saved. It is rejected if:

* It sets a `prompt` or `static_message` (a router never speaks).
* It has no unconditional catch-all edge (a router must always be able to advance).
* Any edge is an event edge (a call never rests on a router, so events would never fire).
* An edge points to a node ID that doesn't exist.
* Routers form a cycle among themselves with no way out to a speaking node.

## When to use a router node

* **Silent NLU dispatcher** — classify a request once and route to the right sub-flow, without a node that speaks.
* **Pre-conversation dispatch** — pick the starting node from caller data before the first turn.
* **Nested deterministic branching** — keep complex rule-based routing in one place instead of copying edges across conversational nodes.

If a routing decision needs the node to also say something, use a normal LLM node with intent edges instead — routing already happens before that node speaks.
