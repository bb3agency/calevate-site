import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import NewClientPage from "@/app/admin/new/page";
import type { CreateOrgOut } from "@/lib/api/admin";

import { problem, renderAdminPage, stubApi } from "./harness";

/**
 * The new-client wizard (FLOWS §1, steps 1 and 8).
 *
 * Lower blast radius than the ops screen — one account rather than every tenant — but it
 * is the screen that mints a single-use OWNER CREDENTIAL, and every assertion below is
 * about the console claiming something the server did not say:
 *
 * 1. **A creation that failed must not render as a created account.** Everything in step
 *    2 — the slug an operator will quote, the invite form that posts to a tenant id —
 *    reads off the server's response, so a success panel drawn from local state would
 *    send an operator to a `/c/…` that does not exist and, worse, would stop them
 *    retrying.
 * 2. **The account is named by what came BACK.** The server may normalise or de-duplicate
 *    a slug; a panel built from the typed one tells the operator the wrong URL.
 * 3. **A token minted for one address must never sit under a refusal for another.** It is
 *    a single-use owner credential shown once, and "copy the token" is exactly what an
 *    operator does next.
 * 4. **A refused control stops offering itself, with the server's reason.** Both writes
 *    are `admin:tenants`, which both admin roles hold, so a 403 here is a genuine
 *    surprise — and a surprise is the worst thing to answer with an identical retry.
 */

const TENANTS = "/v1/admin/tenants";

const CREATED: CreateOrgOut = {
  id: "0192f0aa-7777-7000-8000-000000000001",
  slug: "sunrise-clinic-2",
  status: "active",
  agent_id: "0192f0aa-7777-7000-8000-0000000000a1",
  extraction_schema_id: "0192f0aa-7777-7000-8000-0000000000b1",
};

const INVITATIONS = `${TENANTS}/${CREATED.id}/invitations`;

function fillName(value = "Sunrise Clinic") {
  fireEvent.change(screen.getByPlaceholderText("Sunrise Clinic"), { target: { value } });
}

describe("creating the account", () => {
  it("does not report success it has not received", async () => {
    const { container } = renderAdminPage(<NewClientPage />, {
      [TENANTS]: problem(409, {
        title: "Slug taken",
        detail: "That slug already belongs to another client.",
        remediation: "Choose a different slug.",
      }),
    });

    fillName();
    fireEvent.click(screen.getByRole("button", { name: "Create client" }));

    await screen.findByText("That slug already belongs to another client.");
    // No creation claim anywhere, and the operator is still on step 1 with their input.
    expect(screen.queryByText("Account created")).toBeNull();
    expect(container.textContent).not.toContain("Invite the owner");
    expect(container.textContent).toContain("Step 1 of 2");
    // The refusal is answerable, so the control must stay live to answer it.
    expect(
      (screen.getByRole("button", { name: "Create client" }) as HTMLButtonElement).disabled,
    ).toBe(false);
  });

  it("names the account from the server's slug, not from what was typed", async () => {
    const { container } = renderAdminPage(<NewClientPage />, { [TENANTS]: CREATED });

    fillName();
    fireEvent.click(screen.getByRole("button", { name: "Create client" }));

    await screen.findByText("Account created");
    // The server de-duplicated the slug; the panel quotes what actually exists.
    expect(container.textContent).toContain("/c/sunrise-clinic-2");
    expect(container.textContent).not.toContain("/c/sunrise-clinic ");
    expect(container.textContent).toContain("Step 2 of 2");
  });

  it("stops offering a control the session is refused, with the server's reason", async () => {
    renderAdminPage(<NewClientPage />, {
      [TENANTS]: problem(403, {
        title: "Forbidden",
        detail: "This action requires the admin:tenants permission.",
        remediation: "Ask a superadmin to create the account.",
      }),
    });

    fillName();
    fireEvent.click(screen.getByRole("button", { name: "Create client" }));

    await screen.findByText("This action requires the admin:tenants permission.");
    const button = screen.getByRole("button", { name: "Create client" }) as HTMLButtonElement;
    // A permission refusal will not change on the second click, so the button says so
    // rather than inviting an identical 403.
    await waitFor(() => expect(button.disabled).toBe(true));
    expect(button.title).toBe("Ask a superadmin to create the account.");
    expect(screen.queryByText("Account created")).toBeNull();
  });
});

describe("the owner invite", () => {
  async function reachStepTwo(routes: Record<string, unknown>) {
    const render = renderAdminPage(<NewClientPage />, { [TENANTS]: CREATED, ...routes });
    fillName();
    fireEvent.click(screen.getByRole("button", { name: "Create client" }));
    await screen.findByText("Account created");
    return render;
  }

  it("shows the token once, with what holding it means", async () => {
    const { container } = await reachStepTwo({
      [INVITATIONS]: { token: "inv_live_3f9a2c", expires_in_hours: 72 },
    });

    fireEvent.change(screen.getByPlaceholderText("owner@business.com"), {
      target: { value: "owner@sunrise.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create invite" }));

    await screen.findByText("inv_live_3f9a2c");
    expect(container.textContent).toContain("Copy this now — it is not shown again");
    expect(container.textContent).toContain("becomes an owner of");
  });

  it("clears the previous token before a second attempt, so no refusal sits over a live credential", async () => {
    await reachStepTwo({ [INVITATIONS]: { token: "inv_live_3f9a2c", expires_in_hours: 72 } });

    const emailBox = screen.getByPlaceholderText("owner@business.com");
    fireEvent.change(emailBox, { target: { value: "owner@sunrise.example" } });
    fireEvent.click(screen.getByRole("button", { name: "Create invite" }));
    await screen.findByText("inv_live_3f9a2c");

    // The second address is refused. Re-stubbing the network mid-test is the only way to
    // give one path two answers, and the point of the test is the SEQUENCE: the first
    // owner's credential must not still be on screen under the second one's error.
    stubApi({
      [INVITATIONS]: problem(422, {
        title: "Invalid email",
        detail: "That address is not deliverable.",
      }),
    });
    fireEvent.change(emailBox, { target: { value: "owner@typo" } });
    fireEvent.click(screen.getByRole("button", { name: "Create invite" }));

    await screen.findByText("That address is not deliverable.");
    expect(screen.queryByText("inv_live_3f9a2c")).toBeNull();
  });

  it("mints nothing for an address nobody typed", async () => {
    const { calls } = await reachStepTwo({
      [INVITATIONS]: { token: "inv_live_3f9a2c", expires_in_hours: 72 },
    });

    // The billing email was left blank in step 1, so step 2 opens empty — and an empty
    // invite is a token nobody can use plus a membership row nobody asked for.
    const button = screen.getByRole("button", { name: "Create invite" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(calls.some((c) => c.path === INVITATIONS)).toBe(false);
  });
});
