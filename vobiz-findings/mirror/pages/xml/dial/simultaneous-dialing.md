> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Simultaneous dialing

> Attempt several PSTN destinations concurrently with sibling Number elements and handle the winning and LOSE_RACE callback outcomes.

Add sibling `<Number>` elements to one `<Dial>` when you want Vobiz to attempt several PSTN destinations concurrently. Vobiz bridges the first destination that answers and cancels the remaining B-legs.

## Example

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial
      callerId="+14155550100"
      callerName="Vobiz Transfer"
      timeout="30"
      callbackUrl="https://example.com/dial-events"
      callbackMethod="POST"
      action="https://example.com/dial-result"
      method="POST"
      redirect="false">
    <Number>+14155550101</Number>
    <Number>+14155550102</Number>
  </Dial>
  <Hangup/>
</Response>
```

<Warning>
  Replace `callerId` with a Vobiz number owned or authorized by your account. The receiving carrier and device decide whether to display `callerName`.
</Warning>

## How the race is reported

`DialBLegPosition` follows the child order:

| Child | Position |
| - | -: |
| First `<Number>` | `1` |
| Second `<Number>` | `2` |

The winning destination receives the normal answer, connected, and hangup lifecycle. When another destination loses the race, its `DialHangup` callback reports:

```text theme={null}
Event=DialHangup
DialAction=hangup
DialBLegHangupCause=LOSE_RACE
DialBLegHangupCauseCode=9000
DialBLegHangupCauseName=Lost Race
DialBLegHangupSource=Vobiz
```

Treat `LOSE_RACE` as an expected simultaneous-dial outcome, not as a destination or carrier failure.

## Application handling

* Match callbacks to a destination using `DialBLegUUID`, `DialBLegTo`, and `DialBLegPosition`.
* Do not retry a `LOSE_RACE` leg as an error while another destination is connected.
* Use the final `action` request for the overall Dial result.
* Set `timeout` explicitly to control how long unanswered destinations remain in the race.

## Next steps

* [Review the Dial callback lifecycle](/docs/xml/dial/dial-status-reporting)
* [Configure Number destinations](/docs/xml/dial/number)
* [Review all Dial attributes](/docs/xml/dial)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.