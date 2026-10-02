> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Dial status reporting

> Handle real-time Dial lifecycle events through callbackUrl and receive one final Dial result through action.

Use two callback channels to observe a Dial attempt:

* `callbackUrl` receives events while each B-leg is active.
* `action` receives one final result after the Dial attempt finishes.

## Configure both callback channels

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial
      callerId="+14155550100"
      timeout="30"
      callbackUrl="https://example.com/dial-events"
      callbackMethod="POST"
      action="https://example.com/dial-result"
      method="POST"
      redirect="false">
    <Number>+14155550101</Number>
  </Dial>
  <Hangup/>
</Response>
```

This configuration sends real-time events to `/dial-events` and the final outcome to `/dial-result`. Because `redirect="false"`, Vobiz ignores any XML returned by `/dial-result` and continues with `<Hangup/>`.

<Info>
  `redirect="false"` does not disable the `action` request. It only prevents the action response from redirecting call control.
</Info>

## Choose redirect behavior

| Value | Final action request | Returned XML |
| - | - | - |
| `redirect="true"` | Sent after Dial finishes. | Vobiz executes the returned XML. |
| `redirect="false"` | Sent after Dial finishes. | Vobiz ignores the returned XML and continues the current flow. |
| Omitted | Sent after Dial finishes. | Defaults to `true`; Vobiz executes the returned XML. |

## Real-time callbackUrl events

For a successfully answered B-leg, the lifecycle is:

```text theme={null}
DialAnswer
DialConnected
DialDigitsMatch   # only after a configured pattern matches
DialHangup
DialAction        # final request to action, not callbackUrl
```

| `Event` | `DialAction` | Meaning |
| - | - | - |
| `DialAnswer` | `answer` | The destination answered. |
| `DialConnected` | `connected` | Vobiz bridged the B-leg to the A-leg. |
| `DialDigitsMatch` | `digits` | A configured A-leg or B-leg pattern matched. |
| `DialHangup` | `hangup` | The B-leg ended or lost a simultaneous-dial race. |

### Field availability

| Field | Answer | Connected | Digits | Hangup |
| - | :-: | :-: | :-: | :-: |
| `Event` | Yes | Yes | Yes | Yes |
| `DialAction` | Yes | Yes | Yes | Yes |
| `CallUUID` | Yes | Yes | Yes | Yes |
| `DialALegUUID` | Yes | Yes | Yes | Yes |
| `DialBLegUUID` | Yes | Yes | Yes | Yes |
| `DialBLegStatus` | Yes | Yes | May appear | Yes |
| `DialBLegFrom` | Yes | Yes | Yes | Yes |
| `DialBLegTo` | Yes | Yes | Yes | Yes |
| `DialBLegPosition` | Yes | Yes | May appear | Yes |
| `DialDigitsMatch` | No | No | Yes | No |
| `DialDigitsPressedBy` | No | No | Yes | No |
| `DialBLegDuration` | No | No | No | Yes |
| `DialBLegBillDuration` | No | No | No | Yes |
| Hangup cause, name, code, and source | No | No | No | Yes |

Not every common call parameter is shown in this table. Accept additional fields without rejecting the callback.

### Digits-match callback

```http theme={null}
POST /dial-events HTTP/1.1
Host: example.com
Content-Type: application/x-www-form-urlencoded

Event=DialDigitsMatch&DialAction=digits&DialDigitsMatch=123&DialDigitsPressedBy=aleg
```

`DialDigitsPressedBy` is `aleg` for `digitsMatch` and `bleg` for `digitsMatchBLeg`.

### No-answer callback

When the destination does not answer before `timeout`, the hangup event can contain:

```http theme={null}
POST /dial-events HTTP/1.1
Host: example.com
Content-Type: application/x-www-form-urlencoded

Event=DialHangup&DialAction=hangup&DialBLegHangupCause=NO_ANSWER&DialBLegHangupCauseCode=6010&DialBLegHangupCauseName=Ring%20Timeout%20Reached&DialBLegHangupSource=Vobiz
```

## Final action request

The final request summarizes the Dial attempt.

| Field | Description |
| - | - |
| `Event` | Final callback event type. |
| `DialStatus` | Final result, such as `completed`, `busy`, `failed`, `cancel`, `timeout`, or `no-answer`. |
| `DialRingStatus` | Platform ring-status value. It does not prove that the destination handset physically rang. |
| `DialHangupCause` | Final Dial hangup cause. |
| `DialALegUUID` | A-leg identifier. |
| `DialBLegUUID` | B-leg identifier. It may be empty when no B-leg was created or answered. |

<Tabs>
  <Tab title="Completed">
    ```http theme={null}
    POST /dial-result HTTP/1.1
    Host: example.com
    Content-Type: application/x-www-form-urlencoded

    Event=DialAction&DialStatus=completed&DialRingStatus=true&DialHangupCause=NORMAL_CLEARING&DialALegUUID=A_LEG_UUID&DialBLegUUID=B_LEG_UUID
    ```
  </Tab>

  <Tab title="No answer">
    ```http theme={null}
    POST /dial-result HTTP/1.1
    Host: example.com
    Content-Type: application/x-www-form-urlencoded

    Event=DialAction&DialStatus=no-answer&DialRingStatus=false&DialHangupCause=NO_ANSWER&DialALegUUID=A_LEG_UUID&DialBLegUUID=
    ```
  </Tab>
</Tabs>

## GET and POST callbacks

Set `method="GET"` or `callbackMethod="GET"` to receive the same fields in the URL query string. Both attributes default to `POST` when omitted.

Your endpoint should return a successful response quickly. Perform slow logging or analytics work asynchronously after accepting the callback.

## Handle every final status

* Treat `completed` as a successful bridge that later ended.
* Route `busy`, `no-answer`, and `timeout` to an intentional fallback such as voicemail or another destination.
* Log `failed` and `cancel` with their hangup cause for troubleshooting.
* Do not assume `DialBLegUUID` is populated for unsuccessful attempts.

## Next steps

* [Review all Dial attributes](/docs/xml/dial)
* [Match A-leg and B-leg DTMF](/docs/xml/dial#dtmf-matching)
* [Handle simultaneous-dial outcomes](/docs/xml/dial/simultaneous-dialing)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.