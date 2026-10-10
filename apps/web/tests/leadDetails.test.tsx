import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LeadDetailsScreen } from "@/app/c/[slug]/settings/lead-details/LeadDetailsScreen";
import type { LeadFields } from "@/lib/api/leadFields";
import { BUSINESS_TYPES, businessTypeLabel } from "@/lib/businessTypes";

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
  it("shows the core as always captured and offers the one draft", async () => {
    const { calls } = await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/lead-fields": leadFields(),
      "POST /v1/lead-fields/draft": {
        draft: {
          status: "queued",
          requested_at: "2026-10-10T10:00:00Z",
          completed_at: null,
          fields: [],
          error_code: null,
        },
      },
    });
    await screen.findByRole("heading", { name: "Always captured" });
    expect(screen.getByText("What they want")).toBeTruthy();
    expect(screen.getByText("Nothing here yet.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Draft from the business details" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.path === "/v1/lead-fields/draft")).toBe(
        true,
      ),
    );
  });

  it("says a finished draft was made once and is the owner's to edit", async () => {
    await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/lead-fields": leadFields({
        can_draft: false,
        draft: {
          status: "done",
          requested_at: "2026-10-10T10:00:00Z",
          completed_at: "2026-10-10T10:00:30Z",
          fields: [field("produce", "Produce", true)],
          error_code: null,
        },
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
    expect(screen.queryByRole("button", { name: "Draft from the business details" })).toBeNull();
  });

  it("saves an added detail for the chosen agent through the per-agent write", async () => {
    const { calls } = await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
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
