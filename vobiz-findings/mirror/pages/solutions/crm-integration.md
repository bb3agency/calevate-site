> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# CRM Integration

> Eliminate manual call logging by auto-syncing every call, recording, and outcome to your CRM via Vobiz webhooks. Supports Salesforce, HubSpot, Zoho, Freshsales, and any custom CRM across 130+ countries.

## What is CRM Integration?

CRM integration for voice means connecting your phone call infrastructure to your customer relationship management system so that every call - inbound and outbound - is automatically captured, attributed to the right customer record, enriched with call data, and accessible to sales, support, and management teams within the CRM interface. Your CRM records when a customer called, how long the call lasted, whether it was answered, what was discussed, and what the outcome was - all without any manual entry from an agent.

Vobiz does not require a proprietary CRM integration plugin. Instead, it uses webhooks - standard HTTP callbacks - to send call events to any URL you specify. This means Vobiz can integrate with any CRM, helpdesk, or business intelligence tool, whether it is Salesforce, HubSpot, Zoho, Freshsales, Leadsquared, a proprietary internal CRM, or a custom-built system. If your application can receive an HTTP POST request, it can receive Vobiz call data.

## The Problem It Solves

The biggest problem with voice in CRM systems is the manual entry burden. Agents are expected to log calls, fill in notes, update contact status, and tag conversations - all while handling the next call. In practice, this data is incomplete, inconsistent, or simply not entered at all. CRM records become stale. Management reports are unreliable. Leads fall through gaps because the system does not know a contact was called.

Vobiz's webhook architecture eliminates this problem entirely. Call events are sent automatically to your application the moment they happen, with full metadata. Your application writes this data to the CRM without any agent action required. By the time the agent hangs up, the call is already logged.

## How Vobiz Powers CRM Integration

Vobiz sends HTTP callbacks at four key moments in every call's lifecycle. The `ring_url` is called when the call begins to ring - giving your application the opportunity to create a call record in the CRM immediately, before the call is even answered. The `answer_url` is called when the call is answered - updating the CRM record with the answer timestamp and triggering a screen pop in the agent's CRM interface with the caller's details. The `hangup_url` is called when the call ends - providing the full call duration, start time, answer time, end time, and hangup cause, which completes the CRM record.

The CDR API provides a second channel for CRM integration. After calls complete, your application can query the CDR API with filters - by phone number, date range, call direction, or duration - and push the results into the CRM in batch. This is useful for reconciliation, catching any events that the real-time webhook might have missed, and for historical data imports.

For outbound campaigns, the combination of webhooks and CDR data means every contact attempt is logged against the right CRM record automatically. If a call was unanswered, the CRM shows "No answer, attempted 14:30." If it was answered, the CRM shows "Connected, 3m 20s." If a recording was made, the CRM record includes a link to the audio file. All of this happens without the agent touching the CRM.

The call UUID returned by every Vobiz API call is the key that ties everything together. Your application stores this UUID against the CRM record when the call is initiated. All subsequent webhooks for that call carry the same UUID, allowing your application to update the correct record at every stage without ambiguity.

## Use Cases & Scenarios

* A real estate company's CRM is updated automatically every time an agent calls a lead from Vobiz. The agent opens the lead record, clicks "Call," and the application initiates the call via the Vobiz API. When the call connects, the CRM record is updated with a "Call in Progress" status. When the call ends, the duration, outcome, and recording link are added automatically. The lead status is updated based on the call outcome the agent selects from a dropdown - no free-text entry required.
* A B2B sales team logs all outbound prospecting calls in their CRM using Vobiz webhooks. The CDR API is queried nightly and the results are pushed into a custom analytics dashboard that shows each rep's call volume, average call duration, contact rate, and conversion rate. The data requires zero manual input from the reps.
* An e-commerce support team's helpdesk is updated with call records using the Vobiz hangup\_url webhook. Every support call is attached to the customer's ticket automatically. Support managers can see at a glance how many calls each ticket required before resolution, which tickets have unresolved calls, and which customers have called most frequently.

## Why Choose Vobiz?

Vobiz's webhook architecture uses standard HTTP - no proprietary SDK or middleware required. Any developer who can build a REST endpoint can integrate Vobiz with any CRM. The CDR API's rich filtering and CSV export capabilities make it straightforward to build reporting and reconciliation workflows. Because the entire integration runs on your own application logic, you are not dependent on a marketplace plugin or a third-party connector that may not support your exact CRM version.

***


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.