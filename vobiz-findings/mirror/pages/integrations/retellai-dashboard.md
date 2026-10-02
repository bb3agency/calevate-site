> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Retell AI integration (dashboard)

> Connect Retell AI to Vobiz SIP trunking without code - no-code dashboard setup for outbound and inbound AI voice calls in 130+ countries.

This guide shows how to integrate Retell AI with Vobiz using the dashboard, so your AI agents can place outbound calls to any phone number and answer inbound calls on a Vobiz number.

<iframe width="100%" height="420" src="https://www.youtube.com/embed/sC09VD0zGRA" title="Retell AI Integration Video" frameBorder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowFullScreen style={{ borderRadius: "12px", marginTop: "1rem", marginBottom: "1rem" }} />

<Tip>
  **Prefer using API/CLI?** Check out the [API setup guide](/docs/integrations/retellai-api) for curl commands and programmatic integration.
</Tip>

## What you'll build

A no-code setup in two halves, both on the same Vobiz number:

| Direction | Path |
| - | - |
| **Outbound** | Retell AI agent → Vobiz **outbound** trunk (SIP digest auth) → PSTN |
| **Inbound** | Caller → your Vobiz number → Vobiz **inbound** trunk → `sip.retellai.com` → Retell AI agent |

Inbound is pure trunk-based routing. No Vobiz [application](/docs/applications) or answer webhook is involved.

## Prerequisites

