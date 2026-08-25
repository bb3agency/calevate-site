import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import IntegrationsPage from "@/app/c/[slug]/integrations/page";

import { problem, renderClientPage, type Routes } from "./harness";

/**
 * The two integration endpoints that shipped with no caller: the event CATALOGUE and the
 * Google Sheets create path.
 *
 * `GET /v1/integrations/events` existed while the screen carried its own hardcoded copy of
 * the same four names, and `POST /v1/integrations/endpoints/sheets` existed while the
 * screen could only create webhooks — so the Sheets adapter and its delivery worker were
 * both shipped and both unreachable.
 *
 * What this file pins:
 *
 * 1. **The checkbox list is the SERVER's list.** A hardcoded copy is a wire shape written
 *    by hand, one level up: a withdrawn event stays offered until it 422s and a new one
 *    ships invisible.
 * 2. **A failed catalogue read withholds BOTH forms and says why** (BUILD-LOG §52). The
 *    tempting failure is to fall back to the four names we know — which hides the failure
 *    behind four plausible checkboxes and offers a subscription the server may refuse.
 * 3. **The Sheets form is offered only where the deployment can deliver.**
 *    `EndpointOptions.sheets_delivery_available` is the SERVER's own selector — the same
 *    one `create_sheets_endpoint` asks — so the screen no longer discovers the refusal by
 *    attempting the create. Where it is false the form is GONE, not disabled: a founder/ops
 *    decision is not a fault, must not read as an error, and must not cost a client a
 *    support ticket to learn what one sentence tells them.
 * 4. **The capability is a hint and the server is still the authority.** It is read once
 *    and cached for half an hour, so the screen can be optimistic and wrong; a
 *    `sheets_delivery_unavailable` refusal still replaces the form, in the server's own
 *    words. A screen that trusted its own guess instead would be a second copy of a server
 *    rule, and the copy is what drifts.
 * 5. **Other Sheets refusals keep the form.** An unparseable document reference is
 *    something the client can fix in the field they are looking at.
 * 6. **D-22.** Creating either kind is `org:manage`, which is mutating, so an impersonating
 *    operator gets the reason beside the disabled control rather than a 403 after the
 *    click.
 */

const EVENTS_PATH = "/v1/integrations/events";
const SHEETS_PATH = "/v1/integrations/endpoints/sheets";

const OWNER = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["org:read", "org:manage", "calls:read_raw"],
  impersonating: false,
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

/**
 * The one read both forms are built from. `sheets_delivery_available` defaults to TRUE in
 * this fixture so the Sheets form is on screen for the tests that are about the form; the
 * false case has its own describe block, because on a real deployment today it is the
 * state every account is in.
 */
const OPTIONS = {
  events: ["lead.created", "lead.updated", "call.completed", "campaign.completed"],
  sheets_delivery_available: true,
};

/** The options body with one field overridden — the events list, or the capability. */
function options(over: Record<string, unknown> = {}) {
  return { ...OPTIONS, ...over };
}

function render(over: Partial<Routes> = {}) {
  return renderClientPage(<IntegrationsPage />, {
    "/v1/me": OWNER,
    "/v1/integrations/endpoints": [],
    "/v1/integrations/deliveries": [],
    [EVENTS_PATH]: OPTIONS,
    ...over,
  });
}

