"use client";

import { Lock } from "lucide-react";

import { Card, NoticeBox } from "@/components/ui";
import { ApiProblem } from "@/lib/api/client";

/**
 * A panel this admin session MAY NOT SEE — rendered in place of the panel, with the
 * reason, and having asked the API nothing.
 *
 * ## Why the panel is replaced rather than disabled
 *
 * The console's standing doctrine for a control the session cannot use is "shown and
 * dead, with the reason" (`admin/layout.tsx`, `RestrictionNote`), and that is right for
 * a BUTTON: the control is the whole of what is refused, and the surrounding facts are
 * still readable. It is the wrong shape for these panels, because on `/v1/ops/secrets`
 * and `/v1/ops/config` the READ carries the same permission as the write
 * (`permission_meta("platform:secrets")` / `("platform:config")` on the GET as well as
 * the PUT). A disabled form over a list nobody may read is a panel whose every request
 * is a 403 — so the panel would render its own "we could not read this" notice, which
 * is the sentence for an OUTAGE, over a refusal that is working exactly as designed.
 * That notice invites a retry, and its retry button is itself a control whose only
 * outcome is another 403.
 *
 * So this is the panel-sized version of the same doctrine: the heading stays, the
 * refusal is beside it in the operator's own words, and nothing is fetched. An operator
 * can still say "open Operations, the credentials panel is the third card" to another
 * operator and be describing the screen in front of both of them.
 *
 * ## What it must never do
 *
 * It states NOTHING about the subject it is standing in for. Not "no credentials are
 * installed", not a count, not a mask, not a "0 of 4 keys" — this component was handed
 * no data and asked for none, and a placeholder that reads as an inventory is worse than
 * an absent panel: an operator would act on it. `subject` is a sentence about what the
 * panel WOULD show, phrased in the conditional, and it is the caller's job to keep it
 * that way — "This panel would list…", never "there are none".
 */
export function WithheldPanel({
  title,
  reason,
  subject,
}: {
  title: string;
  /**
   * The refusal in the operator's words. `AdminAccess.reason` when the identity read
   * settled on a refusal; the API's own `detail` when the 403 arrived from the endpoint.
   * Either way it is somebody else's sentence, printed rather than paraphrased.
   */
  reason: string;
  /** What this panel would have shown, in the conditional. Never a claim about state. */
  subject: string;
}) {
  return (
    <Card title={title}>
      <NoticeBox
        tone="neutral"
        icon={<Lock aria-hidden className="h-5 w-5" />}
        title="Your admin account cannot see this"
      >
        <p className="mt-1">{reason}</p>
        <p className="mt-2">
          {subject} Nothing was read to fill it in, so nothing here says what is or is not
          in place.
        </p>
      </NoticeBox>
    </Card>
  );
}

/**
 * Did the SERVER refuse this read for want of a permission?
 *
 * 403 and only 403, read off the status rather than a code, for the reason
 * `isLostUpdate` reads 412 off the status: the code is a per-route string that a rename
 * would silently turn this branch off, and the status is the part of the contract the
 * API cannot move without breaking every client.
 *
 * It exists because `useAdminAccess` cannot answer for the window in which it is itself
 * unknown. While `/v1/admin/me` is in flight — and if it FAILED — every gate deliberately
 * fails open (`access.ts`), so a panel does get mounted for a session that may not read
 * it, fires its query, and is refused. Rendering that refusal as "we could not read this"
 * would be the outage sentence again, one race later.
 */
export function isForbidden(error: unknown): boolean {
  return error instanceof ApiProblem && error.status === 403;
}

/**
 * The server's own sentence for a refusal, or null when there is not one to print.
 *
 * `ApiProblem.message` is `detail ?? title` (`lib/api/client.ts`), i.e. the RFC-9457
 * body's own prose. Printed verbatim — a paraphrase of an authorization refusal is a
 * second opinion about what this session may do, and the API is the only authority on
 * that.
 */
export function forbiddenReason(error: unknown): string | null {
  if (!(error instanceof ApiProblem)) return null;
  const said = error.message.trim();
  return said.length > 0 ? said : null;
}
