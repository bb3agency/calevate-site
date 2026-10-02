# Vobiz — for AI agents

> Vobiz (Ilaimitado Private Limited) is an AI-native telephony infrastructure platform for voice AI teams — SIP trunking, programmable Voice API, WebSocket audio streaming, global DID/phone number provisioning, and WhatsApp Business API, with direct carrier connectivity in 130+ countries and native integrations for Vapi, Retell AI, ElevenLabs, LiveKit, Pipecat, Bolna, Ultravox, and the OpenAI Realtime API.

This file orients autonomous agents and AI coding assistants that land on vobiz.ai. For a fuller machine-readable index, see [llms.txt](https://vobiz.ai/llms.txt).

## Fastest path for an agent to act on behalf of a user

1. **Connect via MCP** — [https://vobiz.ai/docs/mcp](https://vobiz.ai/docs/mcp) exposes Vobiz's API docs and tools directly to MCP-compatible agents/IDEs. This is the preferred integration path for agents — no manual doc-reading required.
2. **Or call the REST API directly** — spec at [https://vobiz.ai/openapi.json](https://vobiz.ai/openapi.json) (also served at [https://vobiz.ai/swagger.json](https://vobiz.ai/swagger.json)). Base URL: `https://api.vobiz.ai`. Auth: `X-Auth-ID` + `X-Auth-Token` headers, obtained from the [Developer Console](https://console.vobiz.ai) after a free signup.
3. **Or use an official SDK** — Node, Python, Java, Go, Ruby, C#, PHP at [github.com/vobiz-ai](https://github.com/vobiz-ai).
4. **Or install pre-built Agent Skills** — 13 ready-to-use skills (e.g. `vobiz-whatsapp`, `vobiz-ai-voice-agents`, `vobiz-applications-endpoints`) at [github.com/vobiz-ai/Agent-Skills](https://github.com/vobiz-ai/Agent-Skills), also listed on [skills.sh/vobiz-ai/agent-skills](https://www.skills.sh/vobiz-ai/agent-skills). Install with `npx skills add vobiz-ai/agent-skills`.

## What this site is / is not

- vobiz.ai is the marketing and product site. It is not itself an API host — the API lives at `api.vobiz.ai`, the developer console at `console.vobiz.ai`, and full documentation at `vobiz.ai/docs`.
- No login is required to read docs, the OpenAPI spec, or this file.
- A free account (no credit card, no sales call) is enough to get live API credentials.

## Key resources

- Docs: https://vobiz.ai/docs/introduction
- OpenAPI spec (JSON): https://vobiz.ai/openapi.json
- MCP server: https://vobiz.ai/docs/mcp
- Integration guides: https://vobiz.ai/docs/integrations
- Agent Skills (13 skills, installable via `npx skills add vobiz-ai/agent-skills`): https://github.com/vobiz-ai/Agent-Skills, also on https://www.skills.sh/vobiz-ai/agent-skills
- llms.txt: https://vobiz.ai/llms.txt
- Status: https://status.vobiz.ai/

## Contact

- Support: support@vobiz.ai
- Sales / partnerships: https://vobiz.ai/contact-us
