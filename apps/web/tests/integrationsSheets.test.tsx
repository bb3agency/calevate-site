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
 * 3. **`sheets_delivery_unavailable` renders as an informative state, in the server's own
 *    words.** This is the state EVERY deployment is in today: no Google service account is
 *    configured, so `create_sheets_endpoint` refuses before it writes anything. It is a
 *    founder/ops decision and not a fault, so it must not read as an error, must not be a
 *    dead button, and must not be second-guessed by a client-side capability check —
 *    there is no capability field to read, and inventing one would be a second copy of a
 *    server rule.
 * 4. **Other Sheets refusals keep the form.** An unparseable document reference is
 *    something the client can fix in the field they are looking at.
 * 5. **D-22.** Creating either kind is `org:manage`, which is mutating, so an impersonating
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
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", plan_tier: "managed" },
};

const CATALOGUE = {
  events: ["lead.created", "lead.updated", "call.completed", "campaign.completed"],
};

function render(over: Partial<Routes> = {}) {
  return renderClientPage(<IntegrationsPage />, {
    "/v1/me": OWNER,
    "/v1/integrations/endpoints": [],
    "/v1/integrations/deliveries": [],
    [EVENTS_PATH]: CATALOGUE,
    ...over,
  });
}

describe("the event catalogue", () => {
  it("builds both forms from the server's list rather than a local copy", async () => {
    const { container, calls } = await render({
      [EVENTS_PATH]: { events: ["lead.created", "campaign.completed"] },
    });

    await screen.findByText("Send events to a Google Sheet");
    expect(calls.filter((c) => c.path === EVENTS_PATH)).toHaveLength(1);
    // Two events offered, twice — once per form — and nothing else. A hardcoded list would
    // still be showing `lead.updated` and `call.completed` here.
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(4);
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
  });

  it("treats a 200 whose body it cannot read as a failed read, not an empty catalogue", async () => {
    // A shape we do not understand is ignorance, not "no events exist". Zero checkboxes
    // with no explanation is the empty state §52 forbids.
    const { container } = await render({ [EVENTS_PATH]: { not_events: [] } });

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("did not arrive in a shape we understand");
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(0);
  });

  it("names an event it cannot subscribe to instead of faking a checkbox for it", async () => {
    // The generated request body takes a literal union, so an event outside it cannot be
    // put in a typed request — a checkbox for it could only ever produce a 422. It means
    // our OpenAPI snapshot is behind the deployment, which is worth saying once.
    const { container } = await render({
      [EVENTS_PATH]: { events: ["lead.created", "call.transferred"] },
    });

    await screen.findByText("Send events to a Google Sheet");
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(2);
    expect(container.textContent).toContain("call.transferred");
    expect(container.textContent).toContain("cannot subscribe to yet");
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
      expect(container.textContent).toContain("No Google credential is attached yet"),
    );
  });

  it("renders the deployment's refusal as a state, with the server's own remediation", async () => {
    // THE case a real deployment hits today: no `GOOGLE_SHEETS_PROVIDER`, so the route
    // refuses before it writes anything. It is a founder/ops decision, not a fault — so
    // the words are the server's, the form goes away rather than sitting there to be
    // re-submitted, and nothing pretends a client-side check could have known.
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
