> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Event

> Vobiz generates call events when the state of a call changes - your application receives them as HTTP requests so it can update state and trigger logic.

Vobiz generates events when the state of a call changes to let the application know about the progress of the call.

Vobiz will send one of these values under the Event parameter:

## Event values

| Value | Description |
| - | - |
| `StartApp` | The call was answered and is currently in progress. You can terminate it with the Hangup API. |
| `Transfer` | The call was transferred with the Transfer API. Vobiz sends this event to the target URL associated with the transfer XML. |
| `Redirect` | The call was redirected with the Redirect XML element. |
| `MachineDetection` | Machine detection was requested for an outbound API call. Vobiz sends this event to the configured machine-detection URL. |

### Example response

```json theme={null}
true
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.