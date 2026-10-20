import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    expect(screen.getByText(/no agent has them yet/)).toBeTruthy();
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
    await screen.findByText(/Drafted once from your business details/);
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
      const sent = JSON.parse(put?.body ?? "{}") as { fields: { key: string }[] };
      expect(sent.fields.map((f) => f.key)).toEqual(["product", "pack_size"]);
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
    expect(screen.getByText(/being written from your business details/)).toBeTruthy();
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
