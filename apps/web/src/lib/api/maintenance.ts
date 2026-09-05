"use client";

/**
 * Planned maintenance, both realms: the operator's four verbs and the client's one read.
 *
 * ══ THIS MODULE DECIDES NOTHING ═════════════════════════════════════════════════════
 *
 * Not whether a window is open, not whether it may still be edited, not how long a client
 * should wait. Every one of those is the server's, for `opsFxRate.ts`'s reasons and one
 * that is specific to this feature:
 *
 * - **it never compares a window's times against the browser's clock to decide state.**
 *   `state` arrives as a word the worker wrote. A laptop whose clock is four minutes fast
 *   would render "active" over a platform that is still draining, and an operator would
 *   start a migration on top of a live call.
 * - **it never decides whether a start may be moved.** `announced` is the server's fact
 *   and `amend_window` is the rule. The console uses `announced` to DISABLE the input, so
 *   the operator is told before they type rather than refused after; the refusal is still
 *   the enforcement.
 * - **it never computes how stale the drain numbers are.** `measured_at` arrives with
 *   them and the screen renders both.
 *
 * ══ THE CLIENT HALF IS TWO SOURCES FOR ONE FACT, AND THAT IS DELIBERATE ═════════════
 *
 * A client learns about a window in two different situations and only one of them can
 * make a successful request:
 *
 * - **before it closes** (`scheduled`/`draining`) — nothing is shed, so `GET
 *   /v1/maintenance` answers and `useMaintenanceBanner` renders the strip.
 * - **while it is closed** (`active`) — EVERY client request, including that one, is
 *   refused with a 503 whose `code` is `platform_maintenance` and whose `detail` is the
 *   operator's own sentence. `maintenanceFromProblem` reads it out of the refusal, so the
 *   lockout page is rendered from the failure itself rather than from a second request
 *   that would also fail.
 *
 * That is why the banner query does not treat a 503 as an error state to hide: the error
 * IS the answer.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { ApiProblem, apiRequest, type Session } from "./client";

import type { components } from "./schema";

type Schemas = components["schemas"];

export const OPS_MAINTENANCE_PATH = "/v1/ops/maintenance";
export const OPS_MAINTENANCE_QUERY_KEY = ["admin", "ops", "maintenance"] as const;
export const CLIENT_MAINTENANCE_PATH = "/v1/maintenance";
export const CLIENT_MAINTENANCE_QUERY_KEY = ["client", "maintenance"] as const;

/** The `code` the API stamps on a maintenance 503. The console switches on it. */
export const MAINTENANCE_PROBLEM_CODE = "platform_maintenance";

export type MaintenanceWindow = Schemas["MaintenanceWindowOut"];
export type MaintenanceBoard = Schemas["MaintenanceBoardOut"];
export type MaintenanceInFlight = Schemas["InFlightOut"];
export type ClientMaintenance = Schemas["ClientMaintenanceOut"];

/**
 * The step-up string for ONE maintenance action — the console's mirror of
 * `ops/maintenance_routes.py`'s `maintenance_confirmation`, built in ONE place for the
 * reason `platformConfirmation` is.
 *
 * The window id is the TARGET, and its absence on `schedule_maintenance` is not an
 * omission: the window that action creates does not exist when the header is typed.
 * Exported so `tests/maintenance.test.tsx` can pin the literals — these strings are an
 * ops procedure `runbooks/maintenance-window.md` prints, so a reformat here has to fail a
 * test rather than quietly leave the console sending a header the API refuses.
 */
export function maintenanceConfirmation(action: string, windowId?: string): string {
  return windowId === undefined ? action : `${action}:${windowId}`;
}

/**
 * The open window and the recent ones.
 *
 * Polled every ten seconds while a window is open, because the numbers this screen exists
 * to show — how many calls and jobs the drain is still waiting for — move on the worker's
 * fifteen-second tick, and an operator watching a spinner with no numbers is precisely the
 * person who forces a window and breaks a live call. Idle, it polls at a minute: there is
 * nothing to watch.
 */
export function useMaintenanceBoard(): UseQueryResult<MaintenanceBoard> {
  return useQuery({
    queryKey: OPS_MAINTENANCE_QUERY_KEY,
    queryFn: () => apiRequest<MaintenanceBoard>(adminSession(), OPS_MAINTENANCE_PATH),
    refetchInterval: (query) => (query.state.data?.current ? 10_000 : 60_000),
  });
}

export interface ScheduleWindowInput {
  startsAt: string;
  endsAt: string;
  reason: string;
  maxDrainMinutes?: number;
}

