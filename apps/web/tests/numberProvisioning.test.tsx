import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PhoneNumberPage from "@/app/c/[slug]/phone-number/page";
import type { Me } from "@/lib/api/client";
import { PATHS } from "@/lib/api/numberProvisioning";

import { expectNoA11yViolations } from "./a11y";
import { OWN_NUMBERS_OFF, OWN_NUMBERS_STATUS_PATH } from "./fixtures/sharedReads";
import { problem, renderClientPage, stillLoading, type Routes } from "./harness";
import { NO_FORWARDING_ROUTES, PHONE_NUMBERS_SETTINGS_ROUTES } from "./fixtures/forwarding";

/**
 * GETTING A PHONE NUMBER, AND THE STATE EVERY CLIENT IS ACTUALLY IN.
 *
 * Five properties, each a way this screen could mislead somebody who cannot afford to be
 * misled:
 *
 * - **A deployment that may not sell says so in the SERVER's words.** Buying is refused
 *   today because no written reseller authorisation is recorded
 *   (`apps/api/campaigns/provisioning.py`), and the API answers one sentence whichever
 *   gate is shut so the shape of an error publishes nothing about our paperwork. A dead
 *   button or an empty state would leave a client waiting for something not coming.
 * - **A recurring charge is stated before it is incurred.** The figure goes through
 *   `formatINR`, which formats the server's decimal DIGITS and never parses them (hard
 *   rule 7); `formatterGuard.test.ts` makes the hand-rolled spelling unwriteable and this
 *   checks the rendering that guard cannot see.
 * - **A double submit buys one number.** The key is minted per ATTEMPT, so both presses
 *   carry the same one and the API answers the second with the first purchase.
 * - **Verification gates ACTIVATION, not the sale.** An unverified client may buy and is
 *   told what they are getting; they are not refused something the API allows.
 * - **Choosing to call OUT must not imply a freedom the number does not have.**
 */

const OWNER: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["calls:read", "leads:read", "org:read", "org:manage", "wallet:read"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

/** `self_serve_purchase_refused()` — the sentence every closed gate answers with. */
const REFUSAL =
  "A phone number cannot be bought from this screen. Numbers are arranged with " +
  "us as part of setting your agent up.";

/** The server's remediation: the number is ours, and no provider is named (white label). */
const REMEDIATION =
  "Talk to us and we will arrange the number. Calevate provides it on " +
  "our own telephony account, so there is no operator account for you to open.";

function operatorLed(): unknown {
  return problem(422, {
    type: "https://calevate.tech/problems/number_purchase_is_operator_led",
    detail: REFUSAL,
    remediation: REMEDIATION,
  });
}

function kyc(verified: boolean): unknown {
  return {
    recorded: verified,
    is_verified: verified,
    number_purchase_available: false,
    status: verified ? "accepted" : "not_started",
  };
}

/** `OfferedNumberOut`. The price is deliberately over ₹1,00,000 — see the price test. */
function offer(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    e164: "+918041234500",
    region: "Karnataka",
    locality: "Bengaluru",
    series: "standard",
    inr_per_month: "149900.00",
    ...over,
  };
}

function holder(recorded: boolean): unknown {
  return recorded
    ? {
        recorded: true,
        holder_type: "business",
        holder_name: "Acme Dental",
        holder_email: "owner@example.com",
      }
    : { recorded: false, holder_type: null, holder_name: null, holder_email: null };
}

/** One number the client already holds, which is what the assignment panel hangs off. */
function heldNumbers(): unknown {
  return [
    {
      id: "num-1",
      e164: "+918041234567",
      series: "standard",
      dlt_status: "registered",
      supplied_by_us: false,
      answerable: true,
      agent_id: null,
      direction: "inbound",
    },
  ];
}

/** The screen when this deployment MAY sell. `extra` overrides any entry. */
function routes(extra: Routes = {}): Routes {
  return {
    "/v1/me": OWNER,
    ...NO_FORWARDING_ROUTES,
    ...PHONE_NUMBERS_SETTINGS_ROUTES,
    "/v1/campaigns/numbers": heldNumbers(),
    "/v1/agents": [{ id: "agent-1", name: "Reception", status: "live" }],
    "/v1/compliance/kyc": kyc(true),
    "/v1/billing/wallet": { prepaid: true, balance_inr: "200000.00" },
    [PATHS.available]: [offer()],
    [PATHS.holder]: holder(true),
    [OWN_NUMBERS_STATUS_PATH]: OWN_NUMBERS_OFF,
    ...extra,
  };
}

