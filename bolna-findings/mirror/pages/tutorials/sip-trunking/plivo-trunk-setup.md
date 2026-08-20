> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Create a SIP Trunk on Plivo for Bolna

> Step-by-step guide to creating inbound and outbound SIP trunks on Plivo Zentrunk, configured to work with Bolna Voice AI agents.

This guide walks you through creating both an **inbound** and **outbound** SIP trunk on Plivo's Zentrunk platform. By the end, your Plivo account will be fully configured to send and receive calls through Bolna's Voice AI system.

## Prerequisites

Make sure you have the following ready before starting:

<CardGroup cols={2}>
  <Card title="Plivo Account" icon="user-plus">
    A Plivo account is required to create trunks. [Sign up for Plivo](https://console.plivo.com/) if you don't have one. A trial account works for initial testing.
  </Card>

  <Card title="Phone Number" icon="phone">
    You need at least one voice-enabled phone number from Plivo. [Purchase a number](https://console.plivo.com/active-phone-numbers/) from the Plivo Console. This will be your DID number for making and receiving calls.
  </Card>

  <Card title="Bolna Account" icon="robot">
    An active [Bolna account](https://platform.bolna.ai/) with SIP trunking access enabled. If you don't have access yet, contact [enterprise@bolna.ai](mailto:enterprise@bolna.ai).
  </Card>

  <Card title="Bolna API Key" icon="key">
    Your Bolna API key, which you can find in the [Bolna Dashboard](https://platform.bolna.ai/). You will need this later when registering the trunk on Bolna.
  </Card>
</CardGroup>

<Note>
  **Bolna's SIP Server IP Address:** Throughout this guide, you will need to use Bolna's SIP media server IP: **`13.200.45.61`**. Keep this handy as you will enter it in multiple configuration steps.
</Note>

***

## Part 1: Create an Inbound Trunk (Receive Calls)

An **inbound trunk** handles calls coming *in* to your Plivo phone number. When someone dials your number, Plivo will forward the call to Bolna's SIP server, where your AI agent picks up and handles the conversation.

<Steps>
  <Step title="Navigate to Inbound Trunks">
    Log in to the [Plivo Console](https://console.plivo.com/) and navigate to **Zentrunk** > **Inbound Trunks** in the left sidebar. You can also go directly to [console.plivo.com/zentrunk/inbound-trunks](https://console.plivo.com/zentrunk/inbound-trunks/).
  </Step>

  <Step title="Create a New Inbound Trunk">
    Click **Create New Inbound Trunk**. Enter a descriptive name that helps you identify this trunk later. For example:

    ```
    Bolna-Inbound
    ```

    This name is just for your reference within the Plivo Console.
  </Step>

  <Step title="Add Bolna's SIP URI as the Primary URI">
    This is the most important step. You are telling Plivo *where to send incoming calls*. Click **Add New URI** and fill in the following:

    | Field        | Value                   | What it means                                 |
    | ------------ | ----------------------- | --------------------------------------------- |
    | **URI Name** | `Bolna-Primary`         | A label for this destination                  |
    | **SIP URI**  | `sip:13.200.45.61:5060` | Bolna's SIP server address                    |
    | **Priority** | `10` (default)          | Lower number = higher priority                |
    | **Weight**   | `10` (default)          | Used for load balancing between multiple URIs |

    <Warning>
      **Do NOT add `transport=tcp` or `transport=tls` to the URI.** Bolna's SIP server uses **UDP**, which is the default SIP transport. Adding a TCP or TLS parameter will cause all calls to fail silently.
    </Warning>
  </Step>

  <Step title="Create the Trunk">
    Review your configuration and click **Create Trunk**. Your inbound trunk is now created. Note down the trunk name for the next step.
  </Step>

  <Step title="Connect Your Phone Number to the Inbound Trunk">
    Now you need to link your Plivo phone number to this trunk so that incoming calls are forwarded to Bolna:

    1. Navigate to **Phone Numbers** > [Your Numbers](https://console.plivo.com/active-phone-numbers/)
    2. Click on the phone number you want to use for inbound calls
    3. In the **Number Configuration** section, set **Application Type** to **Zentrunk**
    4. In the **Trunk** dropdown, select the inbound trunk you just created (e.g., `Bolna-Inbound`)
    5. Click **Update Number** to save

    <Tip>
      You can connect multiple phone numbers to the same inbound trunk. All of them will route incoming calls to Bolna's SIP server, where they can be handled by different AI agents.
    </Tip>
  </Step>
</Steps>

Your inbound trunk is now configured. Calls to your Plivo number will be forwarded to Bolna. You will configure which AI agent answers these calls in the [Register Trunk on Bolna](/docs/tutorials/sip-trunking/register-trunk-on-bolna) step.

***

## Part 2: Create an Outbound Trunk (Make Calls)

An **outbound trunk** allows Bolna to place calls *out* to regular phone numbers through your Plivo account. Your AI agents will use this trunk to initiate conversations with recipients.

<Steps>
  <Step title="Navigate to Outbound Trunks">
    In the Plivo Console, go to **Zentrunk** > [Outbound Trunks](https://console.plivo.com/zentrunk/outbound-trunks/).
  </Step>

  <Step title="Create a New Outbound Trunk">
    Click **Create New Outbound Trunk** and enter a descriptive name:

    ```
    Bolna-Outbound
    ```
  </Step>

  <Step title="Create a Credentials List for Authentication">
    Plivo uses **username/password authentication** for outbound trunks. Bolna will send these credentials with every outbound call so Plivo can verify the request is legitimate.

    In the **Trunk Authentication** section:

    1. Click **Add New Credentials List**
    2. Enter a **username**, for example: `bolna_trunk`
    3. Enter a **strong password** and write it down immediately

    <Warning>
      **Save your username and password securely.** You will need both when [registering the trunk on Bolna](/docs/tutorials/sip-trunking/register-trunk-on-bolna) in a later step. Plivo will not show the password again after you create it.
    </Warning>
  </Step>

  <Step title="Disable Secure Trunking (SRTP)">
    In the trunk settings, find **Secure Trunking** and set it to **Disabled**.

    <Warning>
      **This is critical.** Bolna does **not** support SRTP (Secure RTP). If Secure Trunking is left enabled, the media negotiation between Plivo and Bolna will fail, and you will experience **no audio** on calls (the call appears to connect but neither side can hear anything).
    </Warning>
  </Step>

  <Step title="Create the Trunk and Copy the Domain">
    Click **Create Trunk**. After creation, Plivo will display a **Termination SIP Domain** that looks like this:

    ```
    XXXXXXXXXXXXXXXXXXXX.zt.plivo.com
    ```

    **Copy this domain and save it.** This is the gateway address that Bolna will use to route outbound calls through your Plivo account.

    <Tip>
      The Termination SIP Domain is unique to your outbound trunk. It is the address where Bolna sends SIP INVITE messages when placing outbound calls on your behalf.
    </Tip>
  </Step>
</Steps>

Your outbound trunk is now configured on Plivo.

***

## Part 3: Whitelist Bolna's IP Address

For Plivo to accept SIP traffic from Bolna, you need to whitelist Bolna's IP address. Navigate to your outbound trunk's IP Whitelisting or Access Control settings and add:

```
13.200.45.61
```

This ensures that when Bolna sends SIP requests to Plivo, they are recognized and accepted.

***

## Configuration Summary

Here is a quick reference of everything you configured in this guide:

| Setting                    | Value                                                   |
| -------------------------- | ------------------------------------------------------- |
| **Inbound Trunk Name**     | `Bolna-Inbound` (or your chosen name)                   |
| **Inbound Primary URI**    | `sip:13.200.45.61:5060`                                 |
| **Outbound Trunk Name**    | `Bolna-Outbound` (or your chosen name)                  |
| **Outbound Credentials**   | Username + Password (saved securely)                    |
| **Termination SIP Domain** | `XXXXXXXXXXXXXXXXXXXX.zt.plivo.com` (copied from Plivo) |
| **Bolna IP to Whitelist**  | `13.200.45.61`                                          |
| **Secure Trunking**        | Disabled (SRTP not supported)                           |
| **Transport**              | UDP (default, do not change)                            |

***

## Plivo-Specific Notes

<AccordionGroup>
  <Accordion title="Codec Configuration">
    Plivo Zentrunk supports G.711 ulaw (u-law) and G.711 alaw (A-law) codecs by default. These are fully compatible with Bolna, so no additional codec configuration is needed on the Plivo side.
  </Accordion>

  <Accordion title="Plivo IP Ranges for Bolna Registration">
    When you register this trunk on Bolna with IP-based authentication, you will need Plivo's IP ranges. These are the IP addresses from which Plivo sends SIP traffic to Bolna:

    ```
    15.207.90.192/31
    204.89.151.128/27
    13.52.9.0/25
    ```

    You will add these as `ip_identifiers` when [registering the trunk on Bolna](/docs/tutorials/sip-trunking/register-trunk-on-bolna).
  </Accordion>

  <Accordion title="Indian Phone Numbers (DLT Registration)">
    If you are using Indian phone numbers (+91), you must complete the DLT (Distributed Ledger Technology) registration process before your numbers will work for outbound calling. See [Plivo's guide on Indian numbers](https://www.plivo.com/docs/numbers/rent-india-numbers) and Bolna's [regulated phone numbers guide](/docs/guides/inbound/obtaining-regulated-phone-numbers).
  </Accordion>

  <Accordion title="Trial Account Limitations">
    Trial Plivo accounts have limited functionality. You may only be able to call verified numbers (numbers you have manually added to your Plivo account). [Upgrade your Plivo account](https://console.plivo.com/) for full outbound calling capability.
  </Accordion>
</AccordionGroup>

***

## Next Steps

Your Plivo trunks are now configured. Continue with these guides:

<CardGroup cols={2}>
  <Card title="Register Trunk on Bolna" icon="plug" href="/docs/tutorials/sip-trunking/register-trunk-on-bolna">
    Register your Plivo trunk with Bolna and add your phone numbers via API
  </Card>

  <Card title="Receive Inbound Calls" icon="phone-arrow-down-left" href="/docs/tutorials/sip-trunking/inbound-calls">
    Map your phone numbers to AI agents so they answer incoming calls
  </Card>
</CardGroup>
