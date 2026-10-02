> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Bring Your Own Carrier (BYOC)

> Connect your existing carrier, SBC, or PBX to Vobiz. What details to send us, which Vobiz IP ranges to whitelist, and how the provisioning process runs end to end.

Bring Your Own Carrier (BYOC) lets you keep your existing carrier relationship, SBC, or on-premise PBX and route that traffic through Vobiz. Your numbers stay where they are — Vobiz becomes the platform layer on top.

<Info>
  **Where do the IPs and numbers come from?**

  Both come from your existing telephony provider, not from Vobiz.

  | What we need | Where you get it |
  | - | - |
  | **SIP signalling IPs / CIDR blocks** | Your carrier or SBC provider publishes these. If you run your own SBC or PBX, it is that server's public IP. |
  | **Phone numbers (DIDs)** | You already own them at your provider. They stay there — you tell us which ones to expect. |
</Info>

## Finding your carrier's IPs

If you use a hosted provider, the signalling IPs are in their public documentation:

| Provider | Where to look |
| - | - |
| **Plivo** | "SIP signaling" page — lists `phone.plivo.com` / `app.plivo.com` and the external SIP endpoint IPs |
| **Twilio** | "Elastic SIP Trunking IP addresses" — published as CIDR blocks |
| **Telnyx** | "SIP connection IPs" |
| **Exotel / Ozonetel / Knowlarity** | Supplied by your account manager on request |

If you run your **own** SBC — FreeSWITCH, Asterisk, Kamailio, OpenSIPS, Avaya, or Cisco CUBE — there is nothing to look up. It is the public IP of that machine, or the NAT address it presents.

<Tip>
  The exact phrasing to send your provider: *"Please send me the source IP addresses your platform uses for outbound SIP signalling."* That is the list we need.
</Tip>

## 1. What you send us

### 1.1 Your SIP signalling IPs

Individual IPs or CIDR blocks. All of these are valid:

```text theme={null}
203.0.113.45              single host
203.0.113.0/27            a block
2600:1f1c:...:3891/128    IPv6, if your provider uses it
```

<Warning>
  **Every IP that may originate a call must be listed.** Traffic from an address that is not on the list is rejected with `403 Forbidden` — this is the single most common cause of a failed BYOC launch.
</Warning>

### 1.2 Transport and port

```text theme={null}
UDP or TCP  →  port 5060
TLS         →  port 5061
```

<Warning>
  **If you use TLS, state the port explicitly.** A TLS trunk submitted without a port falls back to `5060`, and calls then ring for roughly 10 seconds before failing without a clear error. Confirm the port before you go live.
</Warning>

### 1.3 Your phone numbers

The E.164 numbers you are bringing, for example `+919876543210`. They remain owned by and billed through your provider. We map them to your trunk so inbound calls route to the right place.

### 1.4 Where we deliver calls to you (origination URI)

The hostname or IP your equipment listens on:

```text theme={null}
sip:sbc.yourcompany.com          or       sip:203.0.113.45:5060
```

You can supply a second URI as failover, with its own priority and weight. See [Origination URIs](/docs/trunks/origination-uri) for how priority and weight are applied.

### 1.5 Choose an authentication method

| Method | How it works | Best when |
| - | - | - |
| **IP-based** (recommended) | We whitelist your IPs. No password, no registration. | Your IPs are static |
| **SIP digest** | Username and password we issue | Your IPs are dynamic |

You can use both across different trunks. See [IP ACLs](/docs/trunks/ip-acl) and [Credentials](/docs/trunks/credentials).

## 2. What you whitelist on your side

[IP Address Whitelisting](/docs/concepts/ip-whitelisting) is the authoritative, always-current list of every Vobiz IP address and port. Whitelist the SIP signalling and RTP media entries from that page on your firewall or SBC — those are the ranges a BYOC trunk uses.

<Card title="IP Address Whitelisting" icon="list-check" href="/docs/concepts/ip-whitelisting" horizontal>
  All Vobiz SIP signalling, RTP media, and callback IPs with ports and directions.
