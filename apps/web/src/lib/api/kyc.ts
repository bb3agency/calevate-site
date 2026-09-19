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
 *   never re-derived here.** (`number_purchase_available` is false for every account
 *   everywhere: Calevate does not supply telephone numbers — the client takes the
 *   connection on their own operator account. See `campaigns/provisioning.py`.) "Is `in_review` good enough" is the question the dispatch
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

import { hasKey, lookup } from "@/lib/lookup";

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

/**
 * `status` is a plain string on the wire; only render copy for members we know.
 *
 * `hasKey` rather than `in`, here and in the four helpers below: `in` walks the
 * prototype chain, so `isKnownKycStatus("constructor")` answered TRUE and the caller
 * then read `.label`/`.tone` off `Object` — a verdict box with no headline and no tone,
 * instead of the "we cannot name this status" fallback that exists for exactly this.
 * Same defect and same fix as `holdRule` (holds.ts), and now literally the same
 * function: `lib/lookup.ts` argues why the guard is centralised rather than repeated.
 *
 * `hasKey` and not `lookup` because the CALLER wants the narrowed type — the admin
 * form puts this value in an `<option value>` the API's `Literal` has to accept.
 */
export function isKnownKycStatus(value: string): value is KycStatus {
  return hasKey(KYC_STATUS_COPY, value);
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
  return hasKey(DOCUMENT_KINDS, value) ? value : null;
}

export function asEntityType(value: string | null): KycEntityType | null {
  return hasKey(ENTITY_TYPES, value) ? value : null;
}

/**
 * The two LABEL helpers fail in the opposite direction to the two above, on purpose.
 *
 * A `<select>` cannot hold a member it has no option for, so `as…` returns `null` and
 * the form leaves what is filed alone. A LABEL has no such constraint: showing an
 * operator the raw stored string beats showing them nothing, because the thing they
 * most need to see is precisely the value this build cannot name. Read-only display
 * fails VISIBLE; anything that feeds a write fails CLOSED.
 */
export function documentKindLabel(value: string | null): string | null {
  if (!value) return null;
  return lookup(DOCUMENT_KINDS, value)?.label ?? value;
}

