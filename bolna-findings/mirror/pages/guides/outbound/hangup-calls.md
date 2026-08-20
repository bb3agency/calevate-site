> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Hangup and Disconnect Bolna Voice AI calls

> Discover methods to disconnect live Bolna Voice AI calls. Implement time-based hangups, custom prompts, and personalized messages for seamless call termination.

## How to Configure Call Hangup

Bolna offers multiple ways to intelligently end voice calls based on user behavior and conversation context.

***

## Hangup Methods

<Tabs>
  <Tab title="Silence Detection">
    Set a `silence time` threshold (in seconds) for detecting user inactivity. If no audio is detected for the specified duration, the call disconnects automatically, preventing unnecessary call durations.

    <Frame caption="Disconnecting calls on silence">
      <img src="https://mintcdn.com/bolna-54a2d4fe/mJ1zPF3eB4Dyupzj/images/disconnect_calls_1.png?fit=max&auto=format&n=mJ1zPF3eB4Dyupzj&q=85&s=3d1b34eb1fc3790b374310256f2c658d" alt="Bolna Voice AI call hangup settings showing silence time threshold configuration" width="714" height="467" data-path="images/disconnect_calls_1.png" />
    </Frame>
  </Tab>

  <Tab title="Prompt-Based Hangup">
    Add a custom prompt that evaluates whether the conversation is complete. The LLM assesses the conversation context and decides when to end the call.

    <Frame caption="Custom prompt for intelligent call hangup">
      <img src="https://mintcdn.com/bolna-54a2d4fe/mJ1zPF3eB4Dyupzj/images/disconnect_calls_2.png?fit=max&auto=format&n=mJ1zPF3eB4Dyupzj&q=85&s=d00898d268c28b390198e547df5f269e" alt="Custom prompt configuration for intelligent call hangup in Bolna Voice AI" width="714" height="467" data-path="images/disconnect_calls_2.png" />
    </Frame>

    <Warning>
      Since this is prompt-based, it may not be 100% accurate. Tune the prompt based on your use case for best results.
    </Warning>

    **Example hangup prompt:**

    ```text hangup prompt example theme={"system"}
    You are an AI assistant determining if a conversation is complete. A conversation is complete if:

    1. The user explicitly says they want to stop (e.g., "That's all," "I'm done," "Goodbye," "thank you").
    2. The user seems satisfied, and their goal appears to be achieved.
    3. The user's goal appears achieved based on the conversation history, even without explicit confirmation.

    If none of these apply, the conversation is not complete.
    ```
  </Tab>
</Tabs>

***

## Personalized Hangup Message

Add a closing message spoken by the agent as the final message before the call ends. This accepts [dynamic context variables](/docs/using-context#custom-variables) using `{}` for a personalized closing statement.

<Frame caption="Adding a custom hangup message">
  <img src="https://mintcdn.com/bolna-54a2d4fe/mJ1zPF3eB4Dyupzj/images/disconnect_calls_4.png?fit=max&auto=format&n=mJ1zPF3eB4Dyupzj&q=85&s=fe4ed2c19095aaecf30c9c7a7d3d7f76" alt="Hangup message configuration showing custom closing statement with dynamic context variables" width="731" height="583" data-path="images/disconnect_calls_4.png" />
</Frame>

<Tip>
  Use variables like `{first_name}` in your hangup message for a personal touch, e.g., *"Thank you {first_name}, have a great day!"*
</Tip>

***

***

## Call Duration Limits

Set a maximum call duration (in seconds) for automatic termination. Once the limit is reached, the call ends automatically — a safety net against runaway calls.

<Frame caption="Configuring maximum call duration">
  <img src="https://mintcdn.com/bolna-54a2d4fe/mJ1zPF3eB4Dyupzj/images/disconnect_calls_3.png?fit=max&auto=format&n=mJ1zPF3eB4Dyupzj&q=85&s=5c2839af80f16d1f9c0fb6eba6149846" alt="Call duration limit settings in Bolna Voice AI showing maximum duration configuration for automatic termination" width="731" height="583" data-path="images/disconnect_calls_3.png" />
</Frame>

### Duration limits vs. hangup prompts

| Feature           | Duration Limits                   | Hangup Prompts                      |
| ----------------- | --------------------------------- | ----------------------------------- |
| **Trigger**       | Hard time-based cutoff            | Context-aware conversation analysis |
| **Accuracy**      | 100%, always triggers at set time | Prompt-dependent, may need tuning   |
| **Use case**      | Safety net for runaway calls      | Natural, intelligent call endings   |
| **Configuration** | Set duration in seconds           | Write a custom evaluation prompt    |

<Tip>
  **Use both together**: hangup prompts for natural conversation endings, duration limits as a hard safety net.
</Tip>

***

## Related Features

<CardGroup cols={3}>
  <Card title="Call Status List" icon="ballot-check" href="/docs/guides/post-call/list-phone-call-status">
    Monitor call statuses in real time
  </Card>

  <Card title="Hangup Status Codes" icon="phone-xmark" href="/docs/guides/post-call/list-phone-call-hangup-status">
    Understand who ended the call and why
  </Card>

  <Card title="Call Pricing" icon="dollar-sign" href="/docs/pricing/call-pricing">
    Understand how call duration affects cost
  </Card>
</CardGroup>
