import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import KnowledgePage from "@/app/c/[slug]/knowledge/page";
import DataRightsPage from "@/app/c/[slug]/data-rights/page";
import { daysLeftLine } from "@/app/c/[slug]/data-rights/deskCopy";
import { BusinessProfileScreen } from "@/app/c/[slug]/settings/business/BusinessProfileScreen";
import { TeamList } from "@/app/c/[slug]/settings/alerts/TeamList";
import { ToastProvider } from "@/components/arc/toast";
import type { Me } from "@/lib/api/client";
import type { BusinessProfile } from "@/lib/api/businessProfile";
import type { KbUpload, KbUploadText } from "@/lib/api/kb";

import { NEUTRAL_WORDING, businessProfileFixture } from "./businessProfileFixture";
import { OWNER_ME, teamAlertReads } from "./fixtures/sharedReads";
import { problem, renderClientPage, type ApiCall, type Routes } from "./harness";

/**
 * Frontend audit round 5, lane Y6 (10 Nov 2026): client settings, knowledge and the
 * compliance screens. Each test fails on the source before its fix.
 */

const OWNER: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["agents:read", "kb:write", "org:read", "org:manage", "calls:read", "calls:read_raw", "leads:read"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};
/** Staff whose owner has not let them add knowledge: they read it and change nothing. */
const STAFF: Me = { ...OWNER, role: "staff", permissions: ["agents:read", "org:read", "leads:read"] };

const MENU: KbUpload = {
  id: "u1",
  source_id: "s1",
  facts_count: 0,
  name: "Menu.pdf",
  source_kind: "pdf",
  ingest_status: "processed",
  ingest_detail: null,
  review_state: "approved",
  is_live: true,
  version: 1,
  filename: "Menu.pdf",
  byte_size: 2048,
  source_url: null,
  text_provenance: null,
  change_detected_at: null,
  read_state: "ready",
  read_detail: null,
  page_count: 1,
  reaches_agents: true,
};

/** A photo whose words were read and wait for the owner to check them. */
const PHOTO: KbUpload = {
  ...MENU,
  id: "u2",
  source_id: "s2",
  name: "Price board.jpg",
  filename: "Price board.jpg",
  source_kind: "image",
  ingest_status: "received",
  review_state: "pending_approval",
  is_live: false,
  text_provenance: "ocr",
  read_state: null,
  page_count: null,
};

const WORDS: KbUploadText = {
  upload_id: "u1",
  name: "Menu.pdf",
  kind: "file",
  state: "in_use",
  reaches_agents: true,
  origin: "Menu.pdf",
  version: 1,
  page: 1,
  pages: 1,
  sections: [{ label: "Page 1", content: "Thali costs 180 rupees." }],
  note: null,
};

function knowledge(me: Me, uploads: KbUpload[], over: Routes = {}) {
  return renderClientPage(
    <ToastProvider>
      <KnowledgePage />
    </ToastProvider>,
    {
      "/v1/me": me,
      "/v1/kb/notes": { notes: [] },
      "/v1/kb/uploads": uploads,
      ...Object.fromEntries(uploads.map((row) => [`/v1/kb/uploads/${row.id}`, row])),
      "/v1/teach/questions": { items: [], open_count: 0 },
      "/v1/kb/staff-curation": { staff_may_curate_knowledge: false },
      "/v1/kb/knows": { facts: [], facts_state: "none", items: [], pinned_not_yet_on: [] },
      "/v1/kb/teach/open": { teaching: null },
      "/v1/business-profile": businessProfileFixture(),
      "/v1/agents": [],
      "/v1/kb/uploads/u1/text?page=1": WORDS,
      "/v1/kb/sources/s2/preview": [{ idx: 0, content: "Thali 180" }],
      ...over,
    },
  );
}

/** The multipart seam (`apiUpload` is an XMLHttpRequest): answers 201 with `xhrBody`. */
let xhrBody: unknown = MENU;
class StubXhr {
  status = 0;
  responseText = "";
  withCredentials = false;
  readonly upload = new EventTarget();
  private readonly events = new EventTarget();
  open(): void {}
  setRequestHeader(): void {}
  getResponseHeader(name: string): string | null {
    return name.toLowerCase() === "content-type" ? "application/json" : null;
  }
  addEventListener(type: string, listener: EventListener): void {
    this.events.addEventListener(type, listener);
  }
  abort(): void {}
  send(): void {
    queueMicrotask(() => {
      this.status = 201;
      this.responseText = JSON.stringify(xhrBody);
      this.events.dispatchEvent(new Event("load"));
    });
  }
}

