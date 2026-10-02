> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# The Conference Object

> Explore the Vobiz Conference object schema - member arrays, mute/deaf states, runtime, call UUID, and join-time fields for multi-party voice calls worldwide.

The Conference resource represents a multi-party voice call session. Participants can join by calling into a named conference room, and the host can mute, kick, or record participants in real time. Conferences persist until the last participant leaves or the host explicitly ends them.

The Conference object contains information about an ongoing conference including its runtime, participant count, and detailed information about each member currently in the conference.

<Info>
  The Retrieve a Conference endpoint is designed to return this object. The List All Conferences endpoint returns room names rather than full Conference objects.
</Info>

<Warning>
  **Known limitation:** Conference list and retrieve responses may not reflect active rooms. The list endpoint can return an empty array while conferences are active, and retrieval of a live room can return `200 OK` with `{"error":"failed"}`. Use conference callbacks and your own room-state tracking for production workflows.
</Warning>

<Note>
  **Conferences are created on join, not via REST.** There is no "create conference" endpoint. A room comes into existence the moment the first caller enters it through the [`<Conference>` XML element](/docs/xml/conference) (`<Conference>RoomName</Conference>`). The REST Conference endpoints only inspect, control, or record rooms that already have at least one member. Retrieving a name that has no members returns `404`.
</Note>

## Conference Attributes

### Top-Level Attributes

| Field | Type | Required | Description |
| - | - | - | - |
| `conference_name` | string | - | Name used to identify the conference. This is the unique identifier for the conference room. |
| `conference_run_time` | string | - | Time (in seconds) since the conference was initiated. Indicates how long the conference has been active. |
| `conference_member_count` | string | - | Number of members currently active in the conference. Updated in real time as members join or leave. |
| `members` | array | - | Array of member objects, each containing detailed information about an individual participant in the conference. See Member Attributes below. |

## Member Attributes

Each member object in the `members` array contains the following attributes:

### Member Object Attributes

| Field | Type | Required | Description |
| - | - | - | - |
| `member_id` | string | - | ID of the member within the current conference session. Use it for operations such as mute, deaf, or kick. A member ID may be reused after a participant leaves and rejoins. |
| `muted` | boolean | - | true if the member is currently muted (their audio is not transmitted to other participants). false if they can speak freely. |
| `deaf` | boolean | - | true if the member cannot hear conversations in the conference (they are "deafened"). false if they can hear other participants. |
| `from` | string | - | Source of the call - either a PSTN number or SIP endpoint. Indicates where the member is calling from. |
| `to` | string | - | Conference bridge number - either a Vobiz number or an application URL. The destination the member dialed to join. |
| `caller_name` | string | - | Name of the caller (only available if the call was made from a SIP endpoint). Empty string if not specified or not applicable. |
| `direction` | string | - | Direction of the call - either "inbound" (caller dialed into conference) or "outbound" (conference system called the participant). |
| `call_uuid` | string | - | Unique identifier of the call. Can be used to reference this specific call in other API operations. |
| `join_time` | string | - | Time (in seconds) since the member joined the conference. Indicates how long this participant has been in the conference. |

<Tip>
  **Member State Indicators:**

  * `muted: true` - Member cannot be heard by others
  * `deaf: true` - Member cannot hear others
  * `muted: true, deaf: true` - Member is isolated from the conference
</Tip>

## Example Response

Here's an example Conference object with one active member:

```json Conference Object Example theme={null}
{
  "conference_name": "My Conf Room",
  "conference_run_time": "590",
  "conference_member_count": "1",
  "members": [
    {
      "muted": false,
      "member_id": "17",
      "deaf": false,
      "from": "CALLER_NUMBER",
      "to": "VOBIZ_NUMBER",
      "caller_name": "John",
      "direction": "inbound",
      "call_uuid": "CALL_UUID",
      "join_time": "590"
    }
  ]
}
```

<Info>
  **Understanding the Example:**

  * Conference "My Conf Room" has been running for 590 seconds (\~9.8 minutes)
  * Currently has 1 active member (John)
  * John is not muted or deaf - full two-way audio
  * John joined through an inbound call from `CALLER_NUMBER`
  * John has been in the conference for 590 seconds (joined when the conference started)
</Info>

### Multiple Members Example

```json Multiple Members Conference theme={null}
{
  "conference_name": "Team Meeting",
  "conference_run_time": "1200",
  "conference_member_count": "3",
  "members": [
    {
      "muted": false,
      "member_id": "45",
      "deaf": false,
      "from": "CALLER_NUMBER_1",
      "to": "VOBIZ_NUMBER",
      "caller_name": "Alice Johnson",
      "direction": "inbound",
      "call_uuid": "CALL_UUID_1",
      "join_time": "1200"
    },
    {
      "muted": true,
      "member_id": "46",
      "deaf": false,
      "from": "CALLER_NUMBER_2",
      "to": "VOBIZ_NUMBER",
      "caller_name": "",
      "direction": "outbound",
      "call_uuid": "CALL_UUID_2",
      "join_time": "900"
    },
    {
      "muted": false,
      "member_id": "47",
      "deaf": false,
      "from": "CALLER_NUMBER_3",
      "to": "VOBIZ_NUMBER",
      "caller_name": "Bob Smith",
      "direction": "inbound",
      "call_uuid": "CALL_UUID_3",
      "join_time": "300"
    }
  ]
}
```

<Note>
  **Analysis:**

  * **Alice (member 45):** Joined when the conference started, speaking
  * **Unnamed (member 46):** Called outbound 5 minutes after start, currently muted
  * **Bob (member 47):** Joined 15 minutes after start, speaking
</Note>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.