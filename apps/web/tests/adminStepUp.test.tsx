import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StepUpPrompt } from "@/components/authn/stepUpPrompt";
import {
  IMPERSONATION_GRANT_PATH,
  clearImpersonationGrants,
  viewAsConfirmation,
  viewAsSession,
} from "@/lib/api/admin";
import { apiRequest } from "@/lib/api/client";
import { requireStepUp } from "@/lib/authn/stepUpPrompt";

import { problem, renderAdminPage, type ApiCall, type Routes } from "./harness";

/**
 * The console's half of D-210: a step-up refusal becomes a code prompt, not a dead end.
 *
 * The API now refuses a COLD view-as mint without a second factor proved in the last five
 * minutes, and the whole point of D-178's refusal text — "an operator mid-incident must
 * not have to find the source to learn how to get past this" — is defeated if the browser
 * has nowhere to type the code. It had nowhere: the step-up gate shipped on sixteen routes
 * and this console had no prompt at all.
 *
 * What is asserted here:
 *
 *   1. the mint carries the `X-Confirm-Action` echo the route demands, and offers the
 *      grant it is replacing as `renew` — which is what makes the prompt roughly hourly
 *      rather than every fourteen minutes;
 *   2. a `reauthentication_required` refusal OPENS the prompt, and answering it retries
 *      the mint — without `renew`, because that value has just been ruled out;
 *   3. DISMISSING fails the action with the server's own refusal rather than looping;
 *   4. six concurrent refusals produce ONE prompt and ONE emailed code, because
 *      `request_step_up` retires the previous challenge and six asks would leave an
 *      operator typing a code the sixth request had already invalidated.
 */

const SLUG = "sri-traders";
const STEP_UP_PATH = "/v1/auth/admin/step-up";
const VERIFY_PATH = "/v1/auth/admin/step-up/verify";

