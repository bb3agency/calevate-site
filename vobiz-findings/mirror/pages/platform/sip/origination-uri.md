> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Origination URI - SIP Destinations for Inbound Calls

> Manage SIP Origination URIs in the Vobiz Console - the destination addresses (host:port + transport) Vobiz forwards inbound PSTN calls to. Walkthrough of the URI list, details, and Create Origination URI form.

An **Origination URI** is a SIP destination address - `host:port` plus transport - that Vobiz forwards inbound PSTN calls to. Each [inbound trunk](/docs/platform/sip/inbound-trunks) picks one URI as its Primary, and you can keep multiple URIs on hand for primary/backup routing or per‑region delivery.

```text URL theme={null}
https://console.vobiz.ai/app/sip/in/uri
```

## The Origination URI list

<Frame caption="Origination URI - list and details">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/sip/sip-origination-uri_blur.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=40e9162b2105289bc9d8061d0c525745" alt="Origination URI page with a search field, Add Origination URI button, a list of URIs (qwerty.asfg.com, ZJGB2STD4WCD.sip.videosdk.li, 2f51fa9d-c783-47ae-ab24-299..., 8ebd23dc-b86b-4fea-bc41-96..., asd.exmaple.sip.com) each showing No description, Transport UDP, and Status Active, and a URI Details panel on the right with URI (qwerty.asfg.com), URI ID, Description, Status Active, Transport UDP, Trunk, and Metadata Created and Last Updated timestamps" style={{maxWidth: '900px', margin: '0 auto', display: 'block'}} width="8000" height="4408" data-path="images/platform/sip/sip-origination-uri_blur.png" />
</Frame>

| Column | Meaning |
| - | - |
| **URI** | The SIP host (and optional port). Vobiz POSTs the INVITE here. |
| **Transport** | `UDP` (default), `TCP`, or `TLS`. Picked when you create the URI. |
| **Status** | `Active` accepts calls; `Inactive` rejects (carrier sees a routing error). |

Click any card to load its details on the right.

## Details panel

| Section | Field | Meaning |
| - | - | - |
| **URI Details** | URI | The host (and port). |
| | URI ID | Immutable UUID. |
| | Description | Optional notes. |
| | Status | `Active` / `Inactive`. |
| | Transport | `UDP`, `TCP`, or `TLS`. |
| | Trunk | The inbound trunk this URI is currently linked to (or `—`). |
| **Metadata** | Created / Last Updated | Both in your browser timezone. |

## Create an Origination URI

Click **+ Add Origination URI** to open the side panel.

<Frame caption="Create Origination URI form">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/sip/sip-origination-uri-create.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=f9c9ca2b1b971c6319ba9eebafea7c52" alt="Create Origination URI modal with URI required field (placeholder example.com:5060) and hint Examples example.com:5060 sip.example.com:5060 34.73.214.124:5060, Description field with placeholder Optional description and hint Primary origination URI backup route etc., Transport dropdown set to UDP, Active toggle on, and Cancel and orange Create URI buttons" style={{maxWidth: '720px', margin: '0 auto', display: 'block'}} width="1656" height="1558" data-path="images/platform/sip/sip-origination-uri-create.png" />
</Frame>

| Field | Required | Notes |
| - | - | - |
| **URI** | ✅ | `host:port` form. Examples: `example.com:5060`, `sip.example.com:5060`, `34.73.214.124:5060`. Port defaults to `5060` if omitted. |
| **Description** | – | Free‑text label like *"Primary Mumbai PBX"* or *"Failover route"*. |
| **Transport** | – | `UDP` (default), `TCP`, or `TLS`. Pick `TLS` if your PBX expects encrypted SIP. |
| **Active** | – | Defaults on. Toggle off to provision without routing traffic. |

Click **Create URI**.

## Link the URI to an inbound trunk

Once the URI exists:

1. Open an [Inbound Trunk](/docs/platform/sip/inbound-trunks).
2. Edit the trunk and pick this URI from the **Primary URI** dropdown.
3. Save.

Vobiz immediately starts forwarding inbound calls on the trunk's linked numbers to this URI.

## Multiple URIs - primary / backup

A URI created here can be reused across many trunks, or you can keep several URIs on standby for fast failover:

1. **Primary URI** stays linked to the production inbound trunk.
2. **Backup URI** stays `Active` but unlinked.
3. When the primary PBX goes down, switch the trunk's Primary URI to the backup - propagation is instant.

For automatic failover at the carrier level, contact [support@vobiz.ai](mailto:support@vobiz.ai) - multi‑URI fallback is a per‑account configuration.

## Tips

* **Always include the port.** `example.com:5060` is clearer than relying on a default - and several common firewalls reject SIP without an explicit port.
* **Use TLS for cloud PBXes.** UDP over the open internet is fine for fixed‑IP deployments, but TLS prevents eavesdropping and SIP fingerprinting for cloud setups.
* **Name the URI well.** The list grows fast; "Primary Mumbai PBX" beats `34.73.214.124:5060` when you're staring at 28 entries.

## What's next

<CardGroup cols={2}>
  <Card title="Inbound Trunks" icon="arrow-down-to-bracket" href="/docs/platform/sip/inbound-trunks">
    Link this URI to a trunk and start receiving calls.
  </Card>

  <Card title="SIP Call Logs" icon="list" href="/docs/platform/sip/call-logs">
    Verify inbound traffic landed on the right URI.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.