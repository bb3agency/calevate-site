> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# IP Address Whitelisting

> Whitelist these IP addresses on your firewall to ensure uninterrupted SIP signaling, RTP media, WebSocket streaming, and callback delivery between your infrastructure and Vobiz.

<CardGroup cols={2}>
  <Card title="SIP Signaling" icon="phone">
    10 IP addresses · Port 5060/5061
  </Card>

  <Card title="RTP Media" icon="server">
    9 entries · UDP 5000–65535
  </Card>

  <Card title="Callbacks" icon="rotate">
    3 IP addresses · HTTPS 443
  </Card>

  <Card title="WebSocket Streaming" icon="wave-square">
    9 entries · TCP 443 to your `wss://`
  </Card>
</CardGroup>

<Warning>
  **Important:** IP addresses are subject to change. Always verify the latest list with the Vobiz team before making firewall changes. Contact [support@vobiz.ai](mailto:support@vobiz.ai) to subscribe to IP change notifications.
</Warning>

## SIP Signaling

Allow inbound and outbound SIP traffic from these IPs. Used for call setup, tear-down, and control messages between your SIP infrastructure and Vobiz.

**India**

| IP Address | Protocol | Port | Direction |
| - | - | - | - |
| `13.203.7.132` | UDP / TCP | 5060, 5061 | Inbound + Outbound |
| `65.2.100.211` | UDP / TCP | 5060, 5061 | Inbound + Outbound |
| `13.126.98.234` | UDP / TCP | 5060, 5061 | Inbound + Outbound |
| `13.235.11.131` | UDP / TCP | 5060, 5061 | Inbound + Outbound |
| `13.233.44.61` | UDP / TCP | 5060, 5061 | Inbound + Outbound |
| `3.111.255.163` | UDP / TCP | 5060, 5061 | Inbound + Outbound |
| `3.111.128.110` | UDP / TCP | 5060, 5061 | Inbound + Outbound |
| `43.204.64.203` | UDP / TCP | 5060, 5061 | Inbound + Outbound |
| `15.207.232.91` | UDP / TCP | 5060, 5061, 5063 | Inbound + Outbound |
| `35.154.133.28` | UDP / TCP | 5060, 5061, 5063 | Inbound + Outbound |

<Info>
  **Firewall rule:** Allow TCP/UDP on ports `5060` and `5061` for all SIP signaling IPs in both directions.
</Info>

### Which of these your trunk points at

If you are configuring a SIP trunk or bringing your own carrier, two subsets of the table above matter most:

| Role | IPs | What it is |
| - | - | - |
| **`sip.vobiz.ai`** | `13.203.7.132`, `65.2.100.211` | The signaling SBCs the hostname resolves to. Point your trunk, SBC, or PBX at the **hostname**, not a single IP — it round-robins across both. |
| **Origination sources** | `13.233.44.61`, `3.111.255.163` | Calls Vobiz delivers **toward** your origination URI arrive from these addresses. |

Whitelist the full table regardless — the remaining IPs carry signaling for other call paths on the platform.

## RTP Media

Allow UDP traffic from these IPs for the audio media stream. RTP carries the actual voice packets during a live call.

**India**

| IP Address | Protocol | Port Range | Direction |
| - | - | - | - |
| `3.110.99.6` | UDP | 5000–65535 | Inbound + Outbound |
| `65.1.145.87` | UDP | 5000–65535 | Inbound + Outbound |
| `13.234.214.51` | UDP | 5000–65535 | Inbound + Outbound |
| `13.200.197.87` | UDP | 5000–65535 | Inbound + Outbound |
| `13.202.13.57` | UDP | 5000–65535 | Inbound + Outbound |
| `18.96.230.96/28` | UDP | 5000–65535 | Inbound + Outbound |
| `18.96.230.112/28` | UDP | 5000–65535 | Inbound + Outbound |
| `18.96.230.208/29` | UDP | 5000–65535 | Inbound + Outbound |
| `18.96.232.168/29` | UDP | 5000–65535 | Inbound + Outbound |

<Tip>
  **Firewall rule:** Allow UDP port range `5000–65535` for all nine entries in both directions.
</Tip>

