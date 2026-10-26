/**
 * Linking and releasing a client's phone numbers, and the voice platform's number panel — the
 * operator's half of D-537.
 *
 * Not in `admin.ts`: every hook in that file is about a client's RECORD, and these act on a
 * number at the voice platform.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  adminSession,
  confirmedAdminRequest,
  engineRefConfirmation,
  recordEngineNumberConfirmation,
  releaseNumberConfirmation,
} from "./admin";
import { apiRequest } from "./client";
import type { components } from "./schema";

export type TenantNumberCost = components["schemas"]["TenantNumberCostOut"];

/** This client's numbers, whether we bought them, and what each costs US. */
export function useTenantNumberCosts(tenantId: string) {
  return useQuery({
    queryKey: ["admin", "number-costs", tenantId],
    queryFn: () =>
      apiRequest<TenantNumberCost[]>(adminSession(), `/v1/admin/numbers/tenants/${tenantId}`),
    enabled: Boolean(tenantId),
  });
}

/**
 * Record the voice platform's own handle for a number the CLIENT brought.
 *
 * Without it an agent set to answer that number will not — the publish reports success and
 * the phone does not ring, which is the state every number on this platform was in before
 * D-537. The response says what the platform was told, so the screen can report a bind
 * that failed rather than implying one that did not happen.
 */
export function useSetNumberEngineRef(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ numberId, ref }: { numberId: string; ref: string }) =>
      confirmedAdminRequest<components["schemas"]["EngineRefOut"]>(
        `/v1/admin/numbers/tenants/${tenantId}/${numberId}/engine-ref`,
        {
          method: "POST",
          body: { engine_number_ref: ref },
          confirmAction: engineRefConfirmation(tenantId, numberId),
        },
        "Recording this number's handle.",
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["admin", "number-costs"] });
      void client.invalidateQueries({ queryKey: ["admin", "numbers"] });
      // The voice-platform panel on the same page names each number's answering agent.
      void client.invalidateQueries({ queryKey: ["admin", "engine-numbers", tenantId] });
    },
  });
}

/**
 * Choose which agent answers this number — or `null`, which detaches it.
 *
 * **THE STEP THAT DID NOT EXIST (D-576).** `phone_numbers.agent_id` had exactly one
 * writer and it was the INSERT, so every number on this platform was attached to nobody:
 * publishing the receptionist reported success and the phone never rang. Detaching
 * releases the binding at the voice platform too — a detach that only nulled the column
 * would leave a client's line answered by an agent this console says is not on it.
 *
 * The response says what the platform was TOLD, so a row can report a routing the vendor
 * refused instead of implying a phone that rings.
 */
export function useSetNumberAgent(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ numberId, agentId }: { numberId: string; agentId: string | null }) =>
      apiRequest<components["schemas"]["NumberAgentOut"]>(
        adminSession(),
        `/v1/admin/tenants/${tenantId}/numbers/${numberId}/agent`,
        { method: "POST", body: { agent_id: agentId } },
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["admin", "number-costs"] });
      void client.invalidateQueries({ queryKey: ["admin", "numbers"] });
      // The voice-platform panel on the same page names each number's answering agent.
      void client.invalidateQueries({ queryKey: ["admin", "engine-numbers", tenantId] });
    },
  });
}

/** Give a bought number back and stop the monthly rental. Offboarding only. */
export function useReleaseNumber(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (numberId: string) =>
      confirmedAdminRequest<void>(
        `/v1/admin/numbers/tenants/${tenantId}/${numberId}/release`,
        { method: "POST", confirmAction: releaseNumberConfirmation(tenantId, numberId) },
        "Releasing this number.",
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["admin", "number-costs"] });
      void client.invalidateQueries({ queryKey: ["admin", "numbers"] });
      // The voice-platform panel beside it lists the same number.
      void client.invalidateQueries({ queryKey: ["admin", "engine-numbers", tenantId] });
    },
  });
}

export type EngineNumbers = components["schemas"]["EngineNumbersOut"];

/**
 * The numbers held in the voice platform's OWN console, and the steps that rent and attach
 * one (D-678). `managed_in_engine_console` is false on every engine whose numbers this
 * console records and routes itself, and the lists are then empty.
 */
export function useTenantEngineNumbers(tenantId: string) {
  return useQuery({
    queryKey: ["admin", "engine-numbers", tenantId],
    queryFn: () =>
      apiRequest<EngineNumbers>(adminSession(), `/v1/admin/numbers/tenants/${tenantId}/engine`),
    enabled: Boolean(tenantId),
  });
}

export type RecordedEngineNumber = components["schemas"]["RecordedEngineNumberOut"];
export type RecordEngineNumber = components["schemas"]["RecordEngineNumberIn"];

/**
 * Record a number the voice platform holds for this client, from its own list (D-691).
 *
 * Only the number and how it is used are sent: whether it is rented, its handle and its
 * series are read from the platform. A rented number is priced at the attested monthly
 * rate and its first month is collected in the same request, and the platform is told
 * which agent answers it.
 */
export function useRecordEngineNumber(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: RecordEngineNumber) =>
      confirmedAdminRequest<RecordedEngineNumber>(
        `/v1/admin/numbers/tenants/${tenantId}/engine/record`,
        { method: "POST", body, confirmAction: recordEngineNumberConfirmation(tenantId) },
        "Recording this number.",
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["admin", "engine-numbers", tenantId] });
      void client.invalidateQueries({ queryKey: ["admin", "number-costs"] });
      void client.invalidateQueries({ queryKey: ["admin", "numbers"] });
    },
  });
}

export type EngineBusinessDetails = components["schemas"]["BusinessDetailsOut"];

export const ENGINE_BUSINESS_DETAILS_PATH = "/v1/admin/numbers/engine/business-details";

/** The voice platform's business-details application, read live. Read-only (D-691). */
export function useEngineBusinessDetails() {
  return useQuery({
    queryKey: ["admin", "engine-business-details"],
    queryFn: () =>
      apiRequest<EngineBusinessDetails>(adminSession(), ENGINE_BUSINESS_DETAILS_PATH),
  });
}
