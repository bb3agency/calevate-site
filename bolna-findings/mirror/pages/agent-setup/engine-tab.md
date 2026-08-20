> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Configure Voice AI Latency and Interruptions

> Fine-tune your Bolna Voice AI agent's performance. Configure transcription accuracy, interruption thresholds, response latency, and user detection.

## What is the Engine Tab?

The Engine Tab controls the core performance settings of your voice AI agent. Fine-tune transcription accuracy, interruption behavior, response timing, and user presence detection for optimal conversation quality.

<Frame caption="Engine Tab on Bolna Playground">
  <img src="https://mintcdn.com/bolna-54a2d4fe/uH9lQxF0tYMrhiL9/images/getting-started/agent-setup/engine-tab-overview.png?fit=max&auto=format&n=uH9lQxF0tYMrhiL9&q=85&s=63c8b55a298ae06cfe31845d07c92645" alt="Engine Tab showing Transcription & Interruptions, Response Latency, and User Online Detection settings" width="1024" height="884" data-path="images/getting-started/agent-setup/engine-tab-overview.png" />
</Frame>

***

## Configuration Options

### Transcription & Interruptions

Control how speech is captured and processed during conversations.

<Frame caption="Transcription & Interruptions Settings">
  <img src="https://mintcdn.com/bolna-54a2d4fe/uH9lQxF0tYMrhiL9/images/getting-started/agent-setup/engine-transcription.png?fit=max&auto=format&n=uH9lQxF0tYMrhiL9&q=85&s=aab8349fa3ee2720a75779e4aa23abaf" alt="Transcription settings showing Generate precise transcript toggle and Number of words to wait slider for interruption handling" width="1024" height="279" data-path="images/getting-started/agent-setup/engine-transcription.png" />
</Frame>

<CardGroup cols={2}>
  <Card title="Generate Precise Transcript" icon="file-lines">
    Enable for higher accuracy transcription. Essential for compliance and call analytics.
  </Card>

  <Card title="Interruption Threshold" icon="hand">
    Number of words to wait before considering user input as an interruption.
  </Card>
</CardGroup>

<Info>
  **Stopwords like "Stop", "Wait", "Hold On"** will always pause the agent immediately, regardless of the interruption threshold.
</Info>

***

### Response Latency

Configure how quickly your agent responds to user input.

<Frame caption="Response Latency Configuration">
  <img src="https://mintcdn.com/bolna-54a2d4fe/uH9lQxF0tYMrhiL9/images/getting-started/agent-setup/engine-latency.png?fit=max&auto=format&n=uH9lQxF0tYMrhiL9&q=85&s=363e05f719e87b2ab29ff642b5d7c31a" alt="Response latency settings showing Custom response rate with Endpointing and Linear delay sliders in milliseconds" width="1024" height="379" data-path="images/getting-started/agent-setup/engine-latency.png" />
</Frame>

| Setting               | Description                          | Impact                              |
| --------------------- | ------------------------------------ | ----------------------------------- |
| **Response Rate**     | Choose preset or Custom              | Balanced, Fast, or Custom timing    |
| **Endpointing (ms)**  | Wait time before generating response | Lower = faster but may cut off user |
| **Linear Delay (ms)** | Accounts for mid-sentence pauses     | Prevents premature responses        |

<Warning>
  **Lower latency isn't always better!** Setting values too low may cause the agent to interrupt users mid-sentence. Start with defaults and adjust based on testing.
</Warning>

<Tip>
  For **natural conversations**, use Endpointing around 200-300ms and Linear Delay around 400-500ms.
</Tip>

***

### User Online Detection

Detect when users go silent and automatically re-engage them.

<Frame caption="User Online Detection Settings">
  <img src="https://mintcdn.com/bolna-54a2d4fe/uH9lQxF0tYMrhiL9/images/getting-started/agent-setup/engine-user-detection.png?fit=max&auto=format&n=uH9lQxF0tYMrhiL9&q=85&s=eb95d47944ef6c04095a495a3ddea40e" alt="User Online Detection toggle with customizable message and invoke timer in seconds" width="1024" height="256" data-path="images/getting-started/agent-setup/engine-user-detection.png" />
</Frame>

<Steps>
  <Step title="Enable Detection">
    Toggle **User Online Detection** to check if the user is still on the call.
  </Step>

  <Step title="Set the Message">
    Customize the prompt (e.g., "Hey, are you still there?") with multi-language support.
  </Step>

  <Step title="Configure Timing">
    Set **Invoke message after (seconds)** to control when the check triggers.
  </Step>
</Steps>

<Tip>
  Set the timer between **8-15 seconds** to give users enough time to respond without seeming impatient.
</Tip>

***

## Best Practices

<CardGroup cols={2}>
  <Card title="Start with Defaults" icon="sliders">
    Use default settings initially and adjust based on real call feedback
  </Card>

  <Card title="Test Extensively" icon="flask">
    Make test calls to experience the timing and interruption handling
  </Card>

  <Card title="Consider Use Case" icon="lightbulb">
    Customer support may need longer pauses; sales may prefer faster responses
  </Card>

  <Card title="Monitor Analytics" icon="chart-line">
    Review call recordings to identify timing issues
  </Card>
</CardGroup>

***

## Next Steps

<CardGroup cols={2}>
  <Card title="Call Tab" icon="phone" href="/docs/agent-setup/call-tab">
    Configure telephony and call features
  </Card>

  <Card title="Audio Tab" icon="language" href="/docs/agent-setup/audio-tab">
    Set up voice and transcription providers
  </Card>

  <Card title="LLM Tab" icon="brain" href="/docs/agent-setup/llm-tab">
    Configure language model settings
  </Card>

  <Card title="Call History" icon="clock-rotate-left" href="/docs/agent-setup/call-history">
    Review call logs and recordings
  </Card>
</CardGroup>
