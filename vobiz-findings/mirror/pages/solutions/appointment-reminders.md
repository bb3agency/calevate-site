> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Appointment Reminders

> Cut no-show rates with automated voice appointment reminders that confirm, reschedule, or cancel via keypad - deployed across 130+ countries. Vobiz delivers DTMF-interactive outbound calls at scale for healthcare, finance, and services.

## What is Appointment Reminders?

An appointment reminder call is an automated outbound call that proactively contacts a customer before a scheduled appointment, confirms the details, and asks them to confirm or reschedule using their keypad. It is one of the most straightforward applications of voice automation, but also one of the highest ROI. In industries where no-shows carry significant costs - healthcare, financial advisory, automotive service, education, hospitality - reducing the no-show rate by even a few percentage points has a measurable bottom-line impact.

Vobiz lets you build a fully automated appointment reminder system using the outbound calling API and a small amount of XML logic. The system runs entirely on autopilot once configured, reaching hundreds or thousands of patients, clients, or customers every day.

## The Problem It Solves

No-shows are expensive. A doctor who blocks an hour for a patient who does not arrive loses both the revenue and the opportunity to treat another patient. A car service centre with an uncollected booking cannot reallocate the mechanic's time efficiently. A financial advisor with a missed meeting cannot reschedule until the client responds to emails - often days later.

SMS reminders help, but their response rates are lower than a voice call, and they do not allow for immediate confirmation with a keypad press. Email reminders are even less effective for time-sensitive confirmations. A voice call, especially one that is personalised and conversational, gets the attention of the recipient and requests an immediate, simple response. It is the most effective reminder channel available.

## How Vobiz Powers Appointment Reminders

An appointment reminder system on Vobiz works as follows. Your application maintains a list of upcoming appointments. A scheduled job runs periodically - typically 24 hours and again 2 hours before each appointment - and for each upcoming appointment, it calls the Vobiz outbound calling API with the patient's or client's phone number.

When the call is answered, Vobiz fetches the XML from your answer URL. The XML uses the Speak element to read a personalised message: "Hello \[Name], this is a reminder that you have an appointment with \[Doctor/Advisor/Service] on \[Date] at \[Time]. Press 1 to confirm, press 2 to reschedule, or press 3 to cancel." The Gather element then listens for a keypad press with a configurable timeout.

The result - confirmed, reschedule requested, or cancelled - is sent to your application via the callback URL that your Gather XML points to. Your application updates the appointment status, triggers a reschedule workflow if needed, or releases the slot for other bookings. The hangup\_url callback confirms the call completed and provides the full call metadata.

When machine detection is enabled, calls that reach voicemail are handled differently - playing a shorter message without the DTMF prompt, since voicemail cannot respond interactively.

## Use Cases & Scenarios

* A dental clinic chain with fifteen locations runs automated reminder calls for all appointments booked more than 48 hours in advance. The system dials each patient 24 hours before their appointment. Confirmed appointments are flagged in the clinic management software. Reschedule requests trigger an SMS with a booking link. The clinic reduced no-shows from 22% to 11% in the first month, recovering over ₹3 lakh per month in previously lost revenue.
* A financial advisory firm sends automated reminder calls to clients before quarterly review meetings. The call is personalised with the client's name and the meeting date and time. If the client cannot make it, pressing 2 connects them directly to the firm's scheduling team to reschedule. The firm found that clients who received a voice reminder were 3x more likely to join the meeting than those who received only an email reminder.
* An automotive service centre uses Vobiz reminders to contact customers the day before their car service is due. The call confirms the appointment time, reminds them to bring their car documents, and offers a rescheduling option. Customers who reschedule are immediately offered the next available slot via a transfer to the booking team.
* An educational institution sends reminder calls to parents 48 hours before parent-teacher meetings. The call is in the regional language - using text-to-speech in Hindi or the local language - which significantly improves response rates compared to English-only SMS reminders.

## Why Choose Vobiz?

Appointment reminder calls are a high-volume, low-value-per-call use case - meaning the economics of the telephony provider matter enormously. At ₹0.45 per minute, a 30-second reminder call costs less than ₹0.25. Running 1000 reminder calls per day costs under ₹250 in telephony alone. This is an order of magnitude cheaper than equivalent global providers billing in USD, and dramatically cheaper than paying a human to make reminder calls.

***


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.