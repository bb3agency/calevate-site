> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Number XML element

> Dial an E.164 PSTN destination inside the Vobiz Dial element, optionally sending DTMF after answer or during early media.

Nest `<Number>` inside [`<Dial>`](/docs/xml/dial) to create a PSTN B-leg. Use E.164 format for both the destination and the parent `callerId`.

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial callerId="+14155550100" timeout="30">
    <Number>+14155550101</Number>
  </Dial>
</Response>
```

<Warning>
  Set the parent `callerId` to a Vobiz number owned or authorized by your account. If you omit it, Vobiz derives a number from the existing A-leg, which may not be authorized for the outbound B-leg.
</Warning>

## Attributes

| Attribute | Description |
| - | - |
| `sendDigits` <br /> *string* | Optional DTMF sequence scheduled after the destination answers. Use digits and `w` pause characters. There is no default. |
| `sendOnPreanswer` <br /> *boolean* | When `true`, Vobiz schedules `sendDigits` on the early-media path instead of the post-answer path. Default: `false`. |

## Dial an extension after answer

Use `sendDigits` when the destination expects an extension or IVR selection after answering. Add leading `w` characters when the destination needs a pause before the first digit.

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial callerId="+14155550100" timeout="30">
    <Number sendDigits="wwww2410">+14155550101</Number>
  </Dial>
</Response>
```

Vobiz sends DTMF using telephone-event signaling when the media path supports it. The destination IVR or SIP endpoint must support and interpret those events.

## Send digits during early media

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial callerId="+14155550100" timeout="30">
    <Number sendDigits="ww1" sendOnPreanswer="true">
      +14155550101
    </Number>
  </Dial>
</Response>
```

Use `sendOnPreanswer="true"` only when the destination provides early media and expects DTMF before answer. Carrier and endpoint support determines whether the remote system receives and acts on the sequence during early media.

## Dial several numbers concurrently

Add sibling `<Number>` elements to attempt multiple destinations at the same time:

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial
      callerId="+14155550100"
      timeout="30"
      callbackUrl="https://example.com/dial-events">
    <Number>+14155550101</Number>
    <Number>+14155550102</Number>
  </Dial>
</Response>
```

Vobiz bridges the first destination that answers and cancels the remaining attempts. See [Simultaneous dialing](/docs/xml/dial/simultaneous-dialing) for callback outcomes.

## Next steps

* [Review the Dial element](/docs/xml/dial)
* [Handle Dial callbacks](/docs/xml/dial/dial-status-reporting)
* [Dial a SIP or WebRTC user](/docs/xml/dial/user)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.