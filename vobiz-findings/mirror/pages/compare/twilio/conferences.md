> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Twilio Conferences → Vobiz Conferences

> Migrate Twilio conference rooms to Vobiz: map conferences.list()/fetch(), participants.create/list/update(muted/hold)/delete, and the <Conference> TwiML verb onto Vobiz conferences, conference member controls, conference_recording, and the <Conference> VobizXML verb - side-by-side Python and Node.

Twilio models a conference as a `Conference` resource (`CF…` SID) with a nested `Participant`
collection keyed by each leg's `CallSid`. Vobiz models the same thing as a **named room**: every
call that runs `<Conference>RoomName</Conference>` joins the room `RoomName`, and you control the
room and its members by that name - so there is no separate SID to track. This page maps every
Twilio conference call onto its Vobiz equivalent, in Python and Node.

<Note>
  Set your credentials once: `AUTH_ID` is your Vobiz Auth ID (`MA_…`), `AUTH_TOKEN` is your Auth
  Token. In the Vobiz SDK, `api_key` **is** the Auth ID, and every account-scoped method takes that
  `auth_id` explicitly. Members are addressed by `conference_name` + `member_id`.
</Note>

## Twilio → Vobiz mapping

| Twilio (twilio-python / TwiML) | Vobiz | Notes |
| - | - | - |
| `client.conferences.list(status='in-progress')` | `client.conferences.list_conferences(auth_id)` | Lists active rooms on the account. |
| `client.conferences(sid).fetch()` | `client.conferences.get_conference(auth_id, conference_name)` | Vobiz returns room details **and** its member list in one call. |
| `client.conferences(sid).update(status='completed')` | `client.conferences.delete_conference(auth_id, conference_name)` | Ends the room and disconnects everyone. |
| *(loop each `CF…` → `update(status='completed')`)* | `client.conferences.delete_all_conferences(auth_id)` | One call ends every active room. |
| `conferences(sid).participants.list()` | `client.conferences.get_conference(auth_id, conference_name)` → `members` | Members come back with the room in `get_conference`. |
| `conferences(sid).participants(call_sid).fetch()` | `client.conferences.get_conference(...)` → pick `member_id` | Find the member in the returned member list. |
| `participants(call_sid).update(muted=True)` | `client.conference_members.mute_member(auth_id, conference_name, member_id)` | Mute a single member. |
| `participants(call_sid).update(muted=False)` | `client.conference_members.unmute_member(auth_id, conference_name, member_id)` | Unmute a single member. |
| `participants(call_sid).update(hold=True, hold_url=…)` | `client.conference.play_audio_member(auth_id, conference_name, member_id, url=…)` | Play hold audio to one member; `stop_audio_member` resumes. |
| `participants(call_sid).update(announce_url=…)` | `client.conference.play_audio_member(auth_id, conference_name, member_id, url=…)` | Play a one-off announcement to a member. |
| *(one-way listen / coach)* | `client.conference.deaf_member` / `undeaf_member(auth_id, conference_name, member_id)` | Stop/restore a member hearing the room; pair with mute for whisper/coach flows. |
| `participants(call_sid).delete()` | `client.conference.kick_member(auth_id, conference_name, member_id)` | Remove a member from the room. |
| *(hang up the participant's leg)* | `client.conference.hangup_member(auth_id, conference_name, member_id)` | Disconnect that member's call entirely. |
| `participants.create(from_, to, …)` | `client.calls.make_call(auth_id, from_, to, answer_url, answer_method)` → answer URL returns `<Conference>` | Originate a leg, then join it to the room from its answer XML. |
| `record='record-from-start'` / `recordingStatusCallback` | `client.conference_recording.start_conference_recording(auth_id, conference_name, file_format, callback_url)` · `stop_conference_recording(...)` - or `record="true"` on `<Conference>` | Start/stop room recording on demand, or record from the first join. |
| `<Dial><Conference>Room</Conference></Dial>` (TwiML) | `<Conference>Room</Conference>` (VobizXML) | Room name is the element text; Vobiz creates the room on first join. |
| `startConferenceOnEnter` / `endConferenceOnExit` | `startConferenceOnEnter` / `endConferenceOnExit` | Same names, same moderator semantics. |
| `muted`, `beep`, `maxParticipants` | `muted`, `beep`, `maxParticipants` | Same attributes; see [Conference attributes](/docs/xml/conference/attributes). |
| `waitUrl` / `waitMethod` | `waitSound` / `waitMethod` | Hold-music URL played until the room starts. |
| `statusCallback` + `statusCallbackEvent` | `callbackUrl` + `callbackMethod` | Vobiz posts `enter` / `exit` / `start` / `end` events. See [Conference callbacks](/docs/xml/conference/conference-callbacks). |

## Join a call to a conference

In Twilio you either dial into a room with `<Dial><Conference>` from an inbound call, or you push a
new leg in with `participants.create`. In Vobiz the room name **is** the join key: return
`<Conference>RoomName</Conference>` from an inbound call's answer URL, and originate outbound legs
with `make_call` pointing at an answer URL that returns the same room.

<CodeGroup>
  ```python Twilio · Python theme={null}
  from twilio.rest import Client
  client = Client(ACCOUNT_SID, AUTH_TOKEN)

  # Push an outbound leg into the conference
  client.conferences("CFxxxxxxxx").participants.create(
      from_="+14155551234",
      to="+14165553434",
      start_conference_on_enter=True,
      end_conference_on_exit=False,
      beep="onEnter",
  )
  ```

  ```python Vobiz · Python theme={null}
  from vobiz import Vobiz
  client = Vobiz(api_key=AUTH_ID, auth_token=AUTH_TOKEN)

  # Originate a leg; its answer URL returns <Conference>SalesRoom</Conference>
  client.calls.make_call(
      auth_id=AUTH_ID,
      from_="+14155551234",
      to="+14165553434",
      answer_url="https://example.com/join-sales-room",
      answer_method="POST",
  )
  ```

  ```javascript Twilio · Node theme={null}
  const client = require('twilio')(ACCOUNT_SID, AUTH_TOKEN);

  await client.conferences('CFxxxxxxxx').participants.create({
    from: '+14155551234',
    to: '+14165553434',
    startConferenceOnEnter: true,
    endConferenceOnExit: false,
    beep: 'onEnter',
  });
  ```

  ```javascript Vobiz · Node theme={null}
  import { VobizClient } from '@vobiz/sdk';
  const client = new VobizClient({ apiKey: AUTH_ID, authToken: AUTH_TOKEN });

  await client.calls.makeCall({
    auth_id: AUTH_ID,
    from: '+14155551234',
    to: '+14165553434',
    answer_url: 'https://example.com/join-sales-room',
    answer_method: 'POST',
  });
  ```
</CodeGroup>

The answer URL returns the room in XML. TwiML nests `<Conference>` inside `<Dial>`; VobizXML uses
`<Conference>` directly, with the room name as the element text.

<CodeGroup>
  ```python Twilio · TwiML (Python) theme={null}
  from twilio.twiml.voice_response import VoiceResponse, Dial

  resp = VoiceResponse()
  dial = Dial()
  dial.conference(
      "SalesRoom",
      start_conference_on_enter=True,
      end_conference_on_exit=False,
      beep="onEnter",
      wait_url="https://example.com/hold-music",
      status_callback="https://example.com/conf-events",
      status_callback_event="start end join leave",
  )
  resp.append(dial)
  print(str(resp))
  ```

  ```python Vobiz · VobizXML (Python) theme={null}
  from vobiz import vobizxml

  resp = vobizxml.ResponseElement()
  resp.add_conference(
      "SalesRoom",
      start_conference_on_enter=True,
      end_conference_on_exit=False,
      beep=True,
      wait_sound="https://example.com/hold-music",
      callback_url="https://example.com/conf-events",
      callback_method="POST",
  )
  print(resp.to_string())
  ```

  ```javascript Vobiz · VobizXML (Node) theme={null}
  import { vobizxml } from '@vobiz/sdk';

  const resp = new vobizxml.ResponseElement();
  resp.addConference('SalesRoom', {
    startConferenceOnEnter: true,
    endConferenceOnExit: false,
    beep: true,
    waitSound: 'https://example.com/hold-music',
    callbackUrl: 'https://example.com/conf-events',
    callbackMethod: 'POST',
  });
  console.log(resp.toString());
  ```
</CodeGroup>

## Control members: mute, hold, kick

Twilio addresses a participant by its leg `CallSid` and mutates it with `participants(sid).update(...)`.
Vobiz gives each control its own verb, addressed by `conference_name` + `member_id` - you get the
member IDs from `get_conference`.

<CodeGroup>
  ```python Twilio · Python theme={null}
  conf = client.conferences("CFxxxxxxxx")

  # Who is in the room?
  for p in conf.participants.list():
      print(p.call_sid, "muted:", p.muted, "hold:", p.hold)

  # Mute one participant
  conf.participants("CAaaaa").update(muted=True)
  # Put one participant on hold with hold music
  conf.participants("CAaaaa").update(hold=True, hold_url="https://example.com/hold-music")
  # Remove one participant
  conf.participants("CAaaaa").delete()
  ```

  ```python Vobiz · Python theme={null}
  # Who is in the room? get_conference returns members + room details
  room = client.conferences.get_conference(AUTH_ID, conference_name="SalesRoom")
  for m in room["members"]:
      print(m["member_id"], "muted:", m["muted"])

  # Mute / unmute one member
  client.conference_members.mute_member(AUTH_ID, conference_name="SalesRoom", member_id="MEMBER_1")
  client.conference_members.unmute_member(AUTH_ID, conference_name="SalesRoom", member_id="MEMBER_1")

  # Hold = play audio to just that member; stop_audio_member returns them to the room
  client.conference.play_audio_member(AUTH_ID, conference_name="SalesRoom",
                                      member_id="MEMBER_1", url="https://example.com/hold-music")
  client.conference.stop_audio_member(AUTH_ID, conference_name="SalesRoom", member_id="MEMBER_1")

  # Remove a member (kick) or fully disconnect their leg (hangup)
  client.conference.kick_member(AUTH_ID, conference_name="SalesRoom", member_id="MEMBER_1")
  client.conference.hangup_member(AUTH_ID, conference_name="SalesRoom", member_id="MEMBER_1")
  ```

  ```javascript Twilio · Node theme={null}
  const conf = client.conferences('CFxxxxxxxx');

  const participants = await conf.participants.list();
  participants.forEach((p) => console.log(p.callSid, p.muted, p.hold));

  await conf.participants('CAaaaa').update({ muted: true });
  await conf.participants('CAaaaa').update({ hold: true, holdUrl: 'https://example.com/hold-music' });
  await conf.participants('CAaaaa').remove();
  ```

  ```javascript Vobiz · Node theme={null}
  const room = await client.conferences.getConference(AUTH_ID, { conferenceName: 'SalesRoom' });
  room.members.forEach((m) => console.log(m.memberId, m.muted));

  await client.conferenceMembers.muteMember(AUTH_ID, { conferenceName: 'SalesRoom', memberId: 'MEMBER_1' });
  await client.conferenceMembers.unmuteMember(AUTH_ID, { conferenceName: 'SalesRoom', memberId: 'MEMBER_1' });

  await client.conference.playAudioMember(AUTH_ID, { conferenceName: 'SalesRoom', memberId: 'MEMBER_1', url: 'https://example.com/hold-music' });
  await client.conference.stopAudioMember(AUTH_ID, { conferenceName: 'SalesRoom', memberId: 'MEMBER_1' });

  await client.conference.kickMember(AUTH_ID, { conferenceName: 'SalesRoom', memberId: 'MEMBER_1' });
  await client.conference.hangupMember(AUTH_ID, { conferenceName: 'SalesRoom', memberId: 'MEMBER_1' });
  ```
</CodeGroup>

<Tip>
  For a whisper/coach flow, pair `deaf_member`/`undeaf_member` (control who a member hears) with
  `mute_member`/`unmute_member` (control who hears them) - the same effect Twilio's `coaching` +
  `muted` combination produces, expressed as two explicit, composable verbs.
</Tip>

## List, inspect, and end rooms

<CodeGroup>
  ```python Twilio · Python theme={null}
  # List active conferences
  for c in client.conferences.list(status="in-progress"):
      print(c.sid, c.friendly_name, c.status)

  # Fetch one
  conf = client.conferences("CFxxxxxxxx").fetch()

  # End a conference (no delete - you update status)
  client.conferences("CFxxxxxxxx").update(status="completed")
  ```

  ```python Vobiz · Python theme={null}
  # List active rooms
  rooms = client.conferences.list_conferences(AUTH_ID)

  # Inspect one room (details + members)
  room = client.conferences.get_conference(AUTH_ID, conference_name="SalesRoom")

  # End one room, or all rooms at once
  client.conferences.delete_conference(AUTH_ID, conference_name="SalesRoom")
  client.conferences.delete_all_conferences(AUTH_ID)
  ```
</CodeGroup>

## Record a conference

Twilio records via the `record` attribute (`record-from-start`) plus `recordingStatusCallback`.
Vobiz records the whole room either declaratively (`record="true"` on `<Conference>`) or imperatively,
starting and stopping on demand by room name.

<CodeGroup>
  ```python Twilio · Python theme={null}
  # Recording is set when the conference is created via TwiML:
  #   <Conference record="record-from-start"
  #               recordingStatusCallback="https://example.com/rec">Room</Conference>
  ```

  ```python Vobiz · Python theme={null}
  # Start / stop recording an active room on demand
  client.conference_recording.start_conference_recording(
      AUTH_ID,
      conference_name="SalesRoom",
      file_format="mp3",
      callback_url="https://example.com/rec",
  )
  client.conference_recording.stop_conference_recording(AUTH_ID, conference_name="SalesRoom")
  ```
</CodeGroup>

The recording URL is delivered to your `callbackUrl` on the conference `end` event (and to
`callback_url` on the recording API) - see [Conference callbacks](/docs/xml/conference/conference-callbacks).

## Key differences

* **Room name, not SID.** Twilio tracks a `Conference` by its `CF…` SID and each participant by leg
  `CallSid`. Vobiz uses the human-readable room name plus a `member_id` for every operation, so you
  never fetch a SID before acting - the name you put in `<Conference>` is the same name you pass to
  every control method.
* **One call returns the whole room.** `get_conference` returns the room's details **and** its member
  list together, where Twilio's `fetch()` and `participants.list()` are separate requests.
* **Ending rooms is explicit.** Vobiz gives you `delete_conference` for one room and
  `delete_all_conferences` for every active room, versus Twilio's `update(status='completed')` per SID.
* **One verb per control.** Mute, hold, deaf, announce, kick, and hangup are each their own method
  (`mute_member`, `play_audio_member`, `deaf_member`, `kick_member`, `hangup_member`), so intent is
  explicit and composable rather than a bundle of flags on one `participant.update()`.
* **Hold is "play to one member."** `play_audio_member` streams hold music to a single participant and
  `stop_audio_member` returns them to the room - the same outcome as Twilio's `hold`/`hold_url`,
  expressed as an audio action you fully control.
* **On-demand recording.** `start_conference_recording`/`stop_conference_recording` let you record any
  portion of an active room by name, in addition to the declarative `record="true"` attribute.
* **Same TwiML-shaped XML.** VobizXML keeps `startConferenceOnEnter`, `endConferenceOnExit`, `muted`,
  `beep`, and `maxParticipants` under the same names - most `<Conference>` blocks port with only a
  `waitUrl`→`waitSound` and `statusCallback`→`callbackUrl` rename.

## See also

* [Conference XML element](/docs/xml/conference/attributes) - every attribute of the Vobiz `<Conference>` verb.
* [Conference callbacks](/docs/xml/conference/conference-callbacks) - `enter` / `exit` / `start` / `end` webhooks.
* [Gather](/docs/xml/gather) - collect DTMF before or after joining a room.
* [Twilio → Vobiz overview](/docs/compare/twilio/overview) - the full migration map and order.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.