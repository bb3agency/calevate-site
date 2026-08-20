> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Edges & Routing

> Edge types, expression operators, built-in variables, and how routing decisions are made on every turn.

Every node has a list of `edges`. After each customer message, the framework picks the next node by checking deterministic edges first (instant, free), then handing off to the routing LLM if nothing deterministic matches.

***

## Edge fields

| Field                  | Description                                                                                                                            |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `to_node_id`           | Target node id. Required.                                                                                                              |
| `condition`            | Human-readable description of when to transition. Used as the routing LLM's tool description.                                          |
| `condition_type`       | One of `"llm"` (default if unset), `"expression"`, `"unconditional"`, `"event"`.                                                       |
| `expression`           | Required when `condition_type == "expression"`. See [Expression edges](#expression-edges).                                             |
| `event_name`           | Required when `condition_type == "event"`. The external event name to listen for. See [Event injection](/docs/graph-agent/event-injection). |
| `function_name`        | Override the auto-generated routing tool name (default: `transition_to_<to_node_id>`).                                                 |
| `function_description` | Override the auto-generated routing tool description.                                                                                  |
| `parameters`           | Map of `{name: type}` to extract from the user's input during the transition. See [Inline data extraction](#inline-data-extraction).   |
| `priority`             | Lower fires first. Defaults: expression / unconditional / event = `0`, llm = `100`.                                                    |

***

## Edge types

| `condition_type`   | How it works                                                                               | When to use                                                                                                                       |
| ------------------ | ------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| Not set or `"llm"` | Routing LLM evaluates `condition` against the customer's reply.                            | When the decision requires understanding intent.                                                                                  |
| `"expression"`     | Rule-based check on context variables. Fires instantly if matched.                         | Time of day, retry counts, language detection, any data-driven decision.                                                          |
| `"unconditional"`  | Always takes this edge. No check.                                                          | When there is only one possible next step.                                                                                        |
| `"event"`          | Fires only when a matching external event arrives via REST. Ignored during speech routing. | When an external system (payment, form, link click) drives the conversation. See [Event injection](/docs/graph-agent/event-injection). |

Expression and unconditional edges are checked together (in `priority` order, ascending) **before** any LLM call is made.

To put routing in its own node instead of on a conversational node's edges — a silent classifier or a pre-conversation dispatcher — use a [router node](/docs/graph-agent/router-nodes).

***

## Expression edges

```json theme={"system"}
{
  "to_node_id": "after_hours",
  "condition": "Outside working hours",
  "condition_type": "expression",
  "expression": {
    "logic": "or",
    "conditions": [
      { "variable": "recipient_data.current_hour", "operator": "lt",  "value": 10 },
      { "variable": "recipient_data.current_hour", "operator": "gte", "value": 18 }
    ]
  }
}
```

Use `"logic": "and"` when all conditions must be true. Use `"logic": "or"` when any one is enough.

### Operators

<CardGroup cols={2}>
  <Card title="Equality" icon="equals">
    `eq`, `neq`
  </Card>

  <Card title="Numbers" icon="hashtag">
    `gt`, `gte`, `lt`, `lte`
  </Card>

  <Card title="Text" icon="font">
    `contains`
  </Card>

  <Card title="Lists" icon="list">
    `in`, `not_in`
  </Card>

  <Card title="Existence" icon="circle-check">
    `exists`, `not_exists`
  </Card>
</CardGroup>

### Priority

Lower priority fires first. Defaults if not set: deterministic edges (expression, unconditional, event) get priority `0`; LLM edges get priority `100`. Within the deterministic bucket, the **first** matching edge wins. For mutually-exclusive rules (e.g. working-hours vs after-hours), set distinct priorities to make ordering explicit.

***

## Built-in variables

These variables are populated automatically and can be referenced in any expression.

| Variable                         | Type       | Notes                                                                                                                                                                        |
| -------------------------------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `recipient_data.current_hour`    | int (0-23) | Hour in the call's timezone.                                                                                                                                                 |
| `recipient_data.current_minute`  | int (0-59) |                                                                                                                                                                              |
| `recipient_data.current_weekday` | string     | Lowercase, e.g. `"wednesday"`.                                                                                                                                               |
| `recipient_data.current_day`     | int (1-31) |                                                                                                                                                                              |
| `recipient_data.current_month`   | int (1-12) |                                                                                                                                                                              |
| `recipient_data.current_year`    | int        |                                                                                                                                                                              |
| `recipient_data.current_date`    | string     | Display string for prompts only, not for comparisons.                                                                                                                        |
| `recipient_data.current_time`    | string     | Display string for prompts only.                                                                                                                                             |
| `recipient_data.timezone`        | string     | e.g. `"Asia/Kolkata"`.                                                                                                                                                       |
| `recipient_data.user_number`     | string     | E.164 phone number.                                                                                                                                                          |
| `detected_language`              | string     | Top-level, not under `recipient_data`. e.g. `"hindi"`, `"en"`.                                                                                                               |
| `_node_turns`                    | int        | User messages on the **current** node. Resets on every transition.                                                                                                           |
| `_total_turns`                   | int        | User messages in the entire call.                                                                                                                                            |
| `_silence_repeats`               | int        | Times the current node has replayed because the user stayed silent past `repeat_after_silence_seconds`. Resets on transition. See [Static nodes](/docs/graph-agent/static-nodes). |

<Warning>
  Time variables (`current_hour`, `current_weekday`, etc.) are populated **only when `recipient_data.timezone` is set on the call**. Without a timezone, time-based expressions silently never match. Always set `timezone` when creating a call that uses time-based routing.
</Warning>

***

## Typed variables

Values used in expressions often arrive as strings (event properties, extracted `parameters`, dynamic `context_data`). So `"18"` would not match `18`, and `"false"` would not be treated as a boolean. Declare the variable's type and both sides of the comparison are converted before matching.

Add a `variable_types` map at the top level of the graph config. Each key is the variable path, written **exactly** as it appears in the condition (including dot-notation):

```json theme={"system"}
{
  "variable_types": {
    "recipient_data.age": "number",
    "recipient_data.hold_status": "boolean",
    "plan_tier": "string"
  }
}
```

| Type      | Matches                                                           |
| --------- | ----------------------------------------------------------------- |
| `number`  | Any number or numeric string, e.g. `18` or `"18"`.                |
| `boolean` | `true` / `1` / `yes` and `false` / `0` / `no` (case-insensitive). |
| `string`  | Compared as text.                                                 |

```json theme={"system"}
{
  "to_node_id": "premium_flow",
  "condition_type": "expression",
  "expression": {
    "conditions": [
      { "variable": "recipient_data.age", "operator": "gte", "value": 18 },
      { "variable": "recipient_data.hold_status", "operator": "eq", "value": true }
    ]
  }
}
```

Declare a type whenever a value can arrive as a string. If you leave a variable out, the framework guesses based on the values, which is fine for plain numbers but unreliable for booleans.

***

## Common patterns

**Working hours (10 AM to 6 PM)**

```json theme={"system"}
{
  "to_node_id": "transfer_call",
  "condition": "Working hours",
  "condition_type": "expression",
  "priority": 0,
  "expression": {
    "logic": "and",
    "conditions": [
      { "variable": "recipient_data.current_hour", "operator": "gte", "value": 10 },
      { "variable": "recipient_data.current_hour", "operator": "lt",  "value": 18 }
    ]
  }
}
```

**Auto-escalate after too many retries**

```json theme={"system"}
{
  "to_node_id": "transfer_call",
  "condition": "Too many retries on this node",
  "condition_type": "expression",
  "expression": {
    "conditions": [
      { "variable": "_node_turns", "operator": "gte", "value": 2 }
    ]
  }
}
```

***

## Inline data extraction

Edges can capture typed values from the user's reply during routing. The routing LLM treats them as required parameters; on a successful transition the values are merged into `context_data` and become available everywhere.

```json theme={"system"}
{
  "to_node_id": "confirm_order",
  "condition": "Customer provided their order id",
  "parameters": {
    "order_id": "string"
  }
}
```

After the transition, `context_data["order_id"]` is set and you can:

* Reference it in node prompts via `{order_id}`.
* Use it in downstream expression edges: `{ "variable": "order_id", "operator": "exists" }`.
* Pass it to API tools as `%(order_id)s`.

<Tip>
  Prefer `parameters` over a separate "extract" node. One LLM call routes **and** captures data.
</Tip>

***

## Routing instructions

The `routing_instructions` field is prepended to every routing request. Keep it short and directive:

```
You are the Routing System for this conversation. Analyze the user's input
and the available edges. Select the edge whose condition best matches.
If no edge matches, stay on the current node.
```

You can include `{variable}` placeholders. They are substituted from `context_data` (and the flattened `recipient_data`) at runtime. Missing keys render as `NULL`.
