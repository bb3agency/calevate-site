> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Check Calendar Slots with Bolna and Cal.com

> Integrate Bolna Voice Agents with Cal.com to fetch real-time available calendar slots during live conversations to check appointment availability automatically.

## What is Check Calendar Slots?

The **Check Calendar Slots** function lets your Voice AI agent query available appointment slots from Cal.com in real-time. When callers ask about availability, your agent instantly fetches open slots and presents options.

<Frame caption="Cal.com Configuration for Check Slot Availability">
  <img src="https://mintcdn.com/bolna-54a2d4fe/zRZRzNcgm9P0_dMD/images/tool-calling/fetch_calendar_slots.png?fit=max&auto=format&n=zRZRzNcgm9P0_dMD&q=85&s=71ac9874cbc6a234b4062fd76d640d01" alt="Cal.com configuration modal showing Description, Pre-tool message, API key, Select Events, and Choose Timezone fields" width="1094" height="1370" data-path="images/tool-calling/fetch_calendar_slots.png" />
</Frame>

***

## Configuration Options

| Setting                  | Description                                                                                |
| ------------------------ | ------------------------------------------------------------------------------------------ |
| **Description (Prompt)** | When to check availability - e.g., *"Fetch available slots before booking an appointment"* |
| **Pre-tool Message**     | What agent says while fetching - e.g., *"Just a moment, let me check our availability"*    |
| **API Key**              | Your [Cal.com API key](https://app.cal.com/settings/developer/api-keys)                    |
| **Select Events**        | Choose event types from your Cal.com account (15 min, 30 min, etc.)                        |
| **Choose Timezone**      | Timezone for accurate slot times                                                           |

<Info>
  **Select Events** and **Choose Timezone** dropdowns appear only after entering a valid Cal.com API key.
</Info>

***

## How to Set Up

<Steps>
  <Step title="Open Tools Tab">
    Navigate to [Tools Tab](/docs/agent-setup/tools-tab) in your agent configuration.
  </Step>

  <Step title="Select the Function">
    Click **"Select functions"** → choose **"Check slot availability (using Cal.com)"**.
  </Step>

  <Step title="Enter API Key">
    Paste your Cal.com API key. Event types will load automatically once validated.
  </Step>

  <Step title="Select Event Type">
    Choose which event to check - *15 min meeting*, *30 min meeting*, or your custom events.
  </Step>

  <Step title="Set Timezone">
    Match your Cal.com event timezone for accurate time communication.
  </Step>

  <Step title="Write Description">
    Add a clear trigger description - e.g., *"Check available slots when caller wants to schedule a meeting."*
  </Step>
</Steps>

***

## Example Conversation

<AccordionGroup>
  <Accordion title="Caller asks about availability" icon="message">
    **Caller**: "Hi, I'd like to schedule a meeting with your team."

    **Agent**: "Of course! Let me check our available slots for you."

    *Agent triggers check\_availability\_of\_slots function*

    **Agent**: "I have openings tomorrow at 10 AM, 2 PM, and 4 PM. We also have slots on Friday at 11 AM and 3 PM. Which works best for you?"
  </Accordion>
</AccordionGroup>

***

## Best Practices

<CardGroup cols={2}>
  <Card title="Detailed Descriptions" icon="bullseye">
    Use *"Fetch available slots when caller wants to schedule or asks about times"* instead of just "Check availability"
  </Card>

  <Card title="Match Timezones" icon="clock">
    Ensure Bolna timezone matches Cal.com event timezone to avoid confusion
  </Card>

  <Card title="Add Pre-tool Message" icon="comment">
    Set a friendly message like *"Just a moment..."* so callers know to wait
  </Card>

  <Card title="Test Before Deploying" icon="flask">
    Verify slots are being fetched correctly with test calls
  </Card>
</CardGroup>

<Warning>
  **Timezone matters!** Mismatched timezones cause the agent to communicate incorrect times to callers.
</Warning>

***

## Next Steps

<CardGroup cols={2}>
  <Card title="Book Calendar Slots" icon="calendar-check" href="/docs/tool-calling/book-calendar-slots">
    After checking availability, book the appointment
  </Card>

  <Card title="Custom Functions" icon="code" href="/docs/tool-calling/custom-function-calls">
    Build your own API integrations
  </Card>

  <Card title="Transfer Calls" icon="phone-arrow-right" href="/docs/tool-calling/transfer-calls">
    Route calls to human agents
  </Card>

  <Card title="Tools Tab Guide" icon="function" href="/docs/agent-setup/tools-tab">
    Complete guide to configuring functions
  </Card>
</CardGroup>
