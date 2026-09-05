import type { Metadata } from "next";
import localFont from "next/font/local";

import "./globals.css";

const ppMori = localFont({
  src: [
    {
      path: "../fonts/PPMori-Extralight.otf",
      weight: "200",
      style: "normal",
    },
    {
      path: "../fonts/PPMori-ExtralightItalic.otf",
      weight: "200",
      style: "italic",
    },
    {
      path: "../fonts/PPMori-Regular.otf",
      weight: "400",
      style: "normal",
    },
    {
      path: "../fonts/PPMori-RegularItalic.otf",
      weight: "400",
      style: "italic",
    },
    {
      path: "../fonts/PPMori-SemiBold.otf",
      weight: "600",
      style: "normal",
    },
    {
      path: "../fonts/PPMori-SemiBoldItalic.otf",
      weight: "600",
      style: "italic",
    },
  ],
  variable: "--font-pp-mori",
});

// JetBrains Mono for keys, IDs, codes and any fixed-width value an operator reads or
// pastes. Chosen over the system monospace stack because it disambiguates the glyphs
// those values collide on — a dotted zero distinct from O, and 1/l/I all distinct — so
// a mistyped or misread API key is caught by the eye, not by a failed call later.
// Self-hosted (SIL OFL 1.1, JetBrainsMono-OFL.txt) like PP Mori: no CDN, no CSP egress.
// Only the two weights the UI uses are bundled — Regular for values, Medium for the rare
// emphasised token — keeping the payload to ~180KB.
const jetbrainsMono = localFont({
  src: [
    {
      path: "../fonts/JetBrainsMono-Regular.woff2",
      weight: "400",
      style: "normal",
    },
    {
      path: "../fonts/JetBrainsMono-Medium.woff2",
      weight: "500",
      style: "normal",
    },
  ],
  variable: "--font-jetbrains-mono",
});

export const metadata: Metadata = {
  title: "Calevate",
  description: "AI phone agents for Indian businesses",
};

/**
 * EVERY PAGE RENDERS PER REQUEST, AND THE CSP IS THE ONLY REASON.
 *
 * `middleware.ts` mints a fresh nonce per request and `script-src` names it with no
 * `'unsafe-inline'` beside it. Under CSP3 a nonce SUPPRESSES `'self'` for inline scripts,
 * and Next emits its RSC payload as bare inline `<script>self.__next_f.push(...)` tags —
 * so the nonce has to reach the HTML or none of them run. Next can only stamp it while
 * RENDERING A REQUEST; a statically prerendered route is built once, before any nonce
 * exists, and ships those scripts bare.
 *
 * That combination served a BLANK WHITE SCREEN in production: the document and the
 * external `/_next/static` bundles loaded (both allowed by `'self'`), every inline script
 * carrying the hydration data was refused, and React had nothing to mount. It was
 * invisible until the policy went enforcing (D-541), because report-only reports and
 * then permits.
 *
 * The cost is real and accepted deliberately: the marketing pages were static and are now
 * rendered per request. The alternatives were worse — dropping the nonce for
 * `'unsafe-inline'` gives up exactly the XSS protection the policy exists for, and adding
 * `'unsafe-inline'` ALONGSIDE the nonce fixes nothing, because a nonce-capable browser
 * ignores it. Next's own guidance is that nonce-based CSP requires dynamic rendering.
 */
export const dynamic = "force-dynamic";

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${ppMori.variable} ${jetbrainsMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        {children}
      </body>
    </html>
  );
}
