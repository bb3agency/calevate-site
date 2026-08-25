import type { Metadata } from "next";
import localFont from "next/font/local";

import { themeScriptSource } from "@/lib/theme";

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

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${ppMori.variable} ${jetbrainsMono.variable} h-full antialiased`}
      // The theme script below adds `.dark` and a `color-scheme` to THIS element before
      // React hydrates, so the server's markup and the browser's DOM legitimately differ
      // here. Without this, React 19 logs a hydration mismatch on every dark-mode page
      // load — a real warning about a deliberate act, which is the kind that trains people
      // to ignore the warning that matters. Scoped to `<html>`: it does not descend.
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col">
        {/*
         * THE NO-FLASH SCRIPT, and its position is the whole of why it works.
         *
         * It is the FIRST thing in `<body>`, so the browser executes it synchronously while
         * parsing, before any content of the page has been laid out or painted: the first
         * paint is already in the right theme. The alternative — applying the theme in an
         * effect after hydration — paints the light page first and repaints, which is the
         * white flash every half-done dark mode ships with, and it lands hardest on the
         * low-end Android the BRD names, where hydration is slowest.
         *
         * `dangerouslySetInnerHTML` with a STATIC source string (`lib/theme.ts`): nothing
         * user-, route- or environment-derived is interpolated into it, so the one hazard
         * of this API has no path in, and `tests/theme.test.ts` executes the exact bytes.
         */}
        <script dangerouslySetInnerHTML={{ __html: themeScriptSource() }} />
        {children}
      </body>
    </html>
  );
}
