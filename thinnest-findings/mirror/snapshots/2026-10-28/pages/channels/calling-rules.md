> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Calling rules by country (US TCPA, UK PECR, India TRAI)

> What ThinnestAI does for you when your agent calls people, and what the law in the US, the UK and India leaves to you.

When your agent calls or messages people, **you** are the caller in the eyes of
the law. ThinnestAI gives you tools that help you keep to the rules, but it does
not decide whether you may call someone, and it does not check for you. This
page sets out which part is which, country by country.

> [!WARNING]
>
> **This is not legal advice.** It is a short guide to rules that change, and
> that apply differently to marketing calls, service calls and calls a customer
> asked for. Check with a lawyer who knows your market before you run outbound
> calls, and read the regulator's own guidance linked below.

## What the platform does for you

* **A do-not-contact list.** Numbers on the list on the **Contacts** page under
  *Do not contact* are never reached by a campaign or an API call, on any
  channel. It is checked as each call is placed, so adding a number stops a
  campaign that is already running. See [Calling
  campaigns](https://docs.thinnest.ai/channels/voice-campaigns.md#who-gets-called).
* **"Don't call me again."** When a caller clearly asks not to be called again,
  your agent puts their number on that list itself, unless you switch this off
  for the agent. See ["Don't call me again"](https://docs.thinnest.ai/channels/voice.md#dont-call-me-again).
* **Opt-outs.** Anybody who has asked you to stop is left out of a campaign
  even when they are in the file you upload.
* **Calling hours you set.** A campaign calls only in the hours you give it,
  and an API call only in the `callingHours` you send. Hours are read on the
  **called person's clock**, worked out from their number: 9am on a London
  number means 9am in London. For a country with several time zones, such as
  the United States, a campaign keeps inside your hours at both ends of the
  country. See [When it calls, and when it
  stops](https://docs.thinnest.ai/channels/voice-campaigns.md#when-it-calls-and-when-it-stops).
* **Pacing.** A cap on calls per hour, and retries that keep to your hours.
* **Honest about being an AI.** If someone asks whether they are talking to an
  AI, a bot or a real person, the agent says it is an AI assistant, on every
  channel and whatever your instructions say. See [Behaviour](https://docs.thinnest.ai/agent/behaviour.md).

## What the platform does not do

> [!WARNING]
>
> * **There are no calling hours of our own.** A campaign with no hours set, or
>   an API call with no `callingHours`, may ring at any hour. Set hours that
>   keep to the law where the person you are calling lives.
> * **No register screening.** We do not check your lists against the US
>   National Do Not Call Registry, the UK's TPS or CTPS, India's DND register or
>   any other register.
> * **No consent check.** Ticking "these people agreed to be called" when you
>   upload a list is a claim you make and we record. We do not verify it.
> * **No automatic announcements on phone calls.** An agent does not say on its
>   own that the call is recorded or that it is an AI. If the law requires
>   either, put it in your agent's first words. (Website calls show *This call
>   is recorded* when recording is on, and an agent always answers truthfully
>   if a caller asks whether the call is recorded.)

## United States: TCPA

The Telephone Consumer Protection Act (TCPA) and the Federal Communications
Commission's (FCC) rules decide most of what an outbound AI call needs.

| You are responsible for | What it means in practice |
| - | - |
| **Consent** | The FCC treats AI-generated voices as "artificial" voices under the TCPA. Calls using one generally need the called person's prior express consent, and marketing calls need prior express **written** consent. Keep the proof. |
| **Do Not Call** | Do not make telemarketing calls to numbers on the National Do Not Call Registry without a valid exception, and keep your own internal do-not-call list. |
| **Calling hours** | Telemarketing calls only between **8am and 9pm** in the called person's local time. Set your campaign hours to match. |
| **Identification and opt-out** | Say who is calling at the start of the call, and give people a way to opt out. |
| **State rules** | Several states have their own calling laws, some stricter than the TCPA on hours, consent or call frequency. |
| **Recording** | Some states, California among them, require every party's consent to record a call. |

Read: [FCC: Telemarketing and robocalls](https://www.fcc.gov/general/telemarketing-and-robocalls)
and the [National Do Not Call Registry](https://www.donotcall.gov/).

## United Kingdom: PECR

Marketing calls in the UK are governed by the Privacy and Electronic
Communications Regulations (PECR), enforced by the Information Commissioner's
Office (ICO), alongside UK GDPR for the personal data itself.

| You are responsible for | What it means in practice |
| - | - |
| **TPS and CTPS** | Do not make live marketing calls to numbers registered with the Telephone Preference Service (TPS) or the Corporate TPS, unless that person has told you they are happy to get your calls. |
| **Automated calls** | Automated marketing calls need the person's specific prior consent. Whether a given AI call counts as automated is a question to settle with your adviser before you call. |
| **Identification** | Say who is calling, show a number the person can call back, and give an address or freephone number if they ask. |
| **Opt-outs** | Stop calling anybody who asks you to. |
| **Calling hours** | PECR sets no fixed hours. The platform sets none either: choose hours your customers would think reasonable, and set them on the campaign. |
| **Recording** | Tell people a call is recorded and why, as UK GDPR's transparency rules expect. |

Read: [ICO: direct marketing and PECR](https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/)
and the [Telephone Preference Service](https://www.tpsonline.org.uk/).

## India: TRAI

Commercial calls in India are governed by the Telecom Regulatory Authority of
India's (TRAI) rules on unsolicited commercial communication, alongside the
Digital Personal Data Protection Act for the personal data.

| You are responsible for | What it means in practice |
| - | - |
| **Registration** | Register as a sender or telemarketer where TRAI's rules require it, and place promotional calls from the number series assigned for them (140). |
| **DND preferences** | Do not make promotional calls to people who have blocked them on the National Customer Preference Register (DND), unless you hold their recorded consent. |
| **Calling hours** | Keep promotional calls to daytime hours, for example 9am to 9pm. Set the hours on the campaign: the platform does not. |
| **Consent and notice** | Hold consent for the purpose you are calling about, and give people the notice the data protection law requires. |
| **Complaints** | Complaints about unwanted calls go against the number that called. Repeated complaints can get a number disconnected. |

Read: [TRAI](https://www.trai.gov.in/), where the regulations on unsolicited
commercial communication and the DND register are published.

## The UAE and other countries

Every country has its own rules on telemarketing, consent, Do Not Call
registers and calling hours. The UAE, for example, has its own telemarketing
regulations and a Do Not Call Registry. For anywhere not covered above, the
hours you set on your campaign are the only hours the platform keeps to, so
check the local rules before you call.

## Where this is written down

Our [Terms of Service](https://thinnest.ai/legal/terms) (section 6) put consent,
Do Not Call screening, calling hours and disclosures on the business that
places the calls, and the [Acceptable Use
Policy](https://thinnest.ai/legal/acceptable-use) lists what may never be done.
If you resell ThinnestAI under your own brand, your clients' calls are yours to
answer for too.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.