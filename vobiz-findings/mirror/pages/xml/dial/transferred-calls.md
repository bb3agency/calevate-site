> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Transferred calls end to end

> How a transferred Vobiz call behaves across its whole lifecycle - the two call legs it creates, the order its webhooks arrive in, how to correlate the legs, how recording spans the transfer, and how each leg is billed.

A call transferred mid-conversation runs as **two call legs**, not one. Each leg has its own UUID, its own call detail record, and its own charge. This page follows a transferred call from the moment it is answered to the moment its recording lands, so you know which webhook carries which identifier and what each leg costs.

## Call legs and identifiers

| Term | Meaning |
| - | - |
| **A-leg** | The original call. Its UUID is returned as `request_uuid` when the call is placed and appears as `CallUUID` in every webhook for that call. |
| **B-leg** | The leg created by [`<Dial>`](/docs/xml/dial). During a transfer, this is the call to the transfer destination. |
| **Bridge** | The state in which both answered legs are connected and audio flows between them. |
| **Session** | The whole application run on the A-leg, spanning every XML document it executes. Identified by `SessionStart`, which stays constant even when the call is redirected to a new URL. |

The A-leg identifier is the key you use everywhere - it targets the Transfer API, it looks up the CDR, and it owns any recording.

## The transfer is a redirect

Transferring a live call means pointing a leg at a new XML document. See [Transfer a call](/docs/xml/redirect/transfer-a-call) for the request itself.

When the transfer is accepted:

1. The leg stops executing its current XML document. Pending elements in that document are discarded.
2. Vobiz requests the new URL, sending the standard call parameters.
3. The XML returned becomes the leg's new document and starts executing immediately.

The redirect moves the leg to new instructions. Connecting the caller to another party is what `<Dial>` does, so return a `<Dial>` from the transfer URL:

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Speak>Transferring your call now. Please hold.</Speak>
  <Dial
      callerId="+14155550100"
      timeout="30"
      timeLimit="3600"
      action="https://example.com/transfer-complete"
      method="POST"
      callbackUrl="https://example.com/transfer-events"
      callbackMethod="POST">
    <Number>+14155550101</Number>
  </Dial>
  <Speak>The transfer could not be completed.</Speak>
  <Hangup/>
</Response>
```

<Info>
  Elements placed after `<Dial>` run only when no bridge is established, which makes them the natural place for no-answer handling.
</Info>

## Webhook sequence

For a call that is answered, transferred, bridged, and then ended by the original party:

```text theme={null}
1.  answer_url                Event = StartApp
2.  Record action             Event = Record        (if recording is started)
3.  ── transfer requested ──
4.  transfer URL              standard call parameters
5.  Dial callbackUrl          Event = DialAnswer
6.  Dial callbackUrl          Event = DialConnected
7.  Dial callbackUrl          Event = DialHangup
8.  hangup_url                Event = Hangup
9.  Dial action               Event = Redirect
10. Record callbackUrl        Event = RecordStop    (one per recording)
```

Two properties of this order shape how you build against it.

**`hangup_url` reports the A-leg.** It fires once per call. The transferred leg does not produce its own hangup webhook, so an integration listening only on `hangup_url` sees the original leg and not the destination. Configure the Dial `callbackUrl` to observe the B-leg - see [Dial status reporting](/docs/xml/dial/dial-status-reporting).

**Recording completion arrives after hangup.** The file is finalised once the call ends, so `RecordStop` is the point at which the recording URL is ready to fetch.

## Correlating the two legs

Capture `DialBLegUUID` from the real-time Dial `callbackUrl`. `DialAnswer` is the earliest event that carries it, and the real-time channel reports it for every attempt - including destinations that never answered, where the final `action` result may arrive with an empty `DialBLegUUID`.

After the call, the two legs are linked by `bridge_uuid`. Each leg's record carries the **other** leg's identifier:

| Leg | `uuid` | `bridge_uuid` |
| - | - | - |
| A-leg | `cbc3e8af-…` | `a1f7439b-…` |
| B-leg | `a1f7439b-…` | `cbc3e8af-…` |

The relationship is symmetric, so either leg works as a starting point for reconciliation. `bridge_uuid` comes from the CDR detail endpoint - see [CDR](/docs/cdr).

<Note>
  `bridge_uuid` is `null` when no bridge was established. A transfer whose destination never answered produces a B-leg record with no bridge, because the legs were never connected. For those calls, correlate on the `DialALegUUID` and `DialBLegUUID` pair from the Dial callback.
</Note>

## Recording across a transfer

A session recording **survives the transfer**. A recording started when the call is answered continues through the redirect, captures the bridged conversation, and ends when the call ends:

```xml theme={null}
<Record
    fileFormat="mp3"
    recordSession="true"
    redirect="false"
    maxLength="3600"
    callbackUrl="https://example.com/recording-ready"
    callbackMethod="POST"/>
```

A single `<Record>` at answer time therefore captures the whole call, transferred portion included. Adding a second `<Record>` before `<Dial>` produces a second, overlapping file covering only the transferred segment, and is billed as an additional recording. The number of recordings follows the number of `<Record>` elements that execute, not the number of legs.

**Every recording is attributed to the A-leg `CallUUID`**, including one started immediately before `<Dial>`. Look recordings up by the original call's identifier rather than the transferred leg's.

See [Record](/docs/xml/record) for attributes and the completion webhook.

## Billing

Each leg is charged independently, so a transferred call produces two charges. The original leg is billed for its whole life, which includes the bridged period. The transferred leg is billed for its own life only.

Billable time is `billsec`, measured from answer to hangup - ring time is not billed - and rounded up to the next pulse. On a 60-second pulse:

| Answered duration | Pulses | Billed as |
| - | - | - |
| 38 s | 1 | 1 minute |
| 44 s | 1 | 1 minute |
| 68 s | 2 | 2 minutes |
| 122 s | 3 | 3 minutes |
| 219 s | 4 | 4 minutes |

A complete transferred call reconciles like this, with the original leg spanning the whole call and the transferred leg only its own portion:

| Leg | `ring_time` | `billsec` | `duration` | Pulses | `cost` |
| - | - | - | - | - | - |
| Original | 7 s | 219 s | 226 s | 4 | 1.80 |
| Transferred | 21 s | 38 s | 59 s | 1 | 0.45 |

The durations relate as `duration = ring_time + billsec`.

<Info>
  Webhooks carry duration, the CDR carries cost. `BillDuration` and `DialBLegBillDuration` arrive already rounded to the pulse and match the CDR, so they are what you reconcile against in real time. Read `cost` and `total_cost` from the [CDR API](/docs/cdr) for the charge itself.
</Info>

An unanswered leg still produces a CDR, with `billsec` and `cost` at zero and the ring duration recorded in `ring_time`. Unanswered legs are not charged, and they remain visible in reporting.

Recording storage is metered separately, applying the same pulse rounding - a 43-second recording is stored and billed as 60 seconds.

## Next steps

* [Review all Dial attributes](/docs/xml/dial)
* [Handle Dial callbacks](/docs/xml/dial/dial-status-reporting)
* [Transfer a call](/docs/xml/redirect/transfer-a-call)
* [Record a call](/docs/xml/record)
* [Look up call detail records](/docs/cdr)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.