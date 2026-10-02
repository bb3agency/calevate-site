> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# The Recording Object

> Explore every field on the Vobiz Recording object - recording ID, file URL, format, duration, source call UUID, and storage billing.

The Recording object represents a call or conference recording stored in your Vobiz account. It includes information about the recording file, associated call details, storage duration, and billing.

<Note>
  All recordings are automatically stored when call or conference recording is enabled. Storage costs are calculated based on duration and time stored, tracked in the `recording_storage_duration` and `monthly_recording_storage_amount` fields.
</Note>

## Attributes

### Core Attributes

| Field | Type | Description |
| - | - | - |
| `recording_id` | string | Unique identifier for the recording. Used in API operations to identify specific recordings. |
| `recording_url` | string | HTTPS download URL for the audio file. **Requires your `X-Auth-ID` and `X-Auth-Token` headers** - it is not a public link and will not open in a browser tab. |
| `recording_format` | string | Requested audio format. Allowed values: "mp3", "wav". **Detect the real container from the file's magic bytes** - this field, the `.mp3` extension and the `audio/mpeg` content-type can all disagree with the actual bytes. |
| `call_uuid` | string | UUID of the call or conference that was recorded. |
| `conference_name` | string | Name of the conference that was recorded. Value is null if it was a regular call, not a conference. |
| `recording_type` | string | Type of recording. Values: "call" (regular call), "conference" (conference call). |
| `add_time` | timestamp | Timestamp when the recording was created. Format: ISO 8601 (YYYY-MM-DDTHH:MM:SSZ). |

### Duration & Timing Attributes

| Field | Type | Description |
| - | - | - |
| `recording_start_ms` | float | Recording start time in milliseconds since epoch. |
| `recording_end_ms` | float | Recording end time in milliseconds since epoch. |
| `recording_duration_ms` | float | Actual duration of the recording in milliseconds. |
| `rounded_recording_duration` | integer | Rounded duration in seconds used for billing calculations. |

### Call Details

| Field | Type | Description |
| - | - | - |
| `from_number` | string | Caller phone number in E.164 format (e.g., +14155551234). |
| `to_number` | string | Destination phone number in E.164 format. |

### Storage & Billing Attributes

| Field | Type | Description |
| - | - | - |
| `recording_storage_duration` | integer | Number of days since the recording was created. Used to calculate storage costs. |
| `recording_storage_rate` | float | Storage rate per month in USD. This is the unit cost for storing this recording. |
| `monthly_recording_storage_amount` | float | Monthly storage cost in USD for the current billing cycle. |

## Example

### Complete Recording Object (Conference)

```json JSON Response theme={null}
{
    "api_id": "668470b7-7a8f-49b6-9011-50075754a50a",
    "meta": {
        "limit": 20,
        "next": null,
        "offset": 0,
        "previous": null,
        "total_count": 1
    },
    "objects": [
        {
            "add_time": "2025-11-06 13:49:10.751756+00:00",
            "call_uuid": "6e558798-499c-4a68-bc77-46f2c53d1f69",
            "conference_name": "",
            "from_number": "+918071387423",
            "monthly_recording_storage_amount": 0,
            "recording_duration_ms": "10080.00000",
            "recording_end_ms": "1762436949502.00000",
            "recording_format": "mp3",
            "recording_id": "d7801b2e-e76d-4dd8-be9c-9e015a7267b8",
            "recording_start_ms": "1762436939422.00000",
            "recording_storage_duration": 1,
            "recording_storage_rate": 0.005,
            "recording_type": "call",
            "recording_url": "https://media.vobiz.ai/api/v1/Account/MA_PU0XU668/Recording/d7801b2e-e76d-4dd8-be9c-9e015a7267b8.mp3",
            "resource_uri": "/v1/Account/MA_PU0XU668/Recording/d7801b2e-e76d-4dd8-be9c-9e015a7267b8/",
            "rounded_recording_duration": 60,
            "to_number": "919624705678"
        }
    ]
}
```

### Regular Call Recording Example

```json JSON Response theme={null}
{
    "api_id": "668470b7-7a8f-49b6-9011-50075754a50a",
    "meta": {
        "limit": 20,
        "next": null,
        "offset": 0,
        "previous": null,
        "total_count": 1
    },
    "objects": [
        {
            "add_time": "2025-11-06 13:49:10.751756+00:00",
            "call_uuid": "6e558798-499c-4a68-bc77-46f2c53d1f69",
            "conference_name": null,
            "from_number": "+918071387423",
            "monthly_recording_storage_amount": 0,
            "recording_duration_ms": "10080.00000",
            "recording_end_ms": "1762436949502.00000",
            "recording_format": "mp3",
            "recording_id": "d7801b2e-e76d-4dd8-be9c-9e015a7267b8",
            "recording_start_ms": "1762436939422.00000",
            "recording_storage_duration": 1,
            "recording_storage_rate": 0.005,
            "recording_type": "call",
            "recording_url": "https://media.vobiz.ai/api/v1/Account/MA_PU0XU668/Recording/d7801b2e-e76d-4dd8-be9c-9e015a7267b8.mp3",
            "resource_uri": "/v1/Account/MA_PU0XU668/Recording/d7801b2e-e76d-4dd8-be9c-9e015a7267b8/",
            "rounded_recording_duration": 60,
            "to_number": "919624705678"
        }
    ]
}
```

<Info>
  **Key Differences:**

  * **Conference Recording:** `conference_name` contains the conference name, `recording_type` is "conference"
  * **Regular Call:** `conference_name` is null, `recording_type` is "call"
  * **Duration:** `recording_duration_ms` is actual duration, `rounded_recording_duration` is used for billing
  * **Storage Cost:** Calculated from `recording_storage_rate` × `recording_storage_duration`
</Info>

<Warning>
  **Important Notes:**

  * Recording URLs may be temporary - download recordings for permanent storage
  * `recording_storage_duration` increments daily and affects monthly costs
  * Timestamps (`recording_start_ms`, `recording_end_ms`) are in milliseconds since Unix epoch and can be `null` (notably for some `trunk` captures)
  * `recording_duration_ms` is returned as a **string** of milliseconds; `rounded_recording_duration` is the integer seconds used for billing
  * Storage rate and amount are in USD
</Warning>

## Related operations

| Operation | Endpoint |
| - | - |
| List recordings | `GET /api/v1/Account/{auth_id}/Recording/` |
| Retrieve one | `GET /api/v1/Account/{auth_id}/Recording/{recording_id}/` |
| Delete one | `DELETE /api/v1/Account/{auth_id}/Recording/{recording_id}/` (returns `204 No Content`) |

<Note>
  Deleting a recording is permanent and frees its storage from your next billing cycle. To keep a copy first, [download](/docs/recording/download-recording) or [export](/docs/recording/export-historical-recordings) it before deleting.
</Note>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.