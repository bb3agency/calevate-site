> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Contact Centre

> Build a fully custom contact centre on Vobiz - inbound routing, queuing, recording, and AI augmentation without per-seat CCaaS pricing, across 130+ countries.

## What is Contact Centre?

A contact centre built on Vobiz is a fully custom, fully programmable voice operation - not a pre-packaged software product with fixed workflows and per-seat pricing, but a set of powerful, flexible building blocks you assemble into exactly the call centre experience your business needs. You control the routing logic, the agent interface, the escalation rules, the recording policies, the analytics, and the AI layer - everything.

This is fundamentally different from buying a CCaaS product. When you build a contact centre on Vobiz, you are building exactly what your business requires, using your own technology stack, integrated with your own CRM and helpdesk tools, and running at a cost model that scales with usage rather than with headcount.

## The Problem It Solves

Off-the-shelf contact centre platforms make easy things easy but hard things impossible. They come with fixed workflows that do not match every business's process. They are expensive at scale - charging per agent seat means your costs grow linearly as you hire, with no efficiency gains from automation. They are deeply integrated into their own ecosystem, making it difficult to connect them to your CRM, your data warehouse, or your own product.

Businesses that need contact centre capabilities at scale, or that have non-standard requirements, consistently find that pre-packaged CCaaS platforms become a ceiling rather than an enabler. Vobiz removes that ceiling.

## How Vobiz Powers Contact Centre

A contact centre built on Vobiz uses all of the platform's capabilities in concert. Inbound calls arrive at Vobiz phone numbers and are handled by an IVR built with the XML engine - gathering caller intent, looking up account information, and routing to the appropriate queue or agent. Outbound calls are made using the Make Call API, which supports bulk dialling of up to 1000 destinations simultaneously, machine detection to skip voicemails and answering machines, and time-limited calls that automatically end after a configured duration.

Calls are distributed to agents using Conference or Multiparty Call rooms. Supervisors monitor active calls using deaf mode and provide coaching using coach mode. Agents can transfer calls to specialists using the Transfer API, with context preserved through your application layer. Every call is recorded with the Record API, and transcripts are generated automatically. All call data flows into the CDR API for real-time reporting.

For AI-augmented contact centres, the WebSocket stream connects every call to an AI processing layer. The AI can provide real-time transcription for agent assistance, flag keywords or sentiments, suggest responses, auto-fill CRM fields after the call, and trigger escalations based on what it hears. Fully automated AI agents handle the highest-volume, lowest-complexity calls, while human agents focus on the calls that require judgement and empathy.

Webhooks are central to the contact centre architecture. Every call event - answered, transferred, recorded, ended - triggers a webhook to your application. Your application maintains the state of every call in your own database, making the contact centre data fully yours.

## Use Cases & Scenarios

* A large insurance BPO built their entire outbound renewal calling operation on Vobiz. They dial 50,000 customers per day using bulk outbound calls with machine detection. Answered calls are connected to agents within seconds. The IVR pre-qualifies callers before agent connection, reducing average handle time by 40%. All calls are recorded and transcripts are pushed into the CRM automatically after each call.
* A digital lending startup built a collections contact centre on Vobiz specifically because they needed full control over the conversation flow and compliance rules. Their application manages all routing, enforces calling time restrictions per TRAI regulations, tracks all contact attempts per customer, and maintains a complete audit log of every call.
* A B2B SaaS company built a customer success call centre on Vobiz for their enterprise tier customers. Account managers handle calls from a browser-based softphone connected via WebRTC. The IVR recognises enterprise customers by their phone number and routes them directly to their named account manager, bypassing the general queue entirely.

## Why Choose Vobiz?

Vobiz provides the infrastructure of a world-class contact centre without the constraints of a pre-packaged product. You own the architecture, the data, and the workflows. The per-minute pricing model ties your costs directly to actual call volume - not agent headcount. With unlimited concurrency on enterprise plans, your contact centre can handle any volume spike without call drops or degradation.

***


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.