> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Voice API Hangup Causes – Codes & Troubleshooting

> Reference every Vobiz hangup code, cause, and source - decode why a call disconnected from the call detail record or hangup callback, and follow the exact next step to resolve it.

Vobiz records why and how every call is disconnected in the call detail record (CDR), which you can retrieve via API or view in the [Vobiz Console](https://console.vobiz.ai) at **Voice → Logs → Calls**.

Hangup information is also delivered in callback requests:

| Call type | Where the hangup is sent |
| - | - |
| Outbound API calls | `hangup_url` specified in the Make Call API |
| Incoming calls | `hangup_url` in the Vobiz application |
| Dial XML calls | `callbackUrl` in `DialHangup` events |

## Hangup Sources

The **source** tells you who or what ended the call.

| Source | Description |
| - | - |
| Caller | Call hung up by the caller |
| Call recipient | Call hung up by the dialed party |
| Vobiz | Vobiz initiated the hangup (see causes below) |
| Carrier | Hangup signal from the remote carrier |
| API Request | Terminated via the Hangup or Cancel Call API |
| Answer XML | Hung up using the `Hangup` XML element |
| Error | An error condition terminated the call |
| Unknown | Hangup source could not be determined |

## Hangup Causes

<AccordionGroup>
  <Accordion title="Normal Completions (4000–4030)">
    Normal call terminations. Typically no action required.

    | Code | Cause | Description | Next Steps |
    | - | - | - | - |
    | `4000` | Normal Hangup | Call terminated normally | None. Call completed successfully |
    | `4010` | End Of XML Instructions | No more XML instructions to execute | None. Normal for XML-controlled calls |
    | `4020` | Multiparty Call Ended | MPC ended via API or max duration | None. Check if max duration was intentional |
    | `4030` | Kicked Out Of Multiparty Call | Participant removed via API | None. Verify participant removal was expected |
  </Accordion>

  <Accordion title="Canceled Calls (1000–1020)">
    Calls canceled before being answered.

    | Code | Cause | Description | Next Steps |
    | - | - | - | - |
    | `0` | Unknown | Hangup reason undetermined. Known bug: the Delete All Calls API sets this | Check call logs for context |
    | `1000` | Canceled | Call canceled via Hangup Call API before answer | None. Intentional cancellation |
    | `1010` | Canceled (Out Of Credits) | Account ran out of credits | Add credits. Enable auto-recharge in **Console → Billing** |
    | `1020` | Canceled (Simultaneous dial limit reached) | Simultaneous dial limit exceeded | Reduce concurrent dials to the same destination |
  </Accordion>

  <Accordion title="Destination Issues (2000–2070)">
    Issues with the destination number or endpoint.

    | Code | Cause | Description | Next Steps |
    | - | - | - | - |
    | `2000` | Invalid Destination Address | Destination number/endpoint invalid | Use E.164 format (`+12292442099`). Verify the number is valid |
    | `2010` | Destination Out Of Service | Destination unavailable | Retry later. Verify the destination is active |
    | `2020` | Endpoint Not Registered | SIP endpoint unregistered or unreachable | Verify the endpoint is logged in. Check SDK troubleshooting |
    | `2030` | Destination Country Barred | Country disabled in geo permissions | Enable the country in **Console → Voice → Geo Permissions** |
    | `2040` | Destination Number Barred | Premium rate numbers disabled | Enable high-risk permissions in **Console → Voice → Geo Permissions** |
    | `2050` | Destination Prefix Barred | Prefix not permitted | Enable the prefix in **Console → Voice → Geo Permissions** |
    | `2060` | Loop Detected | B-leg would redial the A-leg's number | Fix routing logic to prevent loops |
    | `2070` | Violates Media Anchoring | India PSTN regulation violation | For India calls, your server must be in India. Don't mix PSTN and WebRTC in conferences |
  </Accordion>

  <Accordion title="Call Rejections (3000–3050)">
    Calls rejected by the destination or carrier.

    | Code | Cause | Description | Next Steps |
    | - | - | - | - |
    | `3000` | No Answer | Destination unavailable or unreachable | Retry. Check if the destination is online |
    | `3010` | Busy Line | Destination is busy | Retry later or implement voicemail fallback |
    | `3020` | Rejected | Call rejected by the called party | None. Recipient declined the call |
    | `3030` | Unknown Caller ID | Non-Vobiz number used as caller ID | Use a Vobiz-rented number as caller ID |
    | `3040` | Forbidden | Destination rejected or blocked the call | Have the recipient check for blocked numbers |
    | `3050` | Unallocated number | Destination invalid or out of service | Verify the destination number accuracy |
  </Accordion>

  <Accordion title="Carrier Errors (3070–3140)">
    Errors from the remote carrier or network.

    | Code | Cause | Description | Next Steps |
    | - | - | - | - |
    | `3070` | Request timeout | Carrier didn't respond in time | Retry. Check carrier availability |
    | `3080` | Internal server error from carrier | Carrier encountered an error | Retry. If persistent, contact support |
    | `3090` | Network congestion from carrier | Carrier network overloaded | Retry with backoff |
    | `3100` | Busy everywhere | All destination endpoints busy | Retry later |
    | `3110` | Declined | Destination cannot or won't participate | Verify the destination accepts calls |
    | `3120` | User does not exist anywhere | End user doesn't exist | Verify the destination number |
    | `3130` | Spam block | Carrier rejected the call due to a spam flag | Register the number with STIR/SHAKEN. Consider a different caller ID |
    | `3140` | DNO Caller ID | Caller ID on the Do Not Originate list | Use a different number. This one is inbound-only |
  </Accordion>

  <Accordion title="System Errors (5000–5030)">
    Internal system, network, or capacity errors.

    | Code | Cause | Description | Next Steps |
    | - | - | - | - |
    | `5000` | Network Error | Fatal network condition | Contact Vobiz support with the call UUID |
    | `5010` | Internal Error | Vobiz system error | Contact Vobiz support with the call UUID |
    | `5020` | Routing Error | Could not route to destination | Contact Vobiz support with the call UUID |
    | `5030` | Concurrency Limit Breached | India concurrent call limit exceeded | Reduce active calls or upgrade CPS to increase capacity |
  </Accordion>

  <Accordion title="Timeouts (6000–6020)">
    Calls ended due to timeout conditions.

    | Code | Cause | Description | Next Steps |
    | - | - | - | - |
    | `6000` | Scheduled Hangup | Max call duration reached | None. Configure `time_limit` (API) or `timeLimit` (Dial XML) if longer calls are needed |
    | `6010` | Ring Timeout Reached | Not answered within the ring timeout | Increase `ring_timeout` (API) or `timeout` (Dial XML). Default is 120 seconds |
    | `6020` | Media Timeout | No media packets for 60 seconds | Check network connectivity. May indicate a lost connection |
  </Accordion>

  <Accordion title="URL Errors (7011–7034)">
    Errors fetching or validating callback URLs.

    | Code | Cause | Description | Next Steps |
    | - | - | - | - |
    | `7011` | Error Reaching Answer URL | Non-2xx response from the answer URL | Verify the URL is accessible. Check server logs |
    | `7012` | Error Reaching Action URL | Non-2xx response from the action URL | Verify the URL is accessible (only fails if `redirect=true`) |
    | `7013` | Error Reaching Transfer URL | Non-2xx response from the transfer URL | Verify the URL is accessible |
    | `7014` | Error Reaching Redirect URL | Non-2xx response from the redirect URL | Verify the URL is accessible |
    | `7022` | Invalid Action URL | Action URL not valid | Ensure the URL starts with `http://` or `https://` |
    | `7023` | Invalid Transfer URL | Transfer URL not valid | Ensure the URL starts with `http://` or `https://` |
    | `7024` | Invalid Redirect URL | Redirect URL not valid | Ensure the URL starts with `http://` or `https://` |
    | `7032` | Invalid Method For Action URL | Unsupported HTTP method | Use only `GET` or `POST` |
    | `7033` | Invalid Method For Transfer URL | Unsupported HTTP method | Use only `GET` or `POST` |
    | `7034` | Invalid Method For Redirect URL | Unsupported HTTP method | Use only `GET` or `POST` |
  </Accordion>

  <Accordion title="XML Errors (8011–8014)">
    Invalid Vobiz XML returned by your URLs.

    | Code | Cause | Description | Next Steps |
    | - | - | - | - |
    | `8011` | Invalid Answer XML | Answer URL returned invalid XML | Check debug logs in Console. Validate XML syntax |
    | `8012` | Invalid Action XML | Action URL returned invalid XML | Check debug logs. Only fails if `redirect=true` |
    | `8013` | Invalid Transfer XML | Transfer URL returned invalid XML | Check debug logs. Validate XML syntax |
    | `8014` | Invalid Redirect XML | Redirect URL returned invalid XML | Check debug logs. Validate XML syntax |
  </Accordion>

  <Accordion title="Special Cases (9000–9110)">
    Specialized hangup scenarios.

    | Code | Cause | Description | Next Steps |
    | - | - | - | - |
    | `9000` | Lost Race | Another parallel B-leg answered first | None. Normal for simultaneous dial |
    | `9100` | Machine Detected | Answered by an answering machine | None. Occurs when `machine_detection=hangup` |
    | `9110` | Confirm Key Challenge Failed | Participant failed to enter the confirm key | Inform the participant of the required DTMF input |
  </Accordion>
</AccordionGroup>

## SIP Hangup Causes

In addition to the numeric codes above, call logs may surface a textual `hangup_cause` value originating from the underlying SIP / B2BUA layer. The table below describes the common values you may encounter.

| `hangup_cause` | Description |
| - | - |
| `NORMAL_CLEARING` | One of the parties hung up normally |
| `USER_BUSY` | The called party is busy (already on another call or declined) |
| `NO_ANSWER` | The called party did not answer within the timeout period |
| `ORIGINATOR_CANCEL` | The caller cancelled the call before it was answered |
| `CALL_REJECTED` | The destination explicitly rejected the call |
| `REJECTED` | General rejection. The SIP endpoint refused the `INVITE` |
| `INVALID_NUMBER` | The dialed number format is invalid |
| `UNALLOCATED_NUMBER` | The dialed number is valid but not allocated to any subscriber |
| `SERVICE_UNAVAILABLE` | The destination service is temporarily unavailable (SIP 503) |
| `SERVER_ERROR` | An internal server error occurred during call setup |
| `MEDIA_TIMEOUT` | No RTP media packets received. Likely a firewall or network issue |
| `PROTOCOL_ERROR` | A SIP protocol violation or malformed message |
| `NETWORK_OUT_OF_ORDER` | A severe network failure prevented routing |
| `DESTINATION_OUT_OF_ORDER` | The destination endpoint cannot accept the call |
| `NORMAL_TEMPORARY_FAILURE` | Generic temporary failure. Retrying may succeed |
| `SWITCH_CONGESTION` | The SIP switch is at capacity |
| `UNKNOWN` | An error not mapped to a standard cause code |

## Getting Help

If issues persist after troubleshooting:

<Steps>
  <Step title="View debug logs">
    Open **Console → Voice → Logs → Calls** and inspect the debug logs for the affected call.
  </Step>

  <Step title="Note the call details">
    Record the **Call UUID** and the **hangup code**.
  </Step>

  <Step title="Contact support">
    Reach out to [support@vobiz.ai](mailto:support@vobiz.ai) with the Call UUID and hangup code so the team can investigate quickly.
  </Step>
</Steps>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.