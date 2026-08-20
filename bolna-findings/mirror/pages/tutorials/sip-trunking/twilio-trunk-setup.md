> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Create a SIP Trunk on Twilio for Bolna

> Step-by-step guide to creating an Elastic SIP Trunk on Twilio for inbound and outbound calling with Bolna Voice AI agents.

This guide walks you through creating and configuring a **Twilio Elastic SIP Trunk** to work with Bolna's Voice AI platform. Twilio's Elastic SIP Trunking provides cloud-based PSTN connectivity. You will configure termination (for outbound calls), origination (for inbound calls), and associate your Twilio phone numbers with the trunk.

## Prerequisites

Make sure you have the following ready before starting:

<CardGroup cols={2}>
  <Card title="Twilio Account" icon="user-plus">
    A Twilio account is required to create trunks. [Sign up for Twilio](https://www.twilio.com/try-twilio) if you don't have one. A free trial can be used for initial testing.
  </Card>

  <Card title="Phone Number" icon="phone">
    You need at least one Twilio phone number. [Buy a number](https://www.twilio.com/console/phone-numbers) from the Twilio Console. This will be associated with your trunk.
  </Card>

  <Card title="Bolna Account" icon="robot">
    An active [Bolna account](https://platform.bolna.ai/) with SIP trunking access enabled. Contact [enterprise@bolna.ai](mailto:enterprise@bolna.ai) if you don't have access yet.
  </Card>

  <Card title="Bolna API Key" icon="key">
    Your Bolna API key from the [Bolna Dashboard](https://platform.bolna.ai/). You will need this when registering the trunk on Bolna.
  </Card>
</CardGroup>

<Note>
  **Bolna's SIP Server IP Address:** You will need Bolna's SIP media server IP throughout this guide: **`13.200.45.61`**. Keep this handy.
</Note>

***

## Step 1: Create a New SIP Trunk

<Steps>
  <Step title="Navigate to Elastic SIP Trunking">
    Log in to the [Twilio Console](https://www.twilio.com/console) and navigate to **Elastic SIP Trunking** > **Trunks** in the left sidebar. You can also go directly to [twilio.com/console/sip-trunking/trunks](https://www.twilio.com/console/sip-trunking/trunks).
  </Step>

  <Step title="Create the Trunk">
    Click **Create new SIP Trunk** (or the **+** button) and enter a friendly name for your trunk:

    ```
    Bolna Voice AI Trunk
    ```

    Click **Create**. Twilio will assign a unique **Trunk SID** (e.g., `TKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`). Note this down for reference.
  </Step>
</Steps>

***

## Step 2: Configure Termination (Outbound Calls)

**Termination** settings control how Bolna sends outbound calls through Twilio to the PSTN. You need to set up a Termination URI (the address Bolna will call) and configure authentication so Twilio knows the requests are legitimate.

<Steps>
  <Step title="Set the Termination URI">
    Go to the **Termination** tab in your trunk's configuration. Enter a unique domain name in the **Termination URI** field:

    ```
    bolna-trunk.pstn.twilio.com
    ```

    Click **Save**. This URI is the gateway address you will provide to Bolna when registering the trunk.

    <Tip>
      Choose a descriptive name using dashes for readability. The full format is `{your-name}.pstn.twilio.com`. This must be unique across all Twilio accounts.
    </Tip>
  </Step>

  <Step title="Create an IP Access Control List (ACL)">
    An IP ACL tells Twilio which IP addresses are allowed to send SIP traffic to your trunk. You need to add Bolna's SIP server IP so Twilio accepts call requests from Bolna.

    In the **Authentication** section, find **IP Access Control Lists**:

    1. Click **Create IP Access Control List**
    2. Enter a friendly name: `Bolna SIP Server`
    3. Click **Create**, then click **Add IP Address** and fill in:

    | Field             | Value              | What it means                |
    | ----------------- | ------------------ | ---------------------------- |
    | **Friendly Name** | `Bolna Production` | A label for this IP entry    |
    | **IP Address**    | `13.200.45.61`     | Bolna's SIP server IP        |
    | **CIDR**          | `32`               | Single IP address (no range) |

    4. Save and then **associate this ACL with the trunk** by selecting it from the dropdown on the Termination page

    <Warning>
      Without Bolna's IP in the ACL, Twilio will reject all outbound SIP INVITE requests from Bolna with a `403 Forbidden` error. Your calls will fail to connect.
    </Warning>
  </Step>

  <Step title="Create a Credential List (Recommended)">
    In addition to IP-based security, Twilio recommends also using **credential-based authentication**. When configured, Bolna will include a username and password with every outbound call request.

    In the **Authentication** section, find **Credential Lists**:

    1. Click **Create Credential List**
    2. Enter a friendly name: `Bolna Credentials`
    3. Add a **username** (e.g., `bolna_trunk`) and a **strong password**
    4. Click **Create**, then **associate the Credential List** with the trunk

    <Warning>
      **Save your username and password securely.** You will need both when [registering the trunk on Bolna](/docs/tutorials/sip-trunking/register-trunk-on-bolna). Twilio will not show the password again after creation.
    </Warning>

    <Note>
      When both an IP ACL and Credential List are configured, Twilio enforces **both**: the request must come from a whitelisted IP **and** include valid credentials. This is the most secure setup.
    </Note>
  </Step>
</Steps>

***

## Step 3: Configure Origination (Inbound Calls)

**Origination** settings control how Twilio delivers inbound calls (calls from the PSTN) to Bolna's SIP server. This is what enables your AI agent to answer incoming phone calls.

<Steps>
  <Step title="Add Bolna's SIP URI as the Origination URI">
    Go to the **Origination** tab in your trunk's configuration. Click **Add new Origination URI** and fill in:

    | Setting                 | Value                   | What it means                                       |
    | ----------------------- | ----------------------- | --------------------------------------------------- |
    | **Origination SIP URI** | `sip:13.200.45.61:5060` | Where Twilio sends incoming calls (Bolna's server)  |
    | **Priority**            | `10`                    | Lower number = higher priority. Use 10 for primary. |
    | **Weight**              | `10`                    | Load balancing weight. Use 10 for a single trunk.   |
    | **Enabled**             | Yes                     | Must be enabled for calls to route                  |

    Click **Add**.

    <Tip>
      **Failover setup:** You can add multiple Origination URIs with different priorities. If the primary URI fails (e.g., Bolna's server is unreachable), Twilio will try the next URI in priority order.
    </Tip>

    <Warning>
      **Do NOT add `transport=tcp` or `transport=tls` to the URI.** Bolna's SIP server requires **UDP** transport (the default). Adding TCP or TLS will cause inbound calls to fail.
    </Warning>
  </Step>
</Steps>

***

## Step 4: General Settings

These settings apply to the entire trunk and affect both inbound and outbound calls.

<Steps>
  <Step title="Disable Secure Trunking (SRTP)">
    Go to the **General** tab. Find **Secure Trunking** and set it to **Disabled**. Click **Save**.

    <Warning>
      **This is critical.** Bolna does not support SRTP (Secure RTP). If Secure Trunking is left enabled, media negotiation between Twilio and Bolna will fail. Calls may appear to connect, but you will experience **no audio** or **one-way audio**.
    </Warning>
  </Step>

  <Step title="Enable Symmetric RTP">
    Set **Symmetric RTP** to **Enabled** and save. This helps prevent one-way audio issues that can occur due to NAT (Network Address Translation) between Twilio's and Bolna's servers.
  </Step>

  <Step title="Configure Call Recording (Optional)">
    If you want Twilio to record calls on its side, choose your preference:

    * **Do Not Record** (default): No recording on Twilio
    * **Record from ringing**: Recording starts when the phone rings
    * **Record from answer**: Recording starts when the call is answered

    <Note>
      Bolna also offers its own call recording feature. You can use either or both depending on your needs.
    </Note>
  </Step>
</Steps>

***

## Step 5: Associate Phone Numbers

You need to associate at least one Twilio phone number with your trunk. This tells Twilio to route calls to that number through your SIP trunk instead of handling them with TwiML or Studio.

<Steps>
  <Step title="Open the Numbers Tab">
    In your trunk's configuration page, click the **Numbers** tab.
  </Step>

  <Step title="Associate an Existing Number">
    If you already have a Twilio phone number:

    1. Click **Associate a Number with this Trunk**
    2. Select your phone number from the list
    3. The number's Voice configuration will automatically be updated to **SIP Trunking**

    <Note>
      **One number, one trunk:** A Twilio phone number can only be associated with one trunk at a time. Associating it with a new trunk automatically removes it from the previous one.
    </Note>
  </Step>

  <Step title="Verify the Number Configuration">
    To confirm everything is set up correctly:

    1. Go to **Phone Numbers** > **Manage** > **Active Numbers** in the Twilio Console
    2. Click on your number
    3. Under **Voice Configuration**, confirm that **Configure With** is set to **SIP Trunk** and the correct trunk name is shown
  </Step>
</Steps>

***

## Configuration Summary

Here is a complete reference of everything you configured:

| Setting                | Value                                                |
| ---------------------- | ---------------------------------------------------- |
| **Trunk Name**         | `Bolna Voice AI Trunk` (or your chosen name)         |
| **Trunk SID**          | `TKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` (auto-assigned) |
| **Termination URI**    | `bolna-trunk.pstn.twilio.com` (your chosen domain)   |
| **IP ACL**             | Bolna IP `13.200.45.61/32` in `Bolna SIP Server` ACL |
| **Credential List**    | Username + Password (saved securely)                 |
| **Origination URI**    | `sip:13.200.45.61:5060` (Priority: 10, Weight: 10)   |
| **Secure Trunking**    | Disabled (SRTP not supported by Bolna)               |
| **Symmetric RTP**      | Enabled                                              |
| **Transport**          | UDP (default)                                        |
| **Associated Numbers** | Your Twilio phone number(s)                          |

***

## Twilio-Specific Notes

<AccordionGroup>
  <Accordion title="E.164 Number Formatting">
    Twilio **requires** all phone numbers to be in E.164 format (e.g., `+12128675309`). Numbers without the `+` prefix will be rejected with a `400 Bad Request` response. Bolna's `outbound_leading_plus_enabled` setting (default `true`) automatically ensures the `+` is prepended to outbound numbers.
  </Accordion>

  <Accordion title="Localized Termination URIs">
    For lower latency on outbound calls, you can use Twilio's region-specific termination URIs instead of the global one. Replace `bolna-trunk` with your chosen domain name:

    | Region                    | URI                                     |
    | ------------------------- | --------------------------------------- |
    | N. America (Virginia)     | `bolna-trunk.pstn.ashburn.twilio.com`   |
    | N. America (Oregon)       | `bolna-trunk.pstn.umatilla.twilio.com`  |
    | Europe (Ireland)          | `bolna-trunk.pstn.dublin.twilio.com`    |
    | Europe (Frankfurt)        | `bolna-trunk.pstn.frankfurt.twilio.com` |
    | Asia Pacific (Singapore)  | `bolna-trunk.pstn.singapore.twilio.com` |
    | Asia Pacific (Tokyo)      | `bolna-trunk.pstn.tokyo.twilio.com`     |
    | South America (Sao Paulo) | `bolna-trunk.pstn.sao-paulo.twilio.com` |
    | Asia Pacific (Sydney)     | `bolna-trunk.pstn.sydney.twilio.com`    |
  </Accordion>

  <Accordion title="Caller ID Requirements">
    For outbound calls, Twilio requires the `from_number` (caller ID) to be either a Twilio DID number on your account or a verified Caller ID number. If an invalid caller ID is used, Twilio will reject the outbound call.
  </Accordion>

  <Accordion title="Trial Account Limitations">
    Trial Twilio accounts have some restrictions: you can only call **verified phone numbers**, and outbound calls will play a Twilio trial message before your AI agent speaks. [Upgrade your account](https://www.twilio.com/console) to remove these limitations.
  </Accordion>

  <Accordion title="Maximum Call Duration">
    Twilio Elastic SIP Trunking supports call durations up to **24 hours** (extended from the default 4 hours). This can be configured per-trunk in the General settings tab.
  </Accordion>
</AccordionGroup>

***

## Next Steps

Your Twilio Elastic SIP Trunk is fully configured. Continue with these guides:

<CardGroup cols={2}>
  <Card title="Register Trunk on Bolna" icon="plug" href="/docs/tutorials/sip-trunking/register-trunk-on-bolna">
    Register your Twilio trunk with Bolna and add your phone numbers via API
  </Card>

  <Card title="Make Outbound Calls" icon="phone-arrow-up-right" href="/docs/tutorials/sip-trunking/outbound-calls">
    Place outbound calls through your Twilio trunk using Bolna AI agents
  </Card>
</CardGroup>
