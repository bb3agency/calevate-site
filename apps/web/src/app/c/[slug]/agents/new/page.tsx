"use client";

import { use } from "react";

import { BuildAgent } from "./BuildAgent";

/** Build an agent. The route module stays thin (D-196); the flow is `./BuildAgent.tsx`. */
export default function NewAgentPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  return (
    <div className="mx-auto max-w-2xl pb-12">
      <BuildAgent slug={slug} />
    </div>
  );
}
