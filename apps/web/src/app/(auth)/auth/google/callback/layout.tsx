import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = { title: "Signing you in — Calevate" };

// Metadata only: the page is a client component and cannot export it (see tests/a11y.ts).
export default function TitleLayout({ children }: { children: ReactNode }) {
  return children;
}
