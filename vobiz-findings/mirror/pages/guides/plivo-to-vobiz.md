> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Migrate from Plivo to Vobiz

> Move your voice app from Plivo to Vobiz in hours, not weeks. The APIs, SDKs, and XML are near 1:1 - most apps migrate by swapping credentials, the base URL, and one XML verb name.

Vobiz is designed to be a near drop-in replacement for Plivo. You keep the same Auth ID/Token model, the same `/Account/{auth_id}/Call/` paths, near-identical SDK call parameters, and VobizXML maps almost line-for-line to PlivoXML. The SDK client and method names differ - Plivo's `calls.create(...)` becomes Vobiz's `calls.make_call(...)` (Python) / `calls.makeCall(...)` (Node) and takes an explicit `auth_id` - but the call parameters (`from`, `to`, `answer_url`, ...) carry over. Most apps migrate by swapping credentials, the base URL, the SDK client/method names, and one XML verb name.

## Why migration is fast

Plivo and Vobiz share the same core design, so you rarely rewrite logic - you re-point it.

<Steps>
  <Step title="Same auth model">
    Vobiz uses an Auth ID and Auth Token, just like Plivo. You swap the values and the env var names; the concept is identical.
  </Step>

  <Step title="Same API shape">
    Resource paths keep their casing and trailing slash - for example `/Account/{auth_id}/Call/`. You change the base host, not the route structure.
  </Step>

  <Step title="Familiar SDK surface">
    The call parameters carry over (`from`, `to`, `answer_url`, ...), but the method and client differ: `calls.create(...)` becomes `calls.make_call(...)` (Python) / `calls.makeCall(...)` (Node), the client is `Vobiz(api_key=, auth_token=)`, and methods take an explicit `auth_id`.
  </Step>

  <Step title="Same XML, one verb renamed">
    VobizXML mirrors PlivoXML. Most verbs are unchanged - the main edit is renaming `<GetDigits>`/`<GetInput>` to `<Gather>`.
  </Step>
</Steps>

## What changes vs what stays the same

| What changes | What stays the same |
| - | - |
| Client + method: `plivo.RestClient()` / `calls.create(...)` → `Vobiz(api_key=, auth_token=)` / `calls.make_call(...)` (+ explicit `auth_id`) | Call parameters: `from`, `to`, `answer_url`, `answer_method`, ... |
| Env vars: `PLIVO_AUTH_ID` / `PLIVO_AUTH_TOKEN` → `VOBIZ_AUTH_ID` / `VOBIZ_AUTH_TOKEN` | Bulk dial uses the same `<` separator in the `to` field |
| Raw-HTTP auth: `X-Plivo-Auth` basic auth → `X-Auth-ID` + `X-Auth-Token` headers | Machine-detection (AMD) parameters carry over |
| Base URL: `api.plivo.com/v1` → `api.vobiz.ai/api/v1` | All other XML verbs: `<Speak>`, `<Play>`, `<Dial>`, `<Number>`, `<User>`, `<Record>`, `<Conference>`, `<Redirect>`, `<Hangup>`, `<Wait>`, `<PreAnswer>` |
| XML verb: `<GetDigits>` / `<GetInput>` → `<Gather>` (attrs `type` → `inputType`, `timeout` → `executionTimeout`) | Path casing and trailing slash - e.g. `/Account/{auth_id}/Call/` |
| Webhook signature header: `X-Plivo-Signature-V3` → `X-Vobiz-Signature-V2` / `X-Vobiz-Signature-V3` | The signature scheme itself: HMAC-SHA256 plus a nonce |
| SIP domain: `sip.plivo.com` → `app.vobiz.ai` | |

<Tip>
  If you mostly use `calls.create` (→ `calls.make_call`/`makeCall`), `<Speak>`, `<Play>`, and `<Dial>`, your migration is mostly a credentials-and-base-URL change, swapping the client/method names, and a single find-and-replace on the input-gathering verb.
</Tip>

## Migration guide

Work through these pages in order, or jump to whichever part of your stack you are migrating.

<Columns cols={2}>
  <Card title="Auth and base URL" icon="key" href="/docs/guides/plivo-to-vobiz/auth-and-base-url">
    Swap credentials, env vars, raw-HTTP headers, and the API host.
  </Card>

  <Card title="Endpoint mapping" icon="route" href="/docs/guides/plivo-to-vobiz/endpoint-mapping">
    Plivo-to-Vobiz reference for every API path and parameter.
  </Card>

  <Card title="XML migration" icon="code" href="/docs/guides/plivo-to-vobiz/xml-migration">
    Map PlivoXML verbs to VobizXML, including the `<Gather>` rename.
  </Card>

  <Card title="Webhooks and signatures" icon="shield-check" href="/docs/guides/plivo-to-vobiz/webhooks-and-signatures">
    Update callback handling and verify the new signature header.
  </Card>

  <Card title="Gotchas" icon="triangle-exclamation" href="/docs/guides/plivo-to-vobiz/gotchas">
    Edge cases and differences to watch for during migration.
  </Card>

  <Card title="Number porting" icon="phone-arrow-right" href="/docs/guides/plivo-to-vobiz/number-porting">
    Bring your existing numbers over to Vobiz.
  </Card>

  <Card title="Cutover checklist" icon="list-check" href="/docs/guides/plivo-to-vobiz/cutover-checklist">
    Final pre-launch checks before flipping traffic to Vobiz.
  </Card>
</Columns>

## Tools and comparison

<Columns cols={2}>
  <Card title="Vobiz vs Plivo" icon="scale-balanced" href="/docs/compare/vobiz-vs-plivo">
    Compare the two platforms feature by feature.
  </Card>
</Columns>

<Note>
  A drop-in compatibility shim is planned. We are building a separate package - `vobiz-plivo-compat` for Python and `@vobiz/plivo-compat` for Node - that will let existing Plivo code run on Vobiz with a single import change. It is not available yet; this guide covers the manual migration path you can use today.
</Note>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.