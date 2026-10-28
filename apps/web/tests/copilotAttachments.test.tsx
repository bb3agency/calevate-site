import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CopilotPanel } from "@/components/copilot/CopilotPanel";
import { API_BASE, type Session } from "@/lib/api/client";
import {
  ATTACHED_MARKER,
  MAX_FILE_BYTES,
  UPLOADS_UNAVAILABLE,
  kindOf,
  prepareFile,
  refusalFor,
  roomRefusal,
  splitMarker,
} from "@/lib/copilot/attachments";
import { OfficeTextError, officeText } from "@/lib/copilot/officeText";
import { useCopilotSurface, useCopilotSurfaceHolder } from "@/lib/copilot/registry";

import { expectNoA11yViolations } from "./a11y";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), back: vi.fn(), forward: vi.fn(), prefetch: vi.fn() }),
}));

/**
 * Attaching files to Pip (D-781): what the browser refuses, what it converts, what it
 * sends, and what the person sees. The upload is an `XMLHttpRequest` (`apiUpload`) and the
 * question a `fetch`; both are stubbed at the transport, so the real panel, hook and
 * conversion code run.
 */

const SESSION: Session = { orgSlug: "acme" };

// --- a tiny ZIP writer: stored entries only, enough to build an Office file in a test ----

function zip(entries: Record<string, string>): Uint8Array {
  const encoder = new TextEncoder();
  const locals: Uint8Array[] = [];
  const centrals: Uint8Array[] = [];
  let offset = 0;
  for (const [name, body] of Object.entries(entries)) {
    const nameBytes = encoder.encode(name);
    const data = encoder.encode(body);
    const local = new Uint8Array(30 + nameBytes.length + data.length);
    const lv = new DataView(local.buffer);
    lv.setUint32(0, 0x04034b50, true);
    lv.setUint16(8, 0, true);
    lv.setUint32(18, data.length, true);
    lv.setUint32(22, data.length, true);
    lv.setUint16(26, nameBytes.length, true);
    local.set(nameBytes, 30);
    local.set(data, 30 + nameBytes.length);
    const central = new Uint8Array(46 + nameBytes.length);
    const cv = new DataView(central.buffer);
    cv.setUint32(0, 0x02014b50, true);
    cv.setUint16(10, 0, true);
    cv.setUint32(20, data.length, true);
    cv.setUint32(24, data.length, true);
    cv.setUint16(28, nameBytes.length, true);
    cv.setUint32(42, offset, true);
    central.set(nameBytes, 46);
    locals.push(local);
    centrals.push(central);
    offset += local.length;
  }
  const directorySize = centrals.reduce((sum, part) => sum + part.length, 0);
  const end = new Uint8Array(22);
  const ev = new DataView(end.buffer);
  ev.setUint32(0, 0x06054b50, true);
  ev.setUint16(8, centrals.length, true);
  ev.setUint16(10, centrals.length, true);
  ev.setUint32(12, directorySize, true);
  ev.setUint32(16, offset, true);
  const parts = [...locals, ...centrals, end];
  const out = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
  let at = 0;
  for (const part of parts) {
    out.set(part, at);
    at += part.length;
  }
  return out;
}

const W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"';
const DOCX = {
  "[Content_Types].xml": "<Types/>",
  "word/document.xml": `<w:document ${W}><w:body><w:p><w:r><w:t>Price list</w:t></w:r></w:p><w:p><w:r><w:t>Tea</w:t><w:tab/><w:t>20</w:t></w:r></w:p></w:body></w:document>`,
};

