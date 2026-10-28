import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import FirstAgentPage from "@/app/c/[slug]/agents/first/page";
import { metaOf, rowStateOf } from "@/app/c/[slug]/agents/first/BuildStep";
import { JobStep } from "@/app/c/[slug]/agents/first/JobStep";
import { callPhaseOf, isLimitRule } from "@/app/c/[slug]/agents/first/HearItStep";
import { hoursSummary } from "@/app/c/[slug]/agents/first/QuestionsStep";
import { goLiveSteps } from "@/app/c/[slug]/agents/first/ResultStep";
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
  jobPayload,
  jobsTitle,
  languageGlyph,
  piecesOf,
  resumeStage,
  studioFallbackLine,
  trialMinutesLine,
  voicePickNote,
} from "@/lib/firstAgent";
import { answersBody, emptyAnswer } from "@/lib/firstRunQuestions";

import { businessProfileFixture } from "./businessProfileFixture";
import { OWNER_ME, agentRow } from "./fixtures/sharedReads";
import { problem, renderClientPage } from "./harness";

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
        { step: "voice", state: "done", label: "Lakshmi", not_female: false, documents_used: 0 },
        { step: "script", state: "done", label: null, not_female: false, documents_used: 0 },
        { step: "greeting", state: "done", label: null, not_female: false, documents_used: 0 },
        { step: "notice", state: "done", label: null, not_female: false, documents_used: 0 },
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
    "/v1/kb/knows": { facts: [], facts_state: "none", items: [], pinned_not_yet_on: [] },
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
    expect(hoursSummary({ opens: "09:00", closes: "18:00", closed: ["sun"] })).toBe("Mon to Sat, 9:00 am to 6:00 pm");
    expect(hoursSummary({ opens: "10:30", closes: "13:00", closed: ["tue", "thu", "sun"] })).toBe(
      "Mon, Wed, Fri, Sat, 10:30 am to 1:00 pm",
    );
    expect(hoursSummary({ opens: "00:00", closes: "23:59", closed: [] })).toBe("Every day, 12:00 am to 11:59 pm");
  });

  it("lets one agent take several jobs, every one sent, in the cards' order", () => {
    expect(jobPayload(["call_leads", "answer_calls"], "te-IN", ["en-IN"])).toEqual({
      jobs: ["answer_calls", "call_leads"],
      language_primary: "te-IN",
      languages_extra: ["en-IN"],
    });
    expect(jobsTitle(["call_leads", "call_new_leads"])).toBe("Call new leads instantly + 1 more");
    expect(languageGlyph("te-IN")).toBe("తె");
  });

  it("moves each build row only on the server's word", () => {
    const waiting = { step: "script" as const, state: "waiting", label: null, not_female: false, documents_used: 0 };
    expect(rowStateOf(waiting, true, false)).toBe("working");
    expect(rowStateOf(waiting, false, false)).toBe("waiting");
    expect(rowStateOf(waiting, true, true)).toBe("failed");
    expect(rowStateOf({ ...waiting, state: "ready_made" }, false, false)).toBe("done");
    expect(rowStateOf({ ...waiting, step: "voice", state: "none" }, false, false)).toBe("warn");
    expect(rowStateOf({ ...waiting, step: "notice", state: "no_room" }, false, false)).toBe("warn");
  });

  it("says the AI notice is said after the greeting, or why it is not (D-864)", () => {
    const notice = { step: "notice" as const, label: null, not_female: false, documents_used: 0 };
    expect(metaOf({ ...notice, state: "done" })).toBe("Said right after its greeting on every call");
    expect(metaOf({ ...notice, state: "off" })).toBe("Kept off, as you set it");
    expect(metaOf({ ...notice, state: "no_room" })).toBe("No room after its greeting. Shorten the greeting to add it.");
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

  it("says what really happened at each build step, fallbacks included", () => {
    expect(metaOf({ step: "voice", state: "done", label: "Lakshmi", rung: "studio", fallback: null, not_female: false, documents_used: 0 })).toBe("Lakshmi · Studio");
    expect(metaOf({ step: "voice", state: "done", label: "Bindu", rung: "clear", fallback: "studio_minutes_used", not_female: false, documents_used: 0 })).toBe(
      "Bindu · Clear. Your trial's Studio minutes are used, so it uses a Clear voice.",
    );
    expect(studioFallbackLine("studio_unavailable")).toBe("Studio voices aren't available right now, so it uses a Clear voice.");
    expect(studioFallbackLine(null)).toBeNull();
    expect(metaOf({ step: "voice", state: "done", label: "Bindu", rung: "clear", fallback: "no_female_studio_voice", not_female: false, documents_used: 0 })).toBe(
      "Bindu · Clear. No Studio woman's voice speaks this language yet, so it uses a Clear voice.",
    );
    expect(metaOf({ step: "voice", state: "done", label: "Ravi", rung: "studio", fallback: null, not_female: true, documents_used: 0 })).toBe(
      `Ravi · Studio. ${NOT_FEMALE_LINE}`,
    );
    expect(voicePickNote(null, false)).toBeNull();
    expect(NOT_FEMALE_LINE).not.toMatch(/thinnest|cartesia/i);
    expect(metaOf({ step: "voice", state: "none", label: null, not_female: false, documents_used: 0 })).toMatch(/Pick one before the call/);
    expect(metaOf({ step: "script", state: "ready_made", label: null, not_female: false, documents_used: 0 })).toMatch(/ready-made script/);
  });
});

