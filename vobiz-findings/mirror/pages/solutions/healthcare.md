> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Healthcare

> Automate patient appointment booking, triage, reminders, and teleconsultation with Vobiz. Compliant healthcare voice API serving clinics, hospitals, and health-tech platforms across 130+ countries.

## What is Healthcare?

**Voice Communication in Healthcare**

Healthcare is one of the most communication-intensive industries in the world. Every patient interaction - from booking an appointment to receiving a diagnosis to managing an ongoing treatment - involves multiple touchpoints where clear, timely, reliable voice communication makes the difference between good outcomes and bad ones. Missed appointments cost hospitals revenue and deny other patients care. Delayed follow-up calls allow conditions to worsen. Poor call routing leads patients to the wrong department, creating frustration at moments when they are already vulnerable.

Vobiz gives healthcare providers, clinics, hospitals, diagnostic centres, teleconsultation platforms, and health-tech startups the voice infrastructure to build communications experiences that match the care they provide to patients.

## The Problem It Solves

**Appointment Management at Scale**

For any healthcare facility with more than a handful of providers, appointment management by phone is a constant operational challenge. Patients call to book, reschedule, and cancel. Each call takes time. Staff spend a significant portion of their day on the phone for administrative tasks rather than clinical work.

With Vobiz, appointment booking and management can be partially or fully automated. An IVR built on Vobiz's XML engine greets incoming callers, lets them select the type of appointment or the department they need, checks real-time availability from the scheduling system, and presents options using text-to-speech. The patient confirms their slot using the keypad. No staff member is required for the transaction.

For outbound reminders, Vobiz's automated calling API contacts patients 24 and 48 hours before their appointment, confirms their details, and asks them to press 1 to confirm or 2 to reschedule. Reschedule requests are routed to a booking agent or handled by the IVR. No-show rates in healthcare settings typically drop significantly once automated voice reminders are in place.

## How Vobiz Powers Healthcare

**Patient Privacy and Call Recording**

Teleconsultation platforms have a specific requirement that Vobiz addresses well: the ability to record doctor-patient calls for clinical documentation purposes, with full consent capture as part of the call flow. The IVR can play a consent notice at the start of every consultation call and use the DTMF Gather element to capture the patient's consent before the call begins recording. Recordings are stored and linked to patient records programmatically through the recording callback webhook.

For hospitals and clinics, call recording of administrative calls provides protection against billing disputes and service complaints. Every call is recorded, indexed by the patient's number and timestamp, and retrievable instantly via the Recording API when needed.

## Use Cases & Scenarios

* **AI-Assisted Triage and Support**: Health-tech companies are deploying AI voice agents on Vobiz to handle first-contact triage and general health information queries. An AI agent built on VAPI or Retell AI, connected to Vobiz for telephony, can handle questions about symptoms, medication timing, and appointment availability around the clock. When a patient's query indicates they may need urgent attention, the AI hands off to a human nurse or duty doctor using the Transfer API - with the full conversation transcript already available on the human's screen.
* This model is particularly valuable for teleconsultation platforms operating in Tier 2 and Tier 3 cities, where specialist availability is limited. An AI voice agent that can handle the high volume of general queries allows the limited number of specialist humans to focus exclusively on complex cases.

## Why Choose Vobiz?

**Compliance and Regulatory Fit**

Healthcare in India operates under strict guidelines around patient data and communication. TRAI compliance for outbound calling is mandatory, and Vobiz's India-first infrastructure ensures all calls are made within regulatory boundaries. INR billing with GST invoicing makes procurement straightforward for hospital accounts teams. And with 99.99% uptime, the platform is reliable enough for mission-critical patient communication.

***


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.