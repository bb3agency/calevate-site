> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Debugging Graph Agents

> Read the routing logs, understand what the routing LLM saw, and fix the most common misbehaviour patterns.

The fastest way to diagnose a misbehaving graph agent is to read the routing logs. On every customer turn the framework logs the routing decision, the confidence, and the reason. This page walks through the log format and the patterns you'll see most often.

***

## What you'll see in the logs

Every customer turn produces one routing log line. Two formats, depending on whether the routing LLM ran or a deterministic rule fired first.

**LLM-routed turn:**

```
Routing decision (LLM): transition_to_offer_pitch | confidence: 0.95 |
reasoning: Customer confirmed identity by saying 'yeah'. (latency: 210.4ms)
```

**Deterministic turn (expression or unconditional edge):**

```
Routing decision (deterministic): -> after_hours |
deterministic:expression:Outside working hours (latency: 0.6ms)
```

| Field                             | What it tells you                                                                                      |
| --------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `LLM` vs `deterministic`          | Whether the routing LLM made the call, or an expression / unconditional rule fired first.              |
| `transition_to_<id>` or `-> <id>` | The target node the routing picked.                                                                    |
| `confidence` (LLM only)           | How certain the LLM was. Close to `1.0` means a clear match. Below `0.6` suggests ambiguous edges.     |
| `reasoning`                       | Why this transition was chosen. The single most useful field for debugging wrong transitions.          |
| `latency`                         | How long routing took. Deterministic edges are sub-millisecond; LLM routing is typically 150 to 300ms. |

When the routing LLM picks `stay_on_current_node`, the agent **still produces a response** on the current node. It does not stay silent.

***

## Common scenarios

### Agent keeps re-asking instead of moving forward

The routing LLM is returning `stay_on_current_node`. Read the `reasoning` value in the routing log: it almost always explains what it thought was missing.

Common causes:

* The edge condition is too strict, or uses vocabulary the LLM wouldn't associate with what the customer said.
* The customer's input genuinely doesn't match any condition. Add a broader fallback edge.
* The edge has `parameters` and the customer hasn't provided one of the required values yet.

### Agent routes to the wrong node

Two edge conditions are overlapping. The routing LLM is matching the wrong one. Check the `reasoning` value in the routing log to see which condition it picked and why, then rewrite the conditions to be more specific and mutually exclusive.

### Confidence is consistently low

Edge conditions are ambiguous or too similar to each other. Rewrite them, or add expression edges for the deterministic cases (working hours, retry counts, language) so the LLM has fewer overlapping options.

### Agent skips a node unexpectedly

An expression edge fired before the LLM got a chance. Check whether any expression edges on the previous node have overly broad conditions. For example `_node_turns gte 1` would always fire on the second turn regardless of what the customer said.

### Time-based expression never fires

`recipient_data.timezone` was not set on the call. Without it, `current_hour`, `current_weekday`, etc. are never populated and every time-based comparison silently returns `False`. Always set `timezone` when creating a call that uses time-based routing.

### Agent forgets earlier context on long calls

The response LLM only sees the most recent 50 messages of conversation history. For most calls this is fine, but on very long flows the agent can lose earlier turns. Persist important state into `context_data` (extracted via edge `parameters` or pushed via event properties) instead of relying on the LLM seeing it in the transcript.

### Static node plays the wrong text or wrong voice

The cache was built from an earlier version of the config. Re-save the agent so the cache regenerates from the current `static_message` and TTS voice settings.

### Event fires but the agent stays silent

Most likely causes, in rough order:

1. The call had already ended when the event arrived. Check that you got `202 Accepted`, not `404`.
2. The event name doesn't match any edge on the **current** node. Event edges only fire on the active node. Check the most recent `Routing decision` log line to see where the call actually was when the event landed.
3. The user was speaking when the event resolved. The node still transitioned, but proactive generation was deliberately skipped. The next user turn will route on the new node naturally.
4. There's no event edge for that name anywhere on the node. Add one or rename the event to match an existing edge.
