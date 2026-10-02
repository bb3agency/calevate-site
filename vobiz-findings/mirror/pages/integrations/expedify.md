> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Expedify integration

> Connect Expedify's CRM and AI calling platform to Vobiz - configure outbound and inbound voice with your Auth ID, Auth Token, and Caller IDs from the Expedify dashboard, no code required.

Expedify is a CRM and outreach platform with built-in AI agents - a Calling Agent, a Customer Support Agent, and a Lead Qualifier Agent among them. The **Vobiz Voice** integration is available directly from Expedify's integrations marketplace, and connects your Vobiz account so Expedify can place and receive calls on a number you already own.

<Info>
  This integration is configured entirely in the Expedify dashboard and the Vobiz Console. There is no code to write and nothing to host.
</Info>

## What you get

* **Outbound calls** - placed manually by a rep, or driven by an Expedify AI calling agent, from a Vobiz Caller ID you nominate.
* **Inbound calls** - calls to your Vobiz number routed into Expedify through a Vobiz application.
* **Recording and transcription** - Vobiz records the call; Expedify transcribes it with its own transcriber when you enable that option.

## Prerequisites

<Steps>
  <Step title="A Vobiz account with API credentials">
    You need your **Auth ID** and **Auth Token**. Both are on the Console [Dashboard](https://console.vobiz.ai), under **API credentials**.
  </Step>

  <Step title="A Vobiz phone number">
    At least one DID to use as a Caller ID. See [Buy a phone number](/docs/buy-a-phone-number) if you do not have one yet.
  </Step>

  <Step title="An Expedify account">
    Access to the Expedify organization where you want Vobiz connected. Integrations are scoped per organization - if your account has several, confirm you are in the right one before you start.
  </Step>
</Steps>

## Step 1: Open Expedify's integration settings

In Expedify, go to **Settings → Integrations**.

<img className="block mx-auto rounded-xl border border-gray-200" style={{ width: "100%", maxWidth: "222px" }} src="https://mintcdn.com/vobizai/AyHCnbXTYvgd7w2P/images/expedify/expedify-settings-integrations.png?fit=max&auto=format&n=AyHCnbXTYvgd7w2P&q=85&s=3dd3510c2939f316a1ea751a3f778103" alt="Expedify Settings menu with Integrations selected" width="222" height="525" data-path="images/expedify/expedify-settings-integrations.png" />

## Step 2: Add the Vobiz Voice integration

Open the **Add Integrations** tab, find **Vobiz Voice** under the **Voice** category, and click **Configure**.

<img className="block w-full rounded-xl border border-gray-200" src="https://mintcdn.com/vobizai/AyHCnbXTYvgd7w2P/images/expedify/expedify-add-integration.png?fit=max&auto=format&n=AyHCnbXTYvgd7w2P&q=85&s=3cbad9f635c602fe3555186a78dd4851" alt="Expedify Add Integrations screen showing the Vobiz Voice card under the Voice category" width="1912" height="867" data-path="images/expedify/expedify-add-integration.png" />

<Note>
  The configuration panel has two tabs, **Configuration** and **Connection Guide**. Everything in this guide happens on the **Configuration** tab.
</Note>

## Step 3: Get your Vobiz Auth ID and Auth Token

Log in to the [Vobiz Console](https://console.vobiz.ai). Your **Auth ID** and **Auth Token** are on the **Dashboard**, in the **API credentials** card. Use the copy icon next to each - the Auth Token is masked until you reveal it.

<img className="block w-full rounded-xl border border-gray-200" src="https://mintcdn.com/vobizai/AyHCnbXTYvgd7w2P/images/expedify/vobiz-console-api-credentials.png?fit=max&auto=format&n=AyHCnbXTYvgd7w2P&q=85&s=d8fc846f4610296a42055e913315b146" alt="Vobiz Console Dashboard showing Auth ID and Auth Token in the API credentials card" width="1912" height="622" data-path="images/expedify/vobiz-console-api-credentials.png" />

<Warning>
  Treat your Auth Token like a password. Anyone who has it can place calls and spend your Vobiz balance. Paste it straight into Expedify and nowhere else. If it leaks, regenerate it from the Console immediately - the old token stops working as soon as you do.
</Warning>

## Step 4: Enter your credentials

Back in Expedify, name the integration - `Vobiz Expedify`, for example - then paste your **Auth ID** and **Auth Token**.

Set **Default "From" Number Source** and **Default "To" Number Source**. These decide which field Expedify reads when it places a call. The example below uses *User's Phone Number* and *Contact's Phone Number*.

<img className="block w-full rounded-xl border border-gray-200" src="https://mintcdn.com/vobizai/AyHCnbXTYvgd7w2P/images/expedify/expedify-configuration-credentials.png?fit=max&auto=format&n=AyHCnbXTYvgd7w2P&q=85&s=a3d579ae15ead8cd4c44ce2ca48fcdbb" alt="Expedify Vobiz Voice configuration panel with Integration Name, Auth ID, and Auth Token fields" width="1915" height="867" data-path="images/expedify/expedify-configuration-credentials.png" />

## Step 5: Add a Caller ID

Scroll down to **Caller IDs**. You need at least one Vobiz number here before Expedify can place an outbound call.

Click **+ Add Caller ID**, enter the number in E.164 format, and give it a label such as `Sales`. You can add several and mark one as the default.

Then set the call handling options:

* **Enable Call Recording** - on by default. Vobiz records the call.
* **Enable Automatic Transcription** - off by default. Expedify converts the recording to text using its own transcriber.

<img className="block w-full rounded-xl border border-gray-200" src="https://mintcdn.com/vobizai/AyHCnbXTYvgd7w2P/images/expedify/expedify-caller-ids-recording.png?fit=max&auto=format&n=AyHCnbXTYvgd7w2P&q=85&s=4f4f526dcb6cfc0c28bdbb7139a260eb" alt="Expedify configuration showing Caller IDs with a label, Enable Call Recording, and Enable Automatic Transcription" width="1912" height="866" data-path="images/expedify/expedify-caller-ids-recording.png" />

<Note>
  Need a number first? In the Vobiz Console go to **Numbers → My number** and click **Buy New Number**.

  <img className="block w-full rounded-xl border border-gray-200" src="https://mintcdn.com/vobizai/AyHCnbXTYvgd7w2P/images/expedify/vobiz-console-buy-number.png?fit=max&auto=format&n=AyHCnbXTYvgd7w2P&q=85&s=ec7bcf573beac9d6c7d9973e2d701063" alt="Vobiz Console My Number page with the Buy New Number button" width="1912" height="657" data-path="images/expedify/vobiz-console-buy-number.png" />
</Note>

## Step 6: Create the integration

Click **Create Integration**. It appears under **Active** integrations, marked **Active** - and **Default**, if it is your only voice integration.

<img className="block mx-auto rounded-xl border border-gray-200" style={{ width: "100%", maxWidth: "821px" }} src="https://mintcdn.com/vobizai/AyHCnbXTYvgd7w2P/images/expedify/expedify-active-integration.png?fit=max&auto=format&n=AyHCnbXTYvgd7w2P&q=85&s=0c7165cb20a0cf4e533dc08877570220" alt="Expedify Active integrations list showing Vobiz Expedify marked Active and Default" width="821" height="471" data-path="images/expedify/expedify-active-integration.png" />

<Check>
  Outbound is ready. Expedify can now place calls - manually or through an AI calling agent - using your Vobiz Caller ID.
</Check>

## Verify with a test call

Open the integration from the **Active** tab and click **Test Call**.

<img className="block mx-auto rounded-xl border border-gray-200" style={{ width: "100%", maxWidth: "917px" }} src="https://mintcdn.com/vobizai/AyHCnbXTYvgd7w2P/images/expedify/expedify-webhook-test-call.png?fit=max&auto=format&n=AyHCnbXTYvgd7w2P&q=85&s=5bf56b04e7792c3cf8429e77ff9671bf" alt="Expedify integration detail panel showing the Webhook URL, Test Call, and Save Changes buttons" width="917" height="780" data-path="images/expedify/expedify-webhook-test-call.png" />

Enter a **From Number** and a **To Number** in E.164 format, optionally edit the **Test Message**, and click **Test Call**.

<img className="block mx-auto rounded-xl border border-gray-200" style={{ width: "100%", maxWidth: "712px" }} src="https://mintcdn.com/vobizai/AyHCnbXTYvgd7w2P/images/expedify/expedify-test-call-modal.png?fit=max&auto=format&n=AyHCnbXTYvgd7w2P&q=85&s=2cc2f0b1efadf777315dca6bc5a8de8c" alt="Expedify Test Voice Integration modal with From Number, To Number, and Test Message fields" width="712" height="868" data-path="images/expedify/expedify-test-call-modal.png" />

<Warning>
  A test call is a real call. **Both numbers ring**, and both legs are billed to your Vobiz balance. Use numbers you own or have permission to call.
</Warning>

<Check>
  Both numbers ring. Answer either leg to confirm audio, and the integration is verified end to end.
</Check>

## Receive inbound calls

This part is optional. Set it up when you want calls made *to* your Vobiz number to land in Expedify.

<Steps>
  <Step title="Copy Expedify's webhook URLs">
    Open the integration and click **Webhook URL**. Copy the **inbound call URL** and the **status callback URL**.
  </Step>

  <Step title="Create a Vobiz application">
    In the Vobiz Console go to **Voice → Application → Create New Application**.
  </Step>

  <Step title="Point it at Expedify">
    Name it - `Expedify`, for example - set the type to **Inbound calls**, and paste Expedify's inbound call URL and status callback URL into the matching fields. The URLs must match exactly.
  </Step>

  <Step title="Attach your number">
    Click **Create Application**, then attach your Vobiz number to it.
  </Step>
</Steps>

See [Applications](/docs/applications) for the full field reference.

<Check>
  Inbound is ready. Calls to your Vobiz number now route into Expedify.
</Check>

## Configuration reference

| Field | Where it comes from | Example | Notes |
| - | - | - | - |
| Integration Name | You choose it | `Vobiz Expedify` | Label only. Shown in Expedify's integration list. |
| Auth ID | Console Dashboard → API credentials | `MA_XXXXXXXX` | Sent by Expedify as the `X-Auth-ID` header. |
| Auth Token | Console Dashboard → API credentials | - | Sent as the `X-Auth-Token` header. Masked once saved. |
| Default "From" Number Source | Dropdown | User's Phone Number | Which CRM field supplies the caller's number. |
| Default "To" Number Source | Dropdown | Contact's Phone Number | Which CRM field supplies the number dialled. |
| Caller IDs | Your Vobiz numbers | `+91XXXXXXXXXX` | At least one required. Mark one as default. |
| Enable Call Recording | Toggle | On | On by default. Vobiz records the call. |
| Enable Automatic Transcription | Toggle | Off | Expedify transcribes the recording itself. |

## Troubleshooting

<AccordionGroup>
  <Accordion title="The integration will not save, or fields show as invalid">
    Auth ID and Auth Token are both required, and both must be copied exactly from the Console Dashboard. A trailing space or a partial copy is the most common cause - re-copy each with the copy icon rather than selecting the text by hand.
  </Accordion>

  <Accordion title="The test call fails, or one leg never rings">
    Confirm both numbers are in E.164 format with the country code, for example `+919876543210`. Then check your Vobiz balance covers **two** call legs - a test call dials both numbers.
  </Accordion>

  <Accordion title="Outbound calls go out from the wrong number">
    Check **Default "From" Number Source**, then check your **Caller IDs**. If you have added more than one, confirm the number you expect is the one marked default.
  </Accordion>

  <Accordion title="Inbound calls never reach Expedify">
    Confirm the Vobiz application's inbound call URL and status callback URL match exactly what Expedify's **Webhook URL** button shows, that the application type is **Inbound calls**, and that your number is attached to that application.
  </Accordion>

  <Accordion title="Calls connect but there is no recording">
    **Enable Call Recording** is set per integration, not per Caller ID. Open the integration, confirm the toggle is on, and click **Save Changes**. Recordings for calls placed before you enabled it are not created retroactively.
  </Accordion>
</AccordionGroup>

## Next steps

<CardGroup cols={2}>
  <Card title="Buy a phone number" icon="phone" href="/docs/buy-a-phone-number">
    Add more DIDs to use as Expedify Caller IDs.
  </Card>

  <Card title="Applications" icon="file-code" href="/docs/applications">
    The full field reference for the inbound application.
  </Card>

  <Card title="Call recordings" icon="microphone" href="/docs/cdr">
    Retrieve and manage recordings from the Vobiz API.
  </Card>

  <Card title="Vobiz Console" icon="gauge" href="https://console.vobiz.ai">
    Credentials, numbers, applications, and balance.
  </Card>
</CardGroup>

Need help? Email [support@vobiz.ai](mailto:support@vobiz.ai) for anything on the Vobiz side. For Expedify itself, use the headset icon in the Expedify sidebar.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.