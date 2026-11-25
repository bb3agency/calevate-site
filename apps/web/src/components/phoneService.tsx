"use client";

/**
 * The strip above every client screen while the phone service is not answering.
 *
 * Driven by the platform's own health read (`GET /v1/phone-service`), not by the request a
 * screen happened to make, so every client sees the same thing at the same time and it goes
 * away by itself when the service answers. One line, and the rest behind "Details": the
 * owner needs to know their calls are paused and that nothing is needed from them.
 *
 * It names no provider (D-679): to a client this is "our phone service".
 */

import { useEffect, useId, useState } from "react";

import { NOTICE_DOT, SITE_STRIP, formatIST } from "@/components/ui";
import { ApiProblem } from "@/lib/api/client";
import {
  TEST_CALLS_PAUSED,
  isPhoneServiceDown,
  usePhoneService,
  usePhoneServiceDown,
  useRefreshPhoneService,
} from "@/lib/api/phoneService";
import { useClientRealm } from "@/lib/api/session";

/**
 * For a test-call button: whether to disable it now, and whether its last error was the
 * outage rather than a failure. A press that met the outage refreshes the shared read, so
 * the banner and every other test-call button switch at once instead of at the next poll.
 * Disabling reads only the live state, so the button comes back as soon as it answers even
 * though the old error is still on the mutation.
 */
export function useTestCallsPaused(error: unknown): { paused: boolean; errorIsPause: boolean } {
  const { session } = useClientRealm();
  const paused = usePhoneServiceDown(session);
  const refresh = useRefreshPhoneService();
  const errorIsPause = isPhoneServiceDown(error);
  const errorIsOutage =
    errorIsPause || (error instanceof ApiProblem && error.code === "engine_unreachable");
  useEffect(() => {
    if (errorIsOutage) refresh();
    // Once per error, not per render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [error]);
  return { paused, errorIsPause };
}

/** The reason beside a disabled test-call button. */
export function TestCallsPausedNote({ className = "mt-2" }: { className?: string }) {
  return (
    <p role="status" className={`${className} text-meta text-ink-muted`}>
      {TEST_CALLS_PAUSED}
    </p>
  );
}

export function PhoneServiceBanner() {
  const { session } = useClientRealm();
  const service = usePhoneService(session);
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  if (service.data?.state !== "not_answering") return null;
  return (
    <div role="status" className={SITE_STRIP}>
      <span aria-hidden className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${NOTICE_DOT.warn}`} />
      <div className="min-w-0 flex-1">
        <p>
          <span className="font-medium">Calls are paused: our phone service is not answering.</span>{" "}
          Your calls resume by themselves.{" "}
          <button
            type="button"
            aria-expanded={open}
            aria-controls={detailsId}
            onClick={() => setOpen((was) => !was)}
            className="font-medium text-ink underline underline-offset-2 hover:text-ink-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
          >
            {open ? "Hide details" : "Details"}
          </button>
        </p>
        <ul id={detailsId} hidden={!open} className="mt-1 list-disc space-y-0.5 pl-5 text-ink-muted">
          {service.data.since && <li>Since {formatIST(service.data.since)}.</li>}
          <li>Calls to your own numbers may not connect until it is back.</li>
          <li>Campaigns wait, then carry on where they stopped.</li>
          <li>Anything you save is kept and goes live by itself.</li>
          <li>Test calls come back when it answers.</li>
        </ul>
      </div>
    </div>
  );
}
