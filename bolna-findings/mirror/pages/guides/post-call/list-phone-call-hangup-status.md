> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List of Call Hangup Statuses and Codes in Bolna Voice AI

> Explore all hangup statuses, provider codes, and termination reasons in Bolna Voice AI calls. Debug disconnections and improve reliability.

## Introduction

Every Bolna Voice AI call records metadata about how and why it was terminated. This data is essential for debugging, analytics, and improving call completion rates.

Each call termination includes three fields:

| Field           | Description                                                               |
| --------------- | ------------------------------------------------------------------------- |
| `hangup_by`     | Party or system that initiated the hangup (caller, callee, carrier, etc.) |
| `hangup_code`   | Numeric code from the telecom provider indicating the specific reason     |
| `hangup_reason` | Human-readable description of why the call ended                          |

***

## Why Hangup Codes Matter

<CardGroup cols={2}>
  <Card title="Debug Call Issues" icon="bug">
    Identify whether disconnections are user-initiated, carrier-caused, or system errors
  </Card>

  <Card title="Monitor Reliability" icon="signal">
    Track telecom partner performance across providers like Twilio and Plivo
  </Card>

  <Card title="Improve Workflows" icon="arrows-rotate">
    Optimize call handling based on termination patterns and regional issues
  </Card>

  <Card title="Regional Insights" icon="globe">
    Pinpoint geographic routing problems (US, India, Southeast Asia, MENA, etc.)
  </Card>
</CardGroup>

***

## Hangup Status and Provider Codes

| Hangup By       | Description                           | Provider Codes                                         |
| --------------- | ------------------------------------- | ------------------------------------------------------ |
| **API Request** | Call ended via Bolna API request      | `4000`, `4020`                                         |
| **Callee**      | Recipient hung up (outbound calls)    | `3020`, `4000`                                         |
| **Caller**      | Caller ended the call (inbound calls) | `4000`                                                 |
| **Carrier**     | Terminated by telecom carrier         | `2000`, `3000`, `3010`, `3020`, `3040`, `3050`, `3070` |
| **Error**       | Ended due to unexpected error         | `3080`, `3090`, `3110`, `5010`, `5020`, `7011`, `8011` |
| **Plivo**       | Plivo provider disconnected the call  | `1010`, `4010`, `5020`, `6000`, `6010`, `6020`         |
| **Unknown**     | Termination reason unknown            | `0`                                                    |
| *(empty)*       | No hangup reason recorded             | *(empty)*                                              |

<Warning>
  Code `4000` appears across multiple categories (API, Caller, Callee). The correct interpretation depends on **call direction** (inbound vs outbound) and context.
</Warning>

***

## Hangup Reasons

<Tabs>
  <Tab title="Bolna-Side Reasons">
    Bolna provides specific hangup reasons based on your agent configuration:

    | Reason                | Description                                           |
    | --------------------- | ----------------------------------------------------- |
    | `inactivity_timeout`  | Call ended because the silence threshold was exceeded |
    | `llm_prompted_hangup` | Call ended based on custom prompt evaluation          |

    <Tip>
      Configure inactivity timeout and hangup prompts in your [Agent Setup](/docs/agent-setup/agent-tab) to control these behaviors.
    </Tip>
  </Tab>

  <Tab title="Telephony Provider Reasons">
    Reasons provided by the telephony provider (Twilio, Plivo, etc.):

    | Reason                                                   | Description                                             |
    | -------------------------------------------------------- | ------------------------------------------------------- |
    | `Call recipient was busy`                                | Called party was busy                                   |
    | `Call unanswered`                                        | Called party did not answer                             |
    | `Call recipient number invalid`                          | Invalid or unreachable phone number                     |
    | `Call recipient hung up`                                 | Recipient ended the call                                |
    | `Carrier declined`                                       | Call declined by carrier                                |
    | `Call recipient rejected`                                | Call rejected by the called party                       |
    | `failed`                                                 | Call could not be initiated                             |
    | `Carrier ended because call limit exceeded`              | Call terminated due to duration limits                  |
    | `Bolna Error`                                            | Error from Bolna system                                 |
    | `Carrier unable to receive media`                        | Media connection issues                                 |
    | `Network Congestion From Carrier`                        | Network congestion from carrier                         |
    | `End of inputs from Bolna`                               | Call ended after complete conversation (without prompt) |
    | `Carrier unable to reach bolna`                          | Carrier connectivity issue to Bolna                     |
    | `Carrier ended call because MPC duration limit exceeded` | Multi-party call duration limit reached                 |
    | `Telephony Internal Error`                               | Internal telephony system error                         |
    | `Carrier Internal Error`                                 | Internal carrier error                                  |
    | `Call completed`                                         | Call completed successfully                             |
    | `Call canceled`                                          | Call was canceled                                       |
    | `Call ended`                                             | Call terminated normally                                |
    | `Call timed out`                                         | Call exceeded timeout limit                             |
    | `Unknown`                                                | Unknown reason                                          |
  </Tab>
</Tabs>

***

## Notes on Code Interpretation

<AccordionGroup>
  <Accordion title="Multiple codes per status" icon="layer-group">
    Multiple provider codes may map to a single `hangup_by` status depending on network or device behavior. Always check the `hangup_reason` field for additional context.
  </Accordion>

  <Accordion title="Context-dependent codes" icon="arrows-split-up-and-left">
    Codes like `4000` appear in multiple categories. Interpretation depends on **call direction** (inbound vs outbound) and the `hangup_by` field.
  </Accordion>

  <Accordion title="Regional carrier issues" icon="map-location-dot">
    Frequent `3010` or `3050` codes in a specific region may indicate local routing or carrier coverage problems. Contact support if you notice persistent regional patterns.
  </Accordion>
</AccordionGroup>

***

## Related Pages

<CardGroup cols={3}>
  <Card title="Call Status List" icon="ballot-check" href="/docs/guides/post-call/list-phone-call-status">
    Track the full lifecycle of your calls
  </Card>

  <Card title="Call Latency Metrics" icon="chart-bar" href="/docs/concepts/call-latencies">
    Analyze performance across the voice pipeline
  </Card>

  <Card title="Get Execution API" icon="code" href="/docs/api-reference/executions/get_execution">
    Retrieve full execution details programmatically
  </Card>
</CardGroup>
