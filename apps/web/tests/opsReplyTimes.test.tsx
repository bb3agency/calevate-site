import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import ReplyTimesPage from "@/app/admin/ops/reply-times/page";
import { REPLY_TIMES_PATH } from "@/lib/api/replyTimes";

import { SLOW_CALL_ID, figures, replyTimeReport } from "./fixtures/replyTimes";
import { problem, renderAdminPage, type Routes } from "./harness";

const OPERATOR: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-00000000ad09",
  role: "superadmin",
  permissions: ["org:read", "ops:manage"],
};

const WINDOW_PATH = (days: number) => `${REPLY_TIMES_PATH}?days=${days}`;

function routes(over: Routes = {}): Routes {
  return { [ADMIN_ME_PATH]: OPERATOR, [WINDOW_PATH(7)]: replyTimeReport(), ...over };
}

function rowOf(table: HTMLElement, text: string): string[] {
  const row = within(table)
    .getAllByRole("row")
    .find((candidate) => (candidate.textContent ?? "").includes(text));
  expect(row).toBeDefined();
  return within(row as HTMLElement)
    .getAllByRole("cell")
    .map((cell) => cell.textContent ?? "");
}

describe("the voice response time report", () => {
  it("leads with calls over the console target and the server's own figures", async () => {
    const { container } = renderAdminPage(<ReplyTimesPage />, routes());

    await screen.findByRole("table", { name: "Reply times by client" });
    expect(container.textContent).toContain("3 of 12 measured calls");
    expect(container.textContent).toContain("typical 1,600 ms");
    expect(container.textContent).toContain("slow 2,200 ms");
    // Rounded to whole milliseconds, never recomputed.
    expect(container.textContent).toContain("812 ms");
    expect(container.textContent).toContain("1,460 ms");
  });

  it("splits the figures by the settings each call ran on", async () => {
    renderAdminPage(<ReplyTimesPage />, routes());

    const table = await screen.findByRole("table", { name: "Reply times by call setting" });
    expect(table.textContent).toContain("Turn detection");
    expect(table.textContent).toContain("Ear");
    expect(table.textContent).toContain("Facts known by heart");
    expect(table.textContent).toContain("Not recorded");
  });

  it("says every wait ends at the agent's first sound, and sets filler calls apart", async () => {
    const { container } = renderAdminPage(<ReplyTimesPage />, routes());

    await screen.findByRole("table", { name: "Reply times by client" });
    expect(container.textContent).toContain("A filler line counts, so this is not the time to the");
    expect(container.textContent).toContain("Typical wait, no filler found");
    // The server's figure over calls with no filler found, and how many had one.
    expect(container.textContent).toContain("1,240 ms");
    expect(container.textContent).toContain("4 measured calls had a reply open with a filler line");
    expect(container.textContent).not.toMatch(/Typical reply|Slow reply/);
  });

  it("times the model's first word from the turn reaching the platform", async () => {
    renderAdminPage(<ReplyTimesPage />, routes());

    fireEvent.click(await screen.findByRole("button", { name: /What these figures are/ }));
    await screen.findByText(/from the turn reaching\s+the voice platform/);
  });

  it("shows a withheld slow figure as a dash, never as zero", async () => {
    renderAdminPage(<ReplyTimesPage />, routes());

    const table = await screen.findByRole("table", { name: "Reply times by client" });
    const cells = rowOf(table, "Sri Dental");
    expect(cells).toContain("—");
    expect(cells).not.toContain("0 ms");
  });

  it("links a slow call to the client's own call screen through view-as", async () => {
    renderAdminPage(<ReplyTimesPage />, routes());

    const table = await screen.findByRole("table", { name: "Slowest calls" });
    const link = within(table).getAllByRole("link")[0];
    expect(decodeURIComponent(link.getAttribute("href") ?? "")).toContain(`/calls/${SLOW_CALL_ID}`);
    expect(table.textContent).toContain("A reply over 5 s");
    expect(table.textContent).toContain("2 model errors");
  });

  it("says why a window is empty, and which of the two reasons it is", async () => {
    const empty = replyTimeReport({
      empty_reason: "not_reported",
      overall: figures({ calls: 4, calls_measured: 0, reply_typical_ms: null }),
      by_client: [],
      by_agent: [],
      by_tier: [],
      by_day: [],
      by_setting: [],
      worst_calls: [],
    });
    const { container } = renderAdminPage(<ReplyTimesPage />, routes({ [WINDOW_PATH(7)]: empty }));

    await screen.findByText(/sent no reply times/);
    expect(container.textContent).not.toContain("No calls connected");
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("names a partial window and a cut agent list", async () => {
    const { container } = renderAdminPage(
      <ReplyTimesPage />,
      routes({ [WINDOW_PATH(7)]: replyTimeReport({ complete: false, agents_total: 80 }) }),
    );

    await screen.findByRole("table", { name: "Reply times by agent" });
    expect(container.textContent).toContain("These figures cover only the most recent calls");
    expect(container.textContent).toContain("of 80");
  });

  it("asks the API for the window the control picks", async () => {
    const { calls } = renderAdminPage(
      <ReplyTimesPage />,
      routes({ [WINDOW_PATH(30)]: replyTimeReport({ window_days: 30 }) }),
    );

    await screen.findByRole("table", { name: "Reply times by client" });
    fireEvent.click(screen.getByRole("radio", { name: "Last 30 days" }));
    await waitFor(() => {
      expect(calls.some((call) => call.path === WINDOW_PATH(30))).toBe(true);
    });
  });

  it("shows the refusal instead of an empty report when the read fails", async () => {
    const { container } = renderAdminPage(
      <ReplyTimesPage />,
      routes({
        [WINDOW_PATH(7)]: problem(503, {
          type: "urn:calevate:ops/unavailable",
          title: "Service unavailable",
          detail: "The report could not be assembled.",
        }),
      }),
    );

    await screen.findByText("The report could not be assembled.");
    expect(container.textContent).not.toContain("No calls connected");
  });
});
