> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# DTMF (Keypad Input)

> Let callers enter digits on their phone keypad and have your voice agent respond to the input.

## What is DTMF?

DTMF (Dual-Tone Multi-Frequency) is the system behind phone keypad input: the tones produced when a caller presses a digit key (0-9, `*`, `#`).

When enabled, digit presses from the caller are captured and sent to the agent as a text message, which the LLM can read and respond to just like spoken input.

## When to use it

DTMF is useful any time you want callers to enter structured numeric input without speaking it:

* **PIN or OTP verification** -- "Please enter your 6-digit OTP followed by #"
* **Account or order number lookup** -- "Enter your account number and press #"
* **Phone number capture** -- collecting a callback number during a call
* **Confirmation flows** -- "Press 1 to confirm, 2 to cancel"
* **Sensitive input** -- when callers are uncomfortable speaking a number aloud (e.g. a password or card number)

DTMF works alongside speech. A caller can still speak normally between keypad entries.

<Info>
  For branching menu flows ("press 1 for sales, press 2 for support"), use [IVR Inbound Calls](/docs/guides/inbound/ivr-inbound-calls) instead. It handles menu routing natively without an LLM.
</Info>

## Telephony support

| Provider         | Support                 |
| ---------------- | ----------------------- |
| Plivo            | Supported               |
| Twilio           | Supported               |
| SIP Trunk (BYOT) | Currently not supported |
| Exotel           | Currently not supported |
| Vobiz            | Currently not supported |

## Enabling DTMF

### From the dashboard

Toggle on **Keypad Input (DTMF)** in the **Call Tab** of your agent.

<Frame caption="Telephony Provider and Call Features">
  <img src="https://mintcdn.com/bolna-54a2d4fe/uH9lQxF0tYMrhiL9/images/getting-started/agent-setup/call-telephony.png?fit=max&auto=format&n=uH9lQxF0tYMrhiL9&q=85&s=35144af3cd868ff3a7d671982fdebf67" alt="Call tab showing the Keypad Input DTMF toggle" width="1024" height="289" data-path="images/getting-started/agent-setup/call-telephony.png" />
</Frame>

### Via the API

Set `dtmf_enabled: true` inside `task_config` when creating or updating an agent:

```json theme={"system"}
{
  "task_config": {
    "dtmf_enabled": true
  }
}
```

## How it works

1. The agent asks the caller to enter digits and press `#`.
2. The caller presses keys on their keypad.
3. Bolna accumulates the digits until `#` is pressed.
4. The digits are delivered to the agent as: `dtmf_number: <digits>`
5. The agent responds to the input.

<Info>
  `#` is the termination key. The agent only receives the input after the caller presses it. The `#` itself is not included in the value.
</Info>

## Writing the prompt

Tell callers to press `#` after their entry, and tell the agent what to do when it sees a `dtmf_number:` message.

**Example prompt snippet:**

```
When you need the caller's phone number, say:
"Please enter your phone number on your keypad and press the hash key when you are done."

When you receive a message starting with "dtmf_number:", the digits that follow are what the caller entered.
Read them back to confirm and proceed accordingly.
```

**What the agent receives:**

```
dtmf_number: 9876543210
```

The agent treats this like any other message in the conversation. It can confirm the value, use it in a tool call, or move to the next step based on it.

## Next Steps

<CardGroup cols={2}>
  <Card title="IVR Inbound Calls" icon="list-tree" href="/docs/guides/inbound/ivr-inbound-calls">
    Menu-based call routing with keypad navigation
  </Card>

  <Card title="Call Tab" icon="phone" href="/docs/agent-setup/call-tab">
    All call configuration options
  </Card>
</CardGroup>
