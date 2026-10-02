> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Quick Start – Make Your First Vobiz Call

> Set up Vobiz and make your first call in under 5 minutes - connect an AI voice agent via Vapi or Retell, configure a SIP trunk, or build a programmable XML IVR across 130+ countries.

## What are you building?

<CardGroup cols={2}>
  <Card title="AI Voice Agent" icon="robot" href="/docs/guides/ai-voice-agent">
    Vapi · Retell · LiveKit · ElevenLabs - \~5 min
  </Card>

  <Card title="SIP Trunk + Existing PBX" icon="phone" href="/docs/trunks">
    Asterisk · FreeSWITCH · Cisco - \~10 min
  </Card>

  <Card title="Programmable IVR / XML" icon="code" href="/docs/xml/overview/how-it-works">
    Custom call flows + webhooks - \~5 min
  </Card>

  <Card title="WhatsApp Business" icon="message" href="/docs/whatsapp/getting-started/introduction">
    Templates · campaigns · webhooks - \~15 min
  </Card>
</CardGroup>

<Tip>
  **Using an AI platform?** Skip ahead to the dedicated guides for [Vapi](/docs/integrations/vapi-dashboard), [Retell AI](/docs/integrations/retellai-dashboard), [ElevenLabs](/docs/integrations/elevenlabs-dashboard), or [LiveKit](/docs/integrations/livekit).
</Tip>

## Core setup - 4 steps

