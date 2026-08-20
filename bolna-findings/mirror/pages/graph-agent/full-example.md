> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Full Example

> Complete annotated graph agent config showing every feature: nodes, edges, expression routing, static nodes, event injection, and call transfer.

This is the complete shape of a graph agent. It demonstrates every feature documented in the rest of this section. Replace `PLACEHOLDER` values with real config before deploying.

The flow:

* `welcome`: greets the customer. Transfers during working hours, ends the call after-hours, or jumps straight to `payment_confirmed` if a payment event arrives.
* `collect_order`: collects an order id with silence handling and a per-node knowledge base.
* `payment_confirmed`: static confirmation message played from cache.
* `transfer_call`: routes the call to a human agent via the transfer tool.
* `closing`: static goodbye.

```json theme={"system"}
{
  "agent_config": {
    "agent_name": "Demo Graph Agent",
    "agent_type": "other",
    "agent_welcome_message": "Hello, my name is Neha.",
    "tasks": [
      {
        "task_type": "conversation",
        "toolchain": {
          "execution": "parallel",
          "pipelines": [["transcriber", "llm", "synthesizer"]]
        },
        "task_config": {
          "optimize_latency": true,
          "call_terminate": 600,
          "hangup_after_LLMCall": true
        },
        "tools_config": {
          "input":  { "format": "wav", "provider": "plivo" },
          "output": { "format": "wav", "provider": "plivo" },
          "api_tools": {
            "tools": [
              {
                "key": "transfer_call",
                "name": "transfer_call_main",
                "parameters": {
                  "type": "object",
                  "required": ["call_sid"],
                  "properties": {
                    "call_sid": { "type": "string", "description": "unique call id" }
                  }
                },
                "description": "Transfer call to human agent.",
                "pre_call_message": "Please hold while I transfer your call..."
              }
            ],
            "tools_params": {
              "transfer_call_main": {
                "url": null,
                "param": {
                  "call_sid": "%(call_sid)s",
                  "call_transfer_number": "+91XXXXXXXXXX"
                },
                "method": "POST",
                "headers": {},
                "scope": "node",
                "nodes": ["transfer_call"]
              }
            }
          },
          "llm_agent": {
            "agent_type": "graph_agent",
            "agent_flow_type": "streaming",
            "llm_config": {
              "model": "gpt-4.1-mini",
              "max_tokens": 200,
              "temperature": 0.2,
              "provider": "openai",

              "routing_model": "gpt-4.1-mini",
              "routing_max_tokens": 250,
              "routing_instructions": "PLACEHOLDER: routing instructions",

              "agent_information": "PLACEHOLDER: global agent prompt (persona, language, guardrails)",
              "current_node_id": "welcome",
              "variable_types": {
                "recipient_data.current_hour": "number"
              },
              "nodes": [
                {
                  "id": "welcome",
                  "prompt": "Greet the customer and identify their intent.",
                  "edges": [
                    {
                      "to_node_id": "collect_order",
                      "condition": "Customer wants order status",
                      "parameters": { "order_id": "string" }
                    },
                    {
                      "to_node_id": "transfer_call",
                      "condition": "Customer asks for a human",
                      "condition_type": "expression",
                      "expression": {
                        "logic": "and",
                        "conditions": [
                          { "variable": "recipient_data.current_hour", "operator": "gte", "value": 10 },
                          { "variable": "recipient_data.current_hour", "operator": "lt",  "value": 18 }
                        ]
                      }
                    },
                    {
                      "to_node_id": "closing",
                      "condition": "Outside working hours",
                      "condition_type": "expression",
                      "priority": 1,
                      "expression": {
                        "logic": "or",
                        "conditions": [
                          { "variable": "recipient_data.current_hour", "operator": "lt",  "value": 10 },
                          { "variable": "recipient_data.current_hour", "operator": "gte", "value": 18 }
                        ]
                      }
                    },
                    {
                      "to_node_id": "payment_confirmed",
                      "condition_type": "event",
                      "event_name": "payment_completed"
                    }
                  ]
                },
                {
                  "id": "collect_order",
                  "prompt": "Confirm the order id and look up its status using @fetch_order_status.",
                  "repeat_after_silence_seconds": 10,
                  "rag_config": {
                    "vector_store": {
                      "provider_config": { "vector_id": "PLACEHOLDER_collection_id" }
                    },
                    "similarity_top_k": 8
                  },
                  "edges": [
                    { "to_node_id": "closing", "condition": "Status delivered to customer" },
                    {
                      "to_node_id": "transfer_call",
                      "condition_type": "expression",
                      "expression": {
                        "conditions": [
                          { "variable": "_silence_repeats", "operator": "gte", "value": 3 }
                        ]
                      }
                    }
                  ]
                },
                {
                  "id": "payment_confirmed",
                  "node_type": "static",
                  "static_message": "Your payment is confirmed. Thank you!",
                  "edges": [
                    { "to_node_id": "closing", "condition_type": "unconditional" }
                  ]
                },
                {
                  "id": "transfer_call",
                  "prompt": "Transfer the call to a human agent.",
                  "function_call": "transfer_call_main",
                  "edges": []
                },
                {
                  "id": "closing",
                  "node_type": "static",
                  "static_message": "Thank you for calling. Have a wonderful day. Goodbye!",
                  "edges": []
                }
              ]
            }
          },
          "transcriber": {
            "model": "nova-3",
            "language": "multi-hi",
            "provider": "deepgram",
            "stream": true,
            "encoding": "linear16",
            "sampling_rate": 16000,
            "endpointing": 700
          },
          "synthesizer": {
            "provider": "elevenlabs",
            "stream": true,
            "caching": true,
            "buffer_size": 220,
            "audio_format": "wav",
            "provider_config": {
              "model": "eleven_turbo_v2_5",
              "voice": "PLACEHOLDER: voice name",
              "voice_id": "PLACEHOLDER: voice ID",
              "temperature": 0.2,
              "similarity_boost": 0.6,
              "speed": 0.9
            }
          }
        }
      }
    ]
  }
}
```

<Tip>
  For automatic post-call extraction (disposition, sentiment, funnel stage), add an `extraction` task alongside the conversation task. See [Using extractions](/docs/guides/prompting/using-extractions).
</Tip>

## What this example shows

| Feature                                 | Where                                                                                                |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| Mixed edge types on one node            | `welcome` has LLM, expression, and event edges.                                                      |
| Inline data extraction via `parameters` | `welcome -> collect_order` captures `order_id`.                                                      |
| Working-hours routing                   | `welcome -> transfer_call` (expression).                                                             |
| After-hours fallback                    | `welcome -> closing` (expression, priority 1).                                                       |
| Event-driven proactive speech           | `welcome -> payment_confirmed` on `payment_completed`.                                               |
| Typed expression variables              | `variable_types` types `recipient_data.current_hour` as a number.                                    |
| Per-node RAG                            | `collect_order` has `rag_config`.                                                                    |
| Silence handling and escalation         | `collect_order` has `repeat_after_silence_seconds: 10` and an expression edge on `_silence_repeats`. |
| Static node                             | `payment_confirmed`, `closing`.                                                                      |
| Call transfer                           | `transfer_call` with `function_call`.                                                                |
| Node-scoped tool                        | `transfer_call_main` is scoped to the `transfer_call` node via `scope` and `nodes`.                  |
