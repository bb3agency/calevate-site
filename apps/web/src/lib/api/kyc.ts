"use client";

/**
 * Subscriber KYC — the record that decides whether an account may take a phone
 * connection, and, on a self-serve account, whether it may dial out at all.
 * (SURFACES §2b; `apps/api/compliance/kyc.py`; migration a3f6b1e02d95.)
 *
 * Three endpoints shipped in `4024ddf` with no screen anywhere, so a self-serve client
 * whose calls were being refused `kyc_missing` had nothing to open, and the operator
 * who could clear it had no form. This module is the shared half of both screens: the
 * types, the vocabulary, and the client-realm read.
 *
 * Four things the API decided that this module keeps rather than smooths over:
 *
 * - **The client can read and cannot write.** `GET /v1/compliance/kyc` is `org:read`;
 *   the only write is `POST /v1/admin/tenants/{tenant_id}/kyc` (`admin:tenants`), which
 *   lives in `admin.ts` because it is an admin-realm call with an admin session. A
 *   business that could mark its own identity verified would be marking the telecom
 *   gate green on a check nobody performed (Telecom Act 2023 s.3(7)).
 * - **`org:read` is not mutating**, so the client read stays usable inside a read-only
 *   "view as client" session (D-22) — which is exactly the session a support person is
 *   in when the account is blocked. `useKycRecord` therefore takes whatever session the
 *   realm handed it and adds no permission gate of its own.
 * - **Absence is a value, not a 404.** `recorded: false` is the normal state of every
 *   new account, so the screens render it as a state and never as an error.
 * - **`is_verified` and `number_purchase_available` are the SERVER's answers and are
 *   never re-derived here.** "Is `in_review` good enough" is the question the dispatch
 *   gate answers; a console that answered it for itself would eventually disagree with
 *   the gate. Same rule `messagingConsent.ts` states about `messageable`.
 *
 * **There is no upload anywhere in this module, and that is the design.** What the API
 * stores is a REFERENCE — a public business-registry identifier (CIN, LLPIN, GSTIN,
 * Udyam …) plus where the verification pack is filed. No scan, no image, no Aadhaar and
 * no personal PAN exists in the schema to hold, and a CHECK constraint refuses a bare
 * twelve-digit `document_ref` so an Aadhaar cannot be typed into a business field. A
 * file input on either screen would invite precisely the thing the schema refuses.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

/** The client's own state. Every field but the three booleans is genuinely nullable. */
export type KycRecord = Schemas["apps__api__compliance__kyc_routes__KycRecordOut"];
/** The operator's write. `verified_at` and the verifying admin are absent on purpose. */
export type KycRecordIn = Schemas["KycRecordIn"];
export type KycStatus = KycRecordIn["status"];
export type KycDocumentKind = NonNullable<KycRecordIn["document_kind"]>;
export type KycEntityType = NonNullable<KycRecordIn["entity_type"]>;

/** One path string for the one endpoint, so the two realms cannot drift apart. */
export const KYC_PATH = "/v1/compliance/kyc";

export interface KycStatusCopy {
  /** What this state is called. Shared by both realms so they name it identically. */
  label: string;
  /** The client's headline for this state. */
  headline: string;
  /** What happens next and whose move it is — the whole reason the states are split. */
  next: string;
  tone: "ok" | "warn" | "stop" | "neutral";
  /** What an operator is choosing when they pick this in the admin form. */
  operator: string;
}

/**
 * The six states, as a `Record` over the GENERATED union rather than a loose object.
 *
 * If the API adds or renames a status this file stops compiling instead of quietly
 * rendering a state nobody wrote copy for — the device `CONSENT_SOURCES` uses, for the
 * same reason.
 *
 * Each state carries its own `next`, which is the point `kyc_not_verified_reason` makes
 * in the API: `submitted` means we owe them a review, `rejected` means they owe us a
 * document, `expired` means the entity's paperwork lapsed. One "not verified" string
 * would send all three to the same wrong place.
 */
