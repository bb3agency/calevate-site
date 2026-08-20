> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Bolna AI Updates for January, 2026

> Explore the latest features, improvements, and API updates introduced in January 2026 for Bolna Voice AI agents.

<Update label="27th Jan, 2026">
  ## Vobiz Telephony Integration

  * Introducing native Vobiz integration for Voice AI calling in India and global markets
  * Connect your existing Vobiz account securely to Bolna for complete control over your telephony infrastructure
  * Make outbound AI calls and receive inbound calls using your own Vobiz phone numbers
  * Support for both dashboard-based calling and programmatic API integration
  * Learn more in the [Vobiz integration documentation](/docs/vobiz)
</Update>

<Update label="26th Jan, 2026">
  ## Auto-Retry for Failed Calls

  Automatically retry calls that fail due to no-answer, busy signals, or errors. Configure retry attempts, delays, and which statuses trigger retries.

  **Key features:**

  * Up to 3 automatic retry attempts
  * Configurable delays between retries
  * Works with single calls and batch campaigns
  * Webhook notifications include retry status

  Learn more in the [auto-retry documentation](/docs/guides/outbound/auto-retry).
</Update>

<Update label="26th Jan, 2026">
  ## IVR Support for Inbound Calls

  Bolna now supports IVR (Interactive Voice Response) for Plivo inbound calls. Route callers to different Voice AI agents based on their menu selections.

  **Key features:**

  * **Menu steps** - Present options and route based on digit pressed
  * **Collect steps** - Gather multi-digit input (account numbers, PINs)
  * **Multi-agent routing** - Different agent per menu option
  * **Conditional branching** - Build complex flows with language selection
  * **Context passing** - All collected data sent to agent as context

  Configure IVR via the `/inbound/setup` API by adding `ivr_config` to your request. Learn more in the [IVR documentation](/docs/guides/inbound/ivr-inbound-calls).

  ```json theme={"system"}
  {
    "ivr_config": {
      "enabled": true,
      "voice": "Polly.Aditi",
      "welcome_message": "Welcome to Acme Corp.",
      "steps": [
        {
          "step_id": "department",
          "type": "menu",
          "prompt": "Press 1 for Sales. Press 2 for Support.",
          "field_name": "department",
          "options": [
            {"digit": "1", "label": "Sales", "agent_id": "sales-agent-id"},
            {"digit": "2", "label": "Support", "agent_id": "support-agent-id"}
          ]
        }
      ]
    }
  }
  ```
</Update>

<Update label="6th Jan, 2026">
  ## Multilingual Message Auto Switching

  Bolna now automatically detects the language your users speak and adapts system messages accordingly. Bolna agents analyze conversation patterns and intelligently switche messages to match the detected language.

  Bolna agents are now able to identify the dominant language while handling real-world conversational scenarios where users mix languages. This ensures messages are delivered in the language users actually prefer for substantive communication.

  **Currently supported message types:**

  * **User online check message** - The "are you still there?" prompt when checking if users are on the call
  * **Call hangup message** - Closing messages when the agent ends a call
  * **Pre-function call message** - Brief wait messages while executing custom tools or API calls

  Configure multilingual variants using language codes (e.g., `en`, `hi`, `ta`, etc) and Bolna handles the rest. Learn more in the [language detection documentation](/docs/customizations/auto-switch-multilingual-messages).
</Update>

<Update label="5th Jan, 2026">
  ## Noise Cancellation During Calls

  Bolna now supports noise cancellation during calls, providing clearer audio quality by filtering out background noise for both the agent and the caller.

  <Frame caption="Noise cancellation level">
    <img src="https://mintcdn.com/bolna-54a2d4fe/e3luLN3vWpCacagZ/images/changelog/5_january_2026_noise_cancellation.png?fit=max&auto=format&n=e3luLN3vWpCacagZ&q=85&s=b14c7b46561f4f11ad6b57143f548982" alt="Noise cancellation toggle to choose the level on Bolna platform" width="1736" height="762" data-path="images/changelog/5_january_2026_noise_cancellation.png" />
  </Frame>
</Update>

<Update label="2nd Jan, 2026">
  ## Auto Reschedule

  Automatically reschedule calls when a user asks to be called at a specific time. The agent will intelligently detect scheduling requests and handle the rescheduling process seamlessly.

  <Frame caption="Auto reschedule toggle">
    <img src="https://mintcdn.com/bolna-54a2d4fe/e3luLN3vWpCacagZ/images/changelog/2_january_2026_auto_reschedule.png?fit=max&auto=format&n=e3luLN3vWpCacagZ&q=85&s=13c9f896167a8a823f89bf247353aff9" alt="Toggle to automatically reschedule calls on Bolna platform" width="1736" height="342" data-path="images/changelog/2_january_2026_auto_reschedule.png" />
  </Frame>
</Update>
