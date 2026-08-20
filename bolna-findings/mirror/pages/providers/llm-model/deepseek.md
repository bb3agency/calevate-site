> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# DeepSeek Models for Bolna Voice Agents

> Configure DeepSeek V4 Flash or V4 Pro as the LLM for your Bolna voice agent.

[DeepSeek](https://www.deepseek.com/) offers highly cost-effective LLMs with 1M token context windows. `deepseek-v4-flash` is the recommended option for voice agents — very low cost per token, high concurrent request limits, and competitive quality for conversational tasks.

<Warning>
  `deepseek-chat` and `deepseek-reasoner` are deprecated as of **July 24, 2026**. Migrate to `deepseek-v4-flash` or `deepseek-v4-pro` before that date.
</Warning>

***

## Quick config

```json theme={"system"}
"llm_agent": {
  "agent_type": "simple_llm_agent",
  "agent_flow_type": "streaming",
  "llm_config": {
    "provider": "deepseek",
    "model": "deepseek-v4-flash",
    "max_tokens": 150,
    "temperature": 0.2
  }
}
```

To use your own DeepSeek API key, connect it at [platform.bolna.ai/auth/deepseek](https://platform.bolna.ai/auth/deepseek).

***

## Supported models

| Model                   | Context   | Best for                | Notes                                          |
| ----------------------- | --------- | ----------------------- | ---------------------------------------------- |
| `deepseek-v4-flash`     | 1M tokens | Most voice agents       | **Recommended** — fastest, most cost-effective |
| `deepseek-v4-pro`       | 1M tokens | Complex reasoning tasks | Higher quality; lower concurrency limit        |
| ~~`deepseek-chat`~~     | —         | —                       | Deprecated July 24, 2026                       |
| ~~`deepseek-reasoner`~~ | —         | —                       | Deprecated July 24, 2026                       |

**Recommendation:** Use `deepseek-v4-flash` for all new deployments. It supports up to 2,500 concurrent requests — well-suited for high-volume outbound campaigns.

***

## Key settings

| Setting           | Type    | Recommended           | Description                                      |
| ----------------- | ------- | --------------------- | ------------------------------------------------ |
| `provider`        | string  | `"deepseek"`          | Provider name                                    |
| `model`           | string  | `"deepseek-v4-flash"` | Model to use                                     |
| `max_tokens`      | integer | `150`                 | Cap on response length — keep short for voice    |
| `temperature`     | float   | `0.2`                 | Lower = more consistent; good for scripted calls |
| `agent_flow_type` | string  | `"streaming"`         | Always `"streaming"` for voice                   |

### Prompt caching

DeepSeek V4 models support prompt caching — repeated system prompts cost significantly less on cache hits. For agents that run many calls with the same system prompt, this can reduce LLM costs substantially. Cache hits are automatic; no configuration needed.

***

## FAQ

<AccordionGroup>
  <Accordion title="deepseek-v4-flash vs deepseek-v4-pro — which should I use?">
    Use `deepseek-v4-flash` for most agents — lower cost, higher concurrency (2,500 vs 500 requests), and lower latency. Switch to `deepseek-v4-pro` if your use case requires more complex reasoning (e.g., nuanced financial conversations, detailed troubleshooting).
  </Accordion>

  <Accordion title="How do I migrate from deepseek-chat?">
    Change `"model": "deepseek-chat"` to `"model": "deepseek-v4-flash"` in your agent's LLM config. The API is compatible — no other changes needed. Test your prompt to confirm behavior since V4 is a newer generation.
  </Accordion>

  <Accordion title="How does DeepSeek compare to OpenAI for voice?">
    DeepSeek V4 is significantly cheaper and has a 1M token context window. For simple to moderate conversational tasks (reminders, qualification, COD confirmation), quality is comparable. For complex reasoning or precise instruction-following in English, GPT-5.4-mini may have an edge. Test on your specific use case.
  </Accordion>
</AccordionGroup>

***

## Related

* [LLM Tab](/docs/agent-setup/llm-tab) — configure LLM in the dashboard
* [OpenAI](/docs/providers/llm-model/openai) — GPT-5 family alternative
* [OpenRouter](/docs/providers/llm-model/openrouter) — access DeepSeek and others via unified gateway
* [Prompting Guide](/docs/guides/prompting/prompting-guide) — write effective prompts for voice
