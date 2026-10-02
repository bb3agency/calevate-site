> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Conference Attributes

> Full reference for every attribute on the Vobiz Conference XML element - control muting, beeps, participant limits, hold music, and recording.

<Info>
  **Room name**

  The text content of the `<Conference>` element is the room name. All callers placed into the same room name are bridged together. Room names are case-sensitive.
</Info>

## Attributes

| Attribute | Description |
| - | - |
| `muted` <br /> *boolean* | If `true`, the participant joins the conference muted and cannot be heard by others until unmuted. <br />**Default:** `false` |
| `beep` <br /> *boolean* | Configures join and leave tones. Vobiz accepts this value, but audible tones are not currently guaranteed. <br />**Default:** `true` |
| `startConferenceOnEnter` <br /> *boolean* | If `true`, the conference starts and hold music stops when this participant enters. Set to `false` for participants who should wait in hold until the moderator arrives. <br />**Default:** `true` |
| `endConferenceOnExit` <br /> *boolean* | If `true`, this participant's exit issues an unconditional **kick of every remaining member**. It does **not** inspect `stayAlone` on the other members - see the warning below. <br />**Default:** `false` |
| `maxParticipants` <br /> *integer* | Requests a participant limit for the room. Parsed, but **not effective** - the account-level `max_conf_members` cap wins (commonly `20`). Contact support to raise the account cap, and enforce lower limits in your application. <br />**Allowed values:** positive integer |
| `stayAlone` <br /> *boolean* | If `false`, a participant who is alone in the room is disconnected. **Initialises to `false`, so set `stayAlone="true"` on any leg that may arrive before the others** - every transfer, and every conference where the host joins first. <br />**Default:** `false` |
| `enterSound` <br /> *string* | Sound played into the room when this participant enters. |
| `exitSound` <br /> *string* | Sound played into the room when this participant exits. |
| `relayDTMF` <br /> *boolean* | If `true`, DTMF pressed by this participant is relayed into the conference. <br />**Default:** `false` |
| `digitsMatch` <br /> *string* | Comma-separated digit patterns that raise a `ConferenceDigitsMatch` callback when matched. |
| `hangupOnStar` <br /> *boolean* | If `true`, this participant pressing `*` removes them from the conference. <br />**Default:** `false` |
| `waitSound` <br /> *string* | URL that returns XML for a waiting participant while `startConferenceOnEnter` is `false`. Vobiz requests this URL with `POST`; `<Speak>` and `<Wait>` are supported in the response. <br />**Allowed values:** a fully qualified URL |
| `waitMethod` <br /> *string* | **Not implemented.** The attribute is accepted but no component reads it; the `waitSound` fetch method is fixed. Do not rely on it. |
| `callbackUrl` <br /> *string* | URL notified when a participant enters or exits. Separate conference start and end callbacks are not currently available. See [Conference Callbacks](/docs/xml/conference/conference-callbacks) for event-specific parameters. <br />**Allowed values:** a fully qualified URL |
| `callbackMethod` <br /> *string* | HTTP method used to notify `callbackUrl`. <br />**Allowed values:** `GET`, `POST` <br />**Default:** `POST` |
| `record` <br /> *boolean* | **Does not currently produce a recording file.** Use per-leg `<Record recordSession="true">` instead - see the warning below. <br />**Default:** `false` |
| `recordFileFormat` <br /> *string* | Audio format for XML-triggered conference recording. <br />**Allowed values:** `mp3`, `wav` <br />**Default:** `mp3` |
| `timeLimit` <br /> *integer* | Maximum conference duration in seconds. When the limit expires, Vobiz ends the conference and disconnects its members. <br />**Allowed values:** positive integer <br />**Default:** `14400` (4 hours) |
| `action` <br /> *string* | Fully qualified URL requested when this call leg exits the conference. **Not reliably invoked** - see the warning below. Use `callbackUrl` for conference events instead. |
| `method` <br /> *string* | HTTP method used to request `action`. Use `POST` for the documented action flow. <br />**Default:** `POST` |

