import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import MessagingConsentPage from "@/app/c/[slug]/messaging-consent/page";
import { StatusBadge } from "@/components/ui";
import type { MessagingConsent } from "@/lib/api/messagingConsent";
import type { Me } from "@/lib/api/client";
import {
  KYC_STATUS_COPY,
  asDocumentKind,
  asEntityType,
  documentKindLabel,
  entityTypeLabel,
  isKnownKycStatus,
} from "@/lib/api/kyc";
import { hasKey, lookup } from "@/lib/lookup";

import { renderClientPage } from "./harness";

/**
 * Every screen that looks a WIRE STRING up in a copy table, asked the one question a
 * type checker cannot ask: what happens when the string names something on
 * `Object.prototype`?
 *
 * `holdRule` and `isKnownKycStatus` were the first two found, and they were found by
 * reading rather than by running — so the interesting question is not those two but
 * whether the shape survives anywhere else. It does, in three distinct disguises, and
 * the disguises fail differently:
 *
 *  1. `value in TABLE` — the original. `in` walks the prototype chain, so the guard
 *     says yes and the caller reads a property off `Object` itself.
 *  2. `TABLE[value] ?? fallback` — looks safe and is not. `??` fires on `undefined`,
 *     and `TABLE["constructor"]` is the `Object` FUNCTION, which is neither `null` nor
 *     `undefined`. The fallback never runs.
 *  3. `TABLE[value]?.field ?? fallback` — accidentally safe, because the property
 *     access on the inherited function yields `undefined` and the `??` finally fires.
 *
 * The third is the reason a blanket find-and-replace would have been the wrong
 * instrument: some of these sites were already correct, by luck rather than intent, and
 * the fix has to leave their BEHAVIOUR alone while removing the luck.
 *
 * The prototype keys used below are the whole realistic set for an object literal:
 * `constructor`, `toString`, `valueOf`, `hasOwnProperty`, `__proto__`. They are not
 * hypothetical wire values — they are what an attacker sends, and separately what a
 * badly-escaped upstream identifier collides with by accident.
 */

const LOOKUP_PATH = "/v1/compliance/messaging-consent/lookup";
const PHONE = "+919876543210";

/** The inherited names a bare object literal actually carries. */
export const PROTOTYPE_KEYS = [
  "constructor",
  "toString",
  "valueOf",
  "hasOwnProperty",
  "__proto__",
] as const;

const ME: Me = {
  impersonating: false,
  permissions: ["leads:read", "leads:dispatch"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

function consent(over: Partial<MessagingConsent> = {}): MessagingConsent {
  return {
    messageable: true,
    status: "granted",
    source: "inbound_call_verbal",
    captured_at: "2026-06-01T10:00:00Z",
    expires_at: "2027-06-01T10:00:00Z",
    ...over,
  };
}

async function lookUp(answer: MessagingConsent) {
  const rendered = await renderClientPage(<MessagingConsentPage />, {
    "/v1/me": ME,
    [LOOKUP_PATH]: answer,
  });
  fireEvent.change(await screen.findByLabelText("Phone number to check"), {
    target: { value: PHONE },
  });
  fireEvent.click(screen.getByRole("button", { name: "Check" }));
  return rendered;
}

/**
 * THE HIGH-WATER MARK OF THIS CLASS OF BUG, and the reason it is tested through the
 * rendered screen rather than against the guard.
 *
 * `MessagingConsentOut.source` is `string | null` on the wire — not a generated union,
 * not narrowed anywhere, straight out of a `consent_ledger` row. `isKnownSource` tested
 * membership with `in`, so `"constructor"` passed the guard, `CONSENT_SOURCES[...]`
 * handed back `Object`, and `describeCapture` called `.label.toLowerCase()` on it. That
 * is a TypeError thrown during render: not a wrong sentence, a BLANK VERDICT BOX on the
 * one screen whose entire job is answering "may we message this person?".
 *
 * Identical to `holdRule` in every respect except that this one is the client's screen
 * rather than the operator's — which makes it worse, not better. An operator files a
 * bug; a client sees a blank box and messages the number anyway.
 */
describe("consent source off the wire", () => {
  it("does not blank the verdict when `source` names an Object.prototype member", async () => {
    for (const inherited of PROTOTYPE_KEYS) {
      const { container, unmount } = await lookUp(consent({ source: inherited }));

      // The verdict must survive. Before the fix this assertion never ran — the render
      // threw inside `describeCapture` and took the test down with the screen.
      await screen.findByText("You may send this person WhatsApp messages.");
      // …and the unnameable source is simply omitted, never rendered as itself and
      // never rendered as `Object`'s stringification.
      expect(container.textContent, inherited).not.toContain("function Object");
      expect(container.textContent, inherited).not.toContain(inherited);
      unmount();
    }
  });

  it("still names a source it does know", async () => {
    const { container } = await lookUp(consent({ source: "inbound_call_verbal" }));
    await screen.findByText("You may send this person WhatsApp messages.");
    expect(container.textContent).toContain("Recorded");
  });
});

describe("lookup", () => {
  const TABLE = { real: "a value" };

  it("does not return an inherited member", () => {
    for (const inherited of PROTOTYPE_KEYS) {
      expect(lookup(TABLE, inherited), inherited).toBeUndefined();
    }
  });

  it("returns undefined — not the prototype's value — so `??` at the call site fires", () => {
    // The whole point. `TABLE["constructor"] ?? "fallback"` yields the `Object`
    // function; `lookup(TABLE, "constructor") ?? "fallback"` yields "fallback".
    for (const inherited of PROTOTYPE_KEYS) {
      expect(lookup(TABLE, inherited) ?? "fallback", inherited).toBe("fallback");
    }
  });

  it("treats a null or absent key as absent rather than throwing", () => {
    // Several callers hold a nullable column (`source: string | null`), and absorbing
    // that here is what keeps a `&&` off every one of those call sites.
    expect(lookup(TABLE, null)).toBeUndefined();
    expect(lookup(TABLE, undefined)).toBeUndefined();
  });

  it("still returns the table's own values", () => {
    expect(lookup(TABLE, "real")).toBe("a value");
  });

  it("reads own keys that happen to shadow a prototype member", () => {
    // A table may legitimately own a key named `toString` — the guard must answer for
    // the TABLE, not for the name.
    expect(lookup({ toString: "mine" }, "toString")).toBe("mine");
  });
});

describe("hasKey", () => {
  it("refuses inherited members and accepts own ones", () => {
    for (const inherited of PROTOTYPE_KEYS) {
      expect(hasKey(KYC_STATUS_COPY, inherited), inherited).toBe(false);
    }
    expect(hasKey(KYC_STATUS_COPY, "verified")).toBe(true);
    expect(hasKey(KYC_STATUS_COPY, null)).toBe(false);
  });
});

/**
 * The KYC helpers fail in TWO directions and the split is deliberate, so both are
 * pinned: anything feeding a WRITE fails closed (`null`, leave the filed value alone),
 * anything feeding a READ fails visible (show the raw value, because an unnameable
 * member is the one an operator most needs to see).
 */
describe("kyc lookups off the wire", () => {
  it("fails CLOSED on the helpers that feed the admin form's <select>", () => {
    for (const inherited of PROTOTYPE_KEYS) {
      expect(isKnownKycStatus(inherited), inherited).toBe(false);
      expect(asDocumentKind(inherited), inherited).toBeNull();
      expect(asEntityType(inherited), inherited).toBeNull();
    }
  });

  it("fails VISIBLE on the label helpers, echoing the value rather than blanking", () => {
    for (const inherited of PROTOTYPE_KEYS) {
      // Before the fix these returned `Object`'s `.label` (`undefined`) and `Object`
      // itself — a blank cell, and a React child that is a function.
      expect(documentKindLabel(inherited), inherited).toBe(inherited);
      expect(entityTypeLabel(inherited), inherited).toBe(inherited);
    }
  });

  it("still names the members it knows", () => {
    expect(isKnownKycStatus("verified")).toBe(true);
    expect(asDocumentKind("gstin")).toBe("gstin");
    expect(documentKindLabel("gstin")).toBe("GSTIN");
    expect(entityTypeLabel("llp")).toBe("Limited Liability Partnership");
  });
});

/**
 * `StatusBadge` is the most-reached lookup in the app — every leads table and every
 * calls table — and its failure is the quiet one: no crash, just a `className` of
 * `function Object() { [native code] }`, which is a handful of nonsense CSS classes
 * that happen to include none of the ones that colour the badge.
 */
describe("StatusBadge with a status off the wire", () => {
  it("falls back to neutral styling instead of stringifying Object into the class list", () => {
    for (const inherited of PROTOTYPE_KEYS) {
      const { container, unmount } = render(<StatusBadge value={inherited} />);
      const span = container.querySelector("span");

      expect(span?.className, inherited).not.toContain("function");
      expect(span?.className, inherited).not.toContain("native code");
      expect(span?.className, inherited).toContain("bg-slate-100");
      // The status itself is still printed: a value we have no colour for is exactly
      // the one worth reading.
      expect(span?.textContent, inherited).toBe(inherited.replace(/_/g, " "));
      unmount();
    }
  });

  it("still colours a status it knows", () => {
    const { container } = render(<StatusBadge value="won" />);
    expect(container.querySelector("span")?.className).toContain("emerald");
  });
});
