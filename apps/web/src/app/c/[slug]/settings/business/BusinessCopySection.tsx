"use client";

import { AskAssistant } from "@/components/copilot/AskAssistant";
import { Section } from "@/components/console/section";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { formatIST } from "@/components/ui";
import { useBusinessCopy, type BusinessCopy } from "@/lib/api/businessCopy";
import type { Session } from "@/lib/api/client";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

/** What the owner asks Pip, in their own words, on "Refresh now". */
export const REFRESH_REQUEST = "Refresh my examples from my current business details.";

/**
 * YOUR EXAMPLES (D-827). The examples shown in empty fields across the dashboard, the
 * suggested script steps and the questions are written for this business from its details
 * and calls. This row says when they were last written and lets the owner ask Pip to write
 * them again; anything they typed is never changed, which the hint says because it is the
 * first thing an owner worries about.
 */
export function BusinessCopySection({ session, canWrite }: { session: Session; canWrite: boolean }) {
  const copy = useBusinessCopy(session);
  return (
    <Section title="Your examples">
      <SettingRows>
        <SettingRow
          label="Last refreshed"
          hint="Sample text for empty boxes. Yours never changes."
          value={<span aria-live="polite">{lastRefreshed(copy.data, copy.isPending, copy.isError)}</span>}
          control={
            <AskAssistant
              label="Refresh now"
              prompt={REFRESH_REQUEST}
              disabled={!canWrite || copy.data?.refreshing === true}
            />
          }
        />
      </SettingRows>
      {copy.data && notJudged(copy.data) ? (
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
          <p className="text-body text-ink">Still learning what your business does</p>
          <AskAssistant label="Retry" prompt={REFRESH_REQUEST} disabled={!canWrite} />
        </div>
      ) : null}
      {copy.data?.stop_message ? (
        <p className="mt-2 text-meta text-ink-muted">{copy.data.stop_message}</p>
      ) : null}
    </Section>
  );
}

/**
 * Nothing about what the business does has been judged yet (every capability's `applies`
 * is null) and no run is writing it now: until then screens use neutral wording, so the
 * owner is told it is still being learned and can ask for it again. Exported for the test.
 */
export function notJudged(data: BusinessCopy): boolean {
  return !data.refreshing && Object.values(data.capabilities).every((c) => c.applies === null);
}

/** The row's value, in plain words. Exported for the test. */
export function lastRefreshed(data: BusinessCopy | undefined, pending: boolean, failed: boolean): string {
  if (pending) return "Checking…";
  if (failed || !data) return "Could not check just now";
  if (data.refreshing) return `${ASSISTANT_NAME} is writing them now`;
  if (!data.generated_at) return "Not yet";
  return formatIST(data.generated_at);
}
