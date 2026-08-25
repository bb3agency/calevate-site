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
