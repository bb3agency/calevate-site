> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Tools & Knowledge Base

> Wire up call transfer, custom API tools, node-scoped tools, ending the call, and global or per-node knowledge bases inside a graph agent.

Graph agents support two kinds of tools (call transfer and custom HTTP) and an optional knowledge base (RAG). Tools are defined globally in `api_tools` and referenced by name in node prompts. A knowledge base can be set once for the whole agent, or per node when different steps need different sources.

***

## Call transfer

Define the transfer tool once in `api_tools.tools` and `api_tools.tools_params`:

```json theme={"system"}
{
  "key": "transfer_call",
  "name": "transfer_call_main",
  "description": "Use when the customer requests a human agent.",
  "pre_call_message": "Transferring you now, please hold..."
}
```

```json theme={"system"}
{
  "tools_params": {
    "transfer_call_main": {
      "url": null,
      "param": {
        "call_sid": "%(call_sid)s",
        "call_transfer_number": "+91XXXXXXXXXX"
      },
      "method": "POST"
    }
  }
}
```

On the transfer node, set `function_call` to force the response LLM to pick this tool when the node is entered:

```json theme={"system"}
{
  "id": "transfer",
  "prompt": "Transfer the call to a human agent.",
  "function_call": "transfer_call_main",
  "edges": []
}
```

`function_call` sets the response LLM's `tool_choice` to the named tool. The LLM still emits the call; the framework doesn't auto-invoke it.

***

## Custom API tools

Define a tool the LLM can call mid-conversation, e.g. to look up an order:

```json theme={"system"}
{
  "key": "custom_task",
  "name": "fetch_order_status",
  "description": "Fetch order status using the customer's order ID.",
  "parameters": {
    "type": "object",
    "properties": {
      "order_id": { "type": "string", "description": "Customer order ID" }
    }
  },
  "pre_call_message": "Just a moment, let me check that..."
}
```

```json theme={"system"}
{
  "tools_params": {
    "fetch_order_status": {
      "url": "https://your-api.example.com/order/status",
      "param": { "order_id": "%(order_id)s" },
      "method": "POST",
      "headers": { "Authorization": "Bearer YOUR_TOKEN" }
    }
  }
}
```

Reference the tool from a node prompt with the `@` prefix:

```
Call @fetch_order_status with the [order_id] collected earlier.
```

<Warning>
  Only define tools you actually use. Every tool is visible to the LLM as a callable function, and unused tools increase the chance of accidental invocations.
</Warning>

***

## Limiting a tool to specific nodes

By default every tool is visible to the LLM on every node. To expose a tool only where it makes sense, add `scope: "node"` and a `nodes` list to its entry in `tools_params`:

```json theme={"system"}
{
  "tools_params": {
    "fetch_order_status": {
      "url": "https://your-api.example.com/order/status",
      "param": { "order_id": "%(order_id)s" },
      "method": "POST",
      "scope": "node",
      "nodes": ["collect_order", "confirm_order"]
    }
  }
}
```

Now the LLM can only call `fetch_order_status` while the conversation is on `collect_order` or `confirm_order`. On every other node the tool is hidden, so it can't be triggered by accident. Tools with no `scope` (or `scope: "global"`) stay available everywhere.

<Tip>
  Scope each tool to the nodes that need it. Fewer visible tools per node means fewer wrong tool calls and a cheaper, more focused LLM call.
</Tip>

***

## Ending the call

Graph agents can hang up using the built-in `end_call` tool. To let a node end the call, set `function_call: "end_call"` on that node and set `hangup_after_LLMCall: false` in the task config:

```json theme={"system"}
{
  "id": "closing",
  "prompt": "Thank the customer and end the call.",
  "function_call": "end_call",
  "edges": []
}
```

With `hangup_after_LLMCall: false`, the call only ends from the nodes that opt in with `function_call: "end_call"`. This gives you exact control over where a call is allowed to hang up. Leave `hangup_after_LLMCall: true` (the default) if you instead want the agent to decide when to end the call on its own.

***

## Knowledge base

Attach a knowledge base so the agent can answer from your documents. On each turn the latest user message retrieves the most relevant chunks, which are added to the prompt before the response is generated.

### Global knowledge base

Set `rag_config` at the top level of the graph config and every node uses it:

```json theme={"system"}
{
  "agent_type": "graph_agent",
  "agent_information": "...",
  "current_node_id": "welcome",
  "rag_config": {
    "vector_store": {
      "provider_config": { "vector_id": "policies_v1" }
    },
    "similarity_top_k": 10
  },
  "nodes": [ ... ]
}
```

### Per-node knowledge base

Set `rag_config` on a node to use a different source on that node. A node's own `rag_config` takes precedence; nodes without one fall back to the global `rag_config`.

```json theme={"system"}
{
  "id": "policy_questions",
  "prompt": "Answer the customer's policy question using the knowledge base.",
  "rag_config": {
    "vector_store": {
      "provider_config": { "vector_id": "policies_v1" }
    },
    "similarity_top_k": 10
  },
  "edges": [
    { "to_node_id": "closing", "condition": "Customer is satisfied" }
  ]
}
```

### Multiple collections

Pass `vector_ids` instead of `vector_id` to search several collections at once:

```json theme={"system"}
"rag_config": {
  "vector_store": {
    "provider_config": { "vector_ids": ["policies_v1", "faqs_v2"] }
  },
  "similarity_top_k": 10
}
```

| Field                                     | Description                                             |
| ----------------------------------------- | ------------------------------------------------------- |
| `vector_store.provider_config.vector_id`  | A single knowledge base collection id.                  |
| `vector_store.provider_config.vector_ids` | A list of collection ids to search together.            |
| `similarity_top_k`                        | How many chunks to retrieve per turn. Defaults to `10`. |

<Note>
  If retrieval fails, the node still responds, just without retrieved context. The error is logged but never raised to the caller.
</Note>

<Tip>
  Use a global `rag_config` when the whole agent answers from one knowledge base. Add a per-node `rag_config` only where a step needs a different source. Every retrieval adds latency, so a node that needs no knowledge base shouldn't pay for one.
</Tip>
