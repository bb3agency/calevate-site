> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Example: Call Monitoring Dashboard

> Use the Bolna MCP server to explore your account, then have your AI assistant build a small local dashboard around it.

The MCP server is best used two ways in the same session: **interactively**, to explore your account from chat, and as a **spec source**, to hand your assistant real field names and response shapes when it writes code. This walkthrough builds a small local dashboard — one page showing your agents, wallet balance, and recent call outcomes — that talks to the real Bolna API directly, so it keeps working with no MCP connection required at runtime.

<Warning>
  This walkthrough needs an agent that can write and run files — **Claude Code**, **Cursor**, **Windsurf**, or **Codex CLI**. A chat-only client like Claude Desktop can do everything in the [Prompt Cheatsheet](/docs/build-with-ai/mcp-prompts), but can't carry out the codegen steps below.
</Warning>

<Note>
  The shipped dashboard calls `api.bolna.ai` with your `BOLNA_API_KEY` directly, from a small local server — it doesn't depend on the MCP server. MCP is the tool you and your assistant use *while building it*.
</Note>

### Prerequisites

* A Bolna account with at least one agent that has placed calls
* A coding-capable agent (Claude Code, Cursor, Windsurf, or Codex CLI) with the [Bolna MCP server connected](/docs/build-with-ai/mcp-quickstart)
* Node.js 18+

<Steps>
  <Step title="Explore your data through MCP">
    Ask your assistant, connected via MCP:

    ```
    Which of my agents have gotten calls in the last week?
    ```

    This chains `list_agents` → `list_agent_executions` behind the scenes, so you can see real agent IDs and call volume before writing a line of code.
  </Step>

  <Step title="Scaffold the dashboard">
    Now ask it to build the app — talk to it the way you'd brief a teammate, not a spec doc:

    ```
    Build me a simple local dashboard for my Bolna account: my agents,
    my wallet balance, and recent calls for whichever agent I pick.
    Use the real Bolna API, not the MCP server, and keep my API key on
    the server — never send it to the browser.
    ```

    It should land on something like an Express backend proxying `api.bolna.ai`, with a static frontend that only talks to your own server. Expect a route close to this for the calls list:

    ```js theme={"system"}
    app.get("/api/calls/:agentId", async (req, res) => {
      const to = new Date().toISOString();
      const from = new Date(Date.now() - 7 * 86400_000).toISOString();
      const bolnaRes = await fetch(
        `https://api.bolna.ai/v2/agent/${req.params.agentId}/executions?from=${from}&to=${to}`,
        { headers: { Authorization: `Bearer ${process.env.BOLNA_API_KEY}` } }
      );
      const { data } = await bolnaRes.json();
      res.json(data.map(({ id, status, conversation_duration, created_at }) => (
        { id, status, conversation_duration, created_at }
      )));
    });
    ```

    If it puts the key in frontend code or skips a field you need, just say so — that's a normal follow-up, not a failure.
  </Step>

  <Step title="Debug a real failure">
    Pick a failed execution ID from the table and ask, back in the MCP-connected chat:

    ```
    Execution <execution_id> failed — what happened?
    ```

    Then fold the fix into the app:

    ```
    Highlight failed calls in red, and show the reason on hover.
    ```
  </Step>

  <Step title="Guard the wallet before a real call">
    ```
    Add a call button next to each agent, but block it if my wallet
    balance is under ₹100.
    ```

    This mirrors the `get_user_info` → `start_outbound_call` pattern from the [Prompt Cheatsheet](/docs/build-with-ai/mcp-prompts#chained-multi-step), now baked into the dashboard itself.
  </Step>
</Steps>

## What to build next

* **Webhook receiver** that pushes live call events into the dashboard instead of polling — see [Setup Webhooks](/docs/build-with-ai/skills-reference) via the `setup-webhook` Skill
* **Slack alert on low balance** using the same `/api/balance` route this dashboard already exposes
* **Batch-status view** for campaigns — `create_batch`, `schedule_batch`, and `list_batch_executions` cover the create/schedule/monitor side over MCP too now; see the `create-batch` Skill for the code-native equivalent

<CardGroup cols={2}>
  <Card title="Tool List" icon="table-list" href="/docs/build-with-ai/mcp-tool-list">
    Every field and endpoint this example calls
  </Card>

  <Card title="Prompt Cheatsheet" icon="clipboard-list" href="/docs/build-with-ai/mcp-prompts">
    More prompts to extend this dashboard
  </Card>
</CardGroup>
