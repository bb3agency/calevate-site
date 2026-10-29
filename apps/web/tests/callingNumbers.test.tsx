import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CallingNumbers } from "@/app/c/[slug]/verify-business/CallingNumbers";
import { shortDay, todayIST, type CallingNumberDeclaration } from "@/lib/api/autodialerNotice";
import type { Me } from "@/lib/api/client";

import { renderClientPage } from "./harness";

/**
 * The calling-number declaration card (D-941): what it shows before and after the
 * enforcement date, what it sends, and who may press it. `POST` is `org:manage`.
 */

const PATH = "/v1/compliance/autodialer-notice";

function me(role: "owner" | "staff", permissions: string[]): Me {
  return {
    user_id: "u1",
    realm: "client",
    role,
    permissions,
    impersonating: false,
    withheld_acts: [],
    organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
  };
}

const OWNER = me("owner", ["org:read", "org:manage"]);

function declaration(over: Partial<CallingNumberDeclaration> = {}): CallingNumberDeclaration {
  return {
    recorded: false,
    state: null,
    notified_on: null,
    notice_reference: null,
    declared_clis: [],
    attested: false,
    attested_version: null,
    effective: false,
    rented_numbers: ["+919848022338", "+914049001234"],
    undeclared_clis: ["+919848022338"],
    applies: true,
    enforced_from: "2026-11-17",
    enforced: false,
    blocker: {
      rule: "a2p_declaration_missing",
      reason: "Declare your calling numbers to place calls. Incoming calls still work.",
    },
    attestation_version: 1,
    attestation_text: "On behalf of this business I confirm the numbers listed.",
    attestation_sha256: "a".repeat(64),
    ...over,
  };
}

describe("the calling numbers card", () => {
  it("asks for the declaration before the date, prefilled with the rented numbers", async () => {
    const { calls } = await renderClientPage(<CallingNumbers pageFacts={[]} />, {
      "/v1/me": OWNER,
      [PATH]: declaration(),
      [`POST ${PATH}`]: declaration({
        recorded: true,
        state: "notified",
        notified_on: "2026-10-30",
        declared_clis: ["+919848022338", "+914049001234"],
        attested: true,
        attested_version: 1,
        effective: true,
        undeclared_clis: [],
        blocker: null,
      }),
    });

    expect(await screen.findByText("Declare your calling numbers before 17 Nov")).toBeTruthy();
    const boxes = screen.getAllByRole("checkbox");
    // Two rented numbers, ticked, and the attestation, not ticked.
    expect(boxes.filter((box) => (box as HTMLInputElement).checked)).toHaveLength(2);
    const declare = screen.getByRole("button", { name: "Declare numbers" });
    expect(declare.matches(":disabled")).toBe(true);

    fireEvent.click(screen.getByRole("checkbox", { name: /On behalf of this business/ }));
    await waitFor(() => expect(declare.matches(":disabled")).toBe(false));
    fireEvent.click(declare);

    await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
    const sent = JSON.parse(calls.find((call) => call.method === "POST")?.body ?? "{}");
    expect(sent).toMatchObject({
      declared_clis: ["+919848022338", "+914049001234"],
      notified_on: todayIST(),
      notice_reference: null,
      attestation_version: 1,
      attestation_sha256: "a".repeat(64),
      withdraw: false,
    });
    expect(await screen.findByRole("button", { name: "Change" })).toBeTruthy();
  });

  it("says outgoing calls are paused once the date has come", async () => {
    await renderClientPage(<CallingNumbers pageFacts={[]} />, {
      "/v1/me": OWNER,
      [PATH]: declaration({ enforced: true }),
    });
    expect(
      await screen.findByText("Outgoing calls are paused. Declare your numbers."),
    ).toBeTruthy();
  });

  it("warns when an agent's number is left unticked", async () => {
    await renderClientPage(<CallingNumbers pageFacts={[]} />, {
      "/v1/me": OWNER,
      [PATH]: declaration(),
    });
    fireEvent.click(await screen.findByRole("checkbox", { name: "+91 98480 22338" }));
    expect(screen.getByText(/An agent.s number is unticked/)).toBeTruthy();
  });

  it("shows nothing to an account whose agents only answer", async () => {
    const { container } = await renderClientPage(
      <CallingNumbers pageFacts={[]} />,
      { "/v1/me": OWNER, [PATH]: declaration({ applies: false, blocker: null }) },
    );
    await waitFor(() => expect(container.querySelector("#calling-numbers")).toBeNull());
  });

  it("is closed to staff, who are told why, and sends nothing", async () => {
    const { calls } = await renderClientPage(<CallingNumbers pageFacts={[]} />, {
      "/v1/me": me("staff", ["org:read"]),
      [PATH]: declaration(),
    });
    const declare = await screen.findByRole("button", { name: "Declare numbers" });
    await waitFor(() => expect(screen.getAllByRole("checkbox")[0].matches(":disabled")).toBe(true));
    fireEvent.click(declare);
    expect(calls.some((call) => call.method === "POST")).toBe(false);
  });
});

describe("dates on the card", () => {
  it("reads a calendar day without a zone shift", () => {
    expect(shortDay("2026-11-17")).toBe("17 Nov");
  });

  it("takes today in India, not in the browser's zone", () => {
    // 20:00 UTC on 30 Oct is already 31 Oct in India.
    expect(todayIST(new Date("2026-10-30T20:00:00Z"))).toBe("2026-10-31");
  });
});
