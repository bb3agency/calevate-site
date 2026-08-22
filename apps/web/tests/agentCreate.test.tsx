import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import NewAgentPage from "@/app/c/[slug]/agents/new/page";
import type { Agent } from "@/lib/api/agents";
import type { Lanes } from "@/lib/api/publishing";

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
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

/** An owner viewing their own account read-only: the D-22 operator following "view as". */
const VIEWING_AS_ADMIN = { ...OWNER, impersonating: true };

const LANES: Lanes = {
  precedence_rule: "Script decides content, rules decide conduct, voice only changes delivery.",
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
    disclosure_line: "Namaskaram, this is an AI assistant calling for Sri Clinic.",
    ai_disclosure_line: "Namaskaram, this is an AI assistant calling for Sri Clinic.",
    ai_disclosure_enabled: true,
    recording_notice_line: "This call is being recorded.",
    recording_notice_enabled: true,
    opening_line:
      "Namaskaram, this is an AI assistant calling for Sri Clinic. This call is being recorded.",
    truthful_answer_rule:
      "Whatever these settings say, the agent always answers honestly when a caller asks.",
    engine: "bolna",
    published: false,
    inbound_number_count: 0,
    extraction_fields: [],
    // D-454: inheriting all the way up — what this fixture always meant
    // implicitly, back when an agent had no opinion about its model.
    llm_model: null,
    llm_model_effective: "gpt-4o-mini",
    llm_model_source: "platform",
    ...over,
  };
}

const page = <NewAgentPage params={Promise.resolve({ slug: "acme" })} />;

function routes(over: Record<string, unknown> = {}) {
  return { "/v1/me": OWNER, "/v1/agents/lanes": LANES, ...over };
}

/** A control this session may actually press — see `agentDetail.test.tsx::pressable`. */
async function pressable(name: RegExp): Promise<HTMLElement> {
  const button = screen.getByRole("button", { name });
  await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
  return button;
}

async function fillName(value: string): Promise<void> {
  // `/^What do you want to call it/`, not the exact string: the label wraps its hint too,
  // so the accessible name is the whole question plus the sentence under it.
  const input = screen.getByLabelText(/^What do you want to call it/);
  await act(async () => {
    fireEvent.change(input, { target: { value } });
  });
}

describe("what the form sends", () => {
  it("posts the four fields the server accepts, with a blank cap meaning the standard limit", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({ "POST /v1/agents": created() }),
    );

    await screen.findByText("Build an agent");
    await fillName("Front desk");
    await act(async () => {
      fireEvent.click(screen.getByLabelText(/^Make calls/));
    });
    await act(async () => {
      fireEvent.click(await pressable(/Build this agent/));
    });

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

    await screen.findByText("Build an agent");
    await fillName("Front desk");
    await act(async () => {
      fireEvent.change(screen.getByLabelText(/^Longest one call may run/), {
        target: { value: "5" },
      });
    });
    await act(async () => {
      fireEvent.click(await pressable(/Build this agent/));
    });

    const posted = calls.find((call) => call.method === "POST");
    expect(JSON.parse(posted?.body ?? "{}").max_call_duration_s).toBe(300);
  });

  it("asks for no disclosure wording, because creation cannot reach the compliance floor", async () => {
    // `create_agent` writes both sentences from the language templates with both toggles
    // ON, and there is no argument to it that can produce an agent with no AI disclosure on
    // file. A free-text "AI disclosure" field on this form is how an agent ends up
    // announcing "Hi there!" — so the form has exactly the inputs the server takes.
    const { container } = await renderClientPage(page, routes());

    await screen.findByText("Build an agent");
    const textInputs = container.querySelectorAll(
      'input[type="text"], input:not([type]), textarea',
    );
    // One: the name. Nothing else on this form is free text.
    expect(textInputs).toHaveLength(1);
    expect(container.querySelectorAll("textarea")).toHaveLength(0);
  });
});

