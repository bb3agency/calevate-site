> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Configure Telephony, Noise, and Call Timing for Voice AI

> Set up telephony providers like Plivo and Twilio, enable noise cancellation, voicemail detection, DTMF keypad input, ambient noise, and outbound call timing restrictions in the Bolna Call Tab.

## What is the Call Tab?

The Call Tab is where you configure how your agent handles phone calls. Set up your telephony provider, enable call features like noise cancellation and voicemail detection, and manage call timing and hangup behavior.

<Frame caption="Call Tab showing Call Configuration and Outbound call timing restrictions">
  <img src="https://mintcdn.com/bolna-54a2d4fe/mQ_HSrxgFv467vUr/images/getting-started/agent-setup/call-tab-full.png?fit=max&auto=format&n=mQ_HSrxgFv467vUr&q=85&s=d60a60b32b6b46d22795ec944204735c" alt="Call Tab showing Plivo telephony provider, Noise Cancellation at 70, Voicemail Detection, Keypad Input DTMF, Auto Reschedule toggles, and Outbound call timing restrictions with 9 AM to 9 PM window" width="1480" height="944" data-path="images/getting-started/agent-setup/call-tab-full.png" />
</Frame>

***

## Configuration Options

### Telephony Provider & Call Features

Configure your telephony provider and toggle powerful call capabilities.

<Frame caption="Telephony Provider & Call Features">
  <img src="https://mintcdn.com/bolna-54a2d4fe/uH9lQxF0tYMrhiL9/images/getting-started/agent-setup/call-telephony.png?fit=max&auto=format&n=uH9lQxF0tYMrhiL9&q=85&s=35144af3cd868ff3a7d671982fdebf67" alt="Telephony Provider dropdown, Noise Cancellation, Voicemail Detection, Keypad Input DTMF, and Auto Reschedule toggles" width="1024" height="289" data-path="images/getting-started/agent-setup/call-telephony.png" />
</Frame>

<CardGroup cols={2}>
  <Card title="Noise Cancellation" icon="volume-slash">
    Filter background noise for clearer calls (adjustable intensity)
  </Card>

  <Card title="Voicemail Detection" icon="voicemail">
    Detect voicemail systems to avoid awkward messages
  </Card>

  <Card title="Keypad Input (DTMF)" icon="keyboard">
    Accept touch-tone input for IVR-style menus
  </Card>

  <Card title="Auto Reschedule" icon="calendar-check">
    Automatically retry failed calls later
  </Card>
</CardGroup>

<Tip>
  Connect your own telephony provider in [Providers](/docs/getting-started/providers) for more control and cost savings.
</Tip>

***

### Ambient Noise

Add background ambient noise to your calls for a more natural, human-like experience. Ambient noise is available for **Plivo** and **Vobiz** telephony providers.

<Frame caption="Ambient Noise Configuration">
  <img src="https://mintcdn.com/bolna-54a2d4fe/KcE1cPEukmPjW9QA/images/getting-started/agent-setup/call-ambient-noise.png?fit=max&auto=format&n=KcE1cPEukmPjW9QA&q=85&s=d248e5e75127268377e2b6bea351d718" alt="Ambient Noise dropdown with coffee-shop, office-ambience, and call-center options" width="523" height="250" data-path="images/getting-started/agent-setup/call-ambient-noise.png" />
</Frame>

Bolna supports both **preset** and **custom** ambient noise tracks. Select a preset or upload your own custom track to use as background noise during calls.

#### Preset Tracks

Three preset tracks are available to all users out of the box:

| Track               | Description                                    |
| ------------------- | ---------------------------------------------- |
| **Coffee Shop**     | Background sounds of a coffee shop environment |
| **Office Ambience** | Subtle office background noise                 |
| **Call Center**     | Call center ambient sounds                     |

Set ambient noise to **None** to disable it (default).

#### Custom Tracks

You can upload your own custom ambient noise tracks for a personalized experience:

* **Supported formats**: `wav`, `mp3`
* **Maximum file size**: 10 MB
* You can upload, list, and delete your custom tracks from the dashboard or via the API
* Custom tracks are private to your account, while presets are available to everyone

<Info>
  Ambient noise is only supported with **Plivo** and **Vobiz** telephony providers.
</Info>

***

### Final Call Message

