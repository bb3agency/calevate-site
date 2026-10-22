import { act, fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentTour } from "@/app/c/[slug]/agents/[agentId]/tour/AgentTour";
import {
  placeCard,
  seenKey,
  TOUR_PARAM,
  TOUR_STEPS,
  TRY_IT_ANCHOR,
} from "@/app/c/[slug]/agents/[agentId]/tour/tourModel";
import { AGENT_TABS_LABEL } from "@/app/c/[slug]/agents/[agentId]/sections/agentSections";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

import { renderClientPage } from "./harness";

/*
 * THE AGENT PAGE TOUR (D-855): five steps, started by the owner, closed by Escape, the
 * close button or Done, and remembered per person so the trigger turns quiet.
 */
const nav = vi.hoisted(() => ({ params: new URLSearchParams(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => nav.params,
  usePathname: () => "/c/acme/agents/agent-1",
  useRouter: () => ({
    push: vi.fn(),
    replace: nav.replace,
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

const ME = {
  user_id: "user-7",
  realm: "client",
  role: "owner",
  permissions: ["agents:read", "org:read", "org:manage"],
  impersonating: false,
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

beforeEach(() => {
  nav.params = new URLSearchParams();
  nav.replace.mockClear();
  window.localStorage.clear();
});

/** What the tour points at, as the agent page and the console header draw it. */
function Page() {
  return (
    <>
      <button type="button" aria-label={`Ask ${ASSISTANT_NAME}`}>
        {ASSISTANT_NAME}
      </button>
      <button type="button" data-tour={TRY_IT_ANCHOR}>
        Try it
      </button>
      <div role="tablist" aria-label={AGENT_TABS_LABEL}>
        {["overview", "script", "training", "voice"].map((id) => (
          <button key={id} type="button" role="tab" id={`r1-tab-${id}`} aria-selected={id === "overview"}>
            {id}
          </button>
        ))}
      </div>
      <AgentTour />
    </>
  );
}

async function renderTour() {
  return renderClientPage(<Page />, { "/v1/me": ME });
}

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

const trigger = () => screen.getByRole("button", { name: "Show me around" });
const tour = () => screen.getByRole("dialog");

async function press(element: HTMLElement) {
  await act(async () => {
    fireEvent.click(element);
  });
}

describe("starting and moving through the tour", () => {
  it("is closed until the owner asks for it", async () => {
    await renderTour();
    await settle();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(trigger().getAttribute("aria-expanded")).toBe("false");
  });

  it("opens on step 1 of 5 with Next focused and no Back", async () => {
    await renderTour();
    await press(trigger());
    const dialog = tour();
    expect(within(dialog).getByText("Step 1 of 5")).toBeTruthy();
    expect(dialog.getAttribute("aria-labelledby")).toBeTruthy();
    expect(within(dialog).getByRole("heading", { name: TOUR_STEPS[0].title })).toBeTruthy();
    expect(within(dialog).queryByRole("button", { name: "Back" })).toBeNull();
    expect(document.activeElement).toBe(within(dialog).getByRole("button", { name: "Next" }));
  });

  it("walks forward and back, and announces each later step", async () => {
    await renderTour();
    await press(trigger());
    await press(within(tour()).getByRole("button", { name: "Next" }));
    expect(within(tour()).getByText("Step 2 of 5")).toBeTruthy();
    expect(within(tour()).getByRole("heading", { name: TOUR_STEPS[1].title })).toBeTruthy();
    const live = tour().querySelector('[aria-live="polite"]');
    expect(live?.textContent).toContain(`Step 2 of 5. ${TOUR_STEPS[1].title}.`);
    await press(within(tour()).getByRole("button", { name: "Back" }));
    expect(within(tour()).getByText("Step 1 of 5")).toBeTruthy();
  });

  it("ends with Done on the fifth step", async () => {
    await renderTour();
    await press(trigger());
    for (let i = 0; i < 4; i += 1) await press(within(tour()).getByRole("button", { name: "Next" }));
    expect(within(tour()).getByText("Step 5 of 5")).toBeTruthy();
    await press(within(tour()).getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("leaving the tour", () => {
  it("closes on Escape and gives focus back to the trigger", async () => {
    await renderTour();
    trigger().focus();
    await press(trigger());
    await act(async () => {
      fireEvent.keyDown(document, { key: "Escape" });
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger());
  });

  it("closes from the close button", async () => {
    await renderTour();
    await press(trigger());
    await press(within(tour()).getByRole("button", { name: "Close the tour" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("keeps Tab inside the card", async () => {
    await renderTour();
    await press(trigger());
    const next = within(tour()).getByRole("button", { name: "Next" });
    const close = within(tour()).getByRole("button", { name: "Close the tour" });
    next.focus();
    await act(async () => {
      fireEvent.keyDown(document, { key: "Tab" });
    });
    expect(document.activeElement).toBe(close);
  });
});

describe("remembering that the tour was seen", () => {
  it("draws the trigger in the brand colour until the person has taken it", async () => {
    await renderTour();
    await settle();
    expect(trigger().className).toContain("text-brand-strong");
    await press(trigger());
    await press(within(tour()).getByRole("button", { name: "Close the tour" }));
    expect(window.localStorage.getItem(seenKey("user-7"))).toBe("1");
    expect(trigger().className).not.toContain("text-brand-strong");
  });

  it("stays quiet, and still opens, for a person who has seen it", async () => {
    window.localStorage.setItem(seenKey("user-7"), "1");
    await renderTour();
    await settle();
    expect(trigger().className).not.toContain("text-brand-strong");
    await press(trigger());
    expect(tour()).toBeTruthy();
  });

  it("still works when storage is blocked", async () => {
    const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    try {
      await renderTour();
      await settle();
      await press(trigger());
      await press(within(tour()).getByRole("button", { name: "Close the tour" }));
      expect(screen.queryByRole("dialog")).toBeNull();
    } finally {
      getItem.mockRestore();
      setItem.mockRestore();
    }
  });
});

describe("?tour=1, the link the first-call screen can use", () => {
  it("opens the tour once and takes the parameter out of the address", async () => {
    nav.params = new URLSearchParams(`section=voice&${TOUR_PARAM}=1`);
    await renderTour();
    expect(tour()).toBeTruthy();
    expect(nav.replace).toHaveBeenCalledWith("/c/acme/agents/agent-1?section=voice", { scroll: false });
  });

  it("puts focus on the trigger when it closes, since nothing had focus before", async () => {
    nav.params = new URLSearchParams(`${TOUR_PARAM}=1`);
    await renderTour();
    (document.activeElement as HTMLElement | null)?.blur();
    await press(within(tour()).getByRole("button", { name: "Close the tour" }));
    await act(async () => {
      await new Promise((resolve) => requestAnimationFrame(resolve));
    });
    expect(document.activeElement).toBe(trigger());
  });
});

describe("every step points at something on the page", () => {
  it("finds the Script, Training and Voice tabs, Try it and the assistant's launcher", async () => {
    await renderTour();
    expect(TOUR_STEPS).toHaveLength(5);
    expect(TOUR_STEPS.map((step) => step.target(document)?.textContent)).toEqual([
      "script",
      ASSISTANT_NAME,
      "Try it",
      "training",
      "voice",
    ]);
  });
});

describe("where the card goes", () => {
  const card = { width: 352, height: 160 };

  it("is a bottom sheet on a phone", () => {
    expect(placeCard({ top: 100, left: 20, width: 80, height: 40 }, card, { width: 375, height: 812 })).toEqual({
      mode: "sheet",
    });
  });

  it("sits under the target, growing from it, when there is room", () => {
    const place = placeCard({ top: 100, left: 600, width: 80, height: 40 }, card, { width: 1280, height: 800 });
    expect(place).toEqual({ mode: "float", top: 152, left: 464, origin: "176px 0" });
  });

  it("sits over the target when there is no room below", () => {
    const place = placeCard({ top: 700, left: 600, width: 80, height: 40 }, card, { width: 1280, height: 800 });
    expect(place).toMatchObject({ mode: "float", top: 528, origin: "176px 100%" });
  });

  it("stays inside the viewport beside a target at the edge", () => {
    const place = placeCard({ top: 100, left: 1250, width: 30, height: 30 }, card, { width: 1280, height: 800 });
    expect(place).toMatchObject({ mode: "float", left: 1280 - 352 - 16 });
  });

  it("is centred when the target is not on the page", () => {
    expect(placeCard(null, card, { width: 1280, height: 800 })).toEqual({
      mode: "float",
      top: 320,
      left: 464,
      origin: "center",
    });
  });
});
