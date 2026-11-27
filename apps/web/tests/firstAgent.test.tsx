
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BRIEF_TITLE } from "@/app/c/[slug]/agents/first/BriefStep";
import FirstAgentPage from "@/app/c/[slug]/agents/first/page";
import { callPhaseOf, isLimitRule } from "@/app/c/[slug]/agents/first/HearItStep";
import { hoursSummary } from "@/app/c/[slug]/agents/first/QuestionsStep";
import { goLiveSteps } from "@/app/c/[slug]/agents/first/ResultStep";
import { recordingMimeType } from "@/components/voiceButton";
import type { Agent } from "@/lib/api/agents";
import type { FirstRun, FirstRunQuestion } from "@/lib/api/firstRun";
import {
  NOT_FEMALE_LINE,
  briefWaitingFor,
  callsLeft,
  defaultLanguage,
  firstAgentOf,
  forgetCardPick,
  holdCardPick,
  jobToPost,
  readCardPick,
  firstWorkOf,
  jobFromBrief,
  jobsTitle,
  languageGlyph,
  piecesOf,
  resumeStage,
  stepIndexOf,
  studioFallbackLine,
  trialMinutesLine,
  voicePickNote,
  workHref,
  type FirstWork,
} from "@/lib/firstAgent";
import { answersBody, emptyAnswer } from "@/lib/firstRunQuestions";

import { businessProfileFixture } from "./businessProfileFixture";
import { OWNER_ME, agentRow } from "./fixtures/sharedReads";
import { NO_BUSINESS_COPY, problem, renderClientPage } from "./harness";

/** The brief typed in the 28 Nov trial run (docs/evidence/outpero-vs-calevate-2026-11-28). */
const BRIEF_TEXT =
  "We are Rytu Khata, an app that helps farmers keep their farm expenses, crop sales and profit on their phone. " +
  "Call farmers who registered on our website rytukhata.com but have not started using the app. Help them install " +
  "it on their phone's home screen from rytukhata.com (Android: Chrome, iPhone: Safari, Add to Home Screen), log in " +
  "with their mobile number, set the app language to Telugu, add their farm in My Farms, then enter their first " +
  "expense and their first sale. Go one step at a time and wait for them. If they are busy, ask when to call back. " +
  "If they don't remember registering, explain what Rytu Khata is and offer to help.";

/** The placeholders every generated copy carries; a test sets the one it is about. */
const PLACEHOLDERS_FOR_BRIEF = {
  end_call_rules: "Always offer a call back.",
  extraction_label: "What they need",
  extraction_options: "New, Returning",
  extraction_reason: "so we can help them first",
  knowledge_answer: "We help you set up the app.",
  knowledge_title: "Getting started",
  lead_search: "help with setup",
  script_brief: "",
};

/**
 * "MEET YOUR AGENT" (D-855, Phase 3b): about the business, the questions, the agent's name
 * and voice, what it does first (a draft line or campaign Pip writes), one honest screen
 * before the call, the call, and what it caught.
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
  // The first card's pick is held in sessionStorage, which outlives a test.
  sessionStorage.clear();
});

const page = <FirstAgentPage params={Promise.resolve({ slug: "acme" })} />;
const AGENT_ID = "0192f3a4-0000-7000-8000-00000000a001";
const LINE_ID = "0192f3a4-0000-7000-8000-00000000b001";
const OPENING = "Namaskaram, Madhav Homes. Meeku ela help cheyagalanu?";

/** The draft line "Answer my calls" made, as `GET /v1/inbound-lines/{id}` answers. */
function lineRow(over: Record<string, unknown> = {}) {
  return {
    id: LINE_ID,
    name: "Calls to your number",
    agent_id: AGENT_ID,
    agent_name: "Anjali",
    main_task: "We sell flats in Kondapur.",
    script: { opening_line: OPENING },
    proposal: null,
    version: 1,
    published_at: null,
    live: false,
    actions_off: [],
    source_ids: [],
    numbers: [],
    created_at: "2026-11-16T00:00:00Z",
    ...over,
  };
}

const STEPS = ["voice", "script", "greeting", "notice"] as const;

function run(over: Partial<FirstRun> = {}): FirstRun {
  return {
    due: true,
    jobs: [],
    language_primary: null,
    languages_extra: [],
    brief: null,
    documents: [],
    documents_left: 3,
    agent_id: null,
    questions: { status: "idle", items: [], disclosure: null },
    build: {
      status: "idle",
      steps: STEPS.map((step) => ({ step, state: "waiting", label: null, not_female: false, documents_used: 0 })),
      disclosure: null,
      builds_left: 3,
    },
    recordings_left: 3,
    finished_at: null,
    dismissed_at: null,
    line_id: null,
    campaign_id: null,
    default_agent: { name: "Anjali", voice_id: null, gender: "female" },
    ...over,
  };
}

/** The agent made on "Name and voice", with a draft line from "What first?". */
function built(over: Partial<FirstRun> = {}): FirstRun {
  return run({
    jobs: ["answer_calls"],
    language_primary: "te-IN",
    languages_extra: ["en-IN"],
    brief: "We sell flats in Kondapur.",
    agent_id: AGENT_ID,
    line_id: LINE_ID,
    questions: { status: "ready", items: [], disclosure: null },
    ...over,
  });
}

/** What a drafted line looks like to the screen, once its script is written. */
const WORK: FirstWork = { kind: "line", id: LINE_ID, ready: true, writing: false, failed: false, opening: OPENING };

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
    "/v1/kb/knows": { facts: [], facts_state: "none", items: [], pinned_not_yet_on: [] },
    [`/v1/inbound-lines/${LINE_ID}`]: lineRow(),
    [`/v1/agents/${AGENT_ID}`]: agent(),
    [`/v1/calls?agent_id=${AGENT_ID}&limit=1`]: [],
    "/v1/copilot/conversation?limit=50": { turns: [], has_more: false },
    ...over,
  };
}

describe("what the brief's Continue waits for", () => {
  const doc = (state: "reading" | "read" | "failed") =>
    ({ upload_id: state, name: `${state}.pdf`, source_kind: "pdf", state, detail: null, reaches_agents: true }) as const;

  it("waits for words being heard, a file being sent, then files being read; never for a failed or read one", () => {
    expect(briefWaitingFor({ documents: [], sending: false, hearing: true })).toBe("Waiting for your words to reach the box.");
    expect(briefWaitingFor({ documents: [], sending: true, hearing: false })).toBe("Waiting for your file to finish sending.");
    expect(briefWaitingFor({ documents: [doc("reading")], sending: false, hearing: false })).toBe(
      "Waiting for your file to be read. Or remove it.",
    );
    expect(briefWaitingFor({ documents: [doc("reading"), doc("reading")], sending: false, hearing: false })).toBe(
      "Waiting for your files to be read. Or remove them.",
    );
    expect(briefWaitingFor({ documents: [doc("failed"), doc("read")], sending: false, hearing: false })).toBeNull();
  });
});

