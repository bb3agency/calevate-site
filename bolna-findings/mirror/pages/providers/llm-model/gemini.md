> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Google Gemini Models for Bolna Voice Agents

> Configure Gemini 2.5 Flash or Gemini 3.x models as the LLM for your Bolna voice agent.

[Google Gemini](https://ai.google.dev/) models offer large context windows (up to 1M tokens), strong multilingual capability, and competitive latency. `gemini-2.5-flash` is the stable production recommendation for most agents — good speed-quality balance. The Gemini 3.x series is the newer generation with higher capability.

***

## Quick config

```json theme={"system"}
"llm_agent": {
  "agent_type": "simple_llm_agent",
  "agent_flow_type": "streaming",
  "llm_config": {
    "provider": "google",
    "model": "gemini-2.5-flash",
    "max_tokens": 150,
    "temperature": 0.2
  }
}
```

To use your own Google API key, connect it at [platform.bolna.ai/auth/google](https://platform.bolna.ai/auth/google).

***

## Supported models

| Model                   | Context   | Best for                       | Notes                                  |
| ----------------------- | --------- | ------------------------------ | -------------------------------------- |
| `gemini-3.5-flash`      | 1M tokens | Complex reasoning, agent tasks | Latest generation; stable              |
| `gemini-3.1-pro`        | 1M tokens | Complex tasks, highest quality | Gemini 3 premium model                 |
| `gemini-3.1-flash-lite` | 1M tokens | Budget, high-volume agents     | Fastest in Gemini 3 family             |
| `gemini-2.5-pro`        | 1M tokens | Advanced reasoning             | Gemini 2.5 premium; stable             |
| `gemini-2.5-flash`      | 1M tokens | Most production voice agents   | **Recommended** — proven, stable, fast |
| `gemini-2.5-flash-lite` | 1M tokens | Cost-sensitive high volume     | Cheapest in 2.5 family                 |

**Recommendation:** Use `gemini-2.5-flash` for proven production stability. Try `gemini-3.5-flash` or `gemini-3.1-flash-lite` for improved performance on newer deployments.

***

## Key settings

| Setting           | Type    | Recommended          | Description                                   |
| ----------------- | ------- | -------------------- | --------------------------------------------- |
| `provider`        | string  | `"google"`           | Provider name                                 |
| `model`           | string  | `"gemini-2.5-flash"` | Model to use                                  |
| `max_tokens`      | integer | `150`                | Cap on response length — keep short for voice |
| `temperature`     | float   | `0.2`                | Lower = more deterministic                    |
| `agent_flow_type` | string  | `"streaming"`        | Always `"streaming"` for voice                |

***

## Multilingual support

Gemini models have strong native multilingual capability. For Indian language agents (Hindi, Tamil, Bengali, etc.), Gemini is a good alternative to Sarvam if you need broader LLM capability alongside multilingual handling.

Always set the language explicitly in your prompt — Gemini handles it well, but auto-detection adds latency.

***

## FAQ

<AccordionGroup>
  <Accordion title="Gemini 2.5 vs Gemini 3.x — which should I use?">
    Both are stable. `gemini-2.5-flash` is the battle-tested choice with predictable performance. `gemini-3.5-flash` or `gemini-3.1-flash-lite` offer newer capability and are worth testing — especially for complex reasoning tasks. Switch once you've validated quality on your agent.
  </Accordion>

  <Accordion title="How does Gemini compare to GPT for voice?">
    Comparable latency. Gemini has an edge on multilingual tasks and large-context scenarios (1M token window). GPT-5.4-mini has a slight edge on English instruction following consistency. Test both on your specific use case.
  </Accordion>

  <Accordion title="Can I use my own Google API key?">
    Yes. Connect at [platform.bolna.ai/auth/google](https://platform.bolna.ai/auth/google). API costs will be charged to your Google account.
  </Accordion>
</AccordionGroup>

***

## Related

* [LLM Tab](/docs/agent-setup/llm-tab) — configure LLM in the dashboard
* [OpenAI](/docs/providers/llm-model/openai) — GPT-5 family alternative
* [Multilingual Support](/docs/customizations/multilingual-languages-support) — configure language for your agent
* [Prompting Guide](/docs/guides/prompting/prompting-guide) — write effective prompts for voice
