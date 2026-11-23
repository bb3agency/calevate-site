import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LeadDetailsScreen } from "@/app/c/[slug]/settings/lead-details/LeadDetailsScreen";
import { DRAFT_REQUEST } from "@/components/leadFields/LeadDetailsView";
import type { CallOutcomes } from "@/lib/api/callOutcomes";
import type { LeadFields, LeadFieldsJob } from "@/lib/api/leadFields";
import { businessTypeLabel } from "@/lib/businessTypes";
import { useAssistantRequests, type AssistantRequest } from "@/lib/copilot/launcher";

import { BUSINESS_TYPES_FIXTURE } from "./businessTypesFixture";
import { problem, renderClientPage } from "./harness";

/**
 * Lead details (founder decision 15; per campaign and line since D-1029): the fixed core shown
 * as always-on, one What it notes card per campaign and Inbound line, the business's starting
 * set with "Use on campaigns and lines", and the one AI draft — offered when there is nothing,
 * kept onto the ticked jobs, and described as drafted once after.
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

function line(over: Partial<LeadFieldsJob> = {}): LeadFieldsJob {
  return {
    kind: "line",
    id: "l1",
    name: "Front desk",
    status: "live",
    live: true,
    agent_id: "a1",
    agent_name: "Anjali",
    fields: [],
    digest: "d1",
    untouched: true,
    ...over,
  };
}

function leadFields(over: Partial<LeadFields> = {}): LeadFields {
  return {
    business_type: "custom",
    business_type_label: "Something else",
    core_fields: [field("name", "Name"), field("need", "What they want")],
    core_default_labels: { name: "Name", need: "What they want" },
    need_key: "need",
    standard_fields: [],
    has_standard_set: false,
    starting_fields: [],
    draft: null,
    can_draft: true,
    jobs: [],
    ...over,
  };
}

/** The card's own read of a job's list (`GET /v1/inbound-lines/{id}/notes`). */
function notes(fields: ReturnType<typeof field>[] = [], digest = "d1") {
  return { agent_id: "a1", agent_name: "Anjali", fields, core_fields: [], digest, applied_now: true };
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

/** The Lead details card of line l1. */
async function card(): Promise<HTMLElement> {
  await screen.findByRole("button", { name: "Front desk" });
  return document.getElementById("line-notes-l1") as HTMLElement;
}

const SHOP = {
  business_type: "retail",
  business_type_label: "Shop, food or produce",
  has_standard_set: true,
  can_draft: false,
  standard_fields: [field("product", "Product", true)],
  starting_fields: [field("product", "Product", true)],
};


describe("the business types", () => {
  it("are one list that does not start with a clinic", () => {
    expect(BUSINESS_TYPES_FIXTURE.choices[0].value).not.toBe("clinic");
    expect(businessTypeLabel(BUSINESS_TYPES_FIXTURE, "retail")).toBe("Shop, food or produce");
    expect(businessTypeLabel(BUSINESS_TYPES_FIXTURE, null)).toBe("Something else");
    expect(businessTypeLabel(BUSINESS_TYPES_FIXTURE, "constructor")).toBe("Something else");
    // Before the list arrives a label is empty, never another type's.
    expect(businessTypeLabel(undefined, "retail")).toBe("");
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
      "/v1/inbound-lines/l1/notes": notes(),
    });
    await screen.findByRole("heading", { name: "Always captured" });
    expect(screen.getByText("What they want")).toBeTruthy();
    expect(screen.getByText("Nothing here yet.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^Let Pip draft them: / }));
    expect(asked.map((a) => a.prompt)).toEqual([DRAFT_REQUEST]);
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("keeps the drafted details onto the ticked jobs, ticking only lists nobody chose", async () => {
    const own = line({ id: "l2", name: "After hours", digest: "d2", fields: [field("flavour", "Flavour")], untouched: false });
    const { calls } = await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/call-outcomes": callOutcomes(),
      "/v1/lead-fields": leadFields({ can_draft: false, draft: DRAFTED, jobs: [line(), own] }),
      "/v1/inbound-lines/l1/notes": notes(),
      "/v1/inbound-lines/l2/notes": notes([field("flavour", "Flavour")], "d2"),
      "POST /v1/lead-fields/draft/review": { fields_kept: 1, jobs_changed: 1, jobs_waiting: 0 },
    });
    await screen.findByRole("heading", { name: "2 drafted details" });
    const review = screen.getByRole("group", { name: "Add them to" });
    expect((within(review).getByRole("checkbox", { name: /Front desk/ }) as HTMLInputElement).checked).toBe(true);
    expect((within(review).getByRole("checkbox", { name: /After hours/ }) as HTMLInputElement).checked).toBe(false);
    fireEvent.click(screen.getByRole("checkbox", { name: /Kilos/ }));
    fireEvent.click(screen.getByRole("button", { name: "Keep 1 of 2" }));
    await waitFor(() => {
      const sent = calls.find((c) => c.path === "/v1/lead-fields/draft/review");
      expect(sent && JSON.parse(sent.body ?? "{}")).toEqual({
        keep: ["produce"],
        jobs: [{ kind: "line", id: "l1", digest: "d1" }],
      });
    });
  });

  it("says a reviewed draft was made once and is the owner's to edit", async () => {
    await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/call-outcomes": callOutcomes(),
      "/v1/lead-fields": leadFields({
        can_draft: false,
        draft: { ...DRAFTED, reviewed: true, fields: [field("produce", "Produce", true)] },
        starting_fields: [field("produce", "Produce", true)],
        jobs: [line({ fields: [field("produce", "Produce", true)] })],
      }),
      "/v1/inbound-lines/l1/notes": notes([field("produce", "Produce", true)]),
    });
    await screen.findByText(/Drafted from your business details/);
    // The reason is behind its "Why?", one tap away.
    fireEvent.click(screen.getAllByRole("button", { name: /Why\?/ })[0]!);
    expect(screen.getByText(/won't be drafted again/)).toBeTruthy();
    expect(screen.getAllByText("Produce").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /^Let Pip draft them/ })).toBeNull();
    expect(screen.queryByRole("heading", { name: /drafted details/ })).toBeNull();
  });

  it("shows one card per job, named, with its state and a link to its page", async () => {
    await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/call-outcomes": callOutcomes(),
      "/v1/lead-fields": leadFields({ ...SHOP, jobs: [line({ fields: [field("product", "Product", true)] })] }),
      "/v1/inbound-lines/l1/notes": notes([field("product", "Product", true)]),
    });
    expect(await screen.findByRole("button", { name: "Front desk" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open line" }).getAttribute("href")).toContain("/inbound/l1");
    expect(screen.getByText("In Anjali's voice.")).toBeTruthy();
    // No campaign yet: one plain line and the button that makes one.
    expect(screen.getByText("No campaigns yet")).toBeTruthy();
    expect(screen.getByRole("link", { name: "New campaign" }).getAttribute("href")).toContain("/campaigns/new");
  });

  it("saves an added detail through the job's own notes write, with the digest it read", async () => {
    const { calls } = await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/call-outcomes": callOutcomes(),
      "/v1/lead-fields": leadFields({ ...SHOP, jobs: [line({ fields: [field("product", "Product", true)] })] }),
      "/v1/inbound-lines/l1/notes": notes([field("product", "Product", true)]),
      "PUT /v1/inbound-lines/l1/notes": notes([field("product", "Product", true), field("pack_size", "Pack size")], "d2"),
    });
    await within(await card()).findByText("Product");
    fireEvent.click(screen.getByRole("button", { name: "Add a detail" }));
    fireEvent.change(screen.getAllByLabelText(/^Name/).at(-1) as HTMLElement, {
      target: { value: "Pack size" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      const put = calls.find((c) => c.method === "PUT" && c.path === "/v1/inbound-lines/l1/notes");
      const sent = JSON.parse(put?.body ?? "{}") as { fields: { label: string }[]; expected_digest: string };
      expect(sent.fields.map((f) => f.label)).toEqual(["Product", "Pack size"]);
      expect(sent.expected_digest).toBe("d1");
    });
  });

  it("loads the standard set into a card as an unsaved change from Import", async () => {
    await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/call-outcomes": callOutcomes(),
      "/v1/lead-fields": leadFields({ ...SHOP, jobs: [line({ untouched: false, fields: [field("flavour", "Flavour")] })] }),
      "/v1/inbound-lines/l1/notes": notes([field("flavour", "Flavour")]),
      "/v1/inbound-lines": { lines: [] },
    });
    fireEvent.click(await screen.findByRole("button", { name: /^Import/ }));
    fireEvent.click(await screen.findByRole("menuitem", { name: /Standard shop, food or produce details/ }));
    expect(await screen.findByText(/Save to keep it\./)).toBeTruthy();
    expect(within(await card()).getByText("Product")).toBeTruthy();
  });

  it("puts the starting set onto the ticked jobs after a confirm", async () => {
    const { calls } = await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/call-outcomes": callOutcomes(),
      "/v1/lead-fields": leadFields({ ...SHOP, jobs: [line()] }),
      "/v1/inbound-lines/l1/notes": notes(),
      "POST /v1/lead-fields/replace": { jobs_changed: 1, jobs_unchanged: 0, jobs_waiting: 0 },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Use on campaigns and lines" }));
    fireEvent.click(screen.getByRole("button", { name: "Replace on 1" }));
    fireEvent.click(await screen.findByRole("button", { name: "Replace" }));
    await waitFor(() => {
      const sent = calls.find((c) => c.path === "/v1/lead-fields/replace");
      expect(sent && JSON.parse(sent.body ?? "{}")).toEqual({ jobs: [{ kind: "line", id: "l1", digest: "d1" }] });
    });
    expect(await screen.findByText("1 campaign or line updated.")).toBeTruthy();
  });
});