describe("the browser's own checks", () => {
  it("refuses what the server would refuse, in a sentence that says what to do", () => {
    const file = (name: string, size = 10) => new File([new Uint8Array(size)], name);
    expect(refusalFor(file("budget.xlsm"))).toMatch(/macros/);
    expect(refusalFor(file("old.doc"))).toMatch(/older Office file/);
    expect(refusalFor(file("tool.exe"))).toMatch(/can't be attached/);
    expect(refusalFor(file("logo.svg"))).toMatch(/can't be attached/);
    expect(refusalFor(file("big.csv", MAX_FILE_BYTES + 1))).toMatch(/larger than 20 MB/);
    expect(refusalFor(file("notes.txt"))).toBeNull();
    expect(kindOf(file("photo.HEIC"))).toBe("picture");
    expect(kindOf(file("menu.docx"))).toBe("document");
  });

  it("reads the transcript's marker the server writes, and only that", () => {
    expect(splitMarker("[2 files attached]\nWhat is this?")).toEqual({ count: 2, text: "What is this?" });
    expect(splitMarker("[1 file attached]\nHi")).toEqual({ count: 1, text: "Hi" });
    expect(splitMarker("I typed [2 files attached] myself")).toEqual({
      count: 0,
      text: "I typed [2 files attached] myself",
    });
    expect(ATTACHED_MARKER.test("[3 files attached]")).toBe(true);
  });
});

describe("Office files become text on this device", () => {
  it("takes the paragraphs out of a Word file", async () => {
    expect(await officeText(zip(DOCX), "docx")).toBe("Price list\nTea\t20");
  });

  it("refuses a file carrying macros", async () => {
    const withMacros = zip({ ...DOCX, "word/vbaProject.bin": "x" });
    await expect(officeText(withMacros, "docx")).rejects.toMatchObject({ reason: "macros" });
  });

  it("refuses an XML part declaring a DOCTYPE, and a file that is not a ZIP", async () => {
    const doctype = zip({ ...DOCX, "word/document.xml": '<!DOCTYPE x [<!ENTITY a "b">]><x/>' });
    await expect(officeText(doctype, "docx")).rejects.toBeInstanceOf(OfficeTextError);
    await expect(officeText(new TextEncoder().encode("not a zip"), "docx")).rejects.toMatchObject({
      reason: "unreadable",
    });
  });

  it("turns a spreadsheet into CSV lines per sheet", async () => {
    const book = zip({
      "[Content_Types].xml": "<Types/>",
      "xl/workbook.xml":
        '<workbook xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Menu" r:id="rId1"/></sheets></workbook>',
      "xl/_rels/workbook.xml.rels": '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
      "xl/sharedStrings.xml": "<sst><si><t>Tea, hot</t></si></sst>",
      "xl/worksheets/sheet1.xml":
        '<worksheet><sheetData><row><c t="s"><v>0</v></c><c><v>20</v></c></row></sheetData></worksheet>',
    });
    expect(await officeText(book, "xlsx")).toBe('Sheet: Menu\n"Tea, hot",20');
  });

  it("sends a Word file as plain text, never as the original file", async () => {
    const prepared = await prepareFile(new File([zip(DOCX).slice()], "menu.docx"));
    expect(prepared.kind).toBe("document");
    expect(prepared.blob.type).toBe("text/plain");
    expect(await prepared.blob.text()).toBe("Price list\nTea\t20");
  });

  it("sends a Markdown file as plain text", async () => {
    const prepared = await prepareFile(new File(["# Guide\n- Tea → 20"], "guide.md"));
    expect(prepared.kind).toBe("document");
    expect(prepared.blob.type).toBe("text/plain");
    expect(await prepared.blob.text()).toBe("# Guide\n- Tea → 20");
  });
});

// --- the panel -------------------------------------------------------------------------

interface XhrCall {
  url: string;
  headers: Record<string, string>;
  body: Blob | FormData;
}
const xhrCalls: XhrCall[] = [];
let uploadCount = 0;

class StubXhr {
  status = 0;
  responseText = "";
  withCredentials = false;
  readonly upload = new EventTarget();
  private readonly events = new EventTarget();
  private readonly headers: Record<string, string> = {};
  private url = "";

  open(_method: string, url: string): void {
    this.url = url;
  }

  setRequestHeader(name: string, value: string): void {
    this.headers[name] = value;
  }

  getResponseHeader(name: string): string | null {
    return name.toLowerCase() === "content-type" ? "application/json" : null;
  }

  addEventListener(type: string, listener: EventListener): void {
    this.events.addEventListener(type, listener);
  }

  abort(): void {
    this.events.dispatchEvent(new Event("abort"));
  }

  send(body: Blob | FormData): void {
    xhrCalls.push({ url: this.url, headers: { ...this.headers }, body });
    uploadCount += 1;
    const id = `00000000-0000-7000-8000-00000000000${uploadCount}`;
    const name = decodeURIComponent(this.headers["X-Upload-Name"] ?? "file");
    const reply = () => {
      if (uploadRefusal !== null) {
        this.status = Number(uploadRefusal.status);
        this.responseText = JSON.stringify(uploadRefusal);
      } else {
        this.status = 201;
        this.responseText = JSON.stringify({
          id,
          file_name: name,
          kind: "document",
          content_type: "text/plain",
          size_bytes: 5,
          status: "ready",
        });
      }
      this.events.dispatchEvent(new Event("load"));
    };
    if (heldUploads !== null) heldUploads.push(reply);
    else queueMicrotask(reply);
  }
}

/** A problem every upload is answered with instead of 201, when a test sets it. */
let uploadRefusal: Record<string, unknown> | null = null;
/** Replies a test releases itself, when it sets this; otherwise uploads answer at once. */
let heldUploads: (() => void)[] | null = null;

const askBodies: Record<string, unknown>[] = [];
let uploadsOffered = true;
const deletes: string[] = [];

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).replace(API_BASE, "");
      if (path.startsWith("/v1/copilot/uploads/") && init?.method === "DELETE") {
        deletes.push(path);
        return new Response(null, { status: 204 });
      }
      if (path.startsWith("/v1/copilot/ask")) {
        askBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
        const encoder = new TextEncoder();
        return new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              controller.enqueue(encoder.encode('event: text\ndata: {"delta":"Tea is 20."}\n\n'));
              controller.enqueue(encoder.encode('event: done\ndata: {"disclosure":null,"metered":true}\n\n'));
              controller.close();
            },
          }),
          { status: 200, headers: { "content-type": "text/event-stream" } },
        );
      }
      if (path.startsWith("/v1/copilot/conversation")) {
        return new Response(JSON.stringify({ turns: [], has_more: false, answering: false, uploads_available: uploadsOffered }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      throw new Error(`unexpected request: ${path}`);
    }),
  );
}

