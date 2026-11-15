import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import TenantCallHandlingPage from "@/app/admin/tenants/[tenantId]/call-handling/page";
import { CallHandlingPanel } from "@/app/admin/tenants/[tenantId]/agents/[agentId]/prompt/sections/callHandling";
import type { AgentCallHandling, OrganizationCallHandling } from "@/lib/api/callHandling";

import {
  CALL_HANDLING_BOUNDS,
  GIVE_CALLERS_TIME,
  VOICE_EFFECTIVE_DEFAULTS,
  VOICE_ORGANIZATION_NONE,
  VOICE_OWN_NONE,
  VOICE_SOURCES_PLATFORM,
  agentTurnDetection,
} from "./fixtures/sharedReads";
import { renderAdminRoute, routeParams } from "./adminRoute";
import { renderAdminPage, stillLoading } from "./harness";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(""),
  usePathname: () => "/admin/tenants/t1/call-handling",
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

/**
 * Every call-handling row on an operator screen shares ONE write. While one row's save is
 * out, a second row's save must wait: TanStack keeps only the latest `mutate`'s per-call
 * callbacks, so a second press takes over the first's answer and the first editor's
 * `done` never fires (it stays open over a save that landed), and the second row shows
 * the first row's outcome as its own.
 */

const TENANT = "t1";
const OPERATOR: AdminMe = {
  realm: "admin",
  user_id: "op-1",
  role: "operator",
  permissions: ["org:read", "admin:tenants"],
};

function organization(): OrganizationCallHandling {
  return {
    turn_silence_ms: 500,
    turn_silence_ms_effective: 500,
    end_call_on_finish: null,
    end_call_on_finish_effective: true,
    ...VOICE_OWN_NONE,
    ...VOICE_EFFECTIVE_DEFAULTS,
    agents_with_own: [],
    agents_with_own_total: 0,
    bounds: CALL_HANDLING_BOUNDS,
  };
}

function agent(): AgentCallHandling {
  return {
    agent_id: "agent-1",
    turn_silence_ms: 700,
    turn_silence_ms_effective: 700,
    turn_silence_source: "agent",
    end_call_on_finish: null,
    end_call_on_finish_effective: true,
    end_call_on_finish_source: "platform",
    organization_turn_silence_ms: 500,
    organization_end_call_on_finish: null,
    opening_waits_for_caller: false,
    ...VOICE_OWN_NONE,
    ...VOICE_EFFECTIVE_DEFAULTS,
    ...VOICE_SOURCES_PLATFORM,
    ...VOICE_ORGANIZATION_NONE,
    bounds: CALL_HANDLING_BOUNDS,
    give_callers_time: GIVE_CALLERS_TIME,
  };
}

/** Opens the pause and the background-sound editors, then saves the pause into a write that never answers. */
/** The widest ancestor of a row's Change button that holds no other Change button. */
function rowText(button: HTMLElement): string {
  let row: HTMLElement = button;
  while (
    row.parentElement &&
    Array.from(row.parentElement.querySelectorAll("button")).filter((b) => b.textContent === "Change").length === 1
  ) {
    row = row.parentElement;
  }
  return row.textContent ?? "";
}

function changeFor(label: string): HTMLElement {
  const found = screen.getAllByRole("button", { name: "Change" }).find((b) => rowText(b).includes(label));
  expect(found, `a Change button in the row "${label}"`).toBeTruthy();
  return found!;
}

async function savePauseThenOpenSound(writes: () => number, pauseChoice: RegExp) {
  await screen.findByText("Background sound");
  const pauseChange = changeFor("Pause before the agent replies");
  const soundChange = changeFor("Background sound");
  await act(async () => {
    fireEvent.click(pauseChange);
    fireEvent.click(soundChange);
  });
  const useDefault = screen.queryByRole("checkbox", { name: /^Use the .*default: Relaxed|^Use the .*default: Unhurried/ });
  if (useDefault && (useDefault as HTMLInputElement).checked) {
    await act(async () => {
      fireEvent.click(useDefault);
    });
  }
  await act(async () => {
    fireEvent.click(await screen.findByRole("radio", { name: pauseChoice }));
  });
  await act(async () => {
    fireEvent.click(await screen.findByRole("button", { name: /Save pause/ }));
  });
  await waitFor(() => expect(writes()).toBe(1));
  const followDefault = screen.getByRole("checkbox", { name: "Use the Calevate default: Off" });
  if ((followDefault as HTMLInputElement).checked) {
    await act(async () => {
      fireEvent.click(followDefault);
    });
  }
  await act(async () => {
    fireEvent.click(await screen.findByRole("radio", { name: "Office" }));
  });
}

describe("one shared call-handling write on the operator's screens", () => {
  it("one agent's panel: a voice row's save waits for the pause row's", async () => {
    const write = `/v1/admin/tenants/${TENANT}/agents/agent-1/call-handling`;
    const { calls } = renderAdminPage(
      <CallHandlingPanel
        tenantId={TENANT}
        agentId="agent-1"
        slug="acme"
        write={{ allowed: true, refused: false, reason: null }}
      />,
      {
        [ADMIN_ME_PATH]: OPERATOR,
        "/v1/agents/agent-1/call-handling": agent(),
        [`/v1/admin/tenants/${TENANT}/agents/agent-1/turn-detection`]: agentTurnDetection("agent-1"),
        [`PATCH ${write}`]: stillLoading(),
      },
    );
    const writes = () => calls.filter((c) => c.method === "PATCH").length;
    await savePauseThenOpenSound(writes, /^Relaxed/);

    const soundSave = screen.getByRole("button", { name: /Save sound/ });
    await act(async () => {
      fireEvent.click(soundSave);
    });
    await new Promise((settle) => setTimeout(settle, 50));
    expect(writes(), "a second write went out over the first").toBe(1);
    expect(soundSave.getAttribute("aria-disabled")).toBe("true");
  });

  it("a client's defaults: a voice row's save waits for the pause row's", async () => {
    const ADMIN_PATH = `/v1/admin/organizations/${TENANT}/call-handling`;
    const { calls } = await renderAdminRoute(
      <TenantCallHandlingPage params={routeParams({ tenantId: TENANT })} />,
      {
        [ADMIN_ME_PATH]: OPERATOR,
        [`/v1/admin/tenants/${TENANT}`]: { id: TENANT, name: "Sri Stores", slug: "acme" },
        [ADMIN_PATH]: organization(),
        [`PUT ${ADMIN_PATH}`]: stillLoading(),
      },
    );
    const writes = () => calls.filter((c) => c.method === "PUT").length;
    await savePauseThenOpenSound(writes, /^Unhurried/);

    const soundSave = screen.getByRole("button", { name: /Save sound/ });
    await act(async () => {
      fireEvent.click(soundSave);
    });
    await new Promise((settle) => setTimeout(settle, 50));
    expect(writes(), "a second write went out over the first").toBe(1);
    expect(soundSave.getAttribute("aria-disabled")).toBe("true");
  });
});
