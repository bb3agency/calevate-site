> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Types of Bolna Agents

> An overview of the different agent architectures available in Bolna: conversation agents, graph agents, and IVR agents.

Bolna supports three distinct agent architectures. Each is a different way of structuring the conversation logic inside an agent.

***

## Conversation Agent

A conversation agent follows a single system prompt for the entire call. The LLM reads the prompt and the conversation history, then decides what to say next.

This is the default agent type. Most agents you create in the Bolna dashboard are conversation agents.

**Structure:**

```
Caller → Transcriber → LLM (with system prompt) → Synthesizer → Caller
```

**Characteristics:**

* Single prompt drives the entire conversation
* LLM maintains context across turns automatically
* Supports tools (function calls, knowledge base lookups, call transfers)
* Behavior is shaped by the prompt and the LLM's reasoning

See [Build & Configure Agents](/docs/agent-setup/overview) to configure a conversation agent.

***

## Graph Agent

A graph agent structures the conversation as a directed graph of nodes, where each node represents a distinct conversation state with its own prompt, tools, and routing logic.

The agent transitions between nodes based on conditions you define — for example, moving from a "greeting" node to a "qualification" node when the caller confirms their name.

**Structure:**

```
Node A (prompt A, tools A) → [condition met] → Node B (prompt B, tools B) → ...
```

**Characteristics:**

* Each node has its own system prompt and tool set
* Transitions are rule-based (explicit conditions) or LLM-decided
* Well-suited for multi-stage flows where behavior changes significantly between phases
* Supports typed variables that carry data between nodes
* Supports a global knowledge base accessible to all nodes

See [Graph Agents](/docs/graph-agent/introduction) for configuration details.

***

## IVR Agent

An IVR (Interactive Voice Response) agent uses DTMF (touch-tone) input rather than voice transcription. The caller presses keys on their phone (1 for sales, 2 for support) and the agent routes accordingly.

**Structure:**

```
Caller presses key → IVR routing logic → Play audio / transfer / end call
```

**Characteristics:**

* Triggered by key presses, not speech
* Does not use an LLM for the IVR routing layer
* Often combined with conversation agents as transfer targets
* Lower latency than speech-based agents for simple menus

See [IVR Inbound Calls](/docs/guides/inbound/ivr-inbound-calls) for configuration details.

***

## Agent Scope

Regardless of type, every Bolna agent is scoped to a set of **tasks**. A task bundles together:

* A `task_type` (e.g. `conversation`, `extraction`)
* A `toolchain` (transcriber → LLM → synthesizer pipeline)
* A `tools_config` (provider selection and settings)
* A `task_config` (timeout, silence handling)

Most agents have a single `conversation` task. Post-call extraction runs as a separate task after the call ends.

See the [Create Agent API](/docs/api-reference/agent/v2/create) for the full agent schema.
