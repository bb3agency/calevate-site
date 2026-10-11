import { describe, expect, it } from "vitest";

import { API_BASE, apiUrl } from "@/lib/api/client";

/**
 * Route params reach API paths unencoded (`/v1/calls/${callId}/translation`), so a crafted
 * console link must not be able to walk this person's credentialed request onto another
 * route. The browser normalises `..` (and `%2e%2e`) before sending, so the guard sits in
 * the one function every request URL is built by.
 */
describe("apiUrl", () => {
  it("passes an ordinary path through unchanged", () => {
    expect(apiUrl("/v1/calls/0190-abc/translation?x=1")).toBe(
      `${API_BASE}/v1/calls/0190-abc/translation?x=1`,
    );
  });

  it.each([
    "/v1/calls/../agents/0190-abc/deactivate?/translation",
    "/v1/calls/%2e%2e/agents/x/deactivate",
    "/v1/calls/..%2Fagents%2Fx%2Fdeactivate",
    "/v1/calls/.%2E/agents",
    "/v1/calls/x\\..\\agents",
    "/v1/calls/./x",
    "v1/calls",
  ])("refuses %s", (path) => {
    expect(() => apiUrl(path)).toThrow();
  });

  it("does not mistake a dot inside a segment for a dot segment", () => {
    expect(() => apiUrl("/v1/kb/uploads/price.list.pdf")).not.toThrow();
  });
});
