"use client";

import { use } from "react";

import { QaReviewScreen } from "./QaReviewScreen";

/** Outside the tenant pages, so the screen prints its own back link and an `h2` title. */
export default function QaSampleReviewPage({
  params,
}: {
  params: Promise<{ sampleId: string }>;
}) {
  const { sampleId } = use(params);
  return <QaReviewScreen sampleId={sampleId} />;
}
