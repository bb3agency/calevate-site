> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Why am I receiving a 429 error?

> A Vobiz 429 Too Many Requests error means you have hit a concurrency or CPS limit - find out which limit is breached and the exact steps to fix it.

A `429 Too Many Requests` HTTP or SIP response means your application has attempted to initiate more traffic than your current account provisioning allows. Like all cloud communications platforms, Vobiz imposes limits to protect carrier network integrity and ensure fair resource allocation.

## You have hit one of two limits

<CardGroup cols={2}>
  <Card title="1. Concurrency Limits" icon="chart-bar" href="/docs/faq/concurrency">
    Concurrency is the total number of simultaneous, active calls currently running on your account. If your limit is 10, and you attempt to dial the 11th call before any of the previous 10 hang up, the request will immediately fail with a 429.

    Read more about Concurrency →
  </Card>

  <Card title="2. CPS Limits" icon="bolt" href="/docs/faq/cps">
    Calls Per Second (CPS) is the rate at which you launch new requests. Even if your concurrency limit is entirely free, if you have a CPS limit of 1 and rapidly blast 5 calls in the exact same second, the latter 4 calls will be rejected with a 429.

    Read more about CPS →
  </Card>
</CardGroup>

<Tip>
  **Not sure which one you hit?** Work through the [CPS & concurrency visualizer](/docs/resources/cps-concurrency-visualizer). It counts the two refusals separately, so you can see at a glance whether calls are dying at the doorway or in a full room.
</Tip>

## How to resolve 429 errors

To stop receiving 429 errors, either pace your outbound dialer to stay within your allowed limits, or purchase a higher operational ceiling.

* **Check limits:** Log in to your [dashboard](https://console.vobiz.ai) and navigate to the Account Settings limits to observe your current CPS/Concurrency ceiling.
* **Implement pacing queues:** Adjust your backend application logic (like RabbitMQ or Redis queues) to smoothly rate-limit the distribution of outbound API triggers.
* **Purchase an Upgrade:** Scale up to hundreds of concurrent channels by purchasing higher concurrency directly via the billing portal.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.