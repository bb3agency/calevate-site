> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz API changelog

> Dated release notes for the Vobiz public API surface - new endpoints and parameters, VobizXML changes, webhook and streaming updates, and SDK releases.

This page records dated changes to the public Vobiz API surface: REST endpoints and their parameters, VobizXML elements and attributes, webhook and WebSocket streaming contracts, network requirements, and the generated SDKs. Entries are grouped by month, newest first, and cover what an integrator can act on. Console-only and editorial changes are out of scope.

## July 2026

### Added

* **July 1** - Twilio to Vobiz migration section covering the voice call API, VobizXML, webhooks, sub-accounts, phone numbers, conferences, recordings, SIP trunking, and SDKs. See [Twilio migration overview](/docs/compare/twilio/overview).
* **July 3** - `GET /api/v1/account/{auth_id}/numbers/{e164}/health` returns a number's status, spam flag, and call metrics with a per-period snapshot series. See [Get number health](/docs/account-phone-number/get-number-health).
* **July 7** - `webhook_url` and `webhook_method` on [create trunk](/docs/trunks/create-trunk) and [update trunk](/docs/trunks/update-trunk) set a trunk's real-time call-event webhook.
* **July 9** - [Zoiper 5 integration guide](/docs/integrations/zoiper) for registering a softphone against a Vobiz SIP endpoint.
* **July 10** - `exclude` query parameter on [list inventory numbers](/docs/account-phone-number/list-inventory-numbers) removes one or more E.164 prefixes from the results. Prefixes include the country code, and you can pass a comma-separated list or repeat the parameter.
* **July 13** - [Stream audio formats](/docs/xml/stream/audio-formats) reference for inbound and outbound WebSocket audio.
* **July 13** - `18.96.230.96/28` and `18.96.230.112/28` added to the RTP media ranges to whitelist. See [IP whitelisting](/docs/concepts/ip-whitelisting).
* **July 14** - `page`, `per_page`, and `search` query parameters on [list account phone numbers](/docs/account-phone-number/list-account-phone-numbers).
* **July 18** - Capacity APIs: [preview CPS or concurrency pricing](/docs/account/channel-pricing-preview) and [purchase capacity](/docs/account/channel-subscriptions).
* **July 18** - [Rapida AI integration](/docs/integrations/rapida-ai) covering setup and inbound calling.
* **July 20** - `POST /api/v1/account/{account_id}/numbers/{e164}/cancel-release` cancels a standard release during its 24-hour pending window. See [Cancel release](/docs/account-phone-number/cancel-release).
* **July 21** - [Voice Campaign Manager API](/docs/campaign-manager/overview) for outbound campaigns: agents, campaigns, caller-ID pools, contacts and results, runtime controls, capacity monitoring, and HMAC-SHA256 signed webhooks.
* **July 29** - [Sarvam integration](/docs/integrations/sarvam) for taking a Samvaad voice agent live on a Vobiz-powered number.

### Changed

* **July 13** - [Dial reference](/docs/xml/dial) rewritten against runtime behaviour. Set `callerId` to a number your account owns or is authorized to use; when it is omitted, Vobiz derives the caller ID from the A-leg.
* **July 14** - SIP endpoint URIs use the form `sip:username@registrar.vobiz.ai`. See [Endpoint object](/docs/endpoint/endpoint-object).
* **July 14** - Conference references aligned with runtime behaviour: [list conferences](/docs/conference/retrieve-all-conferences) returns an array of room names, retrieve returns the full [conference object](/docs/conference/conference-object), and a room exists from the moment the first caller joins through `<Conference>`. Keep your own room registry for authoritative discovery and cleanup.
* **July 31** - [Releasing a number](/docs/account-phone-number/unrent-number) charges an account-specific release fee, returned as `release_fee`. Cancelling a standard release during the pending window refunds it.

### Fixed

* **July 13** - Stream control examples read the stream identifier from `start.streamId` in the WebSocket `start` event, and `streamId` is required on [`playAudio`](/docs/xml/stream/play-audio).
* **July 13** - Corrected the nesting in the [Stream with Record](/docs/xml/record/stream-with-record) example.

## June 2026

### Added

