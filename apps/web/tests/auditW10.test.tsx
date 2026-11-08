import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TrialLinePanel } from "@/app/admin/ops/config/TrialLinePanel";
import type { TrialLine } from "@/lib/api/opsTrialNumber";

import { stubApi } from "./harness";

/** Frontend audit lane W10 (8 Nov 2026): what a screen shows after a write. */

const LINE: TrialLine = {
  state: "no_agent",
  message: null,
  message_note: null,
  wanted_message: "Thanks for calling back.",
};

describe("the shared trial line after Set it up now", () => {
  it("follows the line the config read hands it afterwards, not the set-up's answer", async () => {
    const ready: TrialLine = { ...LINE, state: "ready", message: "Thanks for calling back." };
    const calls = stubApi({ "POST /v1/ops/trial-number/line": ready });
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const panel = (line: TrialLine) => (
      <QueryClientProvider client={client}>
        <TrialLinePanel line={line} />
      </QueryClientProvider>
    );
    const view = render(panel(LINE));
    fireEvent.click(screen.getByRole("button", { name: "Set it up now" }));
    await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
    // The config read comes back with the line; later it says someone changed it.
    view.rerender(panel(ready));
    view.rerender(panel({ ...ready, state: "drifted" }));
    expect(
      await screen.findByText("Someone changed the line in ThinnestAI's console; set it up again."),
    ).toBeTruthy();
  });
});
