import { describe, expect, it } from "vitest";

import { ApiProblem } from "@/lib/api/client";
import { queryRetryDelay, shouldRetryQuery } from "@/lib/api/queryRetry";

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