<Steps>
  <Step title="Sign Up">
    Create your Vobiz account at the [registration page](https://console.vobiz.ai/app/register). You'll get ₹25 in free credit to explore the platform.

    <Frame>
      <img src="https://mintcdn.com/vobizai/cPP2drhQ7lKsmogc/images/console-new-ui/Signup.png?fit=max&auto=format&n=cPP2drhQ7lKsmogc&q=85&s=ab32d5758507a970e27498ceaea66c6d" alt="Vobiz sign-up screen showing the email and password fields" width="2926" height="1488" data-path="images/console-new-ui/Signup.png" />
    </Frame>
  </Step>

  <Step title="Dashboard Overview">
    After signing in, you land on the main dashboard. Your API credentials - **Auth ID** and **Auth Token** - are displayed here. You'll need these in every API request. See [Authentication](/docs/api-reference/authentication) for header format and troubleshooting.

    <Frame>
      <img src="https://mintcdn.com/vobizai/cPP2drhQ7lKsmogc/images/console-new-ui/dashboard.png?fit=max&auto=format&n=cPP2drhQ7lKsmogc&q=85&s=8cdde70ab01f733540987bb4b4700a09" alt="Vobiz dashboard showing Auth ID, Auth Token, and account balance" width="2936" height="1482" data-path="images/console-new-ui/dashboard.png" />
    </Frame>
  </Step>

  <Step title="Buy a Phone Number">
    Go to the **DID** section and purchase a number. Filter by region to find numbers in the country you need. The number is assigned to an inbound trunk in the next step. For a full walkthrough (console **and** API, fees, and India number series), see [Buy a phone number](/docs/buy-a-phone-number).

    <Frame>
      <img src="https://mintcdn.com/vobizai/cPP2drhQ7lKsmogc/images/console-new-ui/numbers.png?fit=max&auto=format&n=cPP2drhQ7lKsmogc&q=85&s=b70fce62d959e5c349cb7a841ff57533" alt="DID section showing available phone numbers with country filter" width="1850" height="1388" data-path="images/console-new-ui/numbers.png" />
    </Frame>
  </Step>

  <Step title="Create SIP Trunks">
    ### Outbound trunk (for placing calls)

    In the **Trunks** sidebar section, click **Create** under Outbound Trunks. Give it a name, set the domain, then create a credential (username + password) for your platform to authenticate with.

    <Frame>
      <img src="https://mintcdn.com/vobizai/cPP2drhQ7lKsmogc/images/console-new-ui/outbound-trunk.png?fit=max&auto=format&n=cPP2drhQ7lKsmogc&q=85&s=c020543a4bf157a16599a4db299bfcc6" alt="Outbound Trunks page" width="2932" height="1486" data-path="images/console-new-ui/outbound-trunk.png" />
    </Frame>

    <Frame>
      <img src="https://mintcdn.com/vobizai/cPP2drhQ7lKsmogc/images/console-new-ui/credential.png?fit=max&auto=format&n=cPP2drhQ7lKsmogc&q=85&s=a13971f65b76c9ddfa08e04347c648f5" alt="Credential creation form" width="1576" height="1298" data-path="images/console-new-ui/credential.png" />
    </Frame>

    ### Inbound trunk (for receiving calls)

    Under Inbound Trunks, link the phone number you purchased to a destination URI. This is the SIP address where Vobiz sends incoming calls - usually your AI platform's SIP URI.

    <Frame>
      <img src="https://mintcdn.com/vobizai/cPP2drhQ7lKsmogc/images/console-new-ui/inbound-trunk.png?fit=max&auto=format&n=cPP2drhQ7lKsmogc&q=85&s=a2ab8ccfae54a757c10585709c25654e" alt="Inbound trunk form" width="2928" height="1490" data-path="images/console-new-ui/inbound-trunk.png" />
    </Frame>

    <Frame>
      <img src="https://mintcdn.com/vobizai/cPP2drhQ7lKsmogc/images/console-new-ui/sip-origination-uri.png?fit=max&auto=format&n=cPP2drhQ7lKsmogc&q=85&s=44a5f58eb153a42c15e7d05642a85008" alt="SIP origination URI configuration" width="2940" height="1484" data-path="images/console-new-ui/sip-origination-uri.png" />
    </Frame>
  </Step>

  <Step title="Create an XML Application">
    In the **Voice** section, create an XML Application and set a webhook URL. Vobiz calls this URL when a call arrives, and your server responds with XML instructions. Then assign your phone number to the application.

    Use the interactive [XML Builder](/docs/xml-builder) to generate the XML your webhook should return without writing it by hand.

    <Frame>
      <img src="https://mintcdn.com/vobizai/cPP2drhQ7lKsmogc/images/console-new-ui/xml-application.png?fit=max&auto=format&n=cPP2drhQ7lKsmogc&q=85&s=a827cd81bca93b424b51282aae242f56" alt="XML Application configuration" width="2940" height="1478" data-path="images/console-new-ui/xml-application.png" />
    </Frame>
  </Step>
</Steps>

## After your first call

These sections help you monitor and debug - they're not part of the initial setup.

<CardGroup cols={2}>
  <Card title="Voice Call Logs" icon="list" href="/docs/cdr">
    Records for XML app & API calls
  </Card>

  <Card title="Recordings" icon="microphone" href="/docs/recording">
    Listen to and download call audio
  </Card>

  <Card title="SIP Call Logs" icon="server" href="/docs/cdr">
    Low-level SIP signaling details
  </Card>

  <Card title="Transactions" icon="receipt" href="/docs/account">
    Charges and credits on your account
  </Card>
</CardGroup>

## What developers usually do next

<CardGroup cols={2}>
  <Card title="Connect Vapi" icon="plug" href="/docs/integrations/vapi-dashboard">
    Route SIP directly into a Vapi AI agent - 3 min
  </Card>

  <Card title="SIP Trunk API" icon="code" href="/docs/trunks">
    Manage trunks programmatically via REST
  </Card>

  <Card title="Voice XML Reference" icon="file-code" href="/docs/xml/overview/how-it-works">
    Build custom IVR flows with XML verbs
  </Card>

  <Card title="Understand SIP" icon="book-open" href="/docs/concepts/sip-trunking">
    How INVITE, RTP, and signaling actually work - 10 min read
  </Card>
</CardGroup>

## Build it with an AI agent

If you have Cursor, Claude Code, or another MCP-aware AI tool connected to `https://vobiz.ai/docs/mcp`, click below and the agent will scaffold your first outbound call.

<Prompt description="Place your first outbound call on Vobiz - generates curl + answer XML." icon="phone-arrow-up-right" actions={["copy", "cursor"]}>
  Using the Vobiz MCP server at `https://vobiz.ai/docs/mcp`:

  1. Use `search_vobiz` to find docs for "make a call".
  2. Read the `vobiz-voice-calls` skill from `mintlify://skills/voice-calls`.
  3. Generate a runnable curl command that places one outbound call:
     * Ask me for `from` (a Vobiz number I own), `to` (E.164), and `answer_url` (HTTPS).
     * Use POST `https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/` with `X-Auth-ID` and `X-Auth-Token` placeholders for me to fill in.
  4. Also generate the minimum valid VobizXML my `answer_url` should return - `<Response><Speak>Hello from Vobiz</Speak><Hangup/></Response>`.
  5. Save the curl as `place-call.sh` and the XML as `answer.xml`.
  6. Explain the path-casing rule: `/api/v1/Account/{auth_id}/Call/` (capital A, capital C, trailing slash). Lowercase `account` or no trailing slash returns 401.
</Prompt>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.