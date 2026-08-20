> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Bolna Voice AI usage pricing

> Discover detailed insights into Bolna Voice AI's pricing structure. Learn about cost breakdowns and flexible plans tailored to your business needs.

## How much does Bolna Voice AI cost?

Bolna Voice AI uses a transparent, usage-based pricing model. You only pay for what you use, with costs broken down into three components: Voice AI processing (STT + LLM + TTS), telephony charges, and a Bolna platform fee.

<Card title="View pricing plans" icon="hand-holding-dollar" href="https://bolna.ai/pricing">
  See all available plans, volume tiers, and per-minute rates on our pricing page.
</Card>

***

## What does call pricing depend on?

Every call's total cost is the sum of five components across three parts.

**Part A - Voice AI (STT + LLM + TTS)**

<CardGroup cols={3}>
  <Card title="Transcriber" icon="ear-listen" href="/docs/providers/transcriber/deepgram">
    Your choice of Speech-to-Text (STT) model and provider.

    Billed by **call duration** (rounded to seconds).
  </Card>

  <Card title="LLM" icon="brain" href="/docs/providers/llm-model/openai">
    Your choice of Large Language Model (LLM) and provider.

    Billed by **tokens generated**.
  </Card>

  <Card title="Text to Speech (TTS)" icon="volume-high" href="/docs/providers/voice/aws-polly">
    Your choice of TTS model and provider.

    Billed by **characters synthesized**.
  </Card>
</CardGroup>

**Part B & C - Telephony and Platform**

<CardGroup cols={2}>
  <Card title="Telephony provider" icon="phone" href="/docs/supported-telephony-providers">
    Your telephony provider and the country/region of the phone numbers.

    Billed by **call duration** (rounded to minutes).
  </Card>

  <Card title="Bolna platform fee" icon="bolt">
    A flat per-minute fee charged by Bolna on top of your provider costs.

    Billed by **call duration**.
  </Card>
</CardGroup>

***

## Which models are included in my rate?

Every workspace's flat per-minute rate already bundles a curated set of ASR, LLM, and TTS models — Bolna calls these your **preferred models**. Using only preferred models keeps your Voice AI cost at the flat rate; picking any other model bills that component separately at variable, usage-based rates.

<Card title="See your preferred models" icon="list-check" href="/docs/pricing/preferred-models">
  View the current preferred ASR, LLM, and TTS model list and how it affects billing.
</Card>

***

## How can I reduce my Voice AI costs?

You can significantly reduce costs by connecting your own provider accounts. When you bring your own keys (BYOK), Bolna does not charge for those components. You only pay your providers directly, plus Bolna's platform fee.

<Steps>
  <Step title="Connect your provider accounts">
    Head to the [Providers page](https://platform.bolna.ai/providers) to link your own STT, LLM, and TTS accounts.
  </Step>

  <Step title="Choose cost-efficient models">
    Lighter LLM models (e.g. `gpt-4o-mini`) and efficient TTS voices can meaningfully lower per-call costs.
  </Step>

  <Step title="Choose a volume plan">
    For predictable workloads, a volume-based plan offers better per-minute rates than pay-as-you-go.
    See available tiers at [bolna.ai/pricing](https://bolna.ai/pricing).
  </Step>
</Steps>

[Learn more about supported providers](/docs/providers) and how to connect your accounts.

***

## Where can I see my call costs?

After each conversation, go to the [Agent Executions page](https://platform.bolna.ai/agent-executions) to see how many credits the conversation consumed.

<Frame caption="Credits consumed for calls">
  <img src="https://mintcdn.com/bolna-54a2d4fe/DqJpudnR0YtgOS49/images/pricing.png?fit=max&auto=format&n=DqJpudnR0YtgOS49&q=85&s=24d94ce849a7514bc571ff0d74218460" title="Bolna Voice AI Pricing Details" alt="Bolna Voice AI pricing breakdown showing credits consumed per call with detailed component costs for STT, LLM, TTS, telephony, and platform fees displayed in the executions dashboard" width="1310" height="464" data-path="images/pricing.png" />
</Frame>

***

## Next steps

<CardGroup cols={2}>
  <Card title="View pricing plans" icon="hand-holding-dollar" href="https://bolna.ai/pricing">
    Explore pay-as-you-go, pilots, and enterprise plans
  </Card>

  <Card title="Connect providers" icon="plug" href="/docs/providers">
    Bring your own keys to reduce per-call costs
  </Card>

  <Card title="Preferred models" icon="list-check" href="/docs/pricing/preferred-models">
    See which models are included in your flat rate
  </Card>

  <Card title="Call execution history" icon="chart-bar" href="https://platform.bolna.ai/agent-executions">
    Track credits consumed per call
  </Card>

  <Card title="Enterprise plan" icon="building" href="/docs/enterprise/plan">
    Custom pricing for high-volume deployments
  </Card>
</CardGroup>

<Note>
  For customized volume-based pricing, reach out to us at [enterprise@bolna.ai](mailto:enterprise@bolna.ai).
</Note>
