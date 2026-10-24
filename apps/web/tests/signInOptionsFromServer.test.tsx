import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GoogleSignIn, SignInOptionsFromServer } from "@/components/authn/googleSignIn";

import { stubApi } from "./harness";

/**
 * "Continue with Google" is on the first paint when the server read the sign-in options
 * (founder, 24 Oct 2026: it arrived late and pushed the form down), and the page still
 * asks from the browser when the server could not.
 */
function renderButton(options: { google: boolean; self_serve_signup: boolean } | null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SignInOptionsFromServer options={options}>
        <GoogleSignIn />
      </SignInOptionsFromServer>
    </QueryClientProvider>,
  );
}

describe("sign-in options read on the server", () => {
  it("draws the Google button on the first render and asks nothing", () => {
    const calls = stubApi({});
    renderButton({ google: true, self_serve_signup: true });
    expect(screen.getByRole("button", { name: "Continue with Google" })).toBeTruthy();
    expect(calls.filter((call) => call.path === "/v1/auth/client/sign-in-options")).toHaveLength(0);
  });

  it("offers no button when the server says Google is off", () => {
    stubApi({});
    renderButton({ google: false, self_serve_signup: true });
    expect(screen.queryByRole("button", { name: "Continue with Google" })).toBeNull();
  });

  it("asks from the browser when the server could not read them", async () => {
    const calls = stubApi({
      "/v1/auth/client/sign-in-options": { google: true, self_serve_signup: false },
    });
    renderButton(null);
    expect(await screen.findByRole("button", { name: "Continue with Google" })).toBeTruthy();
    expect(calls.some((call) => call.path === "/v1/auth/client/sign-in-options")).toBe(true);
  });
});