beforeEach(() => {
  xhrBody = MENU;
  vi.stubGlobal("XMLHttpRequest", StubXhr);
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Y6-01 a file's row offers no change to someone who may not make it", () => {
  it("has no Remove in the row menu for staff without knowledge access", async () => {
    await knowledge(STAFF, [MENU]);
    fireEvent.click(await screen.findByRole("button", { name: "More actions for Menu.pdf" }));
    expect(await screen.findByRole("menuitem", { name: "Read it" })).toBeTruthy();
    expect(screen.queryByRole("menuitem", { name: /^remove$/i })).toBeNull();
  });

  it("has no Throw this away under a photo's reading for staff", async () => {
    await knowledge(STAFF, [PHOTO]);
    fireEvent.click(await screen.findByRole("button", { name: "Read it and confirm" }));
    await screen.findByText("Thali 180");
    expect(screen.queryByRole("button", { name: /throw this away/i })).toBeNull();
  });

  it("still offers Remove to the owner", async () => {
    await knowledge(OWNER, [MENU]);
    fireEvent.click(await screen.findByRole("button", { name: "More actions for Menu.pdf" }));
    expect(await screen.findByRole("menuitem", { name: /^remove$/i })).toBeTruthy();
  });
});

describe("Y6-02 what the reader did is said after it closes", () => {
  async function openReader(over: Routes = {}) {
    const rendered = await knowledge(OWNER, [MENU], over);
    fireEvent.click(await screen.findByRole("button", { name: "Menu.pdf" }));
    const dialog = await screen.findByRole("dialog", { name: "Menu.pdf" });
    return { ...rendered, dialog };
  }

  it("says a replacement arrived when Replace file closes the reader", async () => {
    xhrBody = { ...MENU, id: "u9", version: 2, is_live: false, read_state: "reading" };
    const { dialog } = await openReader();
    fireEvent.click(within(dialog).getByRole("button", { name: "Replace file" }));
    const file = new File(["%PDF-1.4"], "Menu v2.pdf", { type: "application/pdf" });
    fireEvent.change(within(dialog).getByLabelText(/the new file/i), { target: { files: [file] } });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Menu.pdf" })).toBeNull());
    expect(await screen.findByText("Reading the new Menu.pdf. It replaces the old one.")).toBeTruthy();
  });

  it("says Renamed once the rename form closes", async () => {
    const { dialog } = await openReader({ "PATCH /v1/kb/uploads/u1": { ...MENU, name: "Lunch menu" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Rename" }));
    fireEvent.change(within(dialog).getByLabelText("New name"), { target: { value: "Lunch menu" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save name" }));
    await waitFor(() => expect(within(dialog).queryByLabelText("New name")).toBeNull());
    expect(await screen.findByText("Renamed")).toBeTruthy();
  });

  it("says a thrown-away reading was thrown away after its panel closes", async () => {
    await knowledge(OWNER, [PHOTO], { "DELETE /v1/kb/uploads/u2": null });
    fireEvent.click(await screen.findByRole("button", { name: "Read it and confirm" }));
    fireEvent.click(await screen.findByRole("button", { name: /throw this away/i }));
    fireEvent.click(await screen.findByRole("button", { name: "Throw it away" }));
    expect(await screen.findByText("Threw away what we read from Price board.jpg")).toBeTruthy();
  });
});

describe("Y6-03 the rights desk", () => {
  const DESK = "/v1/compliance/rights-requests?limit=100";
  const EMPTY = { items: [], open: 0, due_soon: 0, overdue: 0, response_days: 90, reminder_days: 14 };

  function rights(routes: Routes) {
    return renderClientPage(
      <ToastProvider>
        <DataRightsPage />
      </ToastProvider>,
      { "/v1/me": OWNER, "/v1/compliance/deletion-requests?limit=100": [], ...routes },
    );
  }

  it("says a logged request was logged when the drawer closes", async () => {
    await rights({
      [DESK]: EMPTY,
      "POST /v1/compliance/rights-requests": {
        id: "r1",
        kind: "access",
        channel: "phone",
        status: "open",
        received_at: "2026-11-10T04:00:00Z",
        due_at: "2027-02-08T04:00:00Z",
        days_left: 90,
        due_soon: false,
        overdue: false,
        subject_ref: "abcdef0123456789",
        outcome: null,
        closed_at: null,
        deletion_request_id: null,
      },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Log a request" }));
    const drawer = await screen.findByRole("dialog", { name: "Log a request" });
    fireEvent.change(within(drawer).getByLabelText("Their phone number"), { target: { value: "9876543210" } });
    fireEvent.click(within(drawer).getByRole("button", { name: "Log it" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Log a request" })).toBeNull());
    expect(await screen.findByText("Logged")).toBeTruthy();
  });

  it("offers Try again when the desk did not load", async () => {
    let fail = true;
    await rights({
      [DESK]: () => (fail ? problem(503, { title: "Unavailable", retryable: true }) : EMPTY),
    });
    const retry = await screen.findByRole("button", { name: /try again/i });
    fail = false;
    fireEvent.click(retry);
    expect(await screen.findByText("No customer has asked about their data yet.")).toBeTruthy();
  });

  it("says one day overdue, not one days", () => {
    expect(daysLeftLine(-1)).toBe("1 day overdue");
    expect(daysLeftLine(-3)).toBe("3 days overdue");
  });
});

describe("Y6-04 adding a team address says the code went", () => {
  it("toasts Code sent after the form closes", async () => {
    const reads = teamAlertReads();
    let added = false;
    await renderClientPage(
      <ToastProvider>
        <ul>
          <TeamList canWrite reason={null} />
        </ul>
      </ToastProvider>,
      {
        "/v1/me": OWNER_ME,
        ...reads,
        "/v1/team-alerts/contacts": (call: ApiCall) => {
          if (call.method === "POST") added = true;
          return added
            ? {
                ...reads["/v1/team-alerts/contacts"],
                contacts: [
                  { id: "c1", channel: "email", address: "team@rytu.in", verified: false, whatsapp_account_id: null },
                ],
              }
            : reads["/v1/team-alerts/contacts"];
        },
      },
    );
    fireEvent.click(await screen.findByRole("button", { name: "Add someone from your team" }));
    fireEvent.change(screen.getByLabelText("Their email"), { target: { value: "team@rytu.in" } });
    fireEvent.click(screen.getByRole("button", { name: "Add and send code" }));
    expect(await screen.findByText(/Waiting for the code/)).toBeTruthy();
    expect(await screen.findByText("Code sent")).toBeTruthy();
  });
});

describe("Y6-05 switching how to answer the business profile keeps unsaved typing", () => {
  const PROFILE_OWNER = { ...OWNER, permissions: ["org:read", "org:manage", "agents:read"] };
  function profile(): BusinessProfile {
    return {
      ...businessProfileFixture(),
      business_name: "Sunrise Dental",
      wording: NEUTRAL_WORDING,
      branches: [{ label: "Main", address: "12 MG Road, Hyderabad" }],
    };
  }

  it("asks before One at a time throws the typing away, and Keep editing keeps it", async () => {
    const { container } = await renderClientPage(<BusinessProfileScreen />, {
      "/v1/me": PROFILE_OWNER,
      "/v1/business-profile": profile(),
    });
    await screen.findAllByRole("button", { name: "Save" });
    const address = Array.from(container.querySelectorAll("input")).find(
      (box) => box.value === "12 MG Road, Hyderabad",
    ) as HTMLInputElement;
    fireEvent.change(address, { target: { value: "14 MG Road, Hyderabad" } });

    fireEvent.click(screen.getByRole("radio", { name: "One at a time" }));
    const ask = await screen.findByRole("dialog", { name: "Leave without saving?" });
    fireEvent.click(within(ask).getByRole("button", { name: "Keep editing" }));
    expect(screen.queryByRole("dialog", { name: "Leave without saving?" })).toBeNull();
    expect(address.value).toBe("14 MG Road, Hyderabad");
  });
});

describe("Y6-05b the one-at-a-time wizard asks too", () => {
  afterEach(() => window.history.replaceState(null, "", "/"));

  it("asks before All answers throws a half-typed step away", async () => {
    window.history.replaceState(null, "", "/?mode=steps&step=branches");
    const { container } = await renderClientPage(<BusinessProfileScreen />, {
      "/v1/me": { ...OWNER, permissions: ["org:read", "org:manage", "agents:read"] },
      "/v1/business-profile": {
        ...businessProfileFixture(),
        wording: NEUTRAL_WORDING,
        branches: [{ label: "Main", address: "12 MG Road, Hyderabad" }],
      },
      "POST /v1/business-profile/setup": businessProfileFixture(),
    });
    const typed = () =>
      Array.from(container.querySelectorAll("input")).find((box) => box.value === "12 MG Road, Hyderabad");
    await waitFor(() => expect(typed()).toBeTruthy());
    fireEvent.change(typed() as HTMLInputElement, { target: { value: "14 MG Road, Hyderabad" } });
    fireEvent.click(screen.getByRole("radio", { name: "All answers" }));
    expect(await screen.findByRole("dialog", { name: "Leave without saving?" })).toBeTruthy();
  });
});
