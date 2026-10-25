import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StepUpPrompt } from "@/components/authn/stepUpPrompt";
import {
  IMPERSONATION_GRANT_PATH,
  IMPERSONATION_RENEW_PATH,
  clearImpersonationGrants,
  confirmedAdminRequest,
  viewAsSession,
} from "@/lib/api/admin";
import { apiRequest } from "@/lib/api/client";
import { useEditTenant } from "@/lib/api/tenantProfile";
import { requireStepUp } from "@/lib/authn/stepUpPrompt";

import { problem, renderAdminPage, type ApiCall, type Routes } from "./harness";

/**
 * The console's half of D-210: a step-up refusal becomes a code prompt, not a dead end.
 *
 * What is asserted here:
 *
 *   1. the view-as mint starts a session with the slug alone (D-791) and offers the grant
 *      it is replacing as `renew` on the renewal route;
 *   2. a `reauthentication_required` refusal on a confirmed operator write OPENS the
 *      prompt, and answering it retries the write;
 *   3. signing out fails the action with the server's own refusal rather than looping;
 *   4. six concurrent refusals produce ONE prompt and ONE emailed code, because
 *      `request_step_up` retires the previous challenge and six asks would leave an
 *      operator typing a code the sixth request had already invalidated.
 */

const SLUG = "sri-traders";
const STEP_UP_PATH = "/v1/auth/admin/step-up";
const VERIFY_PATH = "/v1/auth/admin/step-up/verify";

/** A confirmed operator write, standing for every route behind the step-up gate. */
const WRITE_PATH = "/v1/admin/tenants/t-1/kyc";
const WRITE_CONFIRMATION = "record_kyc:t-1";
const WRITE_REASON = `Recording KYC for ${SLUG}.`;

/** The API's step-up refusal, in the shape `authn/stepup.py` sends it. */
function reauthRequired() {
  return problem(403, {
    type: "https://calevate.tech/problems/reauthentication_required",
    title: "Confirm it is still you",
    detail: "This action needs a second factor proved in the last 30 minutes.",
    remediation: `POST ${STEP_UP_PATH} to have a code emailed, POST the code to ${VERIFY_PATH}, then repeat this request with X-Confirm-Action: ${WRITE_CONFIRMATION}`,
    kind: "permission",
  });
}

/** `SessionOut`, as `/step-up/verify` answers it. */
const SESSION_OUT = {
  realm: "admin",
  subject_id: "op-1",
  mfa_complete: true,
  email_verified: true,
};

function grantBody(): Record<string, unknown> {
  return {
    slug: SLUG,
    grant: "fresh-view-as-grant",
    expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
  };
}

/**
 * Mount the prompt alone, and drive callers the way the screens do.
 *
 * The prompt is mounted once in `app/admin/layout.tsx` and answers refusals raised from
 * anywhere. Rendering the shell to reach it would drag in the session gate, the nav and a
 * dozen unrelated reads; rendering the component and calling the same entry points the
 * shell's screens call is the truthful shape for what is under test.
 */
function mountPrompt(routes: Routes): ApiCall[] {
  const { calls } = renderAdminPage(<StepUpPrompt />, routes);
  return calls;
}

/** One impersonated read, which is what forces a mint. */
function readThroughViewAs(): Promise<unknown> {
  return apiRequest(viewAsSession(SLUG), "/v1/agents");
}

/** One confirmed operator write, which is what can be refused for a stale factor. */
function confirmedWrite(): Promise<unknown> {
  return confirmedAdminRequest(
    WRITE_PATH,
    { method: "POST", body: { status: "verified" }, confirmAction: WRITE_CONFIRMATION },
    WRITE_REASON,
  );
}

const mints = (calls: ApiCall[]) =>
  calls.filter((call) => call.path === IMPERSONATION_GRANT_PATH);

const writes = (calls: ApiCall[]) => calls.filter((call) => call.path === WRITE_PATH);

describe("the view-as mint", () => {
  it("starts with the slug and renews with the grant it replaces", async () => {
    let issued = 0;
    const grant = () => {
      issued += 1;
      return {
        slug: SLUG,
        grant: `grant-${issued}`,
        // Expires INSIDE the console's 60s refresh margin, so the second read re-mints
        // rather than reusing — which is the moment `renew` exists for.
        expires_at: new Date(Date.now() + 5_000).toISOString(),
      };
    };
    const calls = mountPrompt({
      [`POST ${IMPERSONATION_GRANT_PATH}`]: grant,
      // D-730: a renewal has its own route, the one grant route the client console may call.
      [`POST ${IMPERSONATION_RENEW_PATH}`]: grant,
      "/v1/agents": [],
    });

    await readThroughViewAs();
    await readThroughViewAs();

    const first = mints(calls)[0];
    const second = calls.find((call) => call.path === IMPERSONATION_RENEW_PATH);
    expect(JSON.parse(first?.body ?? "{}")).toEqual({ slug: SLUG });
    // The renewal names the grant it continues, so the new grant keeps the session's
    // original `auth_time` (`core/impersonation.VIEW_AS_MAX_AGE`).
    expect(JSON.parse(second?.body ?? "{}")).toEqual({
      slug: SLUG,
      renew: "grant-1",
    });
  });
});

