import { describe, expect, it } from "vitest";

import { blankKeys, fill, segment, toPlainText } from "@/lib/noticeDraft/blanks";
import { parseNotice } from "@/lib/noticeDraft/blocks";

/**
 * How the caller-notice blanks are found and filled, against the draft the local API
 * served for the seeded dental account (1 Oct 2026), verbatim.
 *
 * Until `_render` was fixed, the regulator blank went out with SINGLE braces
 * (`{IF YOUR OWN SECTOR REGULATOR …}`, an f-string escape), and a draft served before
 * the fix can still be open in a browser, so both spellings must parse. Two blanks also
 * break across a line.
 */
const SERVED = "> DRAFT — not legal advice. Calevate generated this from your own agent configuration and retention settings so the itemised list is accurate. It is your notice, you are the Data Fiduciary for these callers, and it must be reviewed by your own advocate before you publish or read it to anyone. Anything in double braces is a blank only you can fill.\n\n# How {{YOUR REGISTERED BUSINESS NAME}} handles your information when you call us\n\n## Who is responsible\n\n{{YOUR REGISTERED BUSINESS NAME}}, of {{YOUR REGISTERED BUSINESS ADDRESS}}, decides what is collected on these calls and why.\nThat address is here so you know who and where we are; it is not a channel for writing to\nus about your information — use the contact under \"Your rights\" below for that. Our\ncalling and AI assistant are operated for us by Calevate, which processes this information\nonly on our instructions.\n\n## Being told what you are speaking to\n\nEvery one of our AI assistants says at the start of the call that it is an AI assistant.\nYou are told at the start of the call that it is being recorded.\nWhatever the call opens with, if you ask the assistant whether it is an AI, or whether the call is being recorded, it will tell you the truth. That is enforced by the platform and cannot be switched off.\n\n## What we collect\n\n- **Your phone number** — the number the call is made from or to\n- **A recording of the call** — the audio — every call on this service is recorded\n- **A transcript of the call** — what was said, in text\n- **A summary of the call** — a short written account of what the call was about\n- **When the call happened and how long it lasted** — call times, duration and outcome\n\n\n## Why we collect it\n\nTo answer your enquiry, to do what you asked us to do on the call, to keep a record of\nwhat was agreed, and to improve how we answer. {{ADD ANY OTHER PURPOSE — AND IF YOU CALL\nPEOPLE FOR MARKETING, SAY SO HERE AND SAY WHAT YOU RELY ON TO DO IT}}\n\n## How long we keep it\n\n- The recording of your call: 90 days\n- The transcript of what was said: 365 days\n- The details noted from your call (your enquiry record): 1095 days\n- The technical record of the call from our calling platform: 90 days\n- Superseded versions of the business's own uploaded information: 365 days\n\nCall recordings are kept for at least 90 days. That is a floor our calling provider\nCalevate applies to every account as a matter of its own policy, not a period we have\nbeen told the law requires — {{IF YOUR OWN SECTOR REGULATOR SETS A LONGER RECORD-KEEPING\nPERIOD, SAY SO HERE AND NAME IT}}. The record of what you agreed to is kept as evidence\nthat the contact was permitted, for as long as we may need to show it.\n\n## Your rights\n\nYou can ask us for a copy of what we hold about you, ask us to correct it, ask us to\nerase it, and ask us to stop calling you.\n\n**Asking to stop being called is the one you can do on the call itself** — say so to\nthe assistant, and it is recorded. Everything else, including a correction, reaches us\nby contacting a person:\n\n{{YOUR CONTACT FOR DATA QUESTIONS — NAME, EMAIL, PHONE}}\n\nIf you are not satisfied with our answer, you can complain to the Data Protection Board\nof India.\n\n## Still to be completed by you\n\n- Put your registered business name and your registered business address in, in place of every blank. The address identifies you under the \"Who is responsible\" heading; it is not offered to callers as a place to send things, so if you do want post, add that yourself and say so.\n- Name the person who answers data questions for your business, with an email and a phone number that are actually monitored.\n- If you call people who have not contacted you first, say what permits you to — their consent, and where you obtained it.\n- Have your advocate check this before you publish it. Calevate generated the facts; the wording and the legal basis are yours.\n";

