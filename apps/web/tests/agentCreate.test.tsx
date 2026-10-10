import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BlankAgentFlow } from "@/app/c/[slug]/agents/new/BuildAgent";
import type { Agent } from "@/lib/api/agents";
import type { Lanes } from "@/lib/api/publishing";

import {
  useCopilotSurfaceHolder,
  type SurfaceHolder,
} from "@/lib/copilot/registry";

import { problem, renderClientPage, stillLoading } from "./harness";

/**
 * Building an agent — the first thing a new client does in this section.
 *
 * What can go wrong here is not layout, it is what the form ASKS and what it PROMISES:
 *
 * 1. **A field that reaches the compliance floor.** `create_agent` writes both notice
 *    sentences from the language templates and cannot be told otherwise, so there is no
 *    disclosure input on this form and there must never be one. The panel says what the
 *    agent will be born announcing, because the alternative is a client discovering it on
 *    a recording.
 * 2. **A bound this build invented.** The call cap's minimum, maximum and default are the
 *    server's (`GET /v1/agents/lanes`); a hardcoded "10 minutes" is a number a client
 *    would be refused on with no way to know why.
 * 3. **"Created" read as "working".** A new agent is a DRAFT: it takes no calls and places
 *    none until it has a script and is switched on. A screen that celebrates and says
 *    nothing else leaves an owner waiting for a phone that will never ring.
 */

const OWNER = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  // `org:manage` is what `POST /v1/agents` requires — the OWNER's own permission, not
  // `agents:write`, which is admin-only and which no client role holds.
  permissions: ["agents:read", "org:read", "org:manage"],
  impersonating: false,
  withheld_acts: [],
  organization: {
    id: "o1",
    name: "Sri Clinic",
    slug: "acme",
    status: "active",
  },
};

/**
 * The operator following "view as client" — WRITABLE since D-587.
 *
 * `/v1/me` sends the EFFECTIVE permission set, and `org:manage` survives it: D-587 lists
 * it in `rbac.VIEW_AS_MUTATIONS` with `None` as its ground, so building an agent for a
 * client on a support call is the job the reversal exists for. No named act covers agent
 * creation, so `withheld_acts` carries the six that ARE withheld and none of them bites
 * here.
 */
const VIEWING_AS_ADMIN = {
  ...OWNER,
  impersonating: true,
  withheld_acts: [
    "billing.ai_assist",
    "compliance.caller_memory_attestation",
    "compliance.erasure_request",
    "kb.self_approve",
    "leads.saved_view",
    "org.membership",
  ],
};

const LANES: Lanes = {
  precedence_rule:
    "Script decides content, rules decide conduct, voice only changes delivery.",
  lanes: [],
  call_cap_default_s: 600,
  call_cap_min_s: 60,
  call_cap_max_s: 3600,
};

function created(over: Partial<Agent> = {}): Agent {
  return {
    id: "agent-9",
    name: "Front desk",
    direction: "inbound",
    status: "draft",
    archived_at: null,
    language_primary: "te-IN",
    disclosure_line:
      "Namaskaram, this is an AI assistant calling for Sri Clinic.",
    ai_disclosure_line:
      "Namaskaram, this is an AI assistant calling for Sri Clinic.",
    // What `POST /v1/agents` answers for a NEW agent since D-669: both sentences on file,
    // both announcements off, so the composed opening is empty and the greeting is the
    // script's.
    ai_disclosure_enabled: false,
    recording_notice_line: "This call is being recorded.",
    caller_memory_notice_line: "I keep a short note of what you ask about.",
    caller_memory_enabled: false,
    recording_notice_enabled: false,
    opening_line: "",
    script_opening_line: "",
    first_words: "",
    truthful_answer_rule:
      "Whatever these settings say, the agent always answers honestly when a caller asks.",
    engine: "pipecat",
    published: false,
    inbound_number_count: 0,
    extraction_fields: [],
    // D-454: inheriting all the way up — what this fixture always meant
    // implicitly, back when an agent had no opinion about its model.
    llm_tier: null,
    llm_tier_effective: "standard",
    llm_tier_label: "Standard",
    llm_tier_source: "platform",
    llm_surcharged: false,
    ...over,
  };
}

