import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect, useState, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { CopilotDock } from "@/components/copilot/CopilotDock";
import { CopilotPanel } from "@/components/copilot/CopilotPanel";
import { ToggleSwitch } from "@/components/ui";
import { API_BASE, type Session } from "@/lib/api/client";
import { clickByAccessibleName, fillById } from "@/lib/copilot/dom";
import { fallbackRoute, fallbackTitle } from "@/lib/copilot/fallback";
import { applyByPaths, setByPath } from "@/lib/copilot/paths";
import { redactForWire } from "@/lib/copilot/redaction";
import {
  useCopilotSurface,
  useCopilotSurfaceHolder,
  type SurfaceHolder,
} from "@/lib/copilot/registry";

import { expectNoA11yViolations } from "./a11y";

/**
 * `next/navigation` is re-mocked for this file because the PATHNAME is an input here
 * rather than scenery: the dock composes its fallback surface from it (D-501), so a fixed
 * "/" would make every fallback assertion a test of one hard-coded string. Same idiom as
 * `globalStates.test.tsx`; `vi.hoisted` is what lets the factory reach a mutable box.
 */
const nav = vi.hoisted(() => ({ pathname: "/" }));

vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useSearchParams: () => new URLSearchParams(),
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

/**
 * Stub `fetch`: the ask route answers with `chunks`, `/v1/billing/ai-quota` with `quota`,
 * and `/v1/copilot/confirm` with `confirm` — or, when `confirmThrows` is set, by failing
 * the way a severed connection does (which never becomes an `ApiProblem`).
 *
 * Returns both request logs, so a test can assert what was sent AND — for Dismiss — that
 * nothing was.
 */
function stubCopilot(options: {
  chunks?: string[];
  askStatus?: number;
  askBody?: Record<string, unknown>;
  quota?: Record<string, unknown>;
  confirm?: { status: number; body: Record<string, unknown> };
  confirmThrows?: boolean;
  conversation?: { turns: unknown[]; has_more: boolean };
}) {
  const bodies: string[] = [];
  const confirms: string[] = [];
  const conversations: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).replace(API_BASE, "");
      if (path.startsWith("/v1/copilot/confirm")) {
        confirms.push(typeof init?.body === "string" ? init.body : "");
        if (options.confirmThrows) throw new TypeError("Failed to fetch");
        const answer = options.confirm ?? { status: 200, body: {} };
        return new Response(JSON.stringify(answer.body), {
          status: answer.status,
          headers: {
            "content-type":
              answer.status === 200 ? "application/json" : "application/problem+json",
          },
        });
      }
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
      if (path.startsWith("/v1/copilot/conversation")) {
        // THE STORED CONVERSATION (D-540), which every panel mount now loads. Answered
        // here rather than left to the `unexpected request` throw below, because the hook
        // swallows a load failure by design — so an unanswered route would make every
        // test in this file start from an empty panel for the RIGHT reason by accident,
        // and would go on doing so if the load ever became load-bearing.
        conversations.push(init?.method ?? "GET");
        if (init?.method === "DELETE") {
          return new Response(JSON.stringify({ cleared: 2 }), {
            status: 200,
            headers: { "content-type": "application/json" },
          });
        }
        return new Response(
          JSON.stringify(options.conversation ?? { turns: [], has_more: false }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
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
  return { bodies, confirms, conversations };
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
    const { bodies } = stubCopilot({
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

/**
 * The write half: a proposal is rendered, confirmed exactly once, and every refusal the
 * server can make lands as a sentence the person can act on.
 *
 * These drive the REAL `CopilotPanel`, the REAL stream reader and the REAL confirm
 * mutation; only `fetch` is replaced. The frames below are the wire's own — the fields are
 * `apps/api/copilot/schemas.py::CopilotProposalEvent`'s, and the prose is what
 * `write_tools._plan_campaign_pause` composes.
 */
const PROPOSAL = {
  token: "eyJ.a-signed-proposal.zzz",
  tool: "campaign_pause",
  title: "Pause this campaign",
  summary:
    "Stop dialling on “Kondapur launch”. It is running right now. Contacts already " +
    "dialled are unaffected; the rest stop. Nothing changes until you confirm.",
  object_type: "campaign",
  object_id: "0192f0aa-0000-7000-8000-00000000c001",
  current: "running",
  proposed: "paused",
  // D-500. `cost` is null here because pausing charges nothing — the card renders no cost
  // line at all rather than "none", which would make a free action look priced.
  cost: null,
  reversal:
    "You can start it again from the campaign screen. Calls already placed cannot be recalled.",
  expires_at: "2099-01-01T00:00:00Z",
};

/** The stream a write tool produces: some prose, then the offer, then `done`. */
function proposalChunks(proposal: Record<string, unknown> = PROPOSAL): string[] {
  return [
    'event: text\ndata: {"delta":"I can pause it for you."}\n\n',
    `event: proposal\ndata: ${JSON.stringify(proposal)}\n\n`,
    'event: done\ndata: {"disclosure":null,"metered":true}\n\n',
  ];
}

function renderPanel() {
  return render(
    withQuery(
      <>
        <DraftScreen />
        <PanelMount />
      </>,
    ),
  );
}

async function clickConfirm() {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /^Confirm — / }));
  });
}

