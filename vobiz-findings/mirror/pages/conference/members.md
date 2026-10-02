> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Conference Members

> Control individual Vobiz conference members - mute, deaf, kick, hang up, and play audio or text to a single participant without affecting others.

This resource lets you perform actions on members of a conference. You can control audio states (mute/deaf), remove participants (kick/hang up), and play audio or text to specific members.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account ID (e.g., `{auth_id}`)
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

## Member Targeting

Most member operations support flexible targeting allowing you to act on individual members, multiple members, or all members at once:

### Single Member - `member_id`

Target a specific member by their member\_id (e.g., "17"). Only that member is affected.

```
/Member/17/Mute/
```

### Multiple Members - comma-separated list

Target multiple specific members by providing a comma-separated list of member IDs.

```
/Member/17,45,82/Mute/
```

### All Members - `"all"`

Use the string "all" to target every member in the conference simultaneously.

```
/Member/all/Mute/
```

<Warning>
  **Member IDs are available only from the conference callbacks.** Every operation on
  this page needs a `ConferenceMemberID`, and the only place one appears is the
  `ConferenceEnter` / `ConferenceExit` callback delivered to your `callbackUrl`.

  The read endpoints do not currently return live member details:
  `GET /Conference/` answers `200 {"conferences": []}` while rooms are live, and
  `GET /Conference/{name}/` answers `200 {"error":"failed"}` with members present.

  Capture and store `ConferenceMemberID` on enter. Member IDs are scoped to a
  conference session and may be reused after a participant leaves and rejoins.
</Warning>

## Status codes and response shape

These operations do not return `200`. The actual codes:

| Operation | Status | Body |
| - | - | - |
| Mute · Deaf · Play · Speak · Kick | `202` | `{"message":"muted","member_id":["101"]}` |
| Unmute · Undeaf · Stop play | `204` | *empty* |
| Hang up member · Hang up room | `204` | *empty* |

Two things to code against:

* **`member_id` is always an array**, even for a single member. Targeting `all`
  echoes back the literal string `all` rather than expanding to the member list.
* **Repeating an applied control is not an error.** Muting an already-muted member
  answers `202` again, so a 2xx does not prove a state change occurred.

<Warning>
  **There is no room-wide Play or Speak.** `POST /Conference/{room}/Play/` and
  `POST /Conference/{room}/Speak/` do not exist - only the per-member routes below.
  To address a whole room, pass `all` as the `member_id` or fan out per member.

  The error shape distinguishes the two cases: a missing route returns
  `{"message":"Not Found"}` from the gateway, while a live route with a bad room
  returns `{"error":"conference not found"}`.
</Warning>

## Control Operations

| Method | Operation | Description |
| - | - | - |
| DELETE | [Hang Up a Member](/docs/conference/members/hang-up-member) | Ends a normal active member's call. After a Kick/rejoin sequence that reuses the same member ID, confirm removal through callbacks. |
| POST | [Kick a Member](/docs/conference/members/kick-member) | Disconnect a member but allow XML flow continuation. Member can hear next XML elements after disconnection. |
| POST | [Mute a Member](/docs/conference/members/mute-member) | Mute a member's audio so other participants cannot hear them. Member can still hear the conference. |
| DELETE | [Unmute a Member](/docs/conference/members/unmute-member) | Unmute a previously muted member allowing them to be heard by other participants again. |
| POST | [Deaf a Member](/docs/conference/members/deaf-member) | Prevent a member from hearing conference audio. They can still speak but won't hear others. |
| DELETE | [Undeaf a Member](/docs/conference/members/undeaf-member) | Restore hearing for a deafened member allowing them to hear conference audio again. |

## Audio & Text Operations

| Method | Operation | Description |
| - | - | - |
| POST | [Play Audio to a Member](/docs/conference/members/play-audio) | Play audio files to specific conference members. Useful for announcements or hold music. |
| DELETE | [Stop Audio to a Member](/docs/conference/members/stop-audio) | Stop ongoing audio playback for specific members. |

<Note>
  Audio injected onto a member's own call leg by a bidirectional [`<Stream>`](/docs/xml/stream)
  `playAudio` event never passes through the conference mixer, so `deaf` cannot
  suppress it. See [Play Audio](/docs/xml/stream/play-audio).
</Note>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.