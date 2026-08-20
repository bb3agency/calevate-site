> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Bolna Voice AI Agent APIs Overview

> Explore Bolna Voice AI Agent APIs overview, featuring endpoints for creating, managing, and executing autonomous voice agents.

## Endpoints

```
POST /v2/agent
GET /v2/agent
PUT /v2/agent/:agent_id
GET /v2/agent/all
```

## Agent Object Attributes

### `agent_config`

* `agent_name`  *string* **(required)**<br />
  Name of the agent

* `agent_welcome_message`  *string* **(required)**<br />
  Initial agent welcome message. you can pass dynamic values here using variables encloed within `{}`

* `webhook_url`  *string* **(required)**<br />
  Get real-time details of the call progress and call data on a webhook. All supported events are listed in [Poll call data using webhooks](/docs/guides/post-call/polling-call-status-webhooks)

* `tasks` *array* **(required)**<br />
  Definitions and configuration for the agentic tasks

### `agent_prompts` <br />

Prompts to be provided to the agent.
