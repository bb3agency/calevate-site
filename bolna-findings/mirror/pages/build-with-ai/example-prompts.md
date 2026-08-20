> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Example Prompts

> Real prompts you can ask your AI assistant, and the Bolna Skill each one triggers.

Once [Bolna Skills are installed and set up](/docs/build-with-ai/setup), just ask your AI assistant what you need in plain English. The right skill loads automatically based on your request.

<AccordionGroup>
  <Accordion title="Create an agent" icon="robot">
    ```
    Create a Hindi voice agent for appointment booking using Plivo and Sarvam.
    ```

    Uses the `create-agent` skill — configures LLM, TTS, STT, telephony, and system prompt in one shot.
  </Accordion>

  <Accordion title="Make a test call" icon="phone-arrow-up-right">
    ```
    Place a test call to +91XXXXXXXXXX and pass customer_name: Priya as user_data.
    ```

    Uses the `make-call` skill — places an outbound call with dynamic variables.
  </Accordion>

  <Accordion title="Run a batch campaign" icon="list-check">
    ```
    Upload leads.csv as a Bolna batch campaign and monitor it until done.
    ```

    Uses the `create-batch` skill — creates a CSV-driven campaign with scheduling and monitoring.
  </Accordion>

  <Accordion title="Debug a call" icon="bug">
    ```
    My Bolna call has a long silence before each response — debug it.
    ```

    Uses the `debug-bolna-calls` skill — runs a symptom-to-fix diagnostic using execution logs.
  </Accordion>

  <Accordion title="Build a graph agent" icon="diagram-project">
    ```
    Build a graph agent for payment confirmation with real-time event injection.
    ```

    Uses the `bolna-graph-agents` skill — creates node-based call flows with deterministic routing.
  </Accordion>

  <Accordion title="Set up inbound IVR" icon="phone-arrow-down-left">
    ```
    Set up an inbound IVR that routes sales, support, and billing to three different agents.
    ```

    Uses the `setup-inbound` skill — wires phone numbers to agents with IVR menus and caller identification.
  </Accordion>
</AccordionGroup>

Looking for the skill behind any of these? See the full [Skills Reference](/docs/build-with-ai/skills-reference).
