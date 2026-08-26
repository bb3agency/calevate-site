import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import NewClientPage from "@/app/admin/new/page";
import type { AdminMe } from "@/app/admin/access";
import type { CreateOrgOut } from "@/lib/api/admin";
import { intakeFieldId, type IntakeState, type UnfinishedOnboarding } from "@/lib/api/intake";

import { problem, renderAdminPage, stubApi, type ApiCall, type Routes } from "./harness";

/**
 * Draft, and resume — FLOWS §1's "draft state saved at every step (resume anytime)".
 *
 * `save_intake_draft` had no route in front of it, so the only write a browser could
 * reach ran the submission gate first: a half-finished intake could not be stored, and
 * with nothing partial stored there was nothing to resume. Both halves land here, and
 * these are the four ways they could ship and still be broken:
 *
 * 1. **The save fires, with a body the SUBMIT would refuse.** A draft control that
 *    quietly inherits the submit's completeness gate is the missing feature wearing a
 *    button.
 * 2. **A failed save is visible.** A save that reports success it did not have is worse
 *    than no save at all — it is what teaches an operator the work is safe.
 * 3. **A resume prefills from what was stored**, addressing the tenant and agent the
 *    list gave, and rendering the language set from the agent's OWN primary (there is no
 *    step-1 state to borrow it from on this path).
 * 4. **A failed list read refuses.** "No unfinished onboardings" over a 503 is the worst
 *    sentence on this screen: the operator concludes their half-finished client is not
 *    waiting and creates the account again, under a slug the first attempt already took
 *    and a DB trigger makes immutable (BUILD-LOG §52).
 */

const TENANTS = "/v1/admin/tenants";
const ADMIN_ME = "/v1/admin/me";
const UNFINISHED = "/v1/admin/onboarding/unfinished";

const CREATED: CreateOrgOut = {
  id: "0192f0aa-7777-7000-8000-000000000001",
  slug: "sunrise-clinic",
  status: "active",
  agent_id: "0192f0aa-7777-7000-8000-0000000000a1",
  extraction_schema_id: "0192f0aa-7777-7000-8000-0000000000b1",
  vertical_template: "clinic",
};

const INTAKE = `${TENANTS}/${CREATED.id}/agents/${CREATED.agent_id}/intake`;
const DRAFT = `${INTAKE}/draft`;

/** An account somebody started last week and never finished. Its ids are NOT the
 *  creation's: a resume that quietly addressed the account from step 1 would pass every
 *  assertion that did not check the path. */
const ABANDONED: UnfinishedOnboarding = {
  tenant_id: "0192f0bb-8888-7000-8000-000000000002",
  name: "Lakeview Dental",
  slug: "lakeview-dental",
  agent_id: "0192f0bb-8888-7000-8000-0000000000a2",
  created_at: "2026-08-01T04:30:00Z",
  // DELIBERATELY NOT A CLINIC. The vertical is carried on this row precisely so a
  // resumed wizard shows the right trade's examples, and a fixture that said "clinic"
  // would pass whether or not the field was ever read.
  vertical_template: "real_estate",
  draft_saved_at: "2026-08-05T09:15:00Z",
  blockers: ["business_hours_missing", "escalation_contact_missing"],
};

const RESUMED_INTAKE = `${TENANTS}/${ABANDONED.tenant_id}/agents/${ABANDONED.agent_id}/intake`;
const RESUMED_DRAFT = `${RESUMED_INTAKE}/draft`;

function me(permissions: string[]): AdminMe {
  return {
    realm: "admin",
    user_id: "0192f0aa-7777-7000-8000-0000000000f2",
    role: "operator",
    permissions,
  };
}

const OPERATOR = me(["org:read", "agents:read", "agents:write", "admin:tenants"]);

const NO_INTAKE: IntakeState = {
  business_hours: {},
  escalation_contacts: [],
  languages: [],
  prose_answers: null,
  compiled_t0_context: null,
  submitted_at: null,
  saved_at: null,
  language_primary: "te-IN",
  sheet_agent_id: null,
};

