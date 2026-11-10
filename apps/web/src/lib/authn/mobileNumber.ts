/**
 * The mobile number on a client user's own login (D-976): `POST /v1/auth/client/mobile-number`.
 *
 * No code is sent to the number yet, so the screen shows it back before saving and the
 * person checks it. That preview is computed here with the SAME rules the server applies
 * (`apps/api/ingest/service.normalize_phone`): ten digits starting 6-9 gain +91, a leading
 * 0 or 91 is folded, a number with + keeps its country, and anything else is refused. The
 * server still decides; if the two ever disagree, the refusal is shown and nothing is stored.
 */

import type { components } from "@/lib/api/schema";
import { CLIENT_ACCOUNT_PATH, clientAuthn } from "@/lib/authn/clientAuthn";

export type MobileNumberChange = components["schemas"]["MobileNumberOut"]["change"];

/** Where an owner adds the number: the row's anchor on Your account. */
export const MOBILE_NUMBER_ANCHOR = "mobile-number";
export const ADD_MOBILE_NUMBER_PATH = `${CLIENT_ACCOUNT_PATH}#${MOBILE_NUMBER_ANCHOR}`;

/** What the number is for, said once wherever the number is asked for. No provider names. */
export const MOBILE_NUMBER_USE = "For WhatsApp alerts and automatic top-ups.";

export { MOBILE_NUMBER_INVALID } from "./problems";

/** E.164 from what was typed, or null: the server's rules, from `lib/phoneNumber`. */
export { normalizePhone as normaliseMobileNumber } from "@/lib/phoneNumber";

/** Set (E.164) or remove (null) the caller's own number. Answers what changed. */
export async function setOwnMobileNumber(phone: string | null): Promise<MobileNumberChange> {
  const out = await clientAuthn.request<components["schemas"]["MobileNumberOut"]>(
    "/mobile-number",
    { method: "POST", body: { phone } },
  );
  return out.change;
}
