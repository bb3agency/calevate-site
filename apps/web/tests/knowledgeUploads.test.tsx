import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import KnowledgePage from "@/app/c/[slug]/knowledge/page";
import type { Me } from "@/lib/api/client";
import type { KbUpload } from "@/lib/api/kb";

import { problem, renderClientPage, stillLoading, type Routes } from "./harness";

/**
 * DOCUMENTS, PHOTOGRAPHS AND LINKS on the client's knowledge screen (D-534) — the states,
 * not the happy path.
 *
 * The founder's gap was "where is a client able to upload files or docs or links?", and
 * the answer is a control; but a control is the easy half. What this file is about is
 * everything the screen has to say WHILE and AFTER a file is sent, because that is where
 * a knowledge screen misleads people:
 *
 *  - a refusal the client can act on (too large, a kind we cannot read, an address the
 *    SSRF gate refused) rather than a form that goes quiet;
 *  - a state in the client's words rather than the machinery's — a shop owner has one
 *    question, "is my agent using my price list yet", and `conversion_unavailable` is not
 *    an answer to it;
 *  - text a MODEL read off a photograph never reaching a phone call until a person has
 *    read it, because a vision model returns a fluent transcription of a price it
 *    misread as confidently as one it got right (`apps/workers/document_ocr.py`);
 *  - and a row that moves on its own, so nobody sends the same menu three times because
 *    the screen looked frozen.
 *
 * ## The `XMLHttpRequest` stub, and why there is one
 *
 * `harness.stubApi` replaces `fetch`, which is every request this console makes except
 * one: the multipart upload goes through `apiUpload`, an `XMLHttpRequest`, because `fetch`
 * still cannot report how many bytes have left the device (see `lib/api/client.ts`). So
 * the seam for that one request is XHR, stubbed here in the same spirit — the real
 * transport runs, and only the network is replaced, so a test that passes has exercised
 * the identity headers, the RFC-9457 parsing and the progress plumbing.
 */

const AGENT_ID = "0192f0aa-5555-7000-8000-000000000001";
const UPLOAD_ID = "0192f0aa-7777-7000-8000-000000000001";
const SOURCE_ID = "0192f0aa-8888-7000-8000-000000000001";

