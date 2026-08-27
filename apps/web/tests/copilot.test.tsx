import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect, useState, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { CopilotPanel } from "@/components/copilot/CopilotPanel";
import { ToggleSwitch } from "@/components/ui";
import { API_BASE, type Session } from "@/lib/api/client";
import { clickByAccessibleName, fillById } from "@/lib/copilot/dom";
import { applyByPaths, setByPath } from "@/lib/copilot/paths";
import { redactForWire } from "@/lib/copilot/redaction";
import {
  useCopilotSurface,
  useCopilotSurfaceHolder,
  type SurfaceHolder,
} from "@/lib/copilot/registry";

/**
 * The screen assistant: the registry contract, both apply paths, the undo contract, and
 * the two rules that are compliance rather than UX — a personal value never leaving the
 * browser, and the wallet ceiling being answered through the ONE wallet dialog.
 *
 * Everything here drives the REAL components and the REAL store. The only thing replaced
 * is `fetch`, which is the seam the rest of this suite uses for the same reason: a test
 * that stubbed the conversation hook would be asserting a mock's opinion of it.
 */

const SESSION: Session = { orgSlug: "acme" };

/** A screen with one typed draft — the good apply path, as most registrations use it. */
function DraftScreen({ initial }: { initial?: { name: string; opens: string; phone: string } }) {
  const [draft, setDraft] = useState(
    initial ?? { name: "", opens: "09:00", phone: "+919876543210" },
  );
  useCopilotSurface({
    route: "/t",
    title: "A test screen",
    realm: "client",
    fields: [
      { id: "t-name", label: "Business name", type: "text", value: draft.name },
      { id: "t-opens", label: "Opens", type: "text", value: draft.opens },
      { id: "t-phone", label: "Escalation phone", type: "text", value: draft.phone, personal: "phone" },
    ],
    apply: (items) =>
      setDraft((current) =>
        applyByPaths(current, items, (id) => (id.startsWith("t-") ? id.slice(2) : null)),
      ),
  });
  return (
    <form>
      <label htmlFor="t-name">Business name</label>
      <input
        id="t-name"
        value={draft.name}
        onChange={(event) => setDraft((d) => ({ ...d, name: event.target.value }))}
      />
      <label htmlFor="t-opens">Opens</label>
      <input
        id="t-opens"
        value={draft.opens}
        onChange={(event) => setDraft((d) => ({ ...d, opens: event.target.value }))}
      />
      <label htmlFor="t-phone">Escalation phone</label>
      <input
        id="t-phone"
        value={draft.phone}
        onChange={(event) => setDraft((d) => ({ ...d, phone: event.target.value }))}
      />
    </form>
  );
}

function Probe({ onHolder }: { onHolder: (holder: SurfaceHolder | null) => void }) {
  const holder = useCopilotSurfaceHolder();
  useEffect(() => {
    onHolder(holder);
  }, [holder, onHolder]);
  return null;
}

/** The panel, mounted against whatever the screen beside it registered. */
function PanelMount() {
  const holder = useCopilotSurfaceHolder();
  if (holder === null) return null;
  return (
    <CopilotPanel
      session={SESSION}
      holder={holder}
      realm="client"
      labelledBy="t-panel"
      onClose={() => {}}
    />
  );
}

function withQuery(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** A `text/event-stream` response with these chunks. */
function sse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    }),
    { status: 200, headers: { "content-type": "text/event-stream" } },
  );
}

/** Stub `fetch`: the ask route answers with `chunks`, `/v1/billing/ai-quota` with `quota`. */
function stubCopilot(options: {
  chunks?: string[];
  askStatus?: number;
  askBody?: Record<string, unknown>;
  quota?: Record<string, unknown>;
}) {
  const bodies: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).replace(API_BASE, "");
      if (path.startsWith("/v1/copilot/ask")) {
        bodies.push(typeof init?.body === "string" ? init.body : "");
        if (options.askStatus !== undefined) {
          return new Response(JSON.stringify(options.askBody ?? {}), {
            status: options.askStatus,
            headers: { "content-type": "application/problem+json" },
          });
        }
        return sse(options.chunks ?? []);
      }
      if (path.startsWith("/v1/billing/ai-quota")) {
        return new Response(JSON.stringify(options.quota ?? {}), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      throw new Error(`unexpected request: ${path}`);
    }),
  );
  return bodies;
}

async function ask(question: string) {
  fireEvent.change(screen.getByLabelText("Your question about this screen"), {
    target: { value: question },
  });
  await act(async () => {
    fireEvent.submit(screen.getByRole("button", { name: "Ask" }).closest("form")!);
  });
}

