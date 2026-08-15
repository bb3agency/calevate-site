import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LeadSourcesPage from "@/app/c/[slug]/lead-sources/page";
import type { Me } from "@/lib/api/client";
import type { IngestActivityItem, LeadSource, MetaSetup } from "@/lib/api/leadSources";

import { problem, renderClientPage, stillLoading } from "./harness";

/**
 * Lead sources — where leads arrive from, and the screen a client opens at exactly the
 * moment they are asking "is this thing even connected?".
 *
 * That question is what makes the failure modes here specific. Ranked by cost:
 *
 * 1. **"No deliveries yet" printed under a failed request.** The person reading it came
 *    to find out whether their form is reaching us. Told that nothing has arrived, they
 *    go and change a working integration — so a request that did not land must produce a
 *    refusal and no table at all.
 * 2. **Implying a source is connected or verified when nothing has been verified.** The
 *    Meta card hands over setup material; it has not spoken to Meta, cannot see the
 *    client's App Dashboard, and in this deployment cannot even read the answers a lead
 *    typed (`lead_retrieval_available: false`). Each of those must be stated where
 *    someone reads it BEFORE spending ad money, not inferred from a rejections column.
 * 3. **The verify token leaking into a URL or onto the screen unasked.** It is a
 *    credential — the endpoint is a POST for that reason alone — so it is masked until
 *    revealed, and the callback URL it sits beside must carry none of it.
 * 4. **A sample payload's phone number in a query string.** The dry-run body is the only
 *    place a number may travel (hard rule 6); the path carries a UUID and nothing else.
 */

const ACTIVITY_PATH = "/v1/lead-sources/activity";
const SOURCES_PATH = "/v1/lead-sources";
const AGENTS_PATH = "/v1/agents";
/** One path, two verbs: the list is a GET and creation is a POST. */
const CREATE_PATH = "POST /v1/lead-sources";
/** A Meta source, so it appears in BOTH pickers (the Meta one filters to its kind). */
const SOURCE_ID = "018f3c00-0000-7000-8000-000000000001";
const FORM_SOURCE_ID = "018f3c00-0000-7000-8000-000000000002";
/** A SECOND Meta source, so the picker can move between two of the same kind. */
const SECOND_META_SOURCE_ID = "018f3c00-0000-7000-8000-000000000003";
const TEST_PATH = `/v1/lead-sources/${SOURCE_ID}/test`;
const META_PATH = `/v1/lead-sources/${SOURCE_ID}/meta/setup`;
const TOKEN = "verify-token-9f2c4a";

