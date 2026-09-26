import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AutodialerNoticePanel } from "@/app/c/[slug]/agreements/AutodialerNoticePanel";
import type { AutodialerNotice } from "@/lib/api/autodialerNotice";
import type { Me } from "@/lib/api/client";

import { renderClientPage } from "./harness";

/**
 * Who may record the autodialer notice.
 *
 * `GET /v1/compliance/autodialer-notice` is `org:read`, so staff see the panel on the
 * agreements screen; `POST` is `org:manage`, which only the owner holds
 * (`core/rbac.ROLE_PERMISSIONS`). A form offered to staff is three answers typed and refused.
 */

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

const RECORDED: AutodialerNotice = {
  recorded: true,
  state: "notified",
  access_provider: "Airtel",
  objective: "Appointment reminders",
  notified_on: "2026-09-01",
  notice_reference: null,
  effective: true,
};

function routes(who: Me) {
  return { "/v1/me": who, "/v1/compliance/autodialer-notice": RECORDED };
}

describe("the autodialer notice form", () => {
  it("is open to an owner", async () => {
    await renderClientPage(
      <AutodialerNoticePanel />,
      routes(me("owner", ["org:read", "org:manage"])),
    );
    const withdraw = await screen.findByRole("button", {
      name: "I have withdrawn this notice",
    });
    await waitFor(() => expect(withdraw.matches(":disabled")).toBe(false));
  });

  it("is closed to staff, who are told why", async () => {
    const { calls } = await renderClientPage(
      <AutodialerNoticePanel />,
      routes(me("staff", ["org:read"])),
    );

    expect(
      await screen.findByText("Only an account owner can record or withdraw this notice."),
    ).toBeTruthy();
    const withdraw = screen.getByRole("button", { name: "I have withdrawn this notice" });
    expect(withdraw.matches(":disabled")).toBe(true);
    expect(
      screen.getByRole("textbox", { name: "Which operator did you tell?" }).matches(":disabled"),
    ).toBe(true);

    fireEvent.click(withdraw);
    expect(calls.some((call) => call.method === "POST")).toBe(false);
  });
});
