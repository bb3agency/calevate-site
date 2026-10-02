> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Sequential dialing

> Attempt PSTN destinations in sequence by returning the next Dial instruction from the previous Dial action URL.

Use one destination per `<Dial>` and return the next `<Dial>` from its `action` URL when the attempt does not connect. This keeps the sequence explicit in your application.

<Info>
  Sibling `<Number>` elements inside one `<Dial>` run concurrently. Use separate Dial instructions when destinations must run in order.
</Info>

## Attempt the first destination

Set `redirect="true"` so Vobiz executes the XML returned by the action endpoint:

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial
      callerId="+14155550100"
      timeout="20"
      action="https://example.com/dial-next"
      method="POST"
      redirect="true">
    <Number>+14155550101</Number>
  </Dial>
</Response>
```

Your `/dial-next` handler receives the final `DialStatus`. Return a fallback Dial only for outcomes your application considers unsuccessful, such as `no-answer`, `busy`, or `failed`. If the call completed successfully, return your normal completion XML instead.

## Return the fallback destination

For an unsuccessful first attempt, `/dial-next` can return:

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial
      callerId="+14155550100"
      timeout="20"
      action="https://example.com/dial-result"
      method="POST"
      redirect="false">
    <Number>+14155550102</Number>
  </Dial>
  <Hangup/>
</Response>
```

Because the second Dial uses `redirect="false"`, Vobiz sends its final result to `/dial-result`, ignores XML returned by that endpoint, and continues to `<Hangup/>`.

<Warning>
  Replace `callerId` with a Vobiz number owned or authorized by your account. Set each Dial `timeout` explicitly so an unavailable destination does not delay the sequence.
</Warning>

## Next steps

* [Review Number attributes](/docs/xml/dial/number)
* [Handle the final Dial result](/docs/xml/dial/dial-status-reporting)
* [Dial destinations concurrently](/docs/xml/dial/simultaneous-dialing)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.