describe("a step-up refusal becomes a prompt", () => {
  it("emails a code, accepts it, and retries the write", async () => {
    let refuse = true;
    const calls = mountPrompt({
      [`POST ${WRITE_PATH}`]: () => (refuse ? reauthRequired() : {}),
      [`POST ${STEP_UP_PATH}`]: {},
      [`POST ${VERIFY_PATH}`]: SESSION_OUT,
    });

    const write = confirmedWrite();

    expect(await screen.findByRole("alertdialog")).toBeTruthy();
    // The reason names what is waiting, so the operator knows which action the code is for.
    expect(screen.getByRole("alertdialog").textContent).toContain(SLUG);

    fireEvent.click(screen.getByRole("button", { name: /email me a code/i }));
    await waitFor(() => {
      expect(calls.some((call) => call.path === STEP_UP_PATH)).toBe(true);
    });

    refuse = false;
    fireEvent.change(screen.getByLabelText(/six-digit code/i), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^confirm$/i }));

    await expect(write).resolves.toEqual({});
    // The prompt closes on success rather than being left for the operator to dismiss.
    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).toBeNull();
    });

    const sent = writes(calls);
    expect(sent).toHaveLength(2);
    expect(sent[1]?.headers["X-Confirm-Action"]).toBe(WRITE_CONFIRMATION);
  });

  it("has no way out except proving the factor or signing out (D-473)", async () => {
    /* A close control on a second-factor challenge reads as "not now", which is the one
       posture the challenge exists to refuse. Escape is asserted too, because leaving the
       button off while Escape still closed it would HIDE the exit rather than remove it. */
    mountPrompt({
      [`POST ${WRITE_PATH}`]: reauthRequired(),
    });

    // Held and swallowed rather than `void`ed: this ask is settled `false` when the tree
    // unmounts at the end of the test, and an unattended rejection there fails the FILE
    // rather than this case.
    confirmedWrite().catch(() => undefined);
    const dialog = await screen.findByRole("alertdialog");

    expect(
      screen.queryByRole("button", { name: /close without confirming/i }),
    ).toBeNull();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.getByRole("alertdialog")).toBeTruthy();
  });

  it("signing out settles the waiting action with the server's own refusal", async () => {
    const calls = mountPrompt({
      [`POST ${WRITE_PATH}`]: reauthRequired(),
      "POST /v1/auth/admin/logout": { revoked: 1 },
    });

    const write = confirmedWrite();
    await screen.findByRole("alertdialog");

    fireEvent.click(screen.getByRole("button", { name: /^sign out$/i }));

    // The ORIGINAL refusal, not an invented one: it already carries a title, a sentence
    // and a remediation this console would have to reinvent. It must settle even though
    // the panel is being torn down.
    await expect(write).rejects.toMatchObject({
      code: "reauthentication_required",
    });
    // And nothing was retried behind the closing prompt.
    expect(writes(calls)).toHaveLength(1);
    await waitFor(() => {
      expect(calls.some((call) => call.path.endsWith("/logout"))).toBe(true);
    });
  });

  it("asks ONCE when six writes are refused together", async () => {
    let refuse = true;
    const calls = mountPrompt({
      [`POST ${WRITE_PATH}`]: () => (refuse ? reauthRequired() : {}),
      [`POST ${STEP_UP_PATH}`]: {},
      [`POST ${VERIFY_PATH}`]: SESSION_OUT,
    });

    const pending = Array.from({ length: 6 }, () => confirmedWrite());
    await screen.findByRole("alertdialog");
    expect(screen.getAllByRole("alertdialog")).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: /email me a code/i }));
    refuse = false;
    // The field appears only once the API has accepted the request for a code — a code
    // box on screen before a code was sent is a box for a code that does not exist.
    fireEvent.change(await screen.findByLabelText(/six-digit code/i), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^confirm$/i }));

    await expect(Promise.all(pending)).resolves.toHaveLength(6);
    // ONE emailed code. `service.request_step_up` retires the previous challenge on
    // issue, so six asks would have left the operator typing a code the sixth invalidated.
    expect(calls.filter((call) => call.path === STEP_UP_PATH)).toHaveLength(1);
    expect(calls.filter((call) => call.path === VERIFY_PATH)).toHaveLength(1);
  });

  it("keeps the prompt open on a wrong code instead of failing the action", async () => {
    mountPrompt({
      [`POST ${WRITE_PATH}`]: reauthRequired(),
      [`POST ${STEP_UP_PATH}`]: {},
      [`POST ${VERIFY_PATH}`]: problem(401, {
        type: "https://calevate.tech/problems/invalid_second_factor",
        title: "That code did not match",
        detail: "That code did not match.",
        kind: "auth",
      }),
      "POST /v1/auth/admin/logout": { revoked: 1 },
    });

    // The write is going to fail when the prompt is eventually closed; attached now so the
    // rejection is never unhandled.
    const settled = confirmedWrite().catch(() => "declined");

    await screen.findByRole("alertdialog");
    fireEvent.click(screen.getByRole("button", { name: /email me a code/i }));
    fireEvent.change(await screen.findByLabelText(/six-digit code/i), {
      target: { value: "000000" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^confirm$/i }));

    // A typo must not eject the operator from the action they asked for.
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("alertdialog")).toBeTruthy();

    // Signing out is the only exit that is not proving the factor (D-473), and it still
    // settles the waiting caller `false` rather than leaving it pending.
    fireEvent.click(screen.getByRole("button", { name: /^sign out$/i }));
    expect(await settled).toBe("declined");
  });
});

