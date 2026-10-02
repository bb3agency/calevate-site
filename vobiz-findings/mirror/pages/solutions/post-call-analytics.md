> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Post-Call Analytics

> Turn every completed call into structured business intelligence using Vobiz CDR and recording APIs. Query call volume, agent performance, and compliance data across global deployments via BI tools or ML pipelines.

## What is Post-Call Analytics?

Post-call analytics is the practice of extracting structured data and insights from completed calls - not just listening to recordings, but systematically analyzing call metadata, audio, and transcripts to understand patterns, measure performance, identify problems, and make decisions. It answers questions like: How long are calls on average? Which agents have the highest and lowest call durations? What percentage of outbound calls are answered? Which customers call most frequently? How are calls distributed across days and hours? Are compliance keywords appearing or missing in call transcripts?

Vobiz provides the data infrastructure for post-call analytics through its CDR API, Recording API, and webhook event system. The analysis layer is built by your application - whether that is a custom dashboard, a BI tool, an AI analysis pipeline, or a spreadsheet for smaller teams.

## The Problem It Solves

Most telephony systems are black boxes for analytics. You can see a call log, but you cannot query it programmatically, filter it precisely, export it in a structured format, or build automated workflows around it. Managers resort to manually downloading CSV files, copying data into spreadsheets, and producing reports that are already outdated by the time they are shared.

Vobiz's CDR API is designed specifically for programmatic analytics. Every field in the call record - caller, recipient, direction, duration, status, cost, trunk, hangup cause - is queryable via API. You can build live dashboards, automated reports, anomaly detection, and compliance monitoring systems using the same data that flows through your Vobiz account.

## How Vobiz Powers Post-Call Analytics

The CDR API exposes five endpoints that cover every analytics use case. The list endpoint returns all CDRs with rich filtering - filter by calling number, receiving number, call direction, date range, and minimum duration. This lets you extract precisely the slice of call data you need for any analysis. The search endpoint adds a filter summary to the response, which is useful for building search interfaces. The recent endpoint returns the last N calls without requiring a date range, useful for real-time monitoring dashboards. The single CDR endpoint retrieves the full detail of one call by its call ID.

The export endpoint returns CDR data as a downloadable CSV file, making it straightforward to load call data into Excel, Google Sheets, or data warehousing tools like BigQuery or Redshift for deeper analysis.

Each CDR record contains the caller number, recipient number, call direction (inbound or outbound), duration in seconds, call status, start time, answer time, end time, cost in INR, the trunk used for the call, and the hangup cause. Hangup cause is particularly valuable for analytics - it distinguishes between calls that ended normally, calls where the recipient did not answer, calls where the line was busy, and calls that failed due to network issues.

For quality-focused analytics, recording data adds another dimension. The Recording API's export endpoint allows bulk retrieval of recording metadata for any date range. By combining CDR data with recording data, your application can calculate the percentage of calls that were recorded, flag calls where recording failed, and identify calls above a certain duration for targeted quality review.

Webhooks complement the CDR API for real-time analytics. Every hangup event, with its full call metadata, arrives at your webhook endpoint the moment the call ends. This allows you to update live dashboards, trigger alerts for anomalous calls, and push call data into your analytics pipeline in near real time rather than waiting for a batch export.

## Use Cases & Scenarios

* A collections contact centre built a live operations dashboard using Vobiz webhooks and the CDR API. The dashboard shows - updated every 30 seconds - the number of calls in progress, the number of calls completed in the last hour, the current answer rate, the average call duration, and the number of calls that went to voicemail. Team leaders use it to make real-time staffing decisions.
* A sales team manager built a weekly performance report that pulls CDR data via the API and calculates, for each sales rep, their total call volume, average call duration, contact rate, and call activity by hour of day. The data is loaded into a Google Sheet automatically every Monday morning. No manual input required.
* A compliance team at an NBFC uses the CDR export function to produce a weekly report of all outbound calls made to customers in DND-registered numbers, cross-referenced against the company's internal DND registry. Any violations are flagged automatically for review.
* A SaaS startup tracks the relationship between support call volume and product usage metrics. CDR data is exported nightly to their data warehouse and joined with product analytics data. The analysis revealed that users who encountered a specific UI bug were 8x more likely to call support within 24 hours - a correlation that triggered an immediate engineering fix.

## Why Choose Vobiz?

Vobiz's CDR API is one of the most complete call record APIs available for the Indian market. The ability to query, search, filter, and export call records programmatically - rather than downloading a static report from a portal - makes it possible to build sophisticated analytics operations on top of Vobiz without a separate data pipeline service. Because INR call costs include all call metadata, you are never paying extra for data that should come with your call.

***


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.