> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz WebRTC Playground

> Make and receive browser-based phone calls with the Vobiz WebRTC Playground using your API credentials and a Vobiz DID.

<img className="block w-full rounded-xl border border-gray-200" src="https://mintcdn.com/vobizai/OZ7y9Kg025aXyvCH/images/integration-bg/WebRTC.png?fit=max&auto=format&n=OZ7y9Kg025aXyvCH&q=85&s=7e59fbc65fe28c941bb573bcb3fe0d3f" alt="Vobiz WebRTC Playground for browser-based calling" width="1800" height="1080" data-path="images/integration-bg/WebRTC.png" />

Use the hosted [Vobiz WebRTC Playground](https://rtc-demo.vobiz.ai) to make and receive phone calls directly in your browser.

<Info>
  **Choose the correct authentication method:**

  * **Hosted WebRTC Playground:** Use your account **Auth ID** and **Auth Token**. You do not configure a SIP registrar.
  * **Custom WebRTC SIP client:** Create a [SIP endpoint](/docs/platform/voice/endpoints). Set the registrar or server to `registrar.vobiz.ai`, then authenticate with the endpoint `username` and `password` over SIP WebSocket. Use `sip:username@registrar.vobiz.ai` only when the client asks for the full SIP URI.
</Info>

<Note>
  **The WebRTC SDK is browser-only.** There are currently no native iOS or Android
  SDKs. For mobile, either run this SDK inside a WebView or place calls through the
  [Voice API](/docs/call) and connect the mobile app over your own transport.
</Note>

## Prerequisites

Before you begin:

* Purchase a Vobiz DID (phone number).
* Have your Vobiz **Auth ID** and **Auth Token** available.

<Warning>
  Your Auth Token is a secret. Enter it only on Vobiz services such as `rtc-demo.vobiz.ai`, and do not share it or include it in screenshots.
</Warning>

<Info>
  Enter every phone number in E.164 format: a leading `+`, the country code, and the subscriber number. Do not include spaces or hyphens. Example: `+919876543210`.
</Info>

## Make an outbound call

<Steps>
  <Step title="Open the WebRTC Playground">
    Go to [rtc-demo.vobiz.ai](https://rtc-demo.vobiz.ai).
  </Step>

  <Step title="Enter your API credentials">
    Enter your Vobiz **Auth ID**. In **API Password**, enter your **Auth Token**.

    Copy both values from the **API Credentials** section in the bottom-left corner of the [Vobiz dashboard](https://console.vobiz.ai/app/dashboard).
  </Step>

  <Step title="Connect the playground">
    Click **Connect**.

    The first time you connect, Vobiz automatically creates the `Vobiz-WebRTC-Playground` application in [Voice Applications](https://console.vobiz.ai/app/voice/applications). You will use this application to configure inbound calls.
  </Step>

  <Step title="Set the caller ID">
    In **Caller ID Override**, enter a DID purchased from Vobiz.

    Use E.164 format with no spaces or hyphens. For example:

    ```text theme={null}
    +919876543210
    ```
  </Step>

  <Step title="Enter the destination">
    In **Destination Target**, enter the phone number you want to call.

    Include the country code and do not include spaces or hyphens. For example:

    ```text theme={null}
    +919812345678
    ```
  </Step>

  <Step title="Place the call">
    Click **Call**. The playground places the outbound call using the DID from **Caller ID Override**.
  </Step>
</Steps>

<Check>
  The destination rings and the browser displays the active call controls.
</Check>

## Receive an inbound call

Complete the outbound connection steps once before configuring inbound calling. This creates the playground application in your Vobiz account.

<Tip>
  For a screenshot-by-screenshot version of this section - including how to use it to answer a voice OTP on a number with no SIM - see [How to Receive an Inbound Call in Your Browser](/docs/guides/receive-inbound-call).
</Tip>

<Steps>
  <Step title="Open the playground application">
    Go to [Voice Applications](https://console.vobiz.ai/app/voice/applications) and open `Vobiz-WebRTC-Playground`.

    If the application is not listed, return to the playground, connect with your API credentials, and refresh the applications page.
  </Step>

  <Step title="Attach a DID">
    Locate **Attach Number** in the bottom-right of the application page. Select the Vobiz DID that should receive browser calls, then complete the attachment.
  </Step>

  <Step title="Configure the playground">
    Return to [rtc-demo.vobiz.ai](https://rtc-demo.vobiz.ai) and make sure the playground is connected.

    In **Caller ID Override**, enter the DID attached to the playground application. Use E.164 format with no spaces or hyphens.
  </Step>

  <Step title="Call the attached DID">
    From another phone, call the attached DID using its full country code. For example:

    ```text theme={null}
    +919876543210
    ```
  </Step>

  <Step title="Answer in the browser">
    When the incoming-call notification appears in the playground, click **Accept** or **Pick Up**.
  </Step>
</Steps>

<Check>
  The browser answers the inbound call through the DID attached to `Vobiz-WebRTC-Playground`.
</Check>

## Troubleshooting

| Problem | What to check |
| - | - |
| **Connect fails** | Confirm that **Auth ID** contains your Auth ID and **API Password** contains your Auth Token. Copy the values again from the Vobiz dashboard. |
| **Outbound call does not start** | Confirm that **Caller ID Override** is a DID purchased from Vobiz and both numbers use E.164 format. |
| **Inbound call does not appear** | Confirm that the DID is attached to `Vobiz-WebRTC-Playground`, the same DID is entered in **Caller ID Override**, and the playground is connected. |
| **The call connects without audio** | Allow microphone access for `rtc-demo.vobiz.ai` in your browser, then reconnect the call. |
| **Custom WebRTC SIP client does not register** | Set the registrar or server to `registrar.vobiz.ai`, not `sip.vobiz.ai`. Authenticate with the SIP endpoint `username` and `password`, not your account Auth ID and Auth Token. |

## Next steps

* [Manage the playground application](/docs/platform/voice/applications)
* [Buy and manage Vobiz phone numbers](/docs/account-phone-number)
* [Review SIP endpoints](/docs/platform/voice/endpoints)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.