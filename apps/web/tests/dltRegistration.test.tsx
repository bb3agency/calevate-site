import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import VerificationPage from "@/app/c/[slug]/verification/page";
import { PE_REGISTRATION_PATH, type PeRegistration } from "@/lib/api/dltRegistration";
import { KYC_PATH, type KycRecord } from "@/lib/api/kyc";

import { problem, renderClientPage } from "./harness";

/**
 * The client's own DLT Principal Entity registration, on `/verification`.
 *
 * `GET /v1/compliance/dlt-registration` shipped with no caller: the operator console could
 * WRITE a client's PE registration and the client could not READ it, while three of the
 * campaign launch gate's refusals (`pe_registration_missing`,
 * `pe_registration_not_active`, `tm_link_not_active`) are about nothing else. A client
 * whose campaigns were being refused had the refusal and not the fact.
 *
 * Four things worth pinning, and the middle two are the expensive ones:
 *
 * 1. **The verdict comes from `is_active`, never from the two statuses recombined here.**
 *    The server computes the predicate the launch gate asks; a screen that rebuilt it
 *    would eventually disagree with the gate that actually refuses the campaign.
 * 2. **A failed read is a refusal, not "nothing filed yet"** (BUILD-LOG §52). Those two
 *    states would render the same card and mean opposite things — one sends a client to
 *    their account manager over a registration that may be perfectly active.
 * 3. **A failed read on ONE half does not blank the other.** The two reads are
 *    independent, and the client most likely to hit a failing KYC read is the client
 *    trying to find out why their campaigns stopped.
 * 4. **Nothing here is a control.** The write is operator-only for the same reason the
 *    KYC write is: a client who could set these statuses would be marking their own
 *    compliance gate green.
 */

const KYC: KycRecord = {
  recorded: true,
  status: "verified",
  is_verified: true,
  number_purchase_available: false,
  rejection_reason: null,
  document_kind: "gstin",
  document_ref: "29ABCDE1234F1Z5",
  entity_type: "private_limited",
  evidence_ref: "dpdp/kyc/2026/0007",
  signatory_name: "A Reddy",
  submitted_at: "2026-02-01T06:00:00Z",
  verified_at: "2026-03-01T06:00:00Z",
};

function registration(over: Partial<PeRegistration> = {}): PeRegistration {
  return {
    recorded: true,
    status: "active",
    tm_link_status: "active",
    pe_id: "1101234567890123456",
    entity_name: "Sri Clinic Pvt Ltd",
    registered_at: "2026-01-05T06:00:00Z",
    verified_at: "2026-02-01T06:00:00Z",
    is_active: true,
    // Calevate's OWN telemarketer registration, which rides on this response so the
    // client can name us on the registrar's portal (it replaced `{{DLT_TELEMARKETER_ID}}`
    // in the published Acceptable Use Policy).
    calevate_tm_id: "1234567890123456789",
    calevate_tm_active: true,
    ...over,
  };
}

function render(pe: unknown, kyc: unknown = KYC) {
  return renderClientPage(<VerificationPage />, {
    [KYC_PATH]: kyc,
    [PE_REGISTRATION_PATH]: pe,
  });
}

