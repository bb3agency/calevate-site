import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import NewClientPage from "@/app/admin/new/page";
import type { AdminMe } from "@/app/admin/access";
import type { CreateOrgOut } from "@/lib/api/admin";
import { intakeFieldId, type IntakeState } from "@/lib/api/intake";

import { problem, renderAdminPage, stubApi, type ApiCall, type Routes } from "./harness";

/**
 * The wizard's intake step — FLOWS §1 step 3 (`/admin/new`, `IntakeStep`).
 *
 * The API shipped in BUILD-LOG §45 and nothing in either realm called it, so the
 * assertions here are about the seam that was missing rather than about pixels. Five of
 * them, each pinning a way the step could pass its own screenshot and still be wrong:
 *
 * 1. **What goes on the wire is FLOWS §1's eight fields and nothing else.** The body is
 *    asserted key by key, and the key COUNT is asserted too — an invented ninth field is
 *    the specific failure the API's authors argued against, and it would sail past any
 *    assertion that only checked the fields it knew about.
 * 2. **The GET prefills.** A form that discards stored answers is worse than no form: the
 *    POST replaces the sheet, so the second visit would silently overwrite the first.
 * 3. **A failed GET refuses; it does not render an empty form** (BUILD-LOG §52). This is
 *    the one that matters most here. "No answers yet" and "we could not read the answers"
 *    look identical on a blank form, and the operator's next move — type them again and
 *    submit — destroys what was stored.
 * 4. **A field-level refusal lands AT its field**, wired with `aria-invalid` /
 *    `aria-describedby` rather than only listed at the top of a forty-control form.
 * 5. **The permission gate explains itself where the control is.** The route is
 *    `agents:write`, which is NOT the permission that got the operator to this screen.
 *
 * Plus two properties of the wizard the step sits in: the answers survive the walk to the
 * invite step and back, and the submit is refused before it is sent when the server's own
 * `submission_blockers` would refuse it.
 *
 * A harness note that shapes several tests below: routes are keyed by PATH, so the GET
 * and the POST of this endpoint cannot answer differently in one table. Where a test
 * needs both, it re-stubs after the prefill has landed — `stubApi` hands back a fresh
 * call log, which is the one the write's assertions read.
 */

const TENANTS = "/v1/admin/tenants";
const ADMIN_ME = "/v1/admin/me";

const CREATED: CreateOrgOut = {
  id: "0192f0aa-7777-7000-8000-000000000001",
  slug: "sunrise-clinic",
  status: "active",
  agent_id: "0192f0aa-7777-7000-8000-0000000000a1",
  extraction_schema_id: "0192f0aa-7777-7000-8000-0000000000b1",
  vertical_template: "clinic",
};

const INTAKE = `${TENANTS}/${CREATED.id}/agents/${CREATED.agent_id}/intake`;
/** The resume list, read by `/admin/new` before step 1 is even filled in. Empty here:
 *  these tests are about the step, and `adminNewResume.test.tsx` owns the list. */
const UNFINISHED = "/v1/admin/onboarding/unfinished";

function me(permissions: string[]): AdminMe {
  return {
    realm: "admin",
    user_id: "0192f0aa-7777-7000-8000-0000000000f2",
    role: "operator",
    permissions,
  };
}

/** What `core/rbac.py` gives an `operator` — `agents:write` among them. */
const OPERATOR = me(["org:read", "agents:read", "agents:write", "admin:tenants"]);

/** A brand-new agent: the API answers 200 with everything empty, never a 404. */
const NO_INTAKE: IntakeState = {
  business_hours: {},
  escalation_contacts: [],
  languages: [],
  prose_answers: null,
  compiled_t0_context: null,
  submitted_at: null,
  saved_at: null,
  // The agent's own language, which the response now carries: the form's language set
  // is the EXTRAS plus this, and a caller that arrived by resuming has no other source.
  language_primary: "te-IN",
  sheet_agent_id: null,
  owner_present: false,
};

/** `IntakeOut` when the answers compiled into something new. */
const RECORDED = {
  agent_id: CREATED.agent_id,
  prompt_version: 2,
  regenerated: true,
  kb_source_id: "0192f0aa-7777-7000-8000-0000000000c1",
};

