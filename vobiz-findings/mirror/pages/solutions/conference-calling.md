> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Conference Calling

> Host multi-party calls with live moderation, recording, and coach mode. Vobiz conference API supports barge, whisper, and mute across 130+ countries.

## What is Conference Calling?

Conference calling is the ability to connect more than two participants in a single voice call simultaneously. In a business context, it ranges from a simple three-way call between a customer, an agent, and a supervisor, all the way to a large-group meeting with dozens of participants, moderated by a host who can mute, remove, and manage members in real time.

Vobiz provides two distinct conferencing capabilities - the Conference API for traditional multi-party meeting use cases, and the Multiparty Call (MPC) API for advanced contact centre scenarios with role-based permissions, supervisor monitoring, and coach mode. Both are fully programmable, so every aspect of the conference experience is driven by your application.

## The Problem It Solves

Businesses have relied on conference bridges for decades, but traditional conferencing tools are disconnected from the rest of the communications stack. You cannot programmatically add a participant, mute a specific member based on a business rule, or record a conference and push the recording into your CRM - not without deep, proprietary integrations that most providers do not offer.

Vobiz changes this by making the entire conference lifecycle accessible via API. You can create a conference, add participants one by one as they dial in or are dialled out to, control their audio in real time, record the session, and receive webhooks at every stage of the conference lifecycle.

## How Vobiz Powers Conference Calling

Vobiz conferences are initiated through the XML Conference element. When a call is instructed to join a conference by name, it is held in a waiting state until at least one other participant joins - unless you set the conference to start immediately. Participants can be dialled in by your application using the outbound calling API, allowing for fully automated conference assembly where your application dials all participants and places them into the conference room.

Once a conference is live, the Conference API gives you full control. You can retrieve the list of all active members with their mute and deaf status. You can mute a specific member or all members simultaneously. You can deafen a member - they stay connected but cannot hear the conference audio - which is used for hold scenarios and supervisor monitoring. You can kick a member, which disconnects them while keeping the rest of the conference alive. You can play audio or text-to-speech to individual members or to everyone.

The Multiparty Call API extends this with role-based participation. Supervisors can join in coach mode, where they can hear everything but only speak to the agent - not the customer. This is the standard mechanism for live call coaching in contact centres. Supervisors can also barge in fully, taking over the call and speaking to both the agent and the customer.

Conference recording works identically to call recording - start it via API, stop it when needed, receive a callback with the file URL, and retrieve it through the Recording API.

## Use Cases & Scenarios

* An investment firm uses Vobiz conference calling for client advisory sessions where an analyst and a senior advisor both need to be on the call with the client. The application dials all three parties automatically at the scheduled time and assembles them into a conference room. The senior advisor can mute themselves while the analyst leads, and unmute to contribute at key moments.
* A legal firm uses conference calling for client-counsel-co-counsel meetings. The firm's practice management software triggers the conference dial-out based on a calendar event. The conference is automatically recorded for documentation purposes, and the recording is attached to the case file via a webhook.
* A contact centre uses Multiparty Call for supervisor quality monitoring. Supervisors join active customer-agent calls in coach mode, listening silently and providing real-time guidance to agents via a text channel. If a situation deteriorates, the supervisor can barge in and take over the call without the customer experiencing any disruption.
* A remote sales team uses Vobiz conference calling for deal review calls. The sales manager joins calls with account executives and prospects, listening in for coaching purposes. Post-call, the recording and auto-transcript are pushed to the CRM and linked to the deal record.

## Why Choose Vobiz?

Vobiz conferencing is fully programmable, so you are not constrained by what a pre-built conferencing product allows. Every action - adding participants, controlling audio, recording, ending the conference - is a REST API call. You can integrate conference management directly into your CRM, scheduling system, agent desktop, or mobile app. Pricing is per minute per participant, so conferences scale linearly and predictably with usage.

***


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.