describe("the event catalogue", () => {
  it("builds both forms from the server's list rather than a local copy", async () => {
    const { container, calls } = await render({
      [EVENTS_PATH]: options({ events: ["lead.created", "campaign.completed"] }),
    });

    await screen.findByText("Send events to a Google Sheet");
    expect(calls.filter((c) => c.path === EVENTS_PATH)).toHaveLength(1);
    // Two events offered, twice — once per form — and nothing else. A hardcoded list would
    // still be showing `lead.updated` and `call.completed` here. Plus the webhook form's
    // three `call.completed` opt-in checkboxes (recording / transcript / raw transcript),
    // which live only on that form: 2 + 2 + 3 = 7.
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(7);
    expect(container.textContent).not.toContain("lead.updated");
    expect(container.textContent).not.toContain("call.completed");
  });

  it("withholds both forms and refuses when the catalogue cannot be read", async () => {
    // §52. The alternative — falling back to the four names this build knows — puts a
    // form on screen that was built from nothing, and hides the failure behind it.
    const { container } = await render({
      [EVENTS_PATH]: problem(503, {
        title: "Service unavailable",
        detail: "The list of events did not load.",
        retryable: true,
      }),
    });

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("The list of events did not load.");
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "Add endpoint" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add sheet" })).toBeNull();
    // And NOT the capability card either. A failed read is not a `false` capability, and
    // "Sheets is not switched on for your account" is a STATE — the exact substitution
    // §52 exists to stop. It renders only inside the success arm.
    expect(container.textContent).not.toContain("not switched on for your account");
  });

  it("treats a 200 whose body it cannot read as a failed read, not an empty catalogue", async () => {
    // A shape we do not understand is ignorance, not "no events exist". Zero checkboxes
    // with no explanation is the empty state §52 forbids.
    //
    // The declared response model (`EndpointOptionsOut`) is what makes both reads
    // `tsc`-checked, and it removed the `lookup` dance this guard used to need. The guard
    // itself stayed: the hook now hands the WHOLE body to the screen, so a missing
    // `events` would reach `EventChoices` as `undefined.filter(…)` — a blank screen,
    // which is worse than either state §52 is arguing between.
    const { container } = await render({ [EVENTS_PATH]: { not_events: [] } });

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("did not arrive in a shape we understand");
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(0);
  });

  it("refuses rather than reading a missing capability as 'Sheets is switched off'", async () => {
    // The half of the guard the capability field added. `sheets_delivery_available`
    // absent is NOT false: rendering the unavailable card off a missing field would print
    // our ignorance as one of the server's two answers, on the screen whose whole job is
    // telling a client which of them is true.
    const { container } = await render({
      [EVENTS_PATH]: { events: ["lead.created"] },
    });

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("did not arrive in a shape we understand");
    expect(container.textContent).not.toContain("not switched on for your account");
    expect(screen.queryByRole("button", { name: "Add sheet" })).toBeNull();
  });

  it("names an event it cannot subscribe to instead of faking a checkbox for it", async () => {
    // The generated request body takes a literal union, so an event outside it cannot be
    // put in a typed request — a checkbox for it could only ever produce a 422. It means
    // our OpenAPI snapshot is behind the deployment, which is worth saying once.
    const { container } = await render({
      [EVENTS_PATH]: options({ events: ["lead.created", "call.transferred"] }),
    });

    await screen.findByText("Send events to a Google Sheet");
    // One recognised event (`lead.created`) as a checkbox on each form, and NOT
    // `call.transferred` — plus the webhook form's three `call.completed` opt-ins:
    // 1 + 1 + 3 = 5. A faked checkbox for the unknown event would push this to 6.
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(5);
    expect(container.textContent).toContain("call.transferred");
    expect(container.textContent).toContain("cannot subscribe to yet");
  });
});

