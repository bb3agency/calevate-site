> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# ElevenLabs integration (dashboard)

> ElevenLabs connects to Vobiz SIP trunking without code - no-code dashboard setup for AI voice agents with ultra-realistic TTS voices in 130+ countries.

This guide shows how to integrate ElevenLabs with Vobiz using the dashboard. By the end you'll have **outbound calling** set up so your conversational AI agent can call any real phone number with an ultra-realistic voice.

<Tip>
  **Prefer watching a walkthrough or using API/CLI?** See the [ElevenLabs integration overview](/docs/integrations/elevenlabs) for the video tutorial, or the [API setup guide](/docs/integrations/elevenlabs-api) for curl commands and programmatic integration.
</Tip>

## What you'll build

A no-code outbound and inbound calling integration where your ElevenLabs conversational agent answers and places calls through Vobiz SIP trunking, using ElevenLabs' ultra-realistic voices.

## Prerequisites

* **Vobiz account** with a SIP trunk → [Create account](https://console.vobiz.ai/auth/signup)
* **ElevenLabs account** → [Sign up](https://elevenlabs.io)
* **ElevenLabs agent** created → [Create in dashboard](https://elevenlabs.io/app)
* **Phone number** from Vobiz (for caller ID)

## Outbound calls

<div className="text-lg font-semibold mt-6 mb-2">1. Import phone number</div>

<img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/OZ7y9Kg025aXyvCH/images/elevenlabs/img1.png?fit=max&auto=format&n=OZ7y9Kg025aXyvCH&q=85&s=d8ed748b56ea6bdfd6794a4f21278800" alt="Import Phone Number from SIP Trunk" width="1548" height="878" data-path="images/elevenlabs/img1.png" />

1. Log in to the [ElevenLabs Dashboard](https://elevenlabs.io/app).
2. Navigate to **Phone Numbers** in the sidebar.
3. Click **Import Number**.
4. Select **Import from SIP Trunk**.

<div className="text-lg font-semibold mt-6 mb-2">2. Label phone number</div>

<img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/OZ7y9Kg025aXyvCH/images/elevenlabs/img2.png?fit=max&auto=format&n=OZ7y9Kg025aXyvCH&q=85&s=b7f12b91b22f4b34ae8e3acbd54e990b" alt="Label Your Phone Number" width="638" height="879" data-path="images/elevenlabs/img2.png" />

Enter:

* **Label** - a name for easy identification (for example, `Vobiz Main Line`).
* **Phone Number** - your Vobiz number (for example, `+911234567890`). Include the country code with `+`, or use the local format (`01234567890`).

Click **Next** to continue to outbound configuration.

<Note>
  Need a phone number? See the [phone numbers documentation](/docs/account-phone-number/list-inventory-numbers) to purchase one from Vobiz.
</Note>

<div className="text-lg font-semibold mt-6 mb-2">3. Configure outbound settings</div>

<img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/OZ7y9Kg025aXyvCH/images/elevenlabs/img3.png?fit=max&auto=format&n=OZ7y9Kg025aXyvCH&q=85&s=ef90b7dd4f150525314523f2848e9c72" alt="Configure Outbound Settings" width="644" height="853" data-path="images/elevenlabs/img3.png" />

| Field | Value |
| - | - |
| Transport Type | `TCP` |
| Address (SIP Trunk Address) | `<your_unique_domain>.sip.vobiz.ai` |
| SIP Trunk Username | `<your_username>` |
| SIP Trunk Password | `<your_password>` |

To find your Vobiz credentials:

1. Log in to the [Vobiz Console](https://console.vobiz.ai).
2. Navigate to **SIP Trunk** → **Outbound Trunks** → **Trunks**.
3. Click on your trunk.
4. Scroll to the **Authentication & Linking** section.

Click **Save** or **Import** to complete the setup.

<div className="text-lg font-semibold mt-6 mb-2">4. Make your first call</div>

<img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/OZ7y9Kg025aXyvCH/images/elevenlabs/img4.png?fit=max&auto=format&n=OZ7y9Kg025aXyvCH&q=85&s=1d81c95c1fc084edc87868758daa5b8f" alt="Make first call" width="884" height="877" data-path="images/elevenlabs/img4.png" />

1. In the ElevenLabs Dashboard, navigate to **Phone Numbers**.
2. Select the phone number you just imported.
3. Click **Make Outbound Call**.
4. Select your agent from the dropdown - this is the conversational AI agent you created in ElevenLabs.
5. Enter the destination phone number (for example, `+919988776655`) - must include country code.
6. Click **Call** or **Start Test Call**.

The call initiates immediately. The destination phone rings, and when answered your ElevenLabs agent speaks.

<div className="text-lg font-semibold mt-6 mb-2">Verify your call</div>

To view call logs and transcripts:

1. Go to **Agents Platform** → your agent.
2. Click **Call History** or **Conversations**.
3. View call details, transcripts, and recordings.

<Check>
  **Outbound complete!** You can now make calls from the ElevenLabs Dashboard anytime.
</Check>

## Inbound calls

To allow people to call your AI agent, configure inbound calling.

<div className="text-lg font-semibold mt-6 mb-2">1. Configure SIP URI</div>

In your Vobiz SIP trunk configuration or Application Answer URL, point incoming calls to the ElevenLabs SIP URI:

<img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/OZ7y9Kg025aXyvCH/images/elevenlabs/image.png?fit=max&auto=format&n=OZ7y9Kg025aXyvCH&q=85&s=1934b7ab704a51476f0cbae1d34ab7ca" alt="Inbound setup" width="611" height="229" data-path="images/elevenlabs/image.png" />

<img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/OZ7y9Kg025aXyvCH/images/elevenlabs/primary%20uri.png?fit=max&auto=format&n=OZ7y9Kg025aXyvCH&q=85&s=fc7d22fada7b5e5e83614c9a50d3fbb2" alt="Primary URI" width="546" height="470" data-path="images/elevenlabs/primary uri.png" />

| Setting | Value |
| - | - |
| SIP URI | `sip.rtc.elevenlabs.io:5060` |
| Transport | `TCP` |

<div className="text-lg font-semibold mt-6 mb-2">2. Import the number</div>

Go to [ElevenLabs Phone Numbers](https://elevenlabs.io/app/agents/phone-numbers) and click **Import from SIP Trunk**.

<img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/rvYkjYTwKZLAegv1/images/elevenlabs/import%20phone%20number%20from%20sip%20trunk.png?fit=max&auto=format&n=rvYkjYTwKZLAegv1&q=85&s=9444c18a4cbf8e254cdea2298550341b" alt="Import phone number" width="209" height="167" data-path="images/elevenlabs/import phone number from sip trunk.png" />

<div className="text-lg font-semibold mt-6 mb-2">3. Configure number details</div>

Enter a label (for example, `Main Line`) and your Vobiz phone number.

<img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/OZ7y9Kg025aXyvCH/images/elevenlabs/elevenlabs%20confid.png?fit=max&auto=format&n=OZ7y9Kg025aXyvCH&q=85&s=e5af9a5ea36b0ad47750927e231a1e9f" alt="Configure number" width="589" height="883" data-path="images/elevenlabs/elevenlabs confid.png" />

<div className="text-lg font-semibold mt-6 mb-2">4. Attach to agent</div>

Once added, locate the number in your list and click **Attach** to link it to an agent.

<img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/rvYkjYTwKZLAegv1/images/elevenlabs/attach%20number.png?fit=max&auto=format&n=rvYkjYTwKZLAegv1&q=85&s=d3fea73871bfd04326fc02dae2949c96" alt="Attach number" width="957" height="197" data-path="images/elevenlabs/attach number.png" />

<div className="text-lg font-semibold mt-6 mb-2">5. Select the agent</div>

<img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/OZ7y9Kg025aXyvCH/images/elevenlabs/select%20agent%20.png?fit=max&auto=format&n=OZ7y9Kg025aXyvCH&q=85&s=c808a6ccbbede8646e2530c9efd4f3aa" alt="Select agent" width="756" height="522" data-path="images/elevenlabs/select agent .png" />

To verify the setup, dial the phone number you attached from any phone. The selected ElevenLabs agent should pick up and start the conversation.

## Troubleshooting

<div className="text-lg font-semibold mt-6 mb-2">SIP 408 request timeout</div>

Vobiz trunk cannot reach ElevenLabs SIP servers.

* Verify the SIP trunk address is correct (for example, `abc123def.sip.vobiz.ai`).
* Check the transport type is set to `TCP`.
* Verify your Vobiz trunk status is `active` in the [Vobiz Console](https://console.vobiz.ai).

<div className="text-lg font-semibold mt-6 mb-2">SIP authentication failed</div>

Wrong username or password.

* Verify username and password in [Vobiz Console](https://console.vobiz.ai) → **Trunks**.
* Ensure credentials match exactly (case-sensitive).
* Re-enter credentials in the ElevenLabs dashboard.

<div className="text-lg font-semibold mt-6 mb-2">Call connects but silent</div>

Agent configuration issue or voice not set.

* Verify the agent has a `First Message` configured.
* Check the agent has a valid voice selected.
* Test the voice in the ElevenLabs dashboard first.
* View call logs in the [ElevenLabs Dashboard](https://elevenlabs.io/app) for errors.

<div className="text-lg font-semibold mt-6 mb-2">Call doesn't connect</div>

Wrong phone number format or trunk configuration.

* Use E.164 format: `+919988776655` (with `+`).
* Or local format: `09988776655` (without `+`).
* Verify your Vobiz trunk is active.

<Tip>
  Need more detail? See the [API troubleshooting guide](/docs/integrations/elevenlabs-api#troubleshooting) for additional error scenarios.
</Tip>

## Next steps

* **Customize your agent** - configure voice, personality, prompts, and first message in the [ElevenLabs Dashboard](https://elevenlabs.io/app).
* **View call analytics** - monitor call logs and transcripts in **ElevenLabs Dashboard** → **Call History**.
* **Automate with API** - see the [ElevenLabs API setup guide](/docs/integrations/elevenlabs-api) to trigger calls programmatically.
* **Monitor usage** - track your Vobiz balance and call records.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.