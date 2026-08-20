> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# OpenAI GPT Models for Bolna Voice Agents

> Configure GPT-5.6 (Sol, Terra, Luna), GPT-5.5, GPT-5.4, or GPT-5.4-mini as the LLM for your Bolna voice agent. Covers model selection, streaming config, prompt tips, and function calling.

[OpenAI's](https://openai.com/) GPT-5 family is the current generation, with **GPT-5.6** (Sol, Terra, Luna) the newest release. `gpt-5.4-mini` remains the default recommendation for most voice agents: it has low time-to-first-token and strong instruction following at a fraction of the cost of the full models.

***

## Quick config

```json theme={"system"}
"llm_agent": {
  "agent_type": "simple_llm_agent",
  "agent_flow_type": "streaming",
  "llm_config": {
    "provider": "openai",
    "model": "gpt-5.4-mini",
    "max_tokens": 150,
    "temperature": 1
  }
}
```

<Warning>
  GPT-5-series models require `"temperature": 1`. Any other value is rejected with `400 For GPT-5 models, temperature must be 1`, and the field defaults to `0.1` when omitted, so send it explicitly.
</Warning>

To use your own OpenAI API key, connect it at [platform.bolna.ai/auth/openai](https://platform.bolna.ai/auth/openai).

***

## Supported models

| Model           | Context     | Best for                                                 | Notes                                                           |
| --------------- | ----------- | -------------------------------------------------------- | --------------------------------------------------------------- |
| `gpt-5.6-sol`   | 1M tokens   | Hardest tasks: complex coding, deep multi-step reasoning | Newest flagship; highest cost                                   |
| `gpt-5.6-terra` | 1M tokens   | High-volume production agents; balanced quality and cost | Newest; about 2x cheaper than Sol                               |
| `gpt-5.6-luna`  | 1M tokens   | Fast, low-cost everyday voice agents                     | Newest low-cost tier; strong quality per dollar                 |
| `gpt-5.5`       | 1M tokens   | Most demanding reasoning and quality                     | Flagship 5.5 line; high cost                                    |
| `gpt-5.5-pro`   | 1M tokens   | Maximum quality on complex reasoning                     | Highest cost and latency; not ideal for latency-sensitive voice |
| `gpt-5.4`       | 1M tokens   | General-purpose production agents                        | Strong reasoning, lower cost than 5.5                           |
| `gpt-5.4-mini`  | 400K tokens | Most voice agents                                        | **Recommended**: fastest TTFT, lowest cost                      |
| `gpt-4.1`       | 1M tokens   | Previous-gen; still available                            | Use if already deployed                                         |
| `gpt-4.1-mini`  | 1M tokens   | Previous-gen; still available                            | Use if already deployed                                         |
| `gpt-4o`        | 128K tokens | Previous-gen; still available                            | Use if already deployed                                         |

**Recommendation:** Start with `gpt-5.4-mini`. Step up to `gpt-5.6-terra` or `gpt-5.6-luna` for newest-generation quality at moderate cost, or `gpt-5.6-sol` / `gpt-5.5` when you need the strongest multi-step reasoning and highest output quality (financial, medical, nuanced escalation).

***

## Key settings

| Setting            | Type    | Recommended      | Description                                                                 |
| ------------------ | ------- | ---------------- | --------------------------------------------------------------------------- |
| `provider`         | string  | `"openai"`       | Provider name                                                               |
| `model`            | string  | `"gpt-5.4-mini"` | Model to use                                                                |
| `max_tokens`       | integer | `150`            | Cap on response length — keep short for voice                               |
| `temperature`      | float   | `1`              | Required value on GPT-5 models; no other value is accepted                  |
| `reasoning_effort` | string  | `"none"`         | How much the model reasons first. GPT-5 only; valid values differ per model |
| `verbosity`        | string  | `"low"`          | How long answers run. GPT-5 only                                            |
| `agent_flow_type`  | string  | `"streaming"`    | Always `"streaming"` for voice                                              |

### Keep max\_tokens short

Voice responses should be 1–3 sentences. `max_tokens: 150` is appropriate for most turns. A higher cap doesn't hurt quality but increases tail latency on long responses.

On GPT-5 models `max_tokens` is sent as `max_completion_tokens` and reasoning tokens come out of the same budget. At `reasoning_effort` above `none`/`minimal`, reasoning can consume most of a 150-token cap and truncate the spoken reply, so raise the cap whenever you raise the effort.

***

## Reasoning effort

GPT-5 models reason before answering. Effort controls how much, and it is the main quality-versus-latency dial on the LLM leg of a call. Leave it unset and the model gets the lowest-latency effort it supports, which is what most voice agents want.

Every model accepts a different subset, and an unsupported value is rejected when the agent is created:

| Model                                          | Accepted `reasoning_effort`              |
| ---------------------------------------------- | ---------------------------------------- |
| `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna` | `none`, `low`, `medium`, `high`, `xhigh` |
| `gpt-5.5`                                      | `none`, `low`, `medium`, `high`, `xhigh` |
| `gpt-5.5-pro`                                  | `medium`, `high`, `xhigh`                |
| `gpt-5.4`                                      | `none`, `low`, `medium`, `high`, `xhigh` |
| `gpt-5.4-mini`, `gpt-5.4-nano`                 | `none`, `low`, `medium`, `high`          |
| `gpt-5.2`                                      | `none`, `low`, `medium`, `high`, `xhigh` |
| `gpt-5.1`                                      | `none`, `low`, `medium`, `high`          |
| `gpt-5`, `gpt-5-mini`, `gpt-5-nano`            | `minimal`, `low`, `medium`, `high`       |

<Warning>
  `minimal` is valid only on `gpt-5`, `gpt-5-mini` and `gpt-5-nano`. On `gpt-5.1` and later the equivalent is `none`.
</Warning>

For live calls, stay at `none` or `low`. Each step up adds reasoning tokens before the first spoken word, which lands directly in time-to-first-token. See [Latency](/docs/concepts/latency).

***

## Writing prompts for voice

Prompts for voice agents differ from chat prompts:

* **Use imperative sentences**: "Keep all responses under 3 sentences."
* **Specify spoken format**: "Never use bullet points or markdown — speak in complete sentences."
* **Define handling for off-topic questions**: "If asked something outside your scope, say: 'I can only help with appointment scheduling today.'"
* **Include the welcome message in the prompt or agent config**, not as part of the system prompt instructions.

See [Prompting Guide](/docs/guides/prompting/prompting-guide) for full guidance.

***

## Function calling

All GPT-5 and GPT-4.1 models support function calling. In Bolna, functions are defined in the [Tools Tab](/docs/agent-setup/tools-tab) and called automatically by the LLM during conversation.

`gpt-5.4`, `gpt-5.5` and `gpt-5.6` run through OpenAI's Responses API automatically, because function calling combined with `reasoning_effort` is not accepted on chat completions for those models. You don't need to configure anything for this.

See [Custom Function Calls](/docs/tool-calling/custom-function-calls) for configuration.

***

## FAQ

<AccordionGroup>
  <Accordion title="Which GPT model should I use?">
    Use `gpt-5.4-mini` for most agents: lowest time-to-first-token and significantly lower cost per call. Step up to `gpt-5.6-terra` or `gpt-5.6-luna` for newest-generation quality at moderate cost, or `gpt-5.6-sol` / `gpt-5.5` for the most demanding tasks (complex financial/medical, long multi-step tool chains) where quality is the top priority. Avoid `gpt-5.5-pro` for live voice; its latency is too high for real-time calls.
  </Accordion>

  <Accordion title="Can I lower temperature to make a GPT-5 agent more consistent?">
    No. GPT-5-series models accept only `temperature: 1`, and anything else fails agent creation with a 400. Use the prompt to constrain behaviour instead: state the exact wording, the sentence limit, and the fallback line for off-topic questions. On the previous-generation GPT-4.1 models a lower temperature still applies.
  </Accordion>

  <Accordion title="How do I reduce latency?">
    Keep `reasoning_effort` at `none` (or `minimal` on `gpt-5`/`gpt-5-mini`/`gpt-5-nano`), lower `max_tokens`, use `gpt-5.4-mini` instead of the larger models, and write shorter system prompts (large prompts increase prefill time). Reasoning effort is usually the biggest single lever. See [Latency](/docs/concepts/latency) for a full breakdown.
  </Accordion>

  <Accordion title="Can I use my own OpenAI API key?">
    Yes. Connect your OpenAI account at [platform.bolna.ai/auth/openai](https://platform.bolna.ai/auth/openai). Costs will be charged to your OpenAI account, not Bolna's platform wallet (for the LLM component).
  </Accordion>
</AccordionGroup>

***

## Related

* [LLM Tab](/docs/agent-setup/llm-tab) — configure LLM in the dashboard
* [Anthropic Claude](/docs/providers/llm-model/anthropic) — alternative LLM
* [Azure OpenAI](/docs/providers/llm-model/azure-openai) — OpenAI models with enterprise data residency
* [Prompting Guide](/docs/guides/prompting/prompting-guide) — write effective prompts for voice
* [Custom Function Calls](/docs/tool-calling/custom-function-calls) — add tools to your agent
