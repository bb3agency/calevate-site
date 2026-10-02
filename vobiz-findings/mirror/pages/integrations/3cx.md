> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# 3CX integration

> Connect 3CX PBX to Vobiz SIP trunking for inbound and outbound calling across 130+ countries - configure a generic SIP trunk in minutes.

## Overview

<div className="grid grid-cols-1 md:grid-cols-3 gap-4 my-6">
  <div className="flex flex-col items-center justify-center p-6 border border-gray-200 rounded-xl shadow-sm text-center bg-white">
    <div className="w-12 h-12 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center mb-4">
      <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    </div>

    <div className="font-bold text-gray-900 mb-1">Time to complete</div>
    <div className="text-gray-500 text-sm">\~10 minutes</div>
  </div>

  <div className="flex flex-col items-center justify-center p-6 border border-gray-200 rounded-xl shadow-sm text-center bg-white">
    <div className="w-12 h-12 rounded-full bg-green-100 text-green-600 flex items-center justify-center mb-4">
      <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M14 10h4.764a2 2 0 011.789 2.894l-3.5 7A2 2 0 0115.263 21h-4.017c-.163 0-.326-.02-.485-.06L7 20m7-10V5a2 2 0 00-2-2h-.095c-.5 0-.905.405-.905.905 0 .714-.211 1.412-.608 2.006L7 11v9m7-10h-2M7 20H5a2 2 0 01-2-2v-6a2 2 0 012-2h2.514" />
      </svg>
    </div>

    <div className="font-bold text-gray-900 mb-1">Difficulty</div>
    <div className="text-gray-500 text-sm">Beginner-Friendly (No Code)</div>
  </div>

  <div className="flex flex-col items-center justify-center p-6 border border-gray-200 rounded-xl shadow-sm text-center bg-white">
    <div className="w-12 h-12 rounded-full bg-purple-100 text-purple-600 flex items-center justify-center mb-4">
      <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
      </svg>
    </div>

    <div className="font-bold text-gray-900 mb-1">Goal</div>
    <div className="text-gray-500 text-sm">Route 3CX calls via Vobiz</div>
  </div>
</div>

