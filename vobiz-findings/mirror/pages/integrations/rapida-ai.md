> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Rapida AI integration

> Connect an open-source Rapida AI deployment to Vobiz for inbound and outbound AI phone calls using Vobiz applications, the REST API, and bidirectional WebSocket audio streaming.

<img className="block w-20 h-20 rounded-xl border border-gray-200 dark:border-zinc-800 mb-5" src="https://mintcdn.com/vobizai/7xPAoTW8YsnU-nVx/images/rapida-ai/logo.png?fit=max&auto=format&n=7xPAoTW8YsnU-nVx&q=85&s=6d3454ae13cd8694cbad54fd3b501db7" alt="Rapida AI logo" width="512" height="512" data-path="images/rapida-ai/logo.png" />

Rapida AI is an open-source platform for building and deploying AI assistants. Its Vobiz provider creates outbound calls through the Vobiz REST API, routes inbound calls through a Vobiz XML Application, and carries live call audio over a bidirectional Vobiz WebSocket stream.

This guide connects your Vobiz account, selects a Vobiz phone number for an assistant, and configures outbound and inbound calling.

<Info>
  Rapida AI can run on different domains because it is open source. In this guide, `<your-rapida-domain>` means the base URL of your own Rapida AI deployment.
</Info>

## How the integration works

```text theme={null}
Outbound: Rapida AI → Vobiz REST API → callee

Inbound: Caller → Vobiz number → XML Application → Rapida AI Answer URL
                                                       ↓
          Rapida AI agent ⇄ bidirectional WebSocket audio ⇄ Vobiz
```

This is a **Vobiz WebSocket integration**, not a SIP trunk configuration. Rapida AI handles outbound call creation and the streaming connection after you save your Vobiz account credentials. For inbound calls, you also route a Vobiz XML Application to the Rapida AI webhook.

## Prerequisites

* Access to a Rapida AI deployment and permission to configure integrations.
* A Vobiz account with an **Auth ID** and **Auth Token**.
* An active Vobiz phone number to use as the outbound caller ID or inbound DID.
* Sufficient Vobiz account balance to place the test call.
* A Rapida AI assistant configured with its model, speech-to-text, and text-to-speech providers.

