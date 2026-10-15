"use client";

/**
 * The client's own WhatsApp, connected through Meta's Embedded Signup (D-784), its message
 * templates, and the operator's view of every client's.
 *
 * Connecting is three calls: `POST /v1/whatsapp/signup` hands back what Meta's window needs
 * (and a single-use state), Meta's window runs in the browser (`lib/facebookSignup.ts`), and
 * `POST /v1/whatsapp/connect` sends Meta's code to the server, which must exchange it within
 * 30 seconds. The PIN in the connect answer is shown once: Calevate never stores it.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type WhatsAppOverview = Schemas["WhatsAppOverviewOut"];
export type WhatsAppAccount = Schemas["WhatsAppAccountOut"];
export type WhatsAppSignup = Schemas["WhatsAppSignupOut"];
export type WhatsAppConnectInput = Schemas["WhatsAppConnectIn"];
export type WhatsAppConnected = Schemas["WhatsAppConnectOut"];
export type WhatsAppTemplate = Schemas["WhatsAppTemplateOut"];
export type WhatsAppTemplateInput = Schemas["WhatsAppTemplateIn"];
export type AdminWhatsApp = Schemas["AdminWhatsAppOut"];
export type SignupChoice = Schemas["WhatsAppSignupIn"]["choice"];

export const WHATSAPP_PATH = "/v1/whatsapp";

export const whatsappKeys = {
  overview: (org: string) => ["whatsapp", org] as const,
  templates: (org: string) => ["whatsapp", org, "templates"] as const,
  admin: () => ["admin", "whatsapp"] as const,
};

/** Meta reviews a template in "up to 24 hours" (templates/template-review.md, 15 Oct 2026). */
export const TEMPLATE_REVIEW_HOURS = 24;

export const LANGUAGE_LABELS: Record<string, string> = {
  te: "Telugu",
  hi: "Hindi",
  en: "English",
  en_US: "English (US)",
  en_GB: "English (UK)",
  en_IN: "English (India)",
};

/** What each of Calevate's own templates is for, in the owner's words. */
export const PURPOSE_LABELS: Record<string, string> = {
  booking_confirmed: "Booking confirmed",
  details_requested: "The details you asked for",
  payment_link: "Payment link",
  callback_time: "Call-back time",
};

/** A template's state as the owner reads it, and how loud it is. */
export function templateState(status: string): { text: string; tone: "ok" | "warn" | "stop" | "neutral" } {
  switch (status) {
    case "approved":
      return { text: "Approved", tone: "ok" };
    case "pending":
    case "draft":
      return { text: "Waiting for Meta", tone: "neutral" };
    case "rejected":
      return { text: "Rejected by Meta", tone: "stop" };
    case "paused":
      return { text: "Paused by Meta", tone: "warn" };
    case "disabled":
      return { text: "Turned off by Meta", tone: "stop" };
    case "submit_failed":
      return { text: "Not sent to Meta", tone: "warn" };
    default:
      return { text: "Removed", tone: "neutral" };
  }
}

/** An account's state as the owner reads it. */
export function accountState(account: WhatsAppAccount): { text: string; tone: "ok" | "warn" | "stop" | "neutral" } {
  if (account.status === "connected") return { text: "Connected", tone: "ok" };
  if (account.status === "needs_attention") return { text: "Needs attention", tone: "warn" };
  if (account.status === "connecting") return { text: "Setting up", tone: "neutral" };
  return { text: "Disconnected", tone: "neutral" };
}

/** The blanks a template body uses, in order: `{{1}}`, `{{2}}`… */
export function templateBlanks(body: string): number[] {
  const seen = new Set<number>();
  for (const match of body.matchAll(/\{\{\s*(\d+)\s*\}\}/g)) seen.add(Number(match[1]));
  return [...seen].sort((a, b) => a - b);
}

/** The body with each blank filled by its example, for the preview. */
export function fillTemplate(body: string, examples: readonly string[]): string {
  return body.replace(/\{\{\s*(\d+)\s*\}\}/g, (whole, n: string) => examples[Number(n) - 1] || whole);
}

/** A template name Meta accepts, from words the owner typed ("Order ready!" → "order_ready"). */
export function templateNameFrom(words: string): string {
  return words
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 60);
}

export function useWhatsApp(session: Session): UseQueryResult<WhatsAppOverview> {
  return useQuery({
    queryKey: whatsappKeys.overview(session.orgSlug),
    queryFn: () => apiRequest<WhatsAppOverview>(session, WHATSAPP_PATH),
  });
}

export function useWhatsAppTemplates(session: Session, enabled = true): UseQueryResult<WhatsAppTemplate[]> {
  return useQuery({
    queryKey: whatsappKeys.templates(session.orgSlug),
    enabled,
    queryFn: () => apiRequest<WhatsAppTemplate[]>(session, `${WHATSAPP_PATH}/templates`),
  });
}

export function useBeginSignup(session: Session) {
  return useMutation({
    mutationFn: (choice: SignupChoice) =>
      apiRequest<WhatsAppSignup>(session, `${WHATSAPP_PATH}/signup`, { method: "POST", body: { choice } }),
  });
}

export function useConnectWhatsApp(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: WhatsAppConnectInput) =>
      apiRequest<WhatsAppConnected>(session, `${WHATSAPP_PATH}/connect`, { method: "POST", body }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: whatsappKeys.overview(session.orgSlug) });
      void client.invalidateQueries({ queryKey: whatsappKeys.templates(session.orgSlug) });
    },
  });
}

export function useFinishWhatsApp(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (accountId: string) =>
      apiRequest<WhatsAppConnected>(
        session,
        `${WHATSAPP_PATH}/accounts/${encodeURIComponent(accountId)}/finish`,
        { method: "POST" },
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: whatsappKeys.overview(session.orgSlug) }),
  });
}

export function useDisconnectWhatsApp(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (accountId: string) =>
      apiRequest<WhatsAppAccount>(
        session,
        `${WHATSAPP_PATH}/accounts/${encodeURIComponent(accountId)}/disconnect`,
        { method: "POST" },
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: whatsappKeys.overview(session.orgSlug) }),
  });
}

export function useCreateTemplate(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: WhatsAppTemplateInput) =>
      apiRequest<WhatsAppTemplate>(session, `${WHATSAPP_PATH}/templates`, { method: "POST", body }),
    onSuccess: () => client.invalidateQueries({ queryKey: whatsappKeys.templates(session.orgSlug) }),
  });
}

export function useAdminWhatsApp(): UseQueryResult<AdminWhatsApp> {
  return useQuery({
    queryKey: whatsappKeys.admin(),
    queryFn: () => apiRequest<AdminWhatsApp>(adminSession(), "/v1/admin/whatsapp"),
  });
}
