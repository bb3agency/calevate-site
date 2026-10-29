"use client";

/**
 * The client's declaration of the numbers its automated calls come from (D-941).
 *
 * What the server decides and this module never re-derives: `effective`, `blocker` and
 * `enforced`. They come from the predicate the dial gate uses, and a browser comparing
 * dates would disagree with it around midnight IST.
 *
 * Declaring invalidates the readiness reads and the campaign check, not only this key:
 * the declaration is one of the predicates they compose, so they say "declare your
 * numbers" until they are read again.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { agreementsKey } from "./agreements";
import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type CallingNumberDeclaration = Schemas["CallingNumberDeclarationOut"];

export const DECLARATION_PATH = "/v1/compliance/autodialer-notice";

export function callingNumbersKey(orgSlug: string) {
  return ["calling-numbers", orgSlug] as const;
}

export function useCallingNumbers(session: Session): UseQueryResult<CallingNumberDeclaration> {
  return useQuery({
    queryKey: callingNumbersKey(session.orgSlug),
    queryFn: () => apiRequest<CallingNumberDeclaration>(session, DECLARATION_PATH),
    staleTime: 60_000,
  });
}

export interface DeclareBody {
  numbers: string[];
  /** YYYY-MM-DD, the day the client declared them. */
  declaredOn: string;
  reference: string;
  /** The attestation the screen showed, echoed so a stale screen is refused. */
  attestationVersion: number;
  attestationSha256: string;
}

export function useDeclareCallingNumbers(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: DeclareBody) =>
      apiRequest<CallingNumberDeclaration>(session, DECLARATION_PATH, {
        method: "POST",
        body: {
          declared_clis: body.numbers,
          notified_on: body.declaredOn,
          notice_reference: body.reference.trim() || null,
          attestation_version: body.attestationVersion,
          attestation_sha256: body.attestationSha256,
          withdraw: false,
        },
      }),
    onSuccess: (next) => {
      client.setQueryData(callingNumbersKey(session.orgSlug), next);
      void client.invalidateQueries({ queryKey: agreementsKey(session.orgSlug) });
      void client.invalidateQueries({ queryKey: ["campaign-check", session.orgSlug] });
    },
  });
}

/** "17 Nov" from "2026-11-17", read as a calendar day with no zone shift. */
export function shortDay(isoDay: string): string {
  const [year, month, day] = isoDay.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", timeZone: "UTC" }).format(date);
}

/** Today's calendar day in India, YYYY-MM-DD, for the form's default. */
export function todayIST(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(now);
}
