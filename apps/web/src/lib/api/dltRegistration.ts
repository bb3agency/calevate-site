"use client";

/**
 * The client's own DLT Principal Entity registration — the OTHER thing that stops a
 * campaign launching, and until now the one with no screen.
 * (`apps/api/compliance/registration_routes.py`; SEC-COMP §3.)
 *
 * `campaigns.service.launch_blockers` refuses a launch with `pe_registration_missing`,
 * `pe_registration_not_active` or `tm_link_not_active`. The operator console can WRITE
 * the registration (`admin.ts::useRecordDltRegistration`), and the API has had a
 * client-realm READ since `registration_routes.py` shipped — but nothing called it, so a
 * client whose campaigns were being refused could see the refusal and never the fact
 * behind it.
 *
 * Four things the API decided that this module keeps rather than re-decides:
 *
 * - **`is_active` is the SERVER's predicate and is never re-derived here.** It is
 *   `status == "active" AND tm_link_status == "active"` today (`PeRegistration.is_active`)
 *   and the route's docstring says out loud that this response and the launch gate must
 *   never disagree about it. Same doctrine as `is_verified` on the KYC screen and
 *   `messageable` on the consent screen.
 * - **Absence is a value, not a 404.** `recorded: false` is the normal state of every new
 *   account; the screen renders it as a state.
 * - **`org:read`, not `org:manage`.** Non-mutating, so this read survives a D-22 read-only
 *   "view as client" session — which is exactly the session a support person is in when
 *   the account being discussed is the blocked one. There is therefore NO write hook here
 *   and no control to gate: a client who could mark their own PE `active` would be
 *   marking their own compliance gate green.
 * - **The two statuses are reported separately because they fail separately.** The entity
 *   registration is filed with the registrar; the TM link is the client authorising
 *   Calevate to dial for them. They send the client to different desks, which is why
 *   `pe_registration_not_active` and `tm_link_not_active` are different blocker names.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { lookup } from "@/lib/lookup";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

/** What the registrar holds for this business, as the platform last verified it. */
export type PeRegistration = Schemas["PeRegistrationOut"];

/**
 * The two enums the operator write accepts, reused for the reader's copy tables.
 *
 * Taken from `DltRegistrationIn` — the generated union — rather than spelled out, so a
 * status the API starts sending without copy here fails `tsc` instead of falling through
 * to a vaguer sentence on a client's screen.
 */
export type PeStatus = Schemas["DltRegistrationIn"]["status"];
export type TmLinkStatus = Schemas["DltRegistrationIn"]["tm_link_status"];

export const PE_REGISTRATION_PATH = "/v1/compliance/dlt-registration";

/**
 * What one status means to the business it is about, and what they do next.
 *
 * Written for the client, not for the operator who set it: `submitted` is "the registrar
 * has it" rather than a workflow label, because the reader's question is "why are my
 * campaigns refused" and the answer is "nobody has approved it yet".
 */
export interface StatusCopy {
  label: string;
  next: string;
}

export const PE_STATUS_COPY: Record<PeStatus, StatusCopy> = {
  not_started: {
    label: "Not started",
    next: "We have not filed your Principal Entity registration with the DLT registrar yet. Ask your account manager to start it.",
  },
  submitted: {
    label: "With the registrar",
    next: "Your registration has been filed and the registrar has not approved it yet. Campaigns stay blocked until it is active.",
  },
  active: { label: "Active", next: "The registrar has approved your business as a Principal Entity." },
  suspended: {
    label: "Suspended",
    next: "The registrar has suspended this registration, so campaigns cannot launch. Ask your account manager what the registrar asked for.",
  },
  rejected: {
    label: "Rejected",
    next: "The registrar refused this registration. It has to be re-filed before campaigns can launch — ask your account manager.",
  },
};

export const TM_LINK_COPY: Record<TmLinkStatus, StatusCopy> = {
  not_linked: {
    label: "Not authorised",
    next: "Your Principal Entity has not yet named Calevate as a telemarketer permitted to dial for you. That authorisation is made by you on the registrar's portal.",
  },
  pending: {
    label: "Awaiting approval",
    next: "The authorisation naming Calevate as your telemarketer is filed and awaiting the registrar's approval.",
  },
  active: {
    label: "Active",
    next: "Your Principal Entity authorises Calevate to place calls on your behalf.",
  },
  revoked: {
    label: "Withdrawn",
    next: "The authorisation naming Calevate as your telemarketer has been withdrawn, so campaigns cannot launch. Re-authorise us on the registrar's portal.",
  },
};

/**
 * The copy for a status, or `null` when this build has never heard of it.
 *
 * `lookup`, not `TABLE[value]`: the value comes off the wire, and an indexed read walks
 * the prototype chain (see `lib/lookup.ts` for the three failures that produced). `null`
 * is the honest answer for a status we cannot name, and the screen prints the raw word
 * beside a vaguer sentence rather than inventing a meaning for it.
 */
export function peStatusCopy(status: string | null): StatusCopy | null {
  return lookup(PE_STATUS_COPY, status) ?? null;
}

export function tmLinkCopy(status: string | null): StatusCopy | null {
  return lookup(TM_LINK_COPY, status) ?? null;
}

/**
 * This account's registration.
 *
 * No polling: a registrar approval takes days, and the field that moves is
 * `verified_at` — when WE last checked — which only moves when an operator re-records
 * it. A refetch on focus is the right granularity and is the provider default.
 */
export function usePeRegistration(session: Session): UseQueryResult<PeRegistration> {
  return useQuery({
    queryKey: ["pe-registration", session.orgSlug],
    queryFn: () => apiRequest<PeRegistration>(session, PE_REGISTRATION_PATH),
    staleTime: 5 * 60_000,
  });
}
