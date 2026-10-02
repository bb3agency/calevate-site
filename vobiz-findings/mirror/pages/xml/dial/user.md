> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# User XML element

> Dial a SIP URI or registered Vobiz WebRTC/SIP user inside Dial, with optional DTMF and X-VH metadata.

Nest `<User>` inside [`<Dial>`](/docs/xml/dial) to create a SIP or registered WebRTC/SIP B-leg. Set the parent `callerId` to a Vobiz number owned or authorized by your account.

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial
      callerId="+14155550100"
      timeout="30"
      timeLimit="1800"
      callbackUrl="https://example.com/dial-events"
      action="https://example.com/dial-result"
      redirect="false">
    <User>sip:agent@example.com</User>
  </Dial>
</Response>
```

<Warning>
  Set the parent `callerId` to a Vobiz number owned or authorized by your account, in E.164 format.
</Warning>

The user must resolve to a reachable SIP or registered Vobiz WebRTC endpoint. The B-leg uses the same `DialAnswer`, `DialConnected`, `DialHangup`, and final action lifecycle as a `<Number>` B-leg.

## Attributes

| Attribute | Description |
| - | - |
| `sendDigits` <br /> *string* | Optional DTMF sequence scheduled after the user answers. Use digits and `w` pause characters. There is no default. |
| `sendOnPreanswer` <br /> *boolean* | When `true`, schedules `sendDigits` on the early-media path instead of the post-answer path. Default: `false`. |
| `sipHeaders` <br /> *string* | Comma-separated `key=value` metadata pairs attached to the SIP B-leg. Vobiz exposes them with an `X-VH-` prefix in Dial lifecycle callbacks. |

## Send metadata to the SIP leg

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial
      callerId="+14155550100"
      timeout="30"
      callbackUrl="https://example.com/dial-events"
      callbackMethod="POST">
    <User sipHeaders="Reason=transfer,Reference=abc123">
      sip:agent@example.com
    </User>
  </Dial>
</Response>
```

The Dial callbacks include fields such as:

```text theme={null}
X-VH-Reason=transfer
X-VH-Reference=abc123
```

These are application-defined metadata fields. Do not use `sipHeaders` to set the displayed PSTN caller ID; set the parent `callerId` instead.

Vobiz does not expand placeholders in these values. Render values such as account references or caller identifiers in your application before returning the XML.

## Send digits after answer

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial callerId="+14155550100" timeout="30">
    <User sendDigits="wwww2410">sip:agent@example.com</User>
  </Dial>
</Response>
```

Vobiz schedules the sequence on the post-answer DTMF path. The destination must support and interpret telephone-event DTMF.

## Caller ID and caller name

`callerId` on the parent `<Dial>` must be a Vobiz number owned or authorized by the account placing the call, in E.164 format. It is required in practice for any `<User>` B-leg created from an inbound call flow.

If `callerId` is omitted, Vobiz derives it from the A-leg. On an inbound call that number belongs to the caller, not to your account, and B-leg creation fails with:

```text theme={null}
The from number <number> is not owned by this account
```

The `<Dial>` then aborts with no B-leg, so no `DialAnswer`, `DialConnected` or `DialHangup` callbacks fire, and execution continues with the next element in the document.

`callerName` is optional. Display depends on the destination endpoint, carrier, and device.

## Handle an unreachable user

Elements after `</Dial>` run only when no bridge is established — an unregistered user, a declined call, or a timeout. Placing a bare `<Hangup/>` there disconnects the caller on any failure, which is rarely what you want. Give them something to hear instead:

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial callerId="+14155550100" timeout="30">
    <User>sip:agent@example.com</User>
  </Dial>
  <Speak>Sorry, no agent is available right now. Please try again shortly.</Speak>
</Response>
```

Use `action` with `redirect="true"` if your application needs to decide the fallback based on the Dial result.

## Next steps

* [Review the Dial element](/docs/xml/dial)
* [Handle Dial callbacks](/docs/xml/dial/dial-status-reporting)
* [Dial a PSTN number](/docs/xml/dial/number)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.