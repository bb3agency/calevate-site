import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import FirstAgentPage from "@/app/c/[slug]/agents/first/page";
import { metaOf } from "@/app/c/[slug]/agents/first/BuildStep";
import { answersOf } from "@/app/c/[slug]/agents/first/QuestionsStep";
import { recordingMimeType } from "@/components/voiceButton";
import type { Agent } from "@/lib/api/agents";
import type { FirstRun, FirstRunQuestion } from "@/lib/api/firstRun";
import {
  GREETING_MAX_CHARS,
  NOT_FEMALE_LINE,
  callsLeft,
  defaultLanguage,
  firstAgentOf,
  greetingFits,
  piecesOf,
  resumeStage,
  studioFallbackLine,
  trialMinutesLine,
  voicePickNote,
} from "@/lib/firstAgent";

import { businessProfileFixture } from "./businessProfileFixture";
import { OWNER_ME, agentRow } from "./fixtures/sharedReads";
import { renderClientPage } from "./harness";

/**
 * "MEET YOUR AGENT" (D-855): the job, the brief, the questions, the build ticked as it
 * happens, one honest screen before the call, the call, and what it caught.
 */

const nav = vi.hoisted(() => ({ pushed: [] as string[] }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/c/acme/agents/first",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({
    push: (path: string) => nav.pushed.push(path),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

beforeEach(() => {
  nav.pushed = [];
});

const page = <FirstAgentPage params={Promise.resolve({ slug: "acme" })} />;
const AGENT_ID = "0192f3a4-0000-7000-8000-00000000a001";

const STEPS = ["voice", "script", "greeting", "notice"] as const;

function run(over: Partial<FirstRun> = {}): FirstRun {
  return {
    due: true,
    jobs: [],
    language_primary: null,
    languages_extra: [],
    brief: null,
    agent_id: null,
    questions: { status: "idle", items: [], disclosure: null },
    build: {
      status: "idle",
      steps: STEPS.map((step) => ({ step, state: "waiting", label: null, not_female: false })),
      disclosure: null,
      builds_left: 3,
    },
    recordings_left: 3,
    finished_at: null,
    dismissed_at: null,
    ...over,
  };
}

function built(over: Partial<FirstRun> = {}): FirstRun {
  return run({
    jobs: ["answer_calls"],
    language_primary: "te-IN",
    languages_extra: ["en-IN"],
    brief: "We sell flats in Kondapur.",
    agent_id: AGENT_ID,
    questions: { status: "ready", items: [], disclosure: null },
    build: {
      status: "built",
      steps: [
        { step: "voice", state: "done", label: "Lakshmi", not_female: false },
        { step: "script", state: "done", label: null, not_female: false },
        { step: "greeting", state: "done", label: null, not_female: false },
        { step: "notice", state: "done", label: null, not_female: false },
      ],
      disclosure: null,
      builds_left: 2,
    },
    ...over,
  });
}

function agent(over: Partial<Agent> = {}): Agent {
  return agentRow({
    id: AGENT_ID,
    name: "Anjali",
    status: "draft",
    published: false,
    direction: "inbound",
    engine_voice_id: "engine:v1",
    script_opening_line: "Namaskaram, Madhav Homes. Meeku ela help cheyagalanu?",
    ...over,
  });
}

const TRIAL = {
  on_trial: true,
  status: "active",
  days_remaining: 7,
  ends_at: "2026-10-29T00:00:00Z",
  free_minutes: 15,
  minutes_used: 0,
  minutes_left: 15,
  calls_today: 1,
  daily_cap: 10,
  can_call: true,
  blocked_reason: null,
  max_call_seconds: 180,
  pledge_accepted: false,
};

const READINESS = {
  acceptance_statement: "By ticking, you accept on behalf of the business.",
  acceptance_statement_version: "s1",
  blockers: [],
  can_accept: true,
  can_accept_reason: null,
  documents: [
    {
      slug: "terms",
      title: "Terms of Service",
      version: "2026-10-01",
      state: "never_accepted",
      headline: "Not accepted yet",
      href: "/legal/terms",
      blocking: true,
      accepted_at: null,
      accepted_by_name: null,
      accepted_version: null,
      effective_date: "2026-10-01",
      provisional: false,
    },
  ],
  may_operate: false,
  outstanding_documents: 1,
  pending_legal_review: false,
  provisional_notice: null,
  verdict: "blocked",
};

const PLEDGE = {
  accepted_at: null,
  accepted_version: null,
  is_current: false,
  pledge_text: "We only call people who asked us to.",
  text_sha256: "b".repeat(64),
  version: "1",
};

function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": OWNER_ME,
    "/v1/first-run": run(),
    "/v1/agents": [],
    "/v1/business-profile": businessProfileFixture(),
    "/v1/business-copy": { placeholders: null, steps: [], caller_details: [], example_questions: [], language: null, generated_at: null, refresh: null },
    "/v1/copilot/consent": { status: "accepted", can_accept: true, can_withdraw: true, text: "", text_sha256: "a", version: 1, accepted_at: null, withdrawn_at: null },
    "/v1/agents/engine-catalogue": { available: true, voices: [], models: [] },
    ...over,
  };
}