describe("a proposal", () => {
  it("RENDERS AS A SUGGESTION — the server's sentence, the pair, and no success state", async () => {
    stubCopilot({ chunks: proposalChunks() });
    renderPanel();
    await ask("stop the kondapur campaign");

    // It says, before anything else, that nothing has happened.
    expect(await screen.findByText("Suggestion — nothing has happened yet")).toBeTruthy();
    expect(screen.getAllByText("Pause this campaign").length).toBe(1);
    // The server's own summary, verbatim — never re-composed in the browser.
    expect(screen.getAllByText(PROPOSAL.summary).length).toBe(1);
    // BOTH halves of the decision: what it is now, and what it would become.
    expect(screen.getAllByText("running").length).toBe(1);
    expect(screen.getAllByText("paused").length).toBe(1);
    // Nothing claims the change happened.
    expect(screen.queryAllByText("Done").length).toBe(0);
  });

  it("CONFIRMS ONCE, sending the token and NOTHING ELSE, then says what was done", async () => {
    const { confirms } = stubCopilot({
      chunks: proposalChunks(),
      confirm: {
        status: 200,
        body: {
          tool: "campaign_pause",
          object_type: "campaign",
          object_id: PROPOSAL.object_id,
          applied: true,
          detail: "Dialling has stopped on that campaign.",
        },
      },
    });
    renderPanel();
    await ask("stop the kondapur campaign");
    await screen.findByRole("button", { name: /^Confirm — / });
    await clickConfirm();

    // ONE request, carrying the token UNCHANGED and no parameter of its own: every
    // argument of the change is inside the signature.
    expect(confirms.length).toBe(1);
    expect(JSON.parse(confirms[0])).toEqual({ token: PROPOSAL.token });

    // The server's own outcome sentence, and only now a completed state.
    expect(await screen.findByText("Dialling has stopped on that campaign.")).toBeTruthy();
    expect(screen.getAllByText("Done").length).toBe(1);
    expect(screen.queryAllByText("Suggestion — nothing has happened yet").length).toBe(0);
  });

  it("says NOTHING TO CHANGE when the world was already in that state", async () => {
    stubCopilot({
      chunks: proposalChunks(),
      confirm: {
        status: 200,
        body: {
          tool: "campaign_pause",
          object_type: "campaign",
          object_id: PROPOSAL.object_id,
          applied: false,
          detail: "That campaign was already paused, so nothing changed.",
        },
      },
    });
    renderPanel();
    await ask("stop it");
    await screen.findByRole("button", { name: /^Confirm — / });
    await clickConfirm();

    // `applied: false` is a real answer (D-65), not a failure and not a success.
    expect(
      await screen.findByText("That campaign was already paused, so nothing changed."),
    ).toBeTruthy();
    expect(screen.getAllByText("Nothing to change").length).toBe(1);
    expect(screen.queryAllByText("Done").length).toBe(0);
  });

  it("DISMISS SENDS NOTHING — a proposal is refused by doing nothing", async () => {
    const { confirms } = stubCopilot({ chunks: proposalChunks() });
    renderPanel();
    await ask("stop the campaign");
    await screen.findByRole("button", { name: /^Confirm — / });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Dismiss — / }));
    });
    expect(confirms.length).toBe(0);
    expect(screen.queryAllByText("Suggestion — nothing has happened yet").length).toBe(0);
  });

  it("REFUSES TO OFFER A CONFIRM on a proposal that has already expired", async () => {
    stubCopilot({ chunks: proposalChunks({ ...PROPOSAL, expires_at: "2020-01-01T00:00:00Z" }) });
    renderPanel();
    await ask("stop the campaign");

    expect(
      await screen.findByText(
        "This suggestion has expired. Ask the assistant again — nothing was changed.",
      ),
    ).toBeTruthy();
    expect(screen.queryAllByRole("button", { name: /^Confirm — / }).length).toBe(0);
  });

  /**
   * Every refusal shape the confirm door can produce, each with the sentence the person is
   * left holding and whether the card may be clicked again.
   *
   * The retry rule is the load-bearing column: the server BURNS the proposal immediately
   * before executing, so a refusal that got past the burn has spent the token and a second
   * click could only ever be told "already confirmed". Only the replay guard being
   * unreachable — it fails CLOSED, so nothing ran — leaves it spendable.
   */
  const REFUSALS: {
    what: string;
    status: number;
    body: Record<string, unknown>;
    reads: string;
    clickable: boolean;
  }[] = [
    {
      what: "an expired, replayed or tampered token",
      status: 403,
      body: {
        type: "urn:calevate:permission/copilot_proposal_invalid",
        title: "That change could not be confirmed",
        detail: "This suggestion is no longer valid.",
        remediation: "Ask the assistant again — nothing has been changed.",
        kind: "permission",
      },
      reads: "Ask the assistant again — nothing has been changed.",
      clickable: false,
    },
    {
      what: "a proposal somebody already confirmed",
      status: 403,
      body: {
        type: "urn:calevate:permission/copilot_proposal_already_used",
        title: "That change could not be confirmed",
        detail: "This suggestion has already been confirmed.",
        remediation: "Check the record — the change was made the first time.",
        kind: "permission",
      },
      reads: "Check the record — the change was made the first time.",
      clickable: false,
    },
    {
      what: "a role that may not do it",
      status: 403,
      body: {
        type: "urn:calevate:permission/forbidden",
        title: "Forbidden",
        detail: "You do not have permission to make this change.",
        remediation: "Ask an owner or manager on this account to confirm it instead.",
        kind: "permission",
      },
      reads: "Ask an owner or manager on this account to confirm it instead.",
      clickable: false,
    },
    {
      what: "a campaign that is no longer running",
      status: 409,
      body: {
        type: "urn:calevate:conflict/campaign_not_running",
        title: "Conflict",
        detail: "That campaign is not running.",
        remediation: "Reload the campaign and check its state.",
        kind: "conflict",
      },
      reads: "Reload the campaign and check its state.",
      clickable: false,
    },
    {
      what: "the replay guard being unreachable",
      status: 503,
      body: {
        type: "urn:calevate:dependency/copilot_confirm_unavailable",
        title: "That change could not be confirmed",
        detail: "The assistant could not check that this suggestion is still unused.",
        remediation: "Try again in a moment — nothing has been changed.",
        kind: "dependency",
      },
      reads: "Try again in a moment — nothing has been changed.",
      clickable: true,
    },
  ];

  for (const refusal of REFUSALS) {
    it(`SHOWS ITS OWN ACTIONABLE SENTENCE for ${refusal.what}`, async () => {
      stubCopilot({
        chunks: proposalChunks(),
        confirm: { status: refusal.status, body: refusal.body },
      });
      renderPanel();
      await ask("stop the campaign");
      await screen.findByRole("button", { name: /^Confirm — / });
      await clickConfirm();

      // The refusal is on screen, in the SERVER's words, and the card did not vanish.
      expect(await screen.findByText(refusal.reads)).toBeTruthy();
      expect(screen.getAllByText("Suggestion — nothing has happened yet").length).toBe(1);
      // …and nothing anywhere claims the change was made.
      expect(screen.queryAllByText("Done").length).toBe(0);
      // The action button, under either of its two words: it reads "Try again" once the
      // refusal is one that left the token spendable.
      expect(screen.queryAllByRole("button", { name: /^(Confirm|Try again) — / }).length).toBe(
        refusal.clickable ? 1 : 0,
      );
    });
  }

  it("keeps the card and offers a RETRY when the connection dropped", async () => {
    // A failure that never became an `ApiProblem`: the request may have landed or may not
    // have, and retrying is safe only because the server's `jti` burn refuses a second
    // execution rather than doubling it.
    stubCopilot({ chunks: proposalChunks(), confirmThrows: true });
    renderPanel();
    await ask("stop the campaign");
    await screen.findByRole("button", { name: /^Confirm — / });
    await clickConfirm();

    expect(
      await screen.findByText("We could not reach Calevate. Check your connection and try again."),
    ).toBeTruthy();
    // Offered again, and its accessible name follows its visible word rather than being
    // frozen at "Confirm" — WCAG 2.5.3 wants the name to contain what is on the button.
    const again = screen.getAllByRole("button", { name: /^Try again — Pause this campaign$/ });
    expect(again.length).toBe(1);
    expect(again[0].textContent).toBe("Try again");
    expect(screen.queryAllByText("Done").length).toBe(0);
  });

  it("STYLES A CONSEQUENTIAL CHANGE AS ONE, and an ordinary edit as ordinary", async () => {
    stubCopilot({ chunks: proposalChunks() });
    const view = renderPanel();
    await ask("stop the campaign");
    // Pausing a campaign stops live dialling — UX-DOCTRINE §4's rose, never the brand
    // green, so an eye scanning the panel cannot mistake it for an ordinary save.
    const stop = await screen.findByRole("button", { name: /^Confirm — / });
    expect(stop.className).toContain("bg-rose-600");
    view.unmount();

    stubCopilot({
      chunks: proposalChunks({
        ...PROPOSAL,
        token: "eyJ.another.zzz",
        tool: "lead_set_status",
        title: "Change this lead's status",
        summary:
          "Mark this lead as Hot. It is currently Contacted. Nothing changes until you confirm.",
        object_type: "lead",
        current: "Contacted",
        proposed: "Hot",
      }),
    });
    renderPanel();
    await ask("mark it hot");
    const edit = await screen.findByRole("button", { name: /^Confirm — / });
    expect(edit.className).toContain("bg-brand-strong");
  });

  it("is KEYBOARD REACHABLE, ANNOUNCED, and axe-clean", async () => {
    stubCopilot({ chunks: proposalChunks() });
    const view = renderPanel();
    await ask("stop the campaign");
    const confirmButton = await screen.findByRole("button", { name: /^Confirm — / });

    // A real `<button>`, so it is in the tab order with no `tabindex` arithmetic; and its
    // accessible name CONTAINS its visible word (WCAG 2.5.3 Label in Name) while naming
    // WHICH change, so a keyboard user does not land on a bare verb.
    expect(confirmButton.tagName).toBe("BUTTON");
    expect(confirmButton.textContent).toBe("Confirm");
    expect(confirmButton.getAttribute("aria-label")).toBe("Confirm — Pause this campaign");

    // Announced when it arrives, WITHOUT stealing the caret from the ask box.
    const card = confirmButton.closest('[role="group"]')!;
    expect(card.getAttribute("aria-label")).toBe("Suggestion: Pause this campaign");
    expect(card.parentElement?.getAttribute("aria-live")).toBe("polite");
    expect(document.activeElement?.tagName).toBe("TEXTAREA");

    await expectNoA11yViolations(view.container, "the copilot proposal card");
  });

  it("MOVES FOCUS TO THE CARD once the confirm resolves, because the button is gone", async () => {
    stubCopilot({
      chunks: proposalChunks(),
      confirm: {
        status: 200,
        body: {
          tool: "campaign_pause",
          object_type: "campaign",
          object_id: PROPOSAL.object_id,
          applied: true,
          detail: "Dialling has stopped on that campaign.",
        },
      },
    });
    renderPanel();
    await ask("stop the campaign");
    await screen.findByRole("button", { name: /^Confirm — / });
    await clickConfirm();
    await screen.findByText("Dialling has stopped on that campaign.");

    // Without this the keyboard would fall to `<body>`: the control the person was
    // standing on has been replaced by the outcome.
    expect(document.activeElement?.getAttribute("role")).toBe("group");
  });

  it("REPLACES a previous card rather than stacking, and a new question clears it", async () => {
    stubCopilot({ chunks: proposalChunks() });
    renderPanel();
    await ask("stop the campaign");
    expect(await screen.findByText("Suggestion — nothing has happened yet")).toBeTruthy();

    stubCopilot({ chunks: ['event: done\ndata: {"disclosure":null,"metered":true}\n\n'] });
    await ask("what about the other one?");
    await waitFor(() =>
      expect(screen.queryAllByText("Suggestion — nothing has happened yet").length).toBe(0),
    );
  });
});

