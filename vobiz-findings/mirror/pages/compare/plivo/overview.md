> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Plivo vs Vobiz - full comparison

> The complete, domain-by-domain Plivo to Vobiz migration reference: voice call API, call-control XML, phone numbers, SIP trunking, conferences, recordings, sub-accounts, webhooks, SDKs, and pricing/compliance - each with a Plivo/Vobiz mapping and a migration-effort rating.

Vobiz is a near drop-in for Plivo - same `/Account/{auth_id}/...` REST shape, same `<Response>` XML verbs, same seven SDK languages. Most of a migration is mechanical (swap host `api.plivo.com/v1` → `api.vobiz.ai/api/v1`, swap HTTP Basic auth for `X-Auth-ID` + `X-Auth-Token` headers, adjust a few SDK method names); the matrix below maps each domain and rates the effort.

## At-a-glance matrix

| Domain | Plivo | Vobiz | Migration effort |
| :- | :- | :- | :-: |
| [Voice Call API](/docs/compare/plivo/voice-call-api) | `calls.*` for create + all in-call control; live transfer and queued-call cancel REST endpoints | Same `Call/` paths; in-call actions split into `play_audio`/`speak_text`/`dtmf`/`record_calls`, in-progress on `live_calls`; explicit `auth_id`; `answer_method` required | Medium |
| [Call-control XML](/docs/compare/plivo/call-control-xml) | PlivoXML verbs; `<GetDigits>` + `<GetInput>`; `<MultiPartyCall>`, `<Message>` | Near drop-in VobizXML; both input verbs → `<Gather>` (`executionTimeout`, never `timeout`) | Low |
| [Phone numbers](/docs/compare/plivo/phone-numbers) | `PhoneNumber` (search carrier catalog) + `Number`; single `update`; manual port-in | Single `phone_numbers` over a pre-provisioned **inventory**; per-action assign endpoints | High |
| [SIP trunking](/docs/compare/plivo/sip-trunking) | Zentrunk REST under `/Zentrunk/`; no SDK resources (cURL/console); per-trunk auth binding | First-class `trunks`/`credentials`/`ip-acl`/`origination-uri` in all SDKs; account-scoped auth; `PUT` updates; priority/weight failover | Medium |
| [Conferences](/docs/compare/plivo/conferences) | `<Conference>` + `conferences.*` member ops; `maxMembers`; rich per-member flags | Same XML verb; `maxParticipants`; member ops split across `conference`/`conference_members`/`conference_recording` | Low |
| [Recordings](/docs/compare/plivo/recordings) | `Record` XML, in-call `Record/`, `Recording/` list/get/delete, transcription | Same surfaces; `record_calls` + `conference_recording` namespaces; transcription via webhook; `timeout` default differs (60s vs 15s) | Low |
| [Sub-accounts](/docs/compare/plivo/sub-accounts) | Flat `Subaccount` (name + enabled); reassign DIDs freely; `cascade` delete | Same CRUD plus `kyc_mode` (`customer_use` India KYC), `kyc_calls_blocked`, **15-day DID cool-off**; hosted KYC sessions | High |
| [Webhooks](/docs/compare/plivo/webhooks) | `answer_url`/`ring_url`/`hangup_url`; `X-Plivo-Signature-V3` (hashes URL + sorted params); SDK validator | `Ring`/`StartApp`/`Hangup` events to the answer flow; `X-Vobiz-Signature-V2`/`V3` (hash base URL + nonce only) | Medium |
| [SDKs](/docs/compare/plivo/sdks) | 7 languages from package registries; `RestClient`; CRUD method names | Same 7 languages **git-cloned** from `vobiz-ai/*`; `Vobiz`/`VobizClient` header auth; verb-named methods; explicit `auth_id`; bundled `vobizxml` | Medium |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.