/**
 * Reach step 3 the way an operator does — through step 1, not by mounting the component.
 *
 * The step being REACHABLE is half of what this slice is: a form nobody can navigate to
 * is a defect that looks like progress. So every test below walks the wizard.
 */
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
  // The step is a skeleton until its prefill answers; every assertion is about what is
  // on the other side of that.
  await screen.findByText("Business hours");
  return render;
}

/**
 * One control, by the WIRE PATH it sends.
 *
 * Seven "Opens" boxes and three "Name" boxes make a label query ambiguous, and the id is
 * not a test-only handle: `intakeFieldId` builds it from the path so that the `<label>`,
 * the input and the server's `field` all name one thing. Reading it back here asserts
 * that contract as much as it locates the box.
 */
function control(path: string): HTMLElement {
  const element = document.getElementById(intakeFieldId(path));
  if (element === null) throw new Error(`no control rendered for ${path}`);
  return element;
}

const valueOf = (path: string) => (control(path) as HTMLInputElement).value;

function type(path: string, value: string): void {
  fireEvent.change(control(path), { target: { value } });
}

/** The minimum `submission_blockers` accepts: hours, an address, a service, a contact.
 *  FAQs, staff and booking rules are deliberately not required by the API. */
function fillTheMinimum(): void {
  type("business_hours.mon.opens", "09:00");
  type("business_hours.mon.closes", "18:00");
  type("branches.0.label", "Main branch");
  type("branches.0.address", "12 Necklace Road, Hyderabad 500003");
  type("services.0.name", "Consultation");
  type("services.0.price_inr", "500");
  type("escalation_contacts.0.name", "Front desk");
  type("escalation_contacts.0.phone_e164", "+919876543210");
}

/** Press submit against a freshly stubbed network, and return ITS call log. */
function submitAgainst(answer: unknown): ApiCall[] {
  const calls = stubApi({ [INTAKE]: answer, [ADMIN_ME]: OPERATOR, [UNFINISHED]: [] });
  fireEvent.click(screen.getByRole("button", { name: "Submit intake" }));
  return calls;
}

const posts = (calls: ApiCall[]) =>
  calls.filter((call) => call.path === INTAKE && call.method === "POST");

/**
 * A client whose intake is already on file — and, deliberately, one that answers all four
 * of `submission_blockers`' conditions. That second property is load-bearing outside the
 * prefill tests: it is what lets the permission test observe the gate rather than the
 * blocker list, which disables the same button for a different reason.
 */
const STORED: IntakeState = {
  business_hours: { mon: { opens: "10:00", closes: "19:00" }, sun: null },
  escalation_contacts: [{ name: "Dr Prasad", phone_e164: "+919812345678", hours: "Mon-Sat" }],
  languages: ["hi-IN"],
  prose_answers: {
    branches: [{ label: "Banjara Hills", address: "3 Road No 12" }],
    services: [{ name: "Root canal", price_inr: "4500.50", notes: "Two sittings" }],
    faqs: [{ question: "Do you take walk-ins?", answer: "Yes, before 11am." }],
    staff: [{ name: "Dr Prasad", pronunciation: "pra-SAAD", role: "Dentist" }],
    booking_rules: "Slots every 20 minutes.",
  },
  compiled_t0_context: "[T0 FACTS]\nHours: mon 10:00-19:00; sun closed",
  submitted_at: "2026-08-01T04:30:00Z",
  saved_at: "2026-08-01T04:30:00Z",
  language_primary: "te-IN",
  sheet_agent_id: CREATED.agent_id,
  owner_present: false,
};

