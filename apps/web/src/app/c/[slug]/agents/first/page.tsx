"use client";

import { use } from "react";

import { MeetYourAgent } from "./MeetYourAgent";

/** "Meet your agent", a new owner's first run (D-855). The route stays thin (D-196); the
 *  screen is beside it. */
export default function FirstAgentPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  return <MeetYourAgent slug={slug} />;
}
