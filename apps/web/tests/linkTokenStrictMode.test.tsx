import { render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { useLinkToken } from "@/lib/authn/useLinkToken";

/**
 * React runs every mount effect twice under Strict Mode, which the App Router turns on for
 * `next dev`. The first run takes the token out of the URL, so a second run that re-reads
 * the URL finds nothing and must not overwrite the token it already captured — otherwise
 * every reset, invitation and bootstrap link reads as "missing its code".
 */
function Probe() {
  const { token, ready } = useLinkToken();
  return <p>{ready ? `token:${token || "none"}` : "reading"}</p>;
}

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("useLinkToken", () => {
  it("keeps the captured token when the mount effect runs twice", async () => {
    window.history.replaceState(null, "", `/auth/reset-password?token=${"t".repeat(40)}`);
    render(
      <StrictMode>
        <Probe />
      </StrictMode>,
    );
    expect(await screen.findByText(`token:${"t".repeat(40)}`)).toBeTruthy();
    expect(window.location.search).toBe("");
  });

  it("still reports a link that arrived without one", async () => {
    window.history.replaceState(null, "", "/auth/reset-password");
    render(
      <StrictMode>
        <Probe />
      </StrictMode>,
    );
    expect(await screen.findByText("token:none")).toBeTruthy();
  });
});
