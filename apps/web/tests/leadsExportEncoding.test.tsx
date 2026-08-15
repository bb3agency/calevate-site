/**
 * The CSV a client double-clicks arrives as UTF-8, and Excel has to be told so.
 *
 * Excel does not sniff encoding: a `.csv` with no byte-order mark is decoded in the
 * machine's legacy code page, so on a Telugu-first product every name in the file
 * renders as mojibake and the client's own data looks like we corrupted it. The mark is
 * added on the DOWNLOAD path only — `apps/api/crm/routes.py` keeps answering clean UTF-8
 * so a script reading `/v1/leads/export.csv` does not find a stray U+FEFF welded to its
 * first header cell. One danger, two renderings, exactly as `core/spreadsheet_safety.py`
 * splits the formula guard.
 *
 * Asserted on the BLOB the browser is handed rather than on the response, because the
 * response is the half that must NOT change and the blob is the half that must.
 */
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useExportLeads } from "@/lib/api/leads";
import type { Session } from "@/lib/api/client";

const CSV = 'Name,Phone\r\n"రవి కుమార్","\t+919876543210"\r\n';

const session: Session = { token: () => "dev:client:u1", orgSlug: "clinic" };

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("the CSV download", () => {
  let captured: Blob | null = null;

  beforeEach(() => {
    captured = null;
    vi.stubGlobal("fetch", vi.fn(async () => new Response(CSV, { status: 200 })));
    // jsdom implements neither, and the hook's whole job here is to call them.
    URL.createObjectURL = vi.fn((blob: Blob) => {
      captured = blob;
      return "blob:leads";
    });
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("prefixes a UTF-8 byte-order mark so Excel does not mangle a Telugu name", async () => {
    const { result } = renderHook(() => useExportLeads(session), { wrapper });
    result.current.mutate({});

    await waitFor(() => expect(captured).not.toBeNull());
    const blob = captured as unknown as Blob;
    // BYTES, not `blob.text()`. `text()` runs the spec's "UTF-8 decode", which STRIPS a
    // leading byte-order mark — so a character-level assertion here would be green
    // whether or not the mark was ever written, which is the wrong-reason pass this
    // whole slice is auditing for. Excel reads bytes; so does this test.
    const bytes = new Uint8Array(await blob.arrayBuffer());
    expect([bytes[0], bytes[1], bytes[2]]).toEqual([0xef, 0xbb, 0xbf]);
    // The mark is a PREFIX, not a replacement: the file itself is unchanged behind it.
    expect(new TextDecoder().decode(bytes.slice(3))).toBe(CSV);
    // And the type says the encoding too, for the consumers that do read it.
    expect(blob.type).toBe("text/csv;charset=utf-8");
  });
});