export const KYC_STATUS_COPY: Record<KycStatus, KycStatusCopy> = {
  not_started: {
    label: "Not started",
    headline: "Your business has not been verified yet.",
    next: "Send us your business registration details and we will verify the account.",
    tone: "neutral",
    operator: "not_started — opened, nothing checked yet",
  },
  submitted: {
    label: "Submitted",
    headline: "We have your details and owe you a review.",
    next: "Nothing for you to do — we will come back to you, or ask if something is missing.",
    tone: "neutral",
    operator: "submitted — the client has sent their documents",
  },
  in_review: {
    label: "In review",
    headline: "We are checking your business details now.",
    next: "Nothing for you to do. Outbound calling opens as soon as this clears.",
    tone: "neutral",
    operator: "in_review — with us, being checked",
  },
  verified: {
    label: "Verified",
    headline: "Your business is verified.",
    next: "Nothing here is holding up your calls.",
    tone: "ok",
    operator: "verified — cleared; opens the gates below",
  },
  rejected: {
    label: "Rejected",
    headline: "We could not verify your business from what we were sent.",
    next: "Send corrected details and we will look again — the reason is below.",
    tone: "stop",
    operator: "rejected — refused; must say why",
  },
  expired: {
    label: "Expired",
    headline: "Your verification has lapsed.",
    next: "Send us current registration details and we will verify the account again.",
    tone: "warn",
    operator: "expired — the entity's paperwork lapsed",
  },
};

/** `status` is a plain string on the wire; only render copy for members we know. */
export function isKnownKycStatus(value: string): value is KycStatus {
  return value in KYC_STATUS_COPY;
}

export interface DocumentKindSpec {
  label: string;
  /** What the client would call it, so both screens ask for the same piece of paper. */
  hint: string;
  /** The SHAPE of the identifier, never a real one. */
  placeholder: string;
}

/**
 * The six registry documents, keyed off the generated union.
 *
 * Every member identifies an ENTITY. None identifies a natural person, and that is what
 * keeps `document_ref` out of DPDP scope: a CIN or a GSTIN is published data about a
 * business. Aadhaar and personal PAN are not members here because they are not members
 * in the database either (`ck_kyc_records_document_kind_enum`).
 */
export const DOCUMENT_KINDS: Record<KycDocumentKind, DocumentKindSpec> = {
  cin: {
    label: "CIN",
    hint: "Corporate Identity Number — on the certificate of incorporation of a company.",
    placeholder: "U74999KA2020PTC131234",
  },
  llpin: {
    label: "LLPIN",
    hint: "The registration number of a Limited Liability Partnership.",
    placeholder: "AAB-1234",
  },
  gstin: {
    label: "GSTIN",
    hint: "The GST registration number, on the registration certificate.",
    placeholder: "29ABCDE1234F1Z5",
  },
  udyam: {
    label: "Udyam registration",
    hint: "The MSME registration number, for a small business registered on Udyam.",
    placeholder: "UDYAM-KA-03-0001234",
  },
  shop_establishment: {
    label: "Shops & Establishments",
    hint: "The state registration a shop or small establishment trades under.",
    placeholder: "Registration number as printed",
  },
  trade_licence: {
    label: "Trade licence",
    hint: "The municipal trade licence number.",
    placeholder: "Licence number as printed",
  },
};

/** The seven entity types the database permits (`ck_kyc_records_entity_type_enum`). */
export const ENTITY_TYPES: Record<KycEntityType, string> = {
  sole_proprietorship: "Sole proprietorship",
  partnership: "Partnership firm",
  llp: "Limited Liability Partnership",
  private_limited: "Private limited company",
  public_limited: "Public limited company",
  trust_or_society: "Trust or society",
  huf: "Hindu Undivided Family",
};

/**
 * The stored value as a member of the union, or `null` when this build cannot name it.
 *
 * Both columns arrive as plain strings on the wire. Falling back to `null` rather than
 * casting is what keeps a form honest across a schema change in either direction: a
 * `<select>` holding a value with no matching option would send the server a member its
 * `Literal` refuses, whereas `null` means "leave what is filed alone" on an endpoint
 * that COALESCEs — so an unrecognised member is neither lost nor bounced.
 */
export function asDocumentKind(value: string | null): KycDocumentKind | null {
  return value !== null && value in DOCUMENT_KINDS ? (value as KycDocumentKind) : null;
}

export function asEntityType(value: string | null): KycEntityType | null {
  return value !== null && value in ENTITY_TYPES ? (value as KycEntityType) : null;
}

export function documentKindLabel(value: string | null): string | null {
  if (!value) return null;
  return value in DOCUMENT_KINDS ? DOCUMENT_KINDS[value as KycDocumentKind].label : value;
}

export function entityTypeLabel(value: string | null): string | null {
  if (!value) return null;
  return value in ENTITY_TYPES ? ENTITY_TYPES[value as KycEntityType] : value;
}

