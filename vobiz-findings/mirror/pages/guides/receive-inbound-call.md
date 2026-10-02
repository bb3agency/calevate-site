> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# How to Receive an Inbound Call in Your Browser

> Answer a call to your Vobiz number in the browser using the WebRTC Playground - connect with your Auth ID and Auth Token, attach the DID to the Vobiz WebRTC Playground application, and pick up the call without a handset.

Sometimes you need to *hear* a call that arrives on a Vobiz number, but the number is a cloud DID - there is no SIM and no handset to pick up. The [Vobiz WebRTC Playground](https://rtc-demo.vobiz.ai) solves this: it turns a browser tab into a softphone for any number on your account.

This is the fastest way to:

* **Receive a voice OTP.** Meta, Google, and most other platforms will read a verification code aloud over a phone call when SMS is not an option. This is how you verify a Vobiz number during [WhatsApp channel setup](/docs/whatsapp/getting-started/console-walkthrough).
* **Test that a newly purchased DID actually rings** before you point it at an application or a SIP trunk.
* **Listen to what a caller hears** while you are building an IVR.

<Note>
  You need nothing installed - no softphone, no SIP client. Just a browser with microphone access and your Vobiz API credentials.
</Note>

## Before you start

* A DID purchased from Vobiz, or the trial number assigned to your account.
* Your Vobiz **Auth ID** and **Auth Token**.
* A browser tab you can leave open. The playground only rings while it is connected.

## Step 1 - Copy your API credentials

Open the [Vobiz Console dashboard](https://console.vobiz.ai/app/dashboard) and find the **API credentials** card. Copy both values.

<Frame caption="API credentials on the Vobiz dashboard">
  <img src="https://mintcdn.com/vobizai/EZZXn_pZueq_Lc5K/images/whatsapp/api-credentials.png?fit=max&auto=format&n=EZZXn_pZueq_Lc5K&q=85&s=20790dc1c9bcc1769986b340448f9e93" alt="API credentials card on the Vobiz dashboard showing an Auth ID beginning with MA_ and a masked Auth Token" style={{maxWidth: '640px', margin: '0 auto', display: 'block'}} width="858" height="552" data-path="images/whatsapp/api-credentials.png" />
</Frame>

Your Auth ID always begins with `MA_`. The Auth Token is hidden behind the eye icon - it is **not** your console login password.

<Warning>
  The Auth Token is a secret. Enter it only on Vobiz services such as `rtc-demo.vobiz.ai`, and never paste it into a screenshot or a support ticket.
</Warning>

## Step 2 - Connect the playground

Go to [rtc-demo.vobiz.ai](https://rtc-demo.vobiz.ai) and stay on the **Zero-Config Setup** tab.

<Frame caption="Vobiz Playground V2.0 - Zero-Config Setup">
  <img src="https://mintcdn.com/vobizai/EZZXn_pZueq_Lc5K/images/webrtc-playground/playground-connect.png?fit=max&auto=format&n=EZZXn_pZueq_Lc5K&q=85&s=c0c924ac8babe340337822daa55973dc" alt="Vobiz Playground V2.0 sign-in card with Zero-Config Setup and SIP Direct tabs, Auth ID and Auth Token fields, the production webhook callback set to rtc-demo.vobiz.ai, a Remember me checkbox, and a Connect button" style={{maxWidth: '380px', margin: '0 auto', display: 'block'}} width="760" height="1662" data-path="images/webrtc-playground/playground-connect.png" />
</Frame>

<Steps>
  <Step title="Enter your credentials">
    Paste your **Auth ID** into `AUTH ID` and your **Auth Token** into `AUTH TOKEN`.
  </Step>

  <Step title="Leave the webhook callback alone">
    **Production Webhook Callback** is fixed at `https://rtc-demo.vobiz.ai`. This is the server that answers the call and bridges it into your browser - you do not host anything yourself.
  </Step>

  <Step title="Click Connect">
    Tick **Remember me** if you expect to come back, then click **Connect**. Allow microphone access when the browser asks.
  </Step>
</Steps>

<Check>
  The first time you connect, Vobiz automatically creates a voice application called **Vobiz WebRTC Playground** in your account. You need it in the next step.
</Check>

<Info>
  The **SIP Direct** tab is for a different job - registering your own SIP client against `registrar.vobiz.ai` with endpoint credentials. For receiving a call in this browser tab, Zero-Config is the one you want. See [SIP Endpoints](/docs/platform/voice/endpoints) if you need the other path.
</Info>

## Step 3 - Attach your number to the playground application

An inbound call only reaches your browser if the DID is routed to the playground application. Go to [Voice Applications](https://console.vobiz.ai/app/voice/applications) and open **Vobiz WebRTC Playground**.

```text URL theme={null}
https://console.vobiz.ai/app/voice/applications
```

<Frame caption="Vobiz WebRTC Playground application - Attach a number">
  <img src="https://mintcdn.com/vobizai/EZZXn_pZueq_Lc5K/images/webrtc-playground/application-attach-number.png?fit=max&auto=format&n=EZZXn_pZueq_Lc5K&q=85&s=45a8ff0f7a5c7dc9516d71e31ed56bef" alt="Vobiz WebRTC Playground application detail panel showing the application ID, a GET answer URL and POST hangup URL pointing at rtc-demo.vobiz.ai/api/answer, and an Attached Numbers section listing two Indian DIDs with an Attach button" style={{maxWidth: '560px', margin: '0 auto', display: 'block'}} width="1030" height="1582" data-path="images/webrtc-playground/application-attach-number.png" />
</Frame>

In **Attached Numbers**, click **+ Attach** and select the number you want to receive the call on.

You do not need to touch the webhooks. The playground sets its own **Answer URL** and **Hangup URL** to `https://rtc-demo.vobiz.ai/api/answer`, which is what hands the audio to your browser.

<Warning>
  A number can be attached to only one application at a time. Attaching it here detaches it from whatever it was routed to before, so inbound traffic to that DID stops hitting your old application until you attach it back.
</Warning>

## Step 4 - Answer the call

Go back to the playground tab and confirm it still shows as connected. Then trigger the call - dial the DID from another phone, or ask the platform you are verifying to call you.

When the incoming-call notification appears, click **Accept**. The audio plays through your browser.

<Check>
  You hear the caller - or, for a verification call, the automated voice reading your code.
</Check>

<Tip>
  Verification calls usually read the code twice and then hang up within about fifteen seconds. Have the code field open and ready before you trigger the call, and keep the playground tab in the foreground so you do not miss the ring.
</Tip>

## Using this to verify a number by voice call

This is the most common reason people reach this page. A Vobiz DID cannot receive SMS, so when a platform offers "Text message" or "Phone call" as verification methods, you must choose **Phone call**.

<Steps>
  <Step title="Set up the playground first">
    Complete steps 1 to 4 above and leave the playground connected, with the number you are verifying attached to **Vobiz WebRTC Playground**.
  </Step>

  <Step title="Switch the verification method to a call">
    On the platform's verification screen, choose the option to change your verification method and select **Phone call** rather than text message.
  </Step>

  <Step title="Answer in the browser and read back the code">
    Accept the call in the playground, listen to the code, and type it into the verification field.
  </Step>
</Steps>

If you are here from WhatsApp onboarding, return to the [WhatsApp Console Walkthrough](/docs/whatsapp/getting-started/console-walkthrough) once the number is verified.

## Troubleshooting

| Problem | What to check |
| - | - |
| **Connect fails** | Confirm `AUTH ID` holds your Auth ID (it starts with `MA_`) and `AUTH TOKEN` holds the Auth Token from the dashboard, not your login password. |
| **`Vobiz WebRTC Playground` is not in the applications list** | The application is created on your first successful connect. Connect the playground, then refresh the applications page. |
| **The call never rings in the browser** | Check that the DID appears under **Attached Numbers** on the playground application, and that the playground tab is still connected. A reloaded or backgrounded-then-slept tab drops the registration - reconnect it. |
| **The call connects but there is no audio** | Allow microphone access for `rtc-demo.vobiz.ai` in your browser's site settings, then reconnect. Browsers block audio on a tab that has never been granted the permission. |
| **The caller hears ringing, then the call drops** | The DID is attached but the playground is not connected, so nothing answers. Reconnect and try again. |
| **You missed the verification call** | Request a new code. Most platforms enforce a cooldown of 30 to 60 seconds before they let you retry. |

## Next steps

* [Vobiz WebRTC Playground →](/docs/integrations/webrtc-application-setup) - the full playground reference, including placing outbound calls and Caller ID Override.
* [Voice Applications →](/docs/platform/voice/applications) - attach numbers, set Answer and Hangup URLs, and serve your own XML.
* [SIP Endpoints →](/docs/platform/voice/endpoints) - register your own softphone against `registrar.vobiz.ai` instead.
* [WhatsApp Console Walkthrough →](/docs/whatsapp/getting-started/console-walkthrough) - connect a WhatsApp Business channel end to end.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.