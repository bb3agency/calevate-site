"use client";

import { use } from "react";

import { FirstAgentScreen } from "./FirstAgentScreen";

/** Build your first agent (D-854). The route stays thin (D-196); the screen is beside it. */
export default function FirstAgentPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  return <FirstAgentScreen slug={slug} />;
}
