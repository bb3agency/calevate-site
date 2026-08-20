> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Preferred models included in the flat rate

> See exactly which ASR, LLM, and TTS models are bundled into Bolna's flat per-minute rate, so you know when you're on the included tier versus paying variable provider costs.

## What are preferred models?

Every Bolna workspace ships with a **flat per-minute rate** — **\$0.06/min (₹5.52/min)** at standard wallet tiers — that already includes a curated set of transcriber (ASR), LLM, and voice (TTS) models. As long as your agent uses only these models, your Voice AI cost is the flat rate — you don't see separate line items for STT, LLM, or TTS usage.

If you pick a model outside this list (a premium model, a [BYOK provider](/docs/pricing/call-pricing#how-can-i-reduce-my-voice-ai-costs), or a model not yet marked as preferred), that component is billed at variable, usage-based rates instead of the flat rate. This is the single biggest reason two agents with the same call volume can see very different bills.

<Info>
  Preferred models change over time as Bolna negotiates provider rates and adds new options. This page is a snapshot — always check the **Add Funds** panel in your dashboard for the current list on your account.
</Info>

<Note>
  Larger wallet top-ups (e.g. \$600+) get a lower effective per-minute rate as a volume discount — the preferred model bundle itself is the same across tiers.
</Note>

***

## Where to see your preferred models

<Steps>
  <Step title="Open Agent Studio and click the wallet '+' button">
    Go to [platform.bolna.ai](https://platform.bolna.ai) and click the **+** button next to your wallet balance in the top-right corner.

    <Frame caption="The + button next to your wallet balance in Agent Studio opens the Add Funds panel">
      <img src="https://mintcdn.com/bolna-54a2d4fe/X4uxa31huXpE1D2q/images/pricing/preferred-models-add-funds-button.png?fit=max&auto=format&n=X4uxa31huXpE1D2q&q=85&s=c9aa9849c1d2ce414f4d86cd02601c68" alt="Bolna Agent Studio header showing the wallet balance and a highlighted + button used to open the Add Funds panel" width="2522" height="1392" data-path="images/pricing/preferred-models-add-funds-button.png" />
    </Frame>
  </Step>

  <Step title="Open the Add Funds panel">
    This opens the **Add Funds** modal. Scroll to the **"Your Selection"** section below the top-up amount options.
  </Step>

  <Step title="Click 'Show models'">
    Under **"Your preferred models (included in the 6¢/min rate)"**, click **Show models** to expand the panel. It lists every ASR, LLM, and TTS model bundled into your current rate, grouped by category.

    <Frame caption="The Add Funds panel with 'Your preferred models' expanded, showing ASR, LLM, and TTS models included in the flat rate">
      <img src="https://mintcdn.com/bolna-54a2d4fe/X4uxa31huXpE1D2q/images/pricing/preferred-models-panel.png?fit=max&auto=format&n=X4uxa31huXpE1D2q&q=85&s=0396a2384a7fccaf6938b22fcf3292a9" alt="Bolna Add Funds modal showing effective price of $0.060/min and the expanded preferred models panel listing ASR models nova-2, nova-3, azure, saarika:v2.5, saaras:v2.5; LLM models gpt-4.1-mini, gpt-4o-mini, azure/gpt-4.1-mini, azure/gpt-4o-mini, azure/ptu-gpt-4-1-mini; and TTS models eleven_turbo_v2_5, eleven_flash_v2_5, bulbul:v2, sonic-english, sonic-3" width="2008" height="1400" data-path="images/pricing/preferred-models-panel.png" />
    </Frame>
  </Step>

  <Step title="Cross-check against your agent config">
    Compare this list with the transcriber, LLM, and voice selected on your agent's [Audio Tab](/docs/agent-setup/audio-tab) and [LLM Tab](/docs/agent-setup/llm-tab). If your agent uses a model not on this list, expect variable pricing for that component.
  </Step>
</Steps>

***

## Current preferred model list

<Tabs>
  <Tab title="ASR (Speech-to-Text)">
    | Provider | Preferred models                           |
    | -------- | ------------------------------------------ |
    | Deepgram | `nova-2`, `nova-3`                         |
    | Azure    | `azure`                                    |
    | Sarvam   | `saarika:v2.5`, `saaras:v2.5`, `saaras:v4` |

    See the [Transcriber providers](/docs/providers/transcriber/deepgram) for setup details on each.
  </Tab>

  <Tab title="LLM">
    | Provider     | Preferred models                                                    |
    | ------------ | ------------------------------------------------------------------- |
    | OpenAI       | `gpt-4.1-mini`, `gpt-4o-mini`                                       |
    | Azure OpenAI | `azure/gpt-4.1-mini`, `azure/gpt-4o-mini`, `azure/ptu-gpt-4-1-mini` |

    See the [LLM providers](/docs/providers/llm-model/openai) for setup details on each.
  </Tab>

  <Tab title="TTS (Text-to-Speech)">
    | Provider   | Preferred models                                                     |
    | ---------- | -------------------------------------------------------------------- |
    | ElevenLabs | `eleven_turbo_v2_5`, `eleven_flash_v2_5`, `eleven_v3_conversational` |
    | Sarvam     | `bulbul:v2`                                                          |
    | Cartesia   | `sonic-3`, `sonic-3.5`, `sonic-preview`                              |

    See the [Voice providers](/docs/providers/voice/elevenlabs) for setup details on each.
  </Tab>
</Tabs>

<Note>
  Model names above match what's shown in the dashboard exactly (including casing and version suffixes like `:v2.5`). Selecting a similarly-named model from a different provider, or a newer/older version of the same model, may fall outside the preferred list.
</Note>

***

## Why does this matter for my bill?

<CardGroup cols={2}>
  <Card title="On the flat rate" icon="circle-check">
    Agent uses only preferred ASR + LLM + TTS models → you pay the flat per-minute rate plus telephony and platform fee. No separate Voice AI usage line items.
  </Card>

  <Card title="Off the flat rate" icon="circle-exclamation">
    Agent uses any non-preferred model → that component (STT, LLM, or TTS) is billed at variable, usage-based rates on top of telephony and platform fee. See the [call pricing breakdown](/docs/pricing/call-pricing#what-does-call-pricing-depend-on).
  </Card>
</CardGroup>

<Tip>
  You can mix and match: for example, run a preferred LLM with a non-preferred TTS voice. Only the non-preferred component is billed separately — everything else stays on the flat rate.
</Tip>

***

## Related

* [Call pricing breakdown](/docs/pricing/call-pricing) — how the flat rate, telephony, and platform fee fit together
* [Choosing providers](/docs/concepts/choosing-providers) — pick the right model for latency, language, and quality
* [Bring your own keys](/docs/pricing/call-pricing#how-can-i-reduce-my-voice-ai-costs) — connect your own provider accounts instead
* [Enterprise plan](/docs/enterprise/plan) — custom rates and preferred model lists for high-volume accounts