describe("the pieces and where an owner resumes", () => {
  it("starts above zero, with only the account done", () => {
    const pieces = piecesOf({ run: run(), agent: null, calls: undefined });
    expect(pieces.filter((piece) => piece.done).map((piece) => piece.id)).toEqual(["account"]);
    expect(pieces).toHaveLength(9);
  });

  it("resumes on the step the server's rows say", () => {
    expect(resumeStage({ run: run(), agent: null, calls: undefined })).toBe("job");
    expect(resumeStage({ run: run({ jobs: ["call_leads"] }), agent: null, calls: undefined })).toBe("brief");
    expect(resumeStage({ run: run({ jobs: ["call_leads"], brief: "x" }), agent: null, calls: undefined })).toBe("questions");
    const building = run({ jobs: ["call_leads"], build: { ...run().build, status: "building" } });
    expect(resumeStage({ run: building, agent: null, calls: undefined })).toBe("build");
    expect(resumeStage({ run: built(), agent: agent(), calls: [] })).toBe("hear");
    expect(resumeStage({ run: built({ finished_at: "2026-10-23T05:00:00Z" }), agent: agent(), calls: [] })).toBe("team");
  });

  it("follows only the first run's own agent", () => {
    expect(firstAgentOf([agent()], built())?.id).toBe(AGENT_ID);
    expect(firstAgentOf([agent()], run())).toBeNull();
    expect(firstAgentOf([agent({ status: "archived" })], built())).toBeNull();
  });

  it("counts a short greeting that ends on a question, in characters a person counts", () => {
    expect(greetingFits("Namaskaram! How can I help?")).toBe(true);
    expect(greetingFits("Namaskaram, how can I help.")).toBe(false);
    expect(greetingFits(`${"అ".repeat(GREETING_MAX_CHARS - 1)}?`)).toBe(true);
    expect(greetingFits(`${"a".repeat(GREETING_MAX_CHARS)}?`)).toBe(false);
  });

  it("keeps the greeting ceiling the server's guide and the build worker name", () => {
    const guide = readFileSync(resolve(__dirname, "../../api/copilot/screen_guides.py"), "utf8");
    expect(guide).toMatch(new RegExp(`FIRST_GREETING_MAX_CHARS: Final = ${GREETING_MAX_CHARS}\\b`));
    const worker = readFileSync(resolve(__dirname, "../../workers/first_run.py"), "utf8");
    expect(worker).toMatch(new RegExp(`GREETING_MAX_CHARS: Final = ${GREETING_MAX_CHARS}\\b`));
  });

  it("starts in the profile's first language we sell, else Telugu", () => {
    expect(defaultLanguage(["hi-IN", "en-IN"])).toBe("hi-IN");
    expect(defaultLanguage(["ta-IN"])).toBe("te-IN");
    expect(defaultLanguage(undefined)).toBe("te-IN");
  });

  it("says what a test call costs from the server's figures, calls rounded down", () => {
    expect(callsLeft(15, 180)).toBe(5);
    expect(callsLeft(4, 180)).toBe(1);
    expect(callsLeft(null, 180)).toBeNull();
    expect(trialMinutesLine(TRIAL)).toBe(
      "Test calls use your 15 free trial minutes: 15 left, about 5 calls. Each call stops at 3 minutes. You can make 10 a day (1 today).",
    );
  });

  it("records in WebM where it can and MP4 on an older iPhone", () => {
    expect(recordingMimeType((type) => type.startsWith("audio/webm"))).toBe("audio/webm;codecs=opus");
    expect(recordingMimeType((type) => type === "audio/mp4")).toBe("audio/mp4");
    expect(recordingMimeType(() => false)).toBe("");
  });

  it("sends only the questions answered, each in its kind's field", () => {
    const question = (id: string, kind: FirstRunQuestion["kind"]): FirstRunQuestion => ({
      id,
      prompt: "?",
      hint: "",
      kind,
      options: [],
      maps_to: null,
    });
    const questions = [
      question("q1", "choices"),
      question("q2", "address"),
      question("q3", "services"),
      question("q4", "single_choice"),
      question("q5", "text"),
    ];
    const entry = {
      choices: [] as string[],
      text: "",
      offer: [{ name: "", price: "" }],
      hours: { opens: "09:00", closes: "18:00", closed: ["sun" as const] },
    };
    const draft = {
      q1: { ...entry, choices: ["Villas"] },
      q2: { ...entry, text: " Kondapur " },
      q3: {
        ...entry,
        offer: [
          { name: "Villa", price: "₹95,00,000" },
          { name: "", price: "" },
        ],
      },
      q4: { ...entry, choices: ["Yes"] },
    };
    expect(answersOf(questions, draft, new Set(["q1", "q2", "q3", "q4", "q5"]))).toEqual({
      answers: [
        { id: "q1", choices: ["Villas"] },
        { id: "q2", text: "Kondapur" },
        { id: "q3", services: [{ name: "Villa", price_inr: "9500000" }] },
        { id: "q4", choices: ["Yes"] },
      ],
    });
    expect(answersOf(questions, draft, new Set())).toEqual({ answers: [] });
  });

  it("says what really happened at each build step, fallbacks included", () => {
    expect(metaOf({ step: "voice", state: "done", label: "Lakshmi", rung: "studio", fallback: null, not_female: false })).toBe("Lakshmi · Studio");
    expect(metaOf({ step: "voice", state: "done", label: "Bindu", rung: "clear", fallback: "studio_minutes_used", not_female: false })).toBe(
      "Bindu · Clear. Your trial's Studio minutes are used, so it uses a Clear voice.",
    );
    expect(studioFallbackLine("studio_unavailable")).toBe("Studio voices aren't available right now, so it uses a Clear voice.");
    expect(studioFallbackLine(null)).toBeNull();
    expect(metaOf({ step: "voice", state: "done", label: "Bindu", rung: "clear", fallback: "no_female_studio_voice", not_female: false })).toBe(
      "Bindu · Clear. No Studio woman's voice speaks this language yet, so it uses a Clear voice.",
    );
    expect(metaOf({ step: "voice", state: "done", label: "Ravi", rung: "studio", fallback: null, not_female: true })).toBe(
      `Ravi · Studio. ${NOT_FEMALE_LINE}`,
    );
    expect(voicePickNote(null, false)).toBeNull();
    expect(NOT_FEMALE_LINE).not.toMatch(/thinnest|cartesia/i);
    expect(metaOf({ step: "voice", state: "none", label: null, not_female: false })).toMatch(/Pick one before the call/);
    expect(metaOf({ step: "script", state: "ready_made", label: null, not_female: false })).toMatch(/ready-made script/);
  });
});