describe("the core in the business's own words", () => {
  it("renames a core detail and sends the usual name back as blank", async () => {
    const { calls } = await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/call-outcomes": callOutcomes(),
      "/v1/lead-fields": leadFields(),
      "PUT /v1/lead-fields/core-labels": leadFields({
        core_fields: [field("name", "Name"), field("need", "Crop issue")],
      }),
    });
    fireEvent.click(await screen.findByRole("button", { name: /Rename/ }));
    fireEvent.change(screen.getByRole("textbox", { name: /What they want, or why they called/ }), {
      target: { value: "Crop issue" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save names" }));
    await waitFor(() => {
      const put = calls.find((c) => c.method === "PUT");
      expect(put?.path).toBe("/v1/lead-fields/core-labels");
      expect(JSON.parse(put?.body ?? "{}")).toEqual({ labels: { name: "", need: "Crop issue" } });
    });
    expect(await screen.findByText("Crop issue")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Save names" })).toBeNull();
  });

  it("offers no rename to someone who may not change the details", async () => {
    await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": { ...OWNER, permissions: ["org:read", "agents:read"] },
      "/v1/call-outcomes": callOutcomes(),
      "/v1/lead-fields": leadFields(),
    });
    await screen.findByRole("heading", { name: "Always captured" });
    expect(screen.queryByRole("button", { name: /Rename/ })).toBeNull();
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
    expect([...moves.options].map((o) => o.text)).toEqual(["Contacted", "Interested", "Goal reached"]);
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

describe("suggested changes to what a job notes (D-889, D-1029)", () => {
  const BHK = {
    key: "bhk_size",
    label: "BHK",
    type: "enum" as const,
    reason: "",
    required: false,
    enum_values: ["1BHK", "2BHK", "3BHK", "4BHK", "5BHK+"],
  };
  const withBhk = () => leadFields({ can_draft: false, jobs: [line({ name: "Flats desk", fields: [BHK] })] });
  const BHK_NOTES = { ...notes(), fields: [BHK] };
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
  const BASE = "/v1/inbound-lines/l1/lead-suggestions";

  it("shows each change with why, and accepting one asks the server and re-reads the list", async () => {
    const { calls } = await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/call-outcomes": callOutcomes(),
      "/v1/lead-fields": withBhk(),
      "/v1/inbound-lines/l1/notes": BHK_NOTES,
      [BASE]: suggestions(),
      [`POST ${BASE}/0123456789abcdef/accept`]: {
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

    const before = calls.filter((c) => c.path === "/v1/inbound-lines/l1/notes").length;
    fireEvent.click(screen.getAllByRole("button", { name: "Accept" })[0]);
    await waitFor(() => expect(screen.queryByText("Add to BHK")).toBeNull());
    expect(calls.some((c) => c.method === "POST" && c.path === `${BASE}/0123456789abcdef/accept`)).toBe(true);
    await waitFor(() => {
      expect(calls.filter((c) => c.path === "/v1/inbound-lines/l1/notes").length).toBeGreaterThan(before);
    });
  });

  it("accepts all of them in one request", async () => {
    const { calls } = await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/call-outcomes": callOutcomes(),
      "/v1/lead-fields": withBhk(),
      "/v1/inbound-lines/l1/notes": BHK_NOTES,
      [BASE]: suggestions(),
      [`POST ${BASE}/accept`]: { accepted: [ADD, NEW], remaining: suggestions({ suggestions: [] }) },
    });
    await screen.findByRole("heading", { name: "Suggested changes (2)" });
    fireEvent.click(screen.getByRole("button", { name: "Accept all 2" }));
    await waitFor(() => expect(screen.queryByText("New detail: Facing")).toBeNull());
    const posts = calls.filter((c) => c.method === "POST" && c.path.startsWith(BASE));
    expect(posts.map((c) => [c.path, JSON.parse(c.body ?? "null")])).toEqual([[`${BASE}/accept`, { ids: [ADD.id, NEW.id] }]]);
  });

  it("shows the saved list when an accept could not reach the calls, and offers Save again", async () => {
    let accepted = false;
    const NOTES_PATH = "/v1/inbound-lines/l1/notes";
    const SAVED = { ...notes(), fields: [{ ...BHK, enum_values: [...BHK.enum_values, "6BHK"] }], digest: "d2" };
    const { calls } = await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/call-outcomes": callOutcomes(),
      "/v1/lead-fields": withBhk(),
      [NOTES_PATH]: () => (accepted ? SAVED : BHK_NOTES),
      [`PUT ${NOTES_PATH}`]: SAVED,
      [BASE]: () => (accepted ? suggestions({ suggestions: [NEW] }) : suggestions()),
      [`POST ${BASE}/0123456789abcdef/accept`]: () => {
        accepted = true;
        return problem(422, {
          type: "https://calevate.tech/problems/engine_unavailable",
          title: "Saved, but not on its calls yet",
          status: 422,
          kind: "business_rule",
          detail: "The calling platform did not answer.",
          remediation: "Your change is kept. Save again to put it on the calls.",
        });
      },
    });
    await screen.findByRole("heading", { name: "Suggested changes (2)" });
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
    const reads = () => calls.filter((c) => c.method === "GET" && c.path === NOTES_PATH).length;
    const before = reads();

    fireEvent.click(screen.getAllByRole("button", { name: "Accept" })[0]);
    expect(await screen.findByText("The calling platform did not answer.")).toBeTruthy();
    // The editor re-read the list the accept saved, and the message outlived its remount.
    await waitFor(() => expect(reads()).toBeGreaterThan(before));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Suggested changes (1)" })).toBeTruthy());
    expect(screen.getByText("The calling platform did not answer.")).toBeTruthy();
    // Nothing is unsaved, and Save over the saved list is still offered: it is the retry.
    expect(screen.queryByText("You have unsaved changes.")).toBeNull();
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Save again" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.path === NOTES_PATH)).toBe(true));
    const put = calls.find((c) => c.method === "PUT" && c.path === NOTES_PATH)!;
    expect(JSON.parse(put.body ?? "null").expected_digest).toBe("d2");
    await waitFor(() => expect(screen.queryByText("The calling platform did not answer.")).toBeNull());
    expect(screen.queryByRole("button", { name: "Save again" })).toBeNull();
  });

  it("turns one down, and holds Accept while the owner has unsaved edits", async () => {
    const { calls } = await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/call-outcomes": callOutcomes(),
      "/v1/lead-fields": withBhk(),
      "/v1/inbound-lines/l1/notes": BHK_NOTES,
      [BASE]: suggestions(),
      [`POST ${BASE}/fedcba9876543210/dismiss`]: {
        answered: NEW,
        remaining: suggestions({ suggestions: [ADD] }),
      },
    });
    await screen.findByRole("heading", { name: "Suggested changes (2)" });
    fireEvent.click(screen.getByRole("button", { name: "Not now: New detail: Facing" }));
    await waitFor(() => expect(screen.queryByText("New detail: Facing")).toBeNull());
    expect(calls.some((c) => c.method === "POST" && c.path === `${BASE}/fedcba9876543210/dismiss`)).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: /Add a detail/ }));
    expect(screen.getByText("Save or undo the changes below to accept one.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Accept" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("says when it is checking, when the allowance stopped it, and checks again on request", async () => {
    const { calls } = await renderClientPage(<LeadDetailsScreen />, {
      "/v1/me": OWNER,
      "/v1/call-outcomes": callOutcomes(),
      "/v1/lead-fields": withBhk(),
      "/v1/inbound-lines/l1/notes": BHK_NOTES,
      [BASE]: suggestions({ state: "skipped", suggestions: [] }),
      [`POST ${BASE}/check`]: suggestions({ state: "queued", suggestions: [] }),
    });
    await screen.findByText(/this month's AI allowance is used up/);
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    await screen.findByText("Checking what it’s for, the script and recent calls…");
    expect(calls.some((c) => c.method === "POST" && c.path === `${BASE}/check`)).toBe(true);
    expect(screen.queryByRole("button", { name: "Check again" })).toBeNull();
  });
});
