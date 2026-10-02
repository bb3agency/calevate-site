> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# What is Call Routing? Types, How It Works & Examples (2026 Guide)

> Call routing decides which endpoint a call reaches. How it works, 11 routing types (round-robin, skills-based, LCR), ACD, and dynamic routing via API.

*June 29, 2026 · By [Piyush Sahoo](https://www.linkedin.com/in/piyush-s713/)*

Call routing is the logic that decides where a phone call goes, which agent, queue, IVR menu, voicemail box, or voice AI agent ends up handling it, and how the system chooses. Every call your business receives or places passes through some form of call routing, whether it's a one-line "send everything to the front desk" rule or a real-time engine weighing agent skills, caller history, time of day, and cost on every single call.

This guide goes well past the dictionary definition. You'll get how call routing works step by step, the routing engine and ACD behind it, the eleven routing types worth knowing (round-robin, skills-based, time-based, geographic, least-cost, and more), inbound vs outbound routing, programmable and dynamic routing with a real code example, the benefits, the honest trade-offs, and how call routing changes when the thing answering the phone is an AI agent.

<Note>
  **Key takeaways**

  * **Call routing** is the set of rules and infrastructure that directs each call to the right endpoint (agent, queue, [IVR](/docs/blogs/what-is-an-ivr), or AI agent).
  * The flow is **number → routing rules → endpoint**, executed by a routing engine; in contact centres an **Automatic Call Distributor (ACD)** queues and distributes inbound calls.
  * There are \~**11 routing types** - round-robin, skills-based, time-based, geo, least-cost (LCR), percentage, priority, list/sequential, sticky, and failover/overflow - usually combined.
  * **Dynamic (programmable) routing** decides the destination *at call time* via a webhook, so routing can depend on live data, not a static map.
  * For voice AI, routing has to be sub-second and reliable - the difference between a [single-hop sub-80 ms path](/docs/platform/voice/overview) and a 300–400 ms legacy one.
</Note>

## What is call routing?

**Call routing is the process of directing an incoming or outgoing phone call to a specific destination based on a defined set of rules.** The destination might be a person, a ring group, an [IVR](/docs/solutions/cloud-ivr) menu, a queue, voicemail, an external number, or a voice AI agent. The one distinction that matters: routing is not just "forwarding a call" - it's the *decision layer* that evaluates conditions (who's calling, when, why, who's free, what it costs) and picks the best endpoint, often differently for every call.

In plain terms, call routing answers a single question millions of times a day: *given this call, right now, where should it go?* The quality of that answer is what separates a caller who reaches the right agent in seconds from one who bounces through three transfers and gives up.

## How call routing works

A routed call moves through three logical stages: **number → rules → endpoint.**

1. **The call arrives at a number.** An inbound call lands on a phone number (a [DID](/docs/account-phone-number/purchase-from-inventory) or toll-free number) that your provider has mapped to an application or trunk. For outbound, your application initiates the call and chooses how to reach the destination.
2. **The routing engine evaluates rules.** The platform looks up the rules attached to that number or application - time of day, caller's location, IVR selection, agent availability, priority - and computes a destination. This can be a static config in a dashboard or a live decision returned by your own code.
3. **The call connects to an endpoint.** The engine bridges the call to the chosen destination - an agent's phone, a SIP user, a queue, a [transfer](/docs/solutions/call-transfer) target, or a streaming session to a voice AI agent.

### The routing engine

The routing engine is the component that holds the rules and applies them. In a simple PBX it's a static dial plan. In a cloud platform it's a programmable layer: you describe call flow with [VobizXML](/docs/xml/overview/how-it-works) (or get a webhook callback) and the platform executes it. Either way, the engine is what turns "a call came in" into "the call is now ringing the right place."

### Automatic Call Distribution (ACD)

In a contact centre, the piece that handles inbound routing is the [Automatic Call Distributor (ACD)](https://en.wikipedia.org/wiki/Automatic_call_distributor) - a telephony system that answers inbound calls and queues and distributes them to agents according to preset criteria. The ACD is what holds callers in a queue, plays hold music, and hands each waiting call to the next eligible agent using a routing strategy (round-robin, skills-based, and so on). ACD is frequently paired with an [IVR](/docs/blogs/what-is-an-ivr): the IVR collects intent ("press 1 for sales"), and the ACD routes the call to the matching agent group. The two are distinct - the IVR *interacts*, the ACD *distributes* - but together they form the front door of most call centres.

## Types of call routing

Most real deployments combine several of these rather than picking one. Here are the eleven worth knowing.

| Routing type | How it decides the destination | Best for |
| - | - | - |
| **Round-robin** | Distributes calls evenly across agents in turn, so each gets a fair share before anyone repeats | Even workload across a single team |
| **Skills-based** | Matches the caller's need (from IVR or data) to an agent with the right skill, language, or tier | Specialised support, multilingual teams |
| **Time-based (time-of-day)** | Routes by business hours, time zone, or day - e.g. after-hours calls go to another region or voicemail | Follow-the-sun support, off-hours coverage |
| **Geographic / location** | Routes by the caller's area code, region, or country to the nearest or most relevant office | Local presence, regional teams, language |
| **Least-cost routing (LCR)** | Picks the carrier/path with the lowest cost for the destination at that moment | High-volume outbound, carrier cost control |
| **Percentage (weighted)** | Splits traffic by ratio across destinations - e.g. 70% to A, 30% to B | A/B testing, load balancing, gradual rollout |
| **Priority-based** | Ranks calls (VIP customers, urgent cases) and serves higher-priority callers first | Tiered SLAs, premium support |
| **List / sequential** | Tries a fixed, ordered list of agents - call B only if A is busy, C if A and B are busy | Small teams with a clear hierarchy |
| **Sticky / relationship-based** | Sends a returning caller back to the agent or AI session they spoke to last | Account managers, continuity of context |
| **Failover / overflow** | Reroutes when the primary destination is busy, unanswered, or down | Reliability, spillover during spikes |
| **Data-directed / dynamic** | Computes the destination at call time from live data (CRM, account state, your own logic) | Personalised, condition-driven routing |

A quick note on two that get confused: **[least-cost routing (LCR)](https://en.wikipedia.org/wiki/Least-cost_routing)** is about *which network path* to send a call over to minimise cost, whereas **least-occupied (or most-idle) routing** is about *which agent* is freest. LCR is a carrier-layer optimisation; least-occupied is an ACD-layer one.

## Inbound vs outbound routing

The word "routing" covers two different jobs depending on call direction.

**Inbound routing** decides what happens to calls coming *to* your numbers. It's the ACD/IVR domain: greet the caller, capture intent, queue, and distribute to the best agent or [voice AI agent](/docs/integrations). The optimisation goals are speed-to-answer, first-contact resolution, and not dropping calls during spikes (which is where overflow routing earns its keep).

**Outbound routing** decides how calls you *place* reach their destination. Here the concerns are different: choosing the right carrier path (least-cost routing), presenting the correct [caller ID](/docs/xml/dial), respecting compliance and [number reputation](/docs/best-practices/number-utilization) so calls aren't spam-flagged, and pacing campaigns. A dialer placing thousands of [automated outbound calls](/docs/solutions/automated-outbound-calling) routes very differently from an ACD fielding inbound support.

Many systems do both - a contact centre runs inbound ACD routing *and* outbound campaign routing on the same platform.

## Programmable and dynamic call routing

Static routing - "this number always rings this group" - works until the decision needs to depend on something the dashboard can't know in advance: the caller's account balance, their last order, whether they're a churn risk, which AI agent is warmed up. That's where **programmable (dynamic) routing** comes in.

With dynamic routing, the platform calls *your* application at call time. Your code looks up whatever it needs and returns the routing decision as [XML](/docs/xml/response). The call is then routed based on data that didn't exist until the moment the call arrived.

Here's a minimal example. When a call comes in, Vobiz fetches your webhook, and your app returns VobizXML that bridges the caller to an agent - overriding the caller ID and reporting the outcome to an `action` URL so you can log it or route again on no-answer:

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>Connecting you to the next available agent.</Speak>
    <Dial callerId="+14155550123" timeout="20" action="https://your-app.com/dial-status">
        <Number>+919900112233</Number>
    </Dial>
</Response>
```

To try multiple agents in parallel and bridge whoever answers first (a simple round-robin or hunt pattern), nest several [`Number`](/docs/xml/dial/number) elements inside one [`Dial`](/docs/xml/dial):

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Dial timeout="25" action="https://your-app.com/dial-status">
        <Number>+919900112233</Number>
        <Number>+919900445566</Number>
        <Number>+919900778899</Number>
    </Dial>
</Response>
```

The first party to pick up is connected; the rest are hung up. Because the destinations come from *your* webhook on each call, you can implement any routing type above - skills-based, sticky, priority - in your own code, then express the result as a [`Dial`](/docs/xml/dial). For browser or SIP endpoints you'd dial a [`User`](/docs/xml/dial/user) instead of a `Number`, and you can [redirect](/docs/xml/redirect) the flow to a new document when an agent doesn't answer.

This is the model that lets a [voice AI builder](/docs/integrations) route a call to a live agent the instant the model decides it needs a human - routing as code, not a static map.

## Benefits and use cases

Done well, call routing pays off across the whole call lifecycle:

* **Shorter wait times and fewer transfers.** Getting the caller to the right place first time cuts hold time and the dreaded "let me transfer you."
* **Higher first-contact resolution.** Skills-based and data-directed routing put the caller with someone (or something) actually equipped to help.
* **Always-on coverage.** Time-based and geographic routing keep calls answered across time zones; failover keeps them answered during outages and spikes.
* **Lower cost.** [Least-cost routing](https://en.wikipedia.org/wiki/Least-cost_routing) trims per-minute spend on high outbound volumes; even, automated distribution reduces the staffing needed to hit an SLA.
* **Better data.** Routed-call metadata feeds [post-call analytics](/docs/solutions/post-call-analytics) - where calls go, where they drop, which paths convert.

**Concrete use cases:** a fintech like Razorpay routing support by product line and language; an insurer like Acko sending claims calls to a specialised queue and sales to another; a voice-AI builder like Bolna routing the caller to an AI agent first and [escalating](/docs/solutions/call-escalation) to a human on intent; a global team using follow-the-sun [time-based routing](/docs/blogs/what-is-an-ivr) so a call at 2 a.m. local rings a staffed region.

## Honest trade-offs

Call routing isn't free of friction, and pretending otherwise helps no one.

* **Over-engineered IVR menus frustrate callers.** Deep, multi-level menus in the name of "precise routing" are a top complaint. Keep menus shallow and offer a path to a human (or AI agent) quickly.
* **Misrouting is worse than no routing.** A skills-based rule built on stale data sends the caller to the wrong agent confidently. Routing logic is only as good as the data behind it.
* **Complexity compounds.** Combining six routing types across dozens of numbers gets hard to reason about and debug. Keep flows observable - log every routing decision via your [action URL](/docs/xml/dial) and review [call logs](/docs/platform/voice/call-logs).
* **Latency is a hidden tax.** Every routing hop and webhook round-trip adds delay before the caller hears a human or agent. On a legacy multi-hop CPaaS path (300–400 ms), that tax is steep; for a real-time AI agent it can break the conversation.
* **Outbound routing carries reputation risk.** Aggressive least-cost or mismatched caller-ID routing can get your numbers [spam-flagged](/docs/best-practices/number-utilization), which then *reduces* answer rates - the opposite of the goal.

## How Vobiz handles call routing

[Vobiz](/docs/introduction) is the telephony infrastructure layer - the rails the routing runs on. It doesn't ship its own contact-centre suite or AI agent; it **powers** the agents and apps that do, from voice-AI builders to enterprise contact centres. Where Vobiz makes routing better:

* **Dynamic routing as code.** Express any routing strategy with [VobizXML](/docs/xml/overview/how-it-works) and webhooks - the routing decision is returned by *your* app at call time, then executed with [`Dial`](/docs/xml/dial), [`Gather`](/docs/xml/gather), and [`Redirect`](/docs/xml/redirect).
* **Sub-80 ms, single-hop path.** A single-hop, event-driven architecture with direct carrier connect keeps the routing tax low (vs 300–400 ms on legacy multi-hop stacks) - the margin a real-time [voice AI agent](/docs/platform/voice/overview) needs.
* **Global reach with failover.** [DID provisioning in 130+ countries](/docs/account-phone-number/purchase-from-inventory) and outbound connectivity to 190+, over [SIP trunks](/docs/platform/sip/overview) with **global failover** and multi-region routing for reliability and overflow.
* **Both directions, one platform.** Inbound routing into [applications](/docs/platform/voice/applications) and [contact centres](/docs/solutions/contact-centre); outbound routing for [campaigns](/docs/platform/campaigns/list) and [automated calling](/docs/solutions/automated-outbound-calling), with reputation-aware [number utilization](/docs/best-practices/number-utilization).
* **Instant provisioning.** eKYC provisioning means a number and routing can go live in minutes, not the 4–8 weeks of legacy paperwork.
* **Reliable at scale.** 99.99% uptime and 4.2+ MOS across 3M+ calls/day, with [call logs](/docs/platform/voice/call-logs) and [post-call analytics](/docs/solutions/post-call-analytics) so every routing decision is observable. Builders like **Bolna**, fintechs like **Razorpay** and **Acko**, and enterprises like **KPMG** run on Vobiz.

## Frequently asked questions

<AccordionGroup>
  <Accordion title="What is call routing in a call center?">
    Call routing in a call centre is the system that directs each inbound call to the right agent, queue, IVR, or voice AI agent based on rules such as agent skills, caller intent, priority, and availability. The Automatic Call Distributor (ACD) is the component that queues and distributes those inbound calls.
  </Accordion>

  <Accordion title="What are the types of call routing?">
    The common types are round-robin, skills-based, time-based, geographic, least-cost routing (LCR), percentage/weighted, priority-based, list/sequential, sticky/relationship-based, failover/overflow, and dynamic/data-directed routing. Most deployments combine several rather than using just one.
  </Accordion>

  <Accordion title="What is the difference between ACD and IVR?">
    An IVR (Interactive Voice Response) interacts with the caller to capture intent ("press 1 for sales"); an ACD (Automatic Call Distributor) queues and distributes the call to an agent. The IVR collects information, the ACD routes the call - they usually work together.
  </Accordion>

  <Accordion title="What is dynamic call routing?">
    Dynamic (or programmable) call routing decides the destination at call time by calling your application via a webhook, so the route can depend on live data - CRM records, account state, agent availability - rather than a fixed dashboard rule. Your app returns the routing decision as XML.
  </Accordion>

  <Accordion title="What is least-cost routing (LCR)?">
    Least-cost routing is a technique that selects the carrier or network path with the lowest cost for a call's destination at that moment. It's a carrier-layer optimisation used mainly for high-volume outbound traffic, and is distinct from least-occupied routing, which picks the freest agent.
  </Accordion>
</AccordionGroup>

## Further reading on Vobiz

* [What is an IVR?](/docs/blogs/what-is-an-ivr) · [What is a Voice API?](/docs/blogs/what-is-a-voice-api) · [What is a call leg?](/docs/blogs/what-is-a-call-leg)
* [Dial XML element](/docs/xml/dial) · [How VobizXML works](/docs/xml/overview/how-it-works) · [Voice platform overview](/docs/platform/voice/overview)
* [Contact centre](/docs/solutions/contact-centre) · [Call transfer](/docs/solutions/call-transfer) · [Call escalation](/docs/solutions/call-escalation)
* [SIP trunking](/docs/concepts/sip-trunking) · [SIP platform overview](/docs/platform/sip/overview)

## Sources

* Wikipedia, ["Automatic call distributor"](https://en.wikipedia.org/wiki/Automatic_call_distributor).
* Wikipedia, ["Least-cost routing"](https://en.wikipedia.org/wiki/Least-cost_routing).
* Wikipedia, ["Interactive voice response"](https://en.wikipedia.org/wiki/Interactive_voice_response).

<Card title="Build on Vobiz" icon="rocket" href="/docs/quick-start">
  Provision a number and wire up programmable call routing in minutes.
</Card>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.