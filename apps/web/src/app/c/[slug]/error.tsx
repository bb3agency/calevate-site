"use client";

/**
 * A crash inside a CLIENT console, with the console still around it.
 *
 * Under `app/c/[slug]/layout.tsx`, so the shell — sidebar, header, the attention bell, the
 * "viewing as" banner — survives and only the screen is replaced. The exit is this
 * account's own dashboard, which is the difference this file exists for: the next boundary
 * up is `app/error.tsx`, and its best offer is the marketing homepage. An owner whose leads
 * table threw should not be shown our sales page.
 *
 * The slug comes from the path rather than from `useParams()` because the path is what the
 * exit is built from anyway, and it is VALIDATED rather than escaped before it reaches an
 * `href`: it arrived from the address bar, and the alternative — `encodeURIComponent` over
 * a segment that is already percent-encoded — either double-encodes a legitimate slug or
 * throws on a malformed sequence. A tenant slug is `[a-z0-9-]`, so anything else is not a
 * slug and the fallback is the junction that resolves one.
 */

import { useEffect } from "react";

import { usePathname } from "next/navigation";

import { FailureScreen } from "@/components/failureScreen";

export default function ClientRealmError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const pathname = usePathname();
  const slug = /^\/c\/([a-z0-9-]+)(?:\/|$)/i.exec(pathname ?? "")?.[1];
  // `/c` resolves a signed-in user's own console, so it is the honest fallback when the
  // path is not the shape we expect rather than a guessed URL.
  const dashboard = slug ? `/c/${slug}` : "/c";

  useEffect(() => {
    console.error("[calevate] uncaught render error in the client realm", {
      digest: error.digest,
      name: error.name,
      message: error.message,
    });
  }, [error]);

  return (
    <FailureScreen
      heading="This screen stopped."
      error={error}
      reset={reset}
      exits={[{ href: dashboard, label: "Back to your dashboard" }]}
    />
  );
}
