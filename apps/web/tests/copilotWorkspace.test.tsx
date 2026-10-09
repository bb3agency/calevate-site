import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AskAssistant } from "@/components/copilot/AskAssistant";
import { ClientCopilotDock } from "@/components/copilot/CopilotDock";
import { ApprovalsInbox } from "@/components/copilot/workspace/ApprovalsInbox";
import { ActivityLog } from "@/components/copilot/workspace/ActivityLog";
import { Routines } from "@/components/copilot/workspace/Routines";
import { ToastProvider } from "@/components/interior/toaster";
import { useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { selectionFact, selectionSummary, MAX_SELECTED_IDS } from "@/lib/copilot/selection";
import { noFill } from "@/lib/copilot/types";
import { clockWords, scheduleWords } from "@/lib/copilot/workspace";

import { expectNoA11yViolations } from "./a11y";
import {
  DONE_ACTION,
  PENDING_APPROVAL,
  PREVIEW,
  REFUSED_ACTION,
  ROUTINE_ON,
  workspaceRoutes,
} from "./copilotWorkspaceFixture";
import { renderClientPage, type ApiCall } from "./harness";

function posted(calls: ApiCall[], path: string): ApiCall[] {
  return calls.filter((call) => call.method === "POST" && call.path === path);
}

/** A screen that declares two ticked leads, the way the leads table does. */
function LeadsLike() {
  useCopilotSurface({
    route: "/c/acme/leads",
    title: "Leads",
    realm: "client",
    fields: [],
    facts: [selectionFact("Leads ticked (lead ids)", ["lead-1", "lead-2"], false)],
    apply: noFill,
  });
  return <AskAssistant prompt="Summarise the leads I've ticked." />;
}

describe("the words the workspace uses", () => {
  it("says a schedule the way a person would", () => {
    expect(scheduleWords({ days: ["mon", "tue", "wed", "thu", "fri"], time: "09:30" })).toBe(
      "Weekdays at 9:30 am",
    );
    expect(scheduleWords({ days: ["fri"], time: "17:00" })).toBe("Every Friday at 5:00 pm");
    expect(
      scheduleWords({ days: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], time: "00:05" }),
    ).toBe("Every day at 12:05 am");
    expect(scheduleWords({ days: ["sat", "sun"], time: "12:00" })).toBe("Weekends at 12:00 pm");
    expect(scheduleWords({ days: ["mon", "thu"], time: "10:00" })).toBe("Mon, Thu at 10:00 am");
    expect(clockWords("nonsense")).toBe("nonsense");
  });

  it("sends selected ids, bounded, and names the selection without them", () => {
    const many = Array.from({ length: MAX_SELECTED_IDS + 5 }, (_, i) => `id-${i}`);
    const fact = selectionFact("Leads ticked", many, false);
    expect(fact.value.startsWith(`${many.length} selected (first ${MAX_SELECTED_IDS}):`)).toBe(true);
    expect(fact.value).not.toContain(`id-${MAX_SELECTED_IDS}`);
    const surface = { route: "/", title: "", realm: "client" as const, fields: [], apply: noFill };
    expect(selectionSummary({ ...surface, facts: [fact] })).toBe(`${many.length} selected`);
    expect(selectionSummary({ ...surface, facts: [selectionFact("x", [], false)] })).toBeNull();
    expect(selectionSummary({ ...surface, facts: [selectionFact("x", [], true)] })).toBe(
      "Everything these filters match",
    );
  });
});

describe("the side panel", () => {
  it("opens from a 'Let the assistant do this' button with the request written but NOT sent", async () => {
    const view = await renderClientPage(
      <>
        <ClientCopilotDock />
        <LeadsLike />
      </>,
      { "/v1/copilot/conversation?limit=50": { turns: [], has_more: false } },
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Let the assistant do this: Summarise the leads I've ticked.",
      }),
    );
    const panel = await screen.findByRole("dialog");
    const box = within(panel).getByRole("textbox");
    await waitFor(() => expect((box as HTMLTextAreaElement).value).toBe("Summarise the leads I've ticked."));
    // It is told what is selected, in words, so "these" has a referent.
    expect(within(panel).getByText("Using: 2 selected")).toBeTruthy();
    // A button never spends the allowance: nothing was asked.
    expect(view.calls.some((call) => call.path.startsWith("/v1/copilot/ask"))).toBe(false);
    await expectNoA11yViolations(view.container.ownerDocument.body, "the side panel");

    // Escape closes it and hands the keyboard back.
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});

function WithSession({ children }: { children: (session: ReturnType<typeof useClientSession>) => React.ReactNode }) {
  return <ToastProvider>{children(useClientSession())}</ToastProvider>;
}

