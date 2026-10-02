> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Sarvam integration

> Take a Sarvam Samvaad voice agent live on a real phone number in minutes - Vobiz powers the Rent from Sarvam telephony option, so you complete KYC, buy an Indian number, and launch outbound campaigns or inbound deployments without leaving the Sarvam platform.

[Sarvam AI](https://sarvam.ai) builds India-first speech and language models. Its **Samvaad** platform lets you design, test, and deploy voice agents - and Vobiz powers the telephony underneath, so your agent can answer and place real phone calls.

## What you'll build

A Sarvam voice agent live on an Indian phone number, handling outbound campaigns and inbound calls. Everything happens inside the Sarvam platform: number provisioning, KYC, and call delivery all run on Vobiz behind the scenes.

<Note>
  **No separate Vobiz account, API keys, or SIP configuration required.** On the *Rent from Sarvam* path, Vobiz is embedded in the Sarvam platform. Numbers are billed through your Sarvam Credits, and the only Vobiz screen you see is the hosted KYC flow that Indian regulation requires.
</Note>

## Two ways to get telephony

Sarvam offers two telephony paths, and Vobiz supports both.

| | Rent from Sarvam | Bring your own telephony |
| - | - | - |
| **Powered by** | Vobiz, embedded | Your own provider account (Vobiz is one of the supported options) |
| **Number provisioning** | Buy inside Sarvam, one number at a time | Import numbers you already own |
| **Billing** | Sarvam Credits | Directly with your provider |
| **Setup time** | About 2 minutes plus KYC | Instant once credentials are added |
| **Best for** | Starting fresh, or wanting one bill | Existing numbers, rates, or trunk setup you want to keep |

This guide walks through **Rent from Sarvam** end to end, then covers connecting a Vobiz account you already have.

## Prerequisites

* **Sarvam account** → [Sign up at platform.sarvam.ai](https://platform.sarvam.ai/samvaad/home)
* **Sarvam Credits** on your account, enough to cover the number's monthly fee
* **KYC documents** for an Indian phone number - PAN plus Aadhaar if you're an individual, or company PAN plus GST if you're a business

## Step-by-step setup

<Steps>
  <Step title="Build a voice agent">
    Log in to the [Sarvam platform](https://platform.sarvam.ai/samvaad/home) and open the **Voice Agents** section from the left rail.

    Under **Build**, go to **Agents** and create your agent - prompt, voice, language, and any knowledge base it should draw on. Once it's ready, the home screen shows **Your agent is ready to deploy**.

    <img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/ioRJkFmz2hzmzXbS/images/sarvam/voice-agents-home.png?fit=max&auto=format&n=ioRJkFmz2hzmzXbS&q=85&s=62941d9bfa54a88476a0f4062f9d19e2" alt="Sarvam Voice Agents home screen showing an agent ready to deploy, with Build, Deploy, and Monitor sections in the sidebar" width="2000" height="1147" data-path="images/sarvam/voice-agents-home.png" />

    <Tip>
      Test the agent in the Sarvam playground before attaching a phone number. It's faster to iterate on the prompt there than over a live call.
    </Tip>
  </Step>

  <Step title="Open the telephony section">
    Under **Deploy**, click **Phone Numbers** - or go straight to [platform.sarvam.ai/samvaad/deploy/telephony](https://platform.sarvam.ai/samvaad/deploy/telephony).

    The **Take your agent live** screen presents both telephony options.

    <img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/ioRJkFmz2hzmzXbS/images/sarvam/take-agent-live.png?fit=max&auto=format&n=ioRJkFmz2hzmzXbS&q=85&s=e227a112b469cce17581c2f12b862e80" alt="Sarvam Take your agent live screen with two cards: Rent from Sarvam, marked Powered by Vobiz, and Bring your own telephony listing supported providers including Vobiz" width="1942" height="1256" data-path="images/sarvam/take-agent-live.png" />

    Click **Get started** on the **Rent from Sarvam** card. The *Powered by Vobiz* label at the bottom of that card is your telephony layer.
  </Step>

  <Step title="Select your business type">
    Indian phone numbers require KYC before they can be provisioned. Sarvam asks which kind of account you're verifying.

    <img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/ioRJkFmz2hzmzXbS/images/sarvam/select-business-type.png?fit=max&auto=format&n=ioRJkFmz2hzmzXbS&q=85&s=21ad1687e723108cfa85fa95b7de09af" alt="Select business type dialog with Individual and Business options" width="1216" height="646" data-path="images/sarvam/select-business-type.png" />

    | Choose | If you are |
    | - | - |
    | **Individual** | A freelancer or sole proprietor |
    | **Business** | A registered company, LLP, or firm |

    Pick the option that matches your account and click **Continue**.

    <Warning>
      Choose carefully - the verification path differs, and the documents you submit must belong to the entity that will own the number. A mismatch between the entity and the documents is the most common reason KYC comes back as failed.
    </Warning>
  </Step>

  <Step title="Complete KYC on Vobiz">
    Sarvam redirects you to a Vobiz-hosted KYC session. It's a three-step flow - **Type → Verify → Done**.

    <img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/ioRJkFmz2hzmzXbS/images/sarvam/kyc-verification-type.png?fit=max&auto=format&n=ioRJkFmz2hzmzXbS&q=85&s=ec7a253d644721fa32f3f19f252ced9b" alt="Vobiz hosted KYC session showing the Select Verification Type step with Individual and Company slash Business options and the documents each requires" width="1218" height="1544" data-path="images/sarvam/kyc-verification-type.png" />

    Confirm the verification type and submit the documents it asks for:

    | Verification type | Documents required |
    | - | - |
    | **Individual** - personal or proprietorship | PAN Card, and Aadhaar via DigiLocker |
    | **Company / Business** - companies, LLPs, firms | Company PAN, and GST Registration Number |

    Aadhaar is verified through **DigiLocker**, so you consent in DigiLocker rather than uploading a scan. Nothing is keyed in by hand.

    <Warning>
      The KYC link is time-limited - the expiry date is shown at the bottom of the session. If it lapses before you finish, return to the telephony section in Sarvam and start the flow again to get a fresh link.
    </Warning>

    When every document clears, you land on the confirmation screen and a confirmation email goes to the address on the account.

    <img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/ioRJkFmz2hzmzXbS/images/sarvam/kyc-complete.png?fit=max&auto=format&n=ioRJkFmz2hzmzXbS&q=85&s=38f2015647e58026aeb27b72f71e17e4" alt="Vobiz KYC Verification Complete screen confirming the submission and noting that a confirmation email will be sent" width="1308" height="1228" data-path="images/sarvam/kyc-complete.png" />

    <Check>
      KYC is done. You can close the window and return to Sarvam - number provisioning is now unlocked.
    </Check>

    <Note>
      Verification is usually near-instant, but a document can land in a pending state while it's checked against the source registry. If provisioning is still blocked after a few minutes, refresh the telephony page before retrying. Background on how this works: [Sub-Account KYC](/docs/sub-accounts/kyc/overview) and [KYC for India](/docs/compliance/india/kyc).
    </Note>
  </Step>

  <Step title="Buy a phone number">
    With KYC cleared, open the buy-number dialog from the **Phone Numbers** section and pick from the available inventory. Each row shows the number, its region, and the monthly fee.

    <img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/ioRJkFmz2hzmzXbS/images/sarvam/buy-phone-number.png?fit=max&auto=format&n=ioRJkFmz2hzmzXbS&q=85&s=7749560dae9d78b248ef8b30f46b9a04" alt="Sarvam Buy a phone number dialog listing available numbers with region and monthly fee, and a note that one number can be bought at a time" width="1204" height="1466" data-path="images/sarvam/buy-phone-number.png" />

    Select one number and click **Buy number**. You buy **one number at a time** - repeat the flow to add more.

    <Warning>
      Keep enough Sarvam Credits to cover renewals. If your balance is short on a number's renewal date, the number is released and any active campaigns or deployments using it are cancelled.
    </Warning>

    <Tip>
      Numbers are searchable, so if you want a specific pattern or a memorable ending, use the search box rather than scrolling the list.
    </Tip>
  </Step>

  <Step title="Launch an outbound campaign">
    Go to **Deploy → Outbound Campaigns** and create a campaign. Vobiz is already wired up, so the number you just bought is available immediately - no trunk setup, no credentials to paste.

    <img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/ioRJkFmz2hzmzXbS/images/sarvam/schedule-campaign.png?fit=max&auto=format&n=ioRJkFmz2hzmzXbS&q=85&s=53db565ff853a0f6026a6824fb1db3ca" alt="Sarvam Schedule campaign dialog, step 1 of 4, with fields for campaign name, agent and version, and a connection with phone numbers selectable by number or by group" width="1932" height="1220" data-path="images/sarvam/schedule-campaign.png" />

    The wizard runs in four steps - **Agent → Recipients → Schedule → Review & Launch**. On the first step:

    | Field | What to set |
    | - | - |
    | **Campaign name** | A label you'll recognise in Agent Analytics later |
    | **Select agent** | The agent to run, plus the **Version** to pin |
    | **Connection** | Your Vobiz-backed connection |
    | **Phone numbers** | The caller IDs to dial from - **By number** or **By group** |

    Then add recipients, set the schedule, review, and launch.

    <Tip>
      Pinning an explicit agent **Version** means a later prompt edit can't change the behaviour of a running campaign. Bump the version deliberately when you want the new prompt live.
    </Tip>

    <Note>
      For outbound calling in India, dial-rate pacing and number rotation have a real effect on connect rates and on how carriers treat your numbers. Worth reading before a large campaign: [Number utilization](/docs/best-practices/number-utilization), [Number health](/docs/best-practices/number-health-guide), and [UCC / DLT regulations](/docs/compliance/india/ucc).
    </Note>
  </Step>

  <Step title="Deploy an inbound agent">
    To have an agent answer calls, go to **Deploy → Inbound Calls** and create a deployment.

    <img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/ioRJkFmz2hzmzXbS/images/sarvam/create-inbound.png?fit=max&auto=format&n=ioRJkFmz2hzmzXbS&q=85&s=895a789a7dcdc24cb37887dd8743164f" alt="Sarvam Create inbound dialog, step 1 of 3, with deployment name, agent and version selectors, and connection with phone numbers" width="1864" height="1182" data-path="images/sarvam/create-inbound.png" />

    Three steps - **Agent → Availability → Review & Deploy**. Name the deployment, choose the agent and version, then attach the connection and the numbers that should reach it.

    **Availability** sets the hours the agent answers, in a timezone you choose.

    Once deployed, the detail view shows the live configuration and an **Active** badge:

    <img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/ioRJkFmz2hzmzXbS/images/sarvam/inbound-deployment-active.png?fit=max&auto=format&n=ioRJkFmz2hzmzXbS&q=85&s=ceb1de5d7c8b00374bb6bef4c1a3428d" alt="Sarvam inbound deployment detail view showing Active status, Deployment ID, App ID, the attached agent and language, the connected phone number, and the daily schedule" width="2000" height="658" data-path="images/sarvam/inbound-deployment-active.png" />

    | Field | What it tells you |
    | - | - |
    | **Deployment ID** | The identifier for this inbound deployment |
    | **App ID** | The underlying app backing it |
    | **Agent** | Which agent, version, and language answers |
    | **Connection** | The Vobiz connection and attached number |
    | **Schedule** | Answering hours and timezone |

    <Check>
      Call the number. Your agent picks up, and Vobiz carries the audio both ways.
    </Check>

    <Tip>
      Configuration is locked while a deployment is **Active**. Hit **Pause** to edit it, then resume - so plan changes for a quiet window if the number is taking live traffic.
    </Tip>
  </Step>
</Steps>

## Connect an existing Vobiz account

Already have a Vobiz account with numbers on it? Use the **Bring your own telephony** path instead - you keep your existing numbers and rates, and billing stays with Vobiz rather than moving to Sarvam Credits. No KYC step here either, because your account is already verified.

On the **Take your agent live** screen, click **Connect** on the **Bring your own telephony** card, then choose **Vobiz**.

<Steps>
  <Step title="Get your credentials">
    The first tab points you at the two values Sarvam needs. Sign in to the [Vobiz Console](https://console.vobiz.ai) - your **Auth ID** and **Auth Token** are shown directly on the main dashboard.

    | Credential | Looks like | Where |
    | - | - | - |
    | **Auth ID** | `MA_XXXXXXXX` | Vobiz Console dashboard |
    | **Auth Token** | A long secret string | Vobiz Console dashboard |

    <Warning>
      Treat your Auth Token like a password - anyone holding both values can act on your account. Full detail in [API authentication](/docs/api-reference/authentication).
    </Warning>
  </Step>

  <Step title="Enter the details">
    On the **Enter details** tab, paste both values and name the connection.

    <img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/ioRJkFmz2hzmzXbS/images/sarvam/connect-vobiz-credentials.png?fit=max&auto=format&n=ioRJkFmz2hzmzXbS&q=85&s=623430c0bd3d0f5127315bda997faa7e" alt="Sarvam Connect Vobiz dialog on the Enter details tab, with fields for connection name, Auth ID, and Auth Token, marked Encrypted and secure" width="1514" height="1248" data-path="images/sarvam/connect-vobiz-credentials.png" />

    | Field | What to enter |
    | - | - |
    | **Connection name** | A label for this connection. Sarvam pre-fills one from your organisation name - keep it, or rename it if you'll connect more than one Vobiz account |
    | **Auth ID** | Your account Auth ID |
    | **Auth Token** | Your account Auth Token. Use the eye toggle to check for stray whitespace before continuing |

    Credentials are stored encrypted. Click **Continue**.

    <Tip>
      Running separate Vobiz accounts for staging and production? Give each connection a name that says which is which - the connection picker in the campaign and inbound wizards shows only this label.
    </Tip>
  </Step>

  <Step title="Configure inbound">
    The final tab sets up inbound so calls arriving on your Vobiz numbers reach a Sarvam agent. Complete it to finish the connection.

    <Check>
      The connection is live. Your Vobiz numbers now appear in the **Phone numbers** picker when you create an outbound campaign or an inbound deployment - steps 7 and 8 above.
    </Check>
  </Step>
</Steps>

<Tip>
  Don't have an account yet? [Create one](https://console.vobiz.ai/auth/signup), then see [Buy a phone number](/docs/buy-a-phone-number) for provisioning in the Vobiz Console. Once numbers are on the account, they show up in Sarvam's number picker.
</Tip>

<Note>
  Both paths deliver calls over the same Vobiz network. The difference is purely commercial - who provisions the number and who bills you for it.
</Note>

## Monitoring your calls

Sarvam's **Monitor → Agent Analytics** covers agent-level behaviour: conversations, outcomes, and transcripts.

For the telephony layer - what the carrier did with each call - Vobiz records a [Call Detail Record](/docs/cdr) per call, including a [hangup cause](/docs/concepts/hangup-causes) that explains exactly why a call ended. That's the layer to check when a call never connected, dropped early, or reached voicemail instead of a person.

## Resources

| Resource | Link |
| - | - |
| Sarvam platform | [platform.sarvam.ai](https://platform.sarvam.ai/samvaad/home) |
| Sarvam telephony section | [Deploy → Telephony](https://platform.sarvam.ai/samvaad/deploy/telephony) |
| Sarvam documentation | [docs.sarvam.ai](https://docs.sarvam.ai) |
| KYC requirements for India | [Compliance → KYC](/docs/compliance/india/kyc) |
| Number best practices | [Number utilization](/docs/best-practices/number-utilization) |
| Vobiz support | [support@vobiz.ai](mailto:support@vobiz.ai) |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.