/** What the abandoned client's sheet holds: an address and a service, and neither of
 *  the two answers `submission_blockers` demands. Exactly a wizard left mid-call. */
const HALF_ANSWERED: IntakeState = {
  business_hours: {},
  escalation_contacts: [],
  // The EXTRAS only — the API drops the agent's own primary before storing.
  languages: ["en-IN"],
  prose_answers: {
    branches: [{ label: "Main", address: "12 MG Road, Hyderabad 500016" }],
    services: [{ name: "Root canal", price_inr: "8000", notes: null }],
    faqs: [],
    staff: [],
    booking_rules: "Same-day slots close at 17:00.",
  },
  compiled_t0_context: null,
  submitted_at: null,
  saved_at: "2026-08-05T09:15:00Z",
  // Hindi, deliberately NOT the "te-IN" step 1 of this wizard would have chosen: the
  // resumed form has to read the agent's own row rather than the browser's memory.
  language_primary: "hi-IN",
  sheet_agent_id: ABANDONED.agent_id,
};

const DRAFT_SAVED = { agent_id: ABANDONED.agent_id, blockers: ABANDONED.blockers };

function control(path: string): HTMLElement {
  const element = document.getElementById(intakeFieldId(path));
  if (element === null) throw new Error(`no control rendered for ${path}`);
  return element;
}

const valueOf = (path: string) => (control(path) as HTMLInputElement).value;

function type(path: string, value: string): void {
  fireEvent.change(control(path), { target: { value } });
}

const postsTo = (calls: ApiCall[], path: string) =>
  calls.filter((call) => call.path === path && call.method === "POST");