/**
 * Does this look like an Aadhaar rather than a business-registry identifier?
 *
 * Mirrors `ck_kyc_records_document_ref_is_not_an_aadhaar`, and the migration's argument
 * is the one worth repeating: an Aadhaar is exactly twelve digits and none of the
 * permitted registry identifiers is (GSTIN 15, CIN 21, LLPIN 8, Udyam 19), so a bare
 * twelve-digit value in that field is a DPDP incident being typed in.
 *
 * The database is the enforcement. This exists so the value is never TRANSMITTED at
 * all — the one class of mistake where a server-side refusal is already too late,
 * because by then someone's Aadhaar has crossed the wire and is in an access log.
 *
 * Deliberately stricter than the constraint in one respect: we test the TRIMMED value,
 * so " 123456789012 " is refused here even though Postgres would store it. A number
 * with a stray space around it is the same number.
 */
export function looksLikeAadhaar(documentRef: string | null | undefined): boolean {
  return /^\d{12}$/.test((documentRef ?? "").trim());
}

/**
 * Why this verification cannot be recorded yet, or `null` when it can.
 *
 * The auditor's four questions, asked BEFORE the round-trip instead of arriving as a
 * refusal after it — the doctrine `grantBlockReason` and `useWriteAccess` already
 * follow on the client realm.
 *
 * It is a PREVIEW, never the enforcement. Behind it stand two layers that stay:
 * `record_kyc_verification` pre-empts the missing `document_ref` and the missing
 * `rejection_reason` with problem+json, and
 * `ck_kyc_records_verified_names_its_evidence` /
 * `ck_kyc_records_rejected_names_its_reason` /
 * `ck_kyc_records_document_ref_is_not_an_aadhaar` refuse the row underneath that.
 *
 * NOTE for whoever owns the API: the route pre-empts only two of the four. A `verified`
 * record with no `document_kind`, and an Aadhaar-shaped `document_ref`, are refused by
 * the CHECK constraints alone — so they would reach an operator as a 500 out of an
 * IntegrityError rather than as a message naming the field. That is why both are
 * blocked here, and it is a gap in `admin/routes.py`, not something this form fixes.
 */
export function recordBlockReason(body: KycRecordIn): string | null {
  if (looksLikeAadhaar(body.document_ref)) {
    return (
      "That is twelve digits, which is an Aadhaar, not a business registry number. " +
      "Calevate never records an individual's identity document — use the entity's " +
      "CIN, GSTIN, LLPIN or Udyam number instead."
    );
  }
  if (body.status === "verified") {
    if (!body.document_kind) {
      return "A verified record has to name which registry document the business was checked against.";
    }
    if (!(body.document_ref ?? "").trim()) {
      return "A verified record has to carry that document's registry number.";
    }
  }
  if (body.status === "rejected" && !(body.rejection_reason ?? "").trim()) {
    return "A rejection has to say what was missing or wrong — otherwise nobody can close the ticket.";
  }
  return null;
}

/**
 * The draft as the API wants it: trimmed, with empty fields sent as `null`.
 *
 * `null` on this endpoint does NOT mean "clear it". `record_kyc` COALESCEs every
 * optional column against what is stored, so a blank field leaves the filed value
 * alone — except `rejection_reason`, which is assigned outright and therefore IS
 * cleared by a blank. The form prefills from the stored record so this rarely bites,
 * and the screen says it out loud where it can.
 */
export function toRecordBody(body: KycRecordIn): KycRecordIn {
  const text = (value: string | null | undefined) => {
    const trimmed = (value ?? "").trim();
    return trimmed === "" ? null : trimmed;
  };
  return {
    status: body.status,
    entity_type: body.entity_type ?? null,
    document_kind: body.document_kind ?? null,
    document_ref: text(body.document_ref),
    signatory_name: text(body.signatory_name),
    evidence_ref: text(body.evidence_ref),
    rejection_reason: text(body.rejection_reason),
  };
}

/**
 * This account's own verification state — client realm, `org:read`, non-mutating.
 *
 * No `refetchInterval`. A blocked client refreshing this page is the expected
 * behaviour, and the route deliberately writes no audit row so that polling stays
 * cheap; a timer would still be a load generator on a page whose answer changes when a
 * human at Calevate does something, which is minutes-to-days, not seconds. Refetch on
 * focus (TanStack Query's default) covers the case that actually matters: the client
 * coming back to the tab after we told them it had cleared.
 */
export function useKycRecord(session: Session): UseQueryResult<KycRecord> {
  return useQuery({
    queryKey: ["kyc", session.orgSlug],
    queryFn: () => apiRequest<KycRecord>(session, KYC_PATH),
  });
}