describe("a deployment that may not supply a number says so", () => {
  const closed = routes({ [PATHS.available]: operatorLed() });

  it("renders the server's own sentence and its remediation", async () => {
    const { container } = await renderClientPage(<PhoneNumberPage />, closed);

    expect(await screen.findByText(REFUSAL)).toBeTruthy();
    expect(screen.getByText(REMEDIATION)).toBeTruthy();
    await expectNoA11yViolations(container, "phone-number: cannot supply");
  });

  it("never tells the client to open an operator account of their own", async () => {
    // Calevate provides the calling number on its own telephony account, naming no provider
    // (founder, 6 Oct 2026). The old sentence offered a connection "you already hold
    // with an Indian operator", which no client is asked to have any more.
    const { container } = await renderClientPage(<PhoneNumberPage />, closed);

    await screen.findByText(REFUSAL);
    expect(container.textContent).not.toMatch(/account holder|withdraw our access|connection you already hold/i);
    expect(screen.getByText(/We set it up with you/i).textContent).not.toMatch(
      /Plivo|Thinnest/i,
    );
  });

  it("offers no way to buy and asks for no registrant details", async () => {
    await renderClientPage(<PhoneNumberPage />, closed);

    await screen.findByText(REFUSAL);
    expect(screen.queryByRole("button", { name: /buy this number/i })).toBeNull();
    // Collecting a permanent registration for a number that cannot be sold would be
    // asking for something we have no use for.
    expect(screen.queryByLabelText(/full name/i)).toBeNull();
  });

  it("still sends an unverified client somewhere they can act", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes({ [PATHS.available]: operatorLed(), "/v1/compliance/kyc": kyc(false) }),
    );

    const link = await screen.findByRole("link", { name: /verify your business/i });
    expect(link.getAttribute("href")).toBe("/c/acme/verify-business");
  });

  it("refuses rather than guessing when it could not ask at all", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes({ [PATHS.available]: problem(503, { detail: "Upstream is down." }) }),
    );

    expect(await screen.findByText("Upstream is down.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /buy this number/i })).toBeNull();
  });

  it("shows a skeleton rather than a refusal while the answer is in flight", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes({ [PATHS.available]: stillLoading() }),
    );

    expect(await screen.findByText(/loading what we can supply/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /buy this number/i })).toBeNull();
  });
});

/** One page (REDESIGN-2): pick the number, and its purchase is confirmed below the list. */
async function chooseNumber(): Promise<void> {
  fireEvent.click(await screen.findByRole("radio", { name: /80412 34500/ }));
}

/** The confirmation under the list, where the dialog used to be. */
function confirmation(): HTMLElement {
  return screen.getByRole("region", { name: /^Buy \+91/ });
}

