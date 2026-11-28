/**
 * What a new key may do, offered as five starting points (D-1047). Each is a set of the
 * account's own permissions; the server refuses any the person does not hold themselves.
 */

export type PresetId = "read" | "call" | "campaigns" | "dnc" | "events";

export interface Preset {
  id: PresetId;
  label: string;
  hint: string;
  scopes: readonly string[];
}

const READ = ["org:read", "agents:read", "calls:read", "leads:read"] as const;

export const PRESETS: readonly Preset[] = [
  {
    id: "read",
    label: "Read results",
    hint: "Calls, leads and agents. Changes nothing.",
    scopes: READ,
  },
  {
    id: "call",
    label: "Place calls",
    hint: "Everything above, plus calling people and sending leads in.",
    scopes: [...READ, "leads:dispatch", "wallet:read"],
  },
  {
    id: "campaigns",
    label: "Run campaigns",
    hint: "Place calls, plus adding people to campaigns and starting or stopping them.",
    scopes: [...READ, "leads:write", "leads:dispatch", "wallet:read"],
  },
  {
    id: "dnc",
    label: "Keep the do-not-call list",
    hint: "Read the list and add numbers to it.",
    scopes: ["org:read", "leads:read", "leads:dispatch"],
  },
  {
    id: "events",
    label: "Send events to my server",
    hint: "Read the events feed, and add or remove the addresses events are sent to.",
    scopes: ["org:read", "org:manage"],
  },
];

/** Plain words for each permission, for the key list. */
export const SCOPE_WORDS: Record<string, string> = {
  "org:read": "account",
  "agents:read": "agents",
  "calls:read": "calls",
  "leads:read": "leads",
  "leads:write": "edit leads",
  "leads:dispatch": "place calls",
  "wallet:read": "balance",
  "org:manage": "webhooks",
};

export function presetScopes(id: PresetId): string[] {
  const preset = PRESETS.find((p) => p.id === id);
  return preset ? [...preset.scopes] : [];
}

/** One address or range per line or comma; blank lines dropped. */
export function parseAddresses(raw: string): string[] {
  return raw
    .split(/[\s,]+/)
    .map((part) => part.trim())
    .filter(Boolean);
}