/** The API's step-up refusal, in the shape `authn/stepup.py` sends it. */
function reauthRequired() {
  return problem(403, {
    type: "https://calevate.tech/problems/reauthentication_required",
    title: "Confirm it is still you",
    detail: "This action needs a second factor proved in the last 5 minutes.",
    remediation: `POST ${STEP_UP_PATH} to have a code emailed, POST the code to ${VERIFY_PATH}, then repeat this request with X-Confirm-Action: ${viewAsConfirmation(SLUG)}`,
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
 * Mount the prompt alone, and drive the grant source the way the transport does.
 *
 * The prompt is mounted once in `app/admin/layout.tsx` and answers refusals raised from
 * anywhere, including from inside `apiRequest` while it assembles headers. Rendering the
 * shell to reach it would drag in the session gate, the nav and a dozen unrelated reads;
 * rendering the component and calling the same entry point the shell's screens call is
 * the truthful shape for what is under test.
 */
function mountPrompt(routes: Routes): ApiCall[] {
  const { calls } = renderAdminPage(<StepUpPrompt />, routes);
  return calls;
}

/** One impersonated read, which is what forces a mint. */
function readThroughViewAs(): Promise<unknown> {
  return apiRequest(viewAsSession(SLUG), "/v1/agents");
}

const mints = (calls: ApiCall[]) => calls.filter((call) => call.path === IMPERSONATION_GRANT_PATH);

describe("the view-as mint carries what the step-up gate asks for", () => {
  it("echoes the confirmation string the API's own function builds", async () => {
    const calls = mountPrompt({
      [`POST ${IMPERSONATION_GRANT_PATH}`]: grantBody(),
      "/v1/agents": [],
    });

    await readThroughViewAs();

    const mint = mints(calls)[0];
    // Copied VERBATIM from `apps/api/admin/routes.py::view_as_confirmation`. If the two
    // ever disagree the API answers `step_up_required` and prints the string it wanted —
    // deliberately NOT a code this console retries, because a version skew must be seen.
    expect(mint?.headers["X-Confirm-Action"]).toBe(`view_as:${SLUG}`);
    expect(JSON.parse(mint?.body ?? "{}")).toEqual({ slug: SLUG });
  });

  it("offers the grant it is replacing as `renew`, so staying in does not re-challenge", async () => {
    let issued = 0;
    const calls = mountPrompt({
      [`POST ${IMPERSONATION_GRANT_PATH}`]: () => {
        issued += 1;
        return {
          slug: SLUG,
          grant: `grant-${issued}`,
          // Expires INSIDE the console's 60s refresh margin, so the second read re-mints
          // rather than reusing — which is the moment `renew` exists for.
          expires_at: new Date(Date.now() + 5_000).toISOString(),
        };
      },
      "/v1/agents": [],
    });

    await readThroughViewAs();
    await readThroughViewAs();

    const [first, second] = mints(calls);
    expect(JSON.parse(first?.body ?? "{}")).toEqual({ slug: SLUG });
    // The renewal names the grant it continues. Without it the API would demand a second
    // factor on every re-mint — an emailed code roughly every fourteen minutes, which is
    // the control `core/impersonation.VIEW_AS_MAX_AGE` argues gets switched off.
    expect(JSON.parse(second?.body ?? "{}")).toEqual({ slug: SLUG, renew: "grant-1" });
  });
});

describe("a step-up refusal becomes a prompt", () => {
  it("emails a code, accepts it, and retries the mint as a cold start", async () => {
    let refuse = true;
    const calls = mountPrompt({
      [`POST ${IMPERSONATION_GRANT_PATH}`]: () => (refuse ? reauthRequired() : grantBody()),
      [`POST ${STEP_UP_PATH}`]: {},
      [`POST ${VERIFY_PATH}`]: {
        realm: "admin",
        subject_id: "op-1",
        mfa_complete: true,
        email_verified: true,
      },
      "/v1/agents": [],
    });

    const read = readThroughViewAs();

    expect(await screen.findByRole("alertdialog")).toBeTruthy();
    // The reason names what is waiting, so the operator knows which action the code is for.
    expect(screen.getByRole("alertdialog").textContent).toContain(SLUG);

    fireEvent.click(screen.getByRole("button", { name: /email me a code/i }));
    await waitFor(() => {
      expect(calls.some((call) => call.path === STEP_UP_PATH)).toBe(true);
    });

    refuse = false;
    fireEvent.change(screen.getByLabelText(/six-digit code/i), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: /^confirm$/i }));

    await expect(read).resolves.toEqual([]);
    // The prompt closes on success rather than being left for the operator to dismiss.
    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).toBeNull();
    });

    const bodies = mints(calls).map((call) => JSON.parse(call.body ?? "{}"));
    expect(bodies).toHaveLength(2);
    // The retry drops `renew` — there was none to offer here, and after a refusal there
    // would be nothing left to continue.
    expect(bodies[1]).toEqual({ slug: SLUG });
  });

  it("has no way out except proving the factor or signing out (D-473)", async () => {
    /* THE `X` IS GONE ON PURPOSE, and this asserts the absence rather than trusting it.

       A close control on a second-factor challenge reads as "not now", which is the one
       posture the challenge exists to refuse. Escape is asserted too, because leaving the
       button off while Escape still closed it would HIDE the exit rather than remove it —
       strict-looking, loose-behaving, and only a keyboard user would ever find out. */
    mountPrompt({
      [`POST ${IMPERSONATION_GRANT_PATH}`]: reauthRequired(),
      "/v1/agents": [],
    });

    // Held and swallowed rather than `void`ed: this ask is settled `false` when the tree
    // unmounts at the end of the test, and an unattended rejection there fails the FILE
    // rather than this case — which is a failure pointing at the wrong line.
    readThroughViewAs().catch(() => undefined);
    const dialog = await screen.findByRole("alertdialog");

    expect(screen.queryByRole("button", { name: /close without confirming/i })).toBeNull();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.getByRole("alertdialog")).toBeTruthy();
  });

  it("signing out settles the waiting action with the server's own refusal", async () => {
    const calls = mountPrompt({
      [`POST ${IMPERSONATION_GRANT_PATH}`]: reauthRequired(),
      "POST /v1/auth/admin/logout": { revoked: 1 },
      "/v1/agents": [],
    });

    const read = readThroughViewAs();
    await screen.findByRole("alertdialog");

    fireEvent.click(screen.getByRole("button", { name: /^sign out$/i }));

    // The ORIGINAL refusal, not an invented one: it is still exactly true, and it already
    // carries a title, a sentence and a remediation this console would have to reinvent.
    // It must settle even though the panel is being torn down — a caller left awaiting a
    // prompt that no longer exists is a promise nothing can resolve.
    await expect(read).rejects.toMatchObject({ code: "reauthentication_required" });
    // And nothing was retried behind the closing prompt.
    expect(mints(calls)).toHaveLength(1);
    await waitFor(() => {
      expect(calls.some((call) => call.path.endsWith("/logout"))).toBe(true);
    });
  });

  it("asks ONCE when six reads are refused together", async () => {
    let refuse = true;
    const calls = mountPrompt({
      [`POST ${IMPERSONATION_GRANT_PATH}`]: () => (refuse ? reauthRequired() : grantBody()),
      [`POST ${STEP_UP_PATH}`]: {},
      [`POST ${VERIFY_PATH}`]: {
        realm: "admin",
        subject_id: "op-1",
        mfa_complete: true,
        email_verified: true,
      },
      "/v1/agents": [],
    });

    // Six at once, the way a tenant screen opens its panels. The grant cache already
    // collapses them into ONE mint, so this asserts the seam end to end: six reads, one
    // prompt, one code, six resolutions. The store's own single-flight — two INDEPENDENT
    // asks sharing one prompt — is pinned separately below, because the grant cache would
    // hide a regression in it here.
    const reads = Array.from({ length: 6 }, () => readThroughViewAs());
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

    await expect(Promise.all(reads)).resolves.toHaveLength(6);
    // ONE emailed code. `service.request_step_up` retires the previous challenge on
    // issue, so six asks would have left the operator typing a code the sixth invalidated.
    expect(calls.filter((call) => call.path === STEP_UP_PATH)).toHaveLength(1);
    expect(calls.filter((call) => call.path === VERIFY_PATH)).toHaveLength(1);
  });

  it("keeps the prompt open on a wrong code instead of failing the action", async () => {
    mountPrompt({
      [`POST ${IMPERSONATION_GRANT_PATH}`]: reauthRequired(),
      [`POST ${STEP_UP_PATH}`]: {},
      [`POST ${VERIFY_PATH}`]: problem(401, {
        type: "https://calevate.tech/problems/invalid_second_factor",
        title: "That code did not match",
        detail: "That code did not match.",
        kind: "auth",
      }),
      "/v1/agents": [],
    });

    const read = readThroughViewAs();
    // The read is going to fail when the prompt is eventually closed; attached now so the
    // rejection is never unhandled.
    const settled = read.catch(() => "declined");

    await screen.findByRole("alertdialog");
    fireEvent.click(screen.getByRole("button", { name: /email me a code/i }));
    fireEvent.change(await screen.findByLabelText(/six-digit code/i), {
      target: { value: "000000" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^confirm$/i }));

    // A typo must not eject the operator from the action they asked for — the same
    // argument `lib/authn/problems.ts` makes about `invalid_credentials` on a live console.
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("alertdialog")).toBeTruthy();

    // Signing out is now the only exit that is not proving the factor (D-473), and it
    // still settles the waiting caller `false` rather than leaving it pending.
    fireEvent.click(screen.getByRole("button", { name: /^sign out$/i }));
    expect(await settled).toBe("declined");
  });
});

describe("the ask is single-flighted, whoever asks", () => {
  it("shares one prompt between independent callers and settles them together", async () => {
    mountPrompt({ [`POST ${STEP_UP_PATH}`]: {}, [`POST ${VERIFY_PATH}`]: SESSION_OUT });

    const first = requireStepUp("Opening one thing.");
    const second = requireStepUp("Opening another thing.");

    await screen.findByRole("alertdialog");
    expect(screen.getAllByRole("alertdialog")).toHaveLength(1);
    // The FIRST asker's sentence stands: changing it under the person reading it would be
    // the prompt describing an action they did not start.
    expect(screen.getByRole("alertdialog").textContent).toContain("Opening one thing.");

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