/** Reach step 3 by CREATING a client, the way the existing wizard tests do. */
async function reachIntake(routes: Routes = {}) {
  const render = renderAdminPage(<NewClientPage />, {
    [TENANTS]: CREATED,
    [ADMIN_ME]: OPERATOR,
    [UNFINISHED]: [],
    [INTAKE]: NO_INTAKE,
    ...routes,
  });
  fireEvent.change(screen.getByPlaceholderText("Sunrise Clinic"), {
    target: { value: "Sunrise Clinic" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create client" }));
  await screen.findByText("Account created");
  await screen.findByText("Business hours");
  return render;
}

/** Reach step 3 by RESUMING the abandoned account off the list. */
async function reachByResuming(routes: Routes = {}) {
  const render = renderAdminPage(<NewClientPage />, {
    [ADMIN_ME]: OPERATOR,
    [UNFINISHED]: [ABANDONED],
    [RESUMED_INTAKE]: HALF_ANSWERED,
    ...routes,
  });
  fireEvent.click(await screen.findByRole("button", { name: /Resume/ }));
  await screen.findByText("Business hours");
  return render;
}

describe("saving a draft", () => {
  it("sends the answers the SUBMIT would refuse, and says what it did not do", async () => {
    await reachIntake();

    // Two of the four blockers unanswered — the submit is withheld for exactly this.
    type("branches.0.label", "Main");
    type("branches.0.address", "12 MG Road, Hyderabad 500016");
    type("services.0.name", "Root canal");
    type("services.0.price_inr", "8000");

    const submit = screen.getByRole("button", { name: "Submit intake" }) as HTMLButtonElement;
    const save = screen.getByRole("button", { name: "Save draft" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    // THE ASSERTION THIS SLICE EXISTS FOR: incompleteness withholds the submit and must
    // not withhold the save, because a partial sheet is the only thing a draft is for.
    expect(save.disabled).toBe(false);

    const calls = stubApi({
      [DRAFT]: { agent_id: CREATED.agent_id, blockers: ["business_hours_missing"] },
      [ADMIN_ME]: OPERATOR,
      [UNFINISHED]: [],
      [INTAKE]: NO_INTAKE,
    });
    fireEvent.click(save);
    await screen.findByText("Draft saved");

    const post = postsTo(calls, DRAFT);
    expect(post).toHaveLength(1);
    // The draft route, not the submit — a "draft" that posts to the gated endpoint is
    // the missing feature wearing a button.
    expect(postsTo(calls, INTAKE)).toHaveLength(0);
    const body = JSON.parse(post[0]!.body ?? "{}");
    expect(body.branches).toEqual([{ label: "Main", address: "12 MG Road, Hyderabad 500016" }]);
    expect(body.services).toEqual([{ name: "Root canal", price_inr: "8000", notes: null }]);
    expect(body.business_hours).toEqual([]);
    expect(body.escalation_contacts).toEqual([]);

    // And it does not overclaim: nothing is compiled, and the count of what is still
    // missing comes from the SERVER's answer.
    expect(screen.getByText(/Nothing has been built into the agent yet/)).toBeTruthy();
    expect(screen.getByText(/1 answer still needed/)).toBeTruthy();
  });

  it("shows a failed save as a refusal instead of leaving 'saved' on screen", async () => {
    await reachIntake();
    type("branches.0.label", "Main");

    stubApi({
      [DRAFT]: problem(503, {
        title: "Service unavailable",
        detail: "The draft could not be saved right now.",
        remediation: "Try again in a minute — keep this tab open.",
        retryable: true,
      }),
      [ADMIN_ME]: OPERATOR,
      [UNFINISHED]: [],
      [INTAKE]: NO_INTAKE,
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));

    // The server's own words, and the action the operator can take. A silent failure
    // here is the worst outcome available: it teaches them the answers are safe.
    await screen.findByText("The draft could not be saved right now.");
    expect(screen.getByText("Try again in a minute — keep this tab open.")).toBeTruthy();
    expect(screen.queryByText("Draft saved")).toBeNull();
  });

  it("puts a structural refusal at the field it is about", async () => {
    await reachIntake();
    // A phone number the API's E.164 pattern refuses — a draft is refused for the same
    // structural reasons a submit is, because the sheet is parsed back on the way out.
    type("escalation_contacts.0.name", "Front desk");
    type("escalation_contacts.0.phone_e164", "9876543210");

    stubApi({
      [DRAFT]: problem(422, {
        title: "Request validation failed",
        fields: [
          {
            field: "escalation_contacts.0.phone_e164",
            rule: "string_pattern_mismatch",
            message: "String should match pattern '^\\+[1-9]\\d{7,18}$'",
          },
        ],
      }),
      [ADMIN_ME]: OPERATOR,
      [UNFINISHED]: [],
      [INTAKE]: NO_INTAKE,
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));

    const message = await screen.findByText(/String should match pattern/);
    const input = control("escalation_contacts.0.phone_e164");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(input.getAttribute("aria-describedby")).toContain(message.id);
  });

  it("withdraws 'Draft saved' as soon as an answer changes", async () => {
    await reachIntake();
    type("branches.0.label", "Main");
    stubApi({
      [DRAFT]: { agent_id: CREATED.agent_id, blockers: [] },
      [ADMIN_ME]: OPERATOR,
      [UNFINISHED]: [],
      [INTAKE]: NO_INTAKE,
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await screen.findByText("Draft saved");

    // The notice says "these answers are on file". One keystroke later that is false,
    // which is precisely the sentence a draft feature must not leave standing.
    type("branches.0.address", "12 MG Road");
    expect(screen.queryByText("Draft saved")).toBeNull();
  });
});

describe("resuming an unfinished onboarding", () => {
  it("lists what is unfinished and reopens it prefilled from the stored sheet", async () => {
    const { container } = renderAdminPage(<NewClientPage />, {
      [ADMIN_ME]: OPERATOR,
      [UNFINISHED]: [ABANDONED],
      [RESUMED_INTAKE]: HALF_ANSWERED,
    });

    await screen.findByText("Lakeview Dental");
    expect(container.textContent).toContain("/c/lakeview-dental");
    // The row's own evidence for the word "unfinished", in the server's codes.
    expect(container.textContent).toContain("A transfer during a call has nowhere to go");

    fireEvent.click(screen.getByRole("button", { name: /Resume/ }));
    await screen.findByText("Business hours");

    // Prefilled from the stored sheet, and NOT claiming the account was just created.
    expect(valueOf("branches.0.address")).toBe("12 MG Road, Hyderabad 500016");
    expect(valueOf("services.0.price_inr")).toBe("8000");
    expect(container.textContent).toContain("Resuming Lakeview Dental");
    expect(container.textContent).not.toContain("Account created");
  });

  it("renders the language set from the agent's own primary, not the wizard's", async () => {
    const { container } = await reachByResuming();

    // `language_primary` is Hindi on this agent. Nothing in this browser chose it —
    // step 1 was never walked — so a form that showed Telugu as fixed would be reading
    // its own default and calling it the client's answer.
    const hindi = screen.getByLabelText(/Hindi/) as HTMLInputElement;
    expect(hindi.checked).toBe(true);
    expect(hindi.disabled).toBe(true);
    expect(container.textContent).toContain("Primary — the agent's own language");
    // The stored EXTRA came back ticked and editable.
    const english = screen.getByLabelText(/English/) as HTMLInputElement;
    expect(english.checked).toBe(true);
    expect(english.disabled).toBe(false);
  });

  it("writes back to the account it resumed, not the one the wizard could create", async () => {
    await reachByResuming();
    const calls = stubApi({
      [RESUMED_DRAFT]: DRAFT_SAVED,
      [ADMIN_ME]: OPERATOR,
      [UNFINISHED]: [ABANDONED],
      [RESUMED_INTAKE]: HALF_ANSWERED,
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await screen.findByText("Draft saved");

    expect(postsTo(calls, RESUMED_DRAFT)).toHaveLength(1);
    expect(postsTo(calls, DRAFT)).toHaveLength(0);

    // And the BODY carries this agent's own primary among the languages, not the one
    // step 1 of this wizard defaults to. The form renders the primary from the response
    // either way, so the wire is the only place a borrowed default shows up: "te-IN"
    // here would silently add Telugu to a clinic that answers in Hindi and English.
    const body = JSON.parse(postsTo(calls, RESUMED_DRAFT)[0]!.body ?? "{}");
    expect([...body.languages].sort()).toEqual(["en-IN", "hi-IN"]);
  });

  it("says when the draft on file was written, from the server's stamp", async () => {
    const { container } = await reachByResuming();
    expect(container.textContent).toContain("Draft on file from");
    // And not the sentence for a client with nothing stored.
    expect(container.textContent).not.toContain("Nothing here is stored until you save");
  });
});

describe("when the resume list cannot be read", () => {
  it("refuses rather than reporting that nothing is unfinished", async () => {
    const { container } = renderAdminPage(<NewClientPage />, {
      [ADMIN_ME]: OPERATOR,
      [UNFINISHED]: problem(503, {
        title: "Service unavailable",
        detail: "The onboarding list could not be read.",
        remediation: "Retry in a minute.",
        retryable: true,
      }),
    });

    await screen.findByText("The onboarding list could not be read.");
    // THE ASSERTION: no empty state, no zero, no silence. An operator told "none" here
    // creates the client a second time, under a slug the first attempt already holds.
    expect(container.textContent).toContain("this list is not saying there are none");
    expect(screen.queryByRole("button", { name: /Resume/ })).toBeNull();
    // And the screen is not a dead end — step 1 is still there.
    expect(screen.getByRole("button", { name: "Create client" })).toBeTruthy();
  });

  it("shows a skeleton while the list is in flight, never an emptiness", async () => {
    const { container } = renderAdminPage(<NewClientPage />, {
      [ADMIN_ME]: OPERATOR,
      [UNFINISHED]: [ABANDONED],
    });

    // Before the query answers: the card is on screen with a skeleton in it, and says
    // nothing about how many onboardings are unfinished.
    expect(container.textContent).toContain("Unfinished onboardings");
    expect(screen.queryByRole("button", { name: /Resume/ })).toBeNull();
    expect(container.textContent).not.toContain("Accounts created but never through step 3");
    await screen.findByText("Lakeview Dental");
  });
});
