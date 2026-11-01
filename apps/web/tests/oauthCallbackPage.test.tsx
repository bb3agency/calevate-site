import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import OAuthCallbackPage from "@/app/oauth/callback/[provider]/page";

/**
 * A connect return that did not complete tells the person to start again from
 * Integrations, so it must give them the way there, not only the sentence.
 */

async function mount(): Promise<void> {
  await act(async () => {
    render(<OAuthCallbackPage params={Promise.resolve({ provider: "google" })} />);
  });
}

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("the connect callback when the provider refused", () => {
  it("offers the console in a full-page return", async () => {
    window.history.replaceState(null, "", "/oauth/callback/google?error=access_denied");
    await mount();
    expect(await screen.findByText("Not connected")).toBeTruthy();
    const link = screen.getByRole("link", { name: "Open your console" });
    expect(link.getAttribute("href")).toBe("/c");
  });
});