describe("the ask is single-flighted, whoever asks", () => {
  it("shares one prompt between independent callers and settles them together", async () => {
    mountPrompt({
      [`POST ${STEP_UP_PATH}`]: {},
      [`POST ${VERIFY_PATH}`]: SESSION_OUT,
    });

    const first = requireStepUp("Opening one thing.");
    const second = requireStepUp("Opening another thing.");

    await screen.findByRole("alertdialog");
    expect(screen.getAllByRole("alertdialog")).toHaveLength(1);
    // The FIRST asker's sentence stands: changing it under the person reading it would be
    // the prompt describing an action they did not start.
    expect(screen.getByRole("alertdialog").textContent).toContain(
      "Opening one thing.",
    );

    fireEvent.click(screen.getByRole("button", { name: /email me a code/i }));
    fireEvent.change(await screen.findByLabelText(/six-digit code/i), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^confirm$/i }));

    expect(await Promise.all([first, second])).toEqual([true, true]);
  });

  it("settles waiters `false` when the shell unmounts and nobody can answer", async () => {
    const { unmount } = renderAdminPage(<StepUpPrompt />, {});
    const waiting = requireStepUp("Opening one thing.");

    await screen.findByRole("alertdialog");
    // Sign-out, or the session gate ceasing to render its children. The only subscriber
    // is gone, so the ask can never be answered — leaving it pending would hang the
    // caller on a prompt that no longer exists anywhere.
    unmount();

    expect(await waiting).toBe(false);
  });

  it("settles every waiter `false` when the operator signs out", async () => {
    mountPrompt({ "POST /v1/auth/admin/logout": { revoked: 1 } });
    const first = requireStepUp("Opening one thing.");
    const second = requireStepUp("Opening another thing.");

    await screen.findByRole("alertdialog");
    fireEvent.click(screen.getByRole("button", { name: /^sign out$/i }));

    // `false`, never a rejection: a prompt nobody answers must not become an unhandled
    // rejection, and the caller reports the refusal it is already holding.
    expect(await Promise.all([first, second])).toEqual([false, false]);
  });
});

describe("the notice address edit", () => {
  it("asks for a code when the factor is stale instead of ending at a 403", async () => {
    const editPath = "/v1/admin/tenants/t-1";
    function SaveAddress() {
      const edit = useEditTenant("t-1");
      return (
        <button type="button" onClick={() => edit.mutate({ billing_email: "new@sri.example" })}>
          Save address
        </button>
      );
    }
    renderAdminPage(
      <>
        <StepUpPrompt />
        <SaveAddress />
      </>,
      { [`PATCH ${editPath}`]: reauthRequired() },
    );

    fireEvent.click(await screen.findByRole("button", { name: "Save address" }));

    expect(await screen.findByRole("alertdialog")).toBeTruthy();
  });
});

describe("the grant cache and the prompt do not outlive a test", () => {
  it("starts every suite with no cached grant", async () => {
    clearImpersonationGrants();
    const calls = mountPrompt({
      [`POST ${IMPERSONATION_GRANT_PATH}`]: grantBody(),
      "/v1/agents": [],
    });
    await readThroughViewAs();
    expect(mints(calls)).toHaveLength(1);
    vi.clearAllMocks();
  });
});