<Warning>
  **`endConferenceOnExit` removes everyone, and `stayAlone` is no defence.**

  When a participant with `endConferenceOnExit="true"` exits, the platform kicks
  every remaining member unconditionally. It does not check `stayAlone` on those
  members.

  `stayAlone` governs only the *becoming-alone* case - "if `false` and this member
  is now alone, disconnect them". It has no interaction with another member's exit.
  The two attribute names imply a negotiation between them; there is none.

  Legs removed this way also get no hangup attribution, so they report as
  `NORMAL_CLEARING` / `4000` / `Callee` - a platform teardown that looks like the
  participant hanging up. See [Hangup causes](/docs/concepts/hangup-causes).
</Warning>

<Warning>
  **Conference recording and `action` are both unreliable on this element.**

  `record="true"` does not write a recording file, and neither does
  `POST /Conference/{room}/Record/` - that route answers `200`
  `{"message":"async api spawned"}` without a `recording_id` or `url`, so a failure
  is indistinguishable from success.

  The `action` URL is fetched only for conferences hosted on a remote media server.
  Where a conference is hosted is not visible to your application, so `action` is
  unpredictable from outside.

  **Use instead:** per-leg session recording, placed as a self-closing sibling
  *before* `<Conference>`, plus `callbackUrl` for conference events.

  ```xml theme={null}
  <Record fileFormat="mp3" recordSession="true" redirect="false"
          playBeep="false" maxLength="3600"
          action="https://example.com/record-action"
          callbackUrl="https://example.com/record-callback" callbackMethod="POST"/>
  ```

  `recordSession="true"` captures the whole leg, including anything bridged into it,
  and survives a transfer. Output is stereo MP3 at 8 kHz, one party per channel.
  With `redirect="false"` the `action` URL must return an empty `<Response></Response>`.
</Warning>

## Conference action callback

The `action` request is separate from the participant events sent to `callbackUrl`. Vobiz invokes `action` after the call leg exits `<Conference>`, then executes the Vobiz XML returned by your endpoint.

The request includes call, conference, and member identifiers. When `record="true"`, it can also include:

| Parameter | Description |
| - | - |
| `RecordingID` | Identifier for the completed conference recording |
| `RecordUrl` | URL associated with the recording |
| `RecordFile` | Recording file name or path |

Return valid Vobiz XML from the action endpoint when the call should continue:

```xml Action response theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>The conference has ended.</Speak>
</Response>
```

## Examples

### Basic conference room

```xml Minimal conference - all defaults theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Conference>SalesTeamRoom</Conference>
</Response>
```

### Moderator-controlled conference

The moderator (`endConferenceOnExit="true"`) holds all participants in music until they arrive, then ends the call for everyone when they leave.

```xml Moderator joins last; ends conference on exit theme={null}
<?xml version="1.0" encoding="UTF-8"?>

<!-- Participant XML (plays hold music until moderator arrives) -->
<Response>
    <Speak>Please hold while we connect you to the conference.</Speak>
    <Conference
        startConferenceOnEnter="false"
        waitSound="https://yourapp.com/hold-music">
        WeeklyStandup
    </Conference>
</Response>

<!-- Moderator XML (starts the conference; ends it when they leave) -->
<Response>
    <Conference
        startConferenceOnEnter="true"
        endConferenceOnExit="true"
        beep="true">
        WeeklyStandup
    </Conference>
</Response>
```

### Recorded conference with participant limit

<Warning>
  The account-level room limit remains authoritative. Enforce any lower participant limit in your application.
</Warning>

```xml Record the session and cap at 10 participants theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Conference
        maxParticipants="10"
        record="true"
        recordFileFormat="wav"
        action="https://yourapp.example/conference-complete"
        method="POST"
        callbackUrl="https://yourapp.example/conference-events"
        callbackMethod="POST">
        BoardMeeting
    </Conference>
</Response>
```

### Muted listener (broadcast mode)

```xml Caller joins as a silent listener theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>You are now listening to the all-hands broadcast.</Speak>
    <Conference
        muted="true"
        startConferenceOnEnter="false">
        AllHandsBroadcast
    </Conference>
</Response>
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.