describe("meet your agent", () => {
  it("opens on its job with three cards, all open, and the meter at one of nine", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        "PUT /v1/first-run/job": run({ jobs: ["call_new_leads"], language_primary: "te-IN", languages_extra: ["en-IN"] }),
      }),
    );
    expect(await screen.findByRole("heading", { name: "What should your agent do?" })).toBeTruthy();
    for (const name of [/Answer my calls/, /Call new leads instantly/, /Run calling campaigns/]) {
      expect((screen.getByRole("radio", { name }) as HTMLInputElement).disabled).toBe(false);
    }
    expect(screen.getByText("1 of 9 ready")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: /Call new leads instantly/ }));
    fireEvent.click(screen.getByRole("button", { name: /Continue/ }));
    await waitFor(() => expect(calls.some((call) => call.method === "PUT" && call.path === "/v1/first-run/job")).toBe(true));
    const sent = calls.find((call) => call.method === "PUT" && call.path === "/v1/first-run/job");
    expect(JSON.parse(sent?.body ?? "{}")).toEqual({ jobs: ["call_new_leads"], language_primary: "te-IN", languages_extra: ["en-IN"] });
    expect(await screen.findByRole("heading", { name: "Tell it about your business" })).toBeTruthy();
  });

  it("starts the brief from the trade's example and says the audio is not kept", async () => {
    await renderClientPage(page, routes({ "/v1/first-run": run({ jobs: ["answer_calls"], language_primary: "te-IN" }) }));
    const box = (await screen.findByRole("textbox", { name: "About your business" })) as HTMLTextAreaElement;
    expect(box.value.length).toBeGreaterThan(20);
    expect(screen.getByText("Your recording is turned into text. The audio is not kept.")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Talk it through with Pip instead/ })).toBeTruthy();
  });

  it("shows the build's real steps ticked, then the agent by name", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/first-run": built(),
        "/v1/agents": [agent()],
        [`/v1/calls?agent_id=${AGENT_ID}&limit=1`]: [],
        "/v1/trial": TRIAL,
        "/v1/legal/readiness": READINESS,
        "/v1/compliance/outbound-pledge": PLEDGE,
      }),
    );
    // A built agent with no call yet resumes on "Hear it".
    expect(await screen.findByRole("heading", { name: "Hear Anjali on your phone" })).toBeTruthy();
    expect(screen.getByText("It rings you and answers as if you had called Sri Clinic.")).toBeTruthy();
  });

  it("holds the call until every outstanding tick is ticked, then accepts each and rings", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/first-run": built(),
        "/v1/agents": [agent()],
        [`/v1/calls?agent_id=${AGENT_ID}&limit=1`]: [],
        "/v1/trial": TRIAL,
        "/v1/legal/readiness": READINESS,
        "/v1/compliance/outbound-pledge": PLEDGE,
        "POST /v1/legal/acceptances": { ...READINESS, documents: [], outstanding_documents: 0 },
        "POST /v1/compliance/outbound-pledge": { ...PLEDGE, is_current: true },
        [`POST /v1/agents/${AGENT_ID}/prepare`]: { status: "paused", changed: true, numbers_released: 0 },
        "POST /v1/trial/calls": { status: "queued", call_handle: "h1", blocked_reason: null, blocked_rule: null },
      }),
    );
    const call = await screen.findByRole("button", { name: /Call me now/ });
    fireEvent.change(screen.getByRole("textbox", { name: "Your mobile number" }), { target: { value: "98765 43210" } });
    expect((call as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: /I accept the Terms of Service/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /no-cold-calls pledge/ }));
    expect((call as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: /The number below is my own/ }));
    expect((call as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(call);
    expect(await screen.findByText("Ringing your phone…")).toBeTruthy();
    const posts = calls.filter((entry) => entry.method === "POST").map((entry) => entry.path);
    expect(posts).toEqual([
      "/v1/legal/acceptances",
      "/v1/compliance/outbound-pledge",
      `/v1/agents/${AGENT_ID}/prepare`,
      "/v1/trial/calls",
    ]);
    const placed = calls.find((entry) => entry.path === "/v1/trial/calls");
    expect(JSON.parse(placed?.body ?? "{}")).toMatchObject({ number_is_mine: true, agent_id: AGENT_ID });
  });

  it("says the trial line's refusal in the server's words", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/first-run": built(),
        "/v1/agents": [agent({ published: true })],
        [`/v1/calls?agent_id=${AGENT_ID}&limit=1`]: [],
        "/v1/trial": { ...TRIAL, can_call: false, blocked_reason: "You have used today's test calls." },
        "/v1/legal/readiness": { ...READINESS, documents: [], outstanding_documents: 0 },
        "/v1/compliance/outbound-pledge": { ...PLEDGE, is_current: true },
      }),
    );
    expect(await screen.findByText("You have used today's test calls.")).toBeTruthy();
  });

  it("refuses a member who may not build agents, in the console's own words", async () => {
    await renderClientPage(page, routes({ "/v1/me": { ...OWNER_ME, role: "staff", permissions: ["agents:read"] } }));
    expect(await screen.findByText(/build an agent/)).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "What should your agent do?" })).toBeNull();
  });

  it("puts the first run aside and goes to the dashboard", async () => {
    const { calls } = await renderClientPage(page, routes({ "POST /v1/first-run/dismiss": run({ due: false }) }));
    fireEvent.click(await screen.findByRole("button", { name: "Skip for now" }));
    await waitFor(() => expect(nav.pushed).toEqual(["/c/acme"]));
    expect(calls.some((call) => call.method === "POST" && call.path === "/v1/first-run/dismiss")).toBe(true);
  });
});
