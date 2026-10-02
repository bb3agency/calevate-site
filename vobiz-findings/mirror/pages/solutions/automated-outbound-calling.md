> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Automated Outbound Calling

> Reach thousands of customers with personalised voice calls at scale. Vobiz bulk outbound API supports 1000 simultaneous calls with AMD across 130+ countries.

## What is Automated Outbound Calling?

Automated outbound calling is the ability for your application to programmatically initiate phone calls to large lists of customers, prospects, or contacts - at scale, at the right time, with the right message, and with intelligence about whether a human or a machine answered. It is the technology behind appointment reminder calls, delivery notification calls, payment due date alerts, promotional voice broadcasts, and any scenario where your business needs to proactively reach customers by phone without a human agent dialling each number.

With Vobiz, automated outbound calling is a single API call that can trigger up to 1,000 simultaneous outbound calls, each customized with the recipient's name, account details, or any dynamic data from your system. The call plays a message, collects a keypad response, detects whether it reached a human or a voicemail, and reports back to your application with full status for every call.

## The Problem It Solves

Businesses that need to proactively communicate with thousands of customers face an impossible trade-off without automation: hire armies of telecallers and pay per-person costs, or give up on voice communication entirely and rely solely on SMS and email - which have far lower open rates and urgency signals than a phone call.

Automated outbound calling bridges this gap. It delivers the reach and attention-getting power of a phone call at the economics of a digital channel. And with machine detection, it avoids wasting call minutes on voicemails and answering machines - only connecting to calls that a real person picks up.

## How Vobiz Powers Automated Outbound Calling

Vobiz's outbound calling API accepts a comma-separated list of destination numbers - up to 1000 - in a single request. Each destination can be a phone number or a SIP endpoint. When a call is answered, Vobiz fetches XML instructions from your answer URL and executes them. Your XML can speak a personalised message using text-to-speech, play a pre-recorded audio file, collect a DTMF response from the caller, or connect the caller to a live agent.

Machine detection is a critical feature for outbound campaigns. When enabled, Vobiz analyses the audio at the beginning of the answered call to determine whether a human or a machine (voicemail, IVR, fax) picked up. If a machine is detected, the call can be automatically hung up or redirected to a voicemail-specific message URL. This means your agents only handle calls that reached real people, and your campaign costs only include calls that delivered value.

The `hangup_url` callback is sent to your server every time a call ends, carrying the full call status - duration, answer time, end time, hangup cause, and call UUID. This allows you to track delivery at the individual call level, retry failed calls, segment your contact list by response type, and feed outcome data back into your CRM or campaign management system.

You can also set a `time_limit` on outbound calls, capping their maximum duration and ensuring your campaign costs stay within budget even if a small number of calls run unexpectedly long.

## Use Cases & Scenarios

* A logistics company runs a daily automated outbound calling campaign to notify customers of scheduled deliveries. Each customer receives a personalised call - "Your order will arrive today between 2pm and 5pm. Press 1 to confirm you will be available, press 2 to reschedule." The DTMF responses feed directly into the delivery management system, improving first-attempt delivery rates significantly.
* An NBFC runs automated EMI reminder calls three days before the due date and on the due date itself. The call is personalised with the customer's name, the due amount, and the due date. If the customer presses 1, they are connected to a payment support agent. If they press 2, they hear payment options read out by text-to-speech. The campaign reaches 50,000 customers per day at a fraction of the cost of running the equivalent number of agent calls.
* A hospital chain runs automated appointment reminder calls 24 hours before each scheduled appointment. The call asks patients to press 1 to confirm or press 2 to reschedule. Confirmed appointments are flagged in the hospital management system. Reschedule requests connect the patient to the appointments team. No-shows dropped by 35% after implementing the campaign.
* A political campaign team uses Vobiz bulk outbound calling to deliver a voice message from the candidate to 200,000 voters on election eve. The machine detection ensures the message only plays to live recipients, and the campaign team receives a real-time report of how many calls were answered, how many went to voicemail, and how many failed.

## Why Choose Vobiz?

Vobiz's bulk outbound calling supports 1,000 simultaneous calls in a single API request - a capability that most Indian telephony providers either do not offer or charge enterprise rates for. Machine detection is built in as a parameter to the same API call, not a separate service. Per-minute pricing in INR keeps outbound campaign costs transparent and predictable. The callback architecture also gives your application complete visibility into every call's outcome without polling.

***


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.