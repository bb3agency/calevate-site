> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Bolna integration

> Connect Bolna.ai voice agents to Vobiz SIP trunking for global inbound and outbound calling across 130+ countries, including India.

<img className="block w-full rounded-xl border border-gray-200" src="https://mintcdn.com/vobizai/OZ7y9Kg025aXyvCH/images/integration-bg/Bolna.png?fit=max&auto=format&n=OZ7y9Kg025aXyvCH&q=85&s=b9b80e28830a6254173a8a99e9f87377" width="1800" height="1080" data-path="images/integration-bg/Bolna.png" />

[Bolna.ai](https://bolna.ai) is a platform for building conversational voice agents. Integrating with Vobiz gives your agents global calling capabilities through premium SIP trunking with superior reliability.

## What you'll build

A no-code integration that lets your Bolna voice agents make outbound calls and answer inbound calls on Vobiz phone numbers, with provisioning available directly inside the Bolna platform.

## Prerequisites

* **Vobiz account** with active balance - you need your `Auth Token` and `Auth Secret` from the Vobiz Console → [Create account](https://console.vobiz.ai/auth/signup)
* **Bolna.ai account** → [Sign up at bolna.ai](https://bolna.ai)

## Step 1: Add Vobiz as a provider

Log in to the [Bolna platform](https://platform.bolna.ai) and navigate to the **Providers** section.

Locate the Vobiz provider option and enter your **Vobiz Auth Token** and **Auth Secret**.

<Tip>
  Find your API credentials in the Vobiz Console under **Dashboard → Settings → API Keys**.
</Tip>

| Credential | Where to find |
| - | - |
| `Auth Token` | Vobiz Console → Settings → API Keys |
| `Auth Secret` | Vobiz Console → Settings → API Keys |

<img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/OZ7y9Kg025aXyvCH/images/bolna/img%20provider.png?fit=max&auto=format&n=OZ7y9Kg025aXyvCH&q=85&s=9ad071bb67b6117031804340918d2d00" alt="Vobiz provider credentials" width="538" height="161" data-path="images/bolna/img provider.png" />

<img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/OZ7y9Kg025aXyvCH/images/bolna/image.png?fit=max&auto=format&n=OZ7y9Kg025aXyvCH&q=85&s=ec5aa0b51f3aabdcdd4a7de7a0c67a34" alt="Bolna connect Vobiz" width="533" height="495" data-path="images/bolna/image.png" />

Once you've entered your credentials, the Vobiz telephony status shows as **Connected**.

<img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/OZ7y9Kg025aXyvCH/images/bolna/vobiz%20connected.png?fit=max&auto=format&n=OZ7y9Kg025aXyvCH&q=85&s=cd611f008fb819dd5b1dc6a47402b1f3" alt="Vobiz connected" width="549" height="167" data-path="images/bolna/vobiz connected.png" />

<Check>
  You've successfully authorized Bolna to use Vobiz for making phone calls.
</Check>

## Step 2: Configure outbound calls

To enable your agents to make outbound calls, select **Vobiz** as the telephony provider in the agent settings.

In the **Call Agent** section, select **Vobiz** from the provider dropdown.

<img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/OZ7y9Kg025aXyvCH/images/bolna/img%20call%20agent%20section%20.png?fit=max&auto=format&n=OZ7y9Kg025aXyvCH&q=85&s=c0f074961bf71de03507ff5feec86aa3" alt="Call agent section" width="1285" height="593" data-path="images/bolna/img call agent section .png" />

<Note>
  Your AI agent will now route outbound calls directly through your Vobiz SIP trunk.
</Note>

## Step 3: Set up inbound calls

Configure which agent answers incoming calls to your Vobiz numbers.

<img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/OZ7y9Kg025aXyvCH/images/bolna/set%20inbound%20agent.png?fit=max&auto=format&n=OZ7y9Kg025aXyvCH&q=85&s=c728dfe3d93101f844f2ccb90c18708b" alt="Set inbound agent" width="392" height="157" data-path="images/bolna/set inbound agent.png" />

1. Go to the **Inbound** section in Bolna.
2. Select the agent that will handle incoming calls.
3. Select the specific Vobiz phone numbers to assign to the chosen agent.

<img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/rvYkjYTwKZLAegv1/images/bolna/select%20inbound%20phone%20numbers.png?fit=max&auto=format&n=rvYkjYTwKZLAegv1&q=85&s=1b41de8e7ce1ef8586f9618a407786b0" alt="Select inbound phone numbers" width="610" height="315" data-path="images/bolna/select inbound phone numbers.png" />

## Step 4: Assign phone numbers

Provision and buy new phone numbers directly within the Bolna.ai platform using Vobiz inventory.

<Tip>
  If you already have numbers in your Vobiz account, they appear automatically in the selection list once you've added your credentials as a provider.
</Tip>

## Resources

| Resource | Link |
| - | - |
| Bolna documentation | [docs.bolna.ai](https://docs.bolna.ai) |
| Vobiz support | [support@vobiz.ai](mailto:support@vobiz.ai) |
| Bolna support | [support@bolna.ai](mailto:support@bolna.ai) |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.