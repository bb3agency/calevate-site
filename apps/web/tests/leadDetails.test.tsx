import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { LeadDetailsScreen } from "@/app/c/[slug]/settings/lead-details/LeadDetailsScreen";
import { DRAFT_REQUEST } from "@/components/leadFields/LeadDetailsView";
import type { CallOutcomes } from "@/lib/api/callOutcomes";
import type { LeadFields } from "@/lib/api/leadFields";
import { BUSINESS_TYPES, businessTypeLabel } from "@/lib/businessTypes";
import { useAssistantRequests, type AssistantRequest } from "@/lib/copilot/launcher";

import { renderClientPage } from "./harness";

/**
 * Lead details (founder decision 15): the fixed core shown as always-on, a business's own
 * details editable per agent, and the one AI draft a custom business gets — offered when
 * there is nothing, shown as drafting while it runs, and described as drafted once after.
 */

const OWNER = {
  realm: "client",
  user_id: "u1",
  tenant_id: "t1",
  org_slug: "acme",
  role: "owner",
  permissions: ["org:read", "org:manage", "agents:read"],
  impersonating: false,
  withheld_acts: [],
};

const field = (key: string, label: string, required = false) => ({
  key,
  label,
  type: "text" as const,
  reason: "",
  required,
  enum_values: null,
});

function leadFields(over: Partial<LeadFields> = {}): LeadFields {
  return {
    business_type: "custom",
    business_type_label: "Something else",
    core_fields: [field("name", "Name"), field("need", "What they want")],
    need_key: "need",
    standard_fields: [],
    has_standard_set: false,
    draft: null,
    can_draft: true,
    agents: [
      {
        id: "a1",
        name: "Front desk",
        direction: "inbound",
        status: "live",
        version: 1,
        business_fields: [],
      },
    ],
    ...over,
  };
}
/** Each agent's own call outcomes (D-836): none by default, so the lead-field tests stay about fields. */
function callOutcomes(over: Partial<CallOutcomes> = {}): CallOutcomes {
  return { max_outcomes: 8, agents: [], ...over };
}

const STARTING_AGENT: CallOutcomes["agents"][number] = {
  id: "a1",
  name: "Shop counter",
  direction: "inbound",
  status: "live",
  starting: true,
  draft: "queued",
  outcomes: [
    { key: "wants_to_buy", label: "Wants to buy or book", meaning: "The caller wants to buy.", lead_status: "interested" },
    { key: "not_interested", label: "Not interested", meaning: "", lead_status: "contacted" },
  ],
};

const DRAFTED: NonNullable<LeadFields["draft"]> = {
  status: "done",
  requested_at: "2026-10-10T10:00:00Z",
  completed_at: "2026-10-10T10:00:30Z",
  fields: [field("produce", "Produce", true), field("kilos", "Kilos")],
  error_code: null,
  reviewed: false,
};


describe("the business types", () => {
  it("are one list that does not start with a clinic", () => {
    expect(BUSINESS_TYPES[0].value).not.toBe("clinic");
    expect(BUSINESS_TYPES.map((t) => t.value)).toEqual([
      "retail",
      "local_services",
      "automobile",
      "clinic",
      "real_estate",
      "insurance",
      "education",
      "custom",
    ]);
    expect(businessTypeLabel("retail")).toBe("Shop, food or produce");
    expect(businessTypeLabel(null)).toBe("Something else");
    expect(businessTypeLabel("constructor")).toBe("Something else");
  });
});

