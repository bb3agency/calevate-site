import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ClientSignInPage from "@/app/(auth)/auth/sign-in/page";
import { CreateAccountForm } from "@/components/authn/createAccountForm";

import { problem, stubApi } from "./harness";

/** Frontend audit 8 Nov 2026, lane W1: the account doors. */

const SIGNED_OUT = { "GET /v1/auth/client/session": problem(401, { code: "unauthorized" }) };

describe("the sign-in page's lead", () => {
  it("does not offer Google where the Google button is not shown", async () => {
    stubApi({
      ...SIGNED_OUT,
      "GET /v1/auth/client/sign-in-options": { google: false, self_serve_signup: true },
    });
    await act(async () => {
      render(<ClientSignInPage />);
    });
    expect(await screen.findByText("Welcome back.")).toBeTruthy();
    expect(document.body.textContent).not.toContain("Use Google");
  });

  it("names Google when its button is there", async () => {
    stubApi({
      ...SIGNED_OUT,
      "GET /v1/auth/client/sign-in-options": { google: true, self_serve_signup: true },
    });
    await act(async () => {
      render(<ClientSignInPage />);
    });
    expect(await screen.findByText("Welcome back. Use Google or your email.")).toBeTruthy();
  });
});

describe("creating an account, going back to change the address", () => {
  it("does not greet the next address with the last one's refusal", async () => {
    stubApi({
      "GET /v1/auth/client/sign-in-options": { google: false, self_serve_signup: true },
      "POST /v1/auth/client/signup/start": null,
      "POST /v1/auth/client/signup/complete": problem(401, { code: "invalid_code" }),
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <CreateAccountForm onCreated={() => undefined} />
      </QueryClientProvider>,
    );
    fireEvent.change(screen.getByLabelText("Work email"), { target: { value: "a@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Email me a code" }));
    await screen.findByText("Check your email");

    const boxes = screen.getAllByRole("textbox").filter((el) => el.getAttribute("name") !== "name");
    fireEvent.change(boxes[0], { target: { value: "123456" } });
    fireEvent.change(screen.getByLabelText("Choose a password"), {
      target: { value: "correct horse battery" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create my account" }));
    expect(await screen.findByRole("alert")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Use a different email address/ }));
    fireEvent.change(screen.getByLabelText("Work email"), { target: { value: "b@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Email me a code" }));
    await screen.findByText("Check your email");
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