* **Retell AI account** → [Sign up](https://dashboard.retellai.com)
* **Vobiz account** with active balance → [Create account](https://console.vobiz.ai/auth/signup)
* **Retell AI agent** created → [Create in dashboard](https://dashboard.retellai.com/agents)
* **Phone number** from Vobiz - the caller ID for outbound, and the number callers dial for inbound

## Part 1: Outbound calls

<Steps>
  <Step title="Open the phone numbers section">
    Log in to the [Retell Dashboard](https://dashboard.retellai.com), navigate to **Phone Numbers** in the sidebar, and click the **+** button to add a new number.

    <img className="block w-full rounded-xl border border-gray-200" src="https://mintcdn.com/vobizai/Y8H0uUEbmzwRjqm8/images/retellai-images/img1.png?fit=max&auto=format&n=Y8H0uUEbmzwRjqm8&q=85&s=a72f644a03c161f475d9e7111b0baec8" alt="Retell dashboard: Phone Numbers section with the button to add a new number" width="388" height="216" data-path="images/retellai-images/img1.png" />
  </Step>

  <Step title="Select SIP trunking">
    Choose **Connect to your number via SIP trunking**. This option lets you use your own Vobiz phone number and SIP infrastructure instead of buying a number from Retell.

    <img className="block w-full rounded-xl border border-gray-200" src="https://mintcdn.com/vobizai/Y8H0uUEbmzwRjqm8/images/retellai-images/img2.png?fit=max&auto=format&n=Y8H0uUEbmzwRjqm8&q=85&s=b851d0f8f33da43dd1146c28123174da" alt="Retell dashboard: selecting Connect to your number via SIP trunking" width="400" height="155" data-path="images/retellai-images/img2.png" />
  </Step>

  <Step title="Configure the SIP trunk">
    Fill in the required fields:

    <img className="block w-full rounded-xl border border-gray-200" src="https://mintcdn.com/vobizai/Y8H0uUEbmzwRjqm8/images/retellai-images/img3.png?fit=max&auto=format&n=Y8H0uUEbmzwRjqm8&q=85&s=5f4769b8d525c4ba24c19fd10f2c0766" alt="Retell dashboard: SIP trunk configuration fields for phone number, termination URI, and credentials" width="560" height="686" data-path="images/retellai-images/img3.png" />

    | Field | Value |
    | - | - |
    | Phone Number | Your Vobiz number in E.164 format (for example, `+1234567890`) |
    | Termination URI | Your Vobiz SIP domain (for example, `abc123.sip.vobiz.ai`) - **do not** include the `sip:` prefix |
    | SIP Trunk User Name | Your Vobiz trunk username |
    | SIP Trunk Password | Your Vobiz trunk password |
    | Nickname | Friendly name (for example, `Vobiz Main Line`) |

    Click **Save** to complete the configuration.
  </Step>

  <Step title="Make a batch call">
    Click on your configured phone number and select **Create a batch call**. Fill in:

    <img className="block w-full rounded-xl border border-gray-200" src="https://mintcdn.com/vobizai/Y8H0uUEbmzwRjqm8/images/retellai-images/img4.png?fit=max&auto=format&n=Y8H0uUEbmzwRjqm8&q=85&s=29c91d092c05bb89d56aeff62afd1a2d" alt="Retell dashboard: creating a batch call with campaign name, from number, and recipient CSV upload" width="681" height="879" data-path="images/retellai-images/img4.png" />

    * **Batch Call Name** - campaign name (for example, `Customer Outreach`)
    * **From number** - your configured Vobiz number
    * **Upload Recipients** - CSV file with phone numbers
    * **When to send** - `Send Now` or `Schedule`

    Click **Send** or **Schedule** to launch the campaign.
  </Step>
</Steps>

<Check>
  **Outbound is live.** Your Retell AI agent can now place calls through Vobiz SIP trunking.
</Check>

## Part 2: Inbound calls

Outbound uses an **outbound** trunk that Retell authenticates into. Inbound needs a second, separate trunk that points the other way — at Retell's SIP address — with your number linked to it.

<Steps>
  <Step title="Create the inbound trunk">
    In the [Vobiz Console](https://console.vobiz.ai), go to **SIP Trunk → Inbound Trunks → Trunks** and click **Create New Trunk**.

    Give it a name, for example `retell-inbound`. Recording and transcription are on this screen and are optional — see [Callbacks](/docs/concepts/callbacks) for the webhook payloads.
  </Step>

  <Step title="Add Retell's origination URI">
    In the same dialog, click **Add New URI**:

    | Field | Value |
    | - | - |
    | Name | A label, for example `retell` |
    | URI | `sip.retellai.com` |
    | Transport | **UDP** |

    <Warning>
      **Enter the host with no `sip:` prefix and no port.** The console field takes `domain` or `domain:port`, so `sip.retellai.com` is correct — not `sip:sip.retellai.com`.

      Saving a bare hostname raises a **URI format warning**: *"Use host:port format (e.g., example.com:5060, 54.72.14.244:5060). Do you want to save anyway?"* Click **Save anyway**. Vobiz assumes the default SIP port `5060` when none is given.
    </Warning>

    Click **Create URI**, then select `sip.retellai.com` as the trunk's **Primary URI** and click **Create Trunk**.
  </Step>

  <Step title="Link your Vobiz number to the trunk">
    Open the trunk you just created. It starts with **Linked Numbers (0)**.

    Click **Link Numbers**, select the same Vobiz number you configured for outbound, and confirm. The count updates to **Linked Numbers (1)** and inbound routing is live.
  </Step>

  <Step title="Assign the inbound agent in Retell">
    In the [Retell Dashboard](https://dashboard.retellai.com), go to **Phone Numbers** and select the number.

    Find the **Inbound Call Agent** section and pick your agent from the **Call Agent** dropdown. Retell confirms with *"Your agent has been updated successfully."*

    <Note>
      **Inbound and outbound agents are set separately on the same number.** The **Inbound Call Agent** section is distinct from **Outbound Call Agent**, so one number can answer with one agent and dial out with another.
    </Note>
  </Step>
</Steps>

<Check>
  **Inbound is live.** Call your Vobiz number from any phone — the Retell agent should answer.
</Check>

## Where to find your Vobiz credentials

* **Console:** [Vobiz Console](https://console.vobiz.ai) → **Trunks** → your trunk
* **API:** see the [SIP trunks documentation](/docs/trunks)

For CSV format requirements, see the [Retell batch calling docs](https://docs.retellai.com).

## Troubleshooting

### "Phone number not found"

Phone number not configured in Retell.

* Verify the number is in E.164 format (`+countrycode + number`).
* Re-configure the phone number using the steps above.
* Check that the number exists in the [Vobiz Console](https://console.vobiz.ai).

### Call fails immediately

SIP authentication or configuration issue.

* Verify your Vobiz username and password in the [Vobiz Console](https://console.vobiz.ai).
* Use the exact Vobiz domain (for example, `abc123.sip.vobiz.ai`).
* Do **not** include a `sip:` prefix.
* Try a different transport type (TCP vs UDP) in the trunk config.

### Inbound calls ring but never reach the agent

The call is arriving at Vobiz but not reaching Retell, or Retell has no agent for it.

* Confirm the number shows under **Linked Numbers** on the **inbound** trunk, not only on the outbound one — they are separate trunks.
* Confirm the trunk's **Primary URI** is set to `sip.retellai.com`. A trunk created without a primary URI selected has nowhere to send the call.
* Check the **Inbound Call Agent** is assigned on the number in Retell. The outbound agent does not cover inbound.
* Try **TCP** instead of **UDP** on the origination URI if your network path drops UDP.

### Inbound calls are rejected immediately

* Re-check the URI value. It must be the bare host `sip.retellai.com` — a `sip:` prefix or a trailing slash will not route.
* Confirm the number is in E.164 format in Retell and matches the linked Vobiz number exactly.

### Agent doesn't speak

Agent not configured or not published.

* Ensure the agent is published in [Retell Dashboard → Agents](https://dashboard.retellai.com/agents).
* Check the agent has a voice configured.
* Verify the agent ID matches the phone number config.

<Tip>
  Need more detail? See the [API troubleshooting guide](/docs/integrations/retellai-api#troubleshooting) for additional error scenarios.
</Tip>

## Next steps

* **Customize your agent** - configure voice, personality, and prompts in [Retell Dashboard → Agents](https://dashboard.retellai.com/agents).
* **View call analytics** - monitor call logs and transcripts in **Retell Dashboard** → **Calls**.
* **Automate with API** - trigger calls programmatically using the [Retell AI API setup guide](/docs/integrations/retellai-api).
* **Monitor usage** - track your Vobiz balance and call records, or read the [CDR](/docs/cdr/get-cdr) for per-call detail.
* **Read the trunk reference** - [SIP trunking concepts](/docs/concepts/sip-trunking) and the [Trunks API](/docs/trunks).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.