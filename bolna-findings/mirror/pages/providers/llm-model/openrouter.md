> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# OpenRouter for Bolna Voice Agents

> Access models from OpenAI, Anthropic, Google, Mistral, Meta, and more through a single OpenRouter API key.

[OpenRouter](https://openrouter.ai) is a unified API gateway that lets you access models from multiple providers — OpenAI, Anthropic, Google, Mistral, Meta, and others — through a single integration. Use it when you want to avoid managing multiple API keys, need automatic fallback between providers, or want to experiment with models without separate provider accounts.

***

## Quick config

```json theme={"system"}
"llm_agent": {
  "agent_type": "simple_llm_agent",
  "agent_flow_type": "streaming",
  "llm_config": {
    "provider": "openrouter",
    "model": "openai/gpt-4o-mini",
    "max_tokens": 150,
    "temperature": 0.2
  }
}
```

Connect your OpenRouter account at [platform.bolna.ai/auth/openrouter](https://platform.bolna.ai/auth/openrouter). Get your API key at [openrouter.ai](https://openrouter.ai).

***

## Recommended models for voice

OpenRouter uses `provider/model-name` slugs. These are the top picks for voice agents:

| Model slug                    | Context | Best for                             |
| ----------------------------- | ------- | ------------------------------------ |
| `openai/gpt-4o-mini`          | 128K    | Best OpenAI balance via OpenRouter   |
| `openai/gpt-4o`               | 128K    | Higher quality OpenAI via OpenRouter |
| `anthropic/claude-haiku-4.5`  | 200K    | Fast, cost-efficient Claude          |
| `anthropic/claude-sonnet-4.1` | 200K    | High-quality Claude                  |
| `google/gemini-3-flash`       | 1M      | Fast Gemini, good multilingual       |
| `google/gemini-3-flash-lite`  | 1M      | Cheapest large-context option        |
| `mistralai/mistral-small`     | 32K     | Fast, low-cost European option       |
| `meta-llama/llama-3.1-70b`    | 128K    | Open-weight; cost-effective          |
| `deepseek/deepseek-chat`      | 1M      | Ultra-low cost (DeepSeek V4)         |

For the full model catalog, see [openrouter.ai/models](https://openrouter.ai/models).

***

## Key settings

| Setting           | Type    | Recommended                 | Description                                   |
| ----------------- | ------- | --------------------------- | --------------------------------------------- |
| `provider`        | string  | `"openrouter"`              | Provider name                                 |
| `model`           | string  | e.g. `"openai/gpt-4o-mini"` | Full OpenRouter model slug                    |
| `max_tokens`      | integer | `150`                       | Cap on response length — keep short for voice |
| `temperature`     | float   | `0.2`                       | Lower = more consistent                       |
| `agent_flow_type` | string  | `"streaming"`               | Always `"streaming"` for voice                |

***

## When to use OpenRouter vs direct providers

Use **OpenRouter** when:

* You want one API key for multiple providers
* You need automatic fallback if a provider is down
* You're testing and comparing models quickly
* You don't have existing API relationships with providers

Use **direct provider integrations** when:

* You need the absolute latest model versions (OpenRouter has a short lag)
* Your compliance requires knowing exactly which provider handles your data
* You want provider-specific features (Azure data residency, Anthropic Workspaces, etc.)

***

## FAQ

<AccordionGroup>
  <Accordion title="Does OpenRouter add latency?">
    Minimal — typically a few milliseconds for routing. For most voice agents this is negligible. If you're highly latency-sensitive, benchmark against a direct provider connection.
  </Accordion>

  <Accordion title="Which OpenRouter model is best for Hindi or Indian languages?">
    `google/gemini-3-flash` has strong multilingual capability including Indian languages. For the best Indian language support, consider using [Sarvam](/docs/providers/llm-model) directly as the LLM provider.
  </Accordion>

  <Accordion title="Can I set fallback models on OpenRouter?">
    Yes — OpenRouter supports model routing and fallback configuration through their dashboard. Set your primary model in Bolna and configure fallback logic in the OpenRouter console.
  </Accordion>
</AccordionGroup>

***

## Related

* [LLM Tab](/docs/agent-setup/llm-tab) — configure LLM in the dashboard
* [OpenAI](/docs/providers/llm-model/openai) — direct OpenAI integration
* [Anthropic](/docs/providers/llm-model/anthropic) — direct Anthropic integration
* [Google Gemini](/docs/providers/llm-model/gemini) — direct Gemini integration
* [Prompting Guide](/docs/guides/prompting/prompting-guide) — write effective prompts for voice