describe("the pieces and where an owner resumes", () => {
  it("starts above zero, with only the account done", () => {
    const pieces = piecesOf({ run: run(), agent: null, calls: undefined });
    expect(pieces.filter((piece) => piece.done).map((piece) => piece.id)).toEqual(["account"]);
    expect(pieces).toHaveLength(7);
    const working = piecesOf({ run: built(), agent: agent(), calls: [], work: WORK });
    expect(working.filter((piece) => !piece.done).map((piece) => piece.id)).toEqual(["call"]);
  });

  it("resumes on the step the server's rows say", () => {
    expect(resumeStage({ run: run(), agent: null, calls: undefined })).toBe("brief");
    expect(resumeStage({ run: run({ brief: "x" }), agent: null, calls: undefined })).toBe("questions");
    const named = run({ brief: "x", agent_id: AGENT_ID });
    expect(resumeStage({ run: named, agent: agent(), calls: undefined, work: null })).toBe("agent");
    const writing = { ...WORK, ready: false, writing: true, opening: null };
    // A script Pip is still writing waits on Hear it; "What first?" is never resumed on.
    expect(resumeStage({ run: built(), agent: agent(), calls: [], work: writing })).toBe("hear");
    expect(resumeStage({ run: built(), agent: agent(), calls: [], work: WORK })).toBe("hear");
    expect(resumeStage({ run: built({ finished_at: "2026-10-23T05:00:00Z" }), agent: agent(), calls: [] })).toBe("team");
    expect(stepIndexOf("team")).toBe(3);
    expect(stepIndexOf("questions")).toBe(0);
    // The fallback "What first?" sits under Name and voice on the rail of three.
    expect(stepIndexOf("work")).toBe(1);
  });

  it("holds the card's pick per account, survives bad storage, and posts only what is not drafted yet", () => {
    sessionStorage.clear();
    expect(readCardPick("acme")).toEqual({ job: null, language: null });
    holdCardPick("acme", { job: "call_leads" });
    holdCardPick("acme", { language: "hi-IN" });
    expect(readCardPick("acme")).toEqual({ job: "call_leads", language: "hi-IN" });
    expect(readCardPick("other")).toEqual({ job: null, language: null });
    sessionStorage.setItem("calevate:first-run-card:acme", '{"job":"sell_things","language":7}');
    expect(readCardPick("acme")).toEqual({ job: null, language: null });
    sessionStorage.setItem("calevate:first-run-card:acme", "not json");
    expect(readCardPick("acme")).toEqual({ job: null, language: null });
    forgetCardPick("acme");
    expect(sessionStorage.getItem("calevate:first-run-card:acme")).toBeNull();
    const broken = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    expect(readCardPick("acme")).toEqual({ job: null, language: null });
    broken.mockRestore();

    expect(jobToPost(null, run(), null)).toBeNull();
    expect(jobToPost("answer_calls", run(), null)).toBe("answer_calls");
    expect(jobToPost("answer_calls", built(), WORK)).toBeNull();
    // The other job drafts that work too.
    expect(jobToPost("call_leads", built(), WORK)).toBe("call_leads");
  });

  it("reads the first work from the line or campaign it drafted, and links to its page", () => {
    expect(firstWorkOf(run(), {})).toBeNull();
    const drafting = { script: null, proposal: { status: "drafting" } };
    expect(firstWorkOf(built(), { line: drafting })).toMatchObject({ kind: "line", ready: false, writing: true });
    expect(firstWorkOf(built(), { line: lineRow() })).toEqual(WORK);
    const campaign = built({ jobs: ["call_leads"], campaign_id: "c1" });
    const failed = { script: null, proposal: { status: "failed" } };
    expect(firstWorkOf(campaign, { campaign: failed })).toMatchObject({ kind: "campaign", id: "c1", failed: true });
    expect(workHref("acme", WORK)).toBe(`/c/acme/inbound/${LINE_ID}`);
    expect(workHref("acme", { ...WORK, kind: "campaign", id: "c1" })).toBe("/c/acme/campaigns/c1?tab=script");
  });

  it("follows only the first run's own agent", () => {
    expect(firstAgentOf([agent()], built())?.id).toBe(AGENT_ID);
    expect(firstAgentOf([agent()], run())).toBeNull();
    expect(firstAgentOf([agent({ status: "archived" })], built())).toBeNull();
  });

  it("starts in the profile's first language the server offers, else the server's first", () => {
    const offered = ["te-IN", "hi-IN", "en-IN"];
    expect(defaultLanguage(["hi-IN", "en-IN"], offered)).toBe("hi-IN");
    expect(defaultLanguage(["ta-IN"], offered)).toBe("te-IN");
    expect(defaultLanguage(undefined, offered)).toBe("te-IN");
    expect(defaultLanguage(["ta-IN"], [...offered, "ta-IN"])).toBe("ta-IN");
    expect(defaultLanguage(undefined, ["ta-IN", "en-IN"])).toBe("ta-IN");
    expect(defaultLanguage(undefined, [])).toBeNull();
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

  it("sends only the questions answered, each with only its kind's field", () => {
    const ask = (id: string, kind: FirstRunQuestion["kind"], options: string[] = []): FirstRunQuestion => ({
      id,
      kind,
      prompt: id,
      hint: "",
      options,
      maps_to: null,
    });
    const questions = [
      ask("q1", "choices", ["Villas", "Plots"]),
      ask("q2", "address"),
      ask("q3", "services"),
      ask("q4", "text"),
      ask("q5", "single_choice", ["Yes", "No"]),
    ];
    const answers = {
      q1: { ...emptyAnswer("q1"), choices: ["Villas"], text: "left over" },
      q2: { ...emptyAnswer("q2"), text: " Kondapur " },
      q3: { ...emptyAnswer("q3"), services: [{ name: "Villa", price: "₹95,00,000" }, { name: "", price: "" }] },
      q4: emptyAnswer("q4"),
      q5: { ...emptyAnswer("q5"), choices: ["Yes"] },
    };
    expect(answersBody(questions, answers)).toEqual({
      answers: [
        { id: "q1", choices: ["Villas"] },
        { id: "q2", text: "Kondapur" },
        { id: "q3", services: [{ name: "Villa", price_inr: "9500000" }] },
        { id: "q5", choices: ["Yes"] },
      ],
    });
    expect(answersBody(questions, {})).toEqual({ answers: [] });
  });

  it("reads the open days and times back as one sentence", () => {
    expect(hoursSummary({ opens: "09:00", closes: "18:00", closed: ["sun"] })).toBe("Mon to Sat, 9am to 6pm");
    expect(hoursSummary({ opens: "10:30", closes: "13:00", closed: ["tue", "thu", "sun"] })).toBe(
      "Mon, Wed, Fri, Sat, 10:30am to 1pm",
    );
    expect(hoursSummary({ opens: "00:00", closes: "23:59", closed: [] })).toBe("Every day, 12am to 11:59pm");
  });

  it("names its works by their cards and a language by its own script", () => {
    expect(jobsTitle(["call_leads", "answer_calls"])).toBe("Answer my calls + 1 more");
    expect(jobsTitle(["call_leads"])).toBe("Call people");
    expect(languageGlyph("te-IN")).toBe("తె");
  });

  it("shows the call as its row says, and a limit as a limit", () => {
    const base = { preparing: false, placing: false, placedStatus: "queued" as const, callStatus: null, refused: false, failed: false, limit: false };
    expect(callPhaseOf({ ...base, preparing: true, placedStatus: null })).toBe("preparing");
    expect(callPhaseOf({ ...base, placing: true, placedStatus: null })).toBe("dialling");
    expect(callPhaseOf(base)).toBe("dialling");
    expect(callPhaseOf({ ...base, callStatus: "ringing" })).toBe("ringing");
    expect(callPhaseOf({ ...base, callStatus: "in_progress" })).toBe("talking");
    expect(callPhaseOf({ ...base, callStatus: "completed" })).toBe("ended");
    expect(callPhaseOf({ ...base, callStatus: "no_answer" })).toBe("missed");
    expect(callPhaseOf({ ...base, placedStatus: "blocked", limit: true })).toBe("limit");
    expect(callPhaseOf({ ...base, failed: true })).toBe("error");
    expect(isLimitRule("trial_daily_cap")).toBe(true);
    expect(isLimitRule("trial_minutes_used")).toBe(true);
    expect(isLimitRule("trial_line_busy")).toBe(false);
  });

  it("reads the first work from a brief only when it plainly asks for one", () => {
    expect(jobFromBrief(BRIEF_TEXT)).toBe("call_leads");
    expect(jobFromBrief("We call our registered users to remind them of renewals.")).toBe("call_leads");
    expect(jobFromBrief("Answer our calls after hours and note what people need.")).toBe("answer_calls");
    expect(jobFromBrief("When customers call us, take their order.")).toBe("answer_calls");
    // A call back is not a list of people to call; neither, or both, suggests nothing.
    expect(jobFromBrief("We sell flats in Kondapur. If they are busy, call back later.")).toBeNull();
    expect(jobFromBrief("Answer incoming calls and call new leads every morning.")).toBeNull();
    expect(jobFromBrief(null)).toBeNull();
  });

  it("says why the default voice is not a woman's Studio voice, naming no provider", () => {
    expect(studioFallbackLine("studio_unavailable")).toBe("Studio voices aren't available right now, so it uses a Clear voice.");
    expect(studioFallbackLine(null)).toBeNull();
    expect(voicePickNote("studio_minutes_used", true)).toBe(
      `Your trial's Studio minutes are used, so it uses a Clear voice. ${NOT_FEMALE_LINE}`,
    );
    expect(voicePickNote(null, false)).toBeNull();
    expect(NOT_FEMALE_LINE).not.toMatch(/thinnest|cartesia/i);
  });
});

describe("meet your agent", () => {
  it("picks the profile's language even when the profile arrives after the first-run read", async () => {
    let release = () => undefined as void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    await renderClientPage(
      page,
      routes({
        "/v1/first-run": run({ brief: "We sell flats.", questions: { status: "ready", items: [], disclosure: null } }),
        "/v1/business-profile": () =>
          new Response(
            new ReadableStream({
              async start(controller) {
                await gate;
                controller.enqueue(new TextEncoder().encode(JSON.stringify(businessProfileFixture({ languages: ["hi-IN"] }))));
                controller.close();
              },
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          ),
      }),
    );
    // The first-run read has landed (the meter counts) while the profile is still on its way.
    expect(await screen.findByText("2 of 7 ready")).toBeTruthy();
    fireEvent.click(await screen.findByRole("button", { name: /Continue/ }));
    release();
    await waitFor(() =>
      expect((screen.getByRole("radio", { name: /Hindi/ }) as HTMLInputElement).checked).toBe(true),
    );
  });

  it("opens on About your business, with the meter at one of seven", async () => {
    await renderClientPage(page, routes());
    expect(await screen.findByRole("heading", { name: BRIEF_TITLE })).toBeTruthy();
    expect(screen.getByText("1 of 7 ready")).toBeTruthy();
    // The first step: nothing to go back to.
    expect(screen.queryByRole("button", { name: /^Back$/ })).toBeNull();
    expect(screen.getByText("Step 1 of 3 ·", { exact: false })).toBeTruthy();
  });

  it("makes the agent from the default agent's name and the language picked, then offers its voice", async () => {
    const atName = run({ brief: "We sell flats.", questions: { status: "ready", items: [], disclosure: null } });
    const named = { ...atName, agent_id: AGENT_ID, language_primary: "te-IN", languages_extra: ["en-IN"] };
    const table = routes({ "/v1/first-run": atName, "PUT /v1/first-run/agent": named });
    const { calls } = await renderClientPage(page, table);
    fireEvent.click(await screen.findByRole("button", { name: /Continue/ }));
    expect(await screen.findByRole("heading", { name: "Name your agent and pick its voice" })).toBeTruthy();
    expect((screen.getByRole("textbox", { name: "Its name" }) as HTMLInputElement).value).toBe("Anjali");
    expect((screen.getByRole("radio", { name: /Telugu/ }) as HTMLInputElement).checked).toBe(true);
    // No script is written on this step: there is nothing to write.
    expect(screen.queryByText(/opening line/i)).toBeNull();
    (table as Record<string, unknown>)["/v1/agents"] = [agent()];
    fireEvent.click(screen.getByRole("button", { name: /Choose its voice/ }));
    await waitFor(() => expect(calls.some((call) => call.method === "PUT" && call.path === "/v1/first-run/agent")).toBe(true));
    const sent = calls.find((call) => call.path === "/v1/first-run/agent");
    expect(JSON.parse(sent?.body ?? "{}")).toMatchObject({ name: "Anjali", language_primary: "te-IN" });
    expect(await screen.findByRole("heading", { name: "Its voice" })).toBeTruthy();
  });

  it("takes the job and language on the first card, then posts the job once the agent is made, with no What first? screen", async () => {
    const typed = "We sell flats in Kondapur.";
    const briefed = run({ brief: typed, questions: { status: "ready", items: [], disclosure: null } });
    const named = { ...briefed, agent_id: AGENT_ID, language_primary: "hi-IN", languages_extra: ["en-IN"] };
    const drafted = { ...named, jobs: ["answer_calls" as const], line_id: LINE_ID };
    const table: Record<string, unknown> = routes({
      "PUT /v1/first-run/brief": briefed,
      "PUT /v1/first-run/agent": named,
      "POST /v1/first-run/work": drafted,
      [`/v1/agents/engine-catalogue?agent_id=${AGENT_ID}`]: { available: true, voices: [], models: [] },
      "/v1/trial": TRIAL,
      "/v1/legal/readiness": READINESS,
      "/v1/compliance/outbound-pledge": PLEDGE,
    });
    const { calls } = await renderClientPage(page, table);
    const box = (await screen.findByRole("textbox", { name: BRIEF_TITLE })) as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: typed } });
    // The brief names no job, so Continue waits for one, saying so.
    const go = screen.getByRole("button", { name: /Continue/ });
    expect(go.getAttribute("aria-disabled")).toBe("true");
    expect(screen.getByText("Pick what it does first.")).toBeTruthy();
    // No generated copy yet: no examples to tap in.
    expect(screen.queryByRole("button", { name: "Examples" })).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: /Answer my calls/ }));
    fireEvent.change(screen.getByRole("combobox", { name: "Speaks first in" }), { target: { value: "hi-IN" } });
    fireEvent.click(go);
    await waitFor(() => expect(calls.some((call) => call.method === "PUT" && call.path === "/v1/first-run/brief")).toBe(true));
    expect(JSON.parse(calls.find((call) => call.path === "/v1/first-run/brief")?.body ?? "{}")).toEqual({ brief: typed });
    // The job cannot go before there is an agent.
    expect(calls.some((call) => call.path === "/v1/first-run/work")).toBe(false);
    table["/v1/first-run"] = briefed;

    // The questions (none here), then Name and voice in the card's language.
    fireEvent.click(await screen.findByRole("button", { name: /Continue/ }));
    expect(await screen.findByRole("heading", { name: "Name your agent and pick its voice" })).toBeTruthy();
    expect((screen.getByRole("radio", { name: /Hindi/ }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText("Step 2 of 3 ·", { exact: false })).toBeTruthy();
    table["/v1/agents"] = [agent({ language_primary: "hi-IN" })];
    table["/v1/first-run"] = named;
    fireEvent.click(screen.getByRole("button", { name: /Choose its voice/ }));
    await waitFor(() => expect(calls.some((call) => call.method === "POST" && call.path === "/v1/first-run/work")).toBe(true));
    expect(JSON.parse(calls.find((call) => call.path === "/v1/first-run/work")?.body ?? "{}")).toEqual({ job: "answer_calls" });
    expect(JSON.parse(calls.find((call) => call.path === "/v1/first-run/agent")?.body ?? "{}")).toMatchObject({
      language_primary: "hi-IN",
    });
    await waitFor(() => expect(readCardPick("acme").job).toBeNull());
    table["/v1/first-run"] = drafted;

    // Continue after the voice goes straight to Hear it.
    expect(await screen.findByRole("heading", { name: "Its voice" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Continue/ }));
    expect(await screen.findByRole("heading", { name: "Hear Anjali on your phone" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "What should Anjali do first?" })).toBeNull();
    expect(calls.filter((call) => call.path === "/v1/first-run/work")).toHaveLength(1);
  });

  it("ticks the job the brief plainly asks for on the card, and the owner's tap wins", async () => {
    await renderClientPage(page, routes());
    const box = (await screen.findByRole("textbox", { name: BRIEF_TITLE })) as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: BRIEF_TEXT } });
    expect((screen.getByRole("radio", { name: /Call people/ }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText("Ticked from what you wrote. Change it if you like.")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: /Answer my calls/ }));
    expect((screen.getByRole("radio", { name: /Answer my calls/ }) as HTMLInputElement).checked).toBe(true);
    expect(screen.queryByText("Ticked from what you wrote. Change it if you like.")).toBeNull();
    expect(readCardPick("acme").job).toBe("answer_calls");
  });

  it("offers the account's own examples, never the neutral ones, and adds a tapped one to the box once", async () => {
    const goal = "Help them install the app and add their first expense.";
    await renderClientPage(
      page,
      routes({
        "/v1/business-copy": { ...NO_BUSINESS_COPY, placeholders: { ...PLACEHOLDERS_FOR_BRIEF, call_goal: goal } },
      }),
    );
    const box = (await screen.findByRole("textbox", { name: BRIEF_TITLE })) as HTMLTextAreaElement;
    fireEvent.click(await screen.findByRole("button", { name: "Examples" }));
    const list = screen.getByRole("list", { name: "Examples for your business" });
    // Only what the copy wrote: its empty brief and the neutral set are not offered.
    expect(within(list).getAllByRole("button")).toHaveLength(1);
    fireEvent.click(within(list).getByRole("button", { name: /What a good call does/ }));
    expect(box.value).toBe(goal);
    expect((within(list).getByRole("button", { name: /What a good call does/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("waits on Hear it while Pip writes what the work says", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/first-run": built(),
        "/v1/agents": [agent()],
        [`/v1/inbound-lines/${LINE_ID}`]: lineRow({ script: null, proposal: { id: "p1", status: "drafting", requested_at: "2026-11-16T00:00:00Z", left_out: [] } }),
      }),
    );
    expect(await screen.findByRole("heading", { name: "Hear Anjali on your phone" })).toBeTruthy();
    expect(screen.getByText("Pip is writing what it says…")).toBeTruthy();
    expect(screen.getByText("Step 3 of 3 ·", { exact: false })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Call me now/ })).toBeNull();
  });

  it("with the card's pick lost, shows What first? once, ticked from the brief, drafting only on Continue (C9)", async () => {
    const named = built({ line_id: null, jobs: [], brief: BRIEF_TEXT });
    const drafted = built({ line_id: null, campaign_id: LINE_ID, jobs: ["call_leads"], brief: BRIEF_TEXT });
    const table = routes({
      "/v1/first-run": named,
      "/v1/agents": [agent()],
      [`/v1/calls?agent_id=${AGENT_ID}&limit=1`]: [],
      "POST /v1/first-run/work": drafted,
      [`/v1/campaigns/${LINE_ID}/workspace`]: { script: null, proposal: { id: "p1", status: "drafting" } },
    });
    const { calls } = await renderClientPage(page, table);
    fireEvent.click(await screen.findByRole("button", { name: /Continue/ }));
    expect(await screen.findByRole("heading", { name: "What should Anjali do first?" })).toBeTruthy();
    expect((screen.getByRole("radio", { name: /Call people/ }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole("radio", { name: /Answer my calls/ }) as HTMLInputElement).checked).toBe(false);
    expect(screen.getByText("Ticked from what you wrote. Change it if you like.")).toBeTruthy();
    // Ticked is not drafted: nothing is written until the owner presses.
    expect(calls.some((call) => call.path === "/v1/first-run/work")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: /Continue/ }));
    await waitFor(() => expect(calls.some((call) => call.method === "POST" && call.path === "/v1/first-run/work")).toBe(true));
    expect(JSON.parse(calls.find((call) => call.path === "/v1/first-run/work")?.body ?? "{}")).toEqual({ job: "call_leads" });
  });

  it("drafts a line on Answer my calls, says Pip is writing it, and offers Hear it once written", async () => {
    const named = built({ line_id: null, jobs: [] });
    const drafted = built();
    const table = routes({
      "/v1/first-run": named,
      "/v1/agents": [agent()],
      [`/v1/calls?agent_id=${AGENT_ID}&limit=1`]: [],
      "PUT /v1/first-run/agent": named,
      "POST /v1/first-run/work": drafted,
      [`/v1/inbound-lines/${LINE_ID}`]: lineRow({ script: null, proposal: { id: "p1", status: "drafting", requested_at: "2026-11-16T00:00:00Z", left_out: [] } }),
    });
    const { calls } = await renderClientPage(page, table);
    // An agent with no work yet resumes on its name and voice; Continue goes on.
    fireEvent.click(await screen.findByRole("button", { name: /Continue/ }));
    expect(await screen.findByRole("heading", { name: "What should Anjali do first?" })).toBeTruthy();
    expect(screen.getAllByRole("radio")).toHaveLength(2);
    fireEvent.click(screen.getByRole("radio", { name: /Answer my calls/ }));
    await waitFor(() => expect(calls.some((call) => call.method === "POST" && call.path === "/v1/first-run/work")).toBe(true));
    expect(JSON.parse(calls.find((call) => call.path === "/v1/first-run/work")?.body ?? "{}")).toEqual({ job: "answer_calls" });
    expect(await screen.findByText("Pip is writing what it says…")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Hear it/ })).toBeNull();
  });

  it("shows the trade's example only as a placeholder, offers no other trade's, and says the audio is not kept", async () => {
    await renderClientPage(page, routes({ "/v1/first-run": run({ jobs: ["answer_calls"], language_primary: "te-IN" }) }));
    const box = (await screen.findByRole("textbox", { name: BRIEF_TITLE })) as HTMLTextAreaElement;
    // An example kept as the value would be saved on Continue as if the owner wrote it.
    expect(box.value).toBe("");
    expect(box.placeholder.length).toBeGreaterThan(20);
    expect(screen.queryByRole("heading", { name: "Start from another example" })).toBeNull();
    expect(screen.getByText(/Only the text is kept, not the audio./)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Talk it through with Pip instead/ })).toBeTruthy();
  });

  it("starts the brief from the account's own written brief once it has landed", async () => {
    const own = "We run an app that helps farmers keep their accounts. We call registered users to help them.";
    await renderClientPage(
      page,
      routes({
        "/v1/first-run": run({ jobs: ["answer_calls"], language_primary: "te-IN" }),
        "/v1/business-copy": { ...NO_BUSINESS_COPY, placeholders: { ...PLACEHOLDERS_FOR_BRIEF, script_brief: own } },
      }),
    );
    const box = (await screen.findByRole("textbox", { name: BRIEF_TITLE })) as HTMLTextAreaElement;
    await waitFor(() => expect(box.value).toBe(own));
    expect(screen.getByText("Written from your business details. Change anything.")).toBeTruthy();
  });

  it("keeps every key typed fast, and never puts the account's late brief into a box being typed in (C3-a)", async () => {
    let release = () => undefined as void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const own = "Help farmers view their farm data";
    const { calls } = await renderClientPage(
      page,
      routes({
        // The account's own brief is written by a job after sign-up and lands mid-step.
        "/v1/business-copy": () =>
          new Response(
            new ReadableStream({
              async start(controller) {
                await gate;
                const body = { ...NO_BUSINESS_COPY, placeholders: { ...PLACEHOLDERS_FOR_BRIEF, script_brief: own } };
                controller.enqueue(new TextEncoder().encode(JSON.stringify(body)));
                controller.close();
              },
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          ),
      }),
    );
    const box = (await screen.findByRole("textbox", { name: BRIEF_TITLE })) as HTMLTextAreaElement;
    expect(box.value).toBe("");
    // The owner puts the cursor in the empty box; the account's brief lands before the first key.
    act(() => box.focus());
    await act(async () => {
      release();
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(calls.some((call) => call.path === "/v1/business-copy")).toBe(true);
    expect(box.value).toBe("");
    // 803 characters, one key at a time with no delay, each built on what the box holds then,
    // as a browser does.
    const typed = `${BRIEF_TEXT} Free for farmers. Hyderabad, Telangana. Call only between 9am and 6pm.`.padEnd(803, " ok").slice(0, 803);
    for (const key of Array.from(typed)) fireEvent.input(box, { target: { value: box.value + key } });
    expect(box.value).toBe(typed);
    expect(box.value.length).toBe(803);
    expect(screen.getByText(`803 of 4000`)).toBeTruthy();
    expect(screen.queryByText("Written from your business details. Change anything.")).toBeNull();
  });

  it.each([
    ["Ravi", false],
    ["Akshita", true],
  ])("says the voice note only of the voice the build chose (%s), never of one picked since (C8-a)", async (built, said) => {
    const voice = (voice_id: string, label: string) => ({
      voice_id,
      label,
      rung: "studio",
      is_custom: false,
      language_note: "Speaks Telugu",
      offerable: true,
      preview_available: false,
      reason: null,
      standing: "offered",
    });
    const atVoice = (label: string) =>
      run({
        brief: "We sell flats.",
        agent_id: AGENT_ID,
        language_primary: "te-IN",
        questions: { status: "ready", items: [], disclosure: null },
        build: {
          ...run().build,
          steps: STEPS.map((step) =>
            step === "voice"
              ? { step, state: "done", label, rung: "studio", not_female: true, documents_used: 0 }
              : { step, state: "waiting", label: null, not_female: false, documents_used: 0 },
          ),
        },
      });
    const catalogue = { available: true, voices: [voice("engine:v1", "Akshita"), voice("engine:v2", "Ravi")], models: [] };
    await renderClientPage(
      page,
      routes({ "/v1/first-run": atVoice(built), "/v1/agents": [agent()], "/v1/agents/engine-catalogue": catalogue }),
    );
    const card = await screen.findByRole("complementary", { name: "Your agent as it takes shape" });
    expect(await within(card).findByText("Akshita")).toBeTruthy();
    expect(within(card).queryByText(NOT_FEMALE_LINE) !== null).toBe(said);
  });

  it("keeps what was typed in the brief through Pip and back (journey audit E1)", async () => {
    await renderClientPage(page, routes());
    const typed = "We repair two-wheelers in Guntur and pick them up from home.";
    const box = (await screen.findByRole("textbox", { name: BRIEF_TITLE })) as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: typed } });
    fireEvent.click(screen.getByRole("button", { name: /Talk it through with Pip instead/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Back to the steps/ }));
    const again = (await screen.findByRole("textbox", { name: BRIEF_TITLE })) as HTMLTextAreaElement;
    expect(again.value).toBe(typed);
  });

  it("lists the brief's files by state: being read, read but not on calls, and unreadable with a way to try another", async () => {
    const reading = "0192f3a4-0000-7000-8000-00000000d001";
    const pdf = "0192f3a4-0000-7000-8000-00000000d002";
    const broken = "0192f3a4-0000-7000-8000-00000000d003";
    const withFiles = run({
      jobs: ["answer_calls"],
      language_primary: "te-IN",
      documents: [
        { upload_id: reading, name: "menu.jpg", source_kind: "image", state: "reading", detail: null, reaches_agents: true },
        { upload_id: pdf, name: "prices.pdf", source_kind: "pdf", state: "read", detail: null, reaches_agents: false },
        { upload_id: broken, name: "old.xlsx", source_kind: "xlsx", state: "failed", detail: "No words found.", reaches_agents: true },
      ],
      documents_left: 0,
    });
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/first-run": withFiles,
        [`DELETE /v1/first-run/documents/${broken}`]: { ...withFiles, documents: withFiles.documents.slice(0, 2), documents_left: 1 },
      }),
    );
    await screen.findByText("That's the most for now. Add more under Knowledge.");
    const step = screen.getByRole("region", { name: "This step" });
    expect(within(step).getByText("menu.jpg")).toBeTruthy();
    expect(within(step).getByText("Reading it…")).toBeTruthy();
    expect(within(step).getByText("Read. Not used on calls yet.")).toBeTruthy();
    expect(within(step).getByText("Couldn't read this file.")).toBeTruthy();
    // At the bound, no picker: the line says where more go.
    expect(within(step).getByText("That's the most for now. Add more under Knowledge.")).toBeTruthy();
    fireEvent.click(within(step).getByRole("button", { name: "Try another file" }));
    await waitFor(() =>
      expect(calls.some((call) => call.method === "DELETE" && call.path === `/v1/first-run/documents/${broken}`)).toBe(true),
    );
  });

  it("greys Continue with its reason while a file is read, and gives it back by itself when the read lands", async () => {
    const MENU = "0192f3a4-0000-7000-8000-00000000d020";
    const menu = { upload_id: MENU, name: "menu.jpg", source_kind: "image", state: "reading", detail: null, reaches_agents: true } as const;
    const reading = run({ jobs: ["answer_calls"], language_primary: "te-IN", documents: [menu], documents_left: 2 });
    const table = routes({ "/v1/first-run": reading, "PUT /v1/first-run/brief": reading });
    const { calls } = await renderClientPage(page, table);
    const go = (await screen.findByRole("button", { name: /Continue/ })) as HTMLButtonElement;
    expect(go.getAttribute("aria-disabled")).toBe("true");
    // Still in the tab order, so its reason can be heard where it is.
    expect(go.disabled).toBe(false);
    const reason = screen.getByText("Waiting for your file to be read. Or remove it.");
    expect(go.getAttribute("aria-describedby")).toContain(reason.id);
    fireEvent.click(go);
    fireEvent.submit(go.closest("form")!);
    expect(calls.some((call) => call.path === "/v1/first-run/brief")).toBe(false);
    // The run is polled while a file is reading; the read lands and Continue comes back.
    table["/v1/first-run"] = { ...reading, documents: [{ ...menu, state: "read" }] };
    await waitFor(() => expect(go.getAttribute("aria-disabled")).toBeNull(), { timeout: 4000 });
    expect(screen.queryByText(/Waiting for your file/)).toBeNull();
    fireEvent.click(go);
    await waitFor(() =>
      expect(calls.filter((call) => call.method === "PUT" && call.path === "/v1/first-run/brief")).toHaveLength(1),
    );
  });

  it("does not hold Continue for a file that could not be read: it shows failed with Remove", async () => {
    const OLD = "0192f3a4-0000-7000-8000-00000000d021";
    const failed = run({
      jobs: ["answer_calls"],
      language_primary: "te-IN",
      documents: [{ upload_id: OLD, name: "old.xlsx", source_kind: "xlsx", state: "failed", detail: null, reaches_agents: true }],
      documents_left: 2,
    });
    await renderClientPage(page, routes({ "/v1/first-run": failed }));
    const go = (await screen.findByRole("button", { name: /Continue/ })) as HTMLButtonElement;
    expect(go.getAttribute("aria-disabled")).toBeNull();
    expect(screen.getByText("Couldn't read this file.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Remove old.xlsx" })).toBeTruthy();
  });

  it("uploads a brief file through the knowledge upload, then records it on the first run", async () => {
    const UPLOAD = "0192f3a4-0000-7000-8000-00000000d010";
    // `apiUpload` is an XMLHttpRequest (upload progress); `knowledgeUploads.test.tsx` has the full stub.
    const sentUploads: string[] = [];
    class UploadXhr {
      status = 0;
      responseText = "";
      withCredentials = false;
      readonly upload = new EventTarget();
      private readonly events = new EventTarget();
      private url = "";
      open(_method: string, url: string) {
        this.url = url;
      }
      setRequestHeader() {}
      getResponseHeader(name: string) {
        return name.toLowerCase() === "content-type" ? "application/json" : null;
      }
      addEventListener(type: string, listener: EventListener) {
        this.events.addEventListener(type, listener);
      }
      abort() {}
      send() {
        sentUploads.push(this.url);
        queueMicrotask(() => {
          this.status = 201;
          this.responseText = JSON.stringify({ id: UPLOAD, name: "menu.docx" });
          this.events.dispatchEvent(new Event("load"));
        });
      }
    }
    vi.stubGlobal("XMLHttpRequest", UploadXhr);
    const before = run({ jobs: ["answer_calls"], language_primary: "te-IN" });
    const { calls, container } = await renderClientPage(
      page,
      routes({
        "/v1/first-run": before,
        "POST /v1/first-run/documents": {
          ...before,
          documents: [
            { upload_id: UPLOAD, name: "menu.docx", source_kind: "docx", state: "reading", detail: null, reaches_agents: true },
          ],
          documents_left: 2,
        },
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Add a file" }));
    const input = container.querySelector<HTMLInputElement>("input[type=file]");
    const file = new File(["Idli 40"], "menu.docx", { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" });
    fireEvent.change(input!, { target: { files: [file] } });
    const step = screen.getByRole("region", { name: "This step" });
    expect(await within(step).findByText("Reading it…")).toBeTruthy();
    vi.unstubAllGlobals();
    expect(sentUploads).toHaveLength(1);
    expect(sentUploads[0].endsWith("/v1/kb/uploads")).toBe(true);
    expect(calls.filter((call) => call.method === "POST").map((call) => call.path)).toEqual(["/v1/first-run/documents"]);
    const linked = calls.find((call) => call.path === "/v1/first-run/documents");
    expect(JSON.parse(linked?.body ?? "{}")).toEqual({ upload_id: UPLOAD });
  });

  it("on the team step, Go live is the next step with its current step's button, from the go-live guide", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/first-run": built({ jobs: ["answer_calls", "call_new_leads"], finished_at: "2026-10-23T05:00:00Z" }),
        "/v1/agents": [agent()],
        [`/v1/calls?agent_id=${AGENT_ID}&limit=1`]: [],
        "/v1/trial": TRIAL,
        "/v1/go-live": { due: false, owed_at: null, finished_at: null, dismissed_at: null, current: "move", move: { state: "done", total: 0, agents: [] }, verify: "todo", number: "locked", numbers: 0, switch_on: "todo", live_agents: 0 },
      }),
    );
    expect(await screen.findByRole("heading", { name: "Anjali is on your team" })).toBeTruthy();
    const card = await screen.findByRole("region", { name: "Go live" });
    expect(within(card).getByRole("button", { name: "Add credit" })).toBeTruthy();
    expect(within(card).getByText("Verify your business")).toBeTruthy();
    expect(within(card).getAllByRole("button")).toHaveLength(1);
    expect(within(card).getByText("Until then, Anjali only makes test calls to you.")).toBeTruthy();
    const leads = screen.getByRole("region", { name: "Connect your lead form" });
    expect(within(leads).getByRole("link", { name: "Connect" }).getAttribute("href")).toBe("/c/acme/lead-sources");
    // What its work says first, read only: the words are changed on the work's own page.
    expect(screen.getAllByText(`“${OPENING}”`).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  });

  it("a finished run whose agent was deleted offers a new agent or the way back, never a blank step", async () => {
    // The roster's empty state ("Meet your agent") links here, so an owner who deleted their
    // only agent arrives on the team step with no agent to show.
    await renderClientPage(
      page,
      routes({
        "/v1/first-run": built({ finished_at: "2026-10-23T05:00:00Z" }),
        "/v1/agents": [],
      }),
    );
    // The step's section is drawn again once the stage is known, so it is found after the text.
    await screen.findByText("Your first agent was deleted.");
    const step = screen.getByRole("region", { name: "This step" });
    expect(within(step).getByRole("link", { name: "New agent" }).getAttribute("href")).toBe("/c/acme/agents/new");
    expect(within(step).getByRole("link", { name: "Bring it back" }).getAttribute("href")).toBe("/c/acme/agents");
  });

  it("puts the go-live steps in order, the first not done current, a review said as such", () => {
    expect(goLiveSteps(undefined).map((step) => step.state)).toEqual(["current", "waiting", "waiting", "waiting"]);
    const paid = { owed_at: "2026-10-27T10:00:00Z", verify: "in_review" as const, number: "locked" as const };
    expect(goLiveSteps(paid).map((step) => step.state)).toEqual(["done", "in_review", "waiting", "waiting"]);
    const verified = { owed_at: "2026-10-27T10:00:00Z", verify: "done" as const, number: "todo" as const };
    expect(goLiveSteps(verified).map((step) => step.state)).toEqual(["done", "done", "current", "waiting"]);
    // A number bought: the draft line it went to answers nobody until it is put live.
    const numbered = { ...verified, number: "done" as const, switch_on: "todo" as const };
    expect(goLiveSteps(numbered).map((step) => [step.id, step.state])).toEqual([
      ["credit", "done"],
      ["verify", "done"],
      ["number", "done"],
      ["live", "current"],
    ]);
    expect(goLiveSteps({ ...numbered, switch_on: "done" }).every((step) => step.state === "done")).toBe(true);
  });

  it("resumes a drafted, written line on Hear it, showing what the line says first", async () => {
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
    // A written line with no call yet resumes on "Hear it".
    expect(await screen.findByRole("heading", { name: "Hear Anjali on your phone" })).toBeTruthy();
    expect(screen.getByText("It rings you and answers as if you had called Sri Clinic.")).toBeTruthy();
    const step = screen.getByRole("region", { name: "This step" });
    expect(within(step).getByText(`“${OPENING}”`)).toBeTruthy();
    expect(within(step).queryByRole("button", { name: "Edit" })).toBeNull();
  });

  it("says plainly that a written script has no opening line, with the way to write one (C11-d)", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/first-run": built(),
        "/v1/agents": [agent()],
        [`/v1/calls?agent_id=${AGENT_ID}&limit=1`]: [],
        [`/v1/inbound-lines/${LINE_ID}`]: lineRow({ script: { opening_line: "" } }),
        "/v1/trial": TRIAL,
        "/v1/legal/readiness": READINESS,
        "/v1/compliance/outbound-pledge": PLEDGE,
      }),
    );
    expect(await screen.findByRole("heading", { name: "Hear Anjali on your phone" })).toBeTruthy();
    expect(screen.queryByText("Written when Pip writes its script.")).toBeNull();
    const step = screen.getByRole("region", { name: "This step" });
    expect(within(step).getByText("No opening line yet.")).toBeTruthy();
    expect(within(step).getByRole("link", { name: "Write one" }).getAttribute("href")).toContain(`/inbound/${LINE_ID}`);
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
        [`POST /v1/inbound-lines/${LINE_ID}/test-call`]: { status: "queued", blocked_reason: null, blocked_rule: null, call_id: null },
      }),
    );
    const call = await screen.findByRole("button", { name: /Call me now/ });
    fireEvent.change(screen.getByRole("textbox", { name: "Your mobile number" }), { target: { value: "98765 43210" } });
    expect(call.getAttribute("aria-disabled")).toBe("true");
    expect(screen.getByText("Tick each box above.")).toBeTruthy();
    fireEvent.click(call);
    expect(calls.some((entry) => entry.method === "POST")).toBe(false);
    fireEvent.click(screen.getByRole("checkbox", { name: /I accept the Terms of Service/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /no-cold-calls pledge/ }));
    expect(call.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(screen.getByRole("checkbox", { name: /This number is my own/ }));
    expect(call.getAttribute("aria-disabled")).toBeNull();
    expect(screen.queryByText("Tick each box above.")).toBeNull();
    fireEvent.click(call);
    expect(await screen.findByText("Dialling your phone")).toBeTruthy();
    const posts = calls.filter((entry) => entry.method === "POST").map((entry) => entry.path);
    // The draft line's own engine agent rings: the agent itself is never got ready here.
    expect(posts).toEqual([
      "/v1/legal/acceptances",
      "/v1/compliance/outbound-pledge",
      `/v1/inbound-lines/${LINE_ID}/test-call`,
    ]);
    const placed = calls.find((entry) => entry.path === `/v1/inbound-lines/${LINE_ID}/test-call`);
    expect(JSON.parse(placed?.body ?? "{}")).toEqual({ number: "98765 43210", number_is_mine: true });
  });

  it("follows the placed call by its id while it rings, before it has a start time", async () => {
    const CALL_ID = "0192f3a4-0000-7000-8000-00000000c009";
    let placedYet = false;
    await renderClientPage(
      page,
      routes({
        "/v1/first-run": built(),
        "/v1/agents": [agent({ published: true })],
        [`/v1/calls?agent_id=${AGENT_ID}&limit=1`]: () =>
          placedYet
            ? [
                {
                  id: CALL_ID,
                  agent_id: AGENT_ID,
                  agent_name: "Anjali",
                  direction: "outbound",
                  status: "ringing",
                  caller_e164: null,
                  // Not connected yet, so the server has no start time for it.
                  started_at: null,
                  created_at: new Date().toISOString(),
                  duration_s: null,
                  outcome_tag: null,
                  summary_state: "none",
                  test_call: true,
                  sentiment: null,
                  summary: null,
                  lead_id: null,
                },
              ]
            : [],
        "/v1/trial": TRIAL,
        "/v1/legal/readiness": { ...READINESS, documents: [], outstanding_documents: 0 },
        "/v1/compliance/outbound-pledge": { ...PLEDGE, is_current: true },
        [`POST /v1/inbound-lines/${LINE_ID}/test-call`]: () => {
          placedYet = true;
          return { status: "queued", call_handle: "h1", call_id: CALL_ID, blocked_reason: null, blocked_rule: null };
        },
      }),
    );
    const call = await screen.findByRole("button", { name: /Call me now/ });
    fireEvent.change(screen.getByRole("textbox", { name: "Your mobile number" }), { target: { value: "98765 43210" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /This number is my own/ }));
    fireEvent.click(call);
    expect(await screen.findByText("Your phone is ringing", {}, { timeout: 8000 })).toBeTruthy();
  }, 15000);

  it("shows used-up trial Studio minutes as a limit with its way forward, not an error to try again (journey audit E1)", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/first-run": built(),
        "/v1/agents": [agent({ published: true })],
        [`/v1/calls?agent_id=${AGENT_ID}&limit=1`]: [],
        "/v1/trial": TRIAL,
        "/v1/legal/readiness": { ...READINESS, documents: [], outstanding_documents: 0 },
        "/v1/compliance/outbound-pledge": { ...PLEDGE, is_current: true },
        [`POST /v1/inbound-lines/${LINE_ID}/test-call`]: problem(422, {
          type: "https://calevate.tech/problems/trial_studio_minutes_used",
          code: "trial_studio_minutes_used",
          kind: "business_rule",
          title: "Your Studio minutes for the trial are used up",
          detail: "This free trial includes 15 minutes of test calls on Studio voices.",
          remediation: "Switch this agent to a Clear voice, or add credit to keep using Studio.",
        }),
      }),
    );
    const call = await screen.findByRole("button", { name: /Call me now/ });
    fireEvent.change(screen.getByRole("textbox", { name: "Your mobile number" }), { target: { value: "98765 43210" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /This number is my own/ }));
    fireEvent.click(call);
    expect(await screen.findByText(/Switch this agent to a Clear voice/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Choose a Clear voice" }).getAttribute("href")).toContain("section=voice");
    expect(screen.getByRole("link", { name: "Add credit" }).getAttribute("href")).toContain("tab=credits");
    expect(screen.queryByRole("button", { name: /Try again/ })).toBeNull();
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

  const NO_LINE =
    "Phone test calls are not switched on yet: the line they ring from is not set up on our side. Until it is, type to your agent on its Training tab to try it.";

  it("says there is no test line yet, and offers typing to the agent instead of a retry (28 Nov 2026)", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/first-run": built(),
        "/v1/agents": [agent({ published: true })],
        [`/v1/calls?agent_id=${AGENT_ID}&limit=1`]: [],
        "/v1/trial": { ...TRIAL, can_call: false, blocked_reason: NO_LINE, blocked_rule: "trial_calling_not_ready" },
        "/v1/legal/readiness": { ...READINESS, documents: [], outstanding_documents: 0 },
        "/v1/compliance/outbound-pledge": { ...PLEDGE, is_current: true },
      }),
    );
    expect(await screen.findByText("No test line yet")).toBeTruthy();
    expect(screen.getByText(NO_LINE)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Type to it instead" }).getAttribute("href")).toContain(
      `/agents/${AGENT_ID}?section=training`,
    );
    expect(screen.queryByRole("button", { name: /Call me now/ })).toBeNull();
    expect(screen.queryByText(/try again later/i)).toBeNull();
  });

  it("gives a refusal at the press for a missing test line the same way on, never Try again", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/first-run": built(),
        "/v1/agents": [agent({ published: true })],
        [`/v1/calls?agent_id=${AGENT_ID}&limit=1`]: [],
        "/v1/trial": TRIAL,
        "/v1/legal/readiness": { ...READINESS, documents: [], outstanding_documents: 0 },
        "/v1/compliance/outbound-pledge": { ...PLEDGE, is_current: true },
        [`POST /v1/inbound-lines/${LINE_ID}/test-call`]: {
          status: "blocked",
          blocked_reason: NO_LINE,
          blocked_rule: "trial_calling_not_ready",
          call_id: null,
        },
      }),
    );
    const call = await screen.findByRole("button", { name: /Call me now/ });
    fireEvent.change(screen.getByRole("textbox", { name: "Your mobile number" }), { target: { value: "98765 43210" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /This number is my own/ }));
    fireEvent.click(call);
    expect(await screen.findByText("No test line yet")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Type to it instead" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Try again|Call me again/ })).toBeNull();
  });

  it("reads the brief on the stage while the questions are written, with a way to go on at once", async () => {
    const reading = run({
      jobs: ["answer_calls"],
      language_primary: "te-IN",
      brief: "We sell flats in Kondapur.",
      questions: { status: "writing", items: [], disclosure: null },
    });
    await renderClientPage(page, routes({ "/v1/first-run": reading }));
    expect(await screen.findByRole("region", { name: "Reading what you wrote" })).toBeTruthy();
    const stage = screen.getByRole("region", { name: "Reading what you wrote" });
    expect(within(stage).getByText("We sell flats in Kondapur.")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Skip the questions/ })).toBeTruthy();
  });

  it("says the questions could not be written, with a retry and a way on", async () => {
    const failed = run({
      jobs: ["answer_calls"],
      language_primary: "te-IN",
      brief: "We sell flats in Kondapur.",
      questions: { status: "failed", items: [], disclosure: null },
    });
    const { calls } = await renderClientPage(
      page,
      routes({ "/v1/first-run": failed, "/v1/first-run/brief": failed }),
    );
    expect(await screen.findByRole("heading", { name: "We couldn't write your questions" })).toBeTruthy();
    expect(screen.queryByText("Your description covers it")).toBeNull();
    expect(screen.getByRole("button", { name: /Continue/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Try again/ }));
    await waitFor(() =>
      expect(calls.some((call) => call.method === "PUT" && call.path === "/v1/first-run/brief")).toBe(true),
    );
    const sent = calls.find((call) => call.method === "PUT" && call.path === "/v1/first-run/brief");
    expect(JSON.parse(sent?.body ?? "{}")).toEqual({ brief: "We sell flats in Kondapur." });
  });

  it("asks for a price list as a list of services, each with a rupee price", async () => {
    const asked = run({
      jobs: ["answer_calls"],
      language_primary: "te-IN",
      brief: "We sell flats in Kondapur.",
      questions: {
        status: "ready",
        items: [
          {
            id: "q1",
            kind: "services",
            prompt: "What do you offer?",
            hint: "Quoted to callers.",
            options: [],
            maps_to: "offer",
          },
        ],
        disclosure: null,
      },
    });
    await renderClientPage(page, routes({ "/v1/first-run": asked }));
    expect(await screen.findByRole("heading", { name: "What do you offer?" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Add another/ }));
    expect(screen.getAllByRole("textbox", { name: /Price of service/ })).toHaveLength(2);
    expect(screen.getByRole("button", { name: /Skip this question/ })).toBeTruthy();
  });

  it("keeps a question answered as shown, the usual hours included, and sends it in its kind's field", async () => {
    const asked = run({
      jobs: ["answer_calls"],
      language_primary: "te-IN",
      brief: "We sell flats in Kondapur.",
      questions: {
        status: "ready",
        items: [{ id: "q1", kind: "hours", prompt: "When are you open?", hint: "", options: [], maps_to: "hours" }],
        disclosure: null,
      },
    });
    const { calls } = await renderClientPage(
      page,
      routes({ "/v1/first-run": asked, "POST /v1/first-run/answers": asked }),
    );
    expect(await screen.findByText("Mon to Sat, 9am to 6pm")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Continue/ }));
    // The answers saved, the next step is the agent's name and voice.
    expect(await screen.findByRole("heading", { name: "Name your agent and pick its voice" })).toBeTruthy();
    const sent = calls.find((call) => call.path === "/v1/first-run/answers");
    expect(JSON.parse(sent?.body ?? "{}")).toEqual({
      answers: [{ id: "q1", hours: { opens: "09:00", closes: "18:00", closed: ["sun"] } }],
    });
  });

  it("reads the first call back in one column, with one next step", async () => {
    const CALL_ID = "0192f3a4-0000-7000-8000-00000000c001";
    const startedAt = new Date(Date.now() - 60_000).toISOString();
    const summary = {
      id: CALL_ID,
      agent_id: AGENT_ID,
      agent_name: "Anjali",
      direction: "outbound",
      status: "completed",
      caller_e164: null,
      started_at: startedAt,
      duration_s: 72,
      outcome_tag: null,
      summary_state: "ready",
      test_call: true,
      sentiment: null,
      summary: "Suresh wants a 3 BHK in Kondapur.",
      lead_id: null,
    };
    const detail = {
      ...summary,
      caller_id_hidden: false,
      forwarding_test: false,
      forwarded_to_phone: false,
      not_placed_reason: null,
      translation_state: "not_needed",
      language: "te-IN",
      extraction: {},
      captured: [
        { key: "bhk", label: "BHK", type: "text", core: false, current: true, source: "call", value: "3" },
        { key: "budget", label: "Budget (lakhs)", type: "number", core: false, current: true, source: "call", value: 120 },
      ],
      extraction_valid: true,
      unclear_fields: [],
      next_step_by: null,
      goal: null,
      extraction_needs_review: {},
      has_recording: false,
      disclosure_played: true,
      moments: [],
      mistakes: [],
      quality: null,
      signals: [],
      transcript: [
        { idx: 0, speaker: "agent", start_approximate: false, likely_cut_off: false, text: "Namaskaram.", redacted: true },
      ],
    };
    await renderClientPage(
      page,
      routes({
        "/v1/first-run": built(),
        "/v1/agents": [agent({ published: true })],
        [`/v1/calls?agent_id=${AGENT_ID}&limit=1`]: [summary],
        [`/v1/calls/${CALL_ID}`]: detail,
      }),
    );
    expect(await screen.findByRole("heading", { name: "That was Anjali's first call" })).toBeTruthy();
    expect(screen.getByText("1:12 call. Here is what it heard.")).toBeTruthy();
    expect(await screen.findByText("Suresh wants a 3 BHK in Kondapur.")).toBeTruthy();
    expect(screen.getByText("120")).toBeTruthy();
    // The card beside the steps and its counter restate steps 1 and 2; they are gone here.
    expect(screen.queryByRole("complementary", { name: "Your agent as it takes shape" })).toBeNull();
    expect(screen.queryByText(/of 7 ready/)).toBeNull();
    expect(screen.queryByText("Version one")).toBeNull();
    // One primary action; the rest are quiet links.
    expect(screen.getByRole("button", { name: /Make it yours/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Call me again/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Change what it says/ }).getAttribute("href")).toBe(`/c/acme/inbound/${LINE_ID}`);
    expect(screen.getByRole("link", { name: /Company training/ }).getAttribute("href")).toBe("/c/acme/knowledge?tab=training");
    // The conversation is there, folded.
    expect(screen.getByRole("heading", { name: "Read the whole conversation" })).toBeTruthy();
    expect(screen.getByText("Step 3 of 3 ·", { exact: false })).toBeTruthy();
  });

  it("refuses a member who may not build agents, in the console's own words", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/me": { ...OWNER_ME, role: "staff", permissions: ["agents:read"] },
        // The real server refuses this read to a non-owner; it must not be what they see.
        "/v1/first-run": problem(403, { type: "https://calevate.tech/problems/forbidden", detail: "Forbidden." }),
      }),
    );
    expect(await screen.findByText(/build an agent/)).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "What should your agent do?" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Skip for now" })).toBeNull();
    expect(calls.some((call) => call.path === "/v1/first-run")).toBe(false);
  });

  it("puts the first run aside and goes to the dashboard", async () => {
    const { calls } = await renderClientPage(page, routes({ "POST /v1/first-run/dismiss": run({ due: false }) }));
    fireEvent.click(await screen.findByRole("button", { name: "Skip for now" }));
    await waitFor(() => expect(nav.pushed).toEqual(["/c/acme"]));
    expect(calls.some((call) => call.method === "POST" && call.path === "/v1/first-run/dismiss")).toBe(true);
  });
});

describe("a failed read of the agent's last call (frontend audit 8 Nov 2026, W1)", () => {
  it("says so instead of holding the skeleton for good", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/first-run": built(),
        "/v1/agents": [agent({ published: true })],
        [`/v1/calls?agent_id=${AGENT_ID}&limit=1`]: problem(403, { title: "Calls are not yours to read" }),
      }),
    );
    expect(await screen.findByText("Calls are not yours to read", {}, { timeout: 8000 })).toBeTruthy();
    expect(screen.queryByText("Getting your agent ready…")).toBeNull();
  }, 15000);

  it("says the first work's read failed instead of saying Pip is still writing it", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/first-run": built(),
        "/v1/agents": [agent()],
        [`/v1/inbound-lines/${LINE_ID}`]: problem(403, { title: "That line is not yours to read" }),
      }),
    );
    expect(await screen.findByText("That line is not yours to read", {}, { timeout: 8000 })).toBeTruthy();
    expect(screen.queryByText("Pip is writing what it says…")).toBeNull();
  }, 15000);
});
