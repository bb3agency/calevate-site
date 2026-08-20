> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Installation

> Install Bolna Skills for your AI coding assistant.

Install Bolna Skills in your project with a single command:

```bash theme={"system"}
npx skills add bolna-ai/skills
```

This detects any Agent Skills-compatible assistants configured in your project and installs all 19 skills for each of them.

## Install for a specific assistant

<Tabs>
  <Tab title="Claude Code">
    ```bash theme={"system"}
    npx skills add bolna-ai/skills -a claude-code
    ```
  </Tab>

  <Tab title="Cursor">
    ```bash theme={"system"}
    npx skills add bolna-ai/skills -a cursor
    ```
  </Tab>

  <Tab title="Codex">
    ```bash theme={"system"}
    npx skills add bolna-ai/skills -a codex
    ```
  </Tab>
</Tabs>

See [Supported AI Assistants](/docs/build-with-ai/supported-assistants) for the full list of compatible tools beyond these three.

## Install a single skill

If you only need one capability, install it by name instead of the full set:

```bash theme={"system"}
npx skills add bolna-ai/skills --skill create-agent
```

Browse every skill name in the [Skills Reference](/docs/build-with-ai/skills-reference).

## Next step

Once installed, connect your API key in [Setup](/docs/build-with-ai/setup) so your assistant can actually call the Bolna API.
