import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CallLinesPanel } from "@/app/admin/tenants/[tenantId]/numbers/CallLinesPanel";
import type { CallLines } from "@/lib/api/callLines";

import { problem, renderAdminPage } from "./harness";

/**
 * CALLS AT ONCE (F7) on the operator's Numbers page: the value in force and where it comes
 * from, a bounded entry, empty for the default (`null` on the wire), and a refusal that does
 * not outlive the attempt it answered.
 */

const PATH = "/v1/admin/organizations/t1/call-lines";

function lines(over: Partial<CallLines> = {}): CallLines {
  return {
    call_lines: 2,
    call_lines_chosen: null,
    source: "platform",
    on_trial: false,
    min_lines: 1,
    max_lines: 50,
    paid_default: 2,
    trial_default: 1,
    ...over,
  };
}

async function change() {
  await act(async () => {
    fireEvent.click(await screen.findByRole("button", { name: "Change" }));
  });
}

describe("calls at once", () => {
  it("shows the default in force for a paying client", async () => {
    renderAdminPage(<CallLinesPanel tenantId="t1" canWrite />, { [PATH]: lines() });
    await screen.findByText("2 calls at once");
    expect(screen.getByText("Calevate default (paying client)")).toBeTruthy();
  });

  it("saves a number in range and returns to the default with an empty field", async () => {
    const { calls } = renderAdminPage(<CallLinesPanel tenantId="t1" canWrite />, {
      [PATH]: lines(),
      [`PUT ${PATH}`]: lines({ call_lines: 5, call_lines_chosen: 5, source: "organization" }),
    });
    await change();
    fireEvent.change(screen.getByLabelText(/Calls at once, 1 to 50/), { target: { value: "5" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
    });
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PUT")?.body ?? "{}")).toEqual({ call_lines: 5 });
    await screen.findByText("5 calls at once");
    expect(screen.getByText("Set for this client")).toBeTruthy();
  });

  it("refuses a number out of range before sending it", async () => {
    const { calls } = renderAdminPage(<CallLinesPanel tenantId="t1" canWrite />, { [PATH]: lines() });
    await change();
    fireEvent.change(screen.getByLabelText(/Calls at once, 1 to 50/), { target: { value: "51" } });
    expect(screen.getByText("Enter 1 to 50, or leave it empty.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("clears the server's refusal when the change is cancelled", async () => {
    renderAdminPage(<CallLinesPanel tenantId="t1" canWrite />, {
      [PATH]: lines(),
      [`PUT ${PATH}`]: problem(409, { title: "Not now", detail: "The workspace is busy." }),
    });
    await change();
    fireEvent.change(screen.getByLabelText(/Calls at once, 1 to 50/), { target: { value: "3" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
    });
    await screen.findByText("The workspace is busy.");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    });
    expect(screen.queryByText("The workspace is busy.")).toBeNull();
  });

  it("offers no change without the permission", async () => {
    renderAdminPage(<CallLinesPanel tenantId="t1" canWrite={false} />, { [PATH]: lines() });
    await screen.findByText("2 calls at once");
    expect(screen.queryByRole("button", { name: "Change" })).toBeNull();
  });
});
