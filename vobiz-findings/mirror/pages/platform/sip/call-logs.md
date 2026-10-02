> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# SIP Call Logs - Per-Call Records & Quality

> Browse every SIP trunk call in the Vobiz Console - MOS scores, call timeline, hangup cause, transcription, recording playback, and CSV export. Filter by direction, caller/callee number, duration, and hangup cause.

The **SIP Call Logs** page is the per‑call audit trail for SIP trunk traffic - both inbound and outbound - with MOS scores, full SIP timeline, hangup cause, transcription button, and inline recording playback.

```text URL theme={null}
https://console.vobiz.ai/app/sip/logs
```

<Frame caption="SIP Trunk - Call Logs">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/sip/sip-call-logs_blur.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=7e4587339ada3e0b9506dd208b2ec4b0" alt="SIP Call Logs page with KPI tiles (SIP Trunk Spend ₹11, Total Calls 15, Answered 10, Answer Rate 66.7%, Avg Duration 31s), paginated call list with MOS scores and AI badges, and a Call Details panel showing Call Timeline (Initiated, Ring Start, Answered, Ended), From and To with country flags, Direction, Type (SIP), Call ID, Call Duration, Total Cost, plus Play Recording and Transcription buttons in the top right of the details panel" style={{maxWidth: '900px', margin: '0 auto', display: 'block'}} width="8000" height="4408" data-path="images/platform/sip/sip-call-logs_blur.png" />
</Frame>

The layout, filters, and call details panel are **identical** to [Voice Call Logs](/docs/platform/voice/call-logs) - same KPI tiles, same call list, same 4‑tab details. The differences:

| Element | SIP Call Logs | Voice Call Logs |
| - | - | - |
| **Scope** | SIP trunk traffic only (inbound + outbound). | Voice API + XML applications. |
| **KPI tiles** | SIP Trunk Spend, Total Calls, Answered, Answer Rate, Avg. Duration. | Voice API Spend, Total Calls, Answered, Answer Rate, Avg. Duration. |
| **Type column** | Shows `SIP` for every row. | Shows `Voice Application`, `API`, or `SIP`. |
| **Recording button** | **Play Recording** (top‑right of details) when the trunk has [Call Recording](/docs/platform/sip/outbound-trunks#recording--transcription-toggles) enabled. | Same button when an XML app recorded the call. |
| **Transcription button** | **Transcription** (top‑right of details) when AI Transcription is enabled. | Same button. |

## KPI tiles

| Tile | What it measures |
| - | - |
| **SIP Trunk Spend** | INR spent on SIP traffic for the selected date range. |
| **Total Calls** | Every SIP attempt. |
| **Answered** | The subset that connected. |
| **Answer Rate** | `Answered / Total Calls`. |
| **Avg. Duration** | Mean talk time across answered calls. |

## Call details panel

Same 4‑tab layout as Voice Call Logs - **Call Details**, **Call Stats**, **Call Quality**, **More**.

For SIP traffic specifically, the **More** tab adds:

* **SIP Trace** - raw INVITE / 100 / 180 / 200 / BYE messages with timing.
* **Hangup Cause Code** - the SIP cause code (`486 Busy Here`, `487 Request Terminated`, etc.) plus the friendly label.
* **Auth Method** - `IP ACL` or `Credentials`, useful for confirming which auth path the call used.

## Filters

Same modal as [Voice Call Logs filters](/docs/platform/voice/call-logs#search-and-filter):

* Direction (All / Inbound / Outbound)
* From Number / To Number (substring)
* Min / Max Duration (seconds)
* Hangup Cause (dropdown)

## Export to CSV

The **Export CSV** button downloads every call in the current filter + date range as a CSV - same columns as Voice Call Logs, plus a `Trunk Name` and `Auth Method` column for SIP rows.

## Tips

* **Filter by Trunk** when triaging a specific PBX. Use search box with the trunk's name.
* **MOS \< 3.5** consistently on outbound suggests a network problem between *your* PBX and Vobiz - check **Call Stats** for packet loss and jitter.
* **Hangup Cause 486 Busy Here** in inbound logs means your PBX's lines are full - increase concurrency or load‑balance across trunks.

## What's next

<CardGroup cols={2}>
  <Card title="Recordings" icon="microphone-lines" href="/docs/platform/sip/recordings">
    Play and download audio for recorded SIP calls.
  </Card>

  <Card title="CDR API" icon="terminal" href="/docs/cdr">
    Pull the same data programmatically.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.