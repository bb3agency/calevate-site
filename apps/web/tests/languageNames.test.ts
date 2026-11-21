import { describe, expect, it } from "vitest";

import { defaultExtraLanguages } from "@/lib/agentState";
import { templateLanguageLabel, templateLanguages } from "@/lib/api/whatsapp";
import { languageName as callLanguageName } from "@/lib/callReview";
import {
  AGENT_LANGUAGES,
  LANGUAGE_NAMES,
  endonym,
  languageLabel,
  languageName,
  scriptLanguageName,
} from "@/lib/languageNames";
import { profileLanguageChoices } from "@/components/businessProfile/SectionEditor";

describe("the one table of language names", () => {
  it("names a language by its base code, and with its region where the region is chosen", () => {
    expect(languageName("ta-IN")).toBe("Tamil");
    expect(languageName("en-IN")).toBe("English");
    expect(languageName("xx-IN")).toBeNull();
    expect(languageLabel("en-IN")).toBe("English (India)");
    expect(languageLabel("en_GB")).toBe("English (UK)");
    expect(languageLabel("mr-IN")).toBe("Marathi");
    expect(languageLabel("xx-IN")).toBe("xx-IN");
    expect(languageLabel(null)).toBe("");
  });

  it("names every language an agent can be stored in", () => {
    expect(AGENT_LANGUAGES).toEqual(["te-IN", "hi-IN", "en-IN", "ta-IN", "kn-IN", "ml-IN", "mr-IN"]);
    expect(LANGUAGE_NAMES["en-IN"]).toBe("English (India)");
    expect(Object.values(LANGUAGE_NAMES).every((name) => name !== "")).toBe(true);
  });

  it("keeps each caller's own wording for an unknown language", () => {
    expect(callLanguageName("en-IN")).toBe("English");
    expect(callLanguageName("xx")).toBe("xx");
    expect(callLanguageName(null)).toBeNull();
  });

  it("reads endonyms from the founder's file, and has none for English", () => {
    expect(endonym("en-IN")).toBeNull();
    expect(endonym("ta-IN")).toBeTruthy();
    expect(endonym("ta")).toBe(endonym("ta-IN"));
    expect(endonym("bn-IN")).toBeNull();
  });

  it("names a shared script as the language the agent speaks", () => {
    expect(scriptLanguageName("Devanagari")).toBe("Hindi");
    expect(scriptLanguageName("Devanagari", ["mr-IN", "en-IN"])).toBe("Marathi");
    expect(scriptLanguageName("Devanagari", ["hi-IN", "mr-IN"])).toBe("Hindi");
    expect(scriptLanguageName("Bengali")).toBe("Bengali");
    expect(scriptLanguageName("Latin")).toBeNull();
  });
});

describe("lists drawn from the server's languages", () => {
  it("offers WhatsApp templates in Meta's code for each of the account's languages", () => {
    expect(templateLanguages(["te-IN", "hi-IN", "en-IN", "ta-IN"])).toEqual(["te", "hi", "en", "ta"]);
    expect(templateLanguageLabel("ta")).toBe("Tamil");
    expect(templateLanguageLabel("en_IN")).toBe("English (India)");
  });

  it("gives an English agent the account's first other language beside it", () => {
    expect(defaultExtraLanguages("ta-IN", ["ta-IN", "en-IN"])).toEqual(["en-IN"]);
    expect(defaultExtraLanguages("en-IN", ["ta-IN", "en-IN"])).toEqual(["ta-IN"]);
    expect(defaultExtraLanguages("en-IN", ["en-IN"])).toEqual([]);
  });

  it("keeps a profile language the server no longer offers, so it can be unticked", () => {
    const offered = [{ value: "te-IN" as const, label: "Telugu" }];
    expect(profileLanguageChoices(offered, ["te-IN", "ta-IN"]).map((c) => c.label)).toEqual(["Telugu", "Tamil"]);
  });
});
