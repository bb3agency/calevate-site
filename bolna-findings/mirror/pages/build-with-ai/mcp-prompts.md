> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Prompt Cheatsheet

> Copy-paste prompts for common tasks with the Bolna MCP server.

Paste any of these into a connected client. Each one links to the tool it triggers — see the [Tool List](/docs/build-with-ai/mcp-tool-list) for the full schema.

## Agents

<AccordionGroup>
  <Accordion title="List your agents" icon="list">
    ```
    List my Bolna agents.
    ```

    Triggers `list_agents`.
  </Accordion>

  <Accordion title="Get an agent's config" icon="robot">
    ```
    Show me the full config for agent <agent_id>.
    ```

    Triggers `get_agent`.
  </Accordion>

  <Accordion title="Create an agent" icon="circle-plus">
    ```
    Create a Hindi appointment-booking agent using Plivo and Sarvam TTS,
    with a welcome message that greets the caller by name.
    ```

    Triggers `create_agent`.
  </Accordion>

  <Accordion title="Update an agent" icon="pen-to-square">
    ```
    Update agent <agent_id>'s welcome message to mention our new return policy.
    ```

    Triggers `update_agent` — most clients ask you to confirm first.
  </Accordion>

  <Accordion title="Cancel an agent's queued calls" icon="ban">
    ```
    Cancel every queued call for agent <agent_id> — we're pausing the campaign.
    ```

    Triggers `stop_agent_queued_calls`.
  </Accordion>

  <Accordion title="Delete an agent" icon="trash">
    ```
    Delete the test agent I created yesterday.
    ```

    Triggers `delete_agent` — irreversible, most clients ask you to confirm first.
  </Accordion>
</AccordionGroup>

## Calls & executions

<AccordionGroup>
  <Accordion title="Place a call" icon="phone-arrow-up-right">
    ```
    Call +91XXXXXXXXXX using my sales agent and pass customer_name: Priya as context.
    ```

    Triggers `start_outbound_call` — spends account balance, most clients ask you to confirm first.
  </Accordion>

  <Accordion title="Cancel a scheduled call" icon="phone-slash">
    ```
    Cancel the call I scheduled for execution <execution_id>.
    ```

    Triggers `stop_call`.
  </Accordion>

  <Accordion title="Review recent calls" icon="clock-rotate-left">
    ```
    Show me agent <agent_id>'s last 20 calls from this week.
    ```

    Triggers `list_agent_executions`.
  </Accordion>

  <Accordion title="Pull a transcript" icon="file-waveform">
    ```
    Pull the transcript and cost for execution <execution_id>.
    ```

    Triggers `get_execution`.
  </Accordion>

  <Accordion title="Debug a slow or failed call" icon="stethoscope">
    ```
    Pull the raw pipeline logs for execution <execution_id> and tell me
    whether the transcriber, LLM, or synthesizer was slow.
    ```

    Triggers `get_execution_raw_logs`.
  </Accordion>
</AccordionGroup>

## Batches

<AccordionGroup>
  <Accordion title="Create a batch" icon="layer-group">
    ```
    Create a batch on my collections agent from this CSV of recipients.
    ```

    Triggers `create_batch`.
  </Accordion>

  <Accordion title="Schedule a batch" icon="calendar-clock">
    ```
    Schedule batch <batch_id> to start calling at 9am tomorrow.
    ```

    Triggers `schedule_batch` — starts real calls and spends balance, most clients ask you to confirm first.
  </Accordion>

  <Accordion title="Check batch status" icon="chart-simple">
    ```
    What's the status and contact count for batch <batch_id>?
    ```

    Triggers `get_batch`.
  </Accordion>

  <Accordion title="Review a batch's calls" icon="list-check">
    ```
    List every execution in batch <batch_id> and tell me how many failed.
    ```

    Triggers `list_batch_executions`.
  </Accordion>

  <Accordion title="Stop a running batch" icon="hand">
    ```
    Stop batch <batch_id> — we found an error in the recipient list.
    ```

    Triggers `stop_batch`.
  </Accordion>

  <Accordion title="Delete a batch" icon="trash">
    ```
    Delete batch <batch_id>, it was a test run.
    ```

    Triggers `delete_batch` — irreversible, most clients ask you to confirm first.
  </Accordion>
</AccordionGroup>

## Dispositions