describe("the registry", () => {
  it("hands the dock the screen's CURRENT values, not the ones it was mounted with", async () => {
    let holder: SurfaceHolder | null = null;
    render(
      <>
        <DraftScreen />
        <Probe onHolder={(next) => (holder = next)} />
      </>,
    );
    expect(holder).not.toBeNull();
    expect(holder!.read().fields.map((field) => field.id)).toEqual(["t-name", "t-opens", "t-phone"]);
    expect(holder!.read().fields[0].value).toBe("");

    fireEvent.change(screen.getByLabelText("Business name"), { target: { value: "Sri Clinic" } });
    await waitFor(() => expect(holder!.read().fields[0].value).toBe("Sri Clinic"));
  });

  it("declares nothing once the screen unmounts", () => {
    let holder: SurfaceHolder | null = null;
    const view = render(
      <>
        <DraftScreen />
        <Probe onHolder={(next) => (holder = next)} />
      </>,
    );
    expect(holder).not.toBeNull();
    view.rerender(<Probe onHolder={(next) => (holder = next)} />);
    expect(holder).toBeNull();
  });
});

describe("applying a fill", () => {
  it("lands through the screen's own draft setter", async () => {
    let holder: SurfaceHolder | null = null;
    render(
      <>
        <DraftScreen />
        <Probe onHolder={(next) => (holder = next)} />
      </>,
    );
    await act(async () => {
      holder!.read().apply([
        { field_id: "t-name", value: "Sri Clinic" },
        { field_id: "t-opens", value: "10:30" },
      ]);
    });
    // BOTH, from one call: six sequential setState calls against a captured draft keep
    // the last and lose the rest, which is why `apply` takes the whole batch.
    expect((screen.getByLabelText("Business name") as HTMLInputElement).value).toBe("Sri Clinic");
    expect((screen.getByLabelText("Opens") as HTMLInputElement).value).toBe("10:30");
  });

  it("lands through the NATIVE-SETTER path on a controlled input", async () => {
    // The last resort (`lib/copilot/dom.ts`): a plain `el.value = x` updates nothing,
    // because React skips the change when its own tracker already matches.
    render(<DraftScreen />);
    const input = screen.getByLabelText("Business name") as HTMLInputElement;
    await act(async () => {
      expect(fillById("t-name", "Front desk")).toBe(true);
    });
    expect(input.value).toBe("Front desk");
  });

  it("reports a miss rather than throwing when the control is not on the page", () => {
    render(<DraftScreen />);
    expect(fillById("t-nothing", "x")).toBe(false);
  });

  it("DRIVES A ToggleSwitch BY `.click()`, found by its accessible name", () => {
    // `ToggleSwitch` is an `sr-only` checkbox whose label WRAPS it with no `htmlFor`, so
    // there is no id to look up — and React delegates a checkbox's `onChange` from a
    // `click`, so dispatching `input` on it would update nothing.
    function Switches() {
      const [recording, setRecording] = useState(false);
      const [disclosure, setDisclosure] = useState(false);
      return (
        <>
          <ToggleSwitch label="Recording notice" checked={recording} onChange={setRecording} />
          <ToggleSwitch label="AI disclosure" checked={disclosure} onChange={setDisclosure} />
          <p>{`recording=${recording} disclosure=${disclosure}`}</p>
        </>
      );
    }
    render(<Switches />);
    expect(clickByAccessibleName("AI disclosure", true)).toBe(true);
    // The OTHER switch is untouched: matching is by the label's leading text, so two
    // switches on one screen cannot be confused for each other.
    expect(screen.getAllByText("recording=false disclosure=true").length).toBe(1);
    // Already in the wanted state: reported as landed, and nothing is clicked.
    expect(clickByAccessibleName("AI disclosure", true)).toBe(true);
    expect(screen.getAllByText("recording=false disclosure=true").length).toBe(1);
  });
});

describe("setByPath", () => {
  it("returns the ORIGINAL object when the path does not exist, so nothing re-renders", () => {
    const draft = { services: [{ name: "Consultation" }] };
    expect(setByPath(draft, "services.9.name", "x")).toBe(draft);
    expect(setByPath(draft, "constructor", "x")).toBe(draft);
    expect(setByPath(draft, "services.0.name", "Scan")).toEqual({ services: [{ name: "Scan" }] });
  });
});

