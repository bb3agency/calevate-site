import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import PipQualityPage from "@/app/admin/ops/pip-quality/page";
import { pipQualityUrl } from "@/lib/api/pipQuality";

import { pipQualityReport } from "./fixtures/pipQuality";
import { renderAdminPage, type Routes } from "./harness";

const OPERATOR: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-00000000ad09",
  role: "superadmin",
  permissions: ["org:read", "ops:manage"],
};

function routes(over: Routes = {}): Routes {
  return {
    [ADMIN_ME_PATH]: OPERATOR,
    [pipQualityUrl("client", 7)]: pipQualityReport(),
    [pipQualityUrl("admin", 7)]: pipQualityReport({ realm: "admin", by_area: [], by_tool: [] }),
    [pipQualityUrl("client", 30)]: pipQualityReport({ window_days: 30 }),
    ...over,
  };
}

describe("Pip quality (D-937)", () => {
  it("shows the server's scores by area with the low ones flagged", async () => {
    const { container } = renderAdminPage(<PipQualityPage />, routes());

    const areas = await screen.findByRole("table", { name: "Pip's scores by area" });
    const leads = within(areas)
      .getAllByRole("row")
      .find((row) => (row.textContent ?? "").includes("Leads"));
    expect(leads?.textContent).toContain("Rated down");
    expect(leads?.textContent).toContain("1 / 4");
    expect(container.textContent).toContain("60%");
    expect(container.textContent).toContain("640 ms");
    expect(container.textContent).toContain("Daily limit");
    expect(container.textContent).toContain("Didn't do it: 3");
  });

  it("links each low score to example answers, ids only", async () => {
    const { container } = renderAdminPage(<PipQualityPage />, routes());

    await screen.findByRole("table", { name: "Pip's scores by area" });
    expect(container.textContent).toContain("0192f0aa-2222-7000-8000-0000000000b1");
    expect(container.textContent).toContain("it missed the booking");
  });

  it("switches between the client Pip and the admin Pip, and between windows", async () => {
    const { calls } = renderAdminPage(<PipQualityPage />, routes());
    await screen.findByRole("table", { name: "Pip's scores by area" });

    fireEvent.click(screen.getByRole("radio", { name: "Admin Pip" }));
    await waitFor(() =>
      expect(calls.some((call) => call.path === pipQualityUrl("admin", 7))).toBe(true),
    );
    fireEvent.click(screen.getByRole("radio", { name: "Client Pip" }));
    fireEvent.click(screen.getByRole("radio", { name: "Last 30 days" }));
    await waitFor(() =>
      expect(calls.some((call) => call.path === pipQualityUrl("client", 30))).toBe(true),
    );
  });

  it("says so when there were no questions", async () => {
    renderAdminPage(
      <PipQualityPage />,
      routes({
        [pipQualityUrl("client", 7)]: pipQualityReport({
          questions: 0,
          by_area: [],
          by_tool: [],
          refusals: [],
        }),
      }),
    );
    await screen.findByText("No questions in this window");
  });
});
