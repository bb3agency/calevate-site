import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import MessagingConsentPage from "@/app/c/[slug]/messaging-consent/page";
import type { MessagingConsent } from "@/lib/api/messagingConsent";
import type { Me } from "@/lib/api/client";

import { renderClientPage } from "./harness";

/**
 * "May we message them?" is answered by `messageable`, never recomputed from `status`.
 *
 * A year-old opt-in still reads `status: "granted"`. The campaign worker refuses it,
 * because the server's `messageable` is "granted AND not stale" — so a screen that
 * derived the verdict from `status` would show a green tick beside a number the product
 * will silently skip, and the client would find out when their follow-ups stopped
 * arriving. Both fields are on the same model and both type-check.
 */

const LOOKUP_PATH = "/v1/compliance/messaging-consent/lookup";
const PHONE = "+919876543210";

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

describe("messaging consent verdict", () => {
  it("does NOT say messageable for a granted opt-in the server has ruled stale", async () => {
    const { container } = await lookUp(
      consent({ messageable: false, status: "granted", expires_at: "2026-05-30T10:00:00Z" }),
    );

    await screen.findByText("Not messageable — their opt-in has expired.");
    expect(container.textContent).not.toContain("You may send this person WhatsApp messages.");
  });

  it("says messageable only when the server does", async () => {
    await lookUp(consent());
    await screen.findByText("You may send this person WhatsApp messages.");
  });

  it("reads a withdrawal and a refusal as different sentences", async () => {
    const withdrawn = await lookUp(consent({ messageable: false, status: "withdrawn" }));
    await screen.findByText("Not messageable — they asked us to stop.");
    withdrawn.unmount();

    await lookUp(consent({ messageable: false, status: "declined" }));
    await screen.findByText("Not messageable — they were asked and said no.");
  });

  it("treats a status this build predates as not messageable", async () => {
    // `messageable: false` with an unfamiliar status must still land on a "no". The
    // final branch is neutral in tone and negative in answer, which is the right pair.
    const { container } = await lookUp(
      consent({ messageable: false, status: "suppressed_by_regulator" }),
    );

    await screen.findByText(/^Not messageable/);
    expect(container.textContent).not.toContain("You may send this person WhatsApp messages.");
  });

  it("keeps the number out of the URL and puts it in the body (hard rule 6)", async () => {
    // Access logs, referrers and browser history. The lookup is a POST for exactly this
    // reason, and it is the sort of thing that quietly becomes a GET during a refactor
    // because a GET is "more correct" for a read.
    const { calls } = await lookUp(consent());
    await screen.findByText("You may send this person WhatsApp messages.");

    const lookup = calls.find((call) => call.path === LOOKUP_PATH);
    expect(lookup?.method).toBe("POST");
    expect(lookup?.url).not.toContain("9876543210");
    expect(lookup?.body).toContain("9876543210");
  });
});
