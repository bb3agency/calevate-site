> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Conference callbacks

> Handle participant enter and exit callbacks and wait-audio requests from Vobiz conferences.

<Info>
  **Prerequisites**

  Set `callbackUrl` and, optionally, `callbackMethod` on the `<Conference>` element. Vobiz sends form-encoded requests to this URL when participants enter or exit.
</Info>

## Events

Vobiz sends the following participant callbacks:

| `ConferenceAction` value | When it fires |
| - | - |
| `enter` | A participant joins the conference room |
| `exit` | A participant leaves the conference room |

<Note>
  Separate `start` and `end` callbacks are not currently available. Use `ConferenceFirstMember` on `enter` and `ConferenceLastMember` on `exit` to track the room lifecycle.
</Note>

## Parameters sent to callbackUrl

Callback fields vary by event. Validate `ConferenceAction` before reading event-specific values.

| Parameter | Description |
| - | - |
| `ConferenceAction` | Event that triggered the callback. **Values:** `enter`, `exit` |
| `Event` | `ConferenceEnter` or `ConferenceExit` |
| `ConferenceUUID` | Unique identifier for the conference session |
| `ConferenceName` | The room name set in the `<Conference>` element |
| `ConferenceMemberID` | Member ID for the participant. Use this value with conference member APIs. |
| `ConferenceFirstMember` | Included on `enter`. `true` when this is the first participant. |
| `ConferenceLastMember` | Included on `exit`. Means **"the room was empty at the instant this exit event fired"** - not "this was the last participant to leave". Do not infer ordering from it. |
| `CallUUID` | Unique identifier for the call leg |
| `From`, `To`, `Direction`, `CallStatus` | Included on `enter`; not included on `exit` |

`ConferenceCurrentSize`, `Timestamp`, and `RecordingUrl` are not included in these callbacks.

<Warning>
  **Callback delivery order is not event order.** Conference callbacks are dispatched
  asynchronously, so two exits can arrive reversed relative to when they happened.
  Reading arrival order as event order will invert your sequence.

  Correlate on `CallUUID` and `ConferenceMemberID` only, and if you need true
  ordering, timestamp the events in your own handler on receipt.
</Warning>

## Examples

### Handling callbacks in Node.js

```javascript Express handler for conference events theme={null}
const express = require('express');
const app = express();
app.use(express.urlencoded({ extended: true }));

app.post('/conference-events', (req, res) => {
  const {
    ConferenceAction,
    ConferenceName,
    ConferenceMemberID,
    ConferenceFirstMember,
    ConferenceLastMember,
    CallUUID,
    From
  } = req.body;

  switch (ConferenceAction) {
    case 'enter':
      console.log(`${From} joined ${ConferenceName} as member ${ConferenceMemberID}`);
      if (ConferenceFirstMember === 'true') {
        console.log(`${ConferenceName} now has its first member`);
      }
      break;

    case 'exit':
      console.log(`Member ${ConferenceMemberID} left ${ConferenceName}`);
      if (ConferenceLastMember === 'true') {
        console.log(`${ConferenceName} is now empty`);
      }
      break;

    default:
      console.log(`Unknown conference event: ${ConferenceAction}`);
  }

  res.status(200).send('OK');
});
```

### Handling callbacks in Python

```python Flask handler for conference events theme={null}
from flask import Flask, request

app = Flask(__name__)

@app.route('/conference-events', methods=['POST'])
def conference_events():
    action = request.form.get('ConferenceAction')
    conference_name = request.form.get('ConferenceName')
    member_id = request.form.get('ConferenceMemberID')
    caller = request.form.get('From')
    first_member = request.form.get('ConferenceFirstMember')
    last_member = request.form.get('ConferenceLastMember')

    if action == 'enter':
        print(f"{caller} joined {conference_name} as member {member_id}")
        if first_member == 'true':
            print(f"{conference_name} now has its first member")

    elif action == 'exit':
        print(f"Member {member_id} left {conference_name}")
        if last_member == 'true':
            print(f"{conference_name} is now empty")

    return 'OK', 200
```

## Example callback payload

```http Enter event theme={null}
POST /conference-events HTTP/1.1
Host: yourapp.com
Content-Type: application/x-www-form-urlencoded

ConferenceAction=enter
Event=ConferenceEnter
ConferenceUUID=CONFERENCE_UUID
ConferenceName=WeeklyStandup
ConferenceMemberID=2
ConferenceFirstMember=true
CallUUID=CALL_UUID
From=CALLER_NUMBER
To=VOBIZ_NUMBER
Direction=inbound
CallStatus=in-progress
```

```http Exit event theme={null}
POST /conference-events HTTP/1.1
Host: yourapp.com
Content-Type: application/x-www-form-urlencoded

ConferenceAction=exit
Event=ConferenceExit
ConferenceUUID=CONFERENCE_UUID
ConferenceName=WeeklyStandup
ConferenceMemberID=2
ConferenceLastMember=true
CallUUID=CALL_UUID
```

## Wait-audio request

When a participant waits for a moderator, Vobiz requests the `waitSound` URL with `ConferenceAction=waitSound` and `Event=ConferenceRemoteSounds`. The request includes `ConferenceName`, `CallUUID`, `From`, `To`, `Direction`, and `CallStatus`. It does not include usable conference or member IDs.

```http Wait-audio request theme={null}
ConferenceAction=waitSound
Event=ConferenceRemoteSounds
ConferenceName=WeeklyStandup
CallUUID=CALL_UUID
From=CALLER_NUMBER
To=VOBIZ_NUMBER
Direction=inbound
CallStatus=in-progress
```

Return Vobiz XML with the audio instructions for the waiting participant:

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Speak>Please wait for the moderator.</Speak>
  <Wait length="5" />
</Response>
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.