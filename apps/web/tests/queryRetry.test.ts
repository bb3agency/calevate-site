import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { relPosix } from "./repoPaths";
import { ApiProblem } from "@/lib/api/client";
import { queryRetryDelay, shouldRetryQuery, untilRefused } from "@/lib/api/queryRetry";
import { livePoll } from "@/lib/live/liveStatus";

const limited = (seconds: number) =>
  new ApiProblem(429, { code: "too_many_requests", retryable: true }, seconds);

describe("the read retry policy", () => {
  it("waits the Retry-After the server named before asking again", () => {
    expect(shouldRetryQuery(0, limited(3))).toBe(true);
    expect(queryRetryDelay(0, limited(3))).toBe(3000);
  });

  it("does not wait out a long limit, so the refusal reaches the screen", () => {
    expect(shouldRetryQuery(0, limited(60))).toBe(false);
  });

  it("never retries what the server says a retry cannot fix", () => {
    expect(shouldRetryQuery(0, new ApiProblem(422, { retryable: false }))).toBe(false);
  });

  it("retries a transport failure twice, on the default backoff", () => {
    const failure = new TypeError("Failed to fetch");
    expect(shouldRetryQuery(0, failure)).toBe(true);
    expect(shouldRetryQuery(1, failure)).toBe(true);
    expect(shouldRetryQuery(2, failure)).toBe(false);
    expect(queryRetryDelay(0, failure)).toBe(1000);
    expect(queryRetryDelay(1, failure)).toBe(2000);
  });
});

describe("a poll stops once its read is refused for good", () => {
  const refused = (error: unknown) => ({ state: { status: "error", error, data: undefined } });
  const notFound = new ApiProblem(404, { retryable: false });

  it("a poll that waits for a first answer stops on a 404 instead of asking forever", () => {
    const poll = untilRefused<{ state: { data: unknown } }>((q) => (q.state.data ? false : 4_000));
    expect(poll({ state: { data: undefined } })).toBe(4_000);
    expect(poll(refused(notFound) as never)).toBe(false);
  });

  it("keeps polling through a failure a retry can fix", () => {
    const poll = untilRefused<unknown>(4_000);
    expect(poll(refused(new ApiProblem(503, { retryable: true })))).toBe(4_000);
    expect(poll(refused(new TypeError("offline")))).toBe(4_000);
  });

  it("a live feed stops on a refusal too", () => {
    expect(livePoll<unknown>(20_000)(refused(notFound))).toBe(false);
    expect(livePoll<unknown>(20_000)({ state: { status: "success" } })).toBe(20_000);
  });
});

describe("every poll in the app stops once its read is refused for good", () => {
  // A `refetchInterval` keeps firing through errors while the cache keeps the last good
  // answer, so a status poll ("drafting", "running", "pending") whose resource was deleted
  // in another tab, or that this seat may no longer read, asked every few seconds for as
  // long as the page stayed open. One wrapper for all of them, held here by source.
  const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..", "src");

  function sources(dir: string, out: string[] = []): string[] {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) sources(path, out);
      else if (/\.tsx?$/.test(name) && !name.endsWith(".d.ts")) out.push(path);
    }
    return out;
  }

  it("wraps every refetchInterval in untilRefused or livePoll", () => {
    const polls: string[] = [];
    const bare: string[] = [];
    for (const file of sources(SRC)) {
      readFileSync(file, "utf8")
        .split("\n")
        .forEach((line, index) => {
          const code = line.trimStart();
          if (!code.startsWith("refetchInterval:")) return;
          const where = `${relPosix(SRC, file)}:${index + 1}`;
          polls.push(where);
          if (!/^refetchInterval:\s*(untilRefused|livePoll)\(/.test(code)) bare.push(where);
        });
    }
    expect(polls.length).toBeGreaterThan(40);
    expect(bare).toEqual([]);
  });

  it("a status poll stops on a 404 while the cache still says the job is running", () => {
    const poll = untilRefused<{ state: { status: string; error?: unknown; data?: { status: string } } }>(
      (q) => (q.state.data?.status === "drafting" ? 3_000 : false),
    );
    expect(poll({ state: { status: "success", data: { status: "drafting" } } })).toBe(3_000);
    expect(
      poll({
        state: { status: "error", error: new ApiProblem(404, { retryable: false }), data: { status: "drafting" } },
      }),
    ).toBe(false);
  });
});