// The blank flow: the page now opens on "pick a job" (agentStarter.test.tsx), and starting
// from nothing is one link away from it, unchanged.
const page = <BlankAgentFlow slug="acme" />;

function routes(over: Record<string, unknown> = {}) {
  return { "/v1/me": OWNER, "/v1/agents/lanes": LANES, ...over };
}

/** A control this session may actually press — see `agentDetail.test.tsx::pressable`. */
async function pressable(name: RegExp): Promise<HTMLElement> {
  const button = screen.getByRole("button", { name });
  await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
  return button;
}

/*
 * CHANGED with D-657: building an agent is a StepFlow — "What should it do?", then "What is
 * it called, and what does it speak?", then "Check and build". The assertions are the same
 * contract as the one-page form's (what is posted, what is promised, what is refused); the
 * helpers below walk the steps a person walks.
 */

/** The flow has painted its first step. */
async function opened(): Promise<void> {
  await screen.findByText("What should it do?");
}

/** Press Next (each step is a form, so this is its submit). */
async function next(): Promise<void> {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
  });
}

/** From step 1 to the name step. */
async function toDetails(): Promise<void> {
  await opened();
  await next();
  await screen.findByText("What is it called, and what does it speak?");
}

async function fillName(value: string): Promise<void> {
  // `/^Name/`: the label wraps its hint too, so the accessible name is longer.
  const input = screen.getByLabelText(/^Name/);
  await act(async () => {
    fireEvent.change(input, { target: { value } });
  });
}

/** Name it, move to the review step and press Build. */
async function buildNamed(value: string): Promise<void> {
  await toDetails();
  await fillName(value);
  await next();
  await screen.findByText("Check and build");
  await act(async () => {
    fireEvent.click(await pressable(/Build this agent/));
  });
}

describe("what the form sends", () => {
  it("posts the four fields the server accepts, with a blank cap meaning the standard limit", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({ "POST /v1/agents": created() }),
    );

    await opened();
    await act(async () => {
      fireEvent.click(screen.getByLabelText(/^Make calls/));
    });
    await buildNamed("Front desk");

    const posted = calls.find((call) => call.method === "POST");
    expect(posted?.path).toBe("/v1/agents");
    expect(JSON.parse(posted?.body ?? "{}")).toEqual({
      name: "Front desk",
      direction: "outbound",
      language_primary: "te-IN",
      // NULL, never 0 and never "unlimited": the server resolves null to the platform
      // default, and a 0 would be refused by the column's own CHECK constraint.
      max_call_duration_s: null,
    });
  });

  it("sends a chosen call cap in seconds, because minutes are the client's unit and not the API's", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({ "POST /v1/agents": created() }),
    );

    await toDetails();
    await fillName("Front desk");
    await act(async () => {
      fireEvent.change(screen.getByLabelText(/^Minutes/), { target: { value: "5" } });
    });
    await next();
    await screen.findByText("Check and build");
    await act(async () => {
      fireEvent.click(await pressable(/Build this agent/));
    });

    const posted = calls.find((call) => call.method === "POST");
    expect(JSON.parse(posted?.body ?? "{}").max_call_duration_s).toBe(300);
  });

  it("asks for no disclosure wording, because creation cannot reach the compliance floor", async () => {
    // `create_agent` writes both sentences from the language templates with both toggles
    // ON; a free-text "AI disclosure" field is how an agent ends up announcing "Hi there!".
    const { container } = await renderClientPage(page, routes());

    await toDetails();
    const textInputs = container.querySelectorAll(
      'input[type="text"], input:not([type]), textarea',
    );
    // One: the name. Nothing else in the flow is free text.
    expect(textInputs).toHaveLength(1);
    expect(container.querySelectorAll("textarea")).toHaveLength(0);
  });
});

