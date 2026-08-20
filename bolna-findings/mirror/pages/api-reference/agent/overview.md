> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Bolna Voice AI Agent APIs Overview (deprecated)

> Explore Bolna Voice AI Agent APIs overview, featuring endpoints for creating, managing, and executing autonomous voice agents.

<Warning>
  These APIs have now been deprecated.

  Please use the latest [**v2 APIs**](/docs/api-reference/agent/v2/overview).
</Warning>

## Endpoints

```
POST /agent
GET /agent
PUT /agent/:agent_id
PATCH /agent/:agent_id
GET /agent/all
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
