> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Import & Export

> Export your graph agent as JSON for backup or sharing, and import JSON to replace the current graph.

The editor can export any agent to a JSON file and import a JSON file to replace an agent's current graph. Use this to back up agents, share them with teammates, migrate agents between environments, or create templates.

***

## Exporting an agent

1. Click **Export** in the toolbar.
2. The export dialog opens with the agent JSON in a read-only text area.
3. Click **Copy JSON** to copy the JSON to your clipboard, or **Download .json** to save it as a `.json` file.

The downloaded file is named after the agent (e.g. `my-graph-agent.json`).

<Tip>
  Export before making large structural changes. If you need to roll back, you can re-import the exported file. For automatic snapshots, use [Version history](/docs/graph-agent/version-history) instead.
</Tip>

***

## Importing an agent

<Warning>
  Importing replaces the **entire current graph** with the imported JSON. The current graph is discarded. Export or save a version before importing if you want to keep the current state.
</Warning>

1. Click **Import** in the toolbar.
2. The import dialog opens with two options:

**Paste JSON:**
Click the **Paste JSON** tab, paste your agent JSON into the text area, and click **Import**.

**Upload a file:**
Click the **Upload file** tab, drag a `.json` file onto the dropzone or click to browse, and click **Import**.

3. The editor validates the JSON format. If it's valid, the canvas reloads with the imported graph. If not, an error message describes the problem.

***

## What's included in the export

The exported JSON is the complete agent payload — the same structure you'd send to the [Agents API](/docs/api-reference/agent/create). It includes:

* Agent name and configuration
* All nodes and their prompts, settings, and overrides
* All transitions with conditions and expressions
* Conversation settings (hangup, backchanneling, etc.)
* LLM, STT, and TTS configuration
* API tools configuration
* Input and output schemas

Variable values set in the Variables panel are **not** included in the export. They are local to your browser session.

***

## Use cases

**Backup before a risky change**
Export → make changes → if something breaks, import the backup.

**Share with a teammate**
Export → send the JSON file → teammate imports into their agent.

**Move between environments**
Export from staging → import into production (update environment-specific URLs in API tools first).

**Create a template library**
Build a well-designed graph for a use case, export it, store it in your team's shared drive. Anyone who needs a similar agent imports the template and customises it.
