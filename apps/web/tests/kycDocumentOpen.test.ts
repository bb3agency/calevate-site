import { afterEach, describe, expect, it, vi } from "vitest";

import { KycViewerBlockedError, openKycDocument } from "@/lib/api/kycReview";

import { problem, stubApi, stubDownloads } from "./harness";

/**
 * Opening a client's KYC file for review.
 *
 * The tab has to be opened inside the click, before the file is fetched: a `window.open`
 * after an `await` is no longer a user gesture and pop-up blockers drop it silently, which
 * left a reviewer pressing Open and seeing nothing.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000aa";
const DOC = "0192f0aa-7777-7000-8000-0000000000bb";
const PATH = `/v1/admin/tenants/${TENANT}/kyc/documents/${DOC}`;

function viewer() {
  return { opener: {} as unknown, location: { href: "" }, close: vi.fn() };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("openKycDocument", () => {
  it("opens the tab before the fetch, then points it at the file", async () => {
    stubDownloads();
    const calls = stubApi({ [PATH]: { pdf: true } });
    const tab = viewer();
    let fetchedBeforeOpen = -1;
    const open = vi.spyOn(window, "open").mockImplementation(() => {
      fetchedBeforeOpen = calls.length;
      return tab as unknown as Window;
    });

    const opening = openKycDocument(TENANT, DOC);
    expect(open).toHaveBeenCalledTimes(1);
    expect(fetchedBeforeOpen).toBe(0);
    expect(tab.opener).toBeNull();

    await opening;
    expect(calls.map((call) => call.path)).toEqual([PATH]);
    expect(tab.location.href).toBe("blob:test");
    expect(tab.close).not.toHaveBeenCalled();
  });

  it("says the browser blocked the tab, and fetches nothing", async () => {
    const calls = stubApi({ [PATH]: { pdf: true } });
    vi.spyOn(window, "open").mockReturnValue(null);

    await expect(openKycDocument(TENANT, DOC)).rejects.toBeInstanceOf(KycViewerBlockedError);
    expect(calls).toHaveLength(0);
  });

  it("closes the empty tab and throws when the file cannot be read", async () => {
    stubApi({ [PATH]: problem(404, { detail: "That file was deleted after review." }) });
    const tab = viewer();
    vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);

    await expect(openKycDocument(TENANT, DOC)).rejects.toThrow("That file was deleted after review.");
    expect(tab.close).toHaveBeenCalledTimes(1);
  });
});
