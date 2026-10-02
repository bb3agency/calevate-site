> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# What is CPS (Calls Per Second)?

> CPS on Vobiz controls how fast you can initiate calls, independent of concurrency - learn how CPS rate limiting works and how to pace outbound dialers to avoid 429 errors.

**CPS** stands for **Calls Per Second**. While Concurrency governs how many calls are actively running, CPS governs how fast you are allowed to *initiate* them. It is a strict rate limit on the velocity of your outbound dialing.

## Why is CPS important?

Telephony signaling infrastructure involves intensive protocol negotiations (SIP INVITEs). To protect switching capacity, carriers throttle how quickly calls can be set up. If your application sends 100 API requests to make a call within the same second but your CPS limit is `1`, then 99 of those requests will fail immediately.

* **Queueing:** Well-architected campaign dialers use pacing algorithms to inject calls into the network evenly. At a CPS of 1, your dialer should wait 1,000 milliseconds between API calls.
* **Throughput:** Even with a CPS of 1, you can still dial 3,600 calls per hour. Do not confuse low CPS with low volume.

<Tip>
  **See it happen.** The [CPS & concurrency visualizer](/docs/resources/cps-concurrency-visualizer) lets you dial calls onto a board second by second. Stage more than your CPS allows and the gate refuses you while the channel pool sits half empty — which is exactly the signal that you need CPS, not more channels.
</Tip>

## Mitigating CPS Bottlenecks

If your application cannot easily buffer or throttle outbound dialing requests locally, you will receive `429 Too Many Requests` failures during usage spikes. The most permanent solution for high-throughput applications is purchasing a higher CPS allocation.

[Learn how to purchase a higher CPS Limit →](/docs/faq/purchase-concurrency-cps)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.