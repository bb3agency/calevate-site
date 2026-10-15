import { Suspense } from "react";

import { QaQueueScreen } from "./QaQueueScreen";

/**
 * No `<h1>`: the admin shell prints the nav label as the page title. The boundary is for
 * `useSearchParams`, which holds the queue's filters.
 */
export default function QaSamplingPage() {
  return (
    <Suspense fallback={null}>
      <QaQueueScreen />
    </Suspense>
  );
}
