> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Campaign webhook events

> Receive and verify signed voice campaign and contact lifecycle events.

Set `notify_url` on a campaign to receive state changes and contact outcomes as JSON `POST` requests.

## Verify signatures

Every request includes:

```http theme={null}
X-VoBiz-Signature: sha256=<hmac-hex>
```

Vobiz computes the value as `HMAC-SHA256(raw_body_bytes, account_auth_token)`. Verify the signature against the unmodified request body before parsing JSON. Compare digests with a constant-time function.

<Warning>
  Do not re-serialize the parsed JSON before verification. Whitespace or key-order changes produce a different digest.
</Warning>

Failed deliveries are retried up to three times, with attempts at approximately `0`, `5`, and `30` seconds. Return a `2xx` response after durable processing. Make handlers idempotent because retries can deliver the same event more than once.

## Campaign events

| Event | When it is sent | Additional fields |
| - | - | - |
| `campaign.started` | A ready campaign becomes `running`. | — |
| `campaign.stalled` | The watchdog pauses a campaign with no recent dial. | `reason`, `last_dial_at`, `stalled_minutes` |
| `campaign.paused` | A campaign pauses manually or automatically. | `reason` |
| `campaign.failed` | Startup fails or a dial-time failure condition pauses execution. | `reason` |
| `campaign.resumed` | A campaign resumes manually or automatically. | — |
| `campaign.completed` | Every contact reaches a terminal state. | — |
| `campaign.cancelled` | The campaign is cancelled. | — |

Every campaign event includes `event`, `campaign_id`, `account_id`, and `timestamp`.

```json campaign.started theme={null}
{
  "event": "campaign.started",
  "campaign_id": "a4c7ab38-11ce-4bd0-a51a-f6a946627843",
  "account_id": "MA_XXXXXXXX",
  "timestamp": "2026-05-01T09:00:00Z"
}
```

### Pause and failure reasons

Pause reasons include `manual_pause`, `window_closed`, `caller_pool_exhausted`, `caller_pool_daily_limit_reached`, `account_inactive`, `stalled`, and `consecutive_failures`.

Current dial-time failure reasons include `consecutive_failures` and `balance_insufficient`.

## Contact events

| Event | Meaning |
| - | - |
| `contact.answered` | The call ended with `NORMAL_CLEARING` or `SUCCESS`. |
| `contact.no_answer` | The destination did not answer. |
| `contact.retry_scheduled` | The contact moved to `retry_pending`. |
| `contact.failed` | The contact reached terminal `failed` state. |
| `contact.expired` | The retry window elapsed without an answer. |

Contact outcome payloads can include `contact_id`, `call_uuid`, `to_number`, `from_number`, `hangup_cause`, and `duration`.

```json contact.answered theme={null}
{
  "event": "contact.answered",
  "campaign_id": "a4c7ab38-11ce-4bd0-a51a-f6a946627843",
  "account_id": "MA_XXXXXXXX",
  "timestamp": "2026-05-01T10:05:30Z",
  "contact_id": "8e7a452d-f9db-43e1-9102-a7bb7eb999c4",
  "call_uuid": "c5e2a7f8-1234-5678-abcd-ef0123456789",
  "to_number": "+919876543210",
  "from_number": "+919000000001",
  "hangup_cause": "NORMAL_CLEARING",
  "duration": 47
}
```

```json contact.retry_scheduled theme={null}
{
  "event": "contact.retry_scheduled",
  "campaign_id": "a4c7ab38-11ce-4bd0-a51a-f6a946627843",
  "account_id": "MA_XXXXXXXX",
  "timestamp": "2026-05-01T10:06:00Z",
  "contact_id": "8e7a452d-f9db-43e1-9102-a7bb7eb999c4",
  "call_uuid": "c5e2a7f8-aaaa-5678-abcd-ef0123456789",
  "to_number": "+919876543211",
  "hangup_cause": "NO_ANSWER",
  "duration": 0
}
```

If retries remain, a `contact.no_answer` event can be followed by `contact.retry_scheduled`. Do not treat the first event as the final contact outcome.

## Hangup mapping

| Hangup cause | Contact status |
| - | - |
| `NORMAL_CLEARING`, `SUCCESS` | `answered` |
| `NO_ANSWER`, `USER_NOT_REGISTERED` | `no_answer` |
| `USER_BUSY` | `busy` |
| All other causes | `failed` |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.