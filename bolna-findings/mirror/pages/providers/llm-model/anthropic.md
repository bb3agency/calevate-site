> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Anthropic Claude Models for Bolna Voice Agents

> Configure Claude Sonnet 5 or Claude Haiku 4.5 as the LLM for your Bolna voice agent.

[Anthropic's](https://www.anthropic.com/) Claude models are known for precise instruction following and strong reasoning. `claude-sonnet-5` is the recommended production choice — best speed-to-quality ratio. `claude-haiku-4-5-20251001` is the fastest and most cost-efficient option for high-volume agents.

***

## Quick config

```json theme={"system"}
"llm_agent": {
  "agent_type": "simple_llm_agent",
  "agent_flow_type": "streaming",
  "llm_config": {
    "provider": "anthropic",
    "model": "claude-sonnet-5",
    "max_tokens": 150,
    "temperature": 0.2
  }
}
```

To use your own Anthropic API key, connect it at [platform.bolna.ai/auth/anthropic](https://platform.bolna.ai/auth/anthropic).

***

## Supported models

| Model                       | Context     | Best for                                   | Notes                                        |
| --------------------------- | ----------- | ------------------------------------------ | -------------------------------------------- |
| `claude-fable-5`            | 1M tokens   | Most complex reasoning, long-horizon tasks | Flagship; highest capability and cost        |
| `claude-opus-4-8`           | 1M tokens   | Complex reasoning, agentic workflows       | High capability; slower than Sonnet          |
| `claude-sonnet-5`           | 1M tokens   | Most production voice agents               | **Recommended** — best speed/quality balance |
| `claude-haiku-4-5-20251001` | 200K tokens | High-volume, cost-sensitive agents         | Fastest TTFT; lowest cost                    |

**Recommendation:** Start with `claude-sonnet-5`. Drop to `claude-haiku-4-5-20251001` if you need lower latency or cost at scale. Upgrade to `claude-opus-4-8` for complex multi-step reasoning or sensitive domains.

***

## Key settings

| Setting           | Type    | Recommended         | Description                                   |
| ----------------- | ------- | ------------------- | --------------------------------------------- |
| `provider`        | string  | `"anthropic"`       | Provider name                                 |
| `model`           | string  | `"claude-sonnet-5"` | Model to use                                  |
| `max_tokens`      | integer | `150`               | Cap on response length — keep short for voice |
| `temperature`     | float   | `0.2`               | Lower = more deterministic; good for scripts  |
| `agent_flow_type` | string  | `"streaming"`       | Always `"streaming"` for voice                |

***

## Writing prompts for voice

Claude follows instructions very precisely — avoid vague phrasing.

* **Be explicit about format**: "Respond in 1–2 sentences maximum. Never use bullet points."
* **Define your scope**: "Only discuss topics related to appointment scheduling."
* **Set the persona clearly**: "You are a friendly receptionist for Acme Clinic. Your name is Priya."

See [Prompting Guide](/docs/guides/prompting/prompting-guide) for full guidance.

***

## Function calling

All current Claude models support function calling. Functions are defined in the [Tools Tab](/docs/agent-setup/tools-tab) and called automatically during conversation.

See [Custom Function Calls](/docs/tool-calling/custom-function-calls) for configuration.

***

## FAQ

<AccordionGroup>
  <Accordion title="Which Claude model should I use for voice?">
    `claude-sonnet-5` for most agents — strong instruction following at low latency. Use `claude-haiku-4-5-20251001` when cost or speed is the primary constraint. Use `claude-opus-4-8` or `claude-fable-5` only for the most complex reasoning tasks.
  </Accordion>

  <Accordion title="Why is temperature 0.2 recommended?">
    Lower temperature makes the model more consistent and predictable — important for scripted outbound calls. For more conversational or discovery-type agents, 0.5–0.7 is fine.
  </Accordion>

  <Accordion title="How do I reduce latency?">
    Use `claude-haiku-4-5-20251001` (significantly faster than Sonnet), keep `max_tokens` low (150 is a good ceiling), and write concise system prompts. See [Latency](/docs/concepts/latency) for a full breakdown.
  </Accordion>

  <Accordion title="Can I use my own Anthropic API key?">
    Yes. Connect your Anthropic account at [platform.bolna.ai/auth/anthropic](https://platform.bolna.ai/auth/anthropic). LLM costs will be charged to your Anthropic account.
  </Accordion>
</AccordionGroup>

***

## Related

* [LLM Tab](/docs/agent-setup/llm-tab) — configure LLM in the dashboard
* [OpenAI](/docs/providers/llm-model/openai) — GPT-5 family alternative
* [OpenRouter](/docs/providers/llm-model/openrouter) — access Claude via unified gateway
* [Prompting Guide](/docs/guides/prompting/prompting-guide) — write effective prompts for voice
* [Custom Function Calls](/docs/tool-calling/custom-function-calls) — add tools to your agent
