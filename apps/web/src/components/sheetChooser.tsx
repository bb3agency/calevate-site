"use client";

/**
 * Choose a Google Sheet on the account's own Google connection (D-703).
 *
 * One control for both places a sheet is chosen: lead delivery (Integrations) and the
 * in-call Sheets actions. It opens Google's picker on the owner's connected Google account;
 * picking the file is what lets Calevate write to it (`drive.file`), so there is no address
 * to paste and nothing to share by hand.
 */

import Link from "next/link";
import { FileSpreadsheet } from "lucide-react";
import { useState } from "react";

import { NoticeBox, ProblemNotice, SECONDARY_BUTTON, Skeleton } from "@/components/ui";
import { openSheetsPicker, useCredentials } from "@/lib/api/actions";
import type { Session } from "@/lib/api/client";
import { type PickedSheet, pickSpreadsheet } from "@/lib/googlePicker";

export interface ChosenSheet {
  credentialId: string;
  spreadsheetId: string;
  /** Shown back to the owner; the id alone means nothing to a person. */
  name: string;
}

export function SheetChooser({
  session,
  value,
  onChange,
  disabled = false,
  label = "Spreadsheet",
}: {
  session: Session;
  value: ChosenSheet | null;
  onChange: (next: ChosenSheet) => void;
  disabled?: boolean;
  label?: string;
}) {
  const creds = useCredentials(session);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  if (creds.isPending) return <Skeleton rows={1} label="Loading your connected accounts…" />;
  if (creds.isError) {
    return <ProblemNotice error={creds.error} onRetry={() => void creds.refetch()} />;
  }
  const connections = creds.data.filter((c) => c.kind === "google_sheets");
  const connection = connections.find((c) => c.id === value?.credentialId) ?? connections[0];

  if (!connection) {
    return (
      <NoticeBox tone="neutral" title="Connect Google Sheets first">
        <p className="mt-1">
          Connect Google Sheets on the{" "}
          <Link
            href={`/c/${session.orgSlug}/integrations`}
            className="font-medium text-brand-strong underline underline-offset-2 dark:text-brand-bright"
          >
            Integrations
          </Link>{" "}
          page, then come back and choose your spreadsheet.
        </p>
      </NoticeBox>
    );
  }

  async function choose() {
    if (!connection) return;
    setBusy(true);
    setError(null);
    try {
      const config = await openSheetsPicker(session, connection.id);
      const picked: PickedSheet | null = await pickSpreadsheet({
        accessToken: config.access_token,
        developerKey: config.developer_key,
        appId: config.app_id,
      });
      if (picked) {
        onChange({ credentialId: connection.id, spreadsheetId: picked.id, name: picked.name });
      }
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium text-ink">{label}</p>
      <div className="flex flex-wrap items-center gap-3">
        {value ? (
          <span className="inline-flex min-w-0 items-center gap-2 rounded-md border border-line bg-app px-3 py-2 text-sm text-ink">
            <FileSpreadsheet aria-hidden className="h-4 w-4 shrink-0 text-brand-strong" />
            <span className="min-w-0 break-words">{value.name}</span>
          </span>
        ) : null}
        <button
          type="button"
          className={SECONDARY_BUTTON}
          disabled={disabled || busy || !connection}
          onClick={() => void choose()}
        >
          <FileSpreadsheet aria-hidden className="h-4 w-4" />
          {busy ? "Opening Google…" : value ? "Choose another" : "Choose a spreadsheet"}
        </button>
      </div>
      {error ? (
        error instanceof Error && !("status" in error) ? (
          <NoticeBox tone="warn" title="Google's file picker did not open">
            <p className="mt-1">Check your connection and try again.</p>
          </NoticeBox>
        ) : (
          <ProblemNotice error={error} />
        )
      ) : null}
    </div>
  );
}
