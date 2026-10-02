> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# The Call Object

> Explore every field of the Vobiz Call object - UUID, status, direction, duration, hangup cause, STIR/SHAKEN verification, and per-call billing rate.

A Call object is created when an outbound call is initiated or when an inbound call is received. Use the Call object to interact with ongoing calls, retrieve details about completed calls, and transfer calls to build custom call flows.

<Note>
  Call objects are automatically created for both inbound and outbound calls. Each call has a unique `call_uuid` (also referred to as `request_uuid`) that can be used to retrieve call details or perform operations on the call.
</Note>

## Attributes

| Field | Type | Description |
| - | - | - |
| `answer_time` | string | Timestamp when the call was answered. Timezone: local timezone as set in the Vobiz Console. Format: `yyyy-MM-dd HH:mm:ss`. |
| `bill_duration` | integer | Duration of the call in seconds. |
| `billed_duration` | integer | Billed duration in seconds. May differ from `bill_duration` depending on the billing interval of the destination. |
| `call_direction` | string | Direction of the call: `outbound` or `inbound`. |
| `call_duration` | integer | Duration of the call in seconds. |
| `call_uuid` | string | Unique identifier for the call (also referred to as `request_uuid`). |
| `end_time` | string | Timestamp when the call ended. Timezone: local timezone as set in the Vobiz Console. Format: `yyyy-MM-dd HH:mm:ss`. |
| `from_number` | string | Caller ID used to initiate the call. |
| `hangup_cause_code` | integer | Integer code for the hangup cause. |
| `hangup_cause_name` | string | Reason the call was hung up. |
| `hangup_source` | string | Entity that triggered the hangup. Possible values: `Caller`, `Callee`, `Vobiz`, `API Request`, `Answer XML`, `Error`, `Unknown`. |
| `initiation_time` | string | Timestamp when the call was initiated. Timezone: local timezone as set in the Vobiz Console. Format: `yyyy-MM-dd HH:mm:ss`. |
| `parent_call_uuid` | string | UUID of the A-leg of the call. |
| `resource_uri` | string | URI of the requested resource. |
| `source_ip` | string | IP address from which the call request originated. Useful for monitoring misuse or unauthorized access. |
| `stir_verification` | string | STIR/SHAKEN attestation. Outbound: attestation assigned by Vobiz. Inbound: attestation received on the inbound call. Possible values: `Verified` (Attestation A), `Not Verified` (Attestation B or C), `Not Applicable` (e.g. non-US calls). |
| `to_number` | string | Number to which the call was initiated. |
| `total_amount` | string | Total amount charged for the call. |
| `total_rate` | string | Per-minute rate based on the destination number. |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.