import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useLeadRowEdit } from "@/lib/api/leads";
import { useClientSession } from "@/lib/api/session";

import { OWNER_ME } from "./fixtures/sharedReads";
import { problem, renderClientPage, stillLoading } from "./harness";

/**
 * The leads table edits many rows through one mutation. Each row keeps its own refusal and
 * its own busy state, also when another row is edited before the first one settles.
 */

function Rows() {
  const rows = useLeadRowEdit(useClientSession());
  return (
    <>
      {["lead-a", "lead-b"].map((id) => (
        <div key={id}>
          <button type="button" onClick={() => rows.edit(id, { status: "contacted" })}>
            Edit {id}
          </button>
          <span>{`${id} ${rows.pendingFor(id) ? "saving" : "idle"} ${rows.errorFor(id) ? "refused" : "fine"}`}</span>
        </div>
      ))}
    </>
  );
}

describe("editing lead rows", () => {
  it("keeps a row's refusal when another row was edited while it saved", async () => {
    await renderClientPage(<Rows />, {
      "/v1/me": OWNER_ME,
      "PATCH /v1/leads/lead-a": problem(409, { title: "Changed meanwhile", detail: "Reload the lead." }),
      "PATCH /v1/leads/lead-b": stillLoading(),
    });
    fireEvent.click(screen.getByRole("button", { name: "Edit lead-a" }));
    fireEvent.click(screen.getByRole("button", { name: "Edit lead-b" }));
    expect(await screen.findByText("lead-a idle refused")).toBeTruthy();
    expect(screen.getByText("lead-b saving fine")).toBeTruthy();
  });
});
