> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# SIP headers

> Receive X-VH custom headers from inbound SIP calls or pass application metadata through Dial and User callbacks.

Use custom SIP headers to carry application metadata into your answer URL or through an outbound Dial flow.

## Inbound SIP headers

For an inbound call from a SIP endpoint, configure the originating SIP phone or endpoint to send custom headers whose names start with `X-VH-`. Vobiz includes those values in the HTTP request that fetches XML from your application.

For example, your SIP endpoint can send:

```text theme={null}
X-VH-Reference: order-4821
X-VH-Reason: support
```

Read the corresponding `X-VH-Reference` and `X-VH-Reason` values from the inbound answer request. Validate header values before using them in application logic.

## Outbound Dial metadata

Set `sipHeaders` on `<Dial>` to attach metadata to a Dial flow. Vobiz exposes each pair with an `X-VH-` prefix in related lifecycle callbacks.

<Warning>
  **The key you send must *end* with `X-VH`.** The `X-VH-` prefix is how the header
  looks when it *arrives* - it is not what you write in `sipHeaders`.

  ```
  correct     sipHeaders="ClinicX-VH=locationAlpha,RefX-VH=abc123"
  rejected    sipHeaders="Clinic=locationAlpha"
  ```

  A key that does not end with `X-VH` causes the **entire header set to be
  discarded, silently** - no error, no warning, and the call proceeds without any
  of your metadata. If your headers are not arriving, check the suffix first.
</Warning>

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial
      callerId="+14155550100"
      sipHeaders="ReasonX-VH=billing,ReferenceX-VH=abc123"
      callbackUrl="https://example.com/dial-events"
      action="https://example.com/dial-result"
      redirect="false">
    <Number>+14155550101</Number>
  </Dial>
</Response>
```

The Dial callbacks include:

```text theme={null}
X-VH-Reason=billing
X-VH-Reference=abc123
```

Parent-level metadata applies to the Dial flow and its webhooks. A pair such as `CallerId=value` is only custom metadata; it does not set the PSTN caller ID. Use the parent `callerId` attribute for caller-ID presentation.

## User SIP-leg metadata

Set `sipHeaders` on `<User>` when metadata must be attached to the SIP B-leg:

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial callbackUrl="https://example.com/dial-events">
    <User sipHeaders="ReasonX-VH=transfer,ReferenceX-VH=abc123">
      sip:agent@example.com
    </User>
  </Dial>
</Response>
```

Vobiz attaches these values to the SIP B-leg and includes the corresponding `X-VH-` fields in answer, connected, and hangup callbacks.

## Render values in your application

Vobiz does not expand application placeholders in XML attributes. Render the final value before returning XML:

```xml theme={null}
<Dial sipHeaders="ReferenceX-VH=order-4821">
  <Number>+14155550101</Number>
</Dial>
```

Do not return unresolved placeholders such as `Reference={{order_id}}` unless that literal value is what you intend to send.

## Next steps

* [Review the Dial element](/docs/xml/dial)
* [Configure User destinations](/docs/xml/dial/user)
* [Handle Dial callbacks](/docs/xml/dial/dial-status-reporting)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.