import { describe, expect, it } from "vitest";

import { appliedSentence } from "@/components/leadFields/ApplyToJobs";

/**
 * The answer after a set is put onto the ticked campaigns and lines (a business-type move, a
 * kept draft, Start again). It is built from the server's counts, so nobody is told that "0
 * campaigns" changed, and a job whose put-live was refused is named as waiting.
 */
describe("appliedSentence", () => {
  it("counts the campaigns and lines that changed", () => {
    expect(appliedSentence({ jobs_changed: 1, jobs_waiting: 0 })).toBe("1 campaign or line updated.");
    expect(appliedSentence({ jobs_changed: 3, jobs_waiting: 0 })).toBe("3 campaigns and lines updated.");
  });

  it("says nothing changed rather than a zero count", () => {
    const sentence = appliedSentence({ jobs_changed: 0, jobs_waiting: 0 });
    expect(sentence).not.toMatch(/^0 /);
    expect(sentence).toBe("Nothing changed. They already note these details.");
  });

  it("names the ones that use the details from their next start", () => {
    expect(appliedSentence({ jobs_changed: 2, jobs_waiting: 1 })).toBe(
      "2 campaigns and lines updated. 1 will use them from their next start.",
    );
  });
});
