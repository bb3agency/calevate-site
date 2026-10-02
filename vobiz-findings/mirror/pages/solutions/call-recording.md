> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Call Recording

> Capture, store, and analyse call audio for compliance, QA, and AI training. Vobiz dual-channel recording API delivers transcripts and webhooks across 130+ countries.

## What is Call Recording?

Call recording is the capture of phone call audio - either in full or in selected segments - stored as a digital file that can be retrieved, reviewed, transcribed, and analyzed at any time. In a programmable telephony context, call recording is a sophisticated capability with multiple dimensions: when to start and stop, which parties to capture, what format to save in, where to store it, how to access it programmatically, and how to extract meaning from it after the fact.

Vobiz provides full-featured call recording that can be started and stopped at any point during a live call, with support for separate audio channels, automated transcription, HTTP callbacks when recording completes, and a complete API for managing, retrieving, exporting, and deleting recordings at scale.

## The Problem It Solves

Businesses that handle customer calls face significant pressure from multiple directions. Regulators want documented evidence that calls were handled correctly. Legal teams want recordings for dispute resolution. Quality assurance teams want to evaluate agent performance. Trainers want real examples for onboarding new agents. Product teams want to understand customer language, objections, and feedback. All of these needs converge on one requirement: reliable, accessible, and queryable call recordings.

Without programmable recording, businesses either record everything indiscriminately - creating vast archives of unindexed audio - or record nothing, losing valuable evidence and insight. Vobiz lets you record exactly what you need, when you need it, with the metadata to find it later.

## How Vobiz Powers Call Recording

Vobiz recording can be initiated via the Record API at any point during an active call. You can record in MP3 or WAV format. MP3 files are smaller and faster to transfer, making them ideal for most business use cases. WAV files preserve full audio fidelity, which is useful when the recording will be processed by speech-to-text models that benefit from uncompressed audio.

You can record in mono - both parties in a single channel - or in stereo, where the caller's voice goes to the left channel and the agent's voice to the right. Stereo recording is particularly valuable when you are running the audio through AI analysis tools, because it allows the model to distinguish between the two speakers without a diarisation step.

Automated transcription is available for English recordings up to four hours in length, with turnaround typically under five minutes. When a recording completes, Vobiz sends an HTTP callback to your configured URL with the recording file URL, duration, and status. Your application can then store the link, trigger downstream processing, notify a quality assurance team, or push the transcript into your CRM.

The Recording API allows you to list all recordings, retrieve individual recordings by ID, export historical recordings in bulk, and delete recordings when retention periods expire. This makes it straightforward to build compliant recording management into your application.

## Use Cases & Scenarios

* A collections agency records all outbound calls for regulatory compliance. Every call is stored with the agent ID, the customer number, the timestamp, and the duration. When a dispute arises, the compliance team queries the Recording API for calls from a specific agent on a specific date and retrieves the audio within seconds.
* A sales training company records calls from their sales floor in stereo. They run the left and right channels separately through a speech analysis tool that scores each agent's use of approved language, talk-to-listen ratio, and handling of objections. The output is used for weekly coaching sessions.
* A telehealth platform records doctor-patient consultations with full consent from both parties. Recordings are stored securely and linked to the patient's record. Patients can request access to their consultation recordings, and doctors use them to review what was communicated during a visit.
* A customer success team at a B2B SaaS company records all renewal calls. The transcripts are analysed monthly to identify the most common reasons customers express concern about renewing, informing product roadmap decisions and churn reduction initiatives.

## Why Choose Vobiz?

Vobiz recording is built into the same API used for everything else - no separate service, no additional credentials. You can start a recording, retrieve it, and delete it all within the same integration. The transcription feature removes the need for a third-party transcription service for standard English recordings. The bulk export endpoint also makes it practical to integrate Vobiz recording into data pipelines, compliance archives, or analytics workflows.

***


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.