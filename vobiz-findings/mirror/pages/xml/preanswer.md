> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# PreAnswer XML Element – Early Media Before Call Answer | Vobiz

> Answer incoming calls in early media mode with the Vobiz PreAnswer element. Play audio or speak text before the call is formally answered - SIP-only feature.

The PreAnswer element answers an incoming call in early media mode. This is useful when you want to play custom caller tunes or to speak text while the call is still in an unanswered state.

**Note:** Not all phone numbers support this feature. The Browser SDK does not support early media (PreAnswer) as it is not part of the WebRTC specification.

## Attributes

The `<PreAnswer>` element has no attributes.

## Nesting rules

Nest `Speak`, `Play`, and `Wait` elements within the `PreAnswer` element. Other verbs are not allowed inside `PreAnswer`. Audio played during early media is not billed, since the call is not yet answered.

`PreAnswer` should be the first element in your `<Response>`. Once it finishes, place the elements that should run after the call is answered (for example, `Gather` or `Dial`) after the `PreAnswer` block.

## Examples

### Speak an announcement before answering

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <PreAnswer>
        <Speak>Your call may be recorded for quality purposes.</Speak>
    </PreAnswer>
    <Speak>Thank you for calling. How can we help?</Speak>
</Response>
```

### Play a custom ringback tone

Play branded audio while the call is still ringing, then continue once it is answered. See [Notify callers](/docs/xml/preanswer/notify-callers).

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <PreAnswer>
        <Play loop="0">https://yourcdn.com/custom-ringback.mp3</Play>
    </PreAnswer>
    <Dial>
        <Number>14155551234</Number>
    </Dial>
</Response>
```

## Edge cases and tips

* **Not universally supported.** Early media depends on the carrier and number type. Some PSTN routes and all WebRTC (Browser SDK) calls do not support `PreAnswer` - the verbs run only after the call is answered in that case. Always make the flow correct whether or not early media is honored.
* **No billsec for early media.** Audio in `PreAnswer` plays before answer, so it does not count toward billed duration. Move anything you want billed (or that needs a fully answered call, like `Dial` or `Gather`) outside `PreAnswer`.
* **Only `Speak`, `Play`, and `Wait`.** Vobiz ignores or errors on other verbs inside `PreAnswer`.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.