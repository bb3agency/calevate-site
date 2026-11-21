import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  AGENT_NAME_MAX_CHARS,
  BRIEF_MAX_CHARS,
  MAIN_TASK_MAX_CHARS,
  NOTE_MAX_CHARS,
  charCount,
} from "@/lib/textLimits";

/**
 * `lib/textLimits.ts` mirrors server text limits. Each is read here from the generated
 * `openapi.json`, so a server change that moves one fails this test rather than leaving a
 * field that lets someone type past what the server takes, or stops them short of it.
 */

const here = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(here, "../src");
type Schema = { properties?: Record<string, unknown> };
const openapi = JSON.parse(readFileSync(join(SRC, "lib/api/openapi.json"), "utf8")) as {
  components: { schemas: Record<string, Schema> };
};

function maxLength(schema: string, property: string): number | undefined {
  const field = JSON.stringify(openapi.components.schemas[schema]?.properties?.[property] ?? {});
  const found = /"maxLength":(\d+)/.exec(field);
  return found ? Number(found[1]) : undefined;
}

describe("server text limits", () => {
  it("match the API's own bounds", () => {
    for (const schema of ["CreateCampaignIn", "MainTaskIn", "NewInboundLineIn", "InboundLinePatch"]) {
      expect(maxLength(schema, "main_task"), schema).toBe(MAIN_TASK_MAX_CHARS);
    }
    expect(maxLength("BriefIn", "brief")).toBe(BRIEF_MAX_CHARS);
    expect(maxLength("CampaignNoteIn", "note")).toBe(NOTE_MAX_CHARS);
    expect(maxLength("CampaignAnswerIn", "answer")).toBe(NOTE_MAX_CHARS);
    expect(maxLength("AgentIn", "name")).toBe(AGENT_NAME_MAX_CHARS);
    expect(maxLength("NameIn", "name")).toBe(AGENT_NAME_MAX_CHARS);
    // The other agent routes take longer names; every screen holds the one shorter bound.
    expect(maxLength("AgentCreateIn", "name")).toBeGreaterThanOrEqual(AGENT_NAME_MAX_CHARS);
    expect(maxLength("AgentUpdateIn", "name")).toBeGreaterThanOrEqual(AGENT_NAME_MAX_CHARS);
  });

  it("counts in Indian grouping", () => {
    expect(charCount(1234, MAIN_TASK_MAX_CHARS)).toBe("1,234 / 4,000");
  });
});
