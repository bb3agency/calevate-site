"use client";

import { Suspense, use } from "react";

import { QaReviewScreen } from "./QaReviewScreen";

/**
 * Outside the tenant pages, so the screen prints its own back link and an `h2` title. The
 * boundary is for `useSearchParams`, which carries the queue's filters.
 */
export default function QaSampleReviewPage({
  params,
}: {
  params: Promise<{ sampleId: string }>;
}) {
  const { sampleId } = use(params);
  return (
    <Suspense fallback={null}>
      <QaReviewScreen sampleId={sampleId} />
    </Suspense>
  );
}
