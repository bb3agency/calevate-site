> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Dial XML element

> Bridge the current call to PSTN numbers or SIP users with Vobiz Dial, with explicit answer and connected-call limits, real-time events, and a final result callback.

Use `<Dial>` to create one or more B-legs and bridge the first successful destination to the current A-leg. Nest [`<Number>`](/docs/xml/dial/number) for a PSTN destination or [`<User>`](/docs/xml/dial/user) for a SIP or registered WebRTC user.

<Warning>
  For PSTN forwarding and transfer flows, set `callerId` to a Vobiz number owned or authorized by your account.

  If you omit `callerId`, Vobiz derives it from the existing A-leg. B-leg creation may fail if that number is not authorized for outbound calling. Use E.164 format, such as `+14155550100`.
</Warning>

## How Dial works

```text theme={null}
1. Vobiz creates the dialed B-leg or B-legs.
2. callbackUrl receives real-time answer, connected, digits, and hangup events.
3. Vobiz bridges the successful B-leg to the current A-leg.
4. action receives one final result after Dial finishes.
5. redirect determines whether Vobiz executes XML returned by action.
```

`callbackUrl` and `action` serve different purposes. Use `callbackUrl` to observe the B-leg while it is active. Use `action` to receive the final result and optionally choose the next call-control step.

## Child elements

| Child | Use |
| - | - |
| [`Number`](/docs/xml/dial/number) | Dial an E.164 PSTN phone number. |
| [`User`](/docs/xml/dial/user) | Dial a SIP URI or registered Vobiz WebRTC/SIP user. |

You can include multiple child destinations for simultaneous dialing. Vobiz attempts sibling destinations concurrently and bridges the first one that answers successfully. See [Simultaneous dialing](/docs/xml/dial/simultaneous-dialing).

You can also place one phone number directly inside `<Dial>` as shorthand, but an explicit `<Number>` child is easier to extend with attributes and callbacks.

## Attributes

| Attribute | Description |
| - | - |
| `action` <br /> *string* | Final result URL requested after Dial finishes. Use the `redirect` attribute to control whether Vobiz executes XML returned by this URL. |
| `method` <br /> *string* | HTTP method for `action`. Values: `GET`, `POST`. Default: `POST`. |
| `callbackUrl` <br /> *string* | URL that receives real-time B-leg lifecycle events. |
| `callbackMethod` <br /> *string* | HTTP method for `callbackUrl`. Values: `GET`, `POST`. Default: `POST`. |
| `redirect` <br /> *boolean* | Controls the response from `action`. With `true`, Vobiz requests `action` and executes its returned XML. With `false`, Vobiz still sends the final Dial result to `action` but does not use the returned XML to redirect call control. Default: `true`. |
| `callerId` <br /> *string* | Caller number presented on the B-leg. For PSTN calls, use an owned or authorized Vobiz number in E.164 format. If omitted, Vobiz derives the value from the A-leg. |
| `callerName` <br /> *string* | Caller name passed toward the B-leg. The destination carrier and device decide whether to display it. |
| `timeout` <br /> *integer* | Maximum number of seconds to wait for a B-leg to answer. When omitted, the effective default applied downstream is **120 seconds**. Set it explicitly for predictable routing behaviour. |
| `timeLimit` <br /> *integer* | Maximum connected duration of the B-leg in seconds. This timer begins after the B-leg connects; ringing time is not included. Default: `14400` seconds. |
| `hangupOnStar` <br /> *boolean* | When `true`, pressing `*` on the A-leg ends the bridge. Default: `false`. |
| `dialMusic` <br /> *string* | URL that returns `<Play>`, `<Speak>`, and/or `<Wait>` instructions for the A-leg while Vobiz connects the destination. Use `real` for the ordinary ringback path. Default: `real`. |
| `confirmSound` <br /> *string* | URL requested after the B-leg answers. It must return XML containing only `<Play>`, `<Speak>`, and/or `<Wait>`. |
| `confirmKey` <br /> *string* | Digit configured with `confirmSound`. Values: `0`–`9`, `#`, or `*`. Enforcement as an acceptance gate is currently unverified, so do not depend on a keypress to control whether the B-leg connects. |
| `confirmTimeout` <br /> *integer* | Confirmation window after the B-leg answers. Set it explicitly when you use confirmation audio. |
| `digitsMatch` <br /> *string* | Comma-separated patterns to match digits pressed on the A-leg. Matching digits produce a `DialDigitsMatch` callback. |
| `digitsMatchBLeg` <br /> *string* | Comma-separated patterns to match digits pressed on the B-leg. Matching digits produce a `DialDigitsMatch` callback. |
| `sipHeaders` <br /> *string* | Comma-separated `key=value` metadata pairs. Vobiz adds the `X-VH-` prefix to these values in Dial webhooks. |

<Info>
  `timeout` and `timeLimit` control different phases. `timeout` covers the unanswered ringing phase. `timeLimit` covers only the connected bridge.
</Info>

## Callback lifecycle

### Callback channels

| Channel | When it fires | What to return |
| - | - | - |
| `callbackUrl` | During B-leg answer, connection, matching digits, and hangup events. | A successful HTTP response. Returned XML does not control the call. |
| `action` | Once after the Dial attempt finishes. | Return XML only when `redirect="true"` and you want Vobiz to continue with a new flow. |

Both channels support `GET` and `POST`. If you omit `method` or `callbackMethod`, Vobiz uses `POST`.

### Real-time events sent to callbackUrl

