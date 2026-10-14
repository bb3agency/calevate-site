"use client";

/**
 * "Stay signed in" on the operator's own account page (D-766).
 *
 * The switch reads the SERVER's answer for this session (`SessionOut.stay_signed_in`) and
 * writes through `setAdminStaySignedIn`, which raises the step-up prompt when switching on
 * finds the second factor stale. On success the returned `SessionOut` is adopted as this
 * realm's session row, so the idle warning moves to the new bound at once rather than on
 * the next restore.
 */
import { useState } from "react";

import { idleDurationLabel } from "@/components/authn/adminIdleTimeoutModal";
import { AuthProblemNotice } from "@/components/authn/fields";
import { ToggleSwitch } from "@/components/ui";
import { setAdminStaySignedIn } from "@/lib/authn/adminAuthn";
import type { AuthnSession } from "@/lib/authn/realm";

/**
 * How long a session with the switch on may live — `STAY_SIGNED_IN_TIMEOUTS.absolute` in
 * `apps/api/authn/sessions.py`. A copy of a server number, so it is pinned:
 * `tests/stay_signed_in_mirror_test.py` reads this literal and compares it.
 */
export const STAY_SIGNED_IN_DAYS = 14;

/**
 * The account page's one line about session length, for the bounds THIS session has. The
 * idle bound is the server's (`idle_timeout_seconds`); `null` is the signed-out page.
 */
export function sessionLifetime(session: AuthnSession | null): string {
  const idle = session ? idleDurationLabel(session.idle_timeout_seconds) : "30 minutes";
  return session?.stay_signed_in
    ? `"Stay signed in" is on: a session ends after ${idle} without activity, and after ${STAY_SIGNED_IN_DAYS} days regardless. You are warned a few minutes before an idle session ends.`
    : `A session ends after ${idle} without activity, and after 8 hours regardless. You are warned a few minutes before an idle session ends.`;
}

export function StaySignedInRow({
  session,
  adopt,
}: {
  session: AuthnSession;
  /** Make the server's answer this realm's session row. */
  adopt: (session: AuthnSession) => void;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const change = (next: boolean) => {
    setSaving(true);
    setError(null);
    void setAdminStaySignedIn(next)
      .then(adopt)
      .catch((failure: unknown) => setError(failure))
      .finally(() => setSaving(false));
  };

  return (
    <div className="space-y-3 py-3.5">
      <ToggleSwitch
        label={`Stay signed in on this device for up to ${STAY_SIGNED_IN_DAYS} days`}
        hint="Less secure on a shared device: anyone who opens this browser can use your operator account until you sign out."
        checked={session.stay_signed_in}
        disabled={saving}
        onChange={change}
      />
      <AuthProblemNotice error={error} />
    </div>
  );
}
