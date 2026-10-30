import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CallingNumbersPage from "@/app/admin/calling-numbers/page";
import { FILING_BOARD_PATH, markFiledPath, type FilingBoard } from "@/lib/api/callingNumberFilings";

import { renderAdminPage } from "./harness";

/**
 * The operations board of numbers clients authorised us to register (D-941, amended 30 Oct
 * 2026): what it shows, what "Mark filed" sends, and that it stays closed to an operator
 * without `admin:tenants`.
 */

const TENANT = "0192f0aa-7777-7000-8000-000000000001";

function board(over: Partial<FilingBoard> = {}): FilingBoard {
  return {
    enforced_from: "2026-11-17",
    alarm_from: "2026-11-10",
    alarm: true,
    clients: [
      {
        tenant_id: TENANT,
        name: "Sri Traders",
        slug: "sri-traders",
        authorised_on: "2026-10-30",
        numbers: [
          { number: "+919848022338", filed_on: null, filing_reference: null },
          { number: "+914049001234", filed_on: "2026-11-02", filing_reference: "ACK-1" },
        ],
        unfiled: 1,
      },
    ],
    ...over,
  };
}

const ADMIN = { user_id: "a1", realm: "admin", role: "operator", impersonating: false };

describe("the calling numbers board", () => {
  it("lists what is filed and what is not, and marks a number filed", async () => {
    const { calls } = renderAdminPage(<CallingNumbersPage />, {
      "/v1/admin/me": { ...ADMIN, permissions: ["org:read", "admin:tenants"] },
      [FILING_BOARD_PATH]: board(),
      [`POST ${markFiledPath(TENANT)}`]: board().clients[0],
    });
    expect(await screen.findByText("Sri Traders")).toBeTruthy();
    expect(screen.getByText("Not filed")).toBeTruthy();
    expect(screen.getByText(/ACK-1/)).toBeTruthy();
    expect(screen.getByText(/Register these before/)).toBeTruthy();

    const mark = screen.getByRole("button", { name: "Mark filed" });
    await waitFor(() => expect(screen.getByLabelText("Reference").matches(":disabled")).toBe(false));
    expect(mark.matches(":disabled")).toBe(true);
    fireEvent.change(screen.getByLabelText("Reference"), { target: { value: " ACK-9 " } });
    await waitFor(() => expect(mark.matches(":disabled")).toBe(false));
    fireEvent.click(mark);

    await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
    const sent = JSON.parse(calls.find((call) => call.method === "POST")?.body ?? "{}");
    expect(sent.numbers).toEqual(["+919848022338"]);
    expect(sent.filing_reference).toBe("ACK-9");
    expect(sent.filed_on).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("is read-only to an operator without admin:tenants", async () => {
    const { calls } = renderAdminPage(<CallingNumbersPage />, {
      "/v1/admin/me": { ...ADMIN, permissions: ["org:read"] },
      [FILING_BOARD_PATH]: board(),
    });
    expect(await screen.findByText("Sri Traders")).toBeTruthy();
    const mark = screen.getByRole("button", { name: "Mark filed" });
    await waitFor(() => expect(screen.getByLabelText("Reference").matches(":disabled")).toBe(true));
    fireEvent.click(mark);
    expect(calls.some((call) => call.method === "POST")).toBe(false);
  });

  it("says so when no client has authorised numbers", async () => {
    renderAdminPage(<CallingNumbersPage />, {
      "/v1/admin/me": { ...ADMIN, permissions: ["org:read", "admin:tenants"] },
      [FILING_BOARD_PATH]: board({ clients: [] }),
    });
    expect(await screen.findByText("No client has authorised numbers yet.")).toBeTruthy();
  });
});