<AccordionGroup>
  <Accordion title="List an agent's dispositions" icon="list">
    ```
    What dispositions are configured on agent <agent_id>?
    ```

    Triggers `list_dispositions`.
  </Accordion>

  <Accordion title="Add a disposition" icon="circle-plus">
    ```
    Add a disposition to agent <agent_id> that captures appointment_time
    as a timestamp from the call.
    ```

    Triggers `create_disposition`.
  </Accordion>

  <Accordion title="Add several at once" icon="layer-group">
    ```
    Add dispositions for lead_qualified (boolean), sentiment (pre-defined:
    positive/neutral/negative), and consent_captured (boolean) to agent <agent_id>.
    ```

    Triggers `bulk_create_dispositions`.
  </Accordion>

  <Accordion title="Test dispositions against a transcript" icon="flask">
    ```
    Run agent <agent_id>'s dispositions against this sample transcript
    and show me what it would extract.
    ```

    Triggers `test_dispositions`.
  </Accordion>

  <Accordion title="Update or remove a disposition" icon="pen-to-square">
    ```
    Update the sentiment disposition on agent <agent_id> to also flag "mixed".
    ```

    Triggers `update_disposition`. Ask to delete one and it triggers `delete_disposition` instead — irreversible, most clients ask you to confirm first.
  </Accordion>
</AccordionGroup>

## Knowledgebase (RAG)

<AccordionGroup>
  <Accordion title="Create a knowledgebase from a URL" icon="book-open">
    ```
    Create a knowledgebase from https://www.example.com/faq and let me
    know when it's done processing.
    ```

    Chains `create_knowledgebase` → `get_knowledgebase` to check status.
  </Accordion>

  <Accordion title="List and inspect knowledgebases" icon="list">
    ```
    List my knowledgebases and show me the status of the one named "FAQ".
    ```

    Chains `list_knowledgebases` → `get_knowledgebase`.
  </Accordion>

  <Accordion title="Delete a knowledgebase" icon="trash">
    ```
    Delete the "old-pricing" knowledgebase, it's out of date.
    ```

    Triggers `delete_knowledgebase` — irreversible, most clients ask you to confirm first.
  </Accordion>
</AccordionGroup>

## Phone numbers & inbound

<AccordionGroup>
  <Accordion title="List phone numbers" icon="phone">
    ```
    What phone numbers do I have, and which agent is each one linked to?
    ```

    Triggers `list_phone_numbers`.
  </Accordion>

  <Accordion title="Search for a number to buy" icon="magnifying-glass">
    ```
    Find me available US numbers with area code 415.
    ```

    Triggers `search_phone_numbers`.
  </Accordion>

  <Accordion title="Buy a number" icon="cart-shopping">
    ```
    Buy that first number you found.
    ```

    Triggers `buy_phone_number` — spends account balance (\$5/month), most clients ask you to confirm first.
  </Accordion>

  <Accordion title="Route inbound calls to an agent" icon="phone-volume">
    ```
    Set up my support agent to answer inbound calls on +1XXXXXXXXXX.
    ```

    Triggers `setup_inbound_agent`.
  </Accordion>

  <Accordion title="Unlink an inbound number" icon="link-slash">
    ```
    Remove the inbound routing on +1XXXXXXXXXX, we're decommissioning that line.
    ```

    Triggers `unlink_inbound_agent`.
  </Accordion>

  <Accordion title="Delete a number" icon="trash">
    ```
    Delete the phone number +1XXXXXXXXXX, we don't need it anymore.
    ```

    Triggers `delete_phone_number` — irreversible, most clients ask you to confirm first.
  </Accordion>
</AccordionGroup>

## SIP trunks

<AccordionGroup>
  <Accordion title="Create a trunk" icon="server">
    ```
    Create a SIP trunk pointed at my Twilio Elastic SIP termination URI,
    using IP-based auth.
    ```

    Triggers `create_sip_trunk`.
  </Accordion>

  <Accordion title="List and inspect trunks" icon="list">
    ```
    List my SIP trunks and show me the config for the one named "primary".
    ```

    Chains `list_sip_trunks` → `get_sip_trunk`.
  </Accordion>

  <Accordion title="Attach or remove a DID" icon="phone">
    ```
    Add +1XXXXXXXXXX to my "primary" trunk.
    ```

    Triggers `add_trunk_number`. Ask to remove one and it triggers `remove_trunk_number` instead.
  </Accordion>

  <Accordion title="List numbers on a trunk" icon="list-check">
    ```
    What numbers are attached to my "primary" trunk?
    ```

    Triggers `list_trunk_numbers`.
  </Accordion>

  <Accordion title="Delete a trunk" icon="trash">
    ```
    Delete the SIP trunk named "old-vendor".
    ```

    Triggers `delete_sip_trunk` — irreversible, most clients ask you to confirm first.
  </Accordion>
</AccordionGroup>

## Sub-accounts

