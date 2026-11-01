import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Providers } from "@/app/providers";
import { StatusScreen } from "@/app/status/StatusScreen";

import { problem, stubApi } from "./harness";

const STATUS = "GET /v1/public/status";

const ALL_WELL = {
  components: [{ key: "calls", name: "Phone calls", state: "operational" }],
  incidents: [],
  updated_at: "2026-10-27T10:30:00Z",
};

async function mount(): Promise<void> {
  await act(async () => {
    render(
      <Providers>
        <StatusScreen />
      </Providers>,
    );
  });
}

describe("the public status page when the read fails", () => {
  it("offers a retry that loads the status, rather than only a sentence", async () => {
    let fail = true;
    const calls = stubApi({
      [STATUS]: () => (fail ? problem(404, { title: "Not found" }) : ALL_WELL),
    });
    await mount();
    expect(await screen.findByText("We could not load the current status.")).toBeTruthy();
    expect(screen.queryByText("Everything is working normally.")).toBeNull();

    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Everything is working normally.")).toBeTruthy();
    expect(calls.filter((c) => c.url.includes("/v1/public/status")).length).toBe(2);
  });
});
