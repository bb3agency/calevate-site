> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# SIP Credentials List - Username & Password Auth

> Create SIP credentials in the Vobiz Console - username and password pairs that authorise PBX traffic to your outbound trunks. Walkthrough of the credentials list, details, and Create Credentials List form.

A **Vobiz SIP credential** is a username/password pair your PBX uses to authenticate against an outbound trunk. Use credentials when you can't whitelist a fixed IP - common for cloud‑hosted PBXes, dynamic IPs, or distributed setups.

```text URL theme={null}
https://console.vobiz.ai/app/sip/out/credentials
```

## The Credentials list

<Frame caption="Credentials List - list, details, and status toggle">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/sip/sip-credentials_blur.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=a5c4045094de5cffb6f0965e0a709421" alt="Credentials List page with a search field, Add Credential button, a list showing credentials (trunk1, PII Test, vobiz, test, testing12345) each with ID and Status Active, and a Credential Details panel on the right showing Status toggle set to Active, Username (trunk1), Credential ID (UUID), masked Password with show/copy icons, and Metadata with Created and Last Updated timestamps" style={{maxWidth: '900px', margin: '0 auto', display: 'block'}} width="8000" height="4408" data-path="images/platform/sip/sip-credentials_blur.png" />
</Frame>

| Column | Meaning |
| - | - |
| **Name** | The credential username. |
| **ID** | Immutable UUID - quote in support tickets. |
| **Status** | `Active` accepts auth; `Inactive` blocks the username without deleting. |

Click any card to load its details on the right.

## Details panel

| Field | Meaning |
| - | - |
| **Status toggle** | Flip between `Active` and `Inactive` without deleting. |
| **Username** | The SIP `username` your PBX presents. |
| **Credential ID** | Immutable UUID. |
| **Password** | Stored hashed - Vobiz never displays plaintext after creation. Click the eye icon (👁) to reveal the value if it's been re‑entered, or the copy icon (⧉) to copy. |
| **Metadata** | Created / Last Updated timestamps. |

## Create a credential

Click **+ Add Credential** to open the side panel.

<Frame caption="Create Credentials List form">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/sip/sip-credentials-create.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=5f47f547fac9568c5dc6207625be90e5" alt="Create Credentials List modal with Username required field (placeholder johndoe) and hint Only letters, numbers, underscores and hyphens allowed, Password required field with placeholder Minimum 8 Character with special character and eye reveal icon and constraints note Password length should be between 5 and 20 should contain only alphanumeric and at least one special character from ~!@#$%^&*()_+, an Active toggle on, and Cancel and orange Create Credential buttons" style={{maxWidth: '720px', margin: '0 auto', display: 'block'}} width="1650" height="1546" data-path="images/platform/sip/sip-credentials-create.png" />
</Frame>

| Field | Required | Rules |
| - | - | - |
| **Username** | ✅ | Letters, numbers, underscores, and hyphens only. No spaces or symbols. |
| **Password** | ✅ | Length **5–20** characters. Must be alphanumeric plus at least one of `~!@#$%^&*()_+`. |
| **Active** | – | Defaults on. Toggle off to provision but reject auth. |

<Warning>
  Store the password in your password manager **now** - Vobiz won't display the plaintext again. If lost, you'll have to rotate by setting a new password.
</Warning>

Click **Create Credential**.

## Use the credential on a trunk

Once created:

1. Open an [Outbound Trunk](/docs/platform/sip/outbound-trunks).
2. Edit the trunk and pick this credential from the **Credentials List** dropdown.
3. Save.

Your PBX should now authenticate against the trunk's SIP Domain with:

```text theme={null}
SIP Server / Domain:  <trunk-id>.sip.vobiz.ai
Username:             <your username>
Password:             <your password>
Realm:                <trunk-id>.sip.vobiz.ai
```

## Tips

* **One credential per environment.** Same logic as one trunk per environment - prevents a leaked staging password from being usable in prod.
* **Rotate passwords on offboarding.** Setting the credential to `Inactive` is faster than rotating, but rotation eliminates the risk that someone re‑enables it.
* **Username uniqueness.** Vobiz rejects duplicate usernames within your account - pick something descriptive like `acme-prod-pbx-01` instead of `sip1`.

## What's next

<CardGroup cols={2}>
  <Card title="Outbound Trunks" icon="arrow-up-right-from-square" href="/docs/platform/sip/outbound-trunks">
    Attach this credential to a trunk.
  </Card>

  <Card title="IP Access Control List" icon="shield-halved" href="/docs/platform/sip/ip-access-control-list">
    IP whitelisting as an alternative to credentials.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.