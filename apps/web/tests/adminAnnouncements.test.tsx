import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AnnouncementsScreen } from "@/app/admin/announcements/AnnouncementsScreen";
import {
  createInput,
  messageLength,
  updateInput,
  validateDraft,
  EMPTY_DRAFT,
} from "@/app/admin/announcements/announcementDraft";

import { problem, renderAdminPage } from "./harness";

const ME = {
  user_id: "admin-1",
  realm: "admin",
  role: "superadmin",
  permissions: ["admin:tenants"],
  impersonating: false,
};

const SHOWING = {
  id: "a1",
  message: "Planned maintenance on Sunday, 02:00 to 03:00 IST.",
  link_url: "/status",
  link_label: "Status page",
  tone: "warning",
  audience: "all",
  target_tenant_id: null,
  target_tenant_name: null,
  starts_at: "2026-10-24T03:30:00Z",
  ends_at: null,
  ended_at: null,
  state: "showing",
  created_at: "2026-10-24T03:00:00Z",
  updated_at: "2026-10-24T03:00:00Z",
};

describe("announcement draft rules", () => {
  it("counts code points after collapsing whitespace, as the server stores it", () => {
    expect(messageLength("  hello   world ")).toBe(11);
    expect(messageLength("నమస్కారం")).toBe([..."నమస్కారం"].length);
  });

  it("refuses what the server refuses, in words", () => {
    const errors = validateDraft({
      ...EMPTY_DRAFT,
      message: "x".repeat(281),
      linkUrl: "http://example.com",
      audience: "tenant",
    });
    expect(errors.message).toBe("Shorten it by 1 character.");
    expect(errors.linkUrl).toMatch(/https:\/\//);
    expect(errors.target).toBe("Choose the client who should see it.");
    expect(validateDraft({ ...EMPTY_DRAFT, message: "ok", linkLabel: "Go" }).linkLabel).toBe(
      "A link label needs a link.",
    );
  });

  it("sends IST times with the instant they mean, and an unchosen start as now", () => {
    const body = createInput({ ...EMPTY_DRAFT, message: "Hi", startsAt: "2026-10-25T09:00", endsAt: "" });
    expect(body.starts_at).toBe("2026-10-25T03:30:00.000Z");
    expect(body.ends_at).toBeNull();
    expect(createInput({ ...EMPTY_DRAFT, message: "Hi" }).starts_at).toBeNull();
  });

  it("patches only what moved, and clears a link with null", () => {
    const before = { ...EMPTY_DRAFT, message: "Hi", linkUrl: "/billing" };
    expect(updateInput(before, before)).toEqual({});
    expect(updateInput(before, { ...before, linkUrl: "" })).toEqual({ link_url: null });
  });
});

describe("announcements screen", () => {
  it("lists what is showing with its audience and window", async () => {
    renderAdminPage(<AnnouncementsScreen />, {
      "/v1/admin/me": ME,
      "/v1/admin/announcements": { items: [SHOWING], total: 1 },
    });
    expect(await screen.findByText(SHOWING.message)).toBeTruthy();
    expect(screen.getByText("Showing now")).toBeTruthy();
    expect(screen.getByText("Heads up for every client")).toBeTruthy();
    expect(screen.getByText(/until ended IST/)).toBeTruthy();
  });

  it("says when the list is only the newest slice of the total", async () => {
    renderAdminPage(<AnnouncementsScreen />, {
      "/v1/admin/me": ME,
      "/v1/admin/announcements": { items: [SHOWING], total: 120 },
    });
    expect(await screen.findByText("The newest 1 of 120 are shown.")).toBeTruthy();
  });

  it("says nothing is shown only when the server answered, and refuses a failed read", async () => {
    renderAdminPage(<AnnouncementsScreen />, {
      "/v1/admin/me": ME,
      "/v1/admin/announcements": problem(503, { title: "Unavailable" }),
    });
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByText("Nothing is being shown to clients.")).toBeNull();
  });

  it("previews the bar live, counts characters, and publishes", async () => {
    const { calls } = renderAdminPage(<AnnouncementsScreen />, {
      "/v1/admin/me": ME,
      "GET /v1/admin/announcements": { items: [], total: 0 },
      "POST /v1/admin/announcements": { ...SHOWING, id: "a9", message: "New voices are here." },
    });
    expect(await screen.findByText("Nothing is being shown to clients.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /New announcement/ }));
    const drawer = await screen.findByRole("dialog");

    fireEvent.click(within(drawer).getByRole("button", { name: "Publish now" }));
    expect(await within(drawer).findByText("Write the message clients will read.")).toBeTruthy();

    fireEvent.change(within(drawer).getByLabelText("Message"), { target: { value: "New voices are here." } });
    expect(within(drawer).getByText("20 of 280 characters")).toBeTruthy();
    const preview = within(drawer).getByRole("region", { name: "Preview of the announcement" });
    expect(within(preview).getByText("New voices are here.")).toBeTruthy();

    await act(async () => {
      fireEvent.click(within(drawer).getByRole("button", { name: "Publish now" }));
    });
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/v1/admin/announcements")).toBe(true));
    const sent = calls.find((c) => c.method === "POST" && c.path === "/v1/admin/announcements");
    expect(JSON.parse(sent?.body ?? "{}")).toMatchObject({ message: "New voices are here.", audience: "all", tone: "info" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("asks before ending one, then ends it", async () => {
    const { calls } = renderAdminPage(<AnnouncementsScreen />, {
      "/v1/admin/me": ME,
      "GET /v1/admin/announcements": { items: [SHOWING], total: 1 },
      "POST /v1/admin/announcements/a1/end": { ...SHOWING, state: "ended", ended_at: "2026-10-24T05:00:00Z" },
    });
    fireEvent.click(await screen.findByRole("button", { name: /More actions for/ }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "End now" }));
    const dialog = await screen.findByRole("dialog", { name: "End this announcement now?" });
    expect(within(dialog).getByText(/stops showing to every client/)).toBeTruthy();
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "End it now" }));
    });
    await waitFor(() => expect(calls.some((c) => c.path === "/v1/admin/announcements/a1/end")).toBe(true));
  });
});
