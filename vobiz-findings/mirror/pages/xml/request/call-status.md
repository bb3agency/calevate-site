> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Call status

> Vobiz sends a call status to request URLs under the CallStatus key. Your application can make decisions about how to process a call based on this status.

Vobiz sends a call status to request URLs under the CallStatus key. Your application can make decisions about how to process a call based on this status.

Vobiz will send one of these values under the CallStatus parameter:

## CallStatus values

| Value | Type | Description |
| - | - | - |
| `in-progress` | string | The call was answered and is currently in progress. You can terminate it with the Hangup API. |
| `completed` | string | The call ended normally, through the Hangup API, or when one of the parties disconnected. |
| `ringing` | string | The call is currently ringing. Vobiz sends this status to the ring URL. |
| `no-answer` | string | The recipient did not answer the call. |
| `busy` | string | The recipient is busy on another call. |
| `cancel` | string | The caller canceled the call. |
| `timeout` | string | The connection attempt timed out because of carrier or network conditions. |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.