/**
 * D-501: the assistant is never absent. A screen that declared nothing still gets a
 * launcher, a route, a title and every read tool — and a screen that DID declare must
 * still win, whatever the mount order.
 */
describe("the fallback surface", () => {
  /** The dock as a realm shell mounts it, with whatever is beside it. */
  function DockMount({ realm = "client" as const, children }: { realm?: "client" | "admin"; children?: ReactNode }) {
    return withQuery(
      <>
        {children}
        <CopilotDock session={SESSION} realm={realm} />
      </>,
    );
  }

  async function openDock() {
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Ask about this screen" }));
    });
  }

  it("MASKS anything in the address that is not a plain name", () => {
    // The realistic hazard: a personal value in the address bar reaching the prompt, the
    // audit row, and the server's redaction guard — which would refuse the whole question
    // and show a defect message to somebody who did nothing wrong.
    expect(fallbackRoute("/c/acme/billing")).toBe("/c/acme/billing");
    expect(fallbackRoute("/c/acme/leads/550e8400-e29b-41d4-a716-446655440000")).toBe(
      "/c/acme/leads/:hidden",
    );
    expect(fallbackRoute("/c/acme/members/priya@example.com")).toBe("/c/acme/members/:hidden");
    expect(fallbackRoute("/c/acme/leads/+919876543210")).toBe("/c/acme/leads/:hidden");
    // A caller passing a full href is the mistake this cuts, and the query string is
    // exactly where an email or a number turns up.
    expect(fallbackRoute("/c/acme/leads?email=priya@example.com")).toBe("/c/acme/leads");
    expect(fallbackRoute("/")).toBe("/");
  });

  it("names the screen from the last part of the address a person would recognise", () => {
    expect(fallbackTitle("/c/acme/billing", "client")).toBe("Billing");
    expect(fallbackTitle("/c/acme/leads/:hidden", "client")).toBe("Leads");
    expect(fallbackTitle("/admin/tenants/:hidden/do-not-call", "admin")).toBe("Do not call");
    expect(fallbackTitle("/", "admin")).toBe("Admin console");
  });

  it("STILL RENDERS THE LAUNCHER, and sends the route, no fields, and the honest fact", async () => {
    nav.pathname = "/c/acme/billing";
    const { bodies } = stubCopilot({
      chunks: [
        'event: text\ndata: {"delta":"You have 12 leads."}\n\n',
        'event: done\ndata: {"disclosure":null,"metered":true}\n\n',
      ],
    });
    render(<DockMount />);
    await openDock();
    // The header names the screen — "I can see you're on the billing screen".
    expect(screen.getAllByText("Billing").length).toBe(1);
    expect(screen.getByText(/hasn't told the assistant what it shows/)).toBeTruthy();

    // THE POINT OF THE WHOLE CHANGE: a read-tool question is asked and answered from a
    // screen that declared nothing. The read tools run server-side off the account's own
    // rows and never look at the screen block, so the answer arrives as it always would.
    await ask("how many leads do I have?");
    await screen.findByText("You have 12 leads.");

    const sent = JSON.parse(bodies[0]) as {
      screen: { route: string; title: string; realm: string };
      fields: unknown[];
      facts: { key: string; value: string }[];
    };
    expect(sent.screen).toEqual({ route: "/c/acme/billing", title: "Billing", realm: "client" });
    expect(sent.fields).toEqual([]);
    // "Declared nothing" and "shows nothing" are different sentences, and only the first is
    // true. Zero fields cannot carry that distinction — a read-only screen declaring
    // `noFill` sends zero too — so the fact has to say it in words.
    expect(sent.facts).toHaveLength(1);
    expect(sent.facts[0].key).toBe("screen_details");
    expect(sent.facts[0].value).toContain("not an empty screen");
  });

  it("LETS A CHILD'S REAL DECLARATION BEAT IT, whatever the mount order", async () => {
    // THE FAILURE THIS EXISTS TO FORECLOSE. The registry is a stack and a parent's effect
    // commits AFTER its child's, so a shell that DECLARED a generic surface would land on
    // top of the screen's own declaration and shadow it — which has already cost this
    // console two field lists. The fallback is composed in the dock and never registered,
    // so there is no ordering for it to win.
    nav.pathname = "/c/acme/agents/new";
    const { bodies } = stubCopilot({
      chunks: ['event: done\ndata: {"disclosure":null,"metered":true}\n\n'],
    });
    render(
      <DockMount>
        <DraftScreen />
      </DockMount>,
    );
    await openDock();
    expect(screen.getAllByText("A test screen").length).toBe(1);
    await ask("what is left to do?");

    const sent = JSON.parse(bodies[0]) as {
      screen: { route: string; title: string };
      fields: { id: string }[];
      facts: unknown[];
    };
    expect(sent.screen.route).toBe("/t");
    expect(sent.screen.title).toBe("A test screen");
    expect(sent.fields.map((field) => field.id)).toEqual(["t-name", "t-opens", "t-phone"]);
    // …and the fallback's "I cannot see this screen" fact is nowhere near it.
    expect(sent.facts).toEqual([]);
  });

  it("APPLIES NOTHING when a fill arrives for a screen that declared no fields", async () => {
    // `set_fields` stays in the tool array (the array is byte-identical on every request —
    // it is the whole prompt cache), so the refusal has to be real rather than absent. The
    // server refuses it item by item (`validate_fill`); this is the browser's own half of
    // the same answer, and it is what keeps "filled 21 fields nobody asked for" impossible
    // on a screen with nothing declared to fill.
    nav.pathname = "/c/acme/billing";
    stubCopilot({
      chunks: [
        'event: text\ndata: {"delta":"I cannot see this screen."}\n\n',
        'event: fill\ndata: {"items":[{"field_id":"plan","value":"growth"}]}\n\n',
        'event: done\ndata: {"disclosure":null,"metered":true}\n\n',
      ],
    });
    render(<DockMount />);
    await openDock();
    await ask("set the plan to growth");
    await screen.findByText("I cannot see this screen.");
    expect(screen.queryAllByText(/^Filled /).length).toBe(0);
  });

  it("TELLS AN OPERATOR WHY RATHER THAN SENDING A DOOMED REQUEST", async () => {
    // The admin realm is server-refused: `/v1/copilot/ask` is client-realm, so an
    // operator's token is checked against the client realm and 401s
    // (`copilot/route_test.py::test_an_operator_is_refused_at_the_door_before_any_of_this_
    // runs`). Rendered raw that is "Unauthorized · Authentication is required" — "you are
    // signed out", told to somebody who is not — and D-501 puts this launcher on every
    // admin screen. So the panel explains instead, and sends nothing.
    nav.pathname = "/admin/tenants";
    const { bodies } = stubCopilot({ chunks: [] });
    render(<DockMount realm="admin" />);
    await openDock();
    expect(screen.getByText(/isn't available in the admin console yet/)).toBeTruthy();
    expect(screen.queryByLabelText("Your question about this screen")).toBeNull();
    expect(bodies).toEqual([]);
  });
});

/**
 * The two frames D-500 added, driven through the REAL panel.
 *
 * `action` and `step` are the browser's half of "an assistant that performs actions": a
 * receipt for something already done, and a live account of what it is doing. Both are
 * asserted against the panel rather than against the reader, because the property that
 * matters is what a PERSON SEES — in particular, that a receipt never looks like an offer.
 */
const ACTION = {
  tool: "agent_create",
  title: "Create a draft agent",
  detail: "“Raghava outbound” exists as a draft.",
  object_type: "agent",
  object_id: "0192f0aa-0000-7000-8000-00000000a001",
  applied: true,
  reversal: "A draft reaches no caller. You can rename it, or archive it, from the Agents screen.",
  where: "under Agents in your dashboard",
};

describe("an action the assistant has already taken", () => {
  it("RENDERS AS A RECEIPT — no Confirm button, and it says where the result is", async () => {
    stubCopilot({
      chunks: [
        `event: action\ndata: ${JSON.stringify(ACTION)}\n\n`,
        'event: text\ndata: {"delta":"Created it as a draft."}\n\n',
        'event: done\ndata: {"disclosure":null,"metered":true}\n\n',
      ],
    });
    renderPanel();
    await ask("create an outbound agent called raghava outbound");

    expect(await screen.findByText("Done")).toBeTruthy();
    expect(screen.getAllByText(ACTION.detail).length).toBe(1);
    // THE CROSS-SCREEN RULE, on screen: it acted from wherever the person was and told
    // them where it went, rather than navigating them or filling in a form for them.
    expect(screen.getAllByText(ACTION.where).length).toBe(1);
    // AND THE HONEST UNDO. The panel's own Undo belongs to a field fill and does not reach
    // a database write, so this sentence is the only thing saying what applies here.
    expect(screen.getAllByText(ACTION.reversal).length).toBe(1);
    // NOTHING TO CONFIRM AND NOTHING SUGGESTED: this already happened.
    expect(screen.queryAllByRole("button", { name: /^Confirm — / }).length).toBe(0);
    expect(screen.queryAllByText("Suggestion — nothing has happened yet").length).toBe(0);
  });
});

describe("live tool-execution visibility", () => {
  it("SHOWS ONE ROW PER CALL, updated in place, with the tool and how long it took", async () => {
    const running = {
      id: "r1",
      tool: "campaigns_list",
      status: "running",
      args: '{"limit":5}',
      detail: null,
      elapsed_ms: null,
    };
    const finished = { ...running, status: "done", detail: "2 campaigns.", elapsed_ms: 84 };
    stubCopilot({
      chunks: [
        `event: step\ndata: ${JSON.stringify(running)}\n\n`,
        `event: step\ndata: ${JSON.stringify(finished)}\n\n`,
        'event: text\ndata: {"delta":"You have two."}\n\n',
        'event: done\ndata: {"disclosure":null,"metered":true}\n\n',
      ],
    });
    renderPanel();
    await ask("what campaigns do i have");

    // ONE row for one call: the terminal frame REPLACED its own `running` one rather than
    // following it, which is what keeps a two-lookup turn from looking like four.
    expect((await screen.findAllByText("campaigns_list")).length).toBe(1);
    expect(screen.getAllByText("2 campaigns.").length).toBe(1);
    expect(screen.getAllByText("84 ms").length).toBe(1);
  });
});
