"use client";

/**
 * "Email me a reset link" — the form whose whole design is that it tells you nothing.
 *
 * D-174, §5.6. The API answers **202 with an empty body, always**
 * (`apps/api/authn/routes.py`), for a known address, an unknown one and a deleted account
 * alike, and `tests/authn_enumeration_test.py` measures the timing equalisation as well as
 * the body. This screen is the other half of that: it renders ONE confirmation, and the
 * confirmation is worded so that it is true in every case.
 *
 * "If that address has an account, a link is on its way" is the standard wording and it is
 * used here for the standard reason — it is the only sentence that is honest without being
 * an oracle. A screen that said "check your inbox" would be claiming an account exists,
 * which is exactly the §5.7 defect 2 leak reappearing on the reset path instead of the
 * sign-in path.
 *
 * The `Idempotency-Key` is §5.6's requirement and it is here from the first commit. See
 * `lib/authn/useIdempotencyKey.ts` for why it is keyed on the address rather than minted
 * per submit, and why the address itself never goes on the wire in the header.
 */

import { useState, type FormEvent } from "react";

import { useMutation } from "@tanstack/react-query";
import { MailCheck, Send } from "lucide-react";

import { AuthField, AuthProblemNotice } from "@/components/authn/fields";
import { Card, NoticeBox, PRIMARY_BUTTON } from "@/components/ui";
import type { RealmAuthn } from "@/lib/authn/realm";
import { useIdempotencyKey } from "@/lib/authn/useIdempotencyKey";

export function ResetRequestForm({ authn }: { authn: RealmAuthn }) {
  const [email, setEmail] = useState("");
  const address = email.trim().toLowerCase();
  const idempotencyKey = useIdempotencyKey(`reset-request:${authn.realm}:${address}`);

  const request = useMutation({
    mutationFn: () => authn.requestPasswordReset(address, idempotencyKey),
  });

  if (request.isSuccess) {
    return (
      <Card>
        <div className="space-y-3 text-sm text-ink-muted">
          <NoticeBox
            tone="ok"
            icon={<MailCheck aria-hidden className="h-4 w-4" />}
            title="If that address has an account, a link is on its way"
          >
            {/* Deliberately not "check your inbox for an email from us" — see the file
                docstring. The sentence must be true whether or not the account exists. */}
            <p className="mt-1">
              We do not say whether an account exists for an address, so this is the same
              answer either way. Nothing else has changed about the account.
            </p>
          </NoticeBox>
          <p>
            The link works once and expires an hour after it is sent. Using it ends every
            session on the account, on every device.
          </p>
          <p className="text-xs text-ink-faint">
            No email after a few minutes? Check the spam folder, then try a different
            address — it is more often the wrong address than a lost email.
          </p>
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <form
        className="space-y-4"
        noValidate
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          // The client half of the idempotency guarantee, and today the working half —
          // `/v1/auth/**` does not yet consume the header (see `transport.ts`). One
          // in-flight submit per form means a double-click and a double Enter cannot each
          // send a mail.
          if (request.isPending) return;
          request.mutate();
        }}
      >
        <AuthField
          label="Email address"
          type="email"
          autoComplete="username"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          hint="The address you sign in with."
        />

        <AuthProblemNotice error={request.error} />

        <button
          type="submit"
          className={PRIMARY_BUTTON}
          disabled={request.isPending || address === ""}
        >
          <Send aria-hidden className="h-4 w-4" />
          {request.isPending ? "Sending…" : "Email me a reset link"}
        </button>
      </form>
    </Card>
  );
}
