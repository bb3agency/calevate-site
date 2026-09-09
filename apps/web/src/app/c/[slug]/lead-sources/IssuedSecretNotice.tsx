"use client";

import { NOTICE_TONES, formatIST } from "@/components/ui";
import { API_BASE } from "@/lib/api/client";

import { CODE, QUIET_BUTTON } from "./styles";

export interface IssuedSecret {
  /** Null when the client supplied it themselves (Meta) — there is nothing to show. */
  secret: string | null;
  header: string;
  /** Only on creation: where to send leads. Null after a rotation, which changes
   *  nothing about the address. */
  path: string | null;
  /** Only after a rotation with a grace window: when the OLD secret stops working. */
  expiresAt: string | null;
}

/**
 * The one moment the plaintext is on screen.
 *
 * It says "copy it now" because that is literally true — no route returns it again —
 * and, after a rotation, it says when the old one stops working. A rotation banner
 * without that deadline is the dangerous version: a client who reads "rotated" as "the
 * old key is dead" will scramble, and one who reads it as "nothing changed" will never
 * update their form. The date is the only sentence that produces the right behaviour.
 */
export function IssuedSecretNotice({
  issued,
  onDismiss,
}: {
  issued: IssuedSecret;
  onDismiss: () => void;
}) {
  return (
    <div className={`mt-3 rounded-lg border p-3 text-sm ${NOTICE_TONES.warn}`}>
      {issued.secret ? (
        <>
          <p className="font-medium">Copy this secret now — we will not show it again.</p>
          <code className={`${CODE} mt-2 block`}>{issued.secret}</code>
          <p className="mt-2 text-xs">
            Send it in the <code className="font-mono">{issued.header}</code> header on
            every submission.
          </p>
        </>
      ) : (
        <p className="font-medium">
          Saved. We store your app secret and verify every notification against it —
          there is nothing new for you to copy.
        </p>
      )}
      {issued.path && (
        <p className="mt-2 text-xs">
          Send leads to <code className="font-mono">{`${API_BASE}${issued.path}`}</code>
        </p>
      )}
      {issued.expiresAt && (
        <p className="mt-2 text-xs">
          Your previous secret keeps working until {formatIST(issued.expiresAt)} — update
          your form before then and no lead is lost.
        </p>
      )}
      {issued.expiresAt === null && issued.path === null && (
        <p className="mt-2 text-xs">The previous secret stopped working immediately.</p>
      )}
      <button type="button" onClick={onDismiss} className={`${QUIET_BUTTON} mt-3`}>
        I&apos;ve saved it
      </button>
    </div>
  );
}