describe("the lead details screen", () => {
  it("shows the core as always captured and offers the one draft through Pip (D-821)", async () => {
    const asked: AssistantRequest[] = [];
    function Listener() {
      useAssistantRequests((request) => asked.push(request));
      return null;
    }
    render(<Listener />);
    const { calls } = await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/call-outcomes": callOutcomes(),
      "/v1/lead-fields": leadFields(),
    });
    await screen.findByRole("heading", { name: "Always captured" });
    expect(screen.getByText("What they want")).toBeTruthy();
    expect(screen.getByText("Nothing here yet.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^Let Pip draft them: / }));
    expect(asked.map((a) => a.prompt)).toEqual([DRAFT_REQUEST]);
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("asks the owner to keep the drafted details before any agent has them", async () => {
    const { calls } = await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/call-outcomes": callOutcomes(),
      "/v1/lead-fields": leadFields({ can_draft: false, draft: DRAFTED }),
      "POST /v1/lead-fields/draft/review": { fields_kept: 1, agents_changed: 1 },
    });
    await screen.findByRole("heading", { name: "2 drafted details" });
    expect(screen.getAllByText(/Keep what fits\./).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("checkbox", { name: /Kilos/ }));
    fireEvent.click(screen.getByRole("button", { name: "Add 1 of 2 to my agents" }));
    await waitFor(() => {
      const review = calls.find((c) => c.path === "/v1/lead-fields/draft/review");
      expect(review && JSON.parse(review.body ?? "{}")).toEqual({ keep: ["produce"] });
    });
  });

  it("says a reviewed draft was made once and is the owner's to edit", async () => {
    await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/call-outcomes": callOutcomes(),
      "/v1/lead-fields": leadFields({
        can_draft: false,
        draft: { ...DRAFTED, reviewed: true, fields: [field("produce", "Produce", true)] },
        agents: [
          {
            id: "a1",
            name: "Front desk",
            direction: "inbound",
            status: "live",
            version: 2,
            business_fields: [field("produce", "Produce", true)],
          },
        ],
      }),
    });
    await screen.findByText(/Drafted from your business details/);
    // The reason is behind its "Why?", one tap away.
    fireEvent.click(screen.getAllByRole("button", { name: /Why\?/ })[0]!);
    expect(screen.getByText(/won't be drafted again/)).toBeTruthy();
    expect(screen.getByText("Produce")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Let Pip draft them/ })).toBeNull();
    expect(screen.queryByRole("heading", { name: /drafted details/ })).toBeNull();
  });

  it("saves an added detail for the chosen agent through the per-agent write", async () => {
    const { calls } = await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/call-outcomes": callOutcomes(),
      "/v1/lead-fields": leadFields({
        business_type: "retail",
        business_type_label: "Shop, food or produce",
        has_standard_set: true,
        can_draft: false,
        standard_fields: [field("product", "Product", true)],
        agents: [
          {
            id: "a1",
            name: "Shop counter",
            direction: "inbound",
            status: "live",
            version: 1,
            business_fields: [field("product", "Product", true)],
          },
        ],
      }),
      "PUT /v1/agents/a1/extraction-schema": {
        fields: [field("product", "Product", true), field("pack_size", "Pack size")],
        core_fields: [],
        version: 2,
        changed: true,
      },
    });
    await screen.findByRole("heading", { name: "Details about your business" });
    fireEvent.click(screen.getByRole("button", { name: "Add a detail" }));
    fireEvent.change(screen.getAllByRole("textbox", { name: "Name" }).at(-1) as HTMLElement, {
      target: { value: "Pack size" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save details" }));
    await waitFor(() => {
      const put = calls.find((c) => c.method === "PUT");
      expect(put?.path).toBe("/v1/agents/a1/extraction-schema");
      const sent = JSON.parse(put?.body ?? "{}") as {
        fields: { key: string }[];
        expected_version: number;
      };
      expect(sent.fields.map((f) => f.key)).toEqual(["product", "pack_size"]);
      // The version the editor loaded: a list changed since (a kept suggestion, Pip) is
      // refused by the server instead of being overwritten by this whole-list save.
      expect(sent.expected_version).toBe(1);
    });
  });

  /** A list written elsewhere (a kept suggestion, Pip) while this screen is open. */
  function shopFields(version: number, fields: ReturnType<typeof field>[]) {
    return leadFields({
      business_type: "retail",
      business_type_label: "Shop, food or produce",
      has_standard_set: true,
      can_draft: false,
      standard_fields: [field("product", "Product", true)],
      agents: [
        { id: "a1", name: "Shop counter", direction: "inbound", status: "live", version, business_fields: fields },
      ],
    });
  }

  it("shows a newer list from elsewhere when nothing has been typed", async () => {
    let current = shopFields(1, [field("product", "Product", true)]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    await renderClientPage(
      <LeadDetailsScreen />,
      { "/v1/me": OWNER, "/v1/call-outcomes": callOutcomes(), "/v1/lead-fields": () => current },
      "acme",
      client,
    );
    await screen.findByRole("heading", { name: "Details about your business" });
    expect(screen.queryByText("Colour")).toBeNull();

    current = shopFields(2, [field("product", "Product", true), field("colour", "Colour")]);
    await act(async () => {
      await client.invalidateQueries();
    });

    await screen.findByText("Colour");
  });

  it("keeps what the owner typed when a newer list arrives, and saves against the old version", async () => {
    let current = shopFields(1, [field("product", "Product", true)]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { calls } = await renderClientPage(
      <LeadDetailsScreen />,
      {
        "/v1/me": OWNER,
        "/v1/call-outcomes": callOutcomes(),
        "/v1/lead-fields": () => current,
        "PUT /v1/agents/a1/extraction-schema": {
          fields: [],
          core_fields: [],
          version: 3,
          changed: true,
        },
      },
      "acme",
      client,
    );
    await screen.findByRole("heading", { name: "Details about your business" });
    fireEvent.click(screen.getByRole("button", { name: "Add a detail" }));
    fireEvent.change(screen.getAllByRole("textbox", { name: "Name" }).at(-1) as HTMLElement, {
      target: { value: "Pack size" },
    });

    current = shopFields(2, [field("product", "Product", true), field("colour", "Colour")]);
    await act(async () => {
      await client.invalidateQueries();
    });

    expect(screen.getByDisplayValue("Pack size")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save details" }));
    await waitFor(() => {
      const put = calls.find((c) => c.method === "PUT");
      expect(JSON.parse(put?.body ?? "{}").expected_version).toBe(1);
    });
  });
});

describe("how calls end (D-836)", () => {
  it("says the general outcomes are in use while the agent's own are written", async () => {
    await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/lead-fields": leadFields(),
      "/v1/call-outcomes": callOutcomes({ agents: [STARTING_AGENT] }),
    });
    await screen.findByRole("heading", { name: "How calls end" });
    expect(screen.getByText(/Writing yours now/)).toBeTruthy();
    expect(screen.getByDisplayValue("Wants to buy or book")).toBeTruthy();
    // How far it moves the lead, in the owner's words, never Won or Lost.
    const moves = screen.getAllByRole("combobox", { name: "Moves the lead to" })[0] as HTMLSelectElement;
    expect([...moves.options].map((o) => o.text)).toEqual(["Contacted", "Interested", "Hot"]);
  });

  it("saves the owner's list with known keys kept and a new one without a key", async () => {
    const { calls } = await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/lead-fields": leadFields(),
      "/v1/call-outcomes": callOutcomes({ agents: [{ ...STARTING_AGENT, starting: false, draft: "done" }] }),
      "PUT /v1/agents/a1/call-outcomes": { ...STARTING_AGENT, starting: false, draft: "done" },
    });
    await screen.findByRole("heading", { name: "How calls end" });
    fireEvent.click(screen.getByRole("button", { name: "Add an outcome" }));
    fireEvent.change(screen.getAllByRole("textbox", { name: "Outcome name" }).at(-1) as HTMLElement, {
      target: { value: "Asked price only" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save outcomes" }));
    await waitFor(() => {
      const put = calls.find((c) => c.path === "/v1/agents/a1/call-outcomes");
      const sent = JSON.parse(put?.body ?? "{}") as { outcomes: { key: string | null; label: string }[] };
      expect(sent.outcomes.map((o) => [o.key, o.label])).toEqual([
        ["wants_to_buy", "Wants to buy or book"],
        ["not_interested", "Not interested"],
        [null, "Asked price only"],
      ]);
    });
  });

  it("refuses two outcomes with one name before asking the server", async () => {
    const { calls } = await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/lead-fields": leadFields(),
      "/v1/call-outcomes": callOutcomes({ agents: [STARTING_AGENT] }),
    });
    await screen.findByRole("heading", { name: "How calls end" });
    fireEvent.change(screen.getAllByRole("textbox", { name: "Outcome name" })[1], {
      target: { value: "wants to buy or book" },
    });
    expect(screen.getByText("Two outcomes have the same name.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Save outcomes" }) as HTMLButtonElement).disabled).toBe(true);
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });
});