describe("browsing what is on offer", () => {
  it("prices the month through the shared rupee formatter", async () => {
    const { container } = await renderClientPage(<PhoneNumberPage />, routes());

    // `formatINR("149900.00")`: Indian grouping and two paise, from the digits the server
    // sent. `₹149900.00` is what a template literal would have printed.
    expect(await screen.findByText(/₹1,49,900 a month/)).toBeTruthy();
    expect(container.textContent).toContain("₹2,00,000");
  });

  it("says who the number will be registered to, and that it is permanent", async () => {
    await renderClientPage(<PhoneNumberPage />, routes({ [PATHS.holder]: holder(false) }));

    expect(
      await screen.findByText(/registered to your business, not to us/i),
    ).toBeTruthy();
    expect(await screen.findByText(/Set once for all numbers\. Check before saving\./i)).toBeTruthy();
  });

  it("will not sell until the registrant is on file", async () => {
    await renderClientPage(<PhoneNumberPage />, routes({ [PATHS.holder]: holder(false) }));

    await chooseNumber();
    const buy = await screen.findByRole("button", { name: /buy this number/i });
    expect(buy.hasAttribute("disabled")).toBe(true);
    // The reason arrives with the registrant read, a round trip after the offers.
    await waitFor(() => expect(buy.getAttribute("title")).toMatch(/registered to first/i));
  });

  it("records the registrant once, with the type it was told", async () => {
    const { calls } = await renderClientPage(
      <PhoneNumberPage />,
      routes({
        [PATHS.holder]: holder(false),
        [`POST ${PATHS.holder}`]: holder(true),
      }),
    );

    fireEvent.click(await screen.findByLabelText(/an individual/i));
    fireEvent.change(screen.getByLabelText(/full name/i), {
      target: { value: "Acme Dental" },
    });
    fireEvent.change(screen.getByLabelText(/email for the paperwork/i), {
      target: { value: "owner@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save these details/i }));

    await waitFor(() => {
      const post = calls.find((call) => call.method === "POST" && call.path === PATHS.holder);
      expect(post).toBeTruthy();
      expect(JSON.parse(post!.body ?? "{}")).toEqual({
        holder_type: "individual",
        holder_name: "Acme Dental",
        holder_email: "owner@example.com",
      });
    });
    expect(await screen.findByText(/Used for every number\. Cannot be changed\./i)).toBeTruthy();
  });

  it("sells to an unverified client and says what they are getting", async () => {
    await renderClientPage(<PhoneNumberPage />, routes({ "/v1/compliance/kyc": kyc(false) }));

    expect(
      await screen.findByText(/A number works once you are verified/i),
    ).toBeTruthy();
    await chooseNumber();
    const buy = screen.getByRole("button", { name: /buy this number/i });
    await waitFor(() => expect(buy.hasAttribute("disabled")).toBe(false));
  });
});

describe("buying", () => {
  const purchased = {
    id: "num-2",
    e164: "+918041234500",
    series: "standard",
    direction: "inbound",
    inr_per_month: "149900.00",
    activated: false,
  };

  async function openConfirmation(extra: Routes = {}) {
    const render = await renderClientPage(<PhoneNumberPage />, routes(extra));
    await screen.findByText(/₹1,49,900 a month/);
    await chooseNumber();
    // Enabled once the registrant read lands, a round trip after the offers.
    const buy = screen.getByRole("button", { name: /buy this number/i });
    await waitFor(() => expect(buy.hasAttribute("disabled")).toBe(false));
    return render;
  }

  function confirmButton(): HTMLElement {
    return within(confirmation()).getByRole("button", { name: /buy this number/i });
  }

  it("states the recurring charge and the balance before it is incurred", async () => {
    await openConfirmation();

    const dialog = confirmation();
    expect(dialog.textContent).toContain("₹1,49,900 a month while you keep it");
    expect(dialog.textContent).toContain("Credit now: ₹2,00,000");
    expect(dialog.textContent).toMatch(/Registered to Acme Dental/);
  });

  it("sends the number and what it is for", async () => {
    const { calls } = await openConfirmation({ [`POST ${PATHS.purchase}`]: purchased });

    const dialog = confirmation();
    fireEvent.click(within(dialog).getByLabelText(/^both/i));
    fireEvent.click(confirmButton());

    await waitFor(() => {
      const post = calls.find(
        (call) => call.method === "POST" && call.path === PATHS.purchase,
      );
      expect(post).toBeTruthy();
      expect(JSON.parse(post!.body ?? "{}")).toEqual({
        e164: "+918041234500",
        country: "IN",
        direction: "both",
      });
    });
  });

  it("carries one idempotency key across a double submit", async () => {
    // NEVER ANSWERS, which is the only way to reach the double-submit window: a route
    // that settles closes the dialog before a second press can land.
    const { calls } = await openConfirmation({
      [`POST ${PATHS.purchase}`]: stillLoading(),
    });

    const confirm = confirmButton();
    fireEvent.click(confirm);
    fireEvent.click(confirm);

    await waitFor(() => {
      const posts = calls.filter(
        (call) => call.method === "POST" && call.path === PATHS.purchase,
      );
      expect(posts.length).toBeGreaterThan(0);
      const keys = new Set(posts.map((post) => post.headers["Idempotency-Key"]));
      expect(keys.size).toBe(1);
      expect([...keys][0]).toBeTruthy();
    });
  });

  it("turns not enough credit into a top-up rather than a fault", async () => {
    await openConfirmation({
      [`POST ${PATHS.purchase}`]: problem(402, {
        type: "https://calevate.tech/problems/number_insufficient_credit",
        detail: "Your calling credit does not cover the first month.",
      }),
    });

    fireEvent.click(confirmButton());

    const dialog = confirmation();
    await waitFor(() =>
      expect(dialog.textContent).toContain(
        "Your calling credit does not cover the first month.",
      ),
    );
    expect(
      within(dialog).getByRole("link", { name: /top up credit/i }).getAttribute("href"),
    ).toBe("/c/acme/billing?tab=credits");
  });

  it("reports a bought number that cannot ring yet, with the way to fix it", async () => {
    await openConfirmation({
      "/v1/compliance/kyc": kyc(false),
      [`POST ${PATHS.purchase}`]: purchased,
    });

    fireEvent.click(confirmButton());

    expect(await screen.findByText("+91 80412 34500 is yours")).toBeTruthy();
    expect(
      screen.getByText(/a month. Works once you are verified/i),
    ).toBeTruthy();
    expect(
      screen.getAllByRole("link", { name: /verify your business/i })[0].getAttribute("href"),
    ).toBe("/c/acme/verify-business");
  });
});

describe("each number has one agent, and does what that agent does", () => {
  const AGENTS = [
    { id: "agent-1", name: "Anjali", status: "live", direction: "inbound" },
    { id: "agent-out", name: "Varsha", status: "live", direction: "outbound" },
  ];
  const number = (over: Record<string, unknown> = {}) => ({
    ...(heldNumbers() as Record<string, unknown>[])[0],
    supplied_by_us: true,
    ...over,
  });
  const assigned = (agentId: string | null) => ({
    number_id: "num-1",
    agent_id: agentId,
    bound: agentId ? 1 : 0,
    released: 0,
    failed: 0,
    unsupported: 0,
  });

  it("offers every agent, each with what it will do, and asks nothing else", async () => {
    await renderClientPage(<PhoneNumberPage />, routes({ "/v1/agents": AGENTS }));

    const select = (await screen.findByLabelText(/^agent$/i)) as HTMLSelectElement;
    expect(Array.from(select.options).map((option) => option.textContent)).toEqual([
      "No agent",
      "Anjali · answers calls",
      "Varsha · makes calls",
    ]);
    expect(screen.queryByRole("radiogroup", { name: /what it does/i })).toBeNull();
  });

  it("puts an agent that only makes calls on a number", async () => {
    const { calls } = await renderClientPage(
      <PhoneNumberPage />,
      routes({ "/v1/agents": AGENTS, [`POST ${PATHS.assign("num-1")}`]: assigned("agent-out") }),
    );

    fireEvent.change(await screen.findByLabelText(/^agent$/i), { target: { value: "agent-out" } });
    const save = screen.getByRole("button", { name: /^save$/i });
    await waitFor(() => expect(save.hasAttribute("disabled")).toBe(false));
    fireEvent.click(save);

    await waitFor(() => {
      const post = calls.find((call) => call.path === PATHS.assign("num-1"));
      expect(JSON.parse(post?.body ?? "{}")).toEqual({ agent_id: "agent-out", direction: null });
    });
  });

  it("opens on the number's agent and says in plain words what happens", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes({ "/v1/agents": AGENTS, "/v1/campaigns/numbers": [number({ agent_id: "agent-out" })] }),
    );

    const select = (await screen.findByLabelText(/^agent$/i)) as HTMLSelectElement;
    expect(select.value).toBe("agent-out");
    expect(await screen.findByText("Varsha calls out from this number.")).toBeTruthy();
    expect(screen.getByText("Ready")).toBeTruthy();
    // Nothing changed, so Save has nothing to do.
    expect(screen.getByRole("button", { name: /^save$/i }).hasAttribute("disabled")).toBe(true);
  });

  it("names a switched-off agent and links to switching it on", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes({
        "/v1/agents": [{ ...AGENTS[0], status: "paused" }],
        "/v1/campaigns/numbers": [number({ agent_id: "agent-1" })],
      }),
    );

    expect(await screen.findByText("Anjali is off")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Switch Anjali on" }).getAttribute("href")).toBe(
      "/c/acme/agents/agent-1",
    );
  });

  it("says Setting up while an answering number is still being connected", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes({
        "/v1/agents": AGENTS,
        "/v1/campaigns/numbers": [number({ agent_id: "agent-1", answerable: false })],
      }),
    );

    expect(await screen.findByText("Setting up")).toBeTruthy();
    expect(screen.getByText("Anjali answers calls to this number.")).toBeTruthy();
  });

  it("asks for an agent on a number with none", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes({ "/v1/agents": AGENTS, "/v1/campaigns/numbers": [number({ agent_id: null })] }),
    );

    expect(await screen.findByText("No agent yet")).toBeTruthy();
    expect(screen.getByText("Pick an agent to use this number.")).toBeTruthy();
  });

  it("does not report a binding the carrier refused", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes({
        "/v1/agents": AGENTS,
        [`POST ${PATHS.assign("num-1")}`]: { ...assigned("agent-1"), bound: 0, failed: 1 },
      }),
    );

    fireEvent.change(await screen.findByLabelText(/^agent$/i), { target: { value: "agent-1" } });
    const save = screen.getByRole("button", { name: /^save$/i });
    await waitFor(() => expect(save.hasAttribute("disabled")).toBe(false));
    fireEvent.click(save);

    expect(await screen.findByText(/could not connect it to that agent/i)).toBeTruthy();
  });
});
