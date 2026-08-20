> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Book Calendar Slots with Bolna Voice AI and Cal.com

> Learn how to book calendar appointments during live calls using Bolna Voice AI integrated with Cal.com. Automate appointment scheduling with your voice agent.

## What is Book Calendar Slots?

The **Book Calendar Slots** function allows your Voice AI agent to schedule appointments directly into your Cal.com calendar during live conversations. After a caller selects a time slot, your agent can book it instantly.

<Frame caption="Cal.com Configuration for Booking Appointments">
  <img src="https://mintcdn.com/bolna-54a2d4fe/bt7FxLUaXiKekHQM/images/tool-calling/book-calendar-slots-config.png?fit=max&auto=format&n=bt7FxLUaXiKekHQM&q=85&s=0268b3df664585d5046a66b0cad299b8" alt="Cal.com configuration modal showing Description prompt, Pre-tool message, API key, Select Events, and Choose Timezone fields" width="772" height="1024" data-path="images/tool-calling/book-calendar-slots-config.png" />
</Frame>

***

## Configuration Options

| Setting                  | Description                                                                                                               |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| **Description (Prompt)** | When to book - e.g., *"Use this tool to book an appointment with given details and save the appointment in the calendar"* |
| **Pre-tool Message**     | What agent says while booking - e.g., *"Just give me a moment, I'll be back with you"*                                    |
| **API Key**              | Your [Cal.com API key](https://app.cal.com/settings/developer/api-keys)                                                   |
| **Select Events**        | Choose event types from your Cal.com account (15 min, 30 min, etc.)                                                       |
| **Choose Timezone**      | Timezone for accurate slot booking                                                                                        |

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
    Click **"Select functions"** → choose **"Book appointment (using Cal.com)"**.
  </Step>

  <Step title="Enter API Key">
    Paste your Cal.com API key. Event types will load automatically once validated.
  </Step>

  <Step title="Select Event Type">
    Choose which event to book - *15 min meeting*, *30 min meeting*, or your custom events.
  </Step>

  <Step title="Set Timezone">
    Match your Cal.com event timezone for accurate booking.
  </Step>

  <Step title="Write Description">
    Add a clear trigger description - e.g., *"Book the appointment after the caller confirms their preferred time slot."*
  </Step>

  <Step title="Save Configuration">
    Click **Save configuration** to apply your settings.
  </Step>
</Steps>

***

## Example Conversation

<AccordionGroup>
  <Accordion title="Caller confirms appointment time" icon="message">
    **Caller**: "I'll take the 2 PM slot on Friday."

    **Agent**: "Perfect! Let me book that for you. Just give me a moment..."

    *Agent triggers book\_appointment function*

    **Agent**: "Done! I've booked your appointment for Friday at 2 PM. You'll receive a calendar invite shortly. Is there anything else I can help with?"
  </Accordion>
</AccordionGroup>

***

## Best Practices

<CardGroup cols={2}>
  <Card title="Use with Check Slots" icon="calendar-range">
    Combine with [Check Calendar Slots](/docs/tool-calling/fetch-calendar-slots) - first fetch availability, then book
  </Card>

  <Card title="Match Timezones" icon="clock">
    Ensure Bolna timezone matches Cal.com event timezone
  </Card>

  <Card title="Confirm Before Booking" icon="check">
    Have your agent confirm the slot with the caller before booking
  </Card>

  <Card title="Collect Required Info" icon="user">
    Ensure agent collects name and email before triggering the booking
  </Card>
</CardGroup>

<Tip>
  **Pro workflow:** First use **Check Calendar Slots** to show availability, then use **Book Calendar Slots** after the caller confirms their preferred time.
</Tip>

<Warning>
  **Test before deploying!** Verify appointments are being created correctly in your Cal.com calendar.
</Warning>

***

## Next Steps

<CardGroup cols={2}>
  <Card title="Check Calendar Slots" icon="calendar-range" href="/docs/tool-calling/fetch-calendar-slots">
    Query available slots before booking
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
