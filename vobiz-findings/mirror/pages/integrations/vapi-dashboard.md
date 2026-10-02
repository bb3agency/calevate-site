> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vapi integration (dashboard)

> Connect Vapi to Vobiz SIP trunking without code - no-code dashboard walkthrough to receive inbound calls and make outbound calls in 130+ countries.

This guide shows how to integrate Vapi with Vobiz using the dashboard. By the end, you'll be able to **make outbound calls** and **receive inbound calls** with your Vapi AI assistant - without writing any code.

<iframe width="100%" height="420" src="https://www.youtube.com/embed/HuyGrTWhVIM" title="Vobiz x VAPI Integration" frameBorder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowFullScreen style={{ borderRadius: "12px", marginTop: "1rem", marginBottom: "1rem" }} />

<Tip>
  **Prefer using API/CLI?** Check out the [API setup guide](/docs/integrations/vapi-api) for curl commands and programmatic integration.
</Tip>

## What you'll build

An end-to-end voice integration where your Vapi AI assistant can place outbound calls through Vobiz SIP trunking and answer inbound calls placed to your Vobiz number.

## Prerequisites

* **Vobiz account** with a SIP trunk → [Create account](https://console.vobiz.ai/auth/signup)
* **Vapi account** → [Sign up](https://dashboard.vapi.ai/signup)
* **Vapi assistant** created → [Create in dashboard](https://dashboard.vapi.ai)
* **Phone number** from Vobiz (for caller ID)

## Outbound calls

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Step 1: Create SIP trunk credentials in Vapi</div>

<Steps>
  <Step title="Open Vapi integrations">
    Log in to the [Vapi Dashboard](https://dashboard.vapi.ai), click **Integrations** in the sidebar, then navigate to **SIP Trunk Credentials**.
  </Step>

  <Step title="Add a new credential">
    Click **Add New Credential** and name your trunk (for example, `Vobiz Trunk`).
  </Step>

  <Step title="Add gateway URL">
    Enter your Vobiz SIP domain from the Vobiz Console (for example, `bfab10fb.sip.vobiz.ai`).
  </Step>

  <Step title="Add credentials">
    Enter the username and password from your Vobiz trunk, enable **outbound calling**, and click **Save**.
  </Step>
</Steps>

<img className="block w-full rounded-xl border border-gray-200" src="https://mintcdn.com/vobizai/Y8H0uUEbmzwRjqm8/images/vapi-images/img1.png?fit=max&auto=format&n=Y8H0uUEbmzwRjqm8&q=85&s=00090cf2dd188cf1d737a6fb1f173158" alt="Vapi dashboard: adding a Vobiz SIP trunk credential with gateway URL and authentication" width="277" height="253" data-path="images/vapi-images/img1.png" />

Copy your unique credentials from the **Authentication & Linking** section of your trunk:

| Field | Example value |
| - | - |
| Gateway URL (SIP Domain) | `<your_unique_domain>.sip.vobiz.ai` |
| Username | `<your_username>` |
| Password | `<your_password>` |

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Step 2: Get Vobiz SIP credentials</div>

From the Vobiz Console:

1. Log in to the [Vobiz Console](https://console.vobiz.ai).
2. Go to **SIP Trunk** → **Outbound Trunks** → **Trunks**.
3. Select your trunk.
4. Scroll down to the **Authentication & Linking** section.
5. Copy the **SIP Domain**, **Username**, and **Password**.

<img className="block w-full rounded-xl border border-gray-200" src="https://mintcdn.com/vobizai/Y8H0uUEbmzwRjqm8/images/vapi-images/img2.png?fit=max&auto=format&n=Y8H0uUEbmzwRjqm8&q=85&s=4b0a7f292c10246593f6cde6fd5102c4" alt="Vobiz Console: Authentication & Linking section showing SIP domain, username, and password for an outbound trunk" width="516" height="818" data-path="images/vapi-images/img2.png" />

<Note>
  Don't have a Vobiz trunk yet? See the [SIP trunks documentation](/docs/trunks) to create one.
</Note>

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Step 3: Import your phone number</div>

<Steps>
  <Step title="Open phone numbers">
    In the Vapi Dashboard, go to **Phone Numbers** and click **Add Number**.
  </Step>

  <Step title="Choose BYO SIP trunk">
    Select **BYO SIP Trunk Number**.
  </Step>

  <Step title="Enter your Vobiz number">
    Enter your Vobiz number (for example, `08071387149`).
  </Step>

  <Step title="Pick the credential">
    Under **SIP Trunk Credentials**, pick the credential you created in Step 1, label it (for example, `Vobiz Main Line`), and click **Import SIP Trunk Number**.
  </Step>
</Steps>

<img className="block w-full rounded-xl border border-gray-200" src="https://mintcdn.com/vobizai/Y8H0uUEbmzwRjqm8/images/vapi-images/img3.png?fit=max&auto=format&n=Y8H0uUEbmzwRjqm8&q=85&s=8ad7b81fdaf379a7fe1d737bf02a1d7d" alt="Vapi dashboard: importing a Vobiz phone number using a BYO SIP trunk credential" width="559" height="649" data-path="images/vapi-images/img3.png" />

<Note>
  Need a phone number? See the [phone numbers documentation](/docs/account-phone-number/list-inventory-numbers) to purchase one from Vobiz.
</Note>

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Step 4: Make an outbound call</div>

<Steps>
  <Step title="Start a new call">
    In the Vapi Dashboard, click **Make a Call** or go to **Phone Calls** → **New Call**.
  </Step>

  <Step title="Configure outbound settings">
    Open **Outbound Settings**, enter the destination number (for example, `+919148223344`), select your assistant, and select your imported Vobiz number as the caller ID.
  </Step>

  <Step title="Place the call">
    Click **Make Outbound Call**. The call will initiate and your Vapi assistant will speak when the recipient answers.
  </Step>
</Steps>

<img className="block w-full rounded-xl border border-gray-200" src="https://mintcdn.com/vobizai/Y8H0uUEbmzwRjqm8/images/vapi-images/img4.png?fit=max&auto=format&n=Y8H0uUEbmzwRjqm8&q=85&s=3425a007736b5357d6ad74e649aa73a9" alt="Vapi dashboard: outbound call settings with destination number, assistant, and Vobiz caller ID" width="1149" height="619" data-path="images/vapi-images/img4.png" />

<Check>
  **Outbound integration complete!** Your Vapi assistant can now make outbound calls through Vobiz SIP infrastructure.
</Check>

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Step 5: Configure call transfer (optional)</div>

To let the AI agent hand a call off to a human, add a **Transfer Call** tool and give it a destination. You can transfer to a plain **phone number**, or - to route the transfer out through your Vobiz trunk - to a **SIP** destination.

<Steps>
  <Step title="Create the transfer tool">
    In the Vapi Dashboard, open **Tools**, click **Create Tool**, and select **Transfer Call** (`transferCall`). Attach the tool to your assistant.
  </Step>

  <Step title="Add a destination">
    In the tool's **Destinations** section, click **Add Destination** and choose **SIP** (or **Phone Number** for a simple PSTN transfer).
  </Step>

  <Step title="Set the SIP URI">
    For a **SIP** destination, set the **SIP URI** to the destination number at your Vobiz trunk domain:

    ```text theme={null}
    sip:+91XXXXXXXXXX@<your-trunk>.sip.vobiz.ai
    ```

    Replace `+91XXXXXXXXXX` with the E.164 number to transfer to, and `<your-trunk>` with your Vobiz SIP domain - for example `sip:+919876543210@abc123.sip.vobiz.ai`.
  </Step>

  <Step title="Save">
    Optionally add a **Message to Customer** (played before the transfer connects), then save.
  </Step>
</Steps>

| Destination type | When to use | Value |
| - | - | - |
| **SIP** | Route the transfer through your Vobiz trunk | `sip:+91XXXXXXXXXX@<your-trunk>.sip.vobiz.ai` |
| **Phone Number** | Simple blind transfer to a PSTN number | E.164, e.g. `+919876543210` |

<img className="block w-full rounded-xl border border-gray-200" src="https://mintcdn.com/vobizai/Y8H0uUEbmzwRjqm8/images/vapi-images/img5.png?fit=max&auto=format&n=Y8H0uUEbmzwRjqm8&q=85&s=90cd618694b5ebed6fb499418afbb540" alt="Vapi dashboard: configuring a Transfer Call tool with a SIP destination on the Vobiz trunk" width="728" height="715" data-path="images/vapi-images/img5.png" />

<Note>
  The SIP destination sends the transferred leg to `<your-trunk>.sip.vobiz.ai`, so it's carried over your Vobiz SIP trunking - the same domain you use for your other Vobiz trunks. Get your SIP domain from **Vobiz Console** → **SIP Trunk** → your trunk → **Authentication & Linking**.
</Note>

## Inbound calls

Receive calls placed to your Vobiz number and route them to your Vapi AI assistant.

```text theme={null}
Caller dials Vobiz number → Vobiz SIP → Vapi SIP trunk → Vapi AI assistant
```

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Step 1: Create an inbound SIP trunk in Vapi</div>

Vobiz sends inbound SIP from **any** of its signaling IPs, so you must add **every** Vobiz SIP signaling IP as a gateway. If you whitelist only one, calls that arrive from a different Vobiz IP are rejected.

<Steps>
  <Step title="Open SIP trunk settings">
    In the [Vapi Dashboard](https://dashboard.vapi.ai), click **More** → **Integrations** in the sidebar, then navigate to **SIP Trunk** and click **Create New SIP Trunk**. Name it (for example, `Vobiz Inbound Trunk`).
  </Step>

  <Step title="Configure Gateway #1">
    In **Gateway #1**, set **IP Address / Domain** to the first Vobiz SIP signaling IP, **Port** `5060`, **Netmask** `32`, and **Outbound Protocol** `UDP`. Check **Allow inbound calls**; leave **Allow outbound calls** and **Enable options ping** unchecked.
  </Step>

  <Step title="Add a gateway for every Vobiz SIP signaling IP">
    Click **Add Another Gateway** and repeat the same settings (Port `5060`, Netmask `32`, UDP, **Allow inbound calls**) for each remaining Vobiz SIP signaling IP - so all of them are whitelisted.
  </Step>

  <Step title="Save">
    Click **Save**. You should end up with one gateway per Vobiz SIP signaling IP (10 at the time of writing), each shown as `udp · inbound`.
  </Step>
</Steps>

Use these settings for **every** gateway:

| Setting | Value |
| - | - |
| Port | `5060` |
| Netmask | `32` |
| Outbound Protocol | `UDP` |
| Allow inbound calls | Enabled |
| Allow outbound calls | Disabled |
| Enable options ping | Disabled |

Add one gateway for each **Vobiz SIP signaling IP**:

```text Vobiz SIP signaling IPs theme={null}
13.203.7.132
65.2.100.211
13.126.98.234
13.235.11.131
13.233.44.61
3.111.255.163
3.111.128.110
43.204.64.203
15.207.232.91
35.154.133.28
```

<Warning>
  These IPs can change. Always confirm the current list on [IP whitelisting → SIP signaling](/docs/concepts/ip-whitelisting#sip-signaling) and keep your Vapi gateways in sync.
</Warning>

<Info>
  **RTP media firewall update:** If your network filters RTP traffic for Vapi calls, allow inbound and outbound UDP traffic on ports `5000–65535` from the complete [RTP media IP list](/docs/concepts/ip-whitelisting#rtp-media), including these new ranges:

  * `18.96.230.96/28`
  * `18.96.230.112/28`

  These ranges carry audio. Do not add them as Vapi SIP gateway entries; the gateways above use SIP signaling IPs only.
</Info>

<Tip>
  **Want outbound on the same trunk?** Add another gateway with your Vobiz SIP domain and credentials and enable **Allow outbound calls** - or use the dedicated outbound credential from the [Outbound calls](#outbound-calls) section above.
</Tip>

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Step 2: Get the Vapi trunk ID</div>

After saving the trunk in Vapi, you need the **Trunk ID** to configure Vobiz. The Trunk ID is only available via the Vapi API.

```bash theme={null}
curl -X GET "https://api.vapi.ai/credential" \
  -H "Authorization: Bearer YOUR_VAPI_API_KEY"
```

Find the trunk in the response that matches your inbound trunk name:

```json theme={null}
{
  "id": "46deea29-645d-44a3-bf42-7c6ec2d4b65c",
  "orgId": "0c147555-d9bc-41ff-8c89-82eca29f891c",
  "provider": "byo-sip-trunk",
  "gateways": [
    { "ip": "13.203.7.132", "outboundEnabled": false },
    { "ip": "65.2.100.211", "outboundEnabled": false },
    { "ip": "13.126.98.234", "outboundEnabled": false }
    // ... one entry per Vobiz SIP signaling IP
  ],
  "name": "Vobiz Inbound Trunk"
}
```

Copy the `id` field - this is your **Trunk ID**. Find the entry whose `name` matches your inbound trunk; its `gateways` array should list every Vobiz SIP signaling IP you added, each with `outboundEnabled: false`.

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Step 3: Create an inbound trunk in the Vobiz Console</div>

<Steps>
  <Step title="Open inbound trunks">
    Log in to the [Vobiz Console](https://console.vobiz.ai) and go to **SIP Trunks** → **Inbound Trunk**.
  </Step>

  <Step title="Create the trunk">
    Click **Create New Trunk**, name it (for example, `Vapi Inbound`), and set **Transport** to `UDP`.
  </Step>

  <Step title="Set the primary URI">
    Set **Primary URI** to `<VAPI_TRUNK_ID>.sip.vapi.ai` - for example, `46deea29-645d-44a3-bf42-7c6ec2d4b65c.sip.vapi.ai`.
  </Step>

  <Step title="Link your number">
    Link your Vobiz phone number to this trunk and click **Save**.
  </Step>
</Steps>

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Step 4: Import the phone number in Vapi</div>

1. In the [Vapi Dashboard](https://dashboard.vapi.ai), go to **Phone Numbers** in the sidebar.
2. Click **Create Phone Number**.
3. Select **BYO SIP Trunk Number**.
4. Enter your Vobiz phone number (for example, `+918071387376`).
5. In **SIP Trunk Credential**, select the inbound trunk you created in Step 1.
6. Label it (for example, `Vobiz Inbound Line`) and click **Import SIP Phone Number**.

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Step 5: Assign assistant and test</div>

1. On the phone number you just imported, scroll to **Inbound Settings**.
2. Under **Select Assistant**, choose your Vapi AI assistant.
3. Click **Save**.
4. **Test it** - dial your Vobiz number from any phone. Your AI assistant should answer.

<Check>
  **Inbound setup complete!** Calls to your Vobiz number now route to your Vapi AI assistant automatically.
</Check>

## Troubleshooting

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Call doesn't connect</div>

* Verify SIP domain, username, and password are correct in the [Vobiz Console](https://console.vobiz.ai).
* Use the exact `sip_domain` (for example, `bfab10fb.sip.vobiz.ai`), not a generic `sip.vobiz.ai`.

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Assistant doesn't speak</div>

* Verify the assistant has a **First Message** configured.
* Check the assistant has a voice provider set up correctly.
* View call logs in the [Vapi Dashboard](https://dashboard.vapi.ai) → **Calls** for errors.

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Phone number format error</div>

* Use E.164 format: `+919148223344` (with `+`).
* Or local format: `09148223344` (without `+`).
* Verify the number is active in the [Vobiz Console](https://console.vobiz.ai).

<Tip>
  Need more detail? See the [API troubleshooting guide](/docs/integrations/vapi-api#troubleshooting) for additional error scenarios.
</Tip>

## Next steps

* **Customize your assistant** - configure voice, personality, and responses in the [Vapi Dashboard](https://dashboard.vapi.ai).
* **View call analytics** - monitor call logs, transcripts, and metrics in **Vapi Dashboard** → **Calls**.
* **Automate with API** - see the [Vapi API setup guide](/docs/integrations/vapi-api) to trigger calls programmatically.
* **Monitor usage** - track your Vobiz balance and call records.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.