import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ClientConsoleJunction from "@/app/c/page";
import { CLIENT_SIGN_IN_PATH } from "@/lib/authn/clientAuthn";

import { problem, renderClientPage } from "./harness";

/** E2E audit OB-34: the junction's failure said "there is no list of yours to choose from yet". */
describe("the console junction when it cannot open an account", () => {
  it("says what to do in one line and offers one button", async () => {
    await renderClientPage(<ClientConsoleJunction />, {
      "/v1/me": problem(500, { title: "Server error", detail: "Something went wrong." }),
    });
    expect(await screen.findByText("We could not open your console")).toBeTruthy();
    expect(screen.getByText("In more than one business? Open the link it sent you.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Sign in again" }).getAttribute("href")).toBe(CLIENT_SIGN_IN_PATH);
    expect(document.body.textContent).not.toContain("no list of yours");
  });
});
