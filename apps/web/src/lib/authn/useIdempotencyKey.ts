"use client";

/**
 * An idempotency key that is stable for one logical request and fresh for the next (D-174).
 *
 * §5.6 requires these on the reset forms "from the first commit", and the reason is
 * concrete: a double-submitted reset REQUEST must not send two emails, and a
 * double-submitted reset CONFIRM must not spend two tokens.
 *
 * ## The semantics, which are the whole design
 *
 * The server's contract (`apps/api/reliability/service.py`) is that the same key with the
 * same body replays the first answer, and the same key with a DIFFERENT body is a 409
 * `idempotency_key_reused`. So a key must be:
 *
 *  - **stable across retries of the same request** — a mistyped-password retry, a
 *    double-click, a "try again" after a dropped connection — or the guarantee is nothing;
 *  - **fresh when the request changes** — a person who corrects their email address and
 *    submits again is making a new request, and reusing the key would 409 them.
 *
 * Keying on a SIGNATURE of the inputs gives both by construction, and it needs no
 * bookkeeping at the call site: there is no "reset the key" call to forget on the one
 * branch that needed it.
 *
 * ## Why the signature is hashed to a UUID rather than sent as itself
 *
 * The signature is the email address and, on the confirm form, the reset token — and
 * `Idempotency-Key` is a header that lands in the API's access logs and in its idempotency
 * table. Hard rule 6 says never log an address; §4 of `reliability/service.py` says raw
 * ids are never stored there. So the signature never leaves the browser: it only decides
 * WHEN to mint a new random v4 UUID, and the UUID is what goes on the wire. A key that
 * carried the address would be a PII leak wearing a correctness feature.
 */

import { useRef } from "react";

/** `crypto.randomUUID` where it exists — every browser this app supports, and jsdom. */
function newKey(): string {
  const cryptoApi = globalThis.crypto;
  if (typeof cryptoApi?.randomUUID === "function") return cryptoApi.randomUUID();
  // A build without it would otherwise send no key at all, silently dropping the
  // guarantee. Random enough to be unique per form instance, and never a credential.
  return `k-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

/**
 * @param signature - anything that identifies THIS request. Changing it mints a new key.
 */
export function useIdempotencyKey(signature: string): string {
  const held = useRef<{ signature: string; key: string } | null>(null);
  if (held.current === null || held.current.signature !== signature) {
    held.current = { signature, key: newKey() };
  }
  return held.current.key;
}
