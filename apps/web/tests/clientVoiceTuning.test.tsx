import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  ClientVoiceTuning,
  multiplierLabel,
  positionOf,
  valueOf,
} from "@/app/c/[slug]/agents/panels/voiceTuning";
import type { ClientVoiceTuning as Tuning } from "@/lib/api/voiceTuning";

import { problem, renderClientPage, type Routes } from "./harness";

/*
 * "How it sounds" on a client's Studio agent (D-843): speed and loudness sliders with Normal
 * in the middle and Reset, an emotion picker with "None (the words decide)", a capped sample,
 * and no provider named anywhere on the screen (D-679).
 */

const AGENT = "0192f0aa-8888-7000-8000-0000000000b2";
const PATH = `/v1/agents/${AGENT}/voice-tuning`;
const PREVIEW = `POST ${PATH}/preview`;

function tuning(over: Partial<Tuning> = {}): Tuning {
  return {
    agent_id: AGENT,
    studio: true,
    speed: null,
    volume: null,
    emotion: "calm",
    options: {
      speed_min: "0.6",
      speed_max: "1.5",
      speed_step: "0.01",
      volume_min: "0.5",
      volume_max: "2.0",
      emotions: ["neutral", "calm", "content", "sad", "angry", "scared", "happy", "excited"],
      previews_per_day: 20,
    },
    previews_left_today: 20,
    ...over,
  };
}

async function mount(routes: Routes) {
  const view = await renderClientPage(
    <ClientVoiceTuning agentId={AGENT} voiceId="byok:cv-1" />,
    routes,
  );
  await screen.findByRole("heading", { name: "How it sounds" });
  return view;
}

const VENDOR_WORDS = /cartesia|sonic|thinnest/i;

describe("the slider scale", () => {
  it("puts Normal in the middle of both uneven ranges", () => {
    expect(positionOf(1, 0.6, 1.5)).toBe(50);
    expect(positionOf(1, 0.5, 2)).toBe(50);
    expect(valueOf(0, 0.6, 1.5)).toBe(0.6);
    expect(valueOf(100, 0.6, 1.5)).toBe(1.5);
    expect(valueOf(100, 0.5, 2)).toBe(2);
    expect(valueOf(75, 0.5, 2)).toBe(1.5);
    expect(multiplierLabel(1)).toBe("Normal");
    expect(multiplierLabel(1.25)).toBe("1.25×");
    // A Clear voice's 0.05 step, never a float tail.
    expect(valueOf(100, 0.7, 1.3, 0.05)).toBe(1.3);
    expect(valueOf(58, 0.7, 1.3, 0.05)).toBe(1.05);
    expect(valueOf(10, 0.7, 1.3, 0.05)).toBe(0.75);
  });
});

