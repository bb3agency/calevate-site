import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LeadSourcesPage from "@/app/c/[slug]/lead-sources/page";
import type { Me } from "@/lib/api/client";
import type { IngestActivityItem, MetaSetup } from "@/lib/api/leadSources";

import { problem, renderClientPage } from "./harness";

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
const SOURCE_ID = "018f3c00-0000-7000-8000-000000000001";
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

/** The "Retries absorbed" cell of the row a source occupies, by column position. */
function retriesCell(source: string): string {
  const row = screen.getByText(source).closest("tr");
  expect(row, `no row for ${source}`).not.toBeNull();
  return row!.querySelectorAll("td")[2]?.textContent ?? "";
}

async function renderPage(routes: Record<string, unknown> = {}, me: Me = ME) {
  const rendered = await renderClientPage(<LeadSourcesPage />, {
    "/v1/me": me,
    [ACTIVITY_PATH]: { items: [] },
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

describe("what the screen claims about a connection", () => {
  async function showSetup(over: Partial<MetaSetup> = {}) {
    const rendered = await renderPage({ [META_PATH]: setup(over) });
    fireEvent.change(screen.getByLabelText("Meta lead source ID"), {
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
    fireEvent.change(screen.getByLabelText("Lead source ID to test"), {
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

    fireEvent.change(screen.getByLabelText("Lead source ID to test"), {
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

    fireEvent.change(screen.getByLabelText("Lead source ID to test"), {
      target: { value: SOURCE_ID },
    });
    fireEvent.change(screen.getByLabelText("Meta lead source ID"), {
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

    fireEvent.change(screen.getByLabelText("Lead source ID to test"), {
      target: { value: SOURCE_ID },
    });
    fireEvent.change(screen.getByLabelText("Meta lead source ID"), {
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
