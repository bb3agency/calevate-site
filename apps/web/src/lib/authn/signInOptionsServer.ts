import { unstable_cache } from "next/cache";

import { readSignInOptions, type SignInOptions } from "@/lib/authn/clientAuthn";

/**
 * `GET /v1/auth/client/sign-in-options`, read while the server renders a sign-in page, so
 * "Continue with Google" and the signup form are on the first paint instead of appearing
 * after the browser has asked (founder, 24 Oct 2026: the button arrived late and pushed
 * the form down).
 *
 * Imported by layouts only, never by a client component. Through the authn transport like
 * the browser's read (one door to the API), with Next's data cache in front: a deployment
 * switch changes with an operator's console write, not per request, so one answer serves
 * five minutes of page views. A failure is not cached, and it never holds the page up for
 * long: after 1.5 s the layout passes `null` and the page asks from the browser as before.
 */

const REVALIDATE_S = 300;
const DEADLINE_MS = 1500;

const cachedRead = unstable_cache(
  () => readSignInOptions(AbortSignal.timeout(DEADLINE_MS)),
  ["authn-client-sign-in-options"],
  { revalidate: REVALIDATE_S },
);

export async function readSignInOptionsOnServer(): Promise<SignInOptions | null> {
  try {
    const options = await cachedRead();
    return typeof options?.google === "boolean" && typeof options.self_serve_signup === "boolean"
      ? { google: options.google, self_serve_signup: options.self_serve_signup }
      : null;
  } catch {
    return null;
  }
}