/** The same draft as the server spelled it before the fix. */
const BEFORE_FIX = SERVED.replace("{{IF YOUR OWN SECTOR", "{IF YOUR OWN SECTOR").replace(
  "SAY SO HERE AND NAME IT}}",
  "SAY SO HERE AND NAME IT}",
);

const NAME = "YOUR REGISTERED BUSINESS NAME";
const PURPOSE =
  "ADD ANY OTHER PURPOSE — AND IF YOU CALL PEOPLE FOR MARKETING, SAY SO HERE AND SAY WHAT YOU RELY ON TO DO IT";
const REGULATOR =
  "IF YOUR OWN SECTOR REGULATOR SETS A LONGER RECORD-KEEPING PERIOD, SAY SO HERE AND NAME IT";

describe("finding the blanks", () => {
  it("is fed a draft that really carries both spellings", () => {
    expect(SERVED).toContain("{{IF YOUR OWN SECTOR");
    expect(BEFORE_FIX).toContain("{IF YOUR OWN SECTOR");
    expect(BEFORE_FIX).not.toContain("{{IF YOUR OWN SECTOR");
  });

  it.each([
    ["as served now", SERVED],
    ["as served before the fix", BEFORE_FIX],
  ])("finds every blank in the real draft, %s", (_, markdown) => {
    expect(blankKeys(markdown)).toEqual([
      NAME,
      "YOUR REGISTERED BUSINESS ADDRESS",
      PURPOSE,
      REGULATOR,
      "YOUR CONTACT FOR DATA QUESTIONS — NAME, EMAIL, PHONE",
    ]);
    // Six occurrences: the business name is asked for twice.
    expect(segment(markdown).filter((part) => part.kind === "blank")).toHaveLength(6);
  });

  it("joins a blank that breaks across a line into one key", () => {
    expect(blankKeys("a {{ONE\nTWO}} b")).toEqual(["ONE TWO"]);
  });

  it("never turns an ordinary brace in prose into a field", () => {
    expect(blankKeys("Agent {front desk} and {x}")).toEqual([]);
    expect(blankKeys("Agent {FRONT DESK}")).toEqual(["FRONT DESK"]);
  });
});

describe("filling the draft", () => {
  it("fills every occurrence and leaves an unfilled blank exactly as written", () => {
    const out = fill(SERVED, { [NAME]: "Sunrise Dental Care", [PURPOSE]: "   " });
    expect(out).not.toContain(`{{${NAME}}}`);
    expect(out.split("Sunrise Dental Care")).toHaveLength(3);
    // Whitespace is not a value: the blank stays, line break and all.
    expect(out).toContain("{{ADD ANY OTHER PURPOSE — AND IF YOU CALL\nPEOPLE FOR MARKETING");
    expect(out).toContain("{{IF YOUR OWN SECTOR REGULATOR");
    // The warning travels with the filled text.
    expect(out).toContain("DRAFT — not legal advice.");
  });

  it("fills a single-brace blank too", () => {
    expect(fill(BEFORE_FIX, { [REGULATOR]: "None applies." })).toContain(
      "the law requires — None applies.",
    );
  });

  it("changes nothing when nothing is filled", () => {
    expect(fill(SERVED, {})).toBe(SERVED);
  });

  it("strips markdown markers, not words, for the .txt download", () => {
    const text = toPlainText("> DRAFT — x\n\n# Title\n\n- **Your phone number** — why");
    expect(text).toBe("DRAFT — x\n\nTitle\n\n- Your phone number — why");
  });
});

describe("rendering the draft as a document", () => {
  it("keeps the warning first, then the title, the lists and the blanks", () => {
    const blocks = parseNotice(SERVED);
    expect(blocks[0].kind).toBe("quote");
    expect(blocks[1]).toMatchObject({ kind: "heading", level: 1 });
    expect(blocks.filter((block) => block.kind === "list").length).toBeGreaterThanOrEqual(3);
    // The two wrapped blanks arrive whole inside their paragraphs.
    const text = JSON.stringify(blocks);
    expect(text).toContain(REGULATOR);
    expect(text).toContain(PURPOSE);
  });
});
