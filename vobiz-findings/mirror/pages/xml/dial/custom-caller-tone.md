> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Custom caller tone

> Return Play, Speak, or Wait instructions from dialMusic while Vobiz connects a Dial destination.

Set `dialMusic` to a URL when you want Vobiz to request custom XML instructions while it connects a Dial destination. The endpoint must return a valid `<Response>` containing `<Play>`, `<Speak>`, and/or `<Wait>`.

## Dial XML

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial
      callerId="+14155550100"
      timeout="30"
      dialMusic="https://example.com/dial-music">
    <Number>+14155550101</Number>
  </Dial>
</Response>
```

## Response from dialMusic

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Speak>Your call is being connected.</Speak>
  <Wait length="2"/>
</Response>
```

Vobiz requests the `dialMusic` endpoint with `POST`. Return XML instructions rather than a direct MP3 or WAV response.

<Info>
  Omit `dialMusic` or set it to `real` to use the ordinary ringback path.
</Info>

The destination carrier and the timing of answer or early media can affect what the A-leg hears before the bridge connects.

## Next steps

* [Review all Dial attributes](/docs/xml/dial)
* [Handle Dial callbacks](/docs/xml/dial/dial-status-reporting)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.