<Note>
  **Whitelist the CIDR blocks, not individual hosts.** The media fleet scales with load and new hosts are added inside `18.96.230.96/28`, `18.96.230.112/28`, `18.96.230.208/29`, and `18.96.232.168/29`. Pinning the individual addresses that answer today will drop media when the fleet grows.

  Media flows **directly** between your equipment and the media layer above — it does not pass through the signaling SBCs. A firewall that allows `5060`/`5061` but not this UDP range produces a call that connects with no audio.
</Note>

## Callbacks

Vobiz sends webhook callbacks from these IP addresses to your server. Allow inbound HTTPS traffic from these IPs so your application receives call status, hangup, and recording events.

**India**

| IP Address | Protocol | Port | Direction |
| - | - | - | - |
| `15.206.6.156` | HTTPS | 443 (80 for HTTP) | Inbound to your server |
| `35.154.59.246` | HTTPS | 443 (80 for HTTP) | Inbound to your server |
| `15.207.8.226` | HTTPS | 443 (80 for HTTP) | Inbound to your server |

<Info>
  **Firewall rule:** Allow inbound TCP port `443` (HTTPS) from all three IPs to your callback server. Port `80` only if you use plain HTTP callbacks.
</Info>

## WebSocket Streaming

When you use the [`<Stream>`](/docs/xml/stream) element, **Vobiz initiates the connection to you** — your `wss://` URL is the server, and our media fleet is the client. You do not need inbound SIP or RTP rules for a WebSocket-only integration.

If your WebSocket endpoint is IP-restricted, it must accept **inbound TCP 443** from the media fleet addresses below.

**India**

| Source | Protocol | Port | Direction |
| - | - | - | - |
| `3.110.99.6` | WSS / TCP | 443 | Inbound to your server |
| `65.1.145.87` | WSS / TCP | 443 | Inbound to your server |
| `13.234.214.51` | WSS / TCP | 443 | Inbound to your server |
| `13.200.197.87` | WSS / TCP | 443 | Inbound to your server |
| `13.202.13.57` | WSS / TCP | 443 | Inbound to your server |
| `18.96.230.96/28` | WSS / TCP | 443 | Inbound to your server |
| `18.96.230.112/28` | WSS / TCP | 443 | Inbound to your server |
| `18.96.230.208/29` | WSS / TCP | 443 | Inbound to your server |
| `18.96.232.168/29` | WSS / TCP | 443 | Inbound to your server |

<Warning>
  **These are the same addresses as the [RTP Media](#rtp-media) table, but the RTP rule does not cover them.** The RTP rule allows **UDP 5000–65535**; WebSocket streaming needs **TCP 443**. If you use both SIP media and `<Stream>`, you need **both rules** — allowing one does not imply the other.
</Warning>

<Info>
  **Firewall rule:** Allow inbound TCP port `443` from all nine entries to your WebSocket server. Whitelist the CIDR blocks rather than the individual hosts — the media fleet scales with load.
</Info>

## Protocol Whitelisting

In addition to IP addresses, ensure your firewall and ISP do not block the following protocols.

| Protocol | Port | Use |
| - | - | - |
| **SIP** | 5060 / 5061 | Call signaling (setup & teardown) |
| **RTP** | 5000–65535 UDP | Voice media streaming |
| **HTTPS** | 443 TCP | Callback / webhook delivery |
| **WSS** | 443 TCP | WebSocket streaming (`<Stream>`) — inbound to your server |

## All IPs at a Glance

<CodeGroup>
  ```text SIP Signaling theme={null}
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

  ```text RTP Media theme={null}
  3.110.99.6
  65.1.145.87
  13.234.214.51
  13.200.197.87
  13.202.13.57
  18.96.230.96/28
  18.96.230.112/28
  18.96.230.208/29
  18.96.232.168/29
  ```

  ```text Callbacks theme={null}
  15.206.6.156
  35.154.59.246
  15.207.8.226
  ```

  ```text WebSocket Streaming theme={null}
  3.110.99.6
  65.1.145.87
  13.234.214.51
  13.200.197.87
  13.202.13.57
  18.96.230.96/28
  18.96.230.112/28
  18.96.230.208/29
  18.96.232.168/29
  ```
</CodeGroup>

## Bringing your own carrier?

<Card title="Bring Your Own Carrier (BYOC)" icon="network-wired" href="/docs/concepts/bring-your-own-carrier" horizontal>
  What to send Vobiz to onboard your existing carrier, SBC, or PBX — and how these IPs fit into the provisioning process.
</Card>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.