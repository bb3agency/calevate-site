import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import { NumberPricePanel, exceedsCeiling } from "@/app/admin/ops/NumberPricePanel";
import { NUMBER_PRICING_PATH, type NumberPrice } from "@/lib/api/numberPricing";

import { problem, stubApi, type Routes } from "./harness";

/**
 * The operator's half of number buying: the API refuses every client purchase until a
 * monthly price is attested at `POST /v1/admin/number-pricing`, and this panel is the only
 * place in the product that can attest it.
 */

const OPERATOR: AdminMe = {
  user_id: "00000000-0000-7000-8000-0000000000a1",
  realm: "admin",
  role: "superadmin",
  permissions: ["admin:tenants"],
};

const READ_ONLY: AdminMe = { ...OPERATOR, role: "support", permissions: [] };

const UNPRICED: NumberPrice = { attested: false };
const PRICED: NumberPrice = {
  attested: true,
  inr_per_month: "499.00",
  source: "Vobiz order form, 1 Oct 2026",
  attested_at: "2026-10-01T06:30:00Z",
};

function renderPanel(routes: Routes) {
  const calls = stubApi(routes);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <NumberPricePanel />
    </QueryClientProvider>,
  );
  return calls;
}

describe("the phone number price panel", () => {
  it("says plainly that clients cannot buy a number until a price is recorded", async () => {
    renderPanel({ [ADMIN_ME_PATH]: OPERATOR, [NUMBER_PRICING_PATH]: UNPRICED });
    expect(await screen.findByText(/clients cannot buy a number/i)).toBeTruthy();
  });

  it("prints the attested figure from the server's string, with its source", async () => {
    renderPanel({ [ADMIN_ME_PATH]: OPERATOR, [NUMBER_PRICING_PATH]: PRICED });
    expect(await screen.findByText("₹499.00")).toBeTruthy();
    expect(screen.getByText("Vobiz order form, 1 Oct 2026")).toBeTruthy();
  });

  it("sends the typed figure as a string, with the document it was read from", async () => {
    const calls = renderPanel({
      [ADMIN_ME_PATH]: OPERATOR,
      [`GET ${NUMBER_PRICING_PATH}`]: UNPRICED,
      [`POST ${NUMBER_PRICING_PATH}`]: PRICED,
    });
    const open = await screen.findByRole("button", { name: "Record a price" });
    await waitFor(() => expect((open as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(open);
    fireEvent.change(screen.getByLabelText(/Rupees per number/), { target: { value: "499.00" } });
    fireEvent.change(screen.getByLabelText(/Read from/), {
      target: { value: "Vobiz order form, 1 Oct 2026" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Record the price" }));

    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const sent = calls.find((c) => c.method === "POST");
    expect(JSON.parse(sent?.body ?? "{}")).toEqual({
      inr_per_month: "499.00",
      source: "Vobiz order form, 1 Oct 2026",
    });
    // Step-up confirmed, like every price an operator attests (D-681).
    expect(sent?.headers["X-Confirm-Action"]).toBe("attest_number_price");
    expect(await screen.findByText(/numbers already bought keep theirs/i)).toBeTruthy();
  });

  it("refuses a figure above the server's ceiling before anything is sent", async () => {
    const calls = renderPanel({ [ADMIN_ME_PATH]: OPERATOR, [NUMBER_PRICING_PATH]: UNPRICED });
    const open = await screen.findByRole("button", { name: "Record a price" });
    await waitFor(() => expect((open as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(open);
    fireEvent.change(screen.getByLabelText(/Rupees per number/), { target: { value: "250000" } });
    fireEvent.change(screen.getByLabelText(/Read from/), { target: { value: "a quote" } });
    fireEvent.click(screen.getByRole("button", { name: "Record the price" }));

    expect(await screen.findByText(/more than ₹1,00,000 a month/)).toBeTruthy();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("keeps the control closed, with the reason, for an operator without the permission", async () => {
    renderPanel({ [ADMIN_ME_PATH]: READ_ONLY, [NUMBER_PRICING_PATH]: PRICED });
    const open = await screen.findByRole("button", { name: "Record a new price" });
    await screen.findByText(/does not have permission to record what a phone number costs/);
    expect((open as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows the server's refusal when the read fails", async () => {
    renderPanel({
      [ADMIN_ME_PATH]: OPERATOR,
      [NUMBER_PRICING_PATH]: problem(503, { title: "Dependency unavailable" }),
    });
    expect(await screen.findByRole("alert")).toBeTruthy();
  });
});

describe("the ceiling check", () => {
  it("compares on the digits, at and around 1,00,000", () => {
    expect(exceedsCeiling("100000")).toBe(false);
    expect(exceedsCeiling("100000.00")).toBe(false);
    expect(exceedsCeiling("100000.01")).toBe(true);
    expect(exceedsCeiling("099999.99")).toBe(false);
    expect(exceedsCeiling("1000000")).toBe(true);
    expect(exceedsCeiling("499.50")).toBe(false);
  });
});