Configure the last message your agent says before disconnecting.

<Frame caption="Final Call Message Configuration">
  <img src="https://mintcdn.com/bolna-54a2d4fe/uH9lQxF0tYMrhiL9/images/getting-started/agent-setup/call-final-message.png?fit=max&auto=format&n=uH9lQxF0tYMrhiL9&q=85&s=e55f08504d32d48f77a2b76ce4357fef" alt="Final Call Message section with language selector and message input field" width="1024" height="257" data-path="images/getting-started/agent-setup/call-final-message.png" />
</Frame>

<Steps>
  <Step title="Select Language">
    Choose the language for your final message (supports multi-language).
  </Step>

  <Step title="Write Your Message">
    Enter a warm, professional closing (e.g., "Thank you for your time. Goodbye!")
  </Step>

  <Step title="Add Languages (Optional)">
    Click **+ Add** to include final messages in other languages.
  </Step>
</Steps>

<Tip>
  A warm, professional final message leaves a positive lasting impression on callers.
</Tip>

***

### Call Management

Configure how and when calls should end.

<Frame caption="Call Management Settings">
  <img src="https://mintcdn.com/bolna-54a2d4fe/uH9lQxF0tYMrhiL9/images/getting-started/agent-setup/call-management.png?fit=max&auto=format&n=uH9lQxF0tYMrhiL9&q=85&s=6db80ffd6532904e439e9f4c88983133" alt="Call Management section with Hangup on User Silence and Total Call Timeout sliders" width="1024" height="211" data-path="images/getting-started/agent-setup/call-management.png" />
</Frame>

| Setting                    | Description                            | Recommended                                |
| -------------------------- | -------------------------------------- | ------------------------------------------ |
| **Hangup on User Silence** | Auto-hangup after X seconds of silence | 6-10 seconds                               |
| **Total Call Timeout**     | Maximum call duration in seconds       | 300s (5 min) for support, higher for sales |

<Warning>
  **Set reasonable timeouts** to manage costs and prevent stuck calls. Very long calls can indicate issues or abandoned calls.
</Warning>

***

### Outbound Call Timing Restrictions

Restrict outbound calls to a specific time window. This is **off by default**. Toggle it on to set an allowed calling window.

<Frame caption="Outbound call timing restrictions toggled on with a 9:00 AM to 9:00 PM allowed window">
  <img src="https://mintcdn.com/bolna-54a2d4fe/mQ_HSrxgFv467vUr/images/getting-started/agent-setup/call-outbound-restrictions.png?fit=max&auto=format&n=mQ_HSrxgFv467vUr&q=85&s=2774c3ec3309e7e86db2af37fb9a86dc" alt="Outbound call timing restrictions section with toggle enabled and Allowed Time Window set from 9:00 AM to 9:00 PM" width="1454" height="324" data-path="images/getting-started/agent-setup/call-outbound-restrictions.png" />
</Frame>

| Field                   | Description                                                                                                                            |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| **Allowed Time Window** | Set a start and end time (e.g., 9:00 AM to 9:00 PM). Calls outside this window are automatically rescheduled to the next allowed time. |

The time window is validated against the **recipient's local timezone**, detected automatically from their phone number. For example, a 9 AM start means 9 AM in the recipient's timezone, not yours.

<Warning>
  Many regions have laws restricting when you can make outbound calls. Enable timing restrictions to stay compliant with local regulations.
</Warning>

<Info>
  You can also configure call timing restrictions via the API and bypass them for urgent calls. See the full [Calling Guardrails](/docs/guides/outbound/calling-guardrails) guide for details.
</Info>

***

## Next Steps

<CardGroup cols={2}>
  <Card title="Calling Guardrails" icon="clock" href="/docs/guides/outbound/calling-guardrails">
    Set allowed hours, bypass rules, and compliance
  </Card>

  <Card title="Engine Tab" icon="gear" href="/docs/agent-setup/engine-tab">
    Configure latency and interruptions
  </Card>

  <Card title="Tools Tab" icon="code" href="/docs/agent-setup/tools-tab">
    Add function tools and APIs
  </Card>

  <Card title="Telephony Providers" icon="phone" href="/docs/getting-started/providers">
    Connect Twilio, Plivo, or Exotel
  </Card>
</CardGroup>
