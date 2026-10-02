> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Plivo Voice Call API → Vobiz: Endpoint & SDK Migration

> Map every Plivo Voice Call API endpoint and SDK method - make a call, list/get live & queued calls, hang up, transfer, play, speak, send DTMF, record - to its Vobiz REST and SDK equivalent.

This page maps Plivo's **Voice Call API** - outbound call creation and in-call control - to the Vobiz REST API and SDKs, method by method. Both share the `/Account/{auth_id}/Call/` path shape and the `from` / `to` / `answer_url` model; the differences are the base host, auth headers, SDK method names, and an endpoint Vobiz handles through XML.

## Plivo → Vobiz mapping table

REST paths are relative to each base URL: Plivo `https://api.plivo.com/v1`, Vobiz `https://api.vobiz.ai/api/v1`. SDK columns use Python names (Node is the camelCase equivalent: `make_call` → `makeCall`).

| Operation | Plivo REST | Plivo SDK | Vobiz REST | Vobiz SDK (Python) |
| - | - | - | - | - |
| Make outbound call | `POST /Account/{id}/Call/` | `client.calls.create(...)` | `POST /Account/{id}/Call/` | `client.calls.make_call(...)` |
| List live calls | `GET /Account/{id}/Call/?status=live` | `client.calls.list(...)` | `GET /Account/{id}/Call?status=live` | `client.live_calls.list_live_calls(...)` |
| Get one live call | `GET /Account/{id}/Call/{uuid}/?status=live` | `client.calls.get(uuid)` | `GET /Account/{id}/Call/{uuid}?status=live` | `client.live_calls.get_live_call(...)` |
| List queued calls | `GET /Account/{id}/Call/?status=queued` | `client.calls.list(...)` | `GET /Account/{id}/Call/?status=queued` | `client.live_calls.list_queued_calls(...)` |
| Get one queued call | `GET /Account/{id}/Call/{uuid}/?status=queued` | `client.calls.get(uuid)` | `GET /Account/{id}/Call/{uuid}/?status=queued` | `client.live_calls.get_queued_call(...)` |
| Hang up a live call | `DELETE /Account/{id}/Call/{uuid}/` | `client.calls.hangup(uuid)` / `delete(uuid)` | `DELETE /Account/{id}/Call/{uuid}` | `client.live_calls.hangup_call(...)` |
| Transfer a live call | `POST /Account/{id}/Call/{uuid}/` | `client.calls.transfer(uuid, ...)` | Via the [`<Redirect>` VobizXML verb](/docs/xml/redirect) | Return `<Redirect>` from your answer XML |
| Play audio on a call | `POST /Account/{id}/Call/{uuid}/Play/` | `client.calls.play(uuid, urls)` | `POST /Account/{id}/Call/{uuid}/Play/` | `client.play_audio.call(...)` |
| Stop audio playback | `DELETE /Account/{id}/Call/{uuid}/Play/` | `client.calls.play_stop(uuid)` | `DELETE /Account/{id}/Call/{uuid}/Play/` | `client.play_audio.stop_audio_call(...)` |
| Speak text (TTS) | `POST /Account/{id}/Call/{uuid}/Speak/` | `client.calls.speak(uuid, text)` | `POST /Account/{id}/Call/{uuid}/Speak/` | `client.speak_text.call(...)` |
| Stop TTS | `DELETE /Account/{id}/Call/{uuid}/Speak/` | `client.calls.speak_stop(uuid)` | `DELETE /Account/{id}/Call/{uuid}/Speak/` | `client.speak_text.stop_speak_call(...)` |
| Send DTMF digits | `POST /Account/{id}/Call/{uuid}/DTMF/` | `client.calls.send_digits(uuid, digits)` | `POST /Account/{id}/Call/{uuid}/DTMF/` | `client.dtmf.send_dtmf(...)` |
| Start recording | `POST /Account/{id}/Call/{uuid}/Record/` | `client.calls.record(uuid)` | `POST /Account/{id}/Call/{uuid}/Record/` | `client.record_calls.start_recording(...)` |
| Stop recording | `DELETE /Account/{id}/Call/{uuid}/Record/` | `client.calls.record_stop(uuid)` | `DELETE /Account/{id}/Call/{uuid}/Record/` | `client.record_calls.stop_recording(...)` |
| Start audio stream | `POST /Account/{id}/Call/{uuid}/Stream/` | `client.calls.start_stream(uuid, ...)` | `POST /Account/{id}/Call/{uuid}/Stream/` | `client.audio_streams.start_stream(...)` |

## Before / after: make an outbound call

The change is the client constructor and method name (`create` → `make_call`), plus passing `auth_id` explicitly. Call parameters carry over unchanged.

**Plivo (Python):**

```python theme={null}
import plivo

client = plivo.RestClient("PLIVO_AUTH_ID", "PLIVO_AUTH_TOKEN")
client.calls.create(
    from_="14155551234",
    to_="+919876543210",
    answer_url="https://example.com/answer",
    answer_method="POST",
)
```

**Vobiz (Python):**

```python theme={null}
from vobiz import Vobiz

client = Vobiz(api_key="VOBIZ_AUTH_ID", auth_token="VOBIZ_AUTH_TOKEN")
client.calls.make_call(
    auth_id="VOBIZ_AUTH_ID",
    from_="14155551234",
    to="+919876543210",
    answer_url="https://example.com/answer",
    answer_method="POST",   # required on Vobiz
)
```

Both return `api_id`, `request_uuid`, and `message: "Call fired"`. To dial multiple destinations in one request, both accept up to 1000 numbers in `to` separated by `<`.

## Key differences & gotchas

* **Auth headers, not Basic auth.** Vobiz uses `X-Auth-ID` and `X-Auth-Token` request headers instead of Plivo's HTTP Basic. Raw-HTTP and webhook-verification code must change.
* **Base URL keeps an extra segment:** `api.vobiz.ai/api/v1` (note the `/api` before `/v1`).
* **`answer_method` is required on Vobiz `make_call`.** Plivo defaults it to `POST`; always pass it on Vobiz.
* **In-call actions are separate resources.** `client.calls.play/speak/send_digits/record` become `client.play_audio`, `client.speak_text`, `client.dtmf`, `client.record_calls`.

For everything outside this `Call`-resource scope (conferences, CDRs, numbers, applications, webhooks/signatures, PlivoXML → VobizXML), see the [full migration guide](/docs/guides/plivo-to-vobiz) and the [Vobiz vs Plivo comparison](/docs/compare/vobiz-vs-plivo).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.