<AccordionGroup>
  <Accordion title="Create a sub-account" icon="circle-plus">
    ```
    Create a sub-account called "Acme Corp".
    ```

    Triggers `create_sub_account`.
  </Accordion>

  <Accordion title="List sub-accounts" icon="list">
    ```
    List my sub-accounts.
    ```

    Triggers `list_sub_accounts`.
  </Accordion>

  <Accordion title="Switch to a sub-account for one request" icon="right-left">
    ```
    Get the API key for my "Acme Corp" sub-account, then use it to list
    that sub-account's agents.
    ```

    Chains `list_sub_accounts` → `list_agents` with the returned key passed as `api_key` — no reconnecting needed. See [Calling tools with a different account](/docs/build-with-ai/mcp-tool-list#calling-tools-with-a-different-account).
  </Accordion>

  <Accordion title="Check a sub-account's usage" icon="chart-simple">
    ```
    What did the "Acme Corp" sub-account spend this month?
    ```

    Triggers `get_sub_account_usage`.
  </Accordion>

  <Accordion title="Check usage across all sub-accounts" icon="chart-line">
    ```
    Show me usage for all of my sub-accounts.
    ```

    Triggers `get_all_sub_accounts_usage`.
  </Accordion>

  <Accordion title="Delete a sub-account" icon="trash">
    ```
    Delete the "Acme Corp" sub-account, the engagement ended.
    ```

    Triggers `delete_sub_account` — irreversible, most clients ask you to confirm first.
  </Accordion>
</AccordionGroup>

## Voice & providers

<AccordionGroup>
  <Accordion title="See connected providers" icon="plug">
    ```
    What telephony, LLM, and voice providers are connected to my account?
    ```

    Triggers `list_providers`.
  </Accordion>

  <Accordion title="Browse voices" icon="microphone">
    ```
    What TTS providers and voices do I have available? I want a
    calm female Hindi voice.
    ```

    Chains `list_tts_providers` → `list_voices`.
  </Accordion>

  <Accordion title="Disconnect a provider" icon="plug-circle-xmark">
    ```
    Remove my old ElevenLabs connection.
    ```

    Triggers `remove_provider` — breaks any agent still using it, most clients ask you to confirm first.
  </Accordion>
</AccordionGroup>

## Violations

<AccordionGroup>
  <Accordion title="Review flagged calls" icon="triangle-exclamation">
    ```
    List any pending violations on my account.
    ```

    Triggers `list_violations`. Ask for a different status ("accepted", "rejected", "submitted") and it filters accordingly.
  </Accordion>
</AccordionGroup>

## Account

<AccordionGroup>
  <Accordion title="Check balance and limits" icon="wallet">
    ```
    What's my current wallet balance and concurrency limit?
    ```

    Triggers `get_user_info`.
  </Accordion>
</AccordionGroup>

## Documentation

<AccordionGroup>
  <Accordion title="Find a doc page" icon="magnifying-glass">
    ```
    How do I set up a webhook in Bolna?
    ```

    Triggers `search_docs`.
  </Accordion>

  <Accordion title="Read a doc page" icon="file-lines">
    ```
    Show me the full content of the MCP tool list doc.
    ```

    Chains `search_docs` → `get_doc`.
  </Accordion>
</AccordionGroup>

## Chained, multi-step

These touch more than one tool in a single request — the assistant chains the lookups itself.

<AccordionGroup>
  <Accordion title="Chain a diagnostic across calls" icon="magnifying-glass-chart">
    ```
    Check agent <agent_id>'s last 10 calls — for any that didn't
    complete, tell me why.
    ```

    Chains `list_agent_executions` → `get_execution`.
  </Accordion>

  <Accordion title="Check balance before calling" icon="wallet">
    ```
    If my wallet balance is above ₹500, call +91XXXXXXXXXX with my
    onboarding agent.
    ```

    Chains `get_user_info` → `start_outbound_call`.
  </Accordion>

  <Accordion title="Audit missing webhooks" icon="magnifying-glass">
    ```
    Which of my agents don't have a webhook set up?
    ```

    Chains `list_agents` → `get_agent` per agent.
  </Accordion>

  <Accordion title="Clean up test agents" icon="broom">
    ```
    Delete any agents I made today with "test" in the name.
    ```

    Chains `list_agents` → `delete_agent`; expect a confirmation prompt per delete.
  </Accordion>

  <Accordion title="Buy a number and wire it up" icon="phone-arrow-up-right">
    ```
    Find me an available number in area code 415, buy it, and route
    it to my support agent.
    ```

    Chains `search_phone_numbers` → `buy_phone_number` → `setup_inbound_agent`; expect a confirmation prompt before the purchase.
  </Accordion>
</AccordionGroup>

<CardGroup cols={2}>
  <Card title="MCP Overview" icon="server" href="/docs/build-with-ai/mcp">
    How the server works and what you can do with it
  </Card>

  <Card title="Example: Monitoring Dashboard" icon="gauge" href="/docs/build-with-ai/mcp-example-app">
    Use these prompts to explore your data, then have your assistant build a small dashboard around it
  </Card>
</CardGroup>
