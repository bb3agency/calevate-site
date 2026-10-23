"use client";

import { use } from "react";

import { GoLiveGuide } from "./GoLiveGuide";

/** "Go live", the owner's guide after the first payment (D-859). The route stays thin (D-196);
 *  the screen is beside it. */
export default function GoLivePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  return <GoLiveGuide slug={slug} />;
}
