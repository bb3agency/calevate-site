import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProblemNotice } from "@/components/ui";
import { apiRequest, devSession } from "@/lib/api/client";

import { noReply, problem, stubApi } from "./harness";

/*
 * A refusal the server SENT speaks for itself; "No reply reached this page" is said only
 * when no reply did. The two were confused on the Voices page's Refresh: a 502 carrying an
 * `engine_capability_absent` problem was reported to an operator as a lost reply, which
 * sent them to debug the network for a refusal the API had explained.
 */

const PATH = "/v1/ops/voices/refresh";

async function failure(): Promise<unknown> {
  try {
    await apiRequest(devSession("acme"), PATH, { method: "POST" });
  } catch (error) {
    return error;
  }
  throw new Error("the request was expected to fail");
}

describe("a problem response that arrived", () => {
  it("renders the server's own title and detail, never the no-reply sentence", async () => {
    stubApi({
      [`POST ${PATH}`]: problem(502, {
        type: "urn:calevate:dependency/engine_capability_absent",
        title: "The voice platform cannot do that",
        detail: "The voice platform in use does not provide: tts.",
        remediation: "Nothing needs fixing on this account.",
        kind: "dependency",
      }),
    });
    render(<ProblemNotice error={await failure()} />);

    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("The voice platform cannot do that");
    expect(alert.textContent).toContain("The voice platform in use does not provide: tts.");
    expect(alert.textContent).toContain("Nothing needs fixing on this account.");
    expect(alert.textContent).not.toMatch(/No reply reached this page/);
  });

  it("prints a title once when the problem carries no separate detail", async () => {
    stubApi({ [`POST ${PATH}`]: problem(503, { title: "Upstream unavailable", kind: "unavailable" }) });
    render(<ProblemNotice error={await failure()} />);

    expect(screen.getAllByText("Upstream unavailable")).toHaveLength(1);
  });
});

describe("a request that got no reply", () => {
  it("says no reply reached the page, and that whether it was done is unknown", async () => {
    stubApi({ [`POST ${PATH}`]: noReply() });
    render(<ProblemNotice error={await failure()} />);

    expect(screen.getByRole("alert").textContent).toContain(
      "No reply reached this page, so we could not confirm whether that was done.",
    );
  });
});