| `Event` | `DialAction` | Purpose | Typical event-specific fields |
| - | - | - | - |
| `DialAnswer` | `answer` | The B-leg answered. | `DialBLegUUID`, `DialBLegStatus`, `DialBLegFrom`, `DialBLegTo`, `DialBLegPosition` |
| `DialConnected` | `connected` | The B-leg connected to the A-leg. | `DialBLegUUID`, `DialBLegStatus`, `DialBLegFrom`, `DialBLegTo`, `DialBLegPosition` |
| `DialDigitsMatch` | `digits` | A configured A-leg or B-leg digit pattern matched. | `DialDigitsMatch`, `DialDigitsPressedBy` |
| `DialHangup` | `hangup` | The B-leg ended or a non-winning simultaneous leg was cancelled. | Duration, bill duration, hangup cause, code, name, and source |

Common fields include `CallUUID`, `DialALegUUID`, `DialBLegUUID`, `DialBLegFrom`, `DialBLegTo`, and `DialBLegPosition`. Not every field is present on every event.

`STIRVerification` may also appear on applicable calls. Values are `Verified`, `Not Verified`, or `Not Applicable`, depending on the call direction, attestation, destination, and whether STIR/SHAKEN applies.

The values observed for `DialDigitsPressedBy` are:

* `aleg` for a match from `digitsMatch`
* `bleg` for a match from `digitsMatchBLeg`

### Final fields sent to action

| Field | Description |
| - | - |
| `Event` | Final callback event type. |
| `DialStatus` | Final Dial result, such as `completed`, `busy`, `failed`, `cancel`, `timeout`, or `no-answer`. |
| `DialRingStatus` | Platform ring-status value. Do not use it as proof that the destination handset physically rang. |
| `DialHangupCause` | Final Dial hangup cause. |
| `DialALegUUID` | A-leg identifier. |
| `DialBLegUUID` | B-leg identifier. It may be empty when no B-leg was created or answered. |

See [Dial status reporting](/docs/xml/dial/dial-status-reporting) for request examples and failure handling.

## DTMF matching

Use `digitsMatch` and `digitsMatchBLeg` when you need real-time callbacks for keypad input during a bridge.

<Tabs>
  <Tab title="A-leg digits">
    ```xml theme={null}
    <?xml version="1.0" encoding="UTF-8"?>
    <Response>
      <Dial
          callerId="+14155550100"
          callbackUrl="https://example.com/dial-events"
          callbackMethod="POST"
          digitsMatch="123">
        <Number>+14155550101</Number>
      </Dial>
    </Response>
    ```

    A matching callback contains `DialAction=digits`, `DialDigitsMatch=123`, and `DialDigitsPressedBy=aleg`.
  </Tab>

  <Tab title="B-leg digits">
    ```xml theme={null}
    <?xml version="1.0" encoding="UTF-8"?>
    <Response>
      <Dial
          callerId="+14155550100"
          callbackUrl="https://example.com/dial-events"
          callbackMethod="POST"
          digitsMatchBLeg="456">
        <Number>+14155550101</Number>
      </Dial>
    </Response>
    ```

    A matching callback contains `DialAction=digits`, `DialDigitsMatch=456`, and `DialDigitsPressedBy=bleg`.
  </Tab>
</Tabs>

## Complete PSTN transfer with recording

Place a self-closing `<Record/>` before `<Dial>` to record the full session, including bridged audio. This example uses `redirect="false"`, so `action` receives the final Dial result but its response does not replace the remaining XML flow.

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Record
      fileFormat="mp3"
      recordSession="true"
      maxLength="3600"
      callbackUrl="https://example.com/recording-ready"
      callbackMethod="POST"
      redirect="false"
      playBeep="false"/>

  <Dial
      callerId="+14155550100"
      timeout="30"
      timeLimit="1800"
      sipHeaders="Reason=billing,Reference=abc123"
      callbackUrl="https://example.com/dial-events"
      callbackMethod="POST"
      action="https://example.com/dial-result"
      method="POST"
      redirect="false">
    <Number sendDigits="wwww2410">+14155550101</Number>
  </Dial>

  <Hangup/>
</Response>
```

Your application must replace the example caller ID with an owned or authorized Vobiz number. Vobiz does not expand placeholders such as `{{caller_id}}`; render application values before you return the XML.

A transferred call runs as two legs with two CDRs and two charges. See [Transferred calls end to end](/docs/xml/dial/transferred-calls) for the webhook order, leg correlation, and billing.

## Dial a SIP or WebRTC user

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial
      timeout="30"
      timeLimit="1800"
      callbackUrl="https://example.com/dial-events"
      callbackMethod="POST"
      action="https://example.com/dial-result"
      method="POST"
      redirect="false">
    <User sipHeaders="Reason=transfer,Reference=abc123">
      sip:agent@example.com
    </User>
  </Dial>
  <Hangup/>
</Response>
```

For registered Vobiz SIP/WebRTC users, Vobiz sends answer, connected, and hangup events through the same Dial callback lifecycle.

## No-answer behavior

When the configured answer window expires, the real-time hangup callback can report:

```text theme={null}
Event=DialHangup
DialAction=hangup
DialBLegHangupCause=NO_ANSWER
DialBLegHangupCauseCode=6010
DialBLegHangupCauseName=Ring Timeout Reached
DialBLegHangupSource=Vobiz
```

The final `action` request reports `DialStatus=no-answer` and `DialHangupCause=NO_ANSWER`. A final `DialBLegUUID` may be empty for this outcome.

## Next steps

* [Dial a phone number](/docs/xml/dial/number)
* [Dial a SIP or WebRTC user](/docs/xml/dial/user)
* [Dial several destinations simultaneously](/docs/xml/dial/simultaneous-dialing)
* [Handle Dial callbacks](/docs/xml/dial/dial-status-reporting)
* [Follow a transferred call end to end](/docs/xml/dial/transferred-calls)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.