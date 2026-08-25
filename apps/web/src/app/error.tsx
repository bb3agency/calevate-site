"use client";

/**
 * THE ROOT ERROR BOUNDARY — the app had none, on any of its 71 routes.
 *
 * Until this file existed, any uncaught throw during render took the whole tree down to
 * Next's built-in screen: *"Application error: a client-side exception has occurred"*, on a
 * blank page, with no recovery control, no support reference, no realm and no way back.
 * (Verified against the framework we actually ship: `next@15.5.21`,
 * `dist/client/components/builtin/global-error.js` — that sentence is the literal default.)
 *
 * ## What each boundary catches, and why there are four of them
 *
 * `error.tsx` is a React error boundary Next wraps around a segment's CHILDREN. It cannot
 * catch a throw from the layout at its own level, because that layout is its parent —
 * which is exactly why the set is:
 *
 *   - `app/error.tsx`            (this file) — everything under the root layout: the
 *                                marketing home, `/signup`, `/invite`, `/legal`, `(auth)`.
 *   - `app/global-error.tsx`     — a throw in the ROOT LAYOUT itself. It replaces the root
 *                                layout, so it must render its own `<html>`/`<body>`.
 *   - `app/admin/error.tsx`      — a crash inside the operator console, KEEPING the shell.
 *   - `app/c/[slug]/error.tsx`   — the same for a client console.
 *
 * The two realm boundaries are not decoration: without them a crash on one screen of a
 * signed-in console unmounts the sidebar and the header too, and the user's only exit is
 * whatever this file offers — which is the marketing homepage. A person who was reading a
 * lead should land back in their console, not on our sales page. That is the same
 * reasoning `app/c/page.tsx` and `admin/sign-in/page.tsx` already record about signing in
 * being a dead end.
 *
 * Boundaries must be Client Components (`error-boundary.d.ts` in the installed framework:
 * the boundary is a `React.Component` with `getDerivedStateFromError`), hence `"use client"`
 * — which is also why the `reset` prop is typed exactly as the framework passes it.
 */

import { useEffect } from "react";

import { FailureScreen } from "@/components/failureScreen";

export default function RootError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  // THE OPERATOR'S HALF. CLAUDE.md: "every failure path a user can reach has a message they
  // can act on, and every failure path they cannot reach has a log line an operator can act
  // on." The user gets the sentence; this is the line — with the digest, which is the key
  // into the server log for a server-side throw, since Next strips the message in
  // production and leaves only that hash.
  useEffect(() => {
    console.error("[calevate] uncaught render error", {
      digest: error.digest,
      name: error.name,
      message: error.message,
    });
  }, [error]);

  return (
    <FailureScreen
      heading="Something went wrong on this page."
      error={error}
      reset={reset}
      exits={[
        { href: "/", label: "Go to the homepage" },
        { href: "/c", label: "Open your console" },
      ]}
    />
  );
}