function Screen() {
  useCopilotSurface({ route: "/t", title: "A test screen", realm: "client", fields: [], apply: () => {} });
  return null;
}

function PanelMount() {
  const holder = useCopilotSurfaceHolder();
  if (holder === null) return null;
  return <CopilotPanel session={SESSION} holder={holder} realm="client" labelledBy="t-panel" />;
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <h2 id="t-panel">Pip</h2>
      <Screen />
      <PanelMount />
    </QueryClientProvider>,
  );
}

function fileInput(): HTMLInputElement {
  const input = document.querySelector<HTMLInputElement>('input[type="file"]');
  if (input === null) throw new Error("no file input");
  return input;
}

function attachButton(): HTMLElement {
  return screen.getByRole("button", { name: "Attach files" });
}

async function attach(...files: File[]) {
  // The paperclip is offered once the conversation read says files can be attached.
  await waitFor(() => expect(attachButton().getAttribute("aria-disabled")).toBeNull());
  await act(async () => {
    fireEvent.change(fileInput(), { target: { files } });
  });
}

const text = (name: string) => new File(["Tea 20"], name, { type: "text/plain" });

beforeEach(() => {
  xhrCalls.length = 0;
  askBodies.length = 0;
  deletes.length = 0;
  uploadCount = 0;
  uploadsOffered = true;
  uploadRefusal = null;
  heldUploads = null;
  window.localStorage.clear();
  vi.stubGlobal("XMLHttpRequest", StubXhr);
  stubFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("attaching files in Pip's panel", () => {
  it("UPLOADS THE CONVERTED FILE with its name in a header, and sends its id with the question", async () => {
    renderPanel();
    await attach(text("prices.txt"));
    expect(await screen.findByText("Attached")).toBeTruthy();

    expect(xhrCalls).toHaveLength(1);
    expect(xhrCalls[0].url).toBe(`${API_BASE}/v1/copilot/uploads`);
    expect(xhrCalls[0].headers["X-Upload-Name"]).toBe("prices.txt");
    expect(xhrCalls[0].body).toBeInstanceOf(Blob);
    expect((xhrCalls[0].body as Blob).type).toBe("text/plain");

    fireEvent.change(screen.getByLabelText("Your question about this screen"), {
      target: { value: "what does tea cost?" },
    });
    await act(async () => {
      fireEvent.submit(screen.getByRole("button", { name: "Ask" }).closest("form")!);
    });
    await waitFor(() => expect(askBodies).toHaveLength(1));
    expect(askBodies[0].attachments).toEqual(["00000000-0000-7000-8000-000000000001"]);
    // The tray empties, and the bubble shows the file the question carried.
    expect(screen.queryByRole("list", { name: "Attached files" })).toBeNull();
    expect(
      screen.getByRole("list", { name: "Files sent with this question" }).textContent,
    ).toContain("prices.txt");
  });

  it("SHOWS THE PLAIN NOTICE ONCE, naming no provider", async () => {
    renderPanel();
    await attach(text("a.txt"));
    const notice = await screen.findByRole("note");
    expect(notice.textContent).toContain("AI provider sees the whole file");
    expect(notice.textContent).not.toMatch(/Google|Gemini|Azure|OpenAI|Microsoft/);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Got it" }));
    });
    expect(screen.queryByRole("note")).toBeNull();
    await attach(text("b.txt"));
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("TAKES A PASTED FILE, and leaves pasted text to the box", async () => {
    renderPanel();
    await waitFor(() => expect(attachButton().getAttribute("aria-disabled")).toBeNull());
    const box = screen.getByLabelText("Your question about this screen");
    await act(async () => {
      fireEvent.paste(box, { clipboardData: { files: [text("pasted.txt")] } });
    });
    expect(await screen.findByText("pasted.txt")).toBeTruthy();
    expect(xhrCalls).toHaveLength(1);
  });

  it("REMOVES a file from the tray and from the server", async () => {
    renderPanel();
    await attach(text("gone.txt"));
    await screen.findByText("Attached");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Remove gone.txt" }));
    });
    expect(screen.queryByText("gone.txt")).toBeNull();
    await waitFor(() => expect(deletes).toEqual(["/v1/copilot/uploads/00000000-0000-7000-8000-000000000001"]));
  });

  it("HOLDS THE LIMITS: two pictures and five files a message, said beside the tray", async () => {
    renderPanel();
    const picture = (name: string) => new File([new Uint8Array([0xff, 0xd8, 0xff])], name, { type: "image/png" });
    await attach(picture("1.png"), picture("2.png"), picture("3.png"));
    expect((await screen.findByRole("alert")).textContent).toContain("up to 2 pictures");
    expect(screen.queryByText("3.png")).toBeNull();

    await attach(text("a.txt"), text("b.txt"), text("c.txt"), text("d.txt"));
    expect((await screen.findByRole("alert")).textContent).toContain("up to 5 files");
    expect(screen.queryByText("d.txt")).toBeNull();
  });

  it("REFUSES what it cannot send, beside the file, with Remove and no pointless Retry", async () => {
    renderPanel();
    await attach(new File(["x"], "macro.xlsm"));
    expect(await screen.findByText(/has macros/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Try macro.xlsm again" })).toBeNull();
    expect(screen.getByRole("button", { name: "Remove macro.xlsm" })).toBeTruthy();
    expect(xhrCalls).toHaveLength(0);
  });

  it("is accessible with a file in the tray", async () => {
    const { container } = renderPanel();
    await attach(text("a.txt"));
    await screen.findByText("Attached");
    await expectNoA11yViolations(container, "Pip panel with an attached file");
  });
});

describe("when files can't be attached", () => {
  it("DISABLES THE PAPERCLIP with a plain sentence, and no file can be picked, dropped or pasted", async () => {
    uploadsOffered = false;
    const picker = vi.spyOn(HTMLInputElement.prototype, "click");
    renderPanel();
    const reason = await screen.findByText(UPLOADS_UNAVAILABLE);
    expect(reason.textContent).toBe("Attaching files isn't available yet. You can still ask Pip in words.");
    const button = attachButton();
    expect(button.getAttribute("aria-disabled")).toBe("true");
    expect(button.getAttribute("aria-describedby")).toBe(reason.id);
    expect(fileInput().disabled).toBe(true);
    await act(async () => {
      fireEvent.click(button);
    });
    expect(picker).not.toHaveBeenCalled();
    picker.mockRestore();

    await act(async () => {
      fireEvent.paste(screen.getByLabelText("Your question about this screen"), {
        clipboardData: { files: [text("pasted.txt")] },
      });
    });
    expect((await screen.findByRole("alert")).textContent).toBe(UPLOADS_UNAVAILABLE);
    expect(screen.queryByText("pasted.txt")).toBeNull();
    expect(xhrCalls).toHaveLength(0);
  });

  it("SAYS THE SAME SENTENCE when the server refuses one as unavailable, with no Retry", async () => {
    uploadRefusal = {
      status: 503,
      type: "https://calevate.tech/problems/copilot_uploads_unavailable",
      title: "Files can't be attached right now",
      detail: "File storage for Pip isn't available at the moment.",
      kind: "dependency",
    };
    renderPanel();
    await attach(text("late.txt"));
    const item = (await screen.findByText("late.txt")).closest("li")!;
    await waitFor(() => expect(item.textContent).toContain(UPLOADS_UNAVAILABLE));
    expect(item.textContent).not.toMatch(/connection|No reply/i);
    expect(screen.queryByRole("button", { name: "Try late.txt again" })).toBeNull();
    // What the refusal taught holds for the panel: the paperclip is withdrawn too.
    expect(attachButton().getAttribute("aria-disabled")).toBe("true");
  });
});

describe("refusals the browser makes before a body is sent", () => {
  it("streams at most two files at once; the rest wait their turn", async () => {
    heldUploads = [];
    renderPanel();
    await attach(text("a.txt"), text("b.txt"), text("c.txt"));
    await screen.findByText("Waiting to send…");
    expect(xhrCalls).toHaveLength(2);
    await act(async () => {
      heldUploads!.shift()!();
    });
    await waitFor(() => expect(xhrCalls).toHaveLength(3));
    await act(async () => {
      for (const reply of heldUploads!.splice(0)) reply();
    });
    await waitFor(() => expect(screen.getAllByText("Attached")).toHaveLength(3));
  });

  it("refuses a file that would take the message past its total or its pictures-and-PDFs bytes", () => {
    const mb = 1024 * 1024;
    expect(roomRefusal("a.txt", { total: 10 * mb, inline: 0 }, [{ total: 40 * mb, inline: 0 }])).toBeNull();
    expect(roomRefusal("a.txt", { total: 11 * mb, inline: 0 }, [{ total: 40 * mb, inline: 0 }])).toMatch(
      /add up to 50 MB/,
    );
    expect(roomRefusal("b.pdf", { total: 8 * mb, inline: 7 * mb }, [{ total: 8 * mb, inline: 8 * mb }])).toMatch(
      /pictures and PDFs on one message can add up to 14 MB/,
    );
    // A document adds no inline bytes, so a message full of pictures still takes it.
    expect(roomRefusal("c.txt", { total: mb, inline: 0 }, [{ total: 14 * mb, inline: 14 * mb }])).toBeNull();
  });
});

// --- PDFs (D-781) ---------------------------------------------------------------------------

describe("a PDF", () => {
  it("is sent as it is, with the text the browser found in it tied to it", async () => {
    vi.resetModules();
    vi.doMock("@/lib/copilot/pdfText", () => ({ pdfText: vi.fn(async () => "Page 1\nTea 20") }));
    const { prepareFile: prepare } = await import("@/lib/copilot/attachments");
    const bytes = new TextEncoder().encode("%PDF-1.7\n...");
    const prepared = await prepare(new File([bytes], "menu.pdf", { type: "application/pdf" }));
    expect(prepared.kind).toBe("pdf");
    expect(prepared.blob.type).toBe("application/pdf");
    expect(Array.from(new Uint8Array(await prepared.blob.arrayBuffer()))).toEqual(Array.from(bytes));
    expect(await prepared.text?.text()).toBe("Page 1\nTea 20");
    vi.doUnmock("@/lib/copilot/pdfText");
  });

  it("carries no text when the PDF has none (a scan), and the server then refuses if Gemini cannot read it", async () => {
    vi.resetModules();
    vi.doMock("@/lib/copilot/pdfText", () => ({ pdfText: vi.fn(async () => "  ") }));
    const { prepareFile: prepare } = await import("@/lib/copilot/attachments");
    const prepared = await prepare(new File([new TextEncoder().encode("%PDF-1.4")], "scan.pdf"));
    expect(prepared.text).toBeNull();
    vi.doUnmock("@/lib/copilot/pdfText");
  });

  it("refuses a file named .pdf that is not one, and one over 14 MB", async () => {
    await expect(prepareFile(new File(["hello"], "fake.pdf"))).rejects.toThrow(/isn't a PDF/);
    expect(refusalFor(new File([new Uint8Array(14 * 1024 * 1024 + 1)], "big.pdf"))).toMatch(/14 MB/);
    expect(kindOf(new File(["%PDF-"], "a.pdf"))).toBe("pdf");
  });

  it("uploads the text as a sibling naming the PDF", async () => {
    vi.resetModules();
    vi.doMock("@/lib/copilot/pdfText", () => ({ pdfText: vi.fn(async () => "Tea 20") }));
    const { prepareFile: prepare, uploadPrepared } = await import("@/lib/copilot/attachments");
    const prepared = await prepare(new File([new TextEncoder().encode("%PDF-1.7")], "menu.pdf"));
    await uploadPrepared(SESSION, "client", prepared);
    expect(xhrCalls).toHaveLength(2);
    expect((xhrCalls[0].body as Blob).type).toBe("application/pdf");
    expect(xhrCalls[1].headers["X-Upload-Text-Of"]).toBe("00000000-0000-7000-8000-000000000001");
    expect(xhrCalls[1].headers["X-Upload-Name"]).toBe("menu.pdf.txt");
    expect((xhrCalls[1].body as Blob).type).toBe("text/plain");
    vi.doUnmock("@/lib/copilot/pdfText");
  });
});

describe("the pdf.js extraction itself", () => {
  it("is hardened: no XFA, text only, in its own worker, and gives up quietly", async () => {
    vi.resetModules();
    const getDocument = vi.fn(() => ({
      promise: Promise.resolve({
        numPages: 2,
        getPage: async (n: number) => ({
          getTextContent: async () => ({
            items: [{ str: `Line ${n}`, hasEOL: true }, { str: "end", hasEOL: false }],
          }),
          cleanup: () => {},
        }),
      }),
      destroy: async () => {},
    }));
    const worker = { workerSrc: "" };
    vi.doMock("pdfjs-dist", () => ({ getDocument, GlobalWorkerOptions: worker }));
    const { pdfText } = await import("@/lib/copilot/pdfText");
    const text = await pdfText(new TextEncoder().encode("%PDF-1.7"));
    expect(text).toBe("Page 1\nLine 1\nend\n\nPage 2\nLine 2\nend");
    const options = (getDocument.mock.calls[0] as unknown as [Record<string, unknown>])[0];
    expect(options).not.toHaveProperty("isEvalSupported");
    expect(options.enableXfa).toBe(false);
    expect(worker.workerSrc).toMatch(/pdf\.worker\.min\.mjs/);

    getDocument.mockReturnValueOnce({
      promise: Promise.reject(new Error("encrypted")),
      destroy: async () => {},
    });
    expect(await pdfText(new TextEncoder().encode("%PDF-1.7"))).toBe("");
    vi.doUnmock("pdfjs-dist");
  });
});
