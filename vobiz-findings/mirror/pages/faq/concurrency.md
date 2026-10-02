> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# What is Concurrency?

> Concurrency on Vobiz defines how many calls run simultaneously on your account - understand channel limits, what triggers a 429 error, and how to right-size for your dialer.

Concurrency (also known as Concurrent Calls or Channels) is the number of **parallel active calls** simultaneously progressing through the Vobiz network on your account at any given moment.

## How Concurrency Limits Work

Every telecom provider uses concurrent call limits to manage hardware capacity. If your application has a Concurrency Limit of `50`, it means you can have 50 active phone calls happening at the same time. These could be:

* 50 outbound dials waiting to be answered.
* 50 people actively talking in an AI Voice agent conversation.
* Or any mix thereof.

<Warning>
  **What happens when you exceed the limit?** If 50 calls are currently active and you attempt to dial a 51st call via the REST API, or a 51st inbound caller attempts to reach your Voice XML application, the call will be **rejected immediately** with a `429 Too Many Requests` or `SIP 503 Service Unavailable`.
</Warning>

<Tip>
  **See it happen.** The [CPS & concurrency visualizer](/docs/resources/cps-concurrency-visualizer) draws every channel as a row and every second as a column. Fill the rows and the next call is refused even though your CPS budget is untouched — the clearest way to tell a channel shortage from a rate limit.
</Tip>

## Calculating your requirements

When scaling your campaign or business application, consider your average call duration (ACD) to determine how many channels you need. If you expect to dial 100 people an hour and each call lasts an hour, you need a concurrency of 100.

[Learn how to purchase a higher Concurrency Limit →](/docs/faq/purchase-concurrency-cps)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.