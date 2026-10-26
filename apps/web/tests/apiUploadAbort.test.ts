import { afterEach, describe, expect, it, vi } from "vitest";

import { apiUpload } from "@/lib/api/client";

/** An upload whose caller has already cancelled is never sent. */

describe("apiUpload with a cancelled signal", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("rejects without opening or sending the request", async () => {
    const send = vi.fn();
    const open = vi.fn();
    class StubXhr {
      upload = { addEventListener: vi.fn() };
      withCredentials = false;
      open = open;
      send = send;
      setRequestHeader = vi.fn();
      addEventListener = vi.fn();
      abort = vi.fn();
      getResponseHeader = vi.fn();
    }
    vi.stubGlobal("XMLHttpRequest", StubXhr);

    const controller = new AbortController();
    controller.abort(new DOMException("cancelled", "AbortError"));

    await expect(
      apiUpload({ orgSlug: "acme", token: "t" }, "/v1/kb/uploads", new FormData(), {
        signal: controller.signal,
      }),
    ).rejects.toBeDefined();
    expect(open).not.toHaveBeenCalled();
    expect(send).not.toHaveBeenCalled();
  });
});