describe("what the form promises about the agent it is about to build", () => {
  it("states the two announcements and the one guarantee that is not a setting", async () => {
    const { container } = await renderClientPage(page, routes());

    await toDetails();
    await fillName("Front desk");
    await next();
    await screen.findByText("Check and build");
    const floor = screen.getByText("What it will say about itself").closest("section");
    // D-669: a new agent volunteers neither announcement; it opens with its greeting.
    expect(floor?.textContent).toContain("greeting only");
    expect(floor?.textContent).not.toContain("starts every call by saying it is an AI");
    expect(floor?.textContent).toContain("it is an AI assistant");
    expect(floor?.textContent).toContain("the call is being recorded");
    // The half that is not switchable by anyone.
    expect(floor?.textContent).toContain("cannot be switched off");
    // …and the announcements are per-agent toggles, off until the owner switches one on.
    expect(container.textContent).toContain("switch either announcement on later");
  });

  it("says the agent is built switched off, and does not celebrate a phone line that cannot ring", async () => {
    const { container } = await renderClientPage(
      page,
      routes({ "POST /v1/agents": created() }),
    );

    await buildNamed("Front desk");

    await screen.findByText("Front desk is created");
    expect(container.textContent).toContain("not answering or dialling anyone");
    // The primary way on is the BUILDER: an agent with no script cannot be switched on.
    const write = screen.getByRole("link", { name: /Write its script/ });
    expect(write.getAttribute("href")).toBe("/c/acme/agents/agent-9/script");
    const open = screen.getByRole("link", { name: /Open Front desk/ });
    expect(open.getAttribute("href")).toBe("/c/acme/agents/agent-9");
    // The flow is gone: a second press would build a second agent nobody asked for.
    expect(screen.queryByRole("button", { name: /Build this agent/ })).toBeNull();
  });
});

describe("the call cap is the server's, or it is not offered", () => {
  it("prints the bounds and the default the API sent, not ten minutes", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents/lanes": {
          ...LANES,
          call_cap_default_s: 900,
          call_cap_min_s: 120,
          call_cap_max_s: 1800,
        },
      }),
    );

    await toDetails();
    const field = screen.getByLabelText(/^Minutes/);
    expect(field.getAttribute("min")).toBe("2");
    expect(field.getAttribute("max")).toBe("30");
    expect(container.textContent).toContain("blank for the standard 15 minutes");
    expect(container.textContent).not.toContain("10 minutes");
  });

  it("offers no cap field at all while the bounds have not arrived", async () => {
    // A min/max this build invented is a refusal the client cannot explain.
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/agents/lanes": stillLoading() }),
    );

    await toDetails();
    expect(container.querySelector('input[type="number"]')).toBeNull();
    // The rest of the flow still works: one slow read must not take the screen with it.
    expect(screen.getByLabelText(/^Name/)).toBeTruthy();
  });

  it("renders the refusal when the bounds could not be read", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/agents/lanes": problem(503, { title: "Service unavailable" }),
      }),
    );

    await screen.findByRole("alert");
    expect(container.querySelector('input[type="number"]')).toBeNull();
  });
});

