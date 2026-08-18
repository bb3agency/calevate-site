import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { problem, stubApi, type ApiCall } from "./harness";

/**
 * Signup — the front door of the self-serve motion (D-34), with the flag ON.
 *
 * ## Why this file renders directly instead of using a harness helper
 *
 * `renderClientPage` wraps its subject in `ClientRealmProvider`, and this screen has no
 * realm: its caller is a Clerk-verified user with NO organization yet, which is the whole
 * point of `POST /v1/auth/signup` (lib/api/signup.ts). `renderAdminPage` is the closer
 * model — no provider — but signup mounts its OWN `Providers` (it is outside both app
 * shells and therefore outside their QueryClients), so wrapping it in a second
 * QueryClientProvider would test a composition the app does not have. `stubApi` is used
 * unchanged: the network is still the only seam, and `calls` is where hard rule 6 is
 * asserted.
 *
 * ## Why the flag is set in `vi.hoisted`
 *
 * `SIGNUP_OPEN` is a build-time constant read at module scope, so it is fixed by the time
 * the page is imported. `vi.hoisted` runs above the imports, which is the only place a
 * value read at import time can be set. The CLOSED half of the behaviour — the default,
 * and the state most deployments are in — lives in `signupClosed.test.tsx` for the same
 * reason: it needs the constant to have the other value, and `vi.resetModules()` would
 * hand the page a second copy of React.
 *
 * Every test here is negative. The screen's danger is not that it fails to create a
 * workspace; it is that it says it did.
 */

vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SELF_SERVE_SIGNUP_ENABLED = "true";
});

const SIGNUP = "/v1/auth/signup";

/** The response shape `POST /v1/auth/signup` returns on 201. */
const CREATED = {
  tenant_id: "0192f0aa-1111-7000-8000-000000000001",
  name: "Sri Sai Dental Care",
  slug: "sri-sai-dental-care",
  role: "owner",
  plan_tier: "self_serve",
  next_steps: ["Top up your wallet before any outbound call can go out."],
};

let SignupPage: () => React.ReactElement;

beforeAll(async () => {
  ({ default: SignupPage } = await import("@/app/signup/page"));
});

function fill(): void {
  fireEvent.change(screen.getByLabelText("Business name"), {
    target: { value: "Sri Sai Dental Care" },
  });
  fireEvent.change(screen.getByLabelText("Workspace URL"), {
    target: { value: "sri-sai-dental" },
  });
  fireEvent.change(screen.getByLabelText("Billing email"), {
    target: { value: "owner@srisai.example" },
  });
}

/**
 * Render and let the realm's restore settle before touching the form (D-177).
 *
 * The page mounts `ClientSessionProvider` and shows the workspace form only to a caller
 * with a live session — a stranger gets the panel explaining how accounts are obtained.
 * The restore is a `fetch`, so a synchronous `render` returns with neither branch decided
 * and `getByLabelText` finds nothing. `stubApi` answers the restore by default; this is
 * what waits for it.
 */
async function mount(): Promise<void> {
  await act(async () => {
    render(<SignupPage />);
  });
}

async function submit(routes: Record<string, unknown>): Promise<ApiCall[]> {
  const calls = stubApi(routes);
  await mount();
  fill();
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Create workspace" }));
  });
  return calls;
}

/** Everything the screen is currently saying, as one string. */
function pageText(): string {
  return document.body.textContent ?? "";
}