</Card>

Two BYOC-specific points on top of that list:

* **Point your trunk at `sip.vobiz.ai`.** It resolves round-robin across the Vobiz signalling SBCs, so use the hostname rather than pinning a single IP.
* **Media is direct, signalling is proxied.** RTP flows between your equipment and our media layer, not through the signalling SBCs — so the RTP media entries have to be open independently of the SIP ports. Whitelist the CIDR blocks rather than individual hosts; the media fleet scales with load and new hosts appear inside those blocks.

<Info>
  **Whitelisting is mutual.** Allowing our IPs on your side is separate from us whitelisting yours. Both are required before calls will complete. Re-confirm the current list with us at provisioning time.
</Info>

## 3. Provisioning process

<Steps>
  <Step title="You send us your details">
    Everything in section 1: signalling IPs, transport and port, numbers, origination URI, and authentication method.
  </Step>

  <Step title="We create the carrier record">
    Vobiz whitelists your IPs on our SBCs.
  </Step>

  <Step title="We create the trunk">
    Vobiz provisions the trunk and registers your numbers against it.
  </Step>

  <Step title="You whitelist our ranges">
    Allow the signalling and media ranges from section 2 through your firewall.
  </Step>

  <Step title="You point your SBC at Vobiz">
    Direct your SBC or carrier at `sip.vobiz.ai`.
  </Step>

  <Step title="Test both directions">
    Place a test call each way. We confirm that signalling and media are both established.
  </Step>
</Steps>

Typical turnaround once we have your details: **same business day.**

## 4. Worth knowing before you start

<AccordionGroup>
  <Accordion title="Concurrency and CPS are enforced per account" icon="gauge">
    Limits apply to your account as a whole, not per trunk — your base account limit plus any purchased channel capacity. If you need a specific ceiling, tell us up front so we can set it during provisioning.
  </Accordion>

  <Accordion title="Caller ID must be a number you own on the account" icon="id-card">
    Presenting a CLI that is not registered to you is rejected with `403`. If you release a number, update your dialler's outbound caller ID at the same time — calls presenting the released number will fail.
  </Accordion>

  <Accordion title="Media is direct, signalling is proxied" icon="tower-broadcast">
    A firewall that allows 5060/5061 but not the RTP range produces a call that connects with no audio. If you get one-way or no audio, check the UDP media range first.
  </Accordion>

  <Accordion title="Codec support" icon="waveform">
    We support G.711 (PCMU/PCMA), G.729, and Opus. Send us your preference order and we will configure the trunk to match.
  </Accordion>
</AccordionGroup>

## 5. Ready-to-send checklist

Copy this, fill it in, and send it to [support@vobiz.ai](mailto:support@vobiz.ai).

```text BYOC onboarding checklist theme={null}
Company:
Provider (or "own SBC"):

SIP signalling IPs / CIDR:
Transport:                        UDP / TCP / TLS
Port:                             5060 / 5061 / other
Auth method:                      IP-based / SIP digest

Numbers (E.164):

Origination URI (where we send calls to you):
Failover URI (optional):

Codec preference:
Expected concurrent calls:
Expected calls per second:
Technical contact (name / email / phone):
```

## Next steps

<CardGroup cols={2}>
  <Card title="SIP Trunking" icon="network-wired" href="/docs/concepts/sip-trunking">
    How SIP signalling and RTP media work, and where trunks fit.
  </Card>

  <Card title="Create a Trunk" icon="plus" href="/docs/trunks/create-trunk">
    Provision a trunk over the API once your carrier record exists.
  </Card>

  <Card title="IP Access Control Lists" icon="shield-halved" href="/docs/trunks/ip-acl">
    Manage the IP addresses authorised to use your trunk.
  </Card>

  <Card title="IP Address Whitelisting" icon="list-check" href="/docs/concepts/ip-whitelisting">
    The full platform IP list, including callback delivery.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.