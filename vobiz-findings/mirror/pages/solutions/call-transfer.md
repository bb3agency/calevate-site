> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Call Transfer

> Move active calls between agents, teams, or IVRs on Vobiz globally - warm transfers, blind transfers, SIP REFER, and full context preservation.

## What is Call Transfer?

Call transfer is the ability to move an active, in-progress call from one destination to another without the caller having to hang up and redial. It is one of the most fundamental features of any telephony system - and one that requires surprisingly deep engineering to do well in a programmable API context. A simple transfer routes the caller to a new number. A warm transfer lets an agent speak to the receiving party first before completing the handoff. A contextual transfer carries metadata and call history to the next destination so no one has to ask the customer to repeat themselves.

With Vobiz, call transfer is a real-time API operation. Send a single API request to a live call, specifying where to send it and what XML logic to execute when it lands. The caller experiences a seamless transition - perhaps a brief "Please hold while we transfer your call" message - and is then speaking with exactly the right person or team.

## The Problem It Solves

Without programmable call transfer, businesses are forced to rely on hardware PBX systems or rigid softphone configurations to move calls around. These systems are expensive, difficult to change, and impossible to make context-aware. Agents end up transferring callers to generic queues, losing all the context gathered during the call. Customers have to re-explain their issue from the start. Resolution times increase. Satisfaction drops.

Programmable transfer through Vobiz solves this by making the transfer decision an application-level event. Your server decides where the call goes, when, and what to say during the transition. The transfer is tied to your business logic - not to a static PBX dial plan configured months ago.

## How Vobiz Powers Call Transfer

Vobiz's Transfer API operates on a live call using its call UUID. You identify which leg of the call to transfer - the caller (A leg), the agent (B leg), or both - and point it at a new URL that returns XML instructions. Those XML instructions define exactly what happens next: play a message, connect to a new number, start a new IVR flow, or join a conference.

This is powerful because the new URL can be entirely dynamic. Your server can look up the best available agent in your system, check their availability status, factor in the caller's history, and return a Dial instruction pointing to that specific agent's number or SIP endpoint. The transfer becomes a fully intelligent routing decision, not just a blind handoff to a queue.

For warm transfers specifically, you can use a conference room as the staging area - bring the receiving agent into a three-way call, let them get context from the original agent, then drop the original agent and leave the caller with the new one. This is a pattern Vobiz's Conference and Transfer APIs support together seamlessly.

## Use Cases & Scenarios

* A customer support centre uses Vobiz call transfer to move callers from a general support IVR to specialised agents. When the IVR determines that a caller is asking about a billing dispute, it transfers the call directly to the billing team's extension, with a URL that pre-announces the reason for the call via text-to-speech. The billing agent hears "Incoming call: billing dispute from a Premium plan customer" before connecting - no need to ask what the call is about.
* A healthcare provider transfers calls between the appointment booking team and the insurance verification team. When a patient needs to verify their insurance before booking, the appointment agent triggers a transfer via API. The patient is moved to the insurance team, who can see from the call context exactly who they are and why they were transferred.
* A sales team at an NBFC uses warm transfer to hand off pre-qualified leads from an outbound calling campaign to senior relationship managers. The telecaller who made first contact does a quick introduction in a three-way call before dropping off, leaving the prospect already engaged with the relationship manager.

## Why Choose Vobiz?

Vobiz's Transfer API gives you per-leg control. You can transfer the caller, the agent, or both simultaneously to different destinations. Everything is driven by your server logic - transfers can be triggered by any event in your system: a CRM update, a chat message, a supervisor flag, or a timed escalation rule. Because the platform runs on Vobiz's India-first infrastructure, transfers within India complete with low latency, keeping call quality consistent through the handoff.

***


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.