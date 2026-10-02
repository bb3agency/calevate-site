> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# IP Access Control List (ACL) - Whitelist PBX Source IPs

> Create IP Access Control Lists in the Vobiz Console to authorise specific source IPs or CIDR ranges to send SIP traffic to your outbound trunks. Walkthrough of the ACL list, details, and Create IP Access Control List form.

An **IP Access Control List (ACL)** is a list of source IP addresses or CIDR ranges Vobiz will accept SIP traffic from on a given outbound trunk. Use it instead of (or alongside) [SIP credentials](/docs/platform/sip/credentials) when your PBX has a stable, public IP.

```text URL theme={null}
https://console.vobiz.ai/app/sip/out/ipacl
```

## The IP ACL list

<Frame caption="IP Access Control List - list and details">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/sip/sip-ip-acl_blur.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=e042b3ce40c3ea3343a97258ee680b3c" alt="IP Access Control List page with a search field, Add IP ACL button, a list showing one ACL named test with ID and CIDR 1.2.3.4/32 and Status Active, and an IP ACL Details panel on the right with Description, IP ACL ID, Status badge, CIDR/IP Addresses chip (1.2.3.4/32), and Metadata showing Created and Last Updated timestamps" style={{maxWidth: '900px', margin: '0 auto', display: 'block'}} width="8000" height="4408" data-path="images/platform/sip/sip-ip-acl_blur.png" />
</Frame>

| Column | Meaning |
| - | - |
| **Name** | Friendly label (e.g. `Mumbai DC`, `Asterisk prod`). |
| **ID** | Immutable UUID - quote in support tickets. |
| **CIDR** | The IP range(s). `1.2.3.4/32` means just that one IP; `203.0.113.0/24` means a whole /24 block. |
| **Status** | `Active` accepts traffic; `Inactive` rejects everything from those IPs without removing the rule. |

Click any card to load its details on the right.

## Details panel

| Section | Field | Meaning |
| - | - | - |
| **IP ACL Details** | Description | Friendly name. |
| | IP ACL ID | Immutable UUID. |
| | Status | `Active` or `Inactive`. |
| **CIDR/IP Addresses** | One chip per entry | All IPs/ranges associated with this ACL. |
| **Metadata** | Created / Last Updated | Both in your browser timezone. |

## Create an IP ACL

Click **+ Add IP ACL** to open the side panel.

<Frame caption="Create IP Access Control List form">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/sip/sip-ip-acl-create.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=4b135f67e178e9725472ae65b512818e" alt="Create IP Access Control List modal with Name field set to placeholder IP_ACL, IP Address List required field with placeholder 192.0.2.0/24 and hint Enter IP addresses or CIDR notation - Press Enter or comma to add each entry, Active toggle on, and Cancel and orange Create IP ACL buttons" style={{maxWidth: '720px', margin: '0 auto', display: 'block'}} width="1660" height="1544" data-path="images/platform/sip/sip-ip-acl-create.png" />
</Frame>

| Field | Required | Notes |
| - | - | - |
| **Name** | – | Friendly identifier. Defaults to `IP_ACL` if left blank. |
| **IP Address List** | ✅ | Type each IP or CIDR and press **Enter** (or `,`) to commit. Examples: `1.2.3.4` (single IP, auto‑expanded to `/32`), `203.0.113.0/24` (whole /24 block). |
| **Active** | – | Defaults on. Toggle off to provision the ACL but reject traffic. |

Click **Create IP ACL**.

## Use the ACL on a trunk

Once created:

1. Open an [Outbound Trunk](/docs/platform/sip/outbound-trunks).
2. Edit the trunk and pick the new ACL from the **IP Access Control List** dropdown.
3. Save.

From now on, SIP INVITEs from any IP in the ACL are accepted without further auth.

## Tips

* **Use `/32` for single hosts.** A bare IP like `1.2.3.4` is normalised to `1.2.3.4/32` - but being explicit makes it obvious to anyone reading the list later.
* **Stack multiple entries on one ACL.** Easier than juggling several ACLs - one per environment is the sweet spot.
* **Toggle, don't delete.** When a PBX is temporarily offline, set the ACL to `Inactive` instead of removing entries - your config returns intact when the box comes back.

## What's next

<CardGroup cols={2}>
  <Card title="Outbound Trunks" icon="arrow-up-right-from-square" href="/docs/platform/sip/outbound-trunks">
    Attach this ACL to a trunk.
  </Card>

  <Card title="Credentials List" icon="key" href="/docs/platform/sip/credentials">
    Username + password auth as an alternative to IP ACL.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.