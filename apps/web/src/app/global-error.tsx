"use client";

/**
 * THE LAST BOUNDARY: a throw in the ROOT LAYOUT, where nothing of the app is left standing.
 *
 * `app/error.tsx` is a boundary around the root layout's CHILDREN, so it cannot catch the
 * root layout itself failing — the boundary would have to render inside the thing that
 * threw. `global-error.tsx` is Next's answer: it REPLACES the root layout, which is why it
 * must render its own `<html>` and `<body>`. Verified against the framework we ship rather
 * than from memory: `next@15.5.21`, `dist/client/components/builtin/global-error.js`, whose
 * own default does exactly that (`'use client'`, then `<html id="__next_error__">` with a
 * `<head>` and a `<body>`), and which is the screen this file exists to replace.
 *
 * Two consequences that shape everything below, and both are easy to get wrong:
 *
 * 1. **The root layout's `<html>` className is gone**, and with it the font variables and
 *    the theme class. So the page re-stamps the theme itself (the same inline script the
 *    root layout runs, from the same module — one source, so the two cannot disagree) and
 *    names an explicit fallback font stack, because `--font-pp-mori` is no longer defined.
 * 2. **The stylesheet may or may not have loaded.** On a client-side throw it is already in
 *    the document; on a root-layout failure during SSR it may not be. So the essential
 *    colours are ALSO written as inline styles off the same custom properties, with literal
 *    fallbacks — `var(--app, #fafafa)`. A last-resort screen that renders black text on a
 *    black background because a stylesheet 404'd is not a last resort.
 *
 * In development Next's error overlay takes over and this is not what you see; it is a
 * production surface, which is the other reason it carries its own belt and braces.
 */

import { useEffect } from "react";

import { FailureScreen } from "@/components/failureScreen";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[calevate] uncaught error in the root layout", {
      digest: error.digest,
      name: error.name,
      message: error.message,
    });
  }, [error]);

  return (
    <html lang="en">
      <body
        className="min-h-full antialiased"
        style={{
          background: "var(--app, #fafafa)",
          color: "var(--text, #171a1c)",
          fontFamily:
            "var(--font-pp-mori), ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
        }}
      >
        <div className="flex min-h-screen flex-col justify-center">
          <FailureScreen
            heading="Calevate could not finish loading."
            error={error}
            reset={reset}
            exits={[{ href: "/", label: "Go to the homepage" }]}
          />
        </div>
      </body>
    </html>
  );
}