export function useScheduleMaintenance() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: ScheduleWindowInput) =>
      apiRequest<MaintenanceWindow>(adminSession(), OPS_MAINTENANCE_PATH, {
        method: "POST",
        body: {
          starts_at: input.startsAt,
          ends_at: input.endsAt,
          reason: input.reason,
          ...(input.maxDrainMinutes === undefined
            ? {}
            : { max_drain_minutes: input.maxDrainMinutes }),
        },
        confirmAction: maintenanceConfirmation("schedule_maintenance"),
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: OPS_MAINTENANCE_QUERY_KEY }),
  });
}

export interface AmendWindowInput {
  windowId: string;
  startsAt?: string;
  endsAt?: string;
  reason?: string;
  maxDrainMinutes?: number;
}

/**
 * Move the end, rewrite the reason, extend the drain — and, before it is announced, move
 * the start.
 *
 * Only the fields that changed are sent. `MaintenanceAmendIn` forbids extras and reads an
 * absent one as "leave it alone", so omitting is how the console says "I am not touching
 * the start" — which is what keeps an operator extending a window from racing another one
 * rewriting its reason.
 */
export function useAmendMaintenance() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ windowId, startsAt, endsAt, reason, maxDrainMinutes }: AmendWindowInput) =>
      apiRequest<MaintenanceWindow>(adminSession(), `${OPS_MAINTENANCE_PATH}/${windowId}`, {
        method: "PATCH",
        body: {
          ...(startsAt === undefined ? {} : { starts_at: startsAt }),
          ...(endsAt === undefined ? {} : { ends_at: endsAt }),
          ...(reason === undefined ? {} : { reason }),
          ...(maxDrainMinutes === undefined ? {} : { max_drain_minutes: maxDrainMinutes }),
        },
        confirmAction: maintenanceConfirmation("amend_maintenance", windowId),
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: OPS_MAINTENANCE_QUERY_KEY }),
  });
}

export function useCancelMaintenance() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (windowId: string) =>
      apiRequest<MaintenanceWindow>(
        adminSession(),
        `${OPS_MAINTENANCE_PATH}/${windowId}/cancel`,
        { method: "POST", confirmAction: maintenanceConfirmation("cancel_maintenance", windowId) },
      ),
    onSuccess: () => void client.invalidateQueries({ queryKey: OPS_MAINTENANCE_QUERY_KEY }),
  });
}

/**
 * End an active (or draining) window now.
 *
 * A separate verb from cancel, and the console offers them in different places, because
 * the server treats them differently: cancel is "never mind" and is refused on an ACTIVE
 * window; end is "we are finished" and owes the restoration work.
 */
export function useEndMaintenance() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (windowId: string) =>
      apiRequest<MaintenanceWindow>(adminSession(), `${OPS_MAINTENANCE_PATH}/${windowId}/end`, {
        method: "POST",
        confirmAction: maintenanceConfirmation("end_maintenance", windowId),
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: OPS_MAINTENANCE_QUERY_KEY }),
  });
}

/**
 * What a maintenance 503 was telling this client, or `null` if the failure was something
 * else.
 *
 * THE LOCKOUT PAGE'S SOURCE. During an active window every client request is refused,
 * including the banner's own — so the page cannot ask a second time and must read the
 * answer out of the refusal it already has. `detail` is the operator's sentence verbatim;
 * `retryAfterSeconds` is the server's own count to the end of the window (RFC 9110
 * §10.2.3 delay-seconds), which is why the page never computes an end time from the
 * browser's clock.
 */
export function maintenanceFromProblem(
  error: unknown,
): { detail: string; retryAfterSeconds: number | null } | null {
  if (!(error instanceof ApiProblem) || error.code !== MAINTENANCE_PROBLEM_CODE) return null;
  return {
    // `ApiProblem.message` IS the server's `detail` — the operator's own sentence about
    // this window. Rendered verbatim; the console adds no words of its own to it.
    detail: error.message,
    retryAfterSeconds: error.retryAfterSeconds ?? null,
  };
}

/**
 * The client console's banner read.
 *
 * `retry: false` because the two answers this can give are both final for the moment: a
 * window or no window, or a 503 that IS the answer. Retrying a maintenance refusal three
 * times only delays the page telling the client what is happening.
 */
export function useMaintenanceBanner(session: Session): UseQueryResult<ClientMaintenance> {
  return useQuery({
    queryKey: [...CLIENT_MAINTENANCE_QUERY_KEY, session.orgSlug],
    queryFn: () => apiRequest<ClientMaintenance>(session, CLIENT_MAINTENANCE_PATH),
    // A minute. The facts move on human timescales — a window is scheduled hours ahead and
    // amended rarely — and the one transition that matters urgently (the door closing) is
    // delivered by the 503 on whatever the client does next, not by this poll.
    refetchInterval: 60_000,
    retry: false,
  });
}
