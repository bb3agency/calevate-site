import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CallingNumbers, WE_REGISTER } from "@/app/c/[slug]/verify-business/CallingNumbers";
import { AnnouncementBar, platformAnnouncementProps } from "@/components/arc/announcement-bar";
import { shortDay, type CallingNumberDeclaration } from "@/lib/api/autodialerNotice";
import type { Me } from "@/lib/api/client";

import { renderClientPage } from "./harness";

/**
 * The calling numbers card (D-941, amended 30 Oct 2026): the client confirms its numbers
 * and authorises Calevate to register them. What it shows before and after the
 * enforcement date, what it sends (no date, no reference), and who may press it.
 * `POST` is `org:manage`.
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
      reason: "Confirm your calling numbers to place calls. Incoming calls still work.",
    },
    attestation_version: 2,
    attestation_text: "On behalf of this business I confirm the numbers listed.",
    attestation_sha256: "a".repeat(64),
    ...over,
  };
}

describe("the calling numbers card", () => {
  it("asks for confirmation before the date, prefilled, and sends no date or reference", async () => {
    const { calls } = await renderClientPage(<CallingNumbers pageFacts={[]} />, {
      "/v1/me": OWNER,
      [PATH]: declaration(),
      [`POST ${PATH}`]: declaration({
        recorded: true,
        state: "notified",
        notified_on: "2026-10-30",
        declared_clis: ["+919848022338", "+914049001234"],
        attested: true,
        attested_version: 2,
        effective: true,
        undeclared_clis: [],
        blocker: null,
      }),
    });

    expect(await screen.findByText("Confirm your calling numbers before 17 Nov")).toBeTruthy();
    expect(screen.getByText("Calling numbers")).toBeTruthy();
    // The client files nothing itself: no date field and no reference field.
    expect(screen.queryByLabelText(/Declared on/)).toBeNull();
    expect(screen.queryByLabelText(/Reference/)).toBeNull();
    expect(document.querySelector('input[type="date"]')).toBeNull();
    expect(document.querySelector('input[type="text"]')).toBeNull();
    expect(screen.getByText(WE_REGISTER)).toBeTruthy();
    expect(WE_REGISTER).toBe("Calevate registers them with the telephone company for you.");

    const boxes = screen.getAllByRole("checkbox");
    // Two rented numbers, ticked, and the authorisation, not ticked.
    expect(boxes.filter((box) => (box as HTMLInputElement).checked)).toHaveLength(2);
    const confirm = screen.getByRole("button", { name: "Confirm numbers" });
    expect(confirm.matches(":disabled")).toBe(true);

    fireEvent.click(screen.getByRole("checkbox", { name: /On behalf of this business/ }));
    await waitFor(() => expect(confirm.matches(":disabled")).toBe(false));
    fireEvent.click(confirm);

    await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
    const sent = JSON.parse(calls.find((call) => call.method === "POST")?.body ?? "{}");
    expect(sent).toEqual({
      declared_clis: ["+919848022338", "+914049001234"],
      attestation_version: 2,
      attestation_sha256: "a".repeat(64),
      withdraw: false,
    });
    expect(await screen.findByRole("button", { name: "Change" })).toBeTruthy();
    expect(screen.getByText("Confirmed on 30 Oct.")).toBeTruthy();
  });

  it("asks again when the account confirmed on an older wording", async () => {
    await renderClientPage(<CallingNumbers pageFacts={[]} />, {
      "/v1/me": OWNER,
      [PATH]: declaration({
        recorded: true,
        state: "notified",
        notified_on: "2026-10-30",
        declared_clis: ["+919848022338"],
        attested: false,
        attested_version: 1,
      }),
    });
    expect(await screen.findByText("Confirm your calling numbers again before 17 Nov")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Confirm numbers" })).toBeTruthy();
  });

  it("says outgoing calls are paused once the date has come", async () => {
    await renderClientPage(<CallingNumbers pageFacts={[]} />, {
      "/v1/me": OWNER,
      [PATH]: declaration({ enforced: true }),
    });
    expect(
      await screen.findByText("Outgoing calls are paused. Confirm your numbers."),
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
    const confirm = await screen.findByRole("button", { name: "Confirm numbers" });
    await waitFor(() => expect(screen.getAllByRole("checkbox")[0].matches(":disabled")).toBe(true));
    fireEvent.click(confirm);
    expect(calls.some((call) => call.method === "POST")).toBe(false);
  });
});

describe("the banner that sends accounts to the card", () => {
  it("renders the D-941 announcement as the migration writes it, with its button", () => {
    // `alembic/versions/c4e1a9b7d305_*.py` NEW_MESSAGE / NEW_LABEL; the row is the source.
    const announcement = {
      message:
        "From 17 Nov, the law needs the numbers your agent calls from to be registered. " +
        "Confirm your calling numbers so your calls keep going.",
      tone: "warning" as const,
      link_url: "/verify-business#calling-numbers",
      link_label: "Confirm numbers",
    };
    render(<AnnouncementBar {...platformAnnouncementProps(announcement)} />);
    expect(screen.getByText(announcement.message)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Confirm numbers" }).getAttribute("href")).toContain(
      "#calling-numbers",
    );
  });
});

describe("dates on the card", () => {
  it("reads a calendar day without a zone shift", () => {
    expect(shortDay("2026-11-17")).toBe("17 Nov");
  });
});