describe("meet your agent", () => {
  it("opens on its job with three cards, any of them chosen, and the meter at one of nine", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        "PUT /v1/first-run/job": run({ jobs: ["call_new_leads"], language_primary: "te-IN", languages_extra: ["en-IN"] }),
      }),
    );
    expect(await screen.findByRole("heading", { name: "What should your agent do?" })).toBeTruthy();
    for (const name of [/Answer my calls/, /Call new leads instantly/, /Run calling campaigns/]) {
      expect((screen.getByRole("checkbox", { name }) as HTMLInputElement).disabled).toBe(false);
    }
    expect(screen.getByText("1 of 9 ready")).toBeTruthy();
    expect((screen.getByRole("radio", { name: /Telugu/ }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: /Run calling campaigns/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Call new leads instantly/ }));
    fireEvent.click(screen.getByRole("button", { name: /Continue/ }));
    await waitFor(() => expect(calls.some((call) => call.method === "PUT" && call.path === "/v1/first-run/job")).toBe(true));
    const sent = calls.find((call) => call.method === "PUT" && call.path === "/v1/first-run/job");
    expect(JSON.parse(sent?.body ?? "{}")).toEqual({
      jobs: ["call_new_leads", "call_leads"],
      language_primary: "te-IN",
      languages_extra: ["en-IN"],
    });
    expect(await screen.findByRole("heading", { name: "Tell it about your business" })).toBeTruthy();
  });

  it("shows a built agent's languages without offering to change them", async () => {
    // The agent took its languages and voice when it was built; changing them here only
    // rewrote the run, so the server refuses it (`first_run_language_locked`).
    await renderClientPage(
      <JobStep run={built()} defaultLanguage="te-IN" onDone={() => undefined} />,
      routes(),
    );
    const telugu = (await screen.findByRole("radio", { name: /Telugu/ })) as HTMLInputElement;
    expect(telugu.checked && telugu.disabled).toBe(true);
    expect(screen.queryByRole("radio", { name: /Hindi/ })).toBeNull();
    expect((screen.getByRole("checkbox", { name: /English/ }) as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByText(/Change languages on its own page/)).toBeTruthy();
  });

  it("starts the brief from the trade's example and says the audio is not kept", async () => {
    await renderClientPage(page, routes({ "/v1/first-run": run({ jobs: ["answer_calls"], language_primary: "te-IN" }) }));
    const box = (await screen.findByRole("textbox", { name: "About your business" })) as HTMLTextAreaElement;
    expect(box.value.length).toBeGreaterThan(20);
    expect(screen.getByText("Only the text is kept, not the audio.")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Talk it through with Pip instead/ })).toBeTruthy();
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
    await screen.findByText("Or add a file");
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
    await screen.findByText("Or add a file");
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

  it("edits the opening line in place on Hear it, counting against the server's room, and saves it through the agent's route", async () => {
    const withRoom = agent({
      greeting_budget: {
        limit: 200,
        opening_chars: 50,
        opening_room: 60,
        opening_room_with_ai_disclosure: 40,
        opening_room_with_recording_notice: 30,
      },
    });
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/first-run": built(),
        "/v1/agents": [withRoom],
        [`/v1/calls?agent_id=${AGENT_ID}&limit=1`]: [],
        "/v1/trial": TRIAL,
        "/v1/legal/readiness": READINESS,
        "/v1/compliance/outbound-pledge": PLEDGE,
        [`PUT /v1/agents/${AGENT_ID}/script/opening-line`]: { opening_line: "Namaskaram! Emi kavali?", version: 2 },
      }),
    );
    await screen.findByRole("heading", { name: "Hear Anjali on your phone" });
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const box = screen.getByRole("textbox", { name: "Opening line" }) as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "x".repeat(61) } });
    expect(screen.getByText("1 character too long")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(box, { target: { value: "Namaskaram! Emi kavali?" } });
    expect(screen.getByText("37 characters left")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.some((call) => call.method === "PUT" && call.path === `/v1/agents/${AGENT_ID}/script/opening-line`)).toBe(true),
    );
    const sent = calls.find((call) => call.path === `/v1/agents/${AGENT_ID}/script/opening-line`);
    expect(JSON.parse(sent?.body ?? "{}")).toEqual({ opening_line: "Namaskaram! Emi kavali?", when: "answers" });
    // An agent of one direction has one first line, so no "When it calls" editor.
    expect(screen.queryByText("When it calls")).toBeNull();
  });

  it("gives an agent that both answers and calls a second line for the calls it places (D-920)", async () => {
    const both = agent({ direction: "both", script_outbound_opening_line: null });
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/first-run": built(),
        "/v1/agents": [both],
        [`/v1/calls?agent_id=${AGENT_ID}&limit=1`]: [],
        "/v1/trial": TRIAL,
        "/v1/legal/readiness": READINESS,
        "/v1/compliance/outbound-pledge": PLEDGE,
        [`PUT /v1/agents/${AGENT_ID}/script/opening-line`]: { opening_line: "Namaskaram, Rytu Khata nundi.", version: 2 },
      }),
    );
    await screen.findByRole("heading", { name: "Hear Anjali on your phone" });
    expect(screen.getAllByText("When it answers").length).toBeGreaterThan(0);
    const calling = screen
      .getAllByText("When it calls")
      .map((caption) => caption.closest("figure"))
      .find((figure): figure is HTMLElement => figure !== null && within(figure).queryAllByRole("button").length > 0);
    if (!calling) throw new Error("no editable When it calls line");
    fireEvent.click(within(calling).getByRole("button", { name: "Write one" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Opening line when it calls" }), {
      target: { value: "Namaskaram, Rytu Khata nundi." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((call) => call.method === "PUT")).toBe(true));
    const sent = calls.find((call) => call.method === "PUT");
    expect(JSON.parse(sent?.body ?? "{}")).toEqual({ opening_line: "Namaskaram, Rytu Khata nundi.", when: "calls" });
  });

  it("shows the server's refusal of an opening line in one short line, and Cancel leaves it as it was", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/first-run": built(),
        "/v1/agents": [agent()],
        [`/v1/calls?agent_id=${AGENT_ID}&limit=1`]: [],
        "/v1/trial": TRIAL,
        "/v1/legal/readiness": READINESS,
        "/v1/compliance/outbound-pledge": PLEDGE,
        [`PUT /v1/agents/${AGENT_ID}/script/opening-line`]: problem(409, {
          code: "script_change_waiting",
          title: "Script changes are waiting",
          detail: "This agent has script changes that are not live yet.",
        }),
      }),
    );
    await screen.findByRole("heading", { name: "Hear Anjali on your phone" });
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Opening line" }), { target: { value: "Hello, Madhav Homes?" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Script changes are waiting")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("textbox", { name: "Opening line" })).toBeNull();
    expect(screen.getAllByText("“Namaskaram, Madhav Homes. Meeku ela help cheyagalanu?”").length).toBeGreaterThan(0);
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
    // The agent's real opening line, editable here too.
    expect(screen.getByRole("button", { name: "Edit" })).toBeTruthy();
  });

  it("puts the go-live steps in order, the first not done current, a review said as such", () => {
    expect(goLiveSteps(undefined).map((step) => step.state)).toEqual(["current", "waiting", "waiting"]);
    const paid = { owed_at: "2026-10-27T10:00:00Z", verify: "in_review" as const, number: "locked" as const };
    expect(goLiveSteps(paid).map((step) => step.state)).toEqual(["done", "in_review", "waiting"]);
    const verified = { owed_at: "2026-10-27T10:00:00Z", verify: "done" as const, number: "todo" as const };
    expect(goLiveSteps(verified).map((step) => step.state)).toEqual(["done", "done", "current"]);
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
    fireEvent.click(screen.getByRole("checkbox", { name: /This number is my own/ }));
    expect((call as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(call);
    expect(await screen.findByText("Dialling your phone")).toBeTruthy();
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

  it("shows the build as its real steps, the one being worked on named by what it does", async () => {
    const building = run({
      jobs: ["answer_calls"],
      language_primary: "te-IN",
      brief: "We sell flats in Kondapur.",
      build: { ...run().build, status: "building" },
    });
    await renderClientPage(page, routes({ "/v1/first-run": building }));
    const list = await screen.findByRole("region", { name: "Your agent being built" });
    // No picture (D-918): each step is a row with what is happening, in words.
    expect(within(list).queryByRole("img")).toBeNull();
    expect(within(list).getAllByText("Choosing a voice for Telugu").length).toBeGreaterThan(0);
    expect(within(list).getByText("Working on it:")).toBeTruthy();
    expect(within(list).getAllByText("Waiting:")).toHaveLength(3);
    expect(within(list).getByText("AI notice")).toBeTruthy();
  });

  it("names a file the build went without, with a way to try another", async () => {
    const DOC = "0192f3a4-0000-7000-8000-00000000d001";
    const steps = run().build.steps.map((step) =>
      step.step === "script"
        ? { ...step, state: "done", left_out: [{ upload_id: DOC, why: "failed" as const }] }
        : { ...step, state: "done" },
    );
    const done = built({
      build: { status: "built", steps, disclosure: null, builds_left: 2 },
      documents: [
        { upload_id: DOC, name: "menu.jpg", source_kind: "image", state: "failed", detail: "No words found.", reaches_agents: true },
      ],
      documents_left: 2,
    });
    await renderClientPage(
      page,
      routes({
        "/v1/first-run": done,
        "/v1/agents": [agent()],
        [`/v1/calls?agent_id=${AGENT_ID}&limit=1`]: [],
        "/v1/trial": TRIAL,
        "/v1/legal/readiness": READINESS,
        "/v1/compliance/outbound-pledge": PLEDGE,
      }),
    );
    await screen.findByRole("heading", { name: "Hear Anjali on your phone" });
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(await screen.findByText("Built without menu.jpg: couldn't read it.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Try another file" })).toBeTruthy();
  });

  it("reads the brief on the stage while the questions are written, with a way to build at once", async () => {
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
    expect(screen.getByRole("button", { name: /Skip the questions and build/ })).toBeTruthy();
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
      routes({ "/v1/first-run": asked, "POST /v1/first-run/answers": asked, "POST /v1/first-run/build": asked }),
    );
    expect(await screen.findByText("Mon to Sat, 9:00 am to 6:00 pm")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Build my agent/ }));
    await waitFor(() => expect(calls.some((call) => call.path === "/v1/first-run/build")).toBe(true));
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
        { key: "bhk", label: "BHK", type: "text", core: false, current: true, value: "3" },
        { key: "budget", label: "Budget (lakhs)", type: "number", core: false, current: true, value: 120 },
      ],
      extraction_valid: true,
      extraction_needs_review: {},
      has_recording: false,
      disclosure_played: true,
      moments: [],
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
    expect(screen.queryByText(/of 9 ready/)).toBeNull();
    expect(screen.queryByText("Version one")).toBeNull();
    // One primary action; the rest are quiet links.
    expect(screen.getByRole("button", { name: /Make it yours/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Call me again/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Change its script/ }).getAttribute("href")).toContain(
      `/agents/${AGENT_ID}?section=script`,
    );
    // The conversation is there, folded.
    expect(screen.getByRole("heading", { name: "Read the whole conversation" })).toBeTruthy();
    expect(screen.getByText("Step 3 of 4 ·", { exact: false })).toBeTruthy();
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
