import { formatISTInput, istInputToInstant } from "@/components/ui";
import type {
  AdminAnnouncement,
  AnnouncementInput,
  AnnouncementUpdate,
} from "@/lib/api/announcements";

/** `announcements/models.MAX_MESSAGE_CHARS`; the server refuses one character more. */
export const MAX_MESSAGE_CHARS = 280;
/** `announcements/schemas.MAX_LINK_CHARS` and `MAX_LINK_LABEL_CHARS`. */
export const MAX_LINK_CHARS = 500;
export const MAX_LINK_LABEL_CHARS = 40;

export type Tone = AdminAnnouncement["tone"];
export type Audience = AdminAnnouncement["audience"];

export type AnnouncementDraft = {
  message: string;
  linkUrl: string;
  linkLabel: string;
  tone: Tone;
  audience: Audience;
  targetTenantId: string | null;
  targetTenantName: string | null;
  /** `YYYY-MM-DDTHH:mm` in IST; empty = now (create only). */
  startsAt: string;
  /** `YYYY-MM-DDTHH:mm` in IST; empty = until ended. */
  endsAt: string;
};

export const EMPTY_DRAFT: AnnouncementDraft = {
  message: "",
  linkUrl: "",
  linkLabel: "",
  tone: "info",
  audience: "all",
  targetTenantId: null,
  targetTenantName: null,
  startsAt: "",
  endsAt: "",
};

export function draftFrom(row: AdminAnnouncement): AnnouncementDraft {
  return {
    message: row.message,
    linkUrl: row.link_url ?? "",
    linkLabel: row.link_label ?? "",
    tone: row.tone,
    audience: row.audience,
    targetTenantId: row.target_tenant_id,
    targetTenantName: row.target_tenant_name,
    startsAt: formatISTInput(row.starts_at),
    endsAt: formatISTInput(row.ends_at),
  };
}

/** The message as the server stores it: runs of whitespace become one space. */
export function normaliseMessage(message: string): string {
  return message.split(/\s+/).filter(Boolean).join(" ");
}

/** Length in code points, which is what Python's `len` counts on the server. */
export function messageLength(message: string): number {
  return [...normaliseMessage(message)].length;
}

/** The server's rule (`schemas._link`): an https address or a console path. */
export function linkProblem(link: string): string | null {
  const value = link.trim();
  if (!value) return null;
  if (value.length > MAX_LINK_CHARS) return `Keep the link under ${MAX_LINK_CHARS} characters.`;
  if (value.startsWith("https://") && value.length > "https://".length) return null;
  if (value.startsWith("/") && !value.startsWith("//")) return null;
  return "Use a full https:// address, or a console page starting with / (for example /billing).";
}

export type DraftErrors = Partial<Record<"message" | "linkUrl" | "linkLabel" | "target" | "startsAt" | "endsAt", string>>;

export function validateDraft(draft: AnnouncementDraft): DraftErrors {
  const errors: DraftErrors = {};
  const length = messageLength(draft.message);
  if (length === 0) errors.message = "Write the message clients will read.";
  else if (length > MAX_MESSAGE_CHARS)
    errors.message = `Shorten it by ${length - MAX_MESSAGE_CHARS} character${length - MAX_MESSAGE_CHARS === 1 ? "" : "s"}.`;
  const link = linkProblem(draft.linkUrl);
  if (link) errors.linkUrl = link;
  if (draft.linkLabel.trim() && !draft.linkUrl.trim()) errors.linkLabel = "A link label needs a link.";
  else if ([...draft.linkLabel.trim()].length > MAX_LINK_LABEL_CHARS)
    errors.linkLabel = `Keep the label to ${MAX_LINK_LABEL_CHARS} characters.`;
  if (draft.audience === "tenant" && !draft.targetTenantId) errors.target = "Choose the client who should see it.";
  if (draft.startsAt && !istInputToInstant(draft.startsAt)) errors.startsAt = "Pick a time as well as a day.";
  if (draft.endsAt && !istInputToInstant(draft.endsAt)) errors.endsAt = "Pick a time as well as a day.";
  const start = istInputToInstant(draft.startsAt);
  const end = istInputToInstant(draft.endsAt);
  if (end && !errors.endsAt) {
    if (start && end <= start) errors.endsAt = "It must end after it starts.";
    else if (!start && Date.parse(end) <= Date.now()) errors.endsAt = "Pick an end that is still to come.";
  }
  return errors;
}

export function createInput(draft: AnnouncementDraft): AnnouncementInput {
  return {
    message: normaliseMessage(draft.message),
    link_url: draft.linkUrl.trim() || null,
    link_label: draft.linkLabel.trim() || null,
    tone: draft.tone,
    audience: draft.audience,
    target_tenant_id: draft.audience === "tenant" ? draft.targetTenantId : null,
    starts_at: istInputToInstant(draft.startsAt),
    ends_at: istInputToInstant(draft.endsAt),
  };
}

/**
 * The PATCH: only what moved. `null` clears a link, its label or the end; a start is never
 * sent as null because the server reads that as "unchanged", so clearing it is ignored.
 */
export function updateInput(before: AnnouncementDraft, after: AnnouncementDraft): AnnouncementUpdate {
  const change: AnnouncementUpdate = {};
  if (normaliseMessage(after.message) !== normaliseMessage(before.message)) change.message = normaliseMessage(after.message);
  if (after.linkUrl.trim() !== before.linkUrl.trim()) change.link_url = after.linkUrl.trim() || null;
  if (after.linkLabel.trim() !== before.linkLabel.trim()) change.link_label = after.linkLabel.trim() || null;
  if (after.tone !== before.tone) change.tone = after.tone;
  if (after.audience !== before.audience || after.targetTenantId !== before.targetTenantId) {
    change.audience = after.audience;
    change.target_tenant_id = after.audience === "tenant" ? after.targetTenantId : null;
  }
  if (after.startsAt !== before.startsAt && after.startsAt) change.starts_at = istInputToInstant(after.startsAt);
  if (after.endsAt !== before.endsAt) change.ends_at = istInputToInstant(after.endsAt);
  return change;
}

export const TONE_OPTIONS: { value: Tone; label: string; hint: string }[] = [
  { value: "info", label: "Information", hint: "News or a change worth knowing about." },
  { value: "success", label: "Good news", hint: "Something fixed or newly available." },
  { value: "warning", label: "Heads up", hint: "Something clients should act on or plan around." },
  { value: "critical", label: "Urgent", hint: "Calls or billing are affected now. Screen readers announce it straight away." },
];

export const AUDIENCE_OPTIONS: { value: Audience; label: string; hint: string }[] = [
  { value: "all", label: "Every client", hint: "Trial and paying accounts alike." },
  { value: "trial", label: "Trial accounts", hint: "Accounts that have never paid." },
  { value: "paid", label: "Paying clients", hint: "Accounts that have paid at least once." },
  { value: "outbound", label: "Accounts that place calls", hint: "Accounts with an agent that calls out." },
  { value: "tenant", label: "One client", hint: "Only the account you choose." },
];

export function audienceLabel(row: Pick<AdminAnnouncement, "audience" | "target_tenant_name">): string {
  if (row.audience === "tenant") return row.target_tenant_name ?? "One client";
  return AUDIENCE_OPTIONS.find((option) => option.value === row.audience)?.label ?? row.audience;
}
