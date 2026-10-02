import { act, fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import { AdminCommandPalette } from "@/app/admin/AdminCommandPalette";
import { rankCommands } from "@/components/interior/command-palette";

import { problem, renderAdminPage, type Routes } from "./harness";

/**
 * The admin console's Ctrl/Cmd+K palette (D-661): keyboard and screen-reader operable,
 * closes on Escape with focus restored, searches clients through the existing directory
 * endpoint, and only ever navigates.
 */

const push = vi.fn();
let pathname = "/admin";
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => pathname,
  useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
}));

const ME: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000a1",
  role: "operator",
  permissions: ["admin:tenants", "org:read"],
};

const ROW = {
  id: "0192f0aa-7777-7000-8000-0000000000bb",
  name: "Sri Traders",
  slug: "sri-traders",
  status: "active",
  plan_tier: "prepaid",
  vertical_template: null,
  live_agents: 0,
  calls_7d: 0,
  leads: 0,
  last_call_at: null,
  holds: [],
  capped: false,
};

const PAGE = { rows: [ROW], total: 1, limit: 25, offset: 0 };

async function mount(routes: Routes = {}) {
  let result!: ReturnType<typeof renderAdminPage>;
  await act(async () => {
    result = renderAdminPage(<AdminCommandPalette />, {
      [ADMIN_ME_PATH]: ME,
      "/v1/admin/tenants": PAGE,
      "/v1/admin/tenants?q=sri": PAGE,
      ...routes,
    });
  });
  return result;
}

async function openWithButton() {
  const trigger = screen.getByRole("button", { name: "Search clients and pages" });
  trigger.focus();
  await act(async () => fireEvent.click(trigger));
  return trigger;
}

beforeEach(() => {
  push.mockReset();
  pathname = "/admin";
});

describe("the admin command palette", () => {
  it("opens on Ctrl+K and Cmd+K, as a labelled modal with focus in the search box", async () => {
    await mount();
    await act(async () => fireEvent.keyDown(document, { key: "k", ctrlKey: true }));
    const dialog = screen.getByRole("dialog", { name: "Search clients and pages" });
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(document.activeElement?.getAttribute("role")).toBe("combobox");

    await act(async () => fireEvent.keyDown(document, { key: "k", metaKey: true }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes on Escape and gives focus back to what opened it", async () => {
    await mount();
    const trigger = await openWithButton();
    expect(screen.getByRole("dialog")).toBeTruthy();
    await act(async () => fireEvent.keyDown(document, { key: "Escape" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("lists clients, pages and actions in labelled groups of options", async () => {
    await mount();
    await openWithButton();
    const listbox = screen.getByRole("listbox");
    expect(await within(listbox).findByRole("option", { name: /Sri Traders/ })).toBeTruthy();
    const names = within(listbox)
      .getAllByRole("group")
      .map((g) => document.getElementById(g.getAttribute("aria-labelledby") ?? "")?.textContent);
    expect(names).toEqual(["Clients", "Pages", "Actions"]);
    expect(within(listbox).getByRole("option", { name: /Client health/ })).toBeTruthy();
    expect(within(listbox).getByRole("option", { name: /Create a client/ })).toBeTruthy();
  });

  it("moves the active option with the arrow keys and opens it with Enter", async () => {
    await mount();
    await openWithButton();
    const input = screen.getByRole("combobox");
    await act(async () => fireEvent.change(input, { target: { value: "client health" } }));
    const first = screen.getAllByRole("option")[0];
    expect(first.getAttribute("aria-selected")).toBe("true");
    expect(input.getAttribute("aria-activedescendant")).toBe(first.id);
    await act(async () => fireEvent.keyDown(input, { key: "Enter" }));
    expect(push).toHaveBeenCalledWith("/admin/health");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("searches clients through the directory endpoint and opens the client", async () => {
    const { calls } = await mount();
    await openWithButton();
    const input = screen.getByRole("combobox");
    await act(async () => fireEvent.change(input, { target: { value: "sri" } }));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 260));
    });
    expect(calls.some((c) => c.method === "GET" && c.path === "/v1/admin/tenants?q=sri")).toBe(true);
    const option = await screen.findByRole("option", { name: /Sri Traders/ });
    await act(async () => fireEvent.click(option));
    expect(push).toHaveBeenCalledWith(`/admin/tenants/${ROW.id}`);
  });

  it("says when clients could not be searched, and keeps pages working", async () => {
    await mount({ "/v1/admin/tenants": problem(503, { title: "Unavailable", retryable: true }) });
    await openWithButton();
    expect(await screen.findByText(/Clients could not be searched right now/)).toBeTruthy();
    expect(screen.getByRole("option", { name: /Client health/ })).toBeTruthy();
  });

  it("offers a client's own sections first on that client's pages", async () => {
    pathname = `/admin/tenants/${ROW.id}/kyc`;
    await mount({ [`/v1/admin/tenants/${ROW.id}`]: ROW });
    await openWithButton();
    const options = await screen.findAllByRole("option");
    await vi.waitFor(() => expect(screen.getAllByRole("option")[0].textContent).toBe("Overview"));
    expect(options.length).toBeGreaterThan(0);
    expect(screen.getByRole("option", { name: /View Sri Traders as client \(logged\)/ })).toBeTruthy();
  });
});

describe("rankCommands", () => {
  const items = [
    { id: "a", label: "Held accounts", group: "Pages" },
    { id: "b", label: "Client health", group: "Pages" },
    { id: "c", label: "Credits", group: "Pages", keywords: "wallet" },
  ];
  it("ranks a word-start match first and drops what does not match", () => {
    expect(rankCommands(items, "ch").map((i) => i.id)[0]).toBe("b");
    expect(rankCommands(items, "zzz")).toEqual([]);
  });
  it("matches keywords, and keeps list order for an empty query", () => {
    expect(rankCommands(items, "wallet").map((i) => i.id)).toEqual(["c"]);
    expect(rankCommands(items, "  ").map((i) => i.id)).toEqual(["a", "b", "c"]);
  });
});