You can copy your Auth ID and Auth Token from the **API Credentials** section of the [Vobiz dashboard](https://console.vobiz.ai/app/dashboard).

<Warning>
  Treat your Vobiz Auth Token as a secret. Do not place it in source code, documentation screenshots, or client-side applications.
</Warning>

## Configure Vobiz in Rapida AI

<Steps>
  <Step title="Sign in to your Rapida AI deployment">
    Open the sign-in page for your Rapida AI instance. If you do not have an account on that instance, click **Sign-up**, create your account, and then sign in.

    <img className="block w-full rounded-xl border border-gray-200 dark:border-zinc-800 my-4 shadow-sm" src="https://mintcdn.com/vobizai/7xPAoTW8YsnU-nVx/images/rapida-ai/signup.png?fit=max&auto=format&n=7xPAoTW8YsnU-nVx&q=85&s=79edc4e20c83b20bbf2f49ef437c319b" alt="Rapida AI sign-in page with the Sign-up link" width="1430" height="1000" data-path="images/rapida-ai/signup.png" />
  </Step>

  <Step title="Open the integrations model page">
    In the same Rapida AI deployment, open:

    ```text theme={null}
    <your-rapida-domain>/integration/models
    ```

    Use your own deployment domain. Do not copy another user's complete Rapida AI URL.
  </Step>

  <Step title="Start the Vobiz provider setup">
    Find the **Vobiz** provider card and click **Setup Credential**.

    <img className="block max-w-md mx-auto rounded-xl border border-gray-200 dark:border-zinc-800 my-4 shadow-sm" src="https://mintcdn.com/vobizai/7xPAoTW8YsnU-nVx/images/rapida-ai/setup.png?fit=max&auto=format&n=7xPAoTW8YsnU-nVx&q=85&s=07a7023b742cc6d698193de976621841" alt="Vobiz provider card with the Setup Credential button in Rapida AI" width="540" height="504" data-path="images/rapida-ai/setup.png" />
  </Step>

  <Step title="Enter your Vobiz credentials">
    Complete the credential form:

    | Field | Value |
    | - | - |
    | **Select your provider** | `Vobiz` |
    | **Key Name** | A unique label for this credential, such as `Vobiz production` |
    | **Account Auth ID** | Your Vobiz Auth ID |
    | **API Auth Token** | Your Vobiz Auth Token |

    Click **Configure**.

    <img className="block max-w-2xl mx-auto rounded-xl border border-gray-200 dark:border-zinc-800 my-4 shadow-sm" src="https://mintcdn.com/vobizai/7xPAoTW8YsnU-nVx/images/rapida-ai/setup-credentials.png?fit=max&auto=format&n=7xPAoTW8YsnU-nVx&q=85&s=38cebef2abdc630672aa75c9a22187c9" alt="Rapida AI form for a Vobiz key name, Account Auth ID, and API Auth Token" width="1122" height="1084" data-path="images/rapida-ai/setup-credentials.png" />
  </Step>

  <Step title="Confirm the provider is connected">
    The Vobiz provider card displays a green check and **Connected** after Rapida AI saves and verifies the credential.

    <img className="block max-w-md mx-auto rounded-xl border border-gray-200 dark:border-zinc-800 my-4 shadow-sm" src="https://mintcdn.com/vobizai/7xPAoTW8YsnU-nVx/images/rapida-ai/setup-connected.png?fit=max&auto=format&n=7xPAoTW8YsnU-nVx&q=85&s=cac83353dcce37cc9215f1d6d7f20412" alt="Vobiz provider card showing Connected in Rapida AI" width="498" height="456" data-path="images/rapida-ai/setup-connected.png" />
  </Step>
</Steps>

## Add Vobiz telephony to an assistant

<Steps>
  <Step title="Open the phone-call deployment">
    Open your assistant, then go to **Deployment → Add Phone Call**.
  </Step>

  <Step title="Configure telephony">
    In **Step 1: Telephony**, select:

    | Setting | Value |
    | - | - |
    | **Telephony provider** | `Vobiz` |
    | **Credential** | The Vobiz credential you configured above |
    | **Caller ID (from number)** | An active phone number from the same Vobiz account |

    Use the refresh control next to **Credential** if a newly added credential or phone number does not appear immediately. Then click **Next** and complete the remaining assistant deployment steps.

    <img className="block w-full rounded-xl border border-gray-200 dark:border-zinc-800 my-4 shadow-sm" src="https://mintcdn.com/vobizai/7xPAoTW8YsnU-nVx/images/rapida-ai/select-phone-number.png?fit=max&auto=format&n=7xPAoTW8YsnU-nVx&q=85&s=b0698c0a71af9bc44be5ac36acf56067" alt="Rapida AI telephony deployment with Vobiz provider, credential, and caller ID selected" width="2514" height="1740" data-path="images/rapida-ai/select-phone-number.png" />
  </Step>
</Steps>

<Note>
  The caller ID must be a phone number available in the Vobiz account connected by the selected credential. Use the international E.164 format, such as `+919876543210`.
</Note>

## Place an outbound test call

<Steps>
  <Step title="Open the phone preview">
    Open the assistant's phone preview or debug phone-call view. Confirm that the configuration panel shows `vobiz` as the telephony provider.

    <img className="block w-full rounded-xl border border-gray-200 dark:border-zinc-800 my-4 shadow-sm" src="https://mintcdn.com/vobizai/7xPAoTW8YsnU-nVx/images/rapida-ai/phone-preview.png?fit=max&auto=format&n=7xPAoTW8YsnU-nVx&q=85&s=eabc57afb37dc20f3382200e991f746e" alt="Rapida AI Debug Phone Call preview with Vobiz shown as the telephony provider" width="2996" height="1750" data-path="images/rapida-ai/phone-preview.png" />
  </Step>

  <Step title="Enter the destination number">
    Select the destination country, enter the phone number, and click **Start Call**. Rapida AI asks Vobiz to create the outbound call and connects the assistant through the Vobiz WebSocket audio stream when the call is answered.
  </Step>

  <Step title="Confirm the call was created">
    A green success message confirms that the call was created. Answer the destination phone and speak with the assistant to verify the complete audio path.

    <img className="block w-full rounded-xl border border-gray-200 dark:border-zinc-800 my-4 shadow-sm" src="https://mintcdn.com/vobizai/7xPAoTW8YsnU-nVx/images/rapida-ai/make-call.png?fit=max&auto=format&n=7xPAoTW8YsnU-nVx&q=85&s=44043b774815b7e862adf5fb12052343" alt="Rapida AI success message confirming that the Vobiz test call was created" width="1524" height="774" data-path="images/rapida-ai/make-call.png" />
  </Step>
</Steps>

<Check>
  Your Rapida AI assistant can now place outbound calls using a Vobiz phone number and exchange live audio over the Vobiz WebSocket stream.
</Check>

## Receive inbound calls

For inbound calling, attach a Vobiz phone number to an XML Application whose Answer URL points to the Rapida AI phone deployment.

<Steps>
  <Step title="Copy the Rapida AI inbound webhook URL">
    In Rapida AI, open your assistant and go to **Deployment → View all**. Select the phone deployment, open the **Integration** tab, and copy the complete **Inbound Webhook URL**.

    <img className="block w-full rounded-xl border border-gray-200 dark:border-zinc-800 my-4 shadow-sm" src="https://mintcdn.com/vobizai/7xPAoTW8YsnU-nVx/images/rapida-ai/phone-deployment.png?fit=max&auto=format&n=7xPAoTW8YsnU-nVx&q=85&s=9d4a73feaac6cf37163f80a630baf0ab" alt="Rapida AI phone deployment showing the Vobiz provider and inbound webhook URL" width="2498" height="1744" data-path="images/rapida-ai/phone-deployment.png" />

    The generated URL follows this pattern:

    ```text theme={null}
    <your-rapida-domain>/v1/talk/vobiz/call/<assistant-id>?x-api-key=<project-credential-key>
    ```

    Copy the URL from Rapida AI instead of constructing it manually. It contains the assistant identifier and project credential required by your deployment.
  </Step>

  <Step title="Create a Vobiz XML Application">
    Open [Voice Applications in the Vobiz Console](https://console.vobiz.ai/app/voice/applications) and click **Create XML Application**. Configure these fields:

    | Field | Value |
    | - | - |
    | **Application Name** | A recognizable name, such as `Rapida AI inbound` |
    | **Answer URL** | The complete **Inbound Webhook URL** copied from Rapida AI |
    | **Answer method** | `GET` |

    If you want Rapida AI to receive call status and completion events, copy the **Call Status / Event Callback Webhook** from the same Rapida AI deployment panel into **Hangup URL** and keep its method set to `POST`.

    Leave **Default Number App**, **Public URI**, and **Default Endpoint App** disabled when you plan to attach a specific number in the next step. Then click **Create Application**.

    <Warning>
      The Rapida AI Answer URL contains an `x-api-key` query parameter. Treat the complete URL as a secret. Do not publish it in screenshots, tickets, logs, or source code.
    </Warning>
  </Step>

  <Step title="Attach a Vobiz phone number">
    Open the XML Application you created. In **Attach Number**, select the Vobiz phone number that callers should dial and save the change.

    Attaching the number routes its inbound calls to the application's Rapida AI Answer URL. For the API equivalent, see [Attach a number to an application](/docs/applications/attach-number).
  </Step>

  <Step title="Test the inbound call">
    Call the attached Vobiz number from another phone. Vobiz requests the Rapida AI Answer URL, Rapida AI returns the call instructions, and Vobiz opens the bidirectional WebSocket audio stream to the assistant.

    Answer and audio behavior depend on the model, speech-to-text, and text-to-speech settings saved in the Rapida AI phone deployment.
  </Step>
</Steps>

<Check>
  The attached Vobiz number now routes inbound calls to your Rapida AI assistant.
</Check>

## Troubleshooting

| Issue | What to check |
| - | - |
| Vobiz does not show **Connected** | Re-enter the Auth ID and Auth Token from the Vobiz dashboard. Confirm that no leading or trailing spaces were copied. |
| The credential or phone number is missing | Click the refresh control. Confirm that the caller ID belongs to the same Vobiz account as the selected credential. |
| The call is not created | Check the destination country and number, your Vobiz balance, and whether the selected caller ID is active. |
| The call connects without agent audio | Confirm that the assistant's model, speech-to-text, and text-to-speech providers are configured. The Vobiz provider uses WebSocket streaming, so no SIP trunk is required for this flow. |
| Inbound calls do not reach Rapida AI | Confirm that the number is attached to the correct XML Application and that its Answer URL exactly matches the Rapida AI **Inbound Webhook URL**. |
| The inbound Answer URL returns an authorization error | Copy the full webhook URL again from Rapida AI. Do not remove or modify its `x-api-key` query parameter. |

## Related resources

| Resource | Link |
| - | - |
| Vobiz WebSocket streaming | [Streaming WebSockets](/docs/concepts/streaming-websockets) |
| Vobiz Stream XML | [Stream element](/docs/xml/stream) |
| Vobiz phone numbers | [Phone numbers](/docs/account-phone-number) |
| Vobiz dashboard | [console.vobiz.ai](https://console.vobiz.ai/app/dashboard) |
| Vobiz support | [support@vobiz.ai](mailto:support@vobiz.ai) |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.