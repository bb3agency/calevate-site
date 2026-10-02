> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Do you support IVR?

> Build fully programmable IVR menus on Vobiz using Gather, Speak, Play, and SIP transfer XML - supporting DTMF input, speech recognition, and dynamic branching logic.

**Yes.** Interactive Voice Response (IVR) systems are fundamentally supported via our powerful Voice XML API platform. You can build highly dynamic, multi-layered branching trees and conversational menus.

## Building Voice Menus

Vobiz does not limit you to a drag-and-drop web builder. Instead, you have full programmatic control by returning valid XML from your own backend webhooks.

* **Speech & DTMF input** *([`<Gather>`](/docs/xml/gather))* - The core of any IVR is collecting user input. Prompt the caller ("Press 1 for Sales or 2 for Support") or ask a free-form question ("How can I help you today?"). Vobiz fires a webhook back to your server containing the digits pressed or the transcribed speech text.
* **Text-to-Speech** *([`<Speak>`](/docs/xml/speak))* - Combined with `<Gather>`, the `<Speak>` tag synthesizes prompts on the fly using neural AI voices across multiple languages - useful for variable content like account balances.
* **Playing audio** *([`<Play>`](/docs/xml/play))* - Point `<Play>` at an accessible MP3 or WAV URL to broadcast pre-recorded studio prompts or hold music.
* **SIP routing & transfer** *([call transfer methods](/docs/faq/call-transfer))* - Branch calls out via SIP based on user navigation. Connect to an external SIP trunk or E.164 number with `<Dial>`, or perform a native network-level blind/attended transfer via RFC 3515 SIP REFER if your endpoint supports it.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.