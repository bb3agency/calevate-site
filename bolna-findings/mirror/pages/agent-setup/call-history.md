> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Agent Conversations, Metrics & Logs

> Access Voice AI agent conversations, recordings, transcripts, and execution data. Monitor performance metrics, debug with logs, and export data for analysis.

## What is Call History?

Call History (Agent Conversations) displays all historical conversations with your agents. View performance metrics, listen to recordings, read transcripts, and access raw execution data for debugging and analysis.

<Frame caption="Call History on Bolna Platform">
  <img src="https://mintcdn.com/bolna-54a2d4fe/nkJ9nAjMGNa34kLN/images/getting-started/call-history/call-history-overview.png?fit=max&auto=format&n=nkJ9nAjMGNa34kLN&q=85&s=882aa09c2e2dc71e1697be83a56fbaa8" alt="Call History page showing performance metrics, call table with execution details, and filter options" width="1024" height="581" data-path="images/getting-started/call-history/call-history-overview.png" />
</Frame>

***

## How to Access Call History

<Steps>
  <Step title="From Sidebar">
    Click **Call History** in the left navigation menu.
  </Step>

  <Step title="From Agent Setup">
    Click **See all call logs** in the actions panel.
  </Step>
</Steps>

***

## Performance Metrics

<Info>
  The top section displays **real-time metrics** for your selected agent and date range. Use these to monitor campaign performance at a glance.
</Info>

| Metric               | Description                                    |
| -------------------- | ---------------------------------------------- |
| **Total Executions** | Total number of call attempts                  |
| **Total Cost**       | Total campaign spend                           |
| **Total Duration**   | Total call time in seconds                     |
| **Status Breakdown** | Count of Error, Completed, and No-Answer calls |
| **Avg Cost**         | Average cost per call                          |
| **Avg Duration**     | Average call length                            |

***

## Filtering Calls

<Accordion title="Available Filters">
  | Filter         | Description                               |
  | -------------- | ----------------------------------------- |
  | **Agent**      | Select a specific agent to view its calls |
  | **Batch**      | Filter by batch campaign                  |
  | **Date Range** | Choose a date range for the calls         |
  | **Group By**   | Group calls by different criteria         |
  | **Call Type**  | Filter by inbound or outbound calls       |
  | **Status**     | Filter by Completed, Error, or No-Answer  |
  | **Provider**   | Filter by telephony provider              |
</Accordion>

<Tip>
  Use the **search by execution ID** box to quickly find a specific call.
</Tip>

***

## Call Table

Each call is displayed with the following information:

| Column                | Description                                         |
| --------------------- | --------------------------------------------------- |
| **Execution ID**      | Unique identifier for the call                      |
| **User Number**       | Phone number of the caller/recipient                |
| **Conversation Type** | Type of call (plivo outbound, twilio inbound, etc.) |
| **Duration (s)**      | Call duration in seconds                            |
| **Hangup By**         | Who ended the call (Callee, Carrier, Plivo, etc.)   |
| **Batch**             | Batch campaign if applicable                        |
| **Timestamp**         | When the call occurred                              |
| **Cost**              | Cost of the call                                    |
| **Status**            | Call status (Completed, No-answer, Error)           |

***

## Call Details

<Tabs>
  <Tab title="Conversation Data">
    Click **Recordings, transcripts, etc** to view the full conversation data.

    <Frame caption="Conversation Data Modal">
      <img src="https://mintcdn.com/bolna-54a2d4fe/nkJ9nAjMGNa34kLN/images/getting-started/call-history/conversation-data.png?fit=max&auto=format&n=nkJ9nAjMGNa34kLN&q=85&s=a3ecf63aea4470e424e184f43f7eab93" alt="Conversation data modal showing call recording with waveform player and transcript" width="1024" height="965" data-path="images/getting-started/call-history/conversation-data.png" />
    </Frame>

    | Section        | Description                                           |
    | -------------- | ----------------------------------------------------- |
    | **Recording**  | Audio waveform with play, copy, and download options  |
    | **Transcript** | Full conversation showing Assistant and User messages |

    <Tip>
      Use the copy button to quickly copy the recording URL or transcript text.
    </Tip>
  </Tab>

  <Tab title="Trace Data">
    Click the **Trace Data** icon to view detailed execution logs for debugging.

    <Frame caption="Agent Execution Logs">
      <img src="https://mintcdn.com/bolna-54a2d4fe/nkJ9nAjMGNa34kLN/images/getting-started/call-history/trace-data.png?fit=max&auto=format&n=nkJ9nAjMGNa34kLN&q=85&s=9840efd0a21d6630cd5f7ec97e9e6711" alt="Agent execution logs showing timestamp, log data, direction, component, and provider" width="1024" height="668" data-path="images/getting-started/call-history/trace-data.png" />
    </Frame>

    | Column        | Description                                                |
    | ------------- | ---------------------------------------------------------- |
    | **Timestamp** | Exact time of each log entry                               |
    | **Log Data**  | The actual request or response content                     |
    | **Direction** | Whether it's a request or response                         |
    | **Component** | Which component handled it (synthesizer, transcriber, llm) |
    | **Provider**  | Provider used (elevenlabs, deepgram, azure, etc.)          |

    When you fetch logs via the [Get execution raw logs API](/docs/api-reference/executions/get_execution_raw_logs), LLM assistant responses may also include **`reasoning_content`** (model thinking or reasoning summary) when the provider returns it.

    <Warning>
      **Trace data is essential for debugging!** Use it to identify latency issues, transcription errors, or unexpected LLM responses.
    </Warning>

    <Tip>
      Click **Download logs** to export all trace data for detailed analysis.
    </Tip>
  </Tab>

  <Tab title="Raw Data">
    Click the **Raw Data** icon to view the complete JSON execution data.

    <Frame caption="Raw Call Data">
      <img src="https://mintcdn.com/bolna-54a2d4fe/nkJ9nAjMGNa34kLN/images/getting-started/call-history/raw-call-data.png?fit=max&auto=format&n=nkJ9nAjMGNa34kLN&q=85&s=863201578966113a4a577173a1285cc3" alt="Raw call data modal showing JSON format" width="1024" height="932" data-path="images/getting-started/call-history/raw-call-data.png" />
    </Frame>

    <Info>
      The raw data format matches the [Get Execution API](/docs/api-reference/executions/get_execution) response, making it easy to integrate with your systems programmatically.
    </Info>
  </Tab>
</Tabs>

***

## Quick Actions

| Action                | Description                       |
| --------------------- | --------------------------------- |
| **Refresh**           | Reload the call list              |
| **Stop Queued Calls** | Cancel pending calls in the queue |
| **Download Records**  | Export call data as CSV           |

<Tip>
  Export call data as CSV for analysis in spreadsheet tools or to share with your team.
</Tip>

***

## Next Steps

<CardGroup cols={2}>
  <Card title="Extractions Tab" icon="chart-line" href="/docs/agent-setup/analytics-tab">
    Configure webhooks and post-call tasks
  </Card>

  <Card title="Get Execution API" icon="code" href="/docs/api-reference/executions/get_execution">
    Access call data programmatically
  </Card>

  <Card title="Agent Setup" icon="gear" href="/docs/agent-setup/overview">
    Configure your agent settings
  </Card>

  <Card title="Batch Calling" icon="phone" href="/docs/guides/outbound/batch-calling">
    Set up automated calling campaigns
  </Card>
</CardGroup>