describe("How it sounds", () => {
  it("saves the sliders and the emotion, Normal and none as null", async () => {
    let sent: unknown = null;
    const { calls, container } = await mount({
      [`GET ${PATH}`]: tuning({ speed: "1.20" }),
      [`PATCH ${PATH}`]: () => {
        sent = JSON.parse(calls[calls.length - 1].body ?? "{}");
        return tuning({ volume: "1.50", emotion: null });
      },
    });
    const speed = screen.getByRole("slider", { name: "Speed" });
    expect(speed.getAttribute("aria-valuetext")).toBe("1.20 times normal");
    fireEvent.click(screen.getByRole("button", { name: "Reset speed to normal" }));
    expect(speed.getAttribute("aria-valuetext")).toBe("Normal");
    expect((speed as HTMLInputElement).value).toBe("50");

    fireEvent.change(screen.getByRole("slider", { name: "Loudness" }), { target: { value: "75" } });
    const emotion = screen.getByRole("combobox", { name: "Emotion" });
    expect(Array.from((emotion as HTMLSelectElement).options).map((o) => o.text)).toEqual([
      "None (the words decide)",
      "Neutral",
      "Calm",
      "Content",
      "Sad",
      "Angry",
      "Scared",
      "Happy",
      "Excited",
    ]);
    fireEvent.change(emotion, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText(/the next call uses these/);
    expect(sent).toEqual({ speed: null, volume: 1.5, emotion: null });
    expect(container.textContent ?? "").not.toMatch(VENDOR_WORDS);
    expect(container.textContent ?? "").not.toMatch(/english/i);
  });

  it("plays a sample of the settings on screen, unsaved", async () => {
    let sent: unknown = null;
    URL.createObjectURL = () => "blob:sample";
    URL.revokeObjectURL = () => undefined;
    HTMLMediaElement.prototype.play = () => Promise.resolve();
    const { calls } = await mount({
      [`GET ${PATH}`]: tuning({ previews_left_today: 3 }),
      [PREVIEW]: () => {
        sent = JSON.parse(calls[calls.length - 1].body ?? "{}");
        return new Response(new Blob(["ID3"]), { headers: { "content-type": "audio/mpeg" } });
      },
    });
    expect(screen.getByText("3 of 20 samples left today")).toBeTruthy();
    fireEvent.change(screen.getByRole("combobox", { name: "Emotion" }), {
      target: { value: "happy" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Hear it" }));
    await waitFor(() => expect(sent).toEqual({ speed: null, volume: null, emotion: "happy" }));
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
  });

  it("says the day's samples are used up, from the server's refusal", async () => {
    await mount({
      [`GET ${PATH}`]: tuning(),
      [PREVIEW]: problem(429, {
        type: "https://calevate.tech/problems/voice_preview_daily_cap",
        title: "You have heard 20 samples today",
        status: 429,
      }),
    });
    fireEvent.click(screen.getByRole("button", { name: "Hear it" }));
    expect(await screen.findByText(/You have heard all 20 samples for today/)).toBeTruthy();
  });

  it("holds Hear it once none are left, and says why", async () => {
    await mount({ [`GET ${PATH}`]: tuning({ previews_left_today: 0 }) });
    expect((screen.getByRole("button", { name: "Hear it" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/You have heard all 20 samples for today/)).toBeTruthy();
  });

  it("says a voice that keeps its pace in a sentence, and the sliders stay usable", async () => {
    await mount({
      [`GET ${PATH}`]: tuning({ speed: "1.10" }),
      [PREVIEW]: problem(422, {
        type: "https://calevate.tech/problems/voice_speed_not_for_this_voice",
        title: "This voice's speed cannot be changed",
        status: 422,
      }),
    });
    fireEvent.click(screen.getByRole("button", { name: "Hear it" }));
    expect(await screen.findByText(/keeps the pace it was recorded at, so its speed cannot be changed/)).toBeTruthy();
    const loudness = screen.getByRole("slider", { name: "Loudness" });
    expect((loudness as HTMLInputElement).disabled).toBe(false);
    fireEvent.change(loudness, { target: { value: "100" } });
    expect(loudness.getAttribute("aria-valuetext")).toBe("2.00 times normal");
  });

  it("sets only the speed on a Clear voice, in its own range and step (D-884)", async () => {
    let sent: unknown = null;
    const clear = tuning({
      studio: false,
      volume: "1.40",
      options: { ...tuning().options, speed_min: "0.7", speed_max: "1.3", speed_step: "0.05" },
    });
    const { calls, container } = await mount({
      [`GET ${PATH}`]: clear,
      [`PATCH ${PATH}`]: () => {
        sent = JSON.parse(calls[calls.length - 1].body ?? "{}");
        return { ...clear, speed: "1.15" };
      },
    });
    expect(screen.getByText(/when the agent speaks a Studio voice/)).toBeTruthy();
    expect(screen.queryByRole("slider", { name: "Loudness" })).toBeNull();
    expect(screen.queryByRole("combobox", { name: "Emotion" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Hear it" })).toBeNull();
    expect(screen.queryByText(/samples left today/)).toBeNull();
    const speed = screen.getByRole("slider", { name: "Speed" });
    // Three quarters of the way: halfway from Normal to 1.3, on the 0.05 step.
    fireEvent.change(speed, { target: { value: "75" } });
    expect(speed.getAttribute("aria-valuetext")).toBe("1.15 times normal");
    fireEvent.change(speed, { target: { value: "62" } });
    expect(speed.getAttribute("aria-valuetext")).toBe("1.05 times normal");
    fireEvent.change(speed, { target: { value: "75" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText(/the next call uses these/);
    // The speed alone: a loudness held from a Studio voice is left as it is.
    expect(sent).toEqual({ speed: 1.15 });
    expect(container.textContent ?? "").not.toMatch(VENDOR_WORDS);
  });
});
