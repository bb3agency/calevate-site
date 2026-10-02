> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Plivo Conferences to Vobiz: XML + API Migration Guide

> Map Plivo's Conference XML element and Conference/Member REST APIs to Vobiz. Side-by-side attribute and endpoint mapping, before/after code for join, mute, kick, play, and record.

Plivo and Vobiz model conferences the same way: callers join a **named room** through a `<Conference>` XML element, and you control participants out-of-band through a REST API (mute, kick, play, record). The XML verb and most attributes line up one-to-one - the main differences are **header auth** and the **SDK resource split** (`conference`, `conference_members`, `conference_recording`).

## Plivo → Vobiz mapping

### XML element & attributes

| Plivo `<Conference>` | Vobiz `<Conference>` | Notes |
| - | - | - |
| `<Conference>RoomName</Conference>` | `<Conference>RoomName</Conference>` | Identical. Room name is the element text, case-sensitive. Vobiz auto-creates the room. |
| `muted` | `muted` | Same boolean. Join muted. |
| `startConferenceOnEnter` | `startConferenceOnEnter` | Same. Default `true` on both. |
| `endConferenceOnExit` | `endConferenceOnExit` | Same. Moderator-leaves-ends-call pattern. |
| `maxMembers` | `maxParticipants` | **Renamed.** Vobiz default `200`. |
| `waitSound` | `waitSound` (+ `waitMethod`) | Hold audio while waiting to start. |
| `enterSound` / `exitSound` (`beep:1`, `beep:2`, URL) | `beep` *(boolean)* | Vobiz uses a single on/off `beep` boolean. |
| `record` + `recordFileFormat` | `record` *(boolean)* | Vobiz `record` is a boolean; use the Record API to choose `mp3`/`wav` format. |
| `timeLimit` | `timeLimit` | Max conference duration in seconds. |
| `callbackUrl` / `callbackMethod` | `callbackUrl` / `callbackMethod` | Lifecycle events. See [Conference Callbacks](/docs/xml/conference/conference-callbacks). |

### REST API (room + member operations)

Vobiz base URL: `https://api.vobiz.ai/api/v1`. Auth via `X-Auth-ID` + `X-Auth-Token` **request headers** (Plivo uses HTTP Basic with the same Auth ID/Token).

| Plivo (path / Python method) | Vobiz path | Vobiz Python SDK |
| - | - | - |
| `GET /Conference/` · `conferences.list` | `GET /Account/{auth_id}/Conference/` | `client.conferences.list_conferences(auth_id)` |
| `GET /Conference/{name}/` · `conferences.get` | `GET /Account/{auth_id}/Conference/{conference_name}/` | `client.conferences.get_conference(auth_id, conference_name)` |
| `DELETE /Conference/{name}/` · `conferences.hangup` | `DELETE /Account/{auth_id}/Conference/{conference_name}/` | `client.conferences.delete_conference(auth_id, conference_name)` |
| `DELETE /Conference/` · `conferences.hangup_all` | `DELETE /Account/{auth_id}/Conference/` | `client.conferences.delete_all_conferences(auth_id)` |
| `POST .../Member/{id}/Mute/` · `conferences.member_mute` | `POST .../Member/{member_id}/Mute/` | `client.conference_members.mute_member(auth_id, conference_name, member_id)` |
| `DELETE .../Member/{id}/Mute/` · `conferences.member_mute_stop` | `DELETE .../Member/{member_id}/Mute/` | `client.conference_members.unmute_member(auth_id, conference_name, member_id)` |
| `POST .../Member/{id}/Kick/` · `conferences.member_kick` | `POST .../Member/{member_id}/Kick/` | `client.conference.kick_member(auth_id, conference_name, member_id)` |
| `DELETE .../Member/{id}/` · `conferences.member_hangup` | `DELETE .../Member/{member_id}/` | `client.conference.hangup_member(auth_id, conference_name, member_id)` |
| `POST .../Member/{id}/Deaf/` · `conferences.member_deaf` | `POST .../Member/{member_id}/Deaf/` | `client.conference.deaf_member(auth_id, conference_name, member_id)` |
| `DELETE .../Member/{id}/Deaf/` · `conferences.member_deaf_stop` | `DELETE .../Member/{member_id}/Deaf/` | `client.conference.undeaf_member(auth_id, conference_name, member_id)` |
| `POST .../Member/{id}/Play/` · `conferences.member_play` | `POST .../Member/{member_id}/Play/` | `client.conference.play_audio_member(auth_id, conference_name, member_id, url=...)` |
| `DELETE .../Member/{id}/Play/` · `conferences.member_play_stop` | `DELETE .../Member/{member_id}/Play/` | `client.conference.stop_audio_member(auth_id, conference_name, member_id)` |
| `POST /Conference/{name}/Record/` · `conferences.record` | `POST .../Conference/{conference_name}/Record/` | `client.conference_recording.start_conference_recording(auth_id, conference_name, file_format="mp3")` |
| `DELETE /Conference/{name}/Record/` · `conferences.record_stop` | `DELETE .../Conference/{conference_name}/Record/` | `client.conference_recording.stop_conference_recording(auth_id, conference_name)` |

## Before / after: join a moderated conference (XML)

**Plivo** - `plivoxml` builder:

```python theme={null}
from plivo import plivoxml

resp = plivoxml.ResponseElement()
resp.add(
    plivoxml.ConferenceElement(
        "WeeklyStandup",
        start_conference_on_enter=False,   # participants wait
        max_members=10,
        wait_sound="https://yourapp.com/hold-music",
        callback_url="https://yourapp.com/conf-events",
    )
)
print(resp.to_string())
```

**Vobiz** - `vobizxml` builder (bundled in every Vobiz SDK):

```python theme={null}
from vobizxml import ResponseElement

r = ResponseElement()
r.add_conference(
    "WeeklyStandup",
    start_conference_on_enter=False,       # participants wait
    max_participants=10,                   # was max_members
    wait_sound="https://yourapp.com/hold-music",
    callback_url="https://yourapp.com/conf-events",
)
print(r.to_string())
```

Both emit the same XML shape:

```xml theme={null}
<Response>
  <Conference startConferenceOnEnter="false" maxParticipants="10"
              waitSound="https://yourapp.com/hold-music"
              callbackUrl="https://yourapp.com/conf-events">WeeklyStandup</Conference>
</Response>
```

## Key differences & gotchas

* **Auth.** Plivo uses HTTP Basic; Vobiz uses `X-Auth-ID` / `X-Auth-Token` request headers (the SDK sets these, but raw `curl`/HTTP clients must switch).
* **Member ops are split across SDK resources.** `client.conference` (kick / hangup / play / deaf), `client.conference_members` (mute / unmute), `client.conferences` (room list / get / delete), `client.conference_recording` (start / stop) - but the REST paths stay under one `/Conference/...` tree.
* **Rename `maxMembers` → `maxParticipants`**, and note `enterSound`/`exitSound` map to a single `beep` boolean; recording format moves from XML to `start_conference_recording(file_format=...)`.
* **Callback params differ in name.** Vobiz posts `ConferenceAction` (`enter`/`exit`/`start`/`end`), `ConferenceUUID`, `ConferenceName`, `CallUUID`, `ConferenceCurrentSize`, and `RecordingUrl`. See [Conference Callbacks](/docs/xml/conference/conference-callbacks).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.