> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz Agent Skills

> Install the Vobiz agent skills into Claude Code, Codex, and 40+ other coding agents with one command, so your AI assistant knows how to drive the Vobiz API, VobizXML, SIP trunking, and KYC flows without guessing.

The Vobiz docs ship a set of **agent skills** - focused instruction sets that teach a coding agent how to use one part of Vobiz correctly (the right endpoints, path casing, request shapes, VobizXML verbs, and the common pitfalls). Install them once and your agent stops guessing: it writes working `Make a Call` requests, valid `<Gather>` XML, and correct KYC flows straight away.

<Note>
  **Skills vs. the MCP server.** [Skills](/docs/resources/skills) are static know-how that lives in your agent's context - *how to use Vobiz*. The [MCP server](/docs/resources/mcp) is a live connection that *searches and fetches the docs* on demand. They're complementary: install the skills for reliable, offline-capable patterns, add the MCP server for always-current page lookups. Use both.
</Note>

## Install with one command

The skills are hosted on this docs site. The [`skills` CLI](https://www.npmjs.com/package/skills) installs them into whichever agents it detects on your machine:

```bash theme={null}
npx skills add https://vobiz.ai/docs
```

The CLI scans for installed agents (Claude Code, Codex, Cursor, and 40+ more), shows a checklist of which to install into and which skills to add, then writes each skill into that agent's skills directory. Re-run it any time to pull updates.

```text Skills source theme={null}
https://vobiz.ai/docs
```

* **What you get:** the Vobiz skill set listed [below](#the-vobiz-skill-set), one folder per skill.
* **What it is not:** skills are instructions, not credentials. You still authenticate every API call with your `X-Auth-ID` / `X-Auth-Token` - see the [API Reference](/docs/account).

## Prerequisites

* A supported coding agent installed (Claude Code, Codex, Cursor, etc.).
* **Node.js 18+** for `npx`. Run `node --version`; if it prints `v18` or higher, you're set.
* An internet connection - the skills are fetched from this docs site.

## Claude Code

Claude Code loads skills from `.claude/skills/` (per-project) or `~/.claude/skills/` (global).

<Steps>
  <Step title="Install the skills">
    From your project directory, install into Claude Code specifically:

    ```bash theme={null}
    npx skills add https://vobiz.ai/docs --agents claude-code
    ```

    Add `--global` to make them available in every project instead of just the current repo:

    ```bash theme={null}
    npx skills add https://vobiz.ai/docs --agents claude-code --global
    ```

    Omit `--agents` to let the CLI auto-detect and offer Claude Code (and anything else) in an interactive checklist.
  </Step>

  <Step title="Confirm they landed">
    ```bash theme={null}
    npx skills list
    ```

    You'll see the `vobiz-*` skills with the directory each was written to - `.claude/skills/` for a project install or `~/.claude/skills/` for a global one.
  </Step>

  <Step title="Use them in a session">
    Skills load automatically by relevance. Just ask for the task:

    > Write a curl that places an outbound Vobiz call and the minimal answer XML it should return.

    Claude Code pulls in the `vobiz-voice-calls` and `vobiz-voice-xml` skills and produces a request with the correct `/Account/{auth_id}/Call/` path casing and a valid `<Response>`.
  </Step>
</Steps>

## Codex

The same command installs into OpenAI Codex. Codex stores its config under `CODEX_HOME` (default `~/.codex`), and the CLI writes the skills into Codex's skills directory there.

<Steps>
  <Step title="Install the skills">
    ```bash theme={null}
    npx skills add https://vobiz.ai/docs --agents codex
    ```

    To install into a custom Codex home, set `CODEX_HOME` first:

    ```bash theme={null}
    CODEX_HOME=~/.config/codex npx skills add https://vobiz.ai/docs --agents codex
    ```
  </Step>

  <Step title="Confirm they landed">
    ```bash theme={null}
    npx skills list
    ```

    The output shows each `vobiz-*` skill and the exact Codex directory it was installed to on your machine.
  </Step>

  <Step title="Use them in a session">
    Start Codex in your project and describe the task - for example:

    > Build a Vobiz IVR: a `<Gather>` menu that routes to two departments.

    Codex applies the `vobiz-voice-xml` skill and uses `executionTimeout` (not `timeout`) on `<Gather>`, the kind of detail the skill encodes.
  </Step>
</Steps>

## Other agents

The same source works with every agent the CLI supports - Cursor, Windsurf, Gemini CLI, GitHub Copilot, Cline, Goose, and more. Target one explicitly with `--agents <name>`, install everywhere with `--all`, or run the bare command and pick from the checklist:

```bash theme={null}
# Interactive - detect agents and choose
npx skills add https://vobiz.ai/docs

# A specific agent
npx skills add https://vobiz.ai/docs --agents cursor

# Every detected agent, no prompts
npx skills add https://vobiz.ai/docs --all --yes
```

<Tip>
  Already connected the [Vobiz MCP server](/docs/resources/mcp)? Your agent can also discover these skills as MCP resources without a separate install - the local install above is for offline use and for agents you haven't wired to MCP.
</Tip>

## The Vobiz skill set

Each skill is scoped to one domain so your agent loads only what's relevant to the task.

| Skill | What it teaches |
| - | - |
| `vobiz-voice-calls` | Place, control, and inspect calls - outbound calls, transfer, hangup, live calls, and mid-call actions. |
| `vobiz-voice-xml` | Build call flows with VobizXML - `Speak`, `Play`, `Gather`, `Dial`, `Record`, `Stream`, `Conference`, `Redirect`, `Wait`, `Hangup`. |
| `vobiz-audio-streams` | Stream live call audio bidirectionally over WebSocket for AI agents and real-time transcription. |
| `vobiz-applications-endpoints` | Configure Voice Applications (answer/hangup webhooks) and SIP Endpoints (soft-phones, IP phones, browser clients). |
| `vobiz-sip-trunking` | Manage SIP trunks, credentials, IP ACLs, and origination URIs for BYOC and outbound routing. |
| `vobiz-phone-numbers` | Discover, purchase, assign, and release phone numbers (DIDs) across countries. |
| `vobiz-sub-accounts` | Create and manage sub-accounts for multi-team or multi-environment isolation. |
| `vobiz-cdr` | Query Call Detail Records - list, search, retrieve by UUID, fetch recent, and export CSV. |
| `vobiz-partner-api` | Reseller flows - create customer accounts, transfer balance, run KYC sessions, and query per-customer data. |
| `vobiz-whatsapp` | Send and receive on the WhatsApp Business API - templates, campaigns, inbox, and webhooks. |
| `vobiz-ai-voice-agents` | Connect Vobiz to Vapi, Retell, ElevenLabs, LiveKit, Pipecat, and other AI voice platforms over SIP or WebSocket. |
| `vobiz-plivo-migration` | Port a Plivo voice app to Vobiz - client/auth + base URL swap, PlivoXML → VobizXML, and the webhook signature header change. |

## Update or remove

* **Update:** re-run `npx skills add https://vobiz.ai/docs` to pull the latest versions. Add `--copy` if you prefer copies over symlinks.
* **Inspect:** `npx skills list` shows every installed skill and its location.
* **Remove:** delete the `vobiz-*` folders from your agent's skills directory (`.claude/skills/`, `~/.claude/skills/`, or the Codex skills directory).

## Related

* [MCP Server](/docs/resources/mcp) - connect your AI client to live, searchable Vobiz docs.
* [skills CLI](https://www.npmjs.com/package/skills) - full command reference and the list of supported agents.
* [Quick Start](/docs/quick-start) - make your first call once your agent is set up.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.