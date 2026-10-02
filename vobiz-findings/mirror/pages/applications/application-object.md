> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# The Application Object

> Explore every field of the Vobiz Application object - answer_url, hangup_url, message_url, HTTP methods, SIP URI, and fallback behavior for call routing.

An Application is a named container for the webhook URLs that control your call flow. You attach a phone number or a SIP endpoint to an application so that calls fire its configured webhooks. See [Application vs Endpoint](#application-vs-endpoint) below to choose the right object.

## Attributes

| Field | Type | Description |
| - | - | - |
| `app_id` | string | Unique identifier for the application. Use it in all per-application API paths. |
| `app_name` | string | Name of the application. |
| `answer_url` | string | URL Vobiz fetches when a call executes this application. Must return valid VobizXML to control the call flow. |
| `answer_method` | string | HTTP method for `answer_url`. One of `GET` or `POST`. Default `POST`. |
| `hangup_url` | string | URL notified when the call ends. Useful for analytics and cleanup. If unset at create time, defaults to `answer_url`. |
| `hangup_method` | string | HTTP method for `hangup_url`. One of `GET` or `POST`. Default `POST`. |
| `fallback_answer_url` | string (nullable) | Backup URL invoked only when `answer_url` is unreachable, times out, or returns invalid VobizXML. Must itself return valid VobizXML. `null` when unset. |
| `fallback_method` | string | HTTP method for `fallback_answer_url`. One of `GET` or `POST`. Default `POST`. |
| `message_url` | string (nullable) | URL notified when an inbound message is received. Vobiz expects an HTTP 200 response. `null` when unset. |
| `message_method` | string | HTTP method for `message_url`. One of `GET` or `POST`. Default `POST`. |
| `default_number_app` | boolean | If `true`, newly created numbers without an `app_id` are auto-routed to this application. Default `false`. Does not retroactively re-route existing numbers. |
| `default_endpoint_app` | boolean | If `true`, newly created endpoints without an `application` are auto-routed to this application. Default `false`. Does not retroactively re-route existing endpoints. |
| `sub_account` | string (nullable) | Sub-account `auth_id`. `null` for the main account. Cannot be changed after creation. |
| `resource_uri` | string | API resource URI for this application. |
| `application_type` | string | Type of application. Typically `XML` (also seen as `voice`). |
| `default_app` | boolean | Whether this is the account-level default application. Default `false`. |
| `enabled` | boolean | Whether the application is enabled. Default `true`. |
| `log_incoming_message` | boolean | Whether incoming messages to numbers on this application are logged. Default `true`. |
| `public_uri` | boolean | Whether the application's `sip_uri` is reachable by external SIP systems. Default `false`. See [Public SIP URI](#public-sip-uri). |
| `sip_transfer_method` | string | HTTP method for SIP transfer callbacks. One of `GET` or `POST`. |
| `sip_transfer_url` | string (nullable) | URL notified during a SIP transfer. `null` when unset. |
| `sip_uri` | string | SIP URI associated with the application, e.g. `sip:<app_id>@sip.vobiz.ai`. |
| `created_at` | string (ISO 8601) | Creation timestamp (UTC). |
| `updated_at` | string (ISO 8601) | Last update timestamp (UTC). |

<Note>
  `api_id` is a request-correlation ID returned alongside the object on single-object responses (Create, Retrieve, Update). It is not a persistent attribute of the application.
</Note>

## Example Application Object

```json JSON theme={null}
{
  "answer_method": "POST",
  "answer_url": "https://example.com/answer",
  "api_id": "aabbccdd-1234-5678-90ab-cdef12345678",
  "app_id": "12345678901234567",
  "app_name": "My Voice App",
  "application_type": "XML",
  "created_at": "2026-04-02 12:11:19.740666+00:00",
  "default_app": false,
  "default_endpoint_app": false,
  "enabled": true,
  "fallback_answer_url": null,
  "fallback_method": "POST",
  "hangup_method": "POST",
  "hangup_url": "https://example.com/hangup",
  "log_incoming_message": true,
  "message_method": "POST",
  "message_url": null,
  "public_uri": false,
  "resource_uri": "/v1/Account/MA_XXXXXXXX/Application/12345678901234567/",
  "sip_transfer_method": "POST",
  "sip_transfer_url": null,
  "sip_uri": "sip:12345678901234567@app.vobiz.ai",
  "sub_account": null,
  "updated_at": "2026-04-02 12:11:19.740666+00:00"
}
```

## Application vs Endpoint

| You want to... | Use |
| - | - |
| Route inbound calls on a **phone number (DID)** to your webhooks | An **Application**, then [attach the number](/docs/applications/attach-number) to it. |
| Let a **device or person** (browser, softphone, desk phone, AI agent) place and receive calls | An [**Endpoint**](/docs/endpoint/endpoint-object), with an Application attached for its call logic. |
| Both - a number rings, then routes to a device | A number attached to an Application whose VobizXML `Dial`s the endpoint's `sip_uri`. |

## Public SIP URI

Every application has a `sip_uri` such as `sip:<app_id>@sip.vobiz.ai`. By default `public_uri` is `false`, meaning the URI is not exposed to external SIP systems.

Set `public_uri: true` only when a third-party SIP system - for example another PBX or carrier - needs to route calls **directly** into this application's `sip_uri`. For ordinary inbound flows driven by a Vobiz phone number, leave `public_uri` as `false`.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.