describe("a refused signup", () => {
  it("renders the refusal and NOT a success state", async () => {
    await submit({
      [SIGNUP]: problem(503, {
        type: "https://calevate.tech/problems/internal",
        title: "Service unavailable",
        detail: "We could not create your workspace just now.",
        retryable: true,
      }),
    });

    expect(await screen.findByText("We could not create your workspace just now.")).toBeTruthy();
    // The three shapes a success would take. None of them may appear on a refusal.
    expect(pageText()).not.toContain("Sri Sai Dental Care is set up");
    expect(screen.queryByRole("link", { name: /^Open / })).toBeNull();
    expect(pageText()).not.toContain("/c/sri-sai-dental-care");
    // The form is still there to correct and resubmit — a refusal is not a dead end.
    expect(screen.queryByRole("button", { name: "Create workspace" })).not.toBeNull();
  });

  it("shows the kill switch as a closed door, not as a fault, and offers no form", async () => {
    await submit({
      [SIGNUP]: problem(403, {
        type: "https://calevate.tech/problems/signup_disabled",
        title: "Signup disabled",
        detail: "Self-serve signup is not enabled on this deployment.",
        remediation: "Ask your account manager to set your workspace up.",
      }),
    });

    expect(await screen.findByText("Signing up online is closed")).toBeTruthy();
    // The server's own remediation, not ours.
    expect(pageText()).toContain("Ask your account manager to set your workspace up.");
    // A form whose every submission is refused is a trap, so it is gone rather than
    // disabled — and there is certainly no success.
    expect(screen.queryByRole("button", { name: "Create workspace" })).toBeNull();
    expect(pageText()).not.toContain("Sri Sai Dental Care is set up");
  });

  it("offers a retry for load-shedding, because that closure clears by itself", async () => {
    await submit({
      [SIGNUP]: problem(503, {
        type: "https://calevate.tech/problems/signup_load_shed",
        title: "Not now",
        detail: "New accounts are paused.",
      }),
    });

    expect(await screen.findByText("Not right now")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeNull();
    // The kill switch's copy must NOT be what a transient closure says: it would send a
    // business to support over a five-minute window.
    expect(pageText()).not.toContain("Signing up online is closed");
  });
});

describe("field-level refusals", () => {
  it("puts the server's message on the field it is about, and announces it there", async () => {
    await submit({
      [SIGNUP]: problem(422, {
        type: "https://calevate.tech/problems/validation_error",
        title: "Invalid",
        detail: "Check your answers.",
        fields: [{ field: "slug", rule: "slug_taken", message: "That name is already taken." }],
      }),
    });

    const input = (await screen.findByLabelText("Workspace URL")) as HTMLInputElement;
    expect(input.getAttribute("aria-invalid")).toBe("true");
    const describedBy = input.getAttribute("aria-describedby") ?? "";
    const described = describedBy
      .split(" ")
      .map((id) => document.getElementById(id)?.textContent ?? "")
      .join(" ");
    expect(described).toContain("That name is already taken.");

    // Said once. The summary points at the field rather than repeating it, so a client
    // reading the top of the page and a client tabbing the form get one message each.
    expect(pageText().split("That name is already taken.").length - 1).toBe(1);
    expect(pageText()).not.toContain("Sri Sai Dental Care is set up");
  });

  it("never drops a message about a field this form does not render", async () => {
    await submit({
      [SIGNUP]: problem(422, {
        type: "https://calevate.tech/problems/validation_error",
        title: "Invalid",
        detail: "Check your answers.",
        fields: [
          { field: "plan_tier", rule: "not_self_assignable", message: "That tier is not open to you." },
        ],
      }),
    });

    // `plan_tier` is sent by this form but has no control on it, so there is nowhere to
    // put the message except the summary — and a refusal the user never sees is worse
    // than one shown twice.
    expect(await screen.findByText("That tier is not open to you.")).toBeTruthy();
    expect(pageText()).not.toContain("Sri Sai Dental Care is set up");
  });
});

describe("what a prospect types", () => {
  it("travels in the POST body and never in a URL (hard rule 6)", async () => {
    const calls = await submit({ [SIGNUP]: CREATED });

    // Asserted BEFORE the count, so the failure a future "check whether this slug is
    // free" GET produces names the rule it broke rather than reading as an off-by-one.
    // Not "no query string on the signup path" — nothing typed may appear ANYWHERE in
    // the URL of ANY request the screen made. A business name in a URL lands in access
    // logs, proxy logs and the next request's Referer.
    for (const made of calls) {
      expect(made.url, "no request may carry typed input in its URL").not.toContain("?");
      expect(made.url.toLowerCase()).not.toContain("sri-sai-dental");
      expect(made.url).not.toContain("owner@srisai.example");
      expect(made.url).not.toContain("Sri%20Sai");
    }
    // TWO calls: the realm's session restore on mount, then the signup. The restore is
    // named rather than counted away, so a THIRD call still fails this the way it should.
    expect(calls.map((c) => c.path)).toEqual(["/v1/auth/client/session", SIGNUP]);
    const call = calls[1];
    expect(call.method).toBe("POST");
    expect(call.path).toBe(SIGNUP);
    const body = JSON.parse(call.body ?? "{}");
    expect(body.business_name).toBe("Sri Sai Dental Care");
    expect(body.billing_email).toBe("owner@srisai.example");
  });

  it("makes no request at all before the form is submitted", async () => {
    const calls = stubApi({});
    await mount();
    fill();
    // The realm's session restore is the ONE call a mount is allowed to make, and it is
    // not "what a prospect typed" — nothing this screen collects has been sent.
    expect(calls.map((c) => c.path)).toEqual(["/v1/auth/client/session"]);
  });
});

describe("the success panel", () => {
  it("claims nothing the API did not send", async () => {
    await submit({ [SIGNUP]: { ...CREATED, next_steps: [] } });

    expect(await screen.findByText("Sri Sai Dental Care is set up")).toBeTruthy();
    // An empty `next_steps` is the server saying there is nothing outstanding it wants to
    // name here. The screen must not invent the compliance list it happens to know about
    // — the wallet gate and the KYC requirement are the server's sentence (SURFACES §2c),
    // and a second copy here is a second copy to keep in step.
    const text = pageText();
    expect(text).not.toContain("Top up");
    expect(text).not.toContain("KYC");
    expect(text).not.toContain("verified number");
    // The role and the slug are printed from the response, so a response that named a
    // different one would print that one.
    expect(text).toContain("/c/sri-sai-dental-care");
    expect(text).toContain("owner");
  });

  it("prints the server's next steps verbatim", async () => {
    await submit({ [SIGNUP]: CREATED });
    expect(
      await screen.findByText("Top up your wallet before any outbound call can go out."),
    ).toBeTruthy();
  });
});

describe("the framing this screen has to carry itself", () => {
  it("scrolls on its own, because globals.css hides the document's overflow", async () => {
    stubApi({});
    let container!: HTMLElement;
    await act(async () => {
      ({ container } = render(<SignupPage />));
    });
    // `html, body { overflow: hidden }` is there for the `/c` and `/admin` shells, and
    // this route has neither. Without an overflow container of its own the submit button
    // is simply unreachable on a short viewport — a bug no type checker can see.
    expect(container.firstElementChild?.className).toContain("overflow-y-auto");
  });
});