describe("write them for me (D-841)", () => {
  it("offers the draft again after it failed, and asks the server for it", async () => {
    const failed = { ...STARTING_AGENT, draft: "failed" as const };
    const { calls } = await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/lead-fields": leadFields(),
      "/v1/call-outcomes": callOutcomes({ agents: [failed] }),
      "POST /v1/agents/a1/call-outcomes/draft": { ...STARTING_AGENT, draft: "queued" },
    });
    await screen.findByRole("heading", { name: "How calls end" });
    expect(screen.getByText(/couldn't be written/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Write them for me" }));
    await waitFor(() => {
      expect(
        calls.some((c) => c.method === "POST" && c.path === "/v1/agents/a1/call-outcomes/draft"),
      ).toBe(true);
    });
  });

  it("does not offer it while a draft is being written or once the outcomes are the owner's", async () => {
    await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/lead-fields": leadFields(),
      "/v1/call-outcomes": callOutcomes({
        agents: [STARTING_AGENT, { ...STARTING_AGENT, id: "a2", name: "Own list", starting: false, draft: "done" }],
      }),
    });
    await screen.findByRole("heading", { name: "How calls end" });
    expect(screen.queryByRole("button", { name: "Write them for me" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Own list" }));
    expect(screen.queryByRole("button", { name: "Write them for me" })).toBeNull();
  });
});

describe("suggested changes to an agent's lead details (D-889)", () => {
  const BHK = {
    key: "bhk_size",
    label: "BHK",
    type: "enum" as const,
    reason: "",
    required: false,
    enum_values: ["1BHK", "2BHK", "3BHK", "4BHK", "5BHK+"],
  };
  const withBhk = () =>
    leadFields({
      can_draft: false,
      agents: [
        { id: "a1", name: "Flats desk", direction: "inbound", status: "live", version: 3, business_fields: [BHK] },
      ],
    });
  const ADD = {
    id: "0123456789abcdef",
    kind: "add_choices" as const,
    field_key: "bhk_size",
    field_label: "BHK",
    values: ["6BHK"],
    field_type: null,
    reason: "Three callers asked for a six bedroom flat.",
    source: "calls" as const,
    callers: 3,
  };
  const NEW = {
    id: "fedcba9876543210",
    kind: "new_field" as const,
    field_key: "facing",
    field_label: "Facing",
    values: ["East", "West"],
    field_type: "enum" as const,
    reason: "Your script asks which way the flat faces.",
    source: "script" as const,
    callers: 0,
  };
  const suggestions = (over: Record<string, unknown> = {}) => ({
    state: "done",
    suggestions: [ADD, NEW],
    checked_at: "2026-10-25T12:00:00Z",
    ...over,
  });

  it("shows each change with why, and accepting one asks the server and re-reads the details", async () => {
    const { calls } = await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/call-outcomes": callOutcomes(),
      "/v1/lead-fields": withBhk(),
      "/v1/agents/a1/lead-suggestions": suggestions(),
      "POST /v1/agents/a1/lead-suggestions/0123456789abcdef/accept": {
        answered: ADD,
        remaining: suggestions({ suggestions: [NEW] }),
      },
    });
    await screen.findByRole("heading", { name: "Suggested changes (2)" });
    expect(screen.getByText("Add to BHK")).toBeTruthy();
    expect(screen.getByText("6BHK")).toBeTruthy();
    expect(screen.getByText(/3 callers asked/)).toBeTruthy();
    expect(screen.getByText("New detail: Facing")).toBeTruthy();
    expect(screen.getByText("East")).toBeTruthy();
    expect(screen.getByText(/^Script/)).toBeTruthy();
    // The reason waits behind "Why?" so the list stays short on a phone.
    expect(screen.queryByText("Three callers asked for a six bedroom flat.")).toBeNull();
    fireEvent.click(screen.getAllByRole("button", { name: "Why?" })[0]);
    expect(screen.getByText("Three callers asked for a six bedroom flat.")).toBeTruthy();

    const before = calls.filter((c) => c.path === "/v1/lead-fields").length;
    fireEvent.click(screen.getAllByRole("button", { name: "Accept" })[0]);
    await waitFor(() => expect(screen.queryByText("Add to BHK")).toBeNull());
    expect(
      calls.some((c) => c.method === "POST" && c.path === "/v1/agents/a1/lead-suggestions/0123456789abcdef/accept"),
    ).toBe(true);
    await waitFor(() => {
      expect(calls.filter((c) => c.path === "/v1/lead-fields").length).toBeGreaterThan(before);
    });
  });

  it("turns one down, and holds Accept while the owner has unsaved edits", async () => {
    const { calls } = await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/call-outcomes": callOutcomes(),
      "/v1/lead-fields": withBhk(),
      "/v1/agents/a1/lead-suggestions": suggestions(),
      "POST /v1/agents/a1/lead-suggestions/fedcba9876543210/dismiss": {
        answered: NEW,
        remaining: suggestions({ suggestions: [ADD] }),
      },
    });
    await screen.findByRole("heading", { name: "Suggested changes (2)" });
    fireEvent.click(screen.getByRole("button", { name: "Not now: New detail: Facing" }));
    await waitFor(() => expect(screen.queryByText("New detail: Facing")).toBeNull());
    expect(
      calls.some((c) => c.method === "POST" && c.path === "/v1/agents/a1/lead-suggestions/fedcba9876543210/dismiss"),
    ).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: /Add a detail/ }));
    expect(screen.getByText("Save or undo the changes below to accept one.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Accept" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("says when it is checking, when the allowance stopped it, and checks again on request", async () => {
    const { calls } = await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/call-outcomes": callOutcomes(),
      "/v1/lead-fields": withBhk(),
      "/v1/agents/a1/lead-suggestions": suggestions({ state: "skipped", suggestions: [] }),
      "POST /v1/agents/a1/lead-suggestions/check": suggestions({ state: "queued", suggestions: [] }),
    });
    await screen.findByText(/this month's AI allowance is used up/);
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    await screen.findByText("Checking the script and recent calls…");
    expect(calls.some((c) => c.method === "POST" && c.path === "/v1/agents/a1/lead-suggestions/check")).toBe(true);
    expect(screen.queryByRole("button", { name: "Check again" })).toBeNull();
  });
});
