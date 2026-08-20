> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Azure OpenAI Models for Bolna Voice Agents

> Use GPT-5.4-mini, GPT-5.4, GPT-4.1, or GPT-4o through Azure OpenAI for enterprise data residency and compliance.

[Azure OpenAI Service](https://azure.microsoft.com/en-us/products/ai-services/openai-service) provides the same OpenAI models through Microsoft's cloud infrastructure — adding data residency controls, private networking, and enterprise compliance (SOC 2, HIPAA, ISO 27001). Use this provider when your deployment requires regional data handling or Azure-native security.

***

## Quick config

```json theme={"system"}
"llm_agent": {
  "agent_type": "simple_llm_agent",
  "agent_flow_type": "streaming",
  "llm_config": {
    "provider": "azure-openai",
    "model": "gpt-5.4-mini",
    "max_tokens": 150,
    "temperature": 1
  }
}
```

<Warning>
  GPT-5-series models require `"temperature": 1`. Any other value is rejected with `400 For GPT-5 models, temperature must be 1`, and the field defaults to `0.1` when omitted, so send it explicitly.
</Warning>

Connect your Azure account at [platform.bolna.ai/auth/azure](https://platform.bolna.ai/auth/azure). You'll need your Azure endpoint URL, API key, and deployment name.

***

## Supported models

| Model          | Context     | Best for                        | Notes                                       |
| -------------- | ----------- | ------------------------------- | ------------------------------------------- |
| `gpt-5.5`      | 1M tokens   | Maximum quality; complex tasks  | Flagship; highest cost                      |
| `gpt-5.4`      | 1M tokens   | General-purpose production      | Strong reasoning at lower cost than 5.5     |
| `gpt-5.4-mini` | 400K tokens | Most voice agents               | **Recommended** — best latency/cost balance |
| `gpt-5.4-nano` | 400K tokens | Ultra-high-volume, simple tasks | Cheapest option                             |
| `gpt-4.1`      | 1M tokens   | Previous gen; still available   | Stable if already deployed                  |
| `gpt-4.1-mini` | 1M tokens   | Previous gen; still available   | Stable if already deployed                  |
| `gpt-4o`       | 128K tokens | Previous gen; still available   | Stable if already deployed                  |
| `gpt-4o-mini`  | 128K tokens | Previous gen; still available   | Stable if already deployed                  |

<Note>
  Azure model availability varies by region. Not all models are available in all Azure regions immediately at launch. Check the [Azure OpenAI model availability](https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/models) page for your region.
</Note>

***

## Key settings

| Setting            | Type    | Recommended      | Description                                                                 |
| ------------------ | ------- | ---------------- | --------------------------------------------------------------------------- |
| `provider`         | string  | `"azure-openai"` | Provider name                                                               |
| `model`            | string  | `"gpt-5.4-mini"` | Model/deployment name                                                       |
| `max_tokens`       | integer | `150`            | Cap on response length — keep short for voice                               |
| `temperature`      | float   | `1`              | Required value on GPT-5 models; no other value is accepted                  |
| `reasoning_effort` | string  | `"none"`         | How much the model reasons first. GPT-5 only; valid values differ per model |
| `verbosity`        | string  | `"low"`          | How long answers run. GPT-5 only                                            |
| `agent_flow_type`  | string  | `"streaming"`    | Always `"streaming"` for voice                                              |

### GPT-5 settings with custom deployment names

Azure deployment names are chosen freely, so `model` here is often not the model name. Keep the underlying model name inside the deployment name — `prod-gpt-5.4-mini` rather than `prod-voice-01`. Bolna resolves the deployment to the model it serves, and that resolution is what selects GPT-5 handling and the right default `reasoning_effort`. A name it cannot resolve is treated as a non-GPT-5 model and gets the wrong defaults.

<Note>
  `reasoning_effort` is only checked against the [per-model table](/docs/providers/llm-model/openai#reasoning-effort) when `model` is an exact model name such as `gpt-5.4-mini` or `azure/gpt-5.4-mini`. With a custom deployment name, an unsupported value is accepted when you create the agent and then fails on the call instead. Check the table yourself when using custom deployment names.
</Note>

***

## When to use Azure OpenAI vs direct OpenAI

Use **Azure OpenAI** when:

* Your data must stay within a specific region (EU data residency, HIPAA)
* You need private networking (VNet, private endpoints)
* Your organization already uses Azure for infrastructure
* You need enterprise SLA guarantees

Use **direct OpenAI** when:

* Simplest setup is preferred
* You don't have compliance requirements for data residency
* You want access to the latest models as soon as they launch (Azure has a short lag)

***

## FAQ

<AccordionGroup>
  <Accordion title="Do I need a separate Azure deployment for each model?">
    Yes. In Azure OpenAI, you create a named deployment for each model in the Azure portal. The deployment name is what you pass as the `model` field in Bolna config.
  </Accordion>

  <Accordion title="Does Azure OpenAI have the same models as OpenAI?">
    Azure mirrors OpenAI's lineup but with a short availability lag after new models launch. All GPT-5.x, GPT-4.1, and GPT-4o variants are available. Check [Microsoft's model page](https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/models) for your region.
  </Accordion>

  <Accordion title="How do I reduce latency on Azure?">
    Keep `reasoning_effort` at `none`, use `gpt-5.4-mini`, keep `max_tokens` at 150, and deploy to an Azure region geographically close to your users. See [Latency](/docs/concepts/latency) for more.
  </Accordion>
</AccordionGroup>

***

## Related

* [LLM Tab](/docs/agent-setup/llm-tab) — configure LLM in the dashboard
* [OpenAI](/docs/providers/llm-model/openai) — same models without Azure overhead
* [Prompting Guide](/docs/guides/prompting/prompting-guide) — write effective prompts for voice
* [Custom Function Calls](/docs/tool-calling/custom-function-calls) — add tools to your agent
