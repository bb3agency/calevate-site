"use client";

/**
 * The file of an export Pip prepared (D-893 L2): `POST /v1/exports/download` spends the
 * one-time ticket the confirm answered with (`crm/export_tickets.py`), within ten minutes.
 * The ticket rides in the body, never a URL. Same save as the Export buttons.
 */

import { useMutation } from "@tanstack/react-query";

import { saveCsv } from "@/lib/csvDownload";

import { apiRequest, type Session } from "./client";

export function useDownloadPreparedExport(session: Session) {
  return useMutation({
    mutationFn: ({ ticket }: { ticket: string; basename: "leads" | "calls" }) =>
      apiRequest<string>(session, "/v1/exports/download", { method: "POST", body: { ticket } }),
    onSuccess: (csv, { basename }) => saveCsv(csv, basename),
  });
}
