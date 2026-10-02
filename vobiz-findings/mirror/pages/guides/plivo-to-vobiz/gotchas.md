> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Gotchas & breaking changes

> The handful of real breaking changes when migrating from Plivo to Vobiz - XML verb renames, path casing, required status params, webhook signatures, SIP domains, and DID cool-off - plus one common false alarm.

Moving from Plivo to Vobiz is mostly drop-in: the same PascalCase REST paths, the same header-based auth, the same XML control flow, and the same HMAC webhook scheme. You can repoint most of your code at `https://api.vobiz.ai` and keep going.

But a handful of things genuinely bite. This page lists every real breaking change, each with the fix - and calls out one thing that looks like a change but isn't.

## XML verb rename: GetDigits/GetInput become Gather

<Warning>
  Plivo's `<GetDigits>` and `<GetInput>` verbs are renamed to a single `<Gather>` verb in VobizXML. Two attributes also rename: `type` becomes `inputType`, and `timeout` becomes `executionTimeout`.

  **Fix:** rename the verb to `<Gather>`, rename `type` to `inputType`, and rename `timeout` to `executionTimeout`. `<Gather>` uses `executionTimeout` and **never** `timeout` - if you leave a `timeout` attribute on `<Gather>` it is ignored. See [XML migration](/docs/guides/plivo-to-vobiz/xml-migration) for the full verb-by-verb mapping.
</Warning>

## Path casing and trailing slash

<Warning>
  Call endpoints are PascalCase with a trailing slash: `POST /api/v1/Account/{auth_id}/Call/`. Lowercasing any segment (`/account/.../call/`) or dropping the trailing slash returns **401**, not a helpful error.

  This is the same convention Plivo uses, so it usually survives a host swap untouched - but it's easy to break when you hand-edit a URL. **Fix:** keep `Account` and `Call` capitalized and keep the trailing slash; copy the exact path from the matching doc page when in doubt. See [Make a call](/docs/call/make-call).
</Warning>

## status is required on call-retrieve endpoints

<Warning>
  The `status` query param is **required** when you retrieve in-progress calls. Use `?status=live` for live calls or `?status=queued` for queued calls.

  **Fix:** always send `status`. Omitting it does not list live calls - it returns the finalized CDR or a **404**, which looks like the call vanished. See [Make a call](/docs/call/make-call).
</Warning>

## Webhook signature header swap

<Warning>
  The webhook signature header changes from `X-Plivo-Signature-V3` to `X-Vobiz-Signature-V2` / `X-Vobiz-Signature-V3`. The underlying scheme is identical - HMAC-SHA256 over the URL plus a nonce - so you only swap the header name and point your validator at the new header.

  **Fix:** read the signature from `X-Vobiz-Signature-V2`/`V3` and validate with the same HMAC-SHA256-plus-nonce logic you already have. See [Webhooks and signatures](/docs/guides/plivo-to-vobiz/webhooks-and-signatures).
</Warning>

## SIP domain change

<Warning>
  SIP URIs move off Plivo's domain. `sip.plivo.com` becomes `app.vobiz.ai` for applications and `<trunk>.sip.vobiz.ai` for trunks.

  **Fix:** update any hardcoded SIP URIs - in `to` parameters, dial targets, SIP endpoints, and device configs - to the Vobiz domains.
</Warning>

## DID 15-day cool-off

<Warning>
  Unassigning a recently used DID from a sub-account is subject to a 15-day cool-off. If the number had a call within the last 15 days, the unassign is rejected with **`409 did_cool_off_in_effect`** (the response includes `cool_off_until` and `cool_off_remaining_seconds`). A DID that was never used moves back immediately.

  **Fix:** wait out the cool-off, or have an admin override it with `?force=true` (this writes an audit record). See [Phone numbers](/docs/guides/plivo-to-vobiz/number-porting).
</Warning>

## Not a gotcha: bulk dial

<Note>
  **The bulk-dial separator did not change.** Both Plivo and Vobiz use the `<` separator to pass multiple destinations in the `to` parameter (for example `14157654321<14153464321`). There were never commas to "fix" - leave your `to` strings exactly as they are. Swapping `<` for `,` will break bulk dialing on Vobiz.
</Note>

## Next steps

<CardGroup cols={2}>
  <Card title="Cutover checklist" icon="list-checks" href="/docs/guides/plivo-to-vobiz/cutover-checklist">
    Run through the step-by-step checklist before you flip traffic to Vobiz.
  </Card>

  <Card title="Plivo to Vobiz overview" icon="arrow-right-left" href="/docs/guides/plivo-to-vobiz">
    Back to the full migration guide and verb-by-verb mappings.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.