describe("the Sheets capability", () => {
  it("does not offer the form at all where the deployment cannot deliver", async () => {
    // The state EVERY deployment is in today: no Google service account, so
    // `sheets_delivery_available` is false and `POST …/endpoints/sheets` would refuse.
    // The screen now knows BEFORE anyone fills anything in, so the form is not offered —
    // and the card is where the form was, so the client is told rather than left to
    // wonder where Sheets went.
    const { container, calls } = await render({
      [EVENTS_PATH]: options({ sheets_delivery_available: false }),
    });

    await screen.findByText("Send events to a Google Sheet");
    expect(container.textContent).toContain(
      "Google Sheets delivery is not switched on for your account.",
    );
    // GONE, not disabled. A dead control costs a support ticket to learn what the
    // sentence above already says.
    expect(screen.queryByRole("button", { name: "Add sheet" })).toBeNull();
    expect(screen.queryByLabelText("Which sheet?")).toBeNull();
    expect(screen.queryByLabelText("Which tab? (optional)")).toBeNull();
    // Not an error: `role="alert"` is the rose ProblemNotice, and a founder/ops decision
    // is not a fault. "Try again" is not the remediation for a capability that does not
    // exist here.
    expect(screen.queryByRole("alert")).toBeNull();
    // Never asked. Discovering the refusal by ATTEMPTING the create is the defect this
    // capability field removed.
    expect(calls.some((c) => c.path === SHEETS_PATH)).toBe(false);
  });

  it("names the remediation the API's own refusal names", async () => {
    // The words are ours here — the server sent a boolean, not a sentence — so they have
    // to point where the server's refusal points, or a client who meets both hears two
    // different stories about one fact.
    const { container } = await render({
      [EVENTS_PATH]: options({ sheets_delivery_available: false }),
    });

    await screen.findByText("Send events to a Google Sheet");
    expect(container.textContent).toContain("Set up a delivery to your own system above instead");
    // The webhook form is the remediation, so it must still be there and still usable.
    // (Its submit is disabled until a URL is typed — that is the form's own rule, not a
    // permission — so the INPUT is what "usable" means here.)
    expect(screen.getByRole("button", { name: "Add endpoint" })).toBeTruthy();
    expect(screen.getByLabelText("Where should we send them?")).toHaveProperty(
      "disabled",
      false,
    );
  });

  it("offers the form where the deployment can deliver", async () => {
    // The other direction, and the reason a hardcoded "hide it" would have been wrong:
    // the day Sheets is enabled the form has to appear on its own.
    await render({ [EVENTS_PATH]: options({ sheets_delivery_available: true }) });

    expect(await screen.findByLabelText("Which sheet?")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Add sheet" })).toBeTruthy();
    expect(
      screen.queryByText("Google Sheets delivery is not switched on for your account."),
    ).toBeNull();
  });
});

describe("registering a Google Sheet", () => {
  it("sends the document reference, the tab and the events, and reports what came back", async () => {
    const { container, calls } = await render({
      [SHEETS_PATH]: {
        id: "0192f0aa-3333-7000-8000-000000000001",
        kind: "google_sheets",
        spreadsheet_id: "1AbCdEfGhIjKlMnOpQrStUvWxYz",
        worksheet: "Leads",
        events: ["lead.created"],
        active: true,
        credential_attached: false,
      },
    });

    const sheet = await screen.findByLabelText("Which sheet?");
    fireEvent.change(sheet, {
      target: { value: "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/edit" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add sheet" }));

    await waitFor(() => expect(calls.some((c) => c.path === SHEETS_PATH)).toBe(true));
    const sent = JSON.parse(calls.find((c) => c.path === SHEETS_PATH)!.body!);
    expect(sent).toEqual({
      spreadsheet: "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/edit",
      events: ["lead.created"],
      // An untouched optional tab is null, not "": the server would strip a blank anyway,
      // and sending null says what we mean.
      worksheet: null,
    });

    await screen.findByText("Sheet added");
    // `credential_attached: false` is the honest state of every endpoint this route can
    // create — a client cannot supply the Google credential — and the screen says so
    // rather than implying the sheet is live.
    await waitFor(() =>
      expect(container.textContent).toContain("We haven't connected to Google yet"),
    );
  });

  it("renders a refusal the capability did not warn about, in the server's own words", async () => {
    // The STALE-CAPABILITY case, and the reason the refusal branch survives the
    // capability field. `sheets_delivery_available` is read once and cached for half an
    // hour, so an operator switching Sheets off mid-session leaves this screen optimistic
    // and wrong. The server refuses anyway — that is the authority — and the screen
    // renders the server's own words rather than its own guess about what happened.
    const { container } = await render({
      [SHEETS_PATH]: problem(422, {
        type: "urn:calevate:business_rule/sheets_delivery_unavailable",
        title: "Google Sheets delivery is not available",
        detail: "This account cannot deliver leads to Google Sheets yet.",
        remediation:
          "Register a webhook endpoint instead, or contact support to have Google Sheets enabled for your account.",
        kind: "business_rule",
      }),
    });

    const sheet = await screen.findByLabelText("Which sheet?");
    fireEvent.change(sheet, { target: { value: "1AbCdEfGhIjKlMnOpQrStUvWxYz" } });
    fireEvent.click(screen.getByRole("button", { name: "Add sheet" }));

    await screen.findByText("This account cannot deliver leads to Google Sheets yet.");
    expect(container.textContent).toContain(
      "Register a webhook endpoint instead, or contact support to have Google Sheets enabled",
    );
    expect(container.textContent).toContain("Nothing was created, so there is nothing to undo.");
    // Not an error panel: `role="alert"` is the rose ProblemNotice, and "try again" is not
    // the remediation for a capability the deployment does not have.
    expect(screen.queryByRole("alert")).toBeNull();
    // And no dead button left behind: the form is replaced by the explanation, not
    // disabled beside it.
    expect(screen.queryByRole("button", { name: "Add sheet" })).toBeNull();
    // The webhook form is untouched — it is the remediation the server just named.
    expect(screen.getByRole("button", { name: "Add endpoint" })).toBeTruthy();
  });

  it("keeps the form on a refusal the client can act on", async () => {
    // An unparseable document reference is fixable in the field they are looking at, so
    // this one renders through ProblemNotice with the form still there.
    const { container } = await render({
      [SHEETS_PATH]: problem(422, {
        type: "urn:calevate:validation/invalid_spreadsheet_ref",
        title: "Not a Google Sheets document",
        detail: "That is not a Google Sheets link or document id.",
        remediation: "Paste the URL from your browser's address bar while the sheet is open.",
        kind: "validation",
      }),
    });

    const sheet = await screen.findByLabelText("Which sheet?");
    fireEvent.change(sheet, { target: { value: "my spreadsheet" } });
    fireEvent.click(screen.getByRole("button", { name: "Add sheet" }));

    await screen.findByText("That is not a Google Sheets link or document id.");
    expect(screen.getByRole("button", { name: "Add sheet" })).toBeTruthy();
    expect(container.textContent).toContain("Paste the URL from your browser's address bar");
  });

  it("labels every field persistently, not with a placeholder", async () => {
    // axe accepts a placeholder as an accessible name, which is why this defect survived
    // the sweep once already — and the text disappears the moment somebody types.
    await render();

    expect(await screen.findByLabelText("Which sheet?")).toBeTruthy();
    expect(screen.getByLabelText("Which tab? (optional)")).toBeTruthy();
    expect(screen.getByLabelText("Where should we send them?")).toBeTruthy();
  });
});

describe("D-22 on the create paths", () => {
  it("disables both forms with the reason rather than letting the click 403", async () => {
    const { container } = await render({
      "/v1/me": { ...OWNER, impersonating: true },
    });

    await screen.findByText(/viewing this account read-only/);
    expect(screen.getByRole("button", { name: "Add sheet" })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Add endpoint" })).toHaveProperty("disabled", true);
    // Every input too — a form that accepts typing and refuses the submit wastes the
    // operator's time twice.
    for (const input of container.querySelectorAll("form input")) {
      expect(input).toHaveProperty("disabled", true);
    }
  });

  it("tells a member of staff who may do it instead", async () => {
    await render({
      "/v1/me": { ...OWNER, role: "staff", permissions: ["org:read"] },
    });

    await screen.findByText(/Only an account owner can change where events are sent/);
    expect(screen.getByRole("button", { name: "Add sheet" })).toHaveProperty("disabled", true);
  });
});