const ME: Me = {
  impersonating: false,
  permissions: ["org:read", "org:manage", "leads:read"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

/** `staff`: sees the deliveries (`org:read`), may not act on the account (`org:manage`). */
const READ_ONLY_ME: Me = { ...ME, permissions: ["org:read", "leads:read"], role: "staff" };

function delivery(over: Partial<IngestActivityItem> = {}): IngestActivityItem {
  return {
    source: "website_form",
    event: "lead.created",
    outcome: "accepted",
    deduplicated: 0,
    error: null,
    first_at: "2026-08-12T09:00:00Z",
    last_at: "2026-08-13T04:00:00Z",
    // The three the re-drive added. `event_key` is the sender's own reference (a
    // `leadgen_id` for Meta), `lead_source_id` is which source it arrived at, and
    // `recoverable` is the server's answer to "would the re-drive act on this row" —
    // all three asserted by "the leads we could not read" below.
    event_key: "lead.created:website_form",
    lead_source_id: FORM_SOURCE_ID,
    recoverable: false,
    ...over,
  };
}

function setup(over: Partial<MetaSetup> = {}): MetaSetup {
  return {
    callback_path: `/hooks/v1/ingest/meta/${SOURCE_ID}`,
    verify_token: TOKEN,
    subscribe_field: "leadgen",
    signature_header: "X-Hub-Signature-256",
    lead_retrieval_available: false,
    lead_retrieval_reason: "meta_access_token_missing",
    ...over,
  };
}

/** The "Retries absorbed" cell of the row a source occupies, by column position.
 *  Source · Reference · Outcome · Retries absorbed · Last seen — the Reference column
 *  (the sender's own id for the delivery) is what shifted this from 2. */
const RETRIES_COLUMN = 3;

function retriesCell(source: string): string {
  const row = screen.getByText(source).closest("tr");
  expect(row, `no row for ${source}`).not.toBeNull();
  return row!.querySelectorAll("td")[RETRIES_COLUMN]?.textContent ?? "";
}

function leadSource(over: Partial<LeadSource> = {}): LeadSource {
  return {
    id: SOURCE_ID,
    source: "meta_lead_ads",
    agent_id: null,
    active: true,
    mapping: { phone: "phone_number" },
    secret_fingerprint: "a1b2c3d4",
    previous_secret_expires_at: null,
    created_at: "2026-08-01T09:00:00Z",
    updated_at: "2026-08-01T09:00:00Z",
    ...over,
  };
}

function sourceList(...items: LeadSource[]) {
  return { items, secret_header: "X-Ingest-Secret" };
}

async function renderPage(routes: Record<string, unknown> = {}, me: Me = ME) {
  const rendered = await renderClientPage(<LeadSourcesPage />, {
    "/v1/me": me,
    [ACTIVITY_PATH]: { items: [] },
    [SOURCES_PATH]: sourceList(
      leadSource(),
      leadSource({ id: FORM_SOURCE_ID, source: "website_form" }),
    ),
    [AGENTS_PATH]: [],
    ...routes,
  });
  await screen.findByText("Try a sample lead");
  return rendered;
}

describe("the delivery log", () => {
  it("refuses rather than reporting that nothing has arrived", async () => {
    // THE assertion on this screen. "No deliveries yet" is a statement about the
    // client's integration; a failed read is a statement about us, and the two must
    // never render as the same sentence.
    const { container } = await renderPage({
      [ACTIVITY_PATH]: problem(503, {
        title: "Service unavailable",
        detail: "We could not read the inbox.",
      }),
    });

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(container.textContent).not.toContain("No deliveries yet");
    // …and no count in the card header either: it is only stated when rows were sent.
    expect(container.textContent).not.toContain("with activity");
  });

  it("says nothing has arrived only when the server said so", async () => {
    const { container } = await renderPage({ [ACTIVITY_PATH]: { items: [] } });

    await screen.findByText("No deliveries yet");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(container.textContent).toContain("0 sources with activity");
  });

  it("shows a rejection with its reason, and absorbed retries as a count", async () => {
    const { container } = await renderPage({
      [ACTIVITY_PATH]: {
        items: [
          delivery({ outcome: "rejected", error: "no dialable phone number" }),
          delivery({ source: "meta_lead_ads", deduplicated: 15 }),
        ],
      },
    });

    await screen.findByText("no dialable phone number");
    expect(container.textContent).toContain("rejected");
    // The dedupe column is the answer to "you got fifteen requests, why one call?".
    expect(retriesCell("meta_lead_ads")).toBe("15");
  });

  it("renders zero absorbed retries as a dash, not as a zero", async () => {
    // "0 retries" reads like a problem someone should look into; a dash reads like
    // nothing needed absorbing, which is what it means.
    await renderPage({ [ACTIVITY_PATH]: { items: [delivery()] } });

    await screen.findByText("website_form");
    // The CELL, not the page: a dash somewhere on screen is not evidence about this
    // column, and `formatIST` prints one too.
    expect(retriesCell("website_form")).toBe("—");
  });

  it("stays visible to a viewer who cannot act, because the read permission differs", async () => {
    // `/v1/lead-sources/activity` is on `org:read` precisely so a read-only support
    // session can still see whether a client's form is reaching us.
    await renderPage({ [ACTIVITY_PATH]: { items: [delivery()] } }, READ_ONLY_ME);
    await screen.findByText("website_form");
  });
});

describe("the leads we could not read", () => {
  /**
   * The half of the re-drive that is not a route. A Meta lead we could not fetch is
   * recorded against its `leadgen_id` and Meta stops resending after ~36 hours; the
   * route that recovers it is worth nothing if nobody can find it, which is why the
   * gaps registry refused to ship the route alone.
   *
   * Three failure modes, in cost order: printing "nothing is waiting" over a read that
   * failed or has not returned (the reason someone gives up on leads that are sitting
   * right there); offering the button for a refusal the route will not act on; and
   * reporting a partial run as a whole one.
   */
  const REDRIVE_PATH = `/v1/lead-sources/${SOURCE_ID}/meta/redrive`;

  function stranded(over: Partial<IngestActivityItem> = {}): IngestActivityItem {
    return delivery({
      source: "meta_lead_ads",
      lead_source_id: SOURCE_ID,
      event_key: "900000000000123",
      outcome: "rejected",
      error: "meta_page_token_not_configured",
      recoverable: true,
      ...over,
    });
  }

  async function pickMetaSource(routes: Record<string, unknown> = {}) {
    const rendered = await renderPage(routes);
    fireEvent.change(screen.getByLabelText("Meta lead source"), {
      target: { value: SOURCE_ID },
    });
    return rendered;
  }

  it("counts what is waiting for THIS source and offers to fetch it", async () => {
    const { calls } = await pickMetaSource({
      [ACTIVITY_PATH]: {
        items: [
          stranded(),
          stranded({ event_key: "900000000000124" }),
          // Another source's stranded lead: recoverable, and not this button's business.
          stranded({
            lead_source_id: FORM_SOURCE_ID,
            event_key: "900000000000125",
          }),
          // THIS source, and NOT recoverable — a verdict about the lead, which the
          // re-drive will not act on. Counting it would promise a recovery that comes
          // back "0 accepted", so it is in the fixture to make the flag load-bearing.
          stranded({
            event_key: "900000000000126",
            error: "meta_lead_had_no_answers",
            recoverable: false,
          }),
          // …and an ordinary accepted delivery for this source, which is not waiting
          // for anything at all.
          stranded({
            event_key: "900000000000127",
            outcome: "accepted",
            error: null,
            recoverable: false,
          }),
        ],
      },
      [`POST ${REDRIVE_PATH}`]: {
        candidates: 2,
        accepted: 2,
        duplicate: 0,
        refused: 0,
        deferred: 0,
      },
    });

    await screen.findByText("2 leads are waiting.");
    fireEvent.click(screen.getByRole("button", { name: "Recover unread leads" }));

    await screen.findByText("2 of 2 recovered.");
    expect(calls.filter((c) => c.path === REDRIVE_PATH && c.method === "POST")).toHaveLength(1);
  });

  it("says nothing is waiting only when the server answered", async () => {
    await pickMetaSource({ [ACTIVITY_PATH]: { items: [delivery()] } });
    await screen.findByText("Nothing is waiting for this source.");
    expect(
      (
        screen.getByRole("button", {
          name: "Recover unread leads",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  });

  it("refuses rather than reporting that nothing is waiting, when the read failed", async () => {
    // The same rule the delivery log holds to, and it costs more here: told nothing is
    // waiting, a client stops looking for leads that are sitting in the inbox.
    const { container } = await pickMetaSource({
      [ACTIVITY_PATH]: problem(503, { title: "Service unavailable" }),
    });

    // `findAllByRole`: the delivery log below refuses on the same failed read, so there
    // are two refusals on screen and exactly one of them is this block's.
    expect((await screen.findAllByRole("alert")).length).toBeGreaterThan(0);
    expect(container.textContent).not.toContain("Nothing is waiting for this source.");
    expect(screen.queryByRole("button", { name: "Recover unread leads" })).toBeNull();
  });

  it("shows a skeleton rather than a count while the read is still in flight", async () => {
    const { container } = await pickMetaSource({
      [ACTIVITY_PATH]: stillLoading(),
    });

    await screen.findByText("Leads we recorded but could not read");
    expect(container.textContent).not.toContain("Nothing is waiting for this source.");
    expect(container.textContent).not.toContain("leads are waiting");
    expect(screen.queryByRole("button", { name: "Recover unread leads" })).toBeNull();
  });

  it("names every bucket, so a partial run does not read as a whole one", async () => {
    await pickMetaSource({
      [ACTIVITY_PATH]: {
        items: [stranded(), stranded({ event_key: "900000000000126" })],
      },
      [`POST ${REDRIVE_PATH}`]: {
        candidates: 2,
        accepted: 1,
        duplicate: 0,
        refused: 0,
        deferred: 1,
      },
    });

    fireEvent.click(screen.getByRole("button", { name: "Recover unread leads" }));

    await screen.findByText("1 of 2 recovered.");
    // The deferred one is the bucket with an action attached: press again shortly.
    expect((await screen.findByText(/could not be fetched just now/)).textContent).toContain(
      "try again shortly",
    );
  });

  it("marks the recoverable row in the delivery log and leaves the others alone", async () => {
    const { container } = await pickMetaSource({
      [ACTIVITY_PATH]: {
        items: [
          stranded(),
          // A verdict about the lead, not about our credentials: never offered.
          stranded({
            event_key: "900000000000127",
            error: "meta_lead_had_no_answers",
            recoverable: false,
          }),
        ],
      },
    });

    // The Meta lead id is rendered, which is what a client quotes to Meta support and
    // the only durable handle on a lead we never read.
    await screen.findByText("900000000000123");
    expect(container.textContent).toContain("900000000000127");
    expect(screen.getAllByText(/Recoverable — use/)).toHaveLength(1);
  });

  it("is disabled for a viewer who lacks the permission the route requires", async () => {
    await renderPage({ [ACTIVITY_PATH]: { items: [stranded()] } }, READ_ONLY_ME);
    fireEvent.change(screen.getByLabelText("Meta lead source"), {
      target: { value: SOURCE_ID },
    });

    await screen.findByText("1 lead is waiting.");
    expect(
      (
        screen.getByRole("button", {
          name: "Recover unread leads",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  });

  it("clears the result when the picker moves to a different source", async () => {
    // "2 of 2 recovered" left standing under a different Page is not a stale number, it
    // is a statement about the wrong Page's leads — the same reason the setup card
    // resets its verify token on this change.
    const { container } = await pickMetaSource({
      [ACTIVITY_PATH]: { items: [stranded()] },
      [SOURCES_PATH]: sourceList(
        leadSource(),
        leadSource({ id: SECOND_META_SOURCE_ID, source: "meta_lead_ads" }),
      ),
      [`POST ${REDRIVE_PATH}`]: {
        candidates: 1,
        accepted: 1,
        duplicate: 0,
        refused: 0,
        deferred: 0,
      },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Recover unread leads" }));
    await screen.findByText("1 of 1 recovered.");

    // To a DIFFERENT Meta source, not to the empty option: clearing the picker hides
    // the whole block, so an empty value would pass whether or not the result is reset.
    fireEvent.change(screen.getByLabelText("Meta lead source"), {
      target: { value: SECOND_META_SOURCE_ID },
    });

    await screen.findByText("Nothing is waiting for this source.");
    expect(container.textContent).not.toContain("recovered.");
  });

  it("renders a refusal, not a result, when the re-drive itself fails", async () => {
    const { container } = await pickMetaSource({
      [ACTIVITY_PATH]: { items: [stranded()] },
      [`POST ${REDRIVE_PATH}`]: problem(404, {
        title: "Lead source not found",
      }),
    });

    fireEvent.click(await screen.findByRole("button", { name: "Recover unread leads" }));

    await screen.findByRole("alert");
    expect(container.textContent).not.toContain("recovered.");
  });
});

describe("what the screen claims about a connection", () => {
  async function showSetup(over: Partial<MetaSetup> = {}) {
    const rendered = await renderPage({ [META_PATH]: setup(over) });
    fireEvent.change(screen.getByLabelText("Meta lead source"), {
      target: { value: SOURCE_ID },
    });
    fireEvent.click(screen.getByRole("button", { name: "Show setup details" }));
    return rendered;
  }

  it("says the setup details are not evidence that anything is connected", async () => {
    const { container } = await showSetup();

    await screen.findByText(/Showing these details does not connect anything/);
    expect(container.textContent).toContain("Recent deliveries");
  });

  it("states the retrieval gap BEFORE the credentials, and names the server's reason", async () => {
    // `lead_retrieval_available: false` means a verified delivery is recorded and then
    // refused: we cannot read what the person typed. Someone about to point ad spend at
    // this has to read it first, not discover it from a column of rejections.
    const { container } = await showSetup();

    await screen.findByText(/lead answers are not collected yet/);
    expect(container.textContent).toContain("meta_access_token_missing");
    expect(container.textContent).not.toContain("Lead answers will be collected.");
  });

  it("does not print the retrieval warning when the deployment can retrieve", async () => {
    const { container } = await showSetup({
      lead_retrieval_available: true,
      lead_retrieval_reason: null,
    });

    await screen.findByText("Lead answers will be collected.");
    expect(container.textContent).not.toContain("lead answers are not collected yet");
    // Still not a claim that anything is wired up — that remains the inbox's job.
    expect(container.textContent).toContain("Showing these details does not connect anything");
  });

  it("keeps the verify token hidden until asked, and out of every URL", async () => {
    const { container, calls } = await showSetup();

    await screen.findByText("Verify token");
    // Masked on arrival: a credential on screen by default is a credential in every
    // screen-share and every screenshot attached to a support ticket.
    expect(container.textContent).not.toContain(TOKEN);

    fireEvent.click(screen.getByRole("button", { name: "Reveal" }));
    expect(container.textContent).toContain(TOKEN);

    // The callback URL is displayable precisely because it carries no secret — the token
    // goes in Meta's own field. If it ever ends up in the URL it is published in the
    // access log of every hop between Meta and us.
    expect(screen.getByText(/\/hooks\/v1\/ingest\/meta\//).textContent).not.toContain(TOKEN);
    for (const call of calls) {
      expect(call.url, `${call.method} ${call.path} carries the verify token`).not.toContain(
        TOKEN,
      );
    }
  });
});

describe("the dry run", () => {
  async function runTest(answer: unknown) {
    const rendered = await renderPage({ [TEST_PATH]: answer });
    fireEvent.change(screen.getByLabelText("Lead source to test"), {
      target: { value: SOURCE_ID },
    });
    fireEvent.click(screen.getByRole("button", { name: /Run test/ }));
    return rendered;
  }

  it("sends the sample in the body — the path carries the source id and nothing else", async () => {
    // The sample holds a phone number, and sooner or later it holds a real one: a client
    // debugging a live form pastes the payload that actually arrived. A number in a query
    // string lands in access logs, proxies and browser history (hard rule 6).
    const { calls } = await runTest({
      would_call: true,
      steps: [{ step: "phone_number", ok: true, detail: "Found a dialable Indian number." }],
    });

    await screen.findByText("A real submission like this WOULD get a call.");
    const posted = calls.filter((c) => c.path === TEST_PATH);
    expect(posted).toHaveLength(1);
    expect(posted[0].method).toBe("POST");
    expect(posted[0].body).toContain("9876543210");
    for (const call of calls) {
      expect(call.url, `${call.method} ${call.path} carries the sample number`).not.toContain(
        "9876543210",
      );
    }
  });

  it("does not say a call would be placed when the gate said it would not", async () => {
    const { container } = await runTest({
      would_call: false,
      steps: [
        {
          step: "compliance_gate",
          ok: false,
          detail: "This number is on the do-not-call list.",
          rule: "dnc",
        },
      ],
    });

    await screen.findByText("A real submission like this would NOT get a call.");
    expect(container.textContent).not.toContain("WOULD get a call");
    // Which rule refused is what tells the client where to look.
    expect(container.textContent).toContain("rule: dnc");
    // …and the verdict is scoped to now: the gate re-reads the list at the real dial.
    expect(container.textContent).toContain("That is the answer right now.");
  });

  it("does not send anything when the sample is not valid JSON", async () => {
    const { calls } = await renderPage();

    fireEvent.change(screen.getByLabelText("Lead source to test"), {
      target: { value: SOURCE_ID },
    });
    fireEvent.change(screen.getByLabelText("Sample lead payload (JSON)"), {
      target: { value: "{ phone_number: " },
    });
    fireEvent.click(screen.getByRole("button", { name: /Run test/ }));

    await screen.findByText(/doesn't look like valid JSON/);
    expect(calls.filter((c) => c.path === TEST_PATH)).toHaveLength(0);
  });

  it("renders a refusal, not a verdict, when the dry run itself fails", async () => {
    const { container } = await runTest(
      problem(404, { title: "Lead source not found", detail: "No such lead source." }),
    );

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(container.textContent).not.toContain("WOULD get a call");
    expect(container.textContent).not.toContain("would NOT get a call");
  });
});

describe("controls are gated on the permission their route requires", () => {
  it("disables BOTH org:manage buttons for a viewer who lacks it, and says so once", async () => {
    // The dry-run writes nothing and still requires `org:manage` (ingest/routes.py: a
    // dry-run is an action taken on the client's behalf), and the Meta setup requires it
    // because its response carries a credential. One permission, two buttons — and the
    // reason has to cover both rather than naming one of them.
    const { container } = await renderPage({}, READ_ONLY_ME);

    expect(container.textContent).toContain(
      "Only an account owner can test or set up a lead source.",
    );

    fireEvent.change(screen.getByLabelText("Lead source to test"), {
      target: { value: SOURCE_ID },
    });
    fireEvent.change(screen.getByLabelText("Meta lead source"), {
      target: { value: SOURCE_ID },
    });
    expect((screen.getByRole("button", { name: /Run test/ }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect(
      (screen.getByRole("button", { name: "Show setup details" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("enables them for an owner, so the disabled state is the permission and not the form", async () => {
    await renderPage();

    fireEvent.change(screen.getByLabelText("Lead source to test"), {
      target: { value: SOURCE_ID },
    });
    fireEvent.change(screen.getByLabelText("Meta lead source"), {
      target: { value: SOURCE_ID },
    });
    expect((screen.getByRole("button", { name: /Run test/ }) as HTMLButtonElement).disabled).toBe(
      false,
    );
    expect(
      (screen.getByRole("button", { name: "Show setup details" }) as HTMLButtonElement).disabled,
    ).toBe(false);
  });

  it("renders no heading of its own — the shell already prints the page title", async () => {
    const { container } = await renderPage();
    expect(container.querySelector("h1")).toBeNull();
  });
});

/**
 * Provisioning (the card that ended out-of-band SQL). Ranked by what a wrong render
 * costs:
 *
 * 1. **"No lead sources yet" under a failed read.** Worse here than on the delivery log:
 *    a client who believes they have none creates a second source for a form that is
 *    already wired up, ends up with two secrets for one form, and leads start landing on
 *    whichever they pasted last.
 * 2. **A secret shown twice, or not at all.** The create/rotate response is the only
 *    place the plaintext exists outside the database. It has to be on screen once, with
 *    the header and address that make it usable, and it must never come back from the
 *    list.
 * 3. **A rotation with no deadline.** "Rotated" reads as "the old key is dead" to one
 *    client and "nothing changed" to another; only the date produces the right
 *    behaviour, and the row has to keep saying it until the window closes.
 */
describe("provisioning a lead source", () => {
  const CREATED = {
    id: "018f3c00-0000-7000-8000-0000000000aa",
    source: "website_form",
    ingest_path: "/hooks/v1/ingest/018f3c00-0000-7000-8000-0000000000aa",
    secret: "s3cr3t-shown-once-abcdefghijklmnop",
    secret_header: "X-Ingest-Secret",
  };

  it("refuses rather than reporting that the account has no lead sources", async () => {
    const { container } = await renderPage({
      [SOURCES_PATH]: problem(503, {
        title: "Service unavailable",
        detail: "We could not read your lead sources.",
      }),
    });

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(container.textContent).not.toContain("No lead sources yet");
    // …and the pickers must not read as "you have none" either.
    expect(container.textContent).toContain("We could not load your lead sources");
  });

  it("says the account has none only when the server said so", async () => {
    const { container } = await renderPage({ [SOURCES_PATH]: sourceList() });
    await screen.findByText("No lead sources yet");
    expect(container.textContent).not.toContain("We could not load your lead sources");
  });

  it("shows a fingerprint in the list and never a secret", async () => {
    const { container } = await renderPage();
    await screen.findByText("Your lead sources");
    expect(container.textContent).toContain("key ···a1b2c3d4");
    // The list response has no secret field at all; this pins the screen to that.
    expect(container.textContent).not.toContain("Copy this secret now");
  });

  it("disables every provisioning control for a viewer without org:manage", async () => {
    await renderPage({}, READ_ONLY_ME);
    await screen.findByText("Your lead sources");
    expect(
      (screen.getByRole("button", { name: "Add lead source" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    for (const button of screen.getAllByRole("button", { name: "New secret" })) {
      expect((button as HTMLButtonElement).disabled).toBe(true);
    }
    for (const button of screen.getAllByRole("button", { name: "Turn off" })) {
      expect((button as HTMLButtonElement).disabled).toBe(true);
    }
  });

  it("keeps saying the old secret works until the deadline the server gave", async () => {
    // The row, not just the banner: a client who dismissed the banner or came back
    // tomorrow still has to be able to find out whether they are inside the window.
    const { container } = await renderPage({
      [SOURCES_PATH]: sourceList(
        leadSource({ previous_secret_expires_at: "2026-08-14T05:30:00Z" }),
      ),
    });
    await screen.findByText(/Your previous secret still works until/);
    expect(container.textContent).not.toContain("stopped working immediately");
  });

  it("offers the immediate revocation named for what it costs", async () => {
    // A "0 minutes" option reads as tidiest and drops every lead submitted while the
    // client updates their form. The label has to say what it is for.
    await renderPage();
    fireEvent.click(screen.getAllByRole("button", { name: "New secret" })[0]);
    const options = screen.getByLabelText("How long the old secret keeps working");
    expect(options.textContent).toContain("Stop it immediately — my secret leaked");
    expect(options.textContent).toContain("1 hour (recommended)");
  });

  it("asks for the Meta App Secret only for a Meta source, and requires it", async () => {
    await renderPage();
    const kind = screen.getByLabelText("Lead source kind");
    // A website form: we mint, so there is nothing to ask for.
    expect(screen.queryByLabelText("Meta App Secret")).toBeNull();
    expect(
      (screen.getByRole("button", { name: "Add lead source" }) as HTMLButtonElement).disabled,
    ).toBe(false);

    fireEvent.change(kind, { target: { value: "meta_lead_ads" } });
    expect(screen.getByLabelText("Meta App Secret")).toBeTruthy();
    // Meta signs with a secret only the client holds, so the form cannot be submitted
    // without it — the server would answer `app_secret_required`.
    expect(
      (screen.getByRole("button", { name: "Add lead source" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("sends only the field mappings the client filled in", async () => {
    const { calls } = await renderPage({ [SOURCES_PATH]: sourceList(), [CREATE_PATH]: CREATED });
    fireEvent.change(screen.getByLabelText("Your form's phone field name"), {
      target: { value: "phone_number" },
    });
    // A blank field is "we do not map this one", not a mapping to an empty name — the
    // server refuses those with `mapping_blank_field`.
    fireEvent.change(screen.getByLabelText("Your form's name field name"), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add lead source" }));

    await screen.findByText("Copy this secret now — we will not show it again.");
    const posted = calls.filter((c) => c.path === SOURCES_PATH && c.method === "POST");
    expect(posted).toHaveLength(1);
    const body = JSON.parse(posted[0].body ?? "{}");
    expect(body.mapping).toEqual({ phone: "phone_number" });
    expect(body.app_secret).toBeUndefined();
  });

  it("shows the minted secret once, with its header and address", async () => {
    const { container } = await renderPage({
      [SOURCES_PATH]: sourceList(),
      [CREATE_PATH]: CREATED,
    });
    fireEvent.click(screen.getByRole("button", { name: "Add lead source" }));

    await screen.findByText("Copy this secret now — we will not show it again.");
    expect(container.textContent).toContain(CREATED.secret);
    expect(container.textContent).toContain("X-Ingest-Secret");
    expect(container.textContent).toContain(CREATED.ingest_path);

    // Dismissed means gone: nothing on this screen can fetch it again.
    fireEvent.click(screen.getByRole("button", { name: "I've saved it" }));
    expect(container.textContent).not.toContain(CREATED.secret);
  });
});
