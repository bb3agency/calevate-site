/**
 * The self-serve signup settings the public site reads at build time. No "use client"
 * directive: the home page renders on the server, where a constant read from a client
 * module is a client reference rather than its value.
 */

/**
 * Does THIS deployment open accounts online? Answered at build time, on purpose.
 *
 * The symptom this fixes: the signup surface had no way to learn it was closed, so a
 * deployment with `SELF_SERVE_SIGNUP_ENABLED=false` — the DEFAULT, and therefore the
 * usual state — rendered a full form, took a business through five fields, and only
 * then answered "closed". Every submission on such a deployment is refused; a form
 * that cannot succeed is a worse answer than no form at all.
 *
 * **Unset means CLOSED.** The API's `SELF_SERVE_SIGNUP_ENABLED` defaults false for the
 * R-11 compliance reason, and a mirror that defaults the other way would advertise an
 * open door on every deployment that forgot to set it. Only the exact string "true"
 * opens it, so a stray "false"/"0"/"" cannot read as open.
 *
 * **It is a HINT, never the authority.** The server re-decides on every request and is
 * the only thing that can; this flag can only be stale (a build shipped before the env
 * changed, or `next build` inlining a value that later flipped). So the runtime
 * refusals below stay wired up: if this says open and the server says closed, the
 * client still gets the honest "closed" panel, from the refusal instead of the config.
 * The reverse — this says closed while the server is open — costs a business nothing
 * they can see, and is corrected by a rebuild.
 *
 * **THE REPLACEMENT.** This exists only because no endpoint exposes the switch. The
 * moment the API grows an unauthenticated `GET /v1/auth/signup/availability` (or an
 * `available: bool` on some public config document) returning whether signup is open
 * and what to do when it is not, delete this constant and read that instead: it is one
 * query, it needs no rebuild to change, and it cannot be stale.
 */
export const SIGNUP_OPEN = process.env.NEXT_PUBLIC_SELF_SERVE_SIGNUP_ENABLED === "true";

/**
 * Who to talk to when the online door is shut. Optional: unset renders the sentence
 * without a link rather than inventing an address that would bounce.
 */
export const SIGNUP_CONTACT_EMAIL = process.env.NEXT_PUBLIC_SIGNUP_CONTACT_EMAIL ?? "";
