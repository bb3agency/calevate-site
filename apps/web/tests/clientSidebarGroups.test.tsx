import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ClientRealmLayout from "@/app/c/[slug]/layout";
import { clientNavigation, showsTrialNav, trialNavigation, TRIAL_AGENTS_LABEL } from "@/lib/clientNav";

import { NOT_ON_TRIAL, problem, stillLoading, stubApi, type Routes } from "./harness";
import { CLIENT_SHELL_ROUTES, LEGAL_READY } from "./fixtures/sharedReads";

/*
 * THE CLIENT SIDEBAR (redesign 28 Nov 2026, PLAN §4): six entries and "Show everything" on a
 * trial with no test minute used, the grouped list for everyone else, and never a hidden
 * screen on a guess.
 */

const nav = vi.hoisted(() => ({ pathname: "/c/acme" }));
vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({ slug: "acme" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), back: vi.fn(), forward: vi.fn(), prefetch: vi.fn() }),
}));

const OWNER = {
  organization: { name: "Acme" },
  role: "owner",
  permissions: ["org:read", "org:manage", "leads:read", "leads:write"],
};

const FRESH_TRIAL = { ...NOT_ON_TRIAL, on_trial: true, minutes_used: 0, free_minutes: 15, minutes_left: 15 };

/** A first run not started yet: due, nothing written, nothing building. */
const FIRST_RUN_DUE = {
  due: true,
  jobs: [],
  documents: [],
  questions: { status: "ready", items: [], disclosure: null },
  build: { status: "none", steps: [], disclosure: null, builds_left: 3 },
};

async function renderShell(routes: Routes) {
  stubApi({
    ...CLIENT_SHELL_ROUTES,
    "/v1/me": OWNER,
    "/v1/legal/readiness": { ...LEGAL_READY, outstanding_documents: 4 },
    ...routes,
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    render(
      <QueryClientProvider client={client}>
        <ClientRealmLayout params={Promise.resolve({ slug: "acme" })}>
          <p>screen</p>
        </ClientRealmLayout>
      </QueryClientProvider>,
    );
  });
}

const sidebar = () => document.querySelector<HTMLElement>("nav.custom-scrollbar") as HTMLElement;
const linkNames = () =>
  within(sidebar())
    .queryAllByRole("link")
    .filter((link) => !link.closest("[inert]"))
    .map((link) => link.textContent?.trim());

beforeEach(() => {
  nav.pathname = "/c/acme";
  window.localStorage.clear();
});

describe("which sidebar an account gets", () => {
  it("is the short list only on a trial with no test minute used", () => {
    expect(showsTrialNav(FRESH_TRIAL)).toBe(true);
    expect(showsTrialNav({ ...FRESH_TRIAL, minutes_used: 1 })).toBe(false);
    expect(showsTrialNav(NOT_ON_TRIAL)).toBe(false);
    expect(showsTrialNav(undefined)).toBe(false);
  });

  it("takes the six trial entries from the one navigation list, in order", () => {
    const items = trialNavigation(clientNavigation("acme"), "acme").map((item) => item.label);
    expect(items).toEqual(["Dashboard", TRIAL_AGENTS_LABEL, "Make a call", "Call logs", "Pip", "Credits & billing"]);
  });
});

describe("the trial sidebar", () => {
  it("shows six entries and Show everything, and no agreements count", async () => {
    await renderShell({ "/v1/trial": FRESH_TRIAL, "/v1/first-run": problem(404, { title: "Not found" }) });
    await screen.findByRole("button", { name: "Show everything" });
    expect(linkNames().slice(0, 6)).toEqual(["Dashboard", "Your agent", "Make a call", "Call logs", "Pip", "Credits & billing"]);
    expect(screen.queryByLabelText("4 outstanding")).toBeNull();
    expect(linkNames()).not.toContain("Agreements");
  });

  it("opens every other screen in place, and remembers it", async () => {
    await renderShell({ "/v1/trial": FRESH_TRIAL, "/v1/first-run": problem(404, { title: "Not found" }) });
    const more = await screen.findByRole("button", { name: "Show everything" });
    expect(more.getAttribute("aria-expanded")).toBe("false");
    await act(async () => {
      fireEvent.click(more);
    });
    expect(screen.getByRole("button", { name: "Show less" }).getAttribute("aria-expanded")).toBe("true");
    expect(linkNames()).toContain("Agreements");
    expect(linkNames().filter((name) => name === "Dashboard")).toHaveLength(1);
    expect(window.localStorage.getItem("calevate:sidebar-show-everything")).toBe("1");
  });

  it("leads Your agent to Meet your agent while the first run is due", async () => {
    await renderShell({ "/v1/trial": FRESH_TRIAL, "/v1/first-run": FIRST_RUN_DUE });
    const agent = await screen.findByRole("link", { name: "Your agent" });
    await vi.waitFor(() => expect(agent.getAttribute("href")).toBe("/c/acme/agents/first"));
  });

  it("opens the rest by itself on a screen outside the six", async () => {
    nav.pathname = "/c/acme/settings/team";
    await renderShell({ "/v1/trial": FRESH_TRIAL, "/v1/first-run": problem(404, { title: "Not found" }) });
    const team = await screen.findByRole("link", { name: "Team" });
    expect(team.getAttribute("aria-current")).toBe("page");
    expect(team.closest("[inert]")).toBeNull();
    expect(screen.queryByRole("button", { name: "Show everything" })).toBeNull();
  });
});

describe("the full sidebar", () => {
  it("shows while the trial read is in flight, so no screen hides on a guess", async () => {
    await renderShell({ "/v1/trial": stillLoading() });
    expect(within(sidebar()).getByRole("group", { name: "Rules & records" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Show everything" })).toBeNull();
  });

  it("groups the screens and keeps the agreements count", async () => {
    await renderShell({ "/v1/trial": { ...FRESH_TRIAL, minutes_used: 3 } });
    for (const group of ["Calling", "Results", "Knowledge", "Rules & records", "Account"]) {
      expect(within(sidebar()).getByRole("group", { name: group })).toBeTruthy();
    }
    expect(await screen.findByLabelText("4 outstanding")).toBeTruthy();
  });

  it("folds a group from its heading, but never the one holding the page", async () => {
    nav.pathname = "/c/acme/calls";
    await renderShell({});
    const results = within(sidebar()).getByRole("group", { name: "Results" });
    expect(within(results).queryByRole("button")).toBeNull();
    const account = within(sidebar()).getByRole("group", { name: "Account" });
    const fold = within(account).getByRole("button", { name: "Account" });
    expect(fold.getAttribute("aria-expanded")).toBe("true");
    await act(async () => {
      fireEvent.click(fold);
    });
    expect(fold.getAttribute("aria-expanded")).toBe("false");
    expect(within(account).getByRole("link", { name: "Team", hidden: true }).closest("[inert]")).not.toBeNull();
  });

  it("puts Pip at the foot of the list", async () => {
    await renderShell({});
    const names = linkNames();
    expect(names.indexOf("Pip")).toBeGreaterThan(names.indexOf("AI help"));
  });
});