describe("what the form promises about the agent it is about to build", () => {
  it("states the two announcements and the one guarantee that is not a setting", async () => {
    const { container } = await renderClientPage(page, routes());

    await screen.findByText("Build an agent");
    const floor = screen.getByText("What it will say about itself").parentElement;
    expect(floor?.textContent).toContain("it is an AI assistant");
    expect(floor?.textContent).toContain("the call is being recorded");
    // The half that is not switchable by anyone. Every sentence in this panel is enforced
    // server-side: the notice lines are NOT NULL with non-empty CHECK constraints, and the
    // truthful answer is appended to every prompt and re-verified on every publish.
    expect(floor?.textContent).toContain("cannot be switched off");
    // …and it does not promise the notices are permanent, because they are two per-agent
    // toggles (D-163) and saying otherwise would be a trap of the opposite kind.
    expect(container.textContent).toContain("switch either announcement off later");
  });

  it("says the agent is built switched off, and does not celebrate a phone line that cannot ring", async () => {
    const { container } = await renderClientPage(
      page,
      routes({ "POST /v1/agents": created() }),
    );

    await screen.findByText("Build an agent");
    await fillName("Front desk");
    await act(async () => {
      fireEvent.click(await pressable(/Build this agent/));
    });

    await screen.findByText(/is ready to be written/);
    expect(container.textContent).toContain("It is not on the calling system");
    expect(container.textContent).toContain("Its script gets written");
    // The way on to the agent it just built.
    const open = screen.getByRole("link", { name: /Open Front desk/ });
    expect(open.getAttribute("href")).toBe("/c/acme/agents/agent-9");
    // The form is gone: a second press would build a second agent nobody asked for.
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

    await screen.findByText("Build an agent");
    const field = screen.getByLabelText(/^Longest one call may run/);
    expect(field.getAttribute("min")).toBe("2");
    expect(field.getAttribute("max")).toBe("30");
    expect(container.textContent).toContain("blank for the standard 15 minutes");
    expect(container.textContent).not.toContain("10 minutes");
  });

  it("offers no cap field at all while the bounds have not arrived", async () => {
    // A blank input over a failed read would silently create the agent on the platform
    // default while looking like a choice — and a min/max this build invented is a refusal
    // the client cannot explain.
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/agents/lanes": stillLoading() }),
    );

    await screen.findByText("Build an agent");
    expect(container.querySelector('input[type="number"]')).toBeNull();
    // The rest of the form still works: one slow read must not take the screen with it.
    expect(screen.getByLabelText(/^What do you want to call it/)).toBeTruthy();
  });

  it("renders the refusal when the bounds could not be read", async () => {
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/agents/lanes": problem(503, { title: "Service unavailable" }) }),
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
          remediation: "Talk to your account manager about reopening it.",
        }),
      }),
    );

    await screen.findByText("Build an agent");
    await fillName("Front desk");
    await act(async () => {
      fireEvent.click(await pressable(/Build this agent/));
    });

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("New agents cannot be created on a closed account.");
    expect(alert.textContent).toContain("Talk to your account manager about reopening it.");
    // The form stays, with what was typed in it: a refusal must not cost the client their
    // input.
    expect((screen.getByLabelText(/^What do you want to call it/) as HTMLInputElement).value).toBe(
      "Front desk",
    );
  });

  it("will not build an agent with no name", async () => {
    const { calls } = await renderClientPage(page, routes({ "POST /v1/agents": created() }));

    await screen.findByText("Build an agent");
    const build = screen.getByRole("button", { name: /Build this agent/ });
    expect(build.hasAttribute("disabled")).toBe(true);
    expect(calls.some((call) => call.method === "POST")).toBe(false);
  });

  it("tells an operator viewing read-only why they cannot build one, rather than 403ing", async () => {
    // D-22: every MUTATING permission is refused to an impersonating principal, so the
    // control is dead before the click and says so. `org:manage` is in this fixture's
    // permission list — the refusal comes from `impersonating`, which is the server's own
    // answer, not from a role check this screen invented.
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/me": VIEWING_AS_ADMIN }),
    );

    await screen.findByText("Build an agent");
    await waitFor(() =>
      expect(container.textContent).toContain("You are viewing this account read-only"),
    );
    const build = screen.getByRole("button", { name: /Build this agent/ });
    expect(build.hasAttribute("disabled")).toBe(true);
  });
});

describe("the direction choice", () => {
  it("offers exactly the three the server's union admits, as real radios", async () => {
    const { container } = await renderClientPage(page, routes());

    await screen.findByText("Build an agent");
    const radios = container.querySelectorAll('input[type="radio"]');
    expect(radios).toHaveLength(3);
    // Keyboard-operable and self-announcing: a styled `<div role="radio">` is what this
    // deliberately is not.
    const group = screen.getByText("What should it do?").parentElement;
    expect(within(group as HTMLElement).getByLabelText(/^Answer calls/)).toBeTruthy();
    expect(within(group as HTMLElement).getByLabelText(/^Make calls/)).toBeTruthy();
    expect(within(group as HTMLElement).getByLabelText(/^Both/)).toBeTruthy();
  });

  it("defaults to answering calls, so creating one is never the first step of a dialling motion", async () => {
    // The server defaults to `inbound` for the same reason (D-38: the receptionist is the
    // headline capability), and the two must not disagree — a form that defaulted to
    // outbound would send `outbound` explicitly and quietly override it.
    const { calls } = await renderClientPage(page, routes({ "POST /v1/agents": created() }));

    await screen.findByText("Build an agent");
    await fillName("Front desk");
    await act(async () => {
      fireEvent.click(await pressable(/Build this agent/));
    });

    expect(JSON.parse(calls.find((c) => c.method === "POST")?.body ?? "{}").direction).toBe(
      "inbound",
    );
  });
});