* **June 4** - [Outbound campaign manager guide](/docs/best-practices/outbound-campaign-manager) covering number rotation, daily caps, cooldown, retry policy, and the campaign state machine.
* **June 4** - Sub-account KYC [email flow webhook](/docs/sub-accounts/kyc/email-flow-webhook) reference. The webhook payload carries the sub-account `account_auth_id` with the `SA_` prefix.
* **June 5** - Sub-account KYC [redirect flow webhook](/docs/sub-accounts/kyc/redirect-flow-webhook) reference, including `webhook_url` on the hosted KYC session.
* **June 8** - [Dograh integration](/docs/integrations/dograh) for self-hosted AI voice agents over Vobiz.
* **June 10** - [Hangup causes](/docs/concepts/hangup-causes) reference listing numeric hangup codes and SIP `hangup_cause` values with next steps.
* **June 11** - `GET /api/v1/Account/{auth_id}/Call/` lists queued calls. See [Retrieve all queued calls](/docs/call/retrieve-all-queued-calls).
* **June 18** - [NDNC webhook](/docs/account/ndnc-webhook) reference for UCC complaint delivery, including payload fields and signature verification.
* **June 18** - [Plivo to Vobiz migration guide](/docs/guides/plivo-to-vobiz) with an XML converter.
* **June 29** - SDKs generated from `openapi.yaml` for [TypeScript](/docs/integrations/node-sdk), [Python](/docs/integrations/python-sdk), [Go](/docs/integrations/go-sdk), [Java](/docs/integrations/java-sdk), [Ruby](/docs/integrations/ruby-sdk), [C#](/docs/integrations/csharp-sdk), and [PHP](/docs/integrations/php-sdk).
* **June 29** - `vobizxml` call-control XML builders ship in all seven SDK languages, so you can construct VobizXML responses without string templating.
* **June 30** - CDR filters `sip_call_id`, `bridge_uuid`, `hangup_cause`, `hangup_disposition`, `context`, `campaign_id`, and `search` on [list](/docs/cdr/list-cdrs), [search](/docs/cdr/search-cdrs), and [export](/docs/cdr/export-cdrs) CDRs.
* **June 30** - [Deleting a sub-account](/docs/sub-accounts/delete-subaccount) with parent credentials alone: list sub-accounts to find the `SA_` auth ID, then delete it.

### Changed

* **June 9** - RTP media uses UDP ports `5000-65535`. See [IP whitelisting](/docs/concepts/ip-whitelisting).
* **June 10** - SIP signaling whitelist extended with `65.2.100.211` and `3.111.255.163`.
* **June 15** - WhatsApp messaging API reference corrected against the live service: base URL `https://api.vobiz.ai/api/v1/messaging`, `X-Auth-ID` and `X-Auth-Token` header authentication, list responses shaped as `items` / `total` / `page` / `limit` / `has_more`, message lists paged by `next_cursor`, and UUID resource identifiers.
* **June 27** - `callerId` is set on the parent `<Dial>` element, not on nested [`<Number>`](/docs/xml/dial/number) or [`<User>`](/docs/xml/dial/user).

### Fixed

* **June 4** - `<Gather>` uses `executionTimeout`. The `timeout` attribute belongs to `<Dial>` and `<Number>`. See [Gather](/docs/xml/gather).

## May 2026

### Added

* **May 13** - [Bun media stream server example](/docs/examples/vobiz-bun-media-stream) for terminating a Vobiz WebSocket stream.
* **May 15** - [Vobiz MCP server](/docs/resources/mcp) so AI clients can query these docs directly.
* **May 19** - [Stop event](/docs/xml/stream/stop-event) reference for the WebSocket stream lifecycle.
* **May 19** - `maxRetries` attribute on [`<Stream>`](/docs/xml/stream) controls reconnect attempts when the WebSocket fails to establish or drops mid-stream.
* **May 19** - [Conference attributes](/docs/xml/conference/attributes) and [conference callbacks](/docs/xml/conference/conference-callbacks) references.
* **May 20** - [Callback signature validation](/docs/concepts/validating-callbacks) reference for the `X-Vobiz-Signature`, `X-Vobiz-Signature-V2`, and `X-Vobiz-Signature-V3` headers.
* **May 25** - Sub-account KYC endpoints as interactive references: [status](/docs/sub-accounts/kyc/kyc-status), [PAN](/docs/sub-accounts/kyc/verify-pan), [GST](/docs/sub-accounts/kyc/verify-gst), CIN [search](/docs/sub-accounts/kyc/cin-search) and [confirm](/docs/sub-accounts/kyc/cin-confirm), DigiLocker [initiate](/docs/sub-accounts/kyc/digilocker-initiate) and [verify](/docs/sub-accounts/kyc/digilocker-verify), and the [hosted session](/docs/sub-accounts/kyc/kyc-session).
* **May 25** - [KYC test mode](/docs/sub-accounts/kyc/test-mode) endpoints for exercising verification outcomes without live checks.
* **May 25** - DID [assign](/docs/account-phone-number/assign-subaccount) and [unassign](/docs/account-phone-number/unassign-subaccount) to a sub-account, including the 15-day cool-off that applies to unassignment.
* **May 25** - [3CX integration guide](/docs/integrations/3cx).
* **May 27** - [Sub-account onboarding flow](/docs/sub-accounts/onboarding-flow) walking create, KYC, number, and first call, with parent versus sub-account authentication.
* **May 27** - `kyc_mode` on [create](/docs/sub-accounts/create-subaccount) and [update](/docs/sub-accounts/update-subaccount) sub-account.

### Changed

* **May 18** - API reference paths and base URLs aligned with the production routes, so requests from the playground reach the live API.
* **May 27** - Sub-account KYC endpoints authenticate with `X-Auth-ID` and `X-Auth-Token`, the primary credential pair for an account.
* **May 27** - `18.96.230.208/29` and `18.96.232.168/29` apply to RTP media rather than SIP signaling. See [IP whitelisting](/docs/concepts/ip-whitelisting).

## API status

For live availability and incident history, check [status.vobiz.ai](https://status.vobiz.ai).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.