describe("the client's DLT registration on /verification", () => {
  it("reads the client-realm route, once, and prints what is on file", async () => {
    const { container, calls } = await render(registration());

    await screen.findByText("Your business is registered to run campaigns.");
    expect(calls.filter((c) => c.path === PE_REGISTRATION_PATH)).toHaveLength(1);
    // The registrar's identifiers, so the client has something to quote at us.
    expect(container.textContent).toContain("1101234567890123456");
    expect(container.textContent).toContain("Sri Clinic Pvt Ltd");
    // `verified_at` is when WE last checked, and is labelled as that rather than as a
    // registration date — the route's docstring is explicit about the difference.
    expect(container.textContent).toContain("We last checked");
  });

  it("names the two statuses separately, because they fail to different desks", async () => {
    // The registrar approves the entity; the CLIENT authorises Calevate as its
    // telemarketer on the registrar's portal. A single collapsed verdict would send half
    // the clients who read this to the wrong place — which is exactly why the launch gate
    // emits `pe_registration_not_active` and `tm_link_not_active` as different blockers.
    const { container } = await render(
      registration({ status: "active", tm_link_status: "revoked", is_active: false }),
    );

    await screen.findByText("Your DLT registration is not active yet.");
    expect(container.textContent).toContain("Calevate authorised to dial for you: Withdrawn");
    expect(container.textContent).toContain("Your business as a Principal Entity: Active");
    // Inbound is unaffected and it is said, for the same reason the KYC half says it.
    expect(container.textContent).toContain("Calls coming IN are unaffected");
  });

  it("never renders an active verdict off the statuses alone", async () => {
    // The server's `is_active` is the whole verdict. A payload whose two statuses read
    // `active` while the server says the predicate is false must NOT produce the green
    // box — that is the day this screen and the launch gate would disagree, and it is the
    // reason `is_active` is computed server-side at all.
    const { container } = await render(
      registration({ status: "active", tm_link_status: "active", is_active: false }),
    );

    await screen.findByText("Your DLT registration is not active yet.");
    expect(container.textContent).not.toContain("Your business is registered to run campaigns.");
    expect(container.textContent).toContain(
      "Outbound campaigns cannot launch until both lines below are active.",
    );
  });

  it("renders a refusal, not an empty state, when the read fails", async () => {
    // §52's central case. "We have not filed a DLT registration for your business" is a
    // FACT about an account; a 503 is a fact about us. Printing the first for the second
    // sends a client chasing a registration that may already be active.
    const { container } = await render(
      problem(503, {
        title: "Service unavailable",
        detail: "We could not read your DLT registration.",
        retryable: true,
      }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("We could not read your DLT registration.");
    expect(container.textContent).not.toContain(
      "We have not filed a DLT registration for your business.",
    );
    expect(container.textContent).not.toContain("Your business is registered to run campaigns.");
    expect(container.textContent).not.toContain("Your DLT registration is not active yet.");
    // A refusal with no way forward is the other half of the defect.
    expect(screen.getByRole("button", { name: /try again/i })).toBeTruthy();
  });

  it("distinguishes nothing-on-file from a failed read", async () => {
    // `recorded: false` is a 200 and the normal state of a new account — the route refuses
    // to answer it with a 404 precisely so this stays a state.
    const { container } = await render(
      registration({
        recorded: false,
        status: null,
        tm_link_status: null,
        pe_id: null,
        entity_name: null,
        registered_at: null,
        verified_at: null,
        is_active: false,
      }),
    );

    await screen.findByText("We have not filed a DLT registration for your business.");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(container.textContent).toContain("Ask your account manager to start it.");
  });

  it("keeps the DLT half readable when the KYC half fails", async () => {
    // The two reads are independent and are composed rather than nested for this reason:
    // the client whose KYC read is failing is very often the client trying to find out why
    // their campaigns are refused, and that answer lives in the other section.
    const { container } = await render(
      registration({ recorded: true, status: "submitted", tm_link_status: "pending", is_active: false }),
      problem(503, { title: "Service unavailable", detail: "KYC is down." }),
    );

    await screen.findByText("Your DLT registration is not active yet.");
    expect(container.textContent).toContain("KYC is down.");
    expect(container.textContent).toContain("Your business as a Principal Entity: With the registrar");
  });

  it("offers no control to change either status", async () => {
    // There is no client-realm write, and there should never be one. The only button this
    // screen may ever grow is a retry on a refusal — so under a clean read, none.
    const { container } = await render(registration({ is_active: false, status: "suspended" }));

    await screen.findByText("Your DLT registration is not active yet.");
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(container.querySelectorAll("form")).toHaveLength(0);
  });

  it("prints an unnameable status verbatim rather than inventing a meaning", async () => {
    // A status this build has no copy for still has to give the client a word to quote at
    // us, and must not be dressed as one we do understand.
    const { container } = await render(
      registration({ status: "under_appeal", is_active: false }),
    );

    await screen.findByText("Your DLT registration is not active yet.");
    expect(container.textContent).toContain("under_appeal");
    expect(container.textContent).toContain(
      "Ask your account manager what this state means for your campaigns.",
    );
  });
});
