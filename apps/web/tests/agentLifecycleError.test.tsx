import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LifecycleError } from "@/app/c/[slug]/agents/AgentLifecycle";
import { ApiProblem } from "@/lib/api/client";

import { renderClientPage } from "./harness";

/**
 * A refused "Get it ready" / "Switch on" names the screen that clears it.
 *
 * On a new account the first press is refused for unaccepted agreements, and the notice
 * used to say where to go ("the Agreements & readiness screen") with nothing to press.
 */

function refusal(code: string, detail: string): ApiProblem {
  return new ApiProblem(409, {
    type: `https://calevate.tech/problems/${code}`,
    title: "We could not complete that",
    detail,
    kind: "conflict",
  });
}

describe("LifecycleError", () => {
  it("links an unaccepted-agreements refusal to the agreements screen", async () => {
    await renderClientPage(
      <LifecycleError
        error={refusal(
          "agreements_not_accepted",
          "This account has not accepted its agreements, so its agents cannot be published.",
        )}
      />,
      {},
      "sunrise-homes",
    );
    expect(screen.getByText(/has not accepted its agreements/)).toBeTruthy();
    const link = screen.getByRole("link", { name: "Read and accept" });
    expect(link.getAttribute("href")).toBe("/c/sunrise-homes/agreements");
  });

  it("shows only the notice when the refusal has no screen to send the owner to", async () => {
    await renderClientPage(
      <LifecycleError error={refusal("engine_rejected", "The voice platform did not answer.")} />,
      {},
      "sunrise-homes",
    );
    expect(screen.getByText(/did not answer/)).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });
});
