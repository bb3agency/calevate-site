> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Download a Recording

> Programmatically download Vobiz recording files and resolve common authentication issues during playback - example code and troubleshooting tips.

Downloading a recording involves a multi-step process using the Vobiz API. Because recording files are stored securely, every request to access the physical file must be authenticated with your API credentials.

## Step-by-step guide to downloading recordings

Follow these three steps to successfully list, retrieve, and download a recording file.

### 1. List all recordings

First, retrieve a list of available recordings to find the `recording_id` you need.

```bash List Recordings theme={null}
curl -X GET "https://api.vobiz.ai/api/v1/Account/{auth_id}/Recording/?limit=20" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json"
```

### 2. Retrieve Specific Recording Details

Once you have the ID, fetch its metadata to get the `recording_url`.

```bash Get Recording Metadata theme={null}
curl -X GET "https://api.vobiz.ai/api/v1/Account/{auth_id}/Recording/{recording_id}/" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json"
```

### 3. Download the physical file

<Warning>
  **Important:** The download requires authentication. You must pass your `X-Auth-ID` and `X-Auth-Token` headers in the download request.
</Warning>

Always download using the **exact `recording_url` returned by step 2** rather than hand-constructing a path. The host can vary (for example `media.vobiz.ai`, `recordings.vobiz.ai`, or `storage.vobiz.ai`) and the file extension matches the `recording_format` (`.mp3` or `.wav`).

```bash Download via cURL theme={null}
RECORDING_URL=$(curl -s "https://api.vobiz.ai/api/v1/Account/{auth_id}/Recording/{recording_id}/" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  | jq -r '.recording_url')

curl -L "$RECORDING_URL" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -o my_recording.mp3
```

<Note>
  **Note:** The `-L` flag ensures cURL follows any server redirects.
</Note>

## Common issues

| Symptom | Cause | Fix |
| - | - | - |
| `401 Unauthorized` | Missing or wrong `X-Auth-ID` / `X-Auth-Token`, or trying to open the URL in a plain `<audio>` tag | Send both auth headers (see below). |
| `404 Not Found` | Wrong `recording_id`, or the recording was deleted / expired | Re-list recordings and confirm the ID still exists. |
| Empty / truncated file | Redirect not followed | Add the `-L` flag so cURL follows redirects. |
| Wrong extension | Saved `.wav` for an MP3 (or vice versa) | Match the file name to `recording_format`. |

## Why Dashboard Playback Fails

Dashboard playback may fail with a **401 Unauthorized** error because standard HTML `<audio>` and `<video>` tags cannot send custom HTTP headers (like `X-Auth-ID`).

## How to fix this on your platform

### 1. Server-side proxy

Create an endpoint on your own backend (e.g., `/api/play?id=123`) that fetches the file from Vobiz using your tokens and streams the binary data back to the dashboard.

### 2. Pre-download & serve

Use your server logic to download recordings to local storage first, and then serve them as static files directly to your clients.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.