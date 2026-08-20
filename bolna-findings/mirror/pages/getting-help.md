> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Getting Help

> Community resources, support channels, and what to include when reporting an issue with Bolna.

Stuck on something, or think you've found a bug? Here's where to look and who to contact, depending on what you need.

## Community & Resources

<CardGroup cols={2}>
  <Card title="Slack Community" icon="slack" href="https://join.slack.com/t/bolnabuilders/shared_invite/zt-42zi57jyd-3yt1XDWq3kWBLj1puqq2fQ">
    Ask questions and get real-time help from the Bolna team and other builders.
  </Card>

  <Card title="Documentation" icon="book" href="/docs/introduction">
    Search these docs from the bar at the top of any page, or browse the sidebar by topic.
  </Card>

  <Card title="FAQs" icon="comments-question-check" href="/docs/frequently-asked-questions">
    Quick answers to the questions we hear most often — pricing, concurrency, phone numbers, and more.
  </Card>

  <Card title="Agent Templates" icon="layer-group" href="/docs/agents-library">
    Ready-made prompts and configs for common use cases — lead qualification, support, scheduling, and more.
  </Card>

  <Card title="YouTube" icon="youtube" href="https://www.youtube.com/@BolnaVoiceAI">
    Tutorials, demos, and walkthroughs for building and deploying voice agents.
  </Card>

  <Card title="Status Page" icon="globe" href="https://status.bolna.ai">
    Check real-time platform status, ongoing incidents, and maintenance notices before filing a report.
  </Card>
</CardGroup>

<Tip>
  Before reaching out, check the [Status Page](https://status.bolna.ai) — if there's an ongoing incident, it's likely already being tracked there.
</Tip>

## Direct Support Channels

| Channel                            | Contact                                                                                     | Use for                                                                                                                                 |
| ---------------------------------- | ------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| **General Support**                | [support@bolna.ai](mailto:support@bolna.ai)                                                 | Technical issues, account/billing questions, feature requests                                                                           |
| **Enterprise & Sales**             | [enterprise@bolna.ai](mailto:enterprise@bolna.ai)                                           | Enterprise plan, sub-accounts, on-premise deployments, data residency, custom pricing — or [schedule a call](https://www.bolna.ai/meet) |
| **Regulated Numbers & Compliance** | [compliance@bolna.ai](mailto:compliance@bolna.ai)                                           | LOA requests and DLT/TRAI compliance for regulated Indian phone numbers                                                                 |
| **Security & Certifications**      | [support@bolna.ai](mailto:support@bolna.ai) / [support@bolna.dev](mailto:support@bolna.dev) | HIPAA, SOC 2, GDPR certification requests, and VAPT report requests — see [Security](/docs/concepts/security)                                |

## What to Include When Reporting an Issue

The faster we can reproduce a problem, the faster we can fix it. Include the following details depending on the issue type.

<AccordionGroup>
  <Accordion title="Agent behavior issues">
    * Agent ID and agent type (single-prompt or [graph agent](/docs/graph-agent/introduction))
    * What you expected the agent to do vs. what it actually did
    * Steps to reproduce, including any inputs or user\_data variables passed
    * The relevant `execution_id` and conversation transcript, if the issue happened on a live or test call
  </Accordion>

  <Accordion title="Call quality issues">
    * The `execution_id` (call ID), phone number, and timestamp of the call
    * Direction (inbound/outbound) and telephony provider used
    * A description of the issue — latency, dropped audio, wrong transcription, premature hangup, etc.
    * Raw logs for the call, pulled via [Get Execution Raw Logs](/docs/api-reference/executions/get_execution_raw_logs) or the [debug-bolna-calls](/docs/agent-setup/call-history) view in the dashboard
  </Accordion>

  <Accordion title="Platform / dashboard issues">
    * Browser and version
    * Steps to reproduce
    * Screenshots or the exact error message shown
    * The account email associated with your Bolna workspace
  </Accordion>

  <Accordion title="Batch calling issues">
    * The `batch_id` and affected recipient row(s) from your CSV
    * Expected vs. actual outcome for those recipients
    * Whether the issue affects the whole batch or specific recipients — see [Batch Calling](/docs/guides/outbound/batch-calling)
  </Accordion>
</AccordionGroup>

## Enterprise Support

<Tip>
  Enterprise customers get a dedicated Slack channel with premium support, priority response times, and a dedicated engineer who knows your use case. See the [Enterprise Plan](/docs/enterprise/plan) or reach out at [enterprise@bolna.ai](mailto:enterprise@bolna.ai).
</Tip>