const ME: Me = {
  impersonating: false,
  permissions: ["agents:read", "kb:write"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

const STAFF: Me = { ...ME, role: "staff", permissions: ["agents:read"] };
const AGENT = { id: AGENT_ID, name: "Front desk", status: "live" };

function upload(over: Partial<KbUpload> = {}): KbUpload {
  return {
    id: UPLOAD_ID,
    source_id: SOURCE_ID,
    agent_id: AGENT_ID,
    name: "Price list.pdf",
    source_kind: "pdf",
    ingest_status: "processed",
    ingest_detail: null,
    review_state: "approved",
    is_live: true,
    version: 1,
    filename: "Price list.pdf",
    byte_size: 284_912,
    source_url: null,
    text_provenance: null,
    change_detected_at: null,
    ...over,
  };
}

async function renderKnowledge(uploads: KbUpload[] | ReturnType<typeof problem>, over: Routes = {}) {
  return await renderClientPage(<KnowledgePage />, {
    "/v1/me": ME,
    "/v1/agents": [AGENT],
    "/v1/kb/sources": [],
    "/v1/kb/staff-curation": { staff_may_curate_knowledge: false },
    "/v1/kb/uploads": uploads,
    ...over,
  });
}

/** One XHR the screen sent, as the network saw it. */
interface XhrCall {
  method: string;
  url: string;
  headers: Record<string, string>;
  form: FormData | null;
}

/** What the stubbed transport should answer with, and how far it got before it did. */
interface XhrAnswer {
  status: number;
  body: unknown;
  contentType?: string;
  /** Bytes reported through `upload.onprogress` before the answer lands. */
  progress?: { loaded: number; total: number };
  /**
   * Hold the request open after the progress event, until `finishUpload()`.
   *
   * A real upload is a period of TIME during which the screen has to say something, and a
   * stub that answers in the same microtask as it reports progress skips exactly the
   * interval the progress bar exists for — a test written against it would pass while the
   * bar never painted.
   */
  hold?: boolean;
}

const xhrCalls: XhrCall[] = [];
let xhrAnswer: XhrAnswer = { status: 201, body: upload() };
/** Completes a held request. Set by the stub when `hold` is on. */
let finishUpload: () => void = () => {};

/**
 * A fake `XMLHttpRequest` — the multipart seam, matching the parts `apiUpload` uses.
 *
 * It answers ASYNCHRONOUSLY (a queued microtask), because a synchronous `load` inside
 * `send()` resolves the mutation before React has painted the pending state, and a test
 * written against that would pass while a real upload showed nothing at all.
 */
class StubXhr {
  status = 0;
  responseText = "";
  withCredentials = false;
  readonly upload = new EventTarget();
  private readonly events = new EventTarget();
  private readonly headers: Record<string, string> = {};
  private method = "";
  private url = "";

  open(method: string, url: string): void {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name: string, value: string): void {
    this.headers[name] = value;
  }

  getResponseHeader(name: string): string | null {
    return name.toLowerCase() === "content-type"
      ? (xhrAnswer.contentType ??
          (xhrAnswer.status >= 400 ? "application/problem+json" : "application/json"))
      : null;
  }

  addEventListener(type: string, listener: EventListener): void {
    this.events.addEventListener(type, listener);
  }

  abort(): void {
    this.events.dispatchEvent(new Event("abort"));
  }

  send(form: FormData): void {
    xhrCalls.push({ method: this.method, url: this.url, headers: { ...this.headers }, form });
    const complete = () => {
      this.status = xhrAnswer.status;
      this.responseText = JSON.stringify(xhrAnswer.body);
      this.events.dispatchEvent(new Event("load"));
    };
    finishUpload = complete;
    queueMicrotask(() => {
      if (xhrAnswer.progress) {
        this.upload.dispatchEvent(
          new ProgressEvent("progress", {
            lengthComputable: true,
            loaded: xhrAnswer.progress.loaded,
            total: xhrAnswer.progress.total,
          }),
        );
      }
      if (!xhrAnswer.hold) complete();
    });
  }
}

beforeEach(() => {
  xhrCalls.length = 0;
  xhrAnswer = { status: 201, body: upload() };
  vi.stubGlobal("XMLHttpRequest", StubXhr);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/**
 * Wait until the panel knows which agent it is teaching.
 *
 * The upload control is deliberately dead until `/v1/me` and `/v1/agents` have answered —
 * a file chosen before either would be posted with no agent, or by somebody the route
 * refuses. So every test that operates the control waits for the same thing a client
 * waits for.
 */
async function ready(): Promise<void> {
  await screen.findByText(/Goes to Front desk/);
}

/** The drop zone's real control — found the way assistive technology finds it. */
function filePicker(): HTMLInputElement {
  return screen.getByLabelText(/choose a file, or drag one here/i) as HTMLInputElement;
}

/** Choose a file, the way the browser hands one over. */
function choose(name: string, bytes = 1024): void {
  const file = new File(["x".repeat(bytes)], name, { type: "application/pdf" });
  fireEvent.change(filePicker(), { target: { files: [file] } });
}

describe("the control the founder could not find", () => {
  it("offers a real file input a keyboard can reach, behind the drop zone", async () => {
    // A `<div onDrop>` with a click handler looks identical and is unreachable without a
    // pointer. The input is `sr-only` — visually hidden and still focusable — so it keeps
    // its place in the tab order and opens the picker on Enter.
    await renderKnowledge([]);
    await ready();

    const input = filePicker();
    expect(input.type).toBe("file");
    expect(input.disabled).toBe(false);
    // `sr-only`, never `hidden`/`display:none`: those remove it from the tab order.
    expect(input.hasAttribute("hidden")).toBe(false);
    expect(input.className).toContain("sr-only");
  });

  it("says which kinds it takes BEFORE a client picks one they cannot use", async () => {
    const { container } = await renderKnowledge([]);

    const text = container.textContent ?? "";
    expect(text).toContain("PDFs, Word documents, spreadsheets, plain text");
    expect(text).toContain("20 MB");
    // The picker's own filter carries the same list, so the file browser greys out a
    // `.doc` rather than letting it be chosen and refused.
    expect(filePicker().accept).toContain(".docx");
    expect(filePicker().accept).toContain(".pdf");
  });

  it("sends the file as multipart, to the agent the form is filed against", async () => {
    await renderKnowledge([]);
    await ready();
    choose("prices.pdf");

    await waitFor(() => expect(xhrCalls.length).toBe(1));
    const sent = xhrCalls[0];
    expect(sent.method).toBe("POST");
    expect(sent.url).toContain("/v1/kb/uploads");
    expect(sent.form?.get("agent_id")).toBe(AGENT_ID);
    expect((sent.form?.get("file") as File).name).toBe("prices.pdf");
    // The identity every other request carries — the point of `apiUpload` living in the
    // transport module rather than beside the screen.
    expect(sent.headers["X-Org-Slug"]).toBe("acme");
    // The browser must write `Content-Type` itself: only it knows the multipart boundary.
    expect(sent.headers["Content-Type"]).toBeUndefined();
  });

  it("shows how much of a big file has actually left the phone", async () => {
    // 20 MB over a phone uplink is minutes of apparent silence, and a form that looks
    // frozen gets pressed twice — which here means the same price list reviewed twice.
    xhrAnswer = {
      status: 201,
      body: upload(),
      progress: { loaded: 5_000_000, total: 20_000_000 },
      hold: true,
    };
    await renderKnowledge([]);
    await ready();
    choose("menu.pdf", 2048);

    const bar = await screen.findByRole("progressbar", { name: /sending your file/i });
    await waitFor(() => expect(bar.getAttribute("aria-valuenow")).toBe("25"));
    expect(screen.getByText(/Sending menu\.pdf/)).toBeTruthy();

    // And it goes away when the request settles: a bar left on screen after the answer
    // has landed is the screen saying the file is still going.
    finishUpload();
    await waitFor(() => expect(screen.queryByRole("progressbar")).toBeNull());
  });

  it("refuses a file over the ceiling in the server's own words", async () => {
    xhrAnswer = {
      status: 413,
      body: {
        type: "urn:calevate:validation/kb_upload_too_large",
        title: "That file is too large",
        detail: "We can take files up to 20 MB and this one is 34 MB.",
        remediation: "Split it into smaller documents, or send the price list on its own.",
        kind: "validation",
      },
    };
    const { container } = await renderKnowledge([]);
    await ready();
    choose("huge.pdf");

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(container.textContent).toContain("We can take files up to 20 MB and this one is 34 MB.");
    expect(container.textContent).toContain("Split it into smaller documents");
    // The machine code never reaches the screen, and neither does a bar left at 100%
    // under a refusal — which would read as "it arrived".
    expect(container.textContent).not.toContain("kb_upload_too_large");
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("refuses a kind nothing can read, and passes on the fix the server named", async () => {
    xhrAnswer = {
      status: 422,
      body: {
        type: "urn:calevate:validation/kb_upload_kind_unsupported",
        title: "We cannot read that kind of file",
        detail: "We cannot read a .doc file.",
        remediation: "Open it and choose Save as, then pick .docx.",
        kind: "validation",
      },
    };
    const { container } = await renderKnowledge([]);
    await ready();
    choose("old.doc");

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(container.textContent).toContain("Open it and choose Save as, then pick .docx.");
    expect(container.textContent).not.toContain("kb_upload_kind_unsupported");
  });

  it("refuses an address the gate would not fetch, without blaming the client's typing", async () => {
    const { container } = await renderKnowledge([], {
      "POST /v1/kb/links": problem(422, {
        type: "urn:calevate:validation/kb_link_refused",
        title: "We cannot read that address",
        detail: "That address is not one we can reach from here.",
        remediation: "Give us a page on your own website that anyone can open.",
      }),
    });

    await ready();
    fireEvent.change(screen.getByLabelText(/address of a page/i), {
      target: { value: "http://169.254.169.254/latest" },
    });
    fireEvent.click(screen.getByRole("button", { name: /add page/i }));

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(container.textContent).toContain("Give us a page on your own website");
    expect(container.textContent).not.toContain("kb_link_refused");
  });

  it("answers an empty address in our words rather than the browser's", async () => {
    await renderKnowledge([]);
    await ready();
    fireEvent.click(screen.getByRole("button", { name: /add page/i }));

    expect(await screen.findByText(/give us the full web address/i)).toBeTruthy();
  });
});

describe("what each state means to the person who sent the file", () => {
  it("never prints the machinery's own word for a state", async () => {
    const { container } = await renderKnowledge([
      upload({ id: "u1", ingest_status: "processing", review_state: "approved", is_live: false }),
      upload({
        id: "u2",
        name: "Old leaflet.docx",
        source_kind: "docx",
        ingest_status: "conversion_unavailable",
        review_state: "pending_approval",
        is_live: false,
      }),
    ]);

    await screen.findByText("Old leaflet.docx");
    const text = container.textContent ?? "";
    for (const wire of [
      "conversion_unavailable",
      "ingest_status",
      "pending_approval",
      "text_provenance",
      "processing",
    ]) {
      expect(text).not.toContain(wire);
    }
  });

  it("says a live document is what the agent is using now", async () => {
    const { container } = await renderKnowledge([upload({ is_live: true })]);

    await screen.findByText("Price list.pdf");
    expect(container.textContent).toContain("In use");
    expect(container.textContent).toContain("Your agent is using this now");
  });

  it("says we are reading a file that has just arrived, and how long that takes", async () => {
    const { container } = await renderKnowledge([
      upload({ ingest_status: "received", review_state: "pending_approval", is_live: false }),
    ]);

    await screen.findByText("Price list.pdf");
    expect(container.textContent).toContain("We are reading your file");
    expect(container.textContent).toContain("usually takes a minute");
  });

  it("shows the specific reason a conversion failed, and offers no confirmation for it", async () => {
    // A document we could not read is NOT "waiting for review" — nobody is going to
    // review it, and telling a client to wait for us is how a broken upload sits
    // untouched for a week. `ingest_detail` is written for a client, so it is shown.
    const { container } = await renderKnowledge([
      upload({
        name: "Scan.pdf",
        ingest_status: "conversion_failed",
        ingest_detail: "There was no text in that file, only pictures. Send a photo of each page instead.",
        review_state: "pending_approval",
        is_live: false,
      }),
    ]);

    await screen.findByText("Scan.pdf");
    expect(container.textContent).toContain("Could not be read");
    expect(container.textContent).toContain("only pictures");
    expect(container.textContent).not.toContain("Waiting for review");
    expect(screen.queryByRole("button", { name: /read it and confirm/i })).toBeNull();
  });

  it("does not report an empty list when it could not read one", async () => {
    // The same sentence the pasted-text panel is guarded against: "nothing sent yet" over
    // a request that never answered tells a client the file they sent this morning was
    // never received, and they send it again.
    const { container } = await renderKnowledge(
      problem(503, { title: "Service unavailable", detail: "We could not read your documents." }),
    );

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(container.textContent).not.toContain("Nothing sent yet");
  });
});

describe("text a machine read is confirmed by a person before a caller hears it", () => {
  const photo = upload({
    name: "Rates board",
    source_kind: "image",
    filename: "rates.jpg",
    ingest_status: "received",
    text_provenance: "ocr",
    review_state: "pending_approval",
    is_live: false,
  });

  const CHUNKS = [{ idx: 0, content: "Haircut ₹280. Shave ₹120.", gloss: null }];

  it("asks the client to read what was read off their photo, and labels whose reading it is", async () => {
    const { container } = await renderKnowledge([photo], {
      [`/v1/kb/sources/${SOURCE_ID}/preview`]: CHUNKS,
    });

    await screen.findByText("Rates board");
    expect(container.textContent).toContain("Check what we read");
    fireEvent.click(screen.getByRole("button", { name: /read it and confirm/i }));

    expect(await screen.findByText(/Haircut ₹280/)).toBeTruthy();
    // The label is the feature, not decoration: a fluent transcription that says ₹260
    // where the board says ₹280 looks exactly like a correct one.
    expect(container.textContent).toContain("what our computer read off your photo");
    expect(container.textContent).toContain("check the numbers");
  });

  it("publishes it only when the client says the reading is right", async () => {
    const { calls } = await renderKnowledge([photo], {
      [`/v1/kb/sources/${SOURCE_ID}/preview`]: CHUNKS,
      [`POST /v1/kb/uploads/${UPLOAD_ID}/confirm`]: upload({
        ingest_status: "processing",
        review_state: "approved",
        text_provenance: "ocr",
        is_live: false,
      }),
    });

    await screen.findByText("Rates board");
    fireEvent.click(screen.getByRole("button", { name: /read it and confirm/i }));
    await screen.findByText(/Haircut ₹280/);
    fireEvent.click(screen.getByRole("button", { name: /yes, this is right/i }));

    await waitFor(() =>
      expect(
        calls.some((c) => c.method === "POST" && c.path === `/v1/kb/uploads/${UPLOAD_ID}/confirm`),
      ).toBe(true),
    );
  });

  it("lets the client throw a bad reading away, saying what that does", async () => {
    const { calls } = await renderKnowledge([photo], {
      [`/v1/kb/sources/${SOURCE_ID}/preview`]: CHUNKS,
      [`DELETE /v1/kb/uploads/${UPLOAD_ID}`]: null,
    });

    await screen.findByText("Rates board");
    fireEvent.click(screen.getByRole("button", { name: /read it and confirm/i }));
    await screen.findByText(/Haircut ₹280/);
    fireEvent.click(screen.getByRole("button", { name: /throw this away/i }));

    // The consequence, before the irreversible act (`components/confirmDialog.tsx`).
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("your agent never sees it");
    fireEvent.click(screen.getByRole("button", { name: /throw it away/i }));

    await waitFor(() =>
      expect(
        calls.some((c) => c.method === "DELETE" && c.path === `/v1/kb/uploads/${UPLOAD_ID}`),
      ).toBe(true),
    );
  });

  it("does not offer a confirmation on text nobody has extracted yet", async () => {
    // `received` means two opposite things and only the provenance separates them: "we
    // have not started" and "we have finished and are waiting for you". Confirming the
    // first would 409 `kb_upload_not_ready` against a document nobody has read.
    await renderKnowledge([
      upload({ ingest_status: "received", text_provenance: null, review_state: "pending_approval", is_live: false }),
    ]);

    await screen.findByText("Price list.pdf");
    expect(screen.queryByRole("button", { name: /read it and confirm/i })).toBeNull();
  });
});

describe("a row that moves on its own", () => {
  it("says where an item is while it is still moving", async () => {
    // The row's own watch is left in flight (`stillLoading`), which is what the first few
    // seconds after an upload look like: the list's answer is all the screen has.
    const { container } = await renderKnowledge(
      [upload({ ingest_status: "processing", review_state: "approved", is_live: false })],
      { [`/v1/kb/uploads/${UPLOAD_ID}`]: stillLoading() },
    );

    await screen.findByText("Price list.pdf");
    expect(container.textContent).toContain("Going to your agent");
    expect(container.textContent).toContain("Your agent is being given this now");
  });

  it("follows one item from being processed to in use, without re-reading the list", async () => {
    const { calls, container } = await renderKnowledge(
      [upload({ ingest_status: "processing", review_state: "approved", is_live: false })],
      {
        [`/v1/kb/uploads/${UPLOAD_ID}`]: upload({
          ingest_status: "processed",
          review_state: "approved",
          is_live: true,
        }),
      },
    );

    await screen.findByText("Price list.pdf");
    await waitFor(() => expect(container.textContent).toContain("Your agent is using this now"));
    // ONE item was watched, not the list. A whole-list poll on a four-second timer to see
    // one row change is the shape this deliberately is not.
    expect(calls.filter((c) => c.path === "/v1/kb/uploads").length).toBe(1);
  });

  it("asks nothing at all about a row that has stopped moving", async () => {
    const { calls } = await renderKnowledge([upload({ is_live: true })]);

    await screen.findByText("Price list.pdf");
    expect(calls.some((c) => c.path === `/v1/kb/uploads/${UPLOAD_ID}`)).toBe(false);
  });

  it("stops asking about a photograph that is resting on a person", async () => {
    // The trap in the contract: an OCR row sits back down at `received` while it waits
    // for a human, so a stop condition keyed on the status alone would poll it forever.
    const { calls } = await renderKnowledge([
      upload({
        source_kind: "image",
        ingest_status: "received",
        text_provenance: "ocr",
        review_state: "pending_approval",
        is_live: false,
      }),
    ]);

    await screen.findByText("Price list.pdf");
    expect(calls.some((c) => c.path === `/v1/kb/uploads/${UPLOAD_ID}`)).toBe(false);
  });
});

describe("removing a document, and reading the original", () => {
  it("says what removal does before doing it, and then does it", async () => {
    const { calls } = await renderKnowledge([upload({ is_live: true })], {
      [`DELETE /v1/kb/uploads/${UPLOAD_ID}`]: null,
    });

    await screen.findByText("Price list.pdf");
    fireEvent.click(screen.getByRole("button", { name: /^remove$/i }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("Your agent stops using this straight away");
    fireEvent.click(screen.getByRole("button", { name: /remove it/i }));

    await waitFor(() =>
      expect(
        calls.some((c) => c.method === "DELETE" && c.path === `/v1/kb/uploads/${UPLOAD_ID}`),
      ).toBe(true),
    );
  });

  it("fetches the five-minute address on the click, never before", async () => {
    const opened = vi.fn();
    vi.stubGlobal("open", opened);
    const { calls } = await renderKnowledge([upload({ is_live: true })], {
      [`/v1/kb/uploads/${UPLOAD_ID}/original`]: {
        url: "https://objects.example/kb/original?signature=abc",
        expires_in_s: 300,
      },
    });

    await screen.findByText("Price list.pdf");
    // Not painted as an href: it would be dead by the time anybody pressed it, and a dead
    // link on the review step reads as "your document is gone".
    expect(calls.some((c) => c.path.endsWith("/original"))).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: /open the file you sent/i }));
    await waitFor(() => expect(opened).toHaveBeenCalled());
    expect(opened.mock.calls[0][0]).toContain("signature=abc");
  });

  it("sends a web page's reader to the page itself, which has no stored file", async () => {
    // `original_download` refuses a link by name (`kb_upload_not_a_file`), so offering the
    // same button on a link would be a control that can only fail.
    await renderKnowledge([
      upload({
        name: "Our prices page",
        source_kind: "url",
        filename: null,
        source_url: "https://clinic.example/prices",
      }),
    ]);

    const link = await screen.findByRole("link", { name: /open the page/i });
    expect(link.getAttribute("href")).toBe("https://clinic.example/prices");
    expect(screen.queryByRole("button", { name: /open the file you sent/i })).toBeNull();
  });
});

describe("who may add, and what happens to what they add", () => {
  it("tells an owner their own document does not wait for us", async () => {
    const { container } = await renderKnowledge([]);

    await screen.findByText(/Add a file or a web page/i);
    expect(container.textContent).toContain("you do not wait for us");
    // And the one exception, stated rather than discovered.
    expect(container.textContent).toContain("anything read off a photo");
  });

  it("tells a staff member their document is reviewed first, and closes the control", async () => {
    // A staff member in an account whose owner has not switched curation on holds no
    // `kb:write`, so the upload control is dead — and it says why, beside itself, rather
    // than answering 403 after they have chosen a 20 MB file.
    const { container } = await renderKnowledge([], { "/v1/me": STAFF });

    await screen.findByText(/Add a file or a web page/i);
    expect(filePicker().disabled).toBe(true);
    expect(container.textContent).toContain("reviewed before your agent starts using it");
    expect(container.textContent).toContain("Only an account owner can add knowledge to this account.");
  });
});
