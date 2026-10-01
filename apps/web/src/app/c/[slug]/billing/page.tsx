"use client";

import { use } from "react";

import { BillingScreen } from "./BillingScreen";

/** Credits & billing (D-525). The screen lives in `BillingScreen` (UX-DOCTRINE §6). */
export default function BillingPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  return <BillingScreen slug={slug} />;
}