describe("submitting the intake", () => {
  it("sends FLOWS §1's eight fields, and only those eight", async () => {
    await reachIntake();
    fillTheMinimum();

    const calls = submitAgainst(RECORDED);
    await screen.findByText("Intake recorded");

    const post = posts(calls);
    expect(post).toHaveLength(1);
    const body = JSON.parse(post[0]!.body ?? "{}");

    // The COUNT first: a ninth field would sail past every assertion below it.
    expect(Object.keys(body).sort()).toEqual([
      "booking_rules",
      "branches",
      "business_hours",
      "escalation_contacts",
      "faqs",
      "languages",
      "services",
      "staff",
    ]);
    expect(body).toEqual({
      // Only the day that was answered. The six blanks are absent rather than sent as
      // half-empty rows — "nobody filled Saturday in" is not "Saturday is closed", and a
      // day with one time is the `business_hours_incomplete` blocker.
      business_hours: [{ day: "mon", closed: false, opens: "09:00", closes: "18:00" }],
      branches: [{ label: "Main branch", address: "12 Necklace Road, Hyderabad 500003" }],
      // `price_inr` is the STRING the operator typed (hard rule 7) and `notes` is `null`
      // rather than `""` — the API's pattern refuses an empty string where `null` means
      // "not answered".
      services: [{ name: "Consultation", price_inr: "500", notes: null }],
      faqs: [],
      staff: [],
      booking_rules: null,
      escalation_contacts: [{ name: "Front desk", phone_e164: "+919876543210", hours: null }],
      // The primary from step 1, which the server drops on the way in (`languages_extra`
      // means the OTHERS) — sending it is what makes the round trip stable.
      languages: ["te-IN"],
    });
  });

  it("reports the prompt version it minted, and the KB source awaiting approval", async () => {
    await reachIntake();
    fillTheMinimum();
    submitAgainst(RECORDED);

    await screen.findByText("Intake recorded");
    expect(screen.getByText(/prompt version/).textContent).toContain("2");
    expect(screen.getByText(/queued in the knowledge base awaiting approval/)).toBeTruthy();
  });

  it("does not dress the idempotent answer as a failure", async () => {
    await reachIntake();
    fillTheMinimum();
    // `regenerated: false` is what reopening the step and saving it unchanged returns —
    // FLOWS §1's "every step idempotent", and a success.
    submitAgainst({ ...RECORDED, prompt_version: 1, regenerated: false, kb_source_id: null });

    await screen.findByText("Intake recorded");
    expect(screen.getByText(/already match what the agent carries/)).toBeTruthy();
  });

  it("refuses to send a body the server's own gate would reject", async () => {
    const { calls, container } = await reachIntake();

    // Only the address answered: no hours, no service, no escalation contact.
    type("branches.0.label", "Main branch");
    type("branches.0.address", "12 Necklace Road");

    const submit = screen.getByRole("button", { name: "Submit intake" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    // Each blocker names what downstream cannot work without it, in the server's terms —
    // and the one the operator HAS answered is absent from the list.
    expect(container.textContent).toContain("The agent uses these hours to handle after-hours calls");
    expect(container.textContent).toContain("A transfer during a call has nowhere to go");
    expect(container.textContent).toContain("The price list is both what the agent answers from");
    expect(container.textContent).not.toContain("No address.");

    fireEvent.click(submit);
    expect(posts(calls)).toHaveLength(0);
  });
});

describe("reopening the step", () => {
  it("prefills every stored answer rather than opening blank", async () => {
    const { calls, container } = await reachIntake({ [INTAKE]: STORED });

    expect(valueOf("business_hours.mon.opens")).toBe("10:00");
    expect(valueOf("business_hours.mon.closes")).toBe("19:00");
    // `null` IS the closed day (`_hours_map`), and it must not come back as an
    // unanswered one — the agent says different things about the two.
    expect((control("business_hours.sun.closes") as HTMLInputElement).disabled).toBe(true);
    expect(valueOf("business_hours.tue.opens")).toBe("");
    expect((control("business_hours.tue.closes") as HTMLInputElement).disabled).toBe(false);

    expect(valueOf("branches.0.label")).toBe("Banjara Hills");
    expect(valueOf("services.0.price_inr")).toBe("4500.50");
    expect(valueOf("faqs.0.question")).toBe("Do you take walk-ins?");
    expect(valueOf("staff.0.pronunciation")).toBe("pra-SAAD");
    expect((control("booking_rules") as HTMLTextAreaElement).value).toBe(
      "Slots every 20 minutes.",
    );
    expect(valueOf("escalation_contacts.0.name")).toBe("Dr Prasad");
    expect(valueOf("escalation_contacts.0.hours")).toBe("Mon-Sat");

    // The stored EXTRA language came back ticked, and the primary is ticked and fixed.
    expect((screen.getByLabelText(/Hindi/) as HTMLInputElement).checked).toBe(true);
    expect(container.textContent).toContain("Primary — the agent's own language");
    // The server's own stamp, not a claim this screen made.
    expect(container.textContent).toContain("Last submitted");

    // Reading is not writing: reopening the step must not post anything.
    expect(posts(calls)).toHaveLength(0);
  });

  it("round-trips the stored answers unchanged when nothing is edited", async () => {
    await reachIntake({ [INTAKE]: STORED });
    const calls = submitAgainst(RECORDED);
    await screen.findByText("Intake recorded");

    const body = JSON.parse(posts(calls)[0]!.body ?? "{}");
    expect(body.business_hours).toEqual([
      { day: "mon", closed: false, opens: "10:00", closes: "19:00" },
      { day: "sun", closed: true, opens: null, closes: null },
    ]);
    expect(body.services).toEqual([
      { name: "Root canal", price_inr: "4500.50", notes: "Two sittings" },
    ]);
    // The primary is re-added to the extras the response carried, which is what keeps a
    // save-with-no-edits from quietly dropping a language.
    expect(body.languages.sort()).toEqual(["hi-IN", "te-IN"]);
  });

  it("explains an org whose prose predates the column that holds it", async () => {
    // `prose_answers: null` WITH stored evidence — a pre-migration org, not a new agent.
    const { container } = await reachIntake({ [INTAKE]: { ...STORED, prose_answers: null } });

    expect(container.textContent).toContain("Only the summary we build for the agent is kept");
    // The block is printed so the operator can retype from it, rather than parsed back
    // into fields this form would then be asserting a price it had itself written.
    expect(container.textContent).toContain("[T0 FACTS]");
    // And the empty rows are NOT presented as "this client has no services".
    expect(screen.queryByText("Root canal")).toBeNull();
    expect(valueOf("services.0.name")).toBe("");
  });

  it("says nothing about a pre-migration gap on an agent that simply has no intake", async () => {
    // The same `prose_answers: null`, with nothing else stored. A brand-new agent must
    // not be told its answers were lost.
    const { container } = await reachIntake();
    expect(container.textContent).not.toContain("Only the summary we build for the agent is kept");
  });

  it("withdraws the owner invite once somebody has accepted, and says why", async () => {
    /* The step exists to get an owner INTO the account. Offering it afterwards invites
       an operator to redo work that is done, and the next screen would then either be
       refused (`invitation_already_pending`) or hand a second key to an account that
       already has an owner.

       `owner_present` is the signal and NOT "are there pending invitations", because
       `list_pending_invitations` filters `used_at IS NULL AND expires_at > now()` — so
       an empty list means never-invited, consumed OR expired, and only the middle one
       should hide this control. The other two are exactly when it is still needed. */
    await reachIntake({ [INTAKE]: { ...STORED, owner_present: true } });

    expect(screen.queryByRole("button", { name: /Continue to the owner invite/ })).toBeNull();
    // Withdrawn WITH a reason: a control that vanishes silently sends an operator
    // hunting for a button they remember.
    expect(screen.getByText(/already accepted into this account/i)).toBeTruthy();
  });

  it("still offers it while nobody has accepted — invited, expired or never sent", async () => {
    // `owner_present: false` is all three of those states, which is the point of using it.
    await reachIntake({ [INTAKE]: { ...STORED, owner_present: false } });
    expect(
      await screen.findByRole("button", { name: /Continue to the owner invite/ }),
    ).toBeTruthy();
  });

  it("keeps the answers when the operator walks to the invite step and back", async () => {
    await reachIntake();

    type("branches.0.address", "12 Necklace Road, Hyderabad 500003");
    fireEvent.click(screen.getByRole("button", { name: /Continue to the owner invite/ }));
    await screen.findByText("Invite the owner");
    fireEvent.click(screen.getByRole("button", { name: /Back to the intake/ }));

    await screen.findByText("Business hours");
    expect(valueOf("branches.0.address")).toBe("12 Necklace Road, Hyderabad 500003");
  });
});

describe("when the prefill cannot be read", () => {
  it("refuses, and withholds the form rather than showing an empty one", async () => {
    const render = renderAdminPage(<NewClientPage />, {
      [TENANTS]: CREATED,
      [ADMIN_ME]: OPERATOR,
      [UNFINISHED]: [],
      [INTAKE]: problem(503, {
        title: "Service unavailable",
        detail: "The intake could not be read right now.",
        remediation: "Try again in a minute.",
        retryable: true,
      }),
    });
    fireEvent.change(screen.getByPlaceholderText("Sunrise Clinic"), {
      target: { value: "Sunrise Clinic" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create client" }));

    await screen.findByText("The intake could not be read right now.");
    expect(render.container.textContent).toContain(
      "Cannot fill the intake while the stored answers are unreadable",
    );
    expect(render.container.textContent).toContain("Try again in a minute.");

    // THE ASSERTION THIS FILE EXISTS FOR: no form, not an empty form. A blank sheet here
    // invites the operator to retype the answers and POST them over what is stored.
    expect(document.getElementById(intakeFieldId("branches.0.label"))).toBeNull();
    expect(document.getElementById(intakeFieldId("business_hours.mon.opens"))).toBeNull();
    expect(screen.queryByRole("button", { name: "Submit intake" })).toBeNull();
    // Nothing about the emptiness reads as a fact about the client.
    expect(render.container.textContent).not.toContain("None yet");
    expect(render.container.textContent).not.toContain("Still needed before this can be submitted");

    // The wizard is not a dead end: the operator can still reach the owner invite.
    expect(screen.getByRole("button", { name: /Skip to the owner invite/ })).toBeTruthy();
  });
});

describe("a refusal about one answer", () => {
  it("lands next to the field it is about, wired to that input", async () => {
    await reachIntake();
    fillTheMinimum();
    // A price an Indian operator types by hand and the API's pattern refuses.
    type("services.0.price_inr", "₹500/-");

    submitAgainst(
      problem(422, {
        title: "Request validation failed",
        detail: "One or more fields are invalid.",
        fields: [
          {
            field: "services.0.price_inr",
            rule: "string_pattern_mismatch",
            message: "String should match pattern '^\\d+(\\.\\d{1,2})?$'",
          },
        ],
      }),
    );

    const message = await screen.findByText(/String should match pattern/);
    const input = control("services.0.price_inr");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    // Announced AS that input's description, not merely printed somewhere near it.
    expect(input.getAttribute("aria-describedby")).toContain(message.id);
    expect(message.id).toBe(`${intakeFieldId("services.0.price_inr")}-error`);

    // The summary points at the field rather than repeating its sentence.
    expect(screen.getByText("Check the answers marked below.")).toBeTruthy();
    expect(screen.queryAllByText(/String should match pattern/)).toHaveLength(1);
  });

  it("withdraws the refusal the moment the answer is edited", async () => {
    await reachIntake();
    fillTheMinimum();
    type("services.0.price_inr", "₹500/-");
    submitAgainst(
      problem(422, {
        title: "Request validation failed",
        fields: [
          { field: "services.0.price_inr", rule: "string_pattern_mismatch", message: "Bad price" },
        ],
      }),
    );
    await screen.findByText("Bad price");

    // The message is placed by RECOMPUTING the row map from the current draft, which is
    // only sound because an edit clears the refusal. If it ever stops clearing, a message
    // could outlive the request it belongs to and point at a different row.
    type("services.0.price_inr", "500");
    expect(screen.queryByText("Bad price")).toBeNull();
    expect(control("services.0.price_inr").getAttribute("aria-invalid")).toBeNull();
  });

  it("keeps the refusal on the right row after blank rows are dropped", async () => {
    await reachIntake();
    fillTheMinimum();
    fireEvent.click(screen.getByRole("button", { name: "Add a service" }));
    // The SECOND service carries the bad price and the first is emptied, so exactly one
    // service goes on the wire — at index 0. The form has to renumber with it, or the
    // server's `services.0.price_inr` lands on a row the operator did not type.
    type("services.1.name", "Whitening");
    type("services.1.price_inr", "₹2000");
    type("services.0.name", "");
    type("services.0.price_inr", "");

    submitAgainst(
      problem(422, {
        title: "Request validation failed",
        fields: [
          { field: "services.0.price_inr", rule: "string_pattern_mismatch", message: "Bad price" },
        ],
      }),
    );

    await screen.findByText("Bad price");
    // The surviving row IS row 0 now — on screen and on the wire — and it is the one
    // wearing the refusal.
    expect(valueOf("services.0.name")).toBe("Whitening");
    expect(control("services.0.price_inr").getAttribute("aria-invalid")).toBe("true");
    expect(document.getElementById(intakeFieldId("services.1.price_inr"))).toBeNull();
  });

  it("resolves a day-level refusal by day rather than by position", async () => {
    await reachIntake();
    fillTheMinimum();
    // Wednesday is the SECOND answered day, so it is `business_hours.1` on the wire while
    // sitting third in a form that always shows all seven. (The times are valid: `type=
    // "time"` cannot hold anything else, so a day-level refusal is necessarily a rule
    // this side does not preview — which is exactly the case that has to land somewhere.)
    type("business_hours.wed.opens", "09:00");
    type("business_hours.wed.closes", "18:00");

    submitAgainst(
      problem(422, {
        title: "Request validation failed",
        fields: [
          {
            field: "business_hours.1.opens",
            rule: "string_pattern_mismatch",
            message: "Not a time of day",
          },
        ],
      }),
    );

    const message = await screen.findByText("Not a time of day");
    expect(message.id).toBe(`${intakeFieldId("business_hours.wed.opens")}-error`);
    expect(control("business_hours.wed.opens").getAttribute("aria-invalid")).toBe("true");
    // And emphatically not on Monday, which is `business_hours.0`.
    expect(control("business_hours.mon.opens").getAttribute("aria-invalid")).toBeNull();
  });

  it("puts a message about a field this form has no input for in the summary", async () => {
    await reachIntake();
    fillTheMinimum();

    submitAgainst(
      problem(422, {
        title: "Request validation failed",
        detail: "One or more fields are invalid.",
        // A path this build renders no control for — an API that grew a ninth answer, or
        // a shape nobody predicted. Dropping it would be the worst outcome of the three.
        fields: [{ field: "loyalty_tier", rule: "missing", message: "Field required" }],
      }),
    );

    // The path names itself and carries its message — the summary is the only place a
    // control-less refusal can be seen at all.
    const named = await screen.findByText("loyalty_tier");
    expect(named.parentElement?.textContent).toContain("Field required");
  });

  it("renders a whole-request refusal as a refusal, not as a red box", async () => {
    await reachIntake();
    fillTheMinimum();

    // `intake_incomplete` — a business-rule refusal with no field list, which is the
    // server disagreeing with this screen's own preview. Its remediation is the point.
    submitAgainst(
      problem(422, {
        type: "urn:calevate:business_rule/intake_incomplete",
        title: "Intake incomplete",
        detail: "The intake is missing answers the agent needs: service_missing.",
        remediation: "Save the step as a draft, finish these answers, then submit.",
      }),
    );

    await screen.findByText("The intake is missing answers the agent needs: service_missing.");
    expect(
      screen.getByText("Save the step as a draft, finish these answers, then submit."),
    ).toBeTruthy();
    expect(screen.queryByText("Check the answers marked below.")).toBeNull();
  });
});

describe("the permission gate", () => {
  it("stops offering the submit and says which permission is missing, at the control", async () => {
    // `agents:read` without `agents:write` — the route's own permission, and NOT the one
    // that got this session as far as the wizard (`admin:tenants`).
    // STORED, not an empty intake: a form with nothing in it disables the same button
    // through `submission_blockers`, so an empty fixture here would assert the gate and
    // measure the blocker list (BUILD-LOG §52's note on sabotages below an earlier guard
    // — this exact test passed with the gate removed until the fixture changed).
    const { calls, container } = await reachIntake({
      [ADMIN_ME]: me(["org:read", "agents:read", "admin:tenants"]),
      [INTAKE]: STORED,
    });
    expect(screen.queryByText("Still needed before this can be submitted:")).toBeNull();

    // TWICE, deliberately: once at the head of the form where the first disabled input
    // is, once beside the submit at the foot of it. A dead control with no sentence is a
    // support ticket, and forty controls is too far to carry an explanation.
    expect(await screen.findAllByText(/does not have permission to/)).toHaveLength(2);
    const submit = screen.getByRole("button", { name: "Submit intake" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    expect(submit.title).toContain("record this client's intake");
    expect(container.textContent).toContain("Ask a superadmin");
    // The inputs go with it — filling forty boxes that cannot be submitted is waste.
    expect((control("branches.0.label") as HTMLInputElement).disabled).toBe(true);

    fireEvent.click(submit);
    expect(posts(calls)).toHaveLength(0);
  });

  it("does not read a failed identity check as a refusal", async () => {
    // `/v1/admin/me` is down. "We could not ask" is not "you may not" — the control is
    // still withheld (a control fails closed) but the sentence must not accuse a role of
    // lacking a permission nobody checked.
    const { container } = await reachIntake({
      [ADMIN_ME]: problem(503, { title: "Service unavailable", detail: "Identity unavailable." }),
    });

    expect(
      await screen.findAllByText(/We could not check whether you may record this client's intake/),
    ).toHaveLength(2);
    expect(container.textContent).not.toContain("does not have permission to");
  });
});