describe("failure paths a person can act on", () => {
  it("renders the API's own refusal rather than a spinner that stops", async () => {
    await renderClientPage(
      page,
      routes({
        "POST /v1/agents": problem(409, {
          type: "urn:calevate:tenancy/account_not_open",
          title: "This account is closed",
          detail: "New agents cannot be created on a closed account.",
          remediation: "Talk to us about reopening it.",
        }),
      }),
    );

    await buildNamed("Front desk");

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("New agents cannot be created on a closed account.");
    expect(alert.textContent).toContain("Talk to us about reopening it.");
    // The flow stays on its review step with what was typed: a refusal must not cost the
    // client their input.
    expect(screen.getByText("Check and build")).toBeTruthy();
    expect(screen.getAllByText("Front desk").length).toBeGreaterThan(0);
  });

  it("will not build an agent with no name, and says so in our words", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({ "POST /v1/agents": created() }),
    );

    await toDetails();
    // REDESIGN-2: the name starts as a ready default for the job, so clear it first.
    fireEvent.change(screen.getByRole("textbox", { name: /^Name/ }), { target: { value: "" } });
    // Next is LIVE and the press is refused with a sentence, in our words rather than the
    // browser's UI language.
    await next();

    expect(
      await screen.findByText("Give this agent a name of at least two characters."),
    ).toBeTruthy();
    expect(screen.getByText("What is it called, and what does it speak?")).toBeTruthy();
    expect(calls.some((call) => call.method === "POST")).toBe(false);
  });

  it("lets an operator in view-as build one, because D-587 made `org:manage` writable", async () => {
    // D-587 reversed D-22's refusal of mutating permissions to an impersonating principal:
    // every write carries the operator's id, the tenant and the grant's `jti`, and the
    // shell's banner says so. So the flow is live, with no read-only sentence.
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/me": VIEWING_AS_ADMIN }),
    );

    await toDetails();
    await fillName("Front desk");
    await next();
    await screen.findByText("Check and build");
    const build = screen.getByRole("button", { name: /Build this agent/ });
    await waitFor(() => expect(build.hasAttribute("disabled")).toBe(false));
    expect(container.textContent).not.toContain("You are viewing this account read-only");
    expect(container.textContent).not.toContain("stays with the client");
  });
});

describe("the direction choice", () => {
  it("offers exactly the three the server's union admits, as real radios", async () => {
    const { container } = await renderClientPage(page, routes());

    await opened();
    const radios = container.querySelectorAll('input[type="radio"]');
    expect(radios).toHaveLength(3);
    // Keyboard-operable and self-announcing: real radios, not a `<div role="radio">`.
    expect(screen.getByLabelText(/^Answer calls/)).toBeTruthy();
    expect(screen.getByLabelText(/^Make calls/)).toBeTruthy();
    expect(screen.getByLabelText(/^Both/)).toBeTruthy();
  });

  it("defaults to answering calls, so creating one is never the first step of a dialling motion", async () => {
    // The server defaults to `inbound` for the same reason (D-38), and the two must agree.
    const { calls } = await renderClientPage(
      page,
      routes({ "POST /v1/agents": created() }),
    );

    await buildNamed("Front desk");

    expect(
      JSON.parse(calls.find((c) => c.method === "POST")?.body ?? "{}").direction,
    ).toBe("inbound");
  });
});

describe("what the assistant is told about leaving this screen half-filled", () => {
  /**
   * D-524. The copilot can open another screen, and a half-composed agent is the hazard
   * D-523 named. The server cannot answer "is it dirty", so this screen declares it.
   *
   * FAILS IF: the declaration goes away or stops tracking the form.
   */
  function Probe({
    onHolder,
  }: {
    onHolder: (holder: SurfaceHolder | null) => void;
  }) {
    onHolder(useCopilotSurfaceHolder());
    return null;
  }

  async function surfaceOf(routeOverrides: Record<string, unknown> = {}) {
    let holder: SurfaceHolder | null = null;
    await renderClientPage(
      <>
        {page}
        <Probe onHolder={(next) => (holder = next)} />
      </>,
      routes(routeOverrides),
    );
    await opened();
    return () => (holder as SurfaceHolder | null)?.read();
  }

  it("says there is NOTHING unsaved on a form nobody has typed in", async () => {
    const read = await surfaceOf();
    expect(read()?.unsaved).toBe(false);
  });

  it("SAYS THERE IS, the moment a name is typed", async () => {
    const read = await surfaceOf();
    await next();
    await fillName("Front desk");
    expect(read()?.unsaved).toBe(true);
  });
});
