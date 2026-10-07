> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Errors

> What each status means, and whether retrying will help.

| Status | Means | What to do |
| - | - | - |
| `400` | Malformed request, or a template blank is missing | Fix and resend. Retrying unchanged fails identically |
| `401` | Key missing, wrong or revoked | Check the header. **Do not retry** |
| `404` | No template of that name on your account | Check the name. Names are per account, so another business's template is invisible to you |
| `409` | Template not approved, WhatsApp not connected, contact opted out, or Meta has restricted the account | Look at **Templates** or **Channels**. Retrying makes a restriction worse |
| `409` | The same idempotency key is still in flight | Retry in a moment; the first request will have answered by then |
| `429` | Rate limited | Wait for `Retry-After` |
| `503` | WhatsApp is temporarily unavailable | Ours to fix, not yours. Safe to retry with the same idempotency key |

## On 409 in particular

<Warning>
  When Meta restricts an account, every refused request is a signal that the
  business has not noticed. **A retry loop against a restriction extends it.**

  The console shows the reason and when it lifts. Go and look rather than
  retrying.
</Warning>

`409` also covers the correct-behaviour cases: a **marketing** template
addressed to somebody who opted out is refused. That is not a bug to work
around.

## Retry policy that will not hurt you

```js theme={null}
const RETRYABLE = new Set([429, 500, 502, 503, 504]);

async function send(payload, key, attempt = 0) {
  const res = await post(payload, key);

  if (res.ok) return res.json();

  if (!RETRYABLE.has(res.status) || attempt >= 4) {
    // 400, 401, 404 and 409 never succeed on a retry. Surface them.
    throw new Error(`${res.status}: ${await res.text()}`);
  }

  const after = Number(res.headers.get("Retry-After") ?? 0);
  const backoff = after > 0 ? after * 1000 : 2 ** attempt * 1000;

  await sleep(backoff);
  // Same idempotency key on every attempt — that is what makes this safe.
  return send(payload, key, attempt + 1);
}
```

The important line is the last one: **the same idempotency key on every
attempt**. Generating a fresh key per retry turns a safe retry into a duplicate
message.

Keys are honoured for 24 hours, so a backoff that runs for minutes is well
inside the window. A job parked overnight and released the next morning is not —
it will send.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.