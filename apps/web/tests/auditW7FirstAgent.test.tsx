import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import FirstAgentPage from "@/app/c/[slug]/agents/first/page";
import type { FirstRun } from "@/lib/api/firstRun";

import { businessProfileFixture } from "./businessProfileFixture";
import { OWNER_ME } from "./fixtures/sharedReads";
import { NO_BUSINESS_COPY, renderClientPage } from "./harness";

/** Frontend audit lane W7 (8 Nov 2026): the first-agent wizard. */

vi.mock("next/navigation", () => ({
  usePathname: () => "/c/acme/agents/first",
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

// The microphone is the browser's; here one press hands over a finished recording.
vi.mock("@/components/voiceButton", () => ({
  MAX_RECORDING_S: 30,
  recordingMimeType: () => "audio/webm",
  VoiceButton: ({ label, onRecorded }: { label: string; onRecorded: (blob: Blob) => void }) => (
    <button type="button" onClick={() => onRecorded(new Blob(["x"], { type: "audio/webm" }))}>
      {label}
    </button>
  ),
}));

const STEPS = ["voice", "script", "greeting", "notice"] as const;
const RECORDING_ID = "0192f3a4-0000-7000-8000-00000000e001";

function run(over: Partial<FirstRun> = {}): FirstRun {
  return {
    due: true,
    jobs: ["answer_calls"],
    language_primary: "te-IN",
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

const PLACEHOLDERS = {
  end_call_rules: "Always offer a call back.",
  extraction_label: "What they need",
  extraction_options: "New, Returning",
  extraction_reason: "so we can help them first",
  knowledge_answer: "We help you set up the app.",
  knowledge_title: "Getting started",
  lead_search: "help with setup",
  script_brief: "",
};

describe("the brief's microphone", () => {
  it("adds the spoken words to the account's own written brief, not in place of it", async () => {
    const own = "We run an app that helps farmers keep their accounts.";
    // `apiUpload` is an XMLHttpRequest; this one accepts the piece at once.
    class UploadXhr {
      status = 0;
      responseText = "";
      withCredentials = false;
      readonly upload = new EventTarget();
      private readonly events = new EventTarget();
      open() {}
      setRequestHeader() {}
      getResponseHeader(name: string) {
        return name.toLowerCase() === "content-type" ? "application/json" : null;
      }
      addEventListener(type: string, listener: EventListener) {
        this.events.addEventListener(type, listener);
      }
      abort() {}
      send() {
        queueMicrotask(() => {
          this.status = 201;
          this.responseText = JSON.stringify({ id: RECORDING_ID, status: "queued", words: null, error_code: null });
          this.events.dispatchEvent(new Event("load"));
        });
      }
    }
    vi.stubGlobal("XMLHttpRequest", UploadXhr);
    await renderClientPage(<FirstAgentPage params={Promise.resolve({ slug: "acme" })} />, {
      "/v1/me": OWNER_ME,
      "/v1/first-run": run(),
      "/v1/agents": [],
      "/v1/business-profile": businessProfileFixture(),
      "/v1/business-copy": { ...NO_BUSINESS_COPY, placeholders: { ...PLACEHOLDERS, script_brief: own } },
      "/v1/copilot/consent": {
        status: "accepted",
        can_accept: true,
        can_withdraw: true,
        text: "",
        text_sha256: "a",
        version: 1,
        accepted_at: null,
        withdrawn_at: null,
      },
      "/v1/agents/engine-catalogue": { available: true, voices: [], models: [] },
      "/v1/kb/knows": { facts: [], facts_state: "none", items: [], pinned_not_yet_on: [] },
      [`/v1/first-run/recordings/${RECORDING_ID}`]: {
        id: RECORDING_ID,
        status: "heard",
        words: "We also sell seeds.",
        error_code: null,
      },
    });
    const box = (await screen.findByRole("textbox", { name: "About your business" })) as HTMLTextAreaElement;
    await waitFor(() => expect(box.value).toBe(own));
    fireEvent.click(screen.getByRole("button", { name: "Record" }));
    await waitFor(() => expect(box.value).toBe(`${own}\nWe also sell seeds.`));
  });
});