describe("the Approvals inbox", () => {
  it("shows what approving would change before the button that does it", async () => {
    const view = await renderClientPage(
      <WithSession>{(session) => <ApprovalsInbox session={session} />}</WithSession>,
      {
        ...workspaceRoutes(),
        [`/v1/copilot/approvals/${PENDING_APPROVAL.id}/preview`]: PREVIEW,
        [`POST /v1/copilot/approvals/${PENDING_APPROVAL.id}/approve`]: {
          tool: "dnc_add",
          object_type: "lead",
          object_id: "x",
          applied: true,
          detail: "Added to your do-not-call list.",
        },
      },
    );
    const row = await screen.findByRole("button", { name: /do-not-call list so no campaign/ });
    // Approve is not offered until the fresh reading has arrived.
    fireEvent.click(row);
    const approve = await screen.findByRole("button", { name: "Approve" });
    await screen.findByText("Never called again");
    expect(screen.getByText("Nothing")).toBeTruthy();
    expect(screen.getByText(/needs the owner/)).toBeTruthy();
    await waitFor(() => expect(approve).toHaveProperty("disabled", false));
    await expectNoA11yViolations(view.container, "the approvals inbox, open");
    await act(async () => {
      fireEvent.click(approve);
    });
    await waitFor(() =>
      expect(
        posted(view.calls, `/v1/copilot/approvals/${PENDING_APPROVAL.id}/approve`),
      ).toHaveLength(1),
    );
  });

  it("does not offer Approve when the step no longer applies", async () => {
    await renderClientPage(
      <WithSession>{(session) => <ApprovalsInbox session={session} />}</WithSession>,
      {
        ...workspaceRoutes(),
        [`/v1/copilot/approvals/${PENDING_APPROVAL.id}/preview`]: {
          ...PREVIEW,
          title: "This no longer applies",
          still_applies: false,
          refusal: "That lead has been deleted.",
        },
      },
    );
    fireEvent.click(await screen.findByRole("button", { name: /do-not-call list so no campaign/ }));
    await screen.findByText("That lead has been deleted.");
    expect(screen.getByRole("button", { name: "Approve" })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Decline" })).toHaveProperty("disabled", false);
  });
});

describe("the activity log", () => {
  it("offers Undo only where the server does, and posts it", async () => {
    const view = await renderClientPage(
      <WithSession>{(session) => <ActivityLog session={session} realm="client" />}</WithSession>,
      {
        ...workspaceRoutes(),
        [`POST /v1/copilot/actions/${DONE_ACTION.id}/undo`]: {
          action_id: DONE_ACTION.id,
          tool: "lead_set_status",
          detail: "The lead is back to New.",
        },
      },
    );
    await screen.findByText(DONE_ACTION.summary as string);
    expect(screen.getByText(REFUSED_ACTION.refusal_reason as string)).toBeTruthy();
    const undos = screen.getAllByRole("button", { name: /^Undo:/ });
    expect(undos).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Show older" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "What the assistant did" })).toBeTruthy();
    await act(async () => {
      fireEvent.click(undos[0]);
    });
    expect((await screen.findAllByText("The lead is back to New.")).length).toBeGreaterThan(0);
    expect(posted(view.calls, `/v1/copilot/actions/${DONE_ACTION.id}/undo`)).toHaveLength(1);
  });
});

describe("routines", () => {
  it("creates a routine one question at a time and sends a schedule in order", async () => {
    const view = await renderClientPage(
      <WithSession>{(session) => <Routines session={session} />}</WithSession>,
      {
        ...workspaceRoutes(),
        "POST /v1/copilot/routines": ROUTINE_ON,
      },
    );
    await screen.findByText(ROUTINE_ON.name);
    expect(screen.getByText(/Weekdays at 9:30 am/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "New routine" }));
    const drawer = await screen.findByRole("dialog", { name: "New routine" });
    fireEvent.click(within(drawer).getByRole("button", { name: "Friday lead summary" }));
    fireEvent.click(within(drawer).getByRole("button", { name: "Next" }));
    await within(drawer).findByText("When should it run?");
    // Add Monday to Friday: the wire is Monday-first whatever order it was ticked in.
    fireEvent.click(within(drawer).getByRole("button", { name: "Monday" }));
    fireEvent.click(within(drawer).getByRole("button", { name: "Next" }));
    await within(drawer).findByText(/wait in\s+Approvals/);
    await act(async () => {
      fireEvent.click(within(drawer).getByRole("button", { name: "Add routine" }));
    });
    await waitFor(() => expect(posted(view.calls, "/v1/copilot/routines")).toHaveLength(1));
    const body = JSON.parse(posted(view.calls, "/v1/copilot/routines")[0].body ?? "{}");
    expect(body).toEqual({
      name: "Friday lead summary",
      instruction:
        "Summarise this week's leads: how many came in, who is hot, and who to call next.",
      schedule: { days: ["mon", "fri"], time: "17:00" },
      enabled: true,
    });
  });
});
