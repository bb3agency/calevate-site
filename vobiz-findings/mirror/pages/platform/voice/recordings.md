> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Call Recordings - Playback, Transcripts & AI Insights

> Browse, play, and download call recordings (WAV / MP3) in the Vobiz Console. AI-powered transcription, sentiment analysis, and storage lifecycle details (30-day retention).

The **Recordings** page lists every recorded call on your account - playable WAV or MP3 audio plus AI‑powered transcripts and sentiment scoring for the last 30 days.

```text URL theme={null}
https://console.vobiz.ai/app/voice/recordings
```

## The Recordings page

<Frame caption="Voice Applications - Recordings">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/voice/voice-recordings_blur.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=42731669a8739cf8c254d6e9c79fd9e1" alt="Call Recordings page with a notification banner stating recordings are shown for the last 30 days, a paginated list of recorded calls on the left with play buttons AI badges and format labels (WAV, MP3), and a Recording Info panel on the right with Format, Type, Storage Life of 3 days, Call Details (From, To, Start Time, Duration, Call UUID), and a Load Recording play card with Transcription Insights and Call Sentiment sections below" style={{maxWidth: '900px', margin: '0 auto', display: 'block'}} width="7960" height="4272" data-path="images/platform/voice/voice-recordings_blur.png" />
</Frame>

A banner at the top reminds you of the **30‑day retention window** - older recordings are deleted automatically. If you need longer retention, [export historical recordings](/docs/recording/export-historical-recordings) before they age out.

## The recordings list

The left column shows up to 20 recordings per page. Each row has:

* **▶ Play** icon - click to load and play inline.
* **From → To** numbers.
* **Date and timestamps** (`HH:MM:SS - HH:MM:SS`) plus duration.
* **Format badge** - `WAV` (uncompressed PCM) or `MP3` (lossy, smaller).
* **AI badge** - indicates the recording has been transcribed and analysed.

Search by call ID or number, or open **Filters** to narrow by date, direction, or duration.

## Recording details panel

The right side shows everything Vobiz knows about the selected recording.

### Top bar

* **Recording ID** (e.g. `#57e4ecdb-7296-49de-8f3e-b0680093505d`).
* **Format badge** (`WAV` / `MP3`).
* **Type badge** (`Call`, `Conference`, `Stream`).
* **▶ Play** - fetches the audio and starts playback.
* **View Analysis** - opens the full AI breakdown (transcript, sentiment, keywords).

### Call Details card

| Field | Meaning |
| - | - |
| **From** | Caller number with country flag. |
| **To** | Destination number. |
| **Start Time** | UTC timestamp converted to your browser timezone. |
| **Duration** | Total recorded length. |
| **Call UUID** | Canonical Call ID - matches what you see in [Call Logs](/docs/platform/voice/call-logs). |

### Recording Info card

| Field | Meaning |
| - | - |
| **Format** | `WAV` (8 kHz mono PCM by default) or `MP3` (CBR 64 kbps). |
| **Type** | `Call` for standard recordings, `Conference` for conference legs. |
| **Storage Life** | Days remaining before automatic deletion. The clock starts at recording creation. |

### Load Recording card

The **▶ Load Recording** card is the inline player. Click play, the audio fetches lazily (recordings aren't pre‑loaded to save bandwidth), and you get standard playback controls. Right‑click → *Save audio as…* to download a local copy.

### Transcription & Insights

Below the player, two AI‑generated sections appear once analysis completes (usually a few minutes after the call ends):

* **Transcription** - the full text with speaker labels.
* **Call Sentiment** - per‑speaker sentiment scoring (positive / neutral / negative) plus highlighted moments.

## Filters

Same modal as [Call Logs filters](/docs/platform/voice/call-logs#search-and-filter) - direction, From/To numbers, min/max duration, hangup cause.

## Tips

* **Export critical recordings within 30 days.** The retention window is hard - there's no recovery after deletion.
* **MP3 saves bandwidth.** For long compliance retention, MP3 is \~10× smaller than WAV with negligible quality loss for voice.
* **Quote the Call UUID** in support tickets, not the recording ID - it ties back to the full CDR and SIP trace.

## What's next

<CardGroup cols={2}>
  <Card title="Recording API" icon="terminal" href="/docs/recording">
    Programmatic access - list, download, delete, bulk export.
  </Card>

  <Card title="Export historical" icon="box-archive" href="/docs/recording/export-historical-recordings">
    Bulk‑export recordings to long‑term storage before retention kicks in.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.