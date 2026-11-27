import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ScriptVersions, restoredToast } from "@/app/c/[slug]/campaigns/ScriptVersions";
import type { ActionFeedback } from "@/components/arc/feedback";
import type { ScriptRestore, ScriptVersions as Versions } from "@/lib/api/scriptVersions";

/**
 * "PUT BACK THE FLOW FROM BEFORE PIP" NEVER CLAIMS A CHANGE IT DID NOT MAKE (D-1039).
 *
 * The founder pressed it, read "Flow put back", and saw nothing change: the switch-back copy
 * was the script from just before an automatic repair. The button now restores the owner's
 * own last version, is held with a reason when there is none, and the toast names which
 * version came back.
 */

const OWN = {
  id: "v-own",
  author: "owner",
  owner_made: true,
  reason: "You saved the script.",
  created_at: "2026-11-23T10:40:00Z",
} as const;
const REPAIR = {
  id: "v-repair",
  author: "pip_repair",
  owner_made: false,
  reason: "Pip repaired lines the script checks found.",
  created_at: "2026-11-24T06:00:00Z",
} as const;

function versions(putBack: Versions["put_back"], list = [REPAIR, OWN]): Versions {
  return { current_version_id: list[0]?.id ?? null, put_back: putBack, versions: [...list] };
}

function feedback(): ActionFeedback<ScriptRestore> {
  return { status: "idle", run: vi.fn(), error: null, retryable: true, reset: vi.fn() };
}

function show(data: Versions, onRestore = vi.fn(() => Promise.resolve()), dirty = false) {
  render(
    <ScriptVersions
      versions={data}
      noun="flow"
      readOnly={false}
      dirty={dirty}
      restore={feedback()}
      onRestore={onRestore}
    />,
  );
  return onRestore;
}

const putBack = () => screen.getByRole("button", { name: /put back the flow from before pip/i });

describe("ScriptVersions", () => {
  it("is held, with the reason, when nothing of the owner's is on file", () => {
    show(versions({ version: null, unavailable: "no_owner_version" }, [REPAIR]));
    expect((putBack() as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Nothing of yours to put back yet.")).toBeTruthy();
  });

  it("is held when the owner's last version is already the script", () => {
    show(versions({ version: null, unavailable: "already_current" }, [OWN]));
    expect((putBack() as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("This is already your version.")).toBeTruthy();
  });

  it("waits for unsaved changes", () => {
    show(versions({ version: OWN, unavailable: null }), undefined, true);
    expect((putBack() as HTMLButtonElement).disabled).toBe(true);
  });

  it("restores the owner's own version, naming it, against the version the page read", async () => {
    const onRestore = show(versions({ version: OWN, unavailable: null }));
    fireEvent.click(putBack());
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/goes back to your version from 23 Nov/i)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Put it back" }));
    await waitFor(() => expect(onRestore).toHaveBeenCalledTimes(1));
    const [input] = onRestore.mock.calls[0] as unknown as [ScriptRestore];
    expect(input.versionId).toBeUndefined();
    expect(input.expectedVersionId).toBe("v-repair");
    expect(restoredToast(null, input)).toMatch(/^Put back your version from 23 Nov/);
  });

  it("lists every version with who and when, and restores an earlier one", async () => {
    const onRestore = show(versions({ version: OWN, unavailable: null }));
    fireEvent.click(screen.getByRole("button", { name: "Versions" }));
    const list = await screen.findByRole("dialog", { name: "Versions" });
    expect(within(list).getByText("Pip, fixing mistakes")).toBeTruthy();
    expect(within(list).getByText("Now")).toBeTruthy();
    fireEvent.click(within(list).getByRole("button", { name: "Put back" }));
    const confirm = await screen.findByRole("dialog", { name: "Put back this flow?" });
    fireEvent.click(within(confirm).getByRole("button", { name: "Put it back" }));
    await waitFor(() => expect(onRestore).toHaveBeenCalledTimes(1));
    const [input] = onRestore.mock.calls[0] as unknown as [ScriptRestore];
    expect(input.versionId).toBe("v-own");
  });
});
