"use client";

import { useState } from "react";
import { AlertTriangle } from "lucide-react";

import {
  Card,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  RestrictionNote,
  formatISTInput,
  formatWholeCount,
  istInputToInstant,
} from "@/components/ui";
import { TypedConfirmation, confirmationMatches } from "@/components/typedConfirmation";
import { MonoValue } from "@/app/admin/ops/opsLanguage";
import type { useAdminAccess } from "@/app/admin/access";
import {
  MAX_BLOCKED_NUMBERS,
  scrubBlockReason,
  splitBlockedNumbers,
  type ScrubDraft,
  type useRecordPreferenceScrub,
} from "@/lib/api/preferenceScrub";
import type { CampaignSummary } from "@/lib/api/campaigns";

/**
 * Filing a provider's scrub run against one campaign.
 *
 * THE CONFIRMATION IS THE PROVIDER'S REFERENCE, TYPED AGAIN. The route's
 * `X-Confirm-Action` header is sent by the client automatically, so on its own it confirms
 * nothing a human did. A reference differs every time, so re-keying it cannot become muscle
 * memory, and it is the only check that catches a transcription error before a write that
 * `preference_scrub_runs` being INSERT-only makes permanent. The match is EXACT
 * (`confirmationMatches(..., "exact")`), because a reference is a string to copy, not a word to agree with.
 */
export function ScrubForm({
  campaign,
  record,
  write,
}: {
  campaign: CampaignSummary;
  record: ReturnType<typeof useRecordPreferenceScrub>;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const [draft, setDraft] = useState<ScrubDraft>(() => ({
    provider: "",
    scrubRef: "",
    // Prefilled to NOW in IST: the common case is a run just done, and a wrong default is
    // visible and editable, unlike an empty field filled in a hurry with a UTC time.
    scrubbedAtInput: formatISTInput(new Date().toISOString()),
    blockedNumbers: "",
  }));
  const [confirmation, setConfirmation] = useState("");

  const set = <K extends keyof ScrubDraft>(key: K, value: ScrubDraft[K]) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
    record.reset();
  };

  const instant = istInputToInstant(draft.scrubbedAtInput);
  const blocked = scrubBlockReason(draft, instant);
  const pasted = splitBlockedNumbers(draft.blockedNumbers);
  const confirmed = confirmationMatches(confirmation, draft.scrubRef.trim(), "exact");

  return (
    <Card title={`Record a scrub of “${campaign.name}”`}>
      <form
        className="max-w-xl space-y-4"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          if (blocked || !confirmed || instant === null) return;
          record.mutate({ draft, instant });
        }}
      >
        <p className="text-sm text-ink-muted">
          Files the provider&apos;s verdict, suppresses the numbers they blocked, and opens
          this campaign&apos;s launch gate until midnight IST. It does not run a scrub.{" "}
          <span className="font-medium text-ink">
            The record cannot be edited or removed afterwards.
          </span>
        </p>

        <RestrictionNote reason={write.reason} />

        <div>
          <label htmlFor="scrub-provider" className={FIELD_LABEL}>
            Access provider
          </label>
          <input
            id="scrub-provider"
            type="text"
            maxLength={80}
            value={draft.provider}
            disabled={!write.allowed}
            onChange={(e) => set("provider", e.target.value)}
            aria-describedby="scrub-provider-hint"
            className={FIELD}
          />
          <span id="scrub-provider-hint" className={FIELD_HINT}>
            Whose platform ran it, as you would name them back to them.
          </span>
        </div>

        <div>
          <label htmlFor="scrub-ref" className={FIELD_LABEL}>
            Their reference for this run
          </label>
          <input
            id="scrub-ref"
            type="text"
            maxLength={120}
            value={draft.scrubRef}
            disabled={!write.allowed}
            onChange={(e) => {
              set("scrubRef", e.target.value);
              // The confirmation names THIS reference: a corrected reference must not be
              // filed under a confirmation typed for the wrong one.
              setConfirmation("");
            }}
            aria-describedby="scrub-ref-hint"
            className={`${FIELD} font-mono`}
          />
          <span id="scrub-ref-hint" className={FIELD_HINT}>
            Makes this record checkable against their portal later. The same provider and
            reference twice files nothing new.
          </span>
        </div>

        <div>
          <label htmlFor="scrub-at" className={FIELD_LABEL}>
            When the provider ran it (IST)
          </label>
          <input
            id="scrub-at"
            type="datetime-local"
            value={draft.scrubbedAtInput}
            disabled={!write.allowed}
            onChange={(e) => set("scrubbedAtInput", e.target.value)}
            aria-describedby="scrub-at-hint"
            className={FIELD}
          />
          <span id="scrub-at-hint" className={FIELD_HINT}>
            As their report states it, in Indian time — this field is IST, not your
            machine&apos;s clock. The validity window ends at midnight IST on THIS date, so
            recording yesterday&apos;s run does not open the gate today.
          </span>
        </div>

        <div>
          <label htmlFor="scrub-blocked" className={FIELD_LABEL}>
            Numbers the register SUPPRESSED
          </label>
          <textarea
            id="scrub-blocked"
            rows={5}
            value={draft.blockedNumbers}
            disabled={!write.allowed}
            onChange={(e) => set("blockedNumbers", e.target.value)}
            aria-describedby="scrub-blocked-hint"
            className={`${FIELD} font-mono`}
          />
          <span id="scrub-blocked-hint" className={FIELD_HINT}>
            {/* The most expensive paste on the screen: a portal hands back the blocked list
                AND the survivors, and pasting the survivors suppresses everyone the scrub
                cleared. By the time the counts come back it is done. */}
            <span className="font-medium text-ink">
              Paste the BLOCKED list — the numbers to take out of this campaign, not the ones
              that survived.
            </span>{" "}
            One per line or comma-separated; {formatWholeCount(String(pasted.length))} read so
            far, up to {formatWholeCount(String(MAX_BLOCKED_NUMBERS))}. A clean scrub that
            blocked nobody is a legitimate run: leave this empty.
          </span>
        </div>

        <TypedConfirmation
          match="exact"
          id="scrub-confirm"
          phrase={draft.scrubRef.trim()}
          value={confirmation}
          onChange={setConfirmation}
          disabled={!write.allowed || draft.scrubRef.trim() === ""}
          hint={
            <>
              Type the provider&apos;s reference again. It is the one field a typo makes
              unrecoverable — <MonoValue>preference_scrub_runs</MonoValue> is append-only, so a
              run filed under the wrong reference stays filed.
            </>
          }
        />

        {blocked && (
          <NoticeBox tone="warn" icon={<AlertTriangle className="h-5 w-5" />}>
            <p className="text-xs">{blocked}</p>
          </NoticeBox>
        )}

        <button
          type="submit"
          className={`${PRIMARY_BUTTON} max-sm:w-full max-sm:justify-center`}
          disabled={!write.allowed || blocked !== null || !confirmed || record.isPending}
        >
          {record.isPending ? "Recording…" : "Record this scrub"}
        </button>
      </form>
    </Card>
  );
}