This guide shows how to connect [3CX](https://www.3cx.com) - a popular software-based PBX - to Vobiz as a SIP trunk provider, enabling your 3CX phone system to make and receive calls through Vobiz numbers globally.

<div className="border border-slate-200 bg-slate-50 rounded-xl p-6 my-8">
  <div className="font-bold text-slate-800 mb-4">Integration flow:</div>

  <div className="flex flex-col gap-4">
    <div className="flex items-center gap-4">
      <div className="bg-green-100 text-green-700 font-bold text-xs px-3 py-1.5 rounded border border-green-200 tracking-wider w-24 text-center">
        OUTBOUND
      </div>

      <div className="flex-1 bg-white border border-slate-200 rounded-lg p-4 flex flex-wrap items-center gap-3">
        <div className="bg-orange-50 border border-orange-200 text-orange-800 px-3 py-1 rounded text-sm font-medium">3CX Extension</div>
        <div className="text-slate-400">→</div>
        <div className="bg-orange-50 border border-orange-200 text-orange-800 px-3 py-1 rounded text-sm font-medium">3CX PBX</div>
        <div className="text-slate-400">→</div>
        <div className="bg-orange-50 border border-orange-200 text-orange-800 px-3 py-1 rounded text-sm font-medium">Vobiz</div>
        <div className="text-slate-400">→</div>
        <div className="bg-orange-50 border border-orange-200 text-orange-800 px-3 py-1 rounded text-sm font-medium">Phone Network</div>
      </div>
    </div>

    <div className="flex items-center gap-4">
      <div className="bg-blue-100 text-blue-700 font-bold text-xs px-3 py-1.5 rounded border border-blue-200 tracking-wider w-24 text-center">
        INBOUND
      </div>

      <div className="flex-1 bg-white border border-slate-200 rounded-lg p-4 flex flex-wrap items-center gap-3">
        <div className="bg-orange-50 border border-orange-200 text-orange-800 px-3 py-1 rounded text-sm font-medium">Phone Network</div>
        <div className="text-slate-400">→</div>
        <div className="bg-orange-50 border border-orange-200 text-orange-800 px-3 py-1 rounded text-sm font-medium">Vobiz</div>
        <div className="text-slate-400">→</div>
        <div className="bg-orange-50 border border-orange-200 text-orange-800 px-3 py-1 rounded text-sm font-medium">3CX PBX</div>
        <div className="text-slate-400">→</div>
        <div className="bg-orange-50 border border-orange-200 text-orange-800 px-3 py-1 rounded text-sm font-medium">3CX Extension</div>
      </div>
    </div>
  </div>
</div>

## Prerequisites

<div className="border border-gray-200 dark:border-gray-800 rounded-xl p-6 mt-4 mb-8">
  <div className="flex flex-col gap-5">
    <div className="flex items-center gap-3">
      <div className="w-5 h-5 rounded bg-[#4ade80] flex items-center justify-center text-white shrink-0">
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="4" d="M5 13l4 4L19 7" />
        </svg>
      </div>

      <div className="text-gray-800 dark:text-gray-200 text-[15px]">**Vobiz Account** with active balance → <a href="https://console.vobiz.ai/signup" className="text-primary hover:underline">Create account</a></div>
    </div>

    <div className="flex items-center gap-3">
      <div className="w-5 h-5 rounded bg-[#4ade80] flex items-center justify-center text-white shrink-0">
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="4" d="M5 13l4 4L19 7" />
        </svg>
      </div>

      <div className="text-gray-800 dark:text-gray-200 text-[15px]">**3CX installation** - self-hosted or 3CX-hosted (v16, v18, or v20) → <a href="https://www.3cx.com/install/" className="text-primary hover:underline">3CX download</a></div>
    </div>

    <div className="flex items-center gap-3">
      <div className="w-5 h-5 rounded bg-[#4ade80] flex items-center justify-center text-white shrink-0">
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="4" d="M5 13l4 4L19 7" />
        </svg>
      </div>

      <div className="text-gray-800 dark:text-gray-200 text-[15px]">**Admin access** to the 3CX Management Console</div>
    </div>

    <div className="flex items-center gap-3">
      <div className="w-5 h-5 rounded bg-[#4ade80] flex items-center justify-center text-white shrink-0">
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="4" d="M5 13l4 4L19 7" />
        </svg>
      </div>

      <div className="text-gray-800 dark:text-gray-200 text-[15px]">**A Vobiz phone number** purchased or ported → <a href="/docs/account-phone-number" className="text-primary hover:underline">Phone Numbers</a></div>
    </div>
  </div>
</div>

## Part 1: Vobiz setup

### Create a SIP trunk

1. Log in to the <a href="https://console.vobiz.ai" className="text-primary font-medium hover:underline">Vobiz Console</a>

2. In the left sidebar, navigate to **SIP Trunk > Outbound Trunks > Trunks**

3. Click **+ Create Trunk**

4. Enter a **Trunk Name** (for example, "3CX Integration") and an optional **Description**

5. Under **Authentication & Linking**, select a Credential from the **Credentials List** - or click **+ Create New Credential** if you don't have one yet

6. Click **+ Create Trunk** to save

After creating the trunk, copy the following values from the **Authentication & Linking** section - you will paste these into 3CX in the next step:

| Field | Description |
| - | - |
| **SIP Domain** | `<your_unique_domain>.sip.vobiz.ai` |
| **Username** | Your SIP credential username |
| **Password** | Your SIP credential password |

<Check>
  You now have a Vobiz SIP trunk ready to accept registrations from 3CX.
</Check>

### Configure inbound routing (optional)

If you want 3CX to receive inbound calls on your Vobiz number, you need to point the trunk's inbound destination to your 3CX SIP URI.

1. In the Vobiz Console, go to your trunk and note the **Inbound Destination** field.
2. You will fill this in after completing the 3CX setup in Part 2.

## Part 2: 3CX setup

### Add Vobiz as a SIP trunk

1. Open the **3CX Management Console** (typically at `https://your-3cx-host:5001`)

2. In the left sidebar, go to **SIP Trunks**

3. Click **Add SIP Trunk**

4. Under **Country**, select your country

5. Under **Main Trunk No.**, enter your Vobiz phone number in E.164 format (for example, `+918071387434`)

6. Under **Provider in your Country**, choose **Generic** (scroll to the bottom of the list if it is not immediately visible)

7. Click **OK** to proceed to the trunk configuration form

### Configure the trunk details

Fill in the following fields on the trunk configuration page:

| 3CX Field | Value |
| - | - |
| **Name** | `Vobiz` (or any label you prefer) |
| **Registrar / Server** | Your Vobiz SIP Domain (e.g., `abc123.sip.vobiz.ai`) |
| **Outbound Proxy** | Leave blank |
| **Number of SIM calls** | Set based on your Vobiz concurrency limit |
| **Authentication ID (SIP User ID)** | Your Vobiz credential **Username** |
| **Authentication Password** | Your Vobiz credential **Password** |
| **Main Trunk No.** | Your Vobiz phone number in E.164 format |

<Warning>
  Do **not** include `sip:` or any URI scheme in the **Registrar / Server** field. Enter only the hostname (e.g., `abc123.sip.vobiz.ai`).
</Warning>

### Configure outbound caller ID

Under the **Outbound Parameters** tab:

* Set **Outbound Caller ID** to your Vobiz phone number in E.164 format
* Leave **Outbound Call Routing** as the default unless you have a custom dial plan

### Save and apply

Click **OK** to save the trunk. 3CX will attempt to register with the Vobiz SIP server. The trunk status should turn **green** (registered) within a few seconds.

<Check>
  A green trunk status confirms that 3CX has successfully registered with Vobiz.
</Check>

## Part 3: Configure inbound DID

To route inbound calls from your Vobiz number to a 3CX extension or ring group:

1. In the 3CX Management Console, go to **DIDs**

2. Click **Add DID**

3. Set **DID number** to your Vobiz phone number (E.164 format)

4. Set **Destination** to the extension, ring group, or IVR that should answer inbound calls

5. Select the Vobiz trunk from the **Trunk** dropdown

6. Click **OK** to save

### Point Vobiz inbound to 3CX

Now go back to the **Vobiz Console** and update your trunk's inbound destination to your 3CX SIP URI:

1. In the Vobiz Console, open your trunk

2. Find the **Inbound Destination** field

3. Enter your 3CX SIP URI - this is the public IP or hostname of your 3CX server (for example, `your-3cx.example.com` or the IP address of the 3CX host)

4. Save the trunk

<Note>
  For 3CX cloud-hosted installations, use the SIP domain shown in **Settings > SIP** within the 3CX console. For self-hosted, use the public IP or FQDN of your 3CX server.
</Note>

## Part 4: Test the integration

### Test outbound calling

1. Pick up a 3CX extension (desk phone, softphone, or the 3CX mobile app)

2. Dial an external number in full E.164 format or using your standard dial plan

3. The call should route through Vobiz and connect

### Test inbound calling

1. Call your Vobiz phone number from an external phone

2. The call should ring on the 3CX extension or ring group you configured in the DID settings

## Troubleshooting

### Trunk shows "Not Registered" or red status

| Cause | Fix |
| - | - |
| Incorrect SIP Domain | Ensure the **Registrar** field contains only the hostname without `sip:` (e.g., `abc123.sip.vobiz.ai`) |
| Wrong credentials | Double-check the **Username** and **Password** from the Vobiz Console |
| Firewall blocking SIP | Ensure UDP port **5060** and RTP ports **9000–10999** are open outbound from the 3CX server |
| NAT issues | In 3CX, go to **Settings > Network** and enable **STUN** or enter your public IP |

### Outbound calls fail or get "no route" error

* Verify the **Outbound Caller ID** matches your Vobiz phone number exactly (E.164)
* Check that the **Outbound Call Routing** rule includes a Vobiz trunk as the provider
* Confirm your Vobiz account has sufficient balance

### Inbound calls do not reach 3CX

* Confirm the Vobiz trunk **Inbound Destination** points to the correct 3CX public IP or domain
* Make sure the DID in 3CX matches the incoming number format (E.164)
* Check that UDP port **5060** is open inbound on your 3CX server or firewall

### SIP 401 Unauthorized

* Verify credentials in the Vobiz Console under **SIP Trunk > Credentials**
* Ensure the 3CX trunk **Authentication ID** matches the Vobiz credential **Username** exactly

## Quick reference

| Setting | Where to get it | Where to paste it |
| - | - | - |
| SIP Domain | Vobiz Console > Trunk | 3CX Trunk > Registrar / Server |
| Username | Vobiz Console > Credentials | 3CX Trunk > Authentication ID |
| Password | Vobiz Console > Credentials | 3CX Trunk > Authentication Password |
| Vobiz phone number | Vobiz Console > Phone Numbers | 3CX Trunk > Main Trunk No. and DID |
| 3CX public IP / domain | 3CX Settings > Network | Vobiz Trunk > Inbound Destination |

## Resources

**Vobiz**

* [SIP Trunks](/docs/trunks)
* [Phone Numbers](/docs/account-phone-number/list-account-phone-numbers)
* [SIP Credentials](/docs/trunks/credentials/credential-object)
* [Balance & Billing](/docs/account/balance)
* [Console](https://console.vobiz.ai)

**3CX**

* [3CX SIP Trunk Setup](https://www.3cx.com/docs/sip-trunks/)
* [3CX DID Configuration](https://www.3cx.com/docs/dids-inbound-call-routing/)
* [3CX Network Configuration](https://www.3cx.com/docs/nat-firewall-requirements/)

**Support**

* Vobiz: [support@vobiz.ai](mailto:support@vobiz.ai)
* 3CX: [3cx.com/support](https://www.3cx.com/support/)

<Check>
  **Integration complete!**

  Your 3CX phone system can now make and receive calls through Vobiz across 130+ countries.
</Check>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.