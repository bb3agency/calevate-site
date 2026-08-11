"use client";

/**
 * Self-serve signup (D-34 motion 2, FLOWS §2 route 1).
 *
 * `POST /v1/auth/signup` is NOT an unauthenticated route, and that shapes this module.
 * The caller is a Clerk-verified user who has no organization YET — the same state the
 * invitation-accept route handles — so the request carries a client-realm token and no
 * org: the membership is what the call creates. `/v1/auth/` sits on the API's public
 * prefixes because no permission can gate a caller with no organization, which is a
 * statement about permissions, not about identity.
 *
 * Two failure modes are first-class rather than incidental, because both are the
 * normal state of the world rather than a bug:
 *
 *  - `signup_disabled` — the R-11 kill switch, which DEFAULTS OFF. Most deployments
 *    will refuse every signup, and a form that answers that with a red "something went
 *    wrong" would send a business to support to report an outage that isn't one.
 *  - `signup_load_shed` — the platform is in reduced/emergency/maintenance mode and is
 *    not creating accounts. Transient; "try again shortly" is the honest answer.
 *
 * There is no way to ask the API whether signup is open before submitting (no probe
 * endpoint), so the page discovers it from the refusal. That is a real gap, not a
 * design: it means a closed deployment still renders a full form first.
 */

import { useMutation } from "@tanstack/react-query";

import { ApiProblem, apiRequest, devSession, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type SignupIn = Schemas["SignupIn"];
export type SignupOut = Schemas["SignupOut"];
export type SignupLanguage = SignupIn["language"];

/**
 * The signup caller's session: a client-realm identity with an EMPTY org slug.
 *
 * Not a bug and not a placeholder — `current_identity` resolves the user from the
 * token alone and never looks at `X-Org-Slug`, precisely because this caller has no
 * organization to name. Passing a slug here would be inventing a tenant the caller is
 * not a member of.
 */
export function signupSession(): Session {
  return devSession("");
}

/** The four seeded verticals (`scripts/seed.py::VERTICAL_TEMPLATES`) — the API refuses
 * anything else with `unknown_vertical_template` rather than silently seating a
 * business on the clinic schema, so this list must stay a list and not a free text. */
export const SIGNUP_VERTICALS = [
  { value: "clinic", label: "Clinic or hospital" },
  { value: "real_estate", label: "Real estate" },
  { value: "insurance", label: "Insurance" },
  { value: "education", label: "Education" },
] as const;

export const SIGNUP_LANGUAGES: { value: SignupLanguage; label: string }[] = [
  { value: "te-IN", label: "Telugu" },
  { value: "hi-IN", label: "Hindi" },
  { value: "en-IN", label: "English (India)" },
];

/** Mirrors `admin_service.slugify` closely enough to PREVIEW the URL. The server
 * derives, validates, reserves and de-collides the real one — and the slug is
 * immutable once set, so this is a preview and never an authority. */
export function previewSlug(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 40);
}

/** Is this refusal the kill switch, rather than something the business did wrong? */
export function isSignupClosed(error: unknown): error is ApiProblem {
  return error instanceof ApiProblem && error.code === "signup_disabled";
}

/** Is this refusal load-shedding — the same "not now" with a different lifetime? */
export function isSignupDeferred(error: unknown): error is ApiProblem {
  return error instanceof ApiProblem && error.code === "signup_load_shed";
}

export function useSignup() {
  return useMutation({
    mutationFn: (payload: SignupIn) =>
      apiRequest<SignupOut>(signupSession(), "/v1/auth/signup", {
        method: "POST",
        body: payload,
      }),
  });
}