describe("the panel", () => {
  it("UNDOES THE WHOLE BATCH, restoring prior values INCLUDING the empty one", async () => {
    stubCopilot({
      chunks: [
        'event: text\ndata: {"delta":"Filled them in."}\n\n',
        'event: fill\ndata: {"items":[{"field_id":"t-name","value":"Sri Clinic"},{"field_id":"t-opens","value":"11:00"}]}\n\n',
        'event: done\ndata: {"disclosure":null,"metered":true}\n\n',
      ],
    });
    render(
      withQuery(
        <>
          <DraftScreen />
          <PanelMount />
        </>,
      ),
    );
    await ask("fill in the hours");
    await waitFor(() =>
      expect((screen.getByLabelText("Business name") as HTMLInputElement).value).toBe("Sri Clinic"),
    );
    expect(screen.getAllByText("Filled 2 fields").length).toBe(1);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Undo/ }));
    });
    // "was empty" is a real prior and the one most worth restoring.
    expect((screen.getByLabelText("Business name") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Opens") as HTMLInputElement).value).toBe("09:00");
    expect(screen.queryAllByText("Filled 2 fields").length).toBe(0);
  });

  it("SENDS A PLACEHOLDER FOR A PERSONAL FIELD AND RESTORES THE REAL VALUE LOCALLY", async () => {
    const bodies = stubCopilot({
      chunks: [
        'event: text\ndata: {"delta":"«PHONE_1» is already the escalation number."}\n\n',
        'event: fill\ndata: {"items":[{"field_id":"t-name","value":"Ring «PHONE_1»"}]}\n\n',
        'event: done\ndata: {"disclosure":null,"metered":true}\n\n',
      ],
    });
    render(
      withQuery(
        <>
          <DraftScreen />
          <PanelMount />
        </>,
      ),
    );
    await ask("whose number is on file?");

    // D-127 G-2: the digits never left the browser.
    const sent = JSON.parse(bodies[0]) as { fields: { id: string; value: string; redacted: boolean }[] };
    const phone = sent.fields.find((field) => field.id === "t-phone")!;
    expect(phone.value).toBe("«PHONE_1»");
    expect(phone.redacted).toBe(true);
    expect(bodies[0]).not.toContain("9876543210");

    // …and the person sees the real number, in the answer AND in the filled field.
    await waitFor(() =>
      expect(
        screen.getAllByText("+919876543210 is already the escalation number.").length,
      ).toBe(1),
    );
    expect((screen.getByLabelText("Business name") as HTMLInputElement).value).toBe(
      "Ring +919876543210",
    );
  });

  it("shows a dropped stream as a retryable refusal and keeps what arrived", async () => {
    stubCopilot({ chunks: ['event: text\ndata: {"delta":"half an ans"}\n\n'] });
    render(
      withQuery(
        <>
          <DraftScreen />
          <PanelMount />
        </>,
      ),
    );
    await ask("anything");
    await waitFor(() =>
      // `ProblemNotice` renders the problem's `detail`, which is where the sentence a
      // person can act on lives.
      expect(
        screen.getAllByText("The connection closed before the assistant finished answering.")
          .length,
      ).toBe(1),
    );
    expect(screen.getAllByText("half an ans").length).toBe(1);
  });

  it("OPENS THE EXISTING WALLET DIALOG AT THE AI CEILING", async () => {
    stubCopilot({
      askStatus: 402,
      askBody: { type: "urn:calevate:billing/ai_quota_exceeded", title: "No AI help left" },
      quota: {
        month: "2026-08",
        plan_tier: "growth",
        state: "ceiling_reached",
        included_inr: "500.00",
        used_inr: "500.00",
        allowance_inr: "500.00",
        remaining_inr: "0.00",
        requests_used: 500,
        requests_included: 500,
        requests_remaining: 0,
        extra_purchased_inr: null,
        extra_block_inr: "250.00",
        extra_block_requests: 250,
        extra_available: true,
        extra_unavailable_reason: null,
      },
    });
    render(
      withQuery(
        <>
          <DraftScreen />
          <PanelMount />
        </>,
      ),
    );
    await ask("fill it in");
    const open = await screen.findByRole("button", { name: "Add more AI help" });
    await act(async () => {
      fireEvent.click(open);
    });
    // `AcceptChargeDialog` — the ONE dialog in this console that debits a wallet.
    expect(screen.getAllByText("Add more AI help this month").length).toBe(1);
    expect(screen.getAllByText("Nothing has been charged yet.").length).toBe(1);
  });
});

describe("redactForWire", () => {
  it("leaves an EMPTY personal field alone — a blank carries no personal data", () => {
    const pass = redactForWire(
      [{ id: "a", label: "Phone", type: "text", value: "", personal: "phone" }],
      [],
    );
    expect(pass.fields[0].value).toBe("");
    expect(pass.fields[0].redacted).toBe(false);
  });

  it("numbers each kind separately and restores every occurrence", () => {
    const pass = redactForWire(
      [
        { id: "a", label: "A", type: "text", value: "+911", personal: "phone" },
        { id: "b", label: "B", type: "text", value: "+912", personal: "phone" },
        { id: "c", label: "C", type: "text", value: "x@y.z", personal: "email" },
      ],
      [],
    );
    expect(pass.fields.map((field) => field.value)).toEqual([
      "«PHONE_1»",
      "«PHONE_2»",
      "«EMAIL_1»",
    ]);
    expect(pass.restore("call «PHONE_2», or «PHONE_2» again, then «EMAIL_1»")).toBe(
      "call +912, or +912 again, then x@y.z",
    );
    // Idempotent over text carrying no token — it runs over every streamed delta.
    expect(pass.restore("nothing here")).toBe("nothing here");
  });
});
