> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz Recordings API – Call & Conference Recording Management

> List, retrieve, download, and delete Vobiz call and conference recordings via REST API - with bulk export, compliance-grade storage, per-recording metadata, and INR billing for India.

The Recording API lets you manage recordings stored in your Vobiz account. Retrieve recording details including storage duration and billing information, list recordings with advanced filtering options, and delete recordings when they are no longer needed.

<Info>
  **Capabilities**

  * **Call Recordings** - Manage recordings from regular voice calls with detailed metadata.
  * **Conference Recordings** - Access recordings from conference calls and multiparty calls.
  * **Storage Management** - Track storage duration and associated monthly costs.
  * **File Formats** - Recordings are available in MP3 and WAV formats. Detect the container from the file's bytes, not its extension - see the warning below.
</Info>

<Info>
  **Important:** Recordings are stored securely and accessible via HTTPS URLs. Storage costs are calculated monthly based on the recording duration and storage time.
</Info>

<Warning>
  **The file's container may not match its extension or content-type.** A recording
  served at `Recording/{id}.mp3` with `Content-Type: audio/mpeg` and
  `recording_format: "mp3"` can still contain WAV (`pcm_s16le`) audio - observed on
  calls placed with `fileFormat="mp3"` on the same account, on the same day.

  **Detect the container from the magic bytes** rather than trusting the extension,
  the content-type, or `recording_format`. Anything that decodes by extension will
  eventually hit a file it cannot open.

  One implementation trap worth knowing: an MP3 frame sync is **11 bits** - `0xFF`
  followed by the top three bits of the next byte. Checking the second byte against
  a fixed list such as `0xFB` / `0xF3` / `0xF2` rejects the valid MPEG-2.5 Layer III
  files (`0xFF 0xE3`) this platform returns.

  Recording URLs also require your `X-Auth-ID` and `X-Auth-Token` headers; they are
  not public links.
</Warning>

## API Endpoint

**Base URL**

```text Base URL theme={null}
https://api.vobiz.ai/api/v1
```

**Recording Base URI**

```text Recording Base URI theme={null}
https://api.vobiz.ai/api/v1/Account/{auth_id}/Recording/
```

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account ID (e.g., `{auth_id}`)
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

## Available Operations

| Method | Operation | Description |
| - | - | - |
| OBJECT | [The Recording object](/docs/recording/recording-object) | Complete structure and attributes of a Recording object including storage and billing details. |
| GET | [Retrieve a recording](/docs/recording/retrieve-recording) | Get details of a specific recording based on its recording ID. |
| GET | [List all recordings](/docs/recording/list-all-recordings) | Retrieve a list of all recordings with extensive filtering options. |
| GET | [Download a recording](/docs/recording/download-recording) | Step-by-step guide to download physical recording files and resolve playback issues. |
| POST | [Export historical recordings](/docs/recording/export-historical-recordings) | Export recordings as a downloadable archive sent via email (async operation). |

<Warning>
  **Note:** Vobiz automatically rounds recording durations to the nearest 60-second interval. Recordings shorter than 60 seconds are rounded up to 60 seconds for billing purposes.
</Warning>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.