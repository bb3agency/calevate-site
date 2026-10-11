"use client";

/**
 * The client's existing number, forwarded by its carrier to its Calevate number (D-746).
 *
 * The codes are the server's catalogue (`apps/api/forwarding/codes.py`), each with its
 * source and evidence class; this module only fills in the Calevate number and the ring time
 * (`renderCode`). Nothing here offers a `tel:` link for a code: iOS does not dial a link
 * containing `*` or `#` (Apple's PhoneLinks reference), so codes are copied instead.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { accountAction, withAccountCode } from "./accountCode";
import { adminSession } from "./admin";
import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Forwarding = Schemas["ForwardingOut"];
export type ForwardedLine = Schemas["LineOut"];
export type ForwardingTest = Schemas["ForwardingTestOut"];
export type ForwardingCodes = Schemas["CodesOut"];
export type CarrierGuide = Schemas["CarrierGuideOut"];
export type ForwardingCode = Schemas["CodeOut"];
export type LineInput = Schemas["LineIn"];
export type LineChange = Schemas["LineChangeIn"];
export type AdminForwarding = Schemas["AdminForwardingOut"];
export type LineKind = LineInput["line_kind"];
export type Carrier = LineInput["carrier"];
export type ForwardingMode = LineInput["mode"];

export const FORWARDING_PATH = "/v1/forwarding";
export const FORWARDING_CODES_PATH = "/v1/forwarding/codes";
export const SAVE_NUMBER_PATH = "/v1/forwarding/save-number";

export const forwardingKeys = {
  all: (org: string) => ["forwarding", org] as const,
  codes: (org: string) => ["forwarding", org, "codes"] as const,
  tests: (org: string, line: string) => ["forwarding", org, "tests", line] as const,
  saveNumber: (org: string) => ["forwarding", org, "save-number"] as const,
  admin: (tenant: string) => ["admin", "forwarding", tenant] as const,
};

/** Ring times a phone network takes for "no answer" (3GPP TS 22.082 §3.3.3). */
export const RING_SECONDS = [5, 10, 15, 20, 25, 30] as const;
export const DEFAULT_RING_SECONDS = 20;

/** A test is still running: poll until it settles. */
export function testRunning(test: ForwardingTest | undefined): boolean {
  return test?.status === "placing" || test?.status === "ringing";
}

/** The Calevate number as a phone in India dials it inside a code (mirrors `codes.dialled_form`). */
export function dialledForm(e164: string): string {
  return `0${e164.replace(/^\+91/, "")}`;
}

export function renderCode(template: string | null, numberE164: string, seconds: number): string | null {
  if (template == null) return null;
  return template.replaceAll("{number}", dialledForm(numberE164)).replaceAll("{seconds}", String(seconds));
}

export function useForwarding(session: Session): UseQueryResult<Forwarding> {
  return useQuery({
    queryKey: forwardingKeys.all(session.orgSlug),
    queryFn: () => apiRequest<Forwarding>(session, FORWARDING_PATH),
  });
}

/** The catalogue changes only with a deploy. */
export function useForwardingCodes(session: Session): UseQueryResult<ForwardingCodes> {
  return useQuery({
    queryKey: forwardingKeys.codes(session.orgSlug),
    queryFn: () => apiRequest<ForwardingCodes>(session, FORWARDING_CODES_PATH),
    staleTime: Infinity,
  });
}

export function useAddLine(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: LineInput) => {
      const confirmAction = accountAction(session, "add_forwarded_number");
      return withAccountCode(confirmAction, "Adding your existing business number.", () =>
        apiRequest<ForwardedLine>(session, `${FORWARDING_PATH}/lines`, { method: "POST", body, confirmAction }),
      );
    },
    onSuccess: () => client.invalidateQueries({ queryKey: forwardingKeys.all(session.orgSlug) }),
  });
}

export function useChangeLine(session: Session, lineId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: LineChange) =>
      apiRequest<ForwardedLine>(session, `${FORWARDING_PATH}/lines/${encodeURIComponent(lineId)}`, {
        method: "PATCH",
        body,
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: forwardingKeys.all(session.orgSlug) }),
  });
}

export function useRemoveLine(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (lineId: string) =>
      apiRequest<void>(session, `${FORWARDING_PATH}/lines/${encodeURIComponent(lineId)}`, {
        method: "DELETE",
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: forwardingKeys.all(session.orgSlug) }),
  });
}

/** The latest tests of one number, polled while one is running. */
export function useLineTests(session: Session, lineId: string): UseQueryResult<ForwardingTest[]> {
  return useQuery({
    queryKey: forwardingKeys.tests(session.orgSlug, lineId),
    queryFn: () =>
      apiRequest<ForwardingTest[]>(
        session,
        `${FORWARDING_PATH}/lines/${encodeURIComponent(lineId)}/tests?limit=5`,
      ),
    refetchInterval: (query) => (testRunning(query.state.data?.[0]) ? 5000 : false),
  });
}

export function useRunTest(session: Session, lineId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => {
      const confirmAction = accountAction(session, "forwarding_test");
      return withAccountCode(confirmAction, "Placing a test call to your number.", () =>
        apiRequest<ForwardingTest>(session, `${FORWARDING_PATH}/lines/${encodeURIComponent(lineId)}/tests`, {
          method: "POST",
          confirmAction,
        }),
      );
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: forwardingKeys.tests(session.orgSlug, lineId) });
      void client.invalidateQueries({ queryKey: forwardingKeys.all(session.orgSlug) });
    },
  });
}

export function useSaveNumberSwitch(session: Session): UseQueryResult<Schemas["SaveNumberOut"]> {
  return useQuery({
    queryKey: forwardingKeys.saveNumber(session.orgSlug),
    queryFn: () => apiRequest<Schemas["SaveNumberOut"]>(session, SAVE_NUMBER_PATH),
  });
}

export function useSetSaveNumber(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) => {
      const confirmAction = accountAction(session, "save_number_message");
      return withAccountCode(confirmAction, "Changing what we send to your callers.", () =>
        apiRequest<Schemas["SaveNumberOut"]>(session, SAVE_NUMBER_PATH, {
          method: "PUT",
          body: { enabled },
          confirmAction,
        }),
      );
    },
    onSuccess: (state) => client.setQueryData(forwardingKeys.saveNumber(session.orgSlug), state),
  });
}

export function useAdminForwarding(tenantId: string): UseQueryResult<AdminForwarding> {
  return useQuery({
    queryKey: forwardingKeys.admin(tenantId),
    enabled: Boolean(tenantId),
    queryFn: () =>
      apiRequest<AdminForwarding>(adminSession(), `/v1/admin/forwarding/tenants/${encodeURIComponent(tenantId)}?limit=5`),
  });
}
