import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import CallMistakesPage from "@/app/admin/ops/call-mistakes/page";
import CallWordsPage from "@/app/admin/ops/call-words/page";
import { CallLinesPanel } from "@/app/admin/tenants/[tenantId]/numbers/CallLinesPanel";
import { ToastProvider } from "@/components/arc/toast";
import { FLEET_FIXES_PATH, PLATFORM_MISTAKES_PATH, mistakeFixedPath } from "@/lib/api/callMistakes";
import { CALL_WORDS_PATH } from "@/lib/api/callWords";

import { CALL_WORDS, PRICING_DETAIL } from "./fixtures/callWords";
import { renderAdminPage } from "./harness";

/**
 * A dialog that closes itself on success unmounts before `useActionFeedback`'s effect can
 * see the outcome, so a success toast promised by the screen is only raised when the write
 * is started through `run` (feedback.tsx, `viaRun`). These dialogs promised a toast and
 * started the write with `mutate(..., { onSuccess: onClose })`, so the operator saw the
 * dialog vanish and nothing said the write landed.
 */

const OPERATOR: AdminMe = {
  user_id: "op-1",
  email: "ops@calevate.tech",
  role: "superadmin",
  permissions: ["org:read", "ops:manage"],
} as unknown as AdminMe;

describe("an admin dialog that closes on success still says it worked", () => {
  it("Ops > Call mistakes: Mark fixed toasts after the dialog closes", async () => {
    renderAdminPage(<ToastProvider>{<CallMistakesPage />}</ToastProvider>, {
      [ADMIN_ME_PATH]: OPERATOR,
      [PLATFORM_MISTAKES_PATH]: {
        window_days: 30,
        items: [
          {
            kind: "said_again",
            label: "Said the same line again",
            calls_7d: 4,
            calls_30d: 9,
            accounts_30d: 3,
            calls_since_fix: 0,
            last_seen_at: "2026-10-25T10:00:00Z",
            fixed_at: null,
            fix_note: null,
            fixed_by: null,
            state: "fixing",
            rule: "",
            last_call_id: null,
            last_client_slug: null,
          },
        ],
      },
      [FLEET_FIXES_PATH]: { window_days: 30, items: [] },
      [`POST ${mistakeFixedPath("said_again")}`]: { kind: "said_again", fixed_at: "2026-11-01T10:00:00Z" },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Mark fixed: Said the same line again" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("What changed"), { target: { value: "Rephrase rule added." } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Mark fixed" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(await screen.findByText("Marked fixed")).toBeTruthy();
  });

  it("Ops > Call words: Save toasts after the editor closes", async () => {
    const PRICING = `${CALL_WORDS_PATH}/detection.topic.pricing`;
    renderAdminPage(<ToastProvider>{<CallWordsPage />}</ToastProvider>, {
      [ADMIN_ME_PATH]: OPERATOR,
      [CALL_WORDS_PATH]: CALL_WORDS,
      [PRICING]: PRICING_DETAIL,
      [`PUT ${PRICING}`]: PRICING_DETAIL,
    });
    await screen.findByText("1 list needs your words");
    fireEvent.change(screen.getByLabelText("Show"), { target: { value: "all" } });
    fireEvent.click(screen.getByRole("button", { name: "Edit: topic pricing" }));
    fireEvent.change(screen.getByLabelText(/^Words/), { target: { value: "price\ncost" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByLabelText(/^Words/)).toBeNull());
    expect(await screen.findByText("Saved")).toBeTruthy();
  });

  it("Client > Numbers: declining a calls-at-once request toasts after the dialog closes", async () => {
    const PATH = "/v1/admin/organizations/t1/call-lines";
    const asked = {
      id: "r1",
      requested_by: "Asha",
      lines_at_request: 2,
      wanted_lines: 4,
      note: "Festival rush",
      created_at: "2026-11-05T06:30:00Z",
    };
    renderAdminPage(<ToastProvider>{<CallLinesPanel tenantId="t1" canWrite />}</ToastProvider>, {
      [PATH]: {
        call_lines: 2,
        call_lines_chosen: null,
        source: "platform",
        on_trial: false,
        min_lines: 1,
        max_lines: 50,
        paid_default: 2,
        trial_default: 1,
        engine_state: "ours",
        applied_lines: null,
        applied_at: null,
        account_ceiling: 20,
        lines_elsewhere_at_most: 14,
        open_request: asked,
      },
      [`POST ${PATH}/requests/r1/decline`]: { ...asked, status: "declined" },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Decline" }));
    const dialog = await screen.findByRole("dialog", { name: "Decline the request" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: /Why/ }), { target: { value: "Let's talk first." } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Decline" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(await screen.findByText("Declined. The client is told.")).toBeTruthy();
  });
});