export function entityTypeLabel(value: string | null): string | null {
  if (!value) return null;
  return lookup(ENTITY_TYPES, value) ?? value;
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

/* ==================================================================================
 * THE CARRIER COMPLIANCE APPLICATION — the OTHER gate in front of a phone connection
 * ==================================================================================
 *
 * KYC above is OUR check on the subscriber. This is the CARRIER's check on the same
 * business, and the two are not interchangeable: `assert_carrier_application_accepted`
 * refuses a number purchase on `accepted` alone, whatever our own KYC says
 * (`apps/api/compliance/carrier_application.py`).
 *
 * All four surfaces shipped together and the OPS HALF HAD NO CALLER anywhere in this
 * console, which is the failure the route's own module docstring names — "a decision ops
 * cannot record is a client stuck behind a carrier that has already said yes". The
 * client could upload documents and watch them sit at `submitted` for ever, because the
 * only person who can record what the carrier answered had no form to record it in.
 *
 * Three properties of the API that the console must not smooth over:
 *
 * - **An operator may record four states, not six.** `not_started` is where a row
 *   begins and `submitted` is the CLIENT's act, so neither is a decision anybody makes;
 *   `CarrierDecision` is the narrower union and the form is built from it.
 * - **Each decision has its own legal source states** (`OPERATOR_DECISIONS`, derived
 *   from the transition table). Recording one from the wrong state is a 409 out of the
 *   CAS, so the source states are mirrored here as a PREVIEW — never as the enforcement.
 * - **`is_accepted` is the SERVER's predicate.** "Is `submitted` good enough for a
 *   number" is the question the purchase gate answers; a console that answered it for
 *   itself would eventually disagree with the gate. Same rule `is_verified` follows.
 */

/** This client's application, as the ops read returns it. Absence is `recorded: false`. */
export type CarrierApplication = Schemas["CarrierApplicationOut"];
/** The operator's write — one decision, plus whatever that decision has to name. */
export type CarrierDecisionIn = Schemas["CarrierDecisionIn"];
export type CarrierDecisionOut = Schemas["CarrierDecisionOut"];
/** The six states an application can be IN. */
export type CarrierStatus = NonNullable<CarrierApplication["status"]>;
/** The four an OPERATOR can move it into. */
export type CarrierDecision = CarrierDecisionOut["status"];

export interface CarrierStatusCopy {
  label: string;
  /** What this state means for the client, in the operator's reading of it. */
  meaning: string;
  tone: "ok" | "warn" | "stop" | "neutral";
}

/**
 * The six states, as a `Record` over the GENERATED union — the same device, and for the
 * same reason, as `KYC_STATUS_COPY`: a seventh member added by the API stops this file
 * compiling instead of rendering a state nobody wrote copy for.
 */
export const CARRIER_STATUS_COPY: Record<CarrierStatus, CarrierStatusCopy> = {
  not_started: {
    label: "Not started",
    meaning: "Nothing has been sent to the carrier. The client uploads first.",
    tone: "neutral",
  },
  documents_required: {
    label: "Documents required",
    meaning: "The carrier asked for more paperwork. The client's move.",
    tone: "warn",
  },
  submitted: {
    label: "With the carrier",
    meaning: "Sent and awaiting their answer. Recording that answer is our move.",
    tone: "neutral",
  },
  accepted: {
    label: "Accepted",
    meaning: "The carrier approved this business. Number provisioning is open.",
    tone: "ok",
  },
  rejected: {
    label: "Rejected",
    meaning: "The carrier refused it. The client is shown the reason and re-applies.",
    tone: "stop",
  },
  expired: {
    label: "Expired or suspended",
    meaning: "An approval that has lapsed. The client must apply again.",
    tone: "warn",
  },
};

export interface CarrierDecisionCopy {
  /** What the operator is choosing. */
  label: string;
  /** What recording it DOES — the blast radius, in the ops order. */
  effect: string;
  /** The states this decision may be recorded FROM (`OPERATOR_DECISIONS`). */
  from: readonly CarrierStatus[];
}

/**
 * The four decisions, with the states each may come from.
 *
 * Mirrored from `OPERATOR_DECISIONS`, which the API derives from
 * `CARRIER_APPLICATION_TRANSITIONS` rather than retyping — and the mirror is a PREVIEW:
 * the CAS in `record_carrier_decision` is the enforcement and answers 409 naming the
 * state it found. It is here so an operator reads "this application is not with the
 * carrier yet" beside the control instead of after a round trip.
 */
export const CARRIER_DECISIONS: Record<CarrierDecision, CarrierDecisionCopy> = {
  accepted: {
    label: "Accepted",
    effect:
      "Opens number provisioning for this client. Needs the carrier's own application " +
      "reference, because a number purchase has to quote it.",
    from: ["submitted"],
  },
  documents_required: {
    label: "More documents needed",
    effect: "Sends the client back for more paperwork. They can re-submit from their own screen.",
    from: ["submitted"],
  },
  rejected: {
    label: "Rejected",
    effect: "Refused. The client is shown the reason you record and can apply again.",
    from: ["submitted"],
  },
  expired: {
    label: "Expired or suspended",
    effect:
      "Records an approval that has lapsed or been suspended. Number provisioning closes " +
      "and the client re-applies.",
    from: ["accepted"],
  },
};

/** The stored status as a member of the union, or `null` when this build cannot name it. */
export function asCarrierStatus(value: string | null | undefined): CarrierStatus | null {
  return hasKey(CARRIER_STATUS_COPY, value) ? value : null;
}

/**
 * The status as words. Fails VISIBLE — an unnameable status prints as the server sent
 * it, because an unrecognised state on a compliance gate is exactly the one worth
 * reading. Same direction as `documentKindLabel`.
 */
export function carrierStatusLabel(value: string | null | undefined): string | null {
  if (!value) return null;
  return lookup(CARRIER_STATUS_COPY, value)?.label ?? value;
}

/**
 * Why this decision cannot be recorded against this application yet, or `null`.
 *
 * Three refusals, each naming what to do next rather than the rule it came from:
 * the API's `carrier_application_id_required` and `carrier_rejection_reason_required`
 * validations, and the CAS's own state check. A blank application (`recorded: false`,
 * `status: null`) is treated as `not_started`, which is what the row would hold.
 */
export function carrierDecisionBlockReason(
  application: CarrierApplication,
  decision: CarrierDecision,
  body: CarrierDecisionIn,
): string | null {
  const current = asCarrierStatus(application.status) ?? "not_started";
  const spec = CARRIER_DECISIONS[decision];
  if (!spec.from.includes(current)) {
    const from = spec.from.map((state) => CARRIER_STATUS_COPY[state].label).join(" or ");
    return (
      `This application is "${carrierStatusLabel(current)}", and "${spec.label}" can only ` +
      `be recorded while it is "${from}". If the carrier really has answered, check you ` +
      `are on the right client — otherwise a colleague may have recorded this already.`
    );
  }
  if (decision === "accepted" && !(body.carrier_application_id ?? "").trim()) {
    return (
      "An acceptance has to carry the carrier's own application reference — copy it from " +
      "their console. A number purchase quotes it, so an acceptance without it cannot be used."
    );
  }
  if (decision === "rejected" && !(body.rejection_reason ?? "").trim()) {
    return (
      "A rejection has to say why, in the carrier's own words where you have them. The " +
      "client is shown this and is the only person who can fix it."
    );
  }
  return null;
}

/**
 * The decision as the API wants it: trimmed, blanks as `null`, and `carrier_status`
 * never sent.
 *
 * The route accepts EITHER our word or the carrier's (`_resolved_status` refuses both or
 * neither). This console sends ours, always, and deliberately offers no transcription
 * box: the four decisions are named on screen with what each one does, so a second field
 * that maps the carrier's vocabulary onto the same four would be a second way to do one
 * thing — and the one that answers 422 when their console says something unmapped.
 */
export function toCarrierDecisionBody(
  decision: CarrierDecision,
  body: CarrierDecisionIn,
): CarrierDecisionIn {
  const text = (value: string | null | undefined) => {
    const trimmed = (value ?? "").trim();
    return trimmed === "" ? null : trimmed;
  };
  return {
    status: decision,
    carrier_status: null,
    carrier_application_id: text(body.carrier_application_id),
    rejection_reason: text(body.rejection_reason),
  };
}
