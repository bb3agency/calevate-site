> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Cloud IVR

> Build programmable cloud IVR on Vobiz with DTMF, speech recognition, and intelligent routing - no hardware, globally available across 130+ countries.

## What is Cloud IVR?

An Interactive Voice Response system is the technology behind every "Press 1 for Sales, Press 2 for Support" experience on a phone call. Modern IVR goes far beyond simple keypad menus, however. A cloud IVR is a fully programmable, hosted version of this system - meaning there is no hardware to buy, no on-premise equipment to maintain, and no PBX box in a server room. Everything runs through an API, and your call flows live in the cloud, accessible and editable from anywhere at any time.

With Vobiz, you can build a cloud IVR that responds to callers in natural language using text-to-speech, collects keypad input using DTMF tones, makes decisions based on what the caller pressed, routes the call to the right team or number, plays pre-recorded or dynamically generated audio, and handles thousands of simultaneous calls without breaking a sweat. The entire experience is defined in a simple, readable format that even non-engineers can understand, and that developers can build, deploy, and change in minutes.

## The Problem It Solves

Every business that receives phone calls faces the same challenge: not every call needs a live agent, but every caller deserves a fast and helpful experience. Without an IVR, every incoming call lands directly with whoever picks up first - creating chaos, misrouted calls, frustrated customers, and overwhelmed staff. Agents waste time handling calls that could be self-served. High-value calls get lost in the noise. There is no way to scale.

A cloud IVR changes this entirely. It acts as an intelligent first layer between your callers and your team. It qualifies, routes, and in many cases fully resolves calls without any human involvement. The result is lower operational cost, faster resolution times, and a dramatically better experience for callers.

## How Vobiz Powers Cloud IVR

Vobiz's IVR capability is built on its XML engine. When a call comes in, Vobiz fetches XML instructions from your server's URL and executes them in real time. The Gather element listens for keypad presses or speech, with a configurable timeout and number of digits. The Speak element reads out any text you provide using a natural text-to-speech voice - no pre-recording required. The Dial element connects the caller to a phone number or SIP endpoint. The Redirect element sends the call to a completely different set of XML instructions, enabling multi-level menus. The Play element plays audio files directly into the call.

This means your IVR logic lives entirely in your own application. Vobiz executes whatever your server returns. You can pull data from your CRM in real time, personalise the greeting with the caller's name, change routing logic based on time of day, business hours, or agent availability, and update everything instantly without touching any telecom configuration.

## Use Cases & Scenarios

* A hospital uses a Vobiz IVR to route incoming patient calls. Callers press 1 for appointments, 2 for billing, 3 for the pharmacy, and 4 to reach the emergency line. The appointment option plays available slots using text-to-speech pulled live from the hospital's scheduling system. Callers confirm their slot by pressing a key. No agent is involved unless the caller specifically requests one.
* An e-commerce company in Mumbai uses Vobiz IVR for their post-purchase support line. When a customer calls after placing an order, the IVR reads out their order status automatically using their phone number as a lookup key against the order database. Most callers get their answer in under 30 seconds without waiting in a queue.
* A logistics company uses a multi-level IVR to handle driver check-ins. Drivers call a number, press their zone code, and get routed to the regional dispatch team. The IVR also handles automated delivery confirmations - customers call in, enter their tracking number via keypad, and hear the current delivery status read out loud.
* A fintech startup uses Vobiz IVR for loan EMI reminders. When a customer calls in after receiving an SMS reminder, the IVR reads out their outstanding amount, due date, and payment options. Customers can connect to a payment support agent by pressing a key, or simply hang up after getting the information they needed.

## Why Choose Vobiz?

With Vobiz, your IVR is live in minutes - not days or weeks. You write XML, point a phone number at your server URL, and the IVR is running. Because the logic lives in your own application, you have total control. You are not locked into a no-code platform with limited options. You can add conditions, fetch live data, change menus on the fly, and build multi-level flows of any complexity. And because Vobiz is priced in INR with rates starting at ₹0.45 per minute, running a high-volume IVR for the Indian market costs a fraction of what global providers charge.

## Build an IVR with an AI agent

<Prompt description="Scaffold a multi-level IVR - VobizXML answer handler + DTMF routing in your language of choice." icon="microphone-lines" actions={["copy", "cursor"]}>
  Using the Vobiz MCP at `https://vobiz.ai/docs/mcp`, build me a working IVR:

  1. Read the `vobiz-voice-xml` skill from `mintlify://skills/voice-xml`.
  2. Use `search_vobiz` for "Gather DTMF input" and `xml/gather` for the verb syntax.
  3. Ask me what menu options I want (e.g. "1 for sales, 2 for support, 3 for billing").
  4. Pick a server framework - default to Python + FastAPI, but ask if I want Node/Express or Go.
  5. Generate two files:
     * `ivr_server.py` (or equivalent) - implements `POST /answer` returning VobizXML with `<Gather>` for the top menu, plus action endpoints for each digit that return follow-up XML.
     * `requirements.txt` (or equivalent dependency manifest).
  6. Include sample VobizXML for `<Gather action="/menu" finishOnKey="#" timeout="5">` with `<Speak>` prompts that match my menu options.
  7. Explain how to expose the server with ngrok and attach a Vobiz number to it via the Applications API.
</Prompt>

***


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.