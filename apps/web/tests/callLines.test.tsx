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

/** Types into the bounded field; it applies the number when focus leaves, as a person's tab does. */
function enter(value: string) {
  const box = screen.getByRole("spinbutton", { name: "Calls at once" });
  fireEvent.change(box, { target: { value } });
  fireEvent.blur(box);
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
    enter("5");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
    });
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PUT")?.body ?? "{}")).toEqual({ call_lines: 5 });
    await screen.findByText("5 calls at once");
    expect(screen.getByText("Set for this client")).toBeTruthy();
  });

  it("holds a number past the limit at the limit and says so", async () => {
    const { calls } = renderAdminPage(<CallLinesPanel tenantId="t1" canWrite />, {
      [PATH]: lines(),
      [`PUT ${PATH}`]: lines({ call_lines: 50, call_lines_chosen: 50, source: "organization" }),
    });
    await change();
    enter("51");
    expect(screen.getByText("Kept to 50, the limit here.")).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
    });
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PUT")?.body ?? "{}")).toEqual({ call_lines: 50 });
  });

  it("sends null for an emptied field, so the default applies", async () => {
    const { calls } = renderAdminPage(<CallLinesPanel tenantId="t1" canWrite />, {
      [PATH]: lines({ call_lines: 5, call_lines_chosen: 5, source: "organization" }),
      [`PUT ${PATH}`]: lines(),
    });
    await change();
    enter("");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
    });
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PUT")?.body ?? "{}")).toEqual({ call_lines: null });
  });

  it("clears the server's refusal when the change is cancelled", async () => {
    renderAdminPage(<CallLinesPanel tenantId="t1" canWrite />, {
      [PATH]: lines(),
      [`PUT ${PATH}`]: problem(409, { title: "Not now", detail: "The workspace is busy." }),
    });
    await change();
    enter("3");
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
