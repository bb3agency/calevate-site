"use client";

/**
 * A crash inside the OPERATOR console, with the console still around it.
 *
 * This boundary sits under `app/admin/layout.tsx`, so it replaces the failing SCREEN and
 * not the shell: the sidebar, the header and the "Cross-client · every action is audited"
 * marker all survive, and the operator's next click is a normal navigation rather than a
 * page reload. Without it the nearest boundary is `app/error.tsx`, whose exits are the
 * marketing homepage and the client console — the wrong realm for someone who was halfway
 * through a tenant's ledger.
 *
 * The realm split matters more here than in the client console, for the reason
 * `authPage.tsx` and the idle-timeout comments already give: the two realms' blast radii
 * differ by an order of magnitude, and a screen that offers "go to your console" to an
 * operator is offering the wrong door.
 */

import { useEffect } from "react";

import { FailureScreen } from "@/components/failureScreen";

export default function AdminError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[calevate] uncaught render error in the admin realm", {
      digest: error.digest,
      name: error.name,
      message: error.message,
    });
  }, [error]);

  return (
    <FailureScreen
      heading="This operator screen stopped."
      error={error}
      reset={reset}
      exits={[{ href: "/admin", label: "Back to clients" }]}
    />
  );
}
