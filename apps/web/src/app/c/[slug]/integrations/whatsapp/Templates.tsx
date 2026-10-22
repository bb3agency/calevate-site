"use client";

/**
 * The connected WhatsApp account's message templates: Calevate's four standard ones in
 * Telugu, Hindi and English, and the owner's own (D-784).
 *
 * Every in-call WhatsApp is a template, and Meta reviews each one before it can be sent, in
 * "up to 24 hours". The list says each template's state in words; the form checks Meta's
 * rules a person can fix before Meta sees them (blanks numbered in order, none at the very
 * start or end, an example for each) and shows the message as the customer will read it.
 */

import { useId, useMemo, useState } from "react";

import { Section, TEXT_ACTION } from "@/components/console/section";
import { StatusPill } from "@/components/console/statusPill";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { lookup } from "@/lib/lookup";
import { useVerticalExamples } from "@/lib/useVerticalExamples";
import {
  LANGUAGE_LABELS,
  PURPOSE_LABELS,
  TEMPLATE_REVIEW_HOURS,
  fillTemplate,
  templateBlanks,
  templateNameFrom,
  templateState,
  useCreateTemplate,
  useWhatsAppTemplates,
  type WhatsAppAccount,
  type WhatsAppTemplate,
} from "@/lib/api/whatsapp";

const LANGUAGES = ["te", "hi", "en"] as const;

function titleOf(t: WhatsAppTemplate): string {
  return lookup(PURPOSE_LABELS, t.purpose) ?? t.name.replaceAll("_", " ");
}

/** "Edge" in Meta's sense: a blank as the very first or very last thing in the message. */
export function blankAtEdge(body: string): boolean {
  const text = body.trim();
  return /^\{\{\s*\d+\s*\}\}/.test(text) || /\{\{\s*\d+\s*\}\}[\s.!?।]*$/.test(text);
}

/** Blanks must run 1, 2, 3… with none skipped. */
export function blanksInOrder(body: string): boolean {
  return templateBlanks(body).every((n, i) => n === i + 1);
}

export function Templates({
  session,
  account,
  canWrite,
}: {
  session: Session;
  account: WhatsAppAccount;
  canWrite: boolean;
}) {
  const templates = useWhatsAppTemplates(session);
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState<string | null>(null);

  return (
    <Section
      headingLevel={3}
      title="Message templates"
      description={`WhatsApp only lets a business start a chat with an approved template. Meta reviews each one in up to ${TEMPLATE_REVIEW_HOURS} hours.`}
      action={
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          disabled={!canWrite || account.status !== "connected"}
          onClick={() => setAdding((v) => !v)}
          aria-expanded={adding}
        >
          Add a template
        </button>
      }
    >
      {adding && <TemplateForm session={session} account={account} onDone={() => setAdding(false)} />}
      {templates.isPending ? (
        <Skeleton rows={4} />
      ) : templates.error || !templates.data ? (
        <ProblemNotice
          error={templates.error ?? new Error("We could not load your message templates.")}
          onRetry={() => void templates.refetch()}
        />
      ) : templates.data.filter((t) => t.account_id === account.id).length === 0 ? (
        <p className="text-body text-ink-muted">
          {account.templates_submitted
            ? "No templates yet."
            : "Calevate's standard templates are on their way to Meta."}
        </p>
      ) : (
        <ul className="divide-y divide-line border-y border-line">
          {templates.data
            .filter((t) => t.account_id === account.id)
            .map((t) => {
            const state = templateState(t.status);
            const expanded = open === t.id;
            return (
              <li key={t.id} className="py-3">
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                  <div className="min-w-0">
                    <p className="text-body font-medium text-ink [overflow-wrap:anywhere]">{titleOf(t)}</p>
                    <p className="text-meta text-ink-muted">
                      {lookup(LANGUAGE_LABELS, t.language) ?? t.language} ·{" "}
                      {t.category === "UTILITY" ? "About an order or booking" : "Marketing"}
                      {t.origin === "calevate" ? " · Written by Calevate" : ""}
                    </p>
                  </div>
                  <span className="flex items-center gap-4">
                    <StatusPill tone={state.tone}>{state.text}</StatusPill>
                    <button
                      type="button"
                      className={TEXT_ACTION}
                      aria-expanded={expanded}
                      onClick={() => setOpen(expanded ? null : t.id)}
                    >
                      {expanded ? "Hide" : "Read"}
                    </button>
                  </span>
                </div>
                {expanded && (
                  <div className="mt-2 space-y-1">
                    <p className="max-w-prose whitespace-pre-wrap rounded-md bg-ink/[0.04] px-3 py-2 text-body text-ink">
                      {fillTemplate(
                        t.body,
                        t.variables.map((v) => v.example),
                      )}
                    </p>
                    {t.variables.length > 0 && (
                      <p className="text-meta text-ink-muted">
                        Blanks: {t.variables.map((v, i) => `${i + 1} ${v.label}`).join(" · ")}
                      </p>
                    )}
                    {t.status === "rejected" && t.rejection_code && (
                      <p className="text-meta text-danger">Meta&rsquo;s reason: {t.rejection_code}</p>
                    )}
                    {t.category_changed_to && (
                      <p className="text-meta text-ink-muted">
                        Meta moved this to {t.category_changed_to.toLowerCase()}, which Meta charges at a
                        different rate.
                      </p>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Section>
  );
}

function TemplateForm({
  session,
  account,
  onDone,
}: {
  session: Session;
  account: WhatsAppAccount;
  onDone: () => void;
}) {
  const create = useCreateTemplate(session);
  const eg = useVerticalExamples();
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState<"UTILITY" | "MARKETING">("UTILITY");
  const [language, setLanguage] = useState<string>("en");
  const [body, setBody] = useState("");
  const [labels, setLabels] = useState<string[]>([]);
  const [examples, setExamples] = useState<string[]>([]);
  const bodyId = useId();
  const blanks = useMemo(() => templateBlanks(body), [body]);
  const name = templateNameFrom(title);

  const problem = !body.trim()
    ? null
    : !blanksInOrder(body)
      ? "Number the blanks in order: {{1}}, then {{2}}, and so on."
      : blankAtEdge(body)
        ? "Put a word before the first blank and after the last one. Meta refuses a message that starts or ends with a blank."
        : null;
  const missingExample = blanks.some((_, i) => !(examples[i] ?? "").trim() || !(labels[i] ?? "").trim());
  const ready = name.length > 0 && body.trim().length > 0 && !problem && !missingExample;

  const insertBlank = () => {
    const next = (blanks.at(-1) ?? 0) + 1;
    setBody((b) => `${b}${b && !b.endsWith(" ") ? " " : ""}{{${next}}}`);
  };

  return (
    <form
      className="mb-6 max-w-xl space-y-4"
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        if (!ready) return;
        create.mutate(
          {
            account_id: account.id,
            name,
            language,
            category,
            body: body.trim(),
            variables: blanks.map((_, i) => ({ label: labels[i].trim(), example: examples[i].trim() })),
          },
          { onSuccess: onDone },
        );
      }}
    >
      <label className="block">
        <span className={FIELD_LABEL}>What is this message for?</span>
        <input
          className={FIELD}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={eg.messageTitle}
          maxLength={60}
        />
        <span className={FIELD_HINT}>{name ? `Meta will know it as ${name}.` : "A few words you will recognise."}</span>
      </label>

      <fieldset>
        <legend className={FIELD_LABEL}>Kind of message</legend>
        <div className="mt-1 space-y-1.5">
          <label className="flex items-start gap-2 text-body text-ink">
            <input type="radio" name="category" checked={category === "UTILITY"} onChange={() => setCategory("UTILITY")} className="mt-1" />
            <span>
              About something the customer asked for: an order, a booking, a payment.
              <span className="block text-meta text-ink-muted">Meta calls this Utility. Use this for your agent.</span>
            </span>
          </label>
          <label className="flex items-start gap-2 text-body text-ink">
            <input type="radio" name="category" checked={category === "MARKETING"} onChange={() => setCategory("MARKETING")} className="mt-1" />
            <span>
              An offer or promotion.
              <span className="block text-meta text-ink-muted">Meta calls this Marketing and charges more for it.</span>
            </span>
          </label>
        </div>
      </fieldset>

      <label className="block">
        <span className={FIELD_LABEL}>Language</span>
        <select className={FIELD} value={language} onChange={(e) => setLanguage(e.target.value)}>
          {LANGUAGES.map((l) => (
            <option key={l} value={l}>
              {LANGUAGE_LABELS[l]}
            </option>
          ))}
        </select>
      </label>

      <div>
        <label htmlFor={bodyId} className={FIELD_LABEL}>
          The message
        </label>
        <textarea
          id={bodyId}
          className={`${FIELD} min-h-28`}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          maxLength={1024}
          placeholder={eg.messageBody}
          aria-describedby={`${bodyId}-hint`}
        />
        <span id={`${bodyId}-hint`} className={FIELD_HINT}>
          A blank like {"{{1}}"} is filled on each message, for example with the customer&rsquo;s name. {body.length}/1024
        </span>
        <button type="button" className={`${TEXT_ACTION} mt-1`} onClick={insertBlank}>
          Insert a blank
        </button>
        {problem && <p className="mt-1 text-meta text-danger">{problem}</p>}
      </div>

      {blanks.length > 0 && (
        <fieldset className="space-y-2">
          <legend className={FIELD_LABEL}>What goes in each blank</legend>
          {blanks.map((n, i) => (
            <div key={n} className="flex flex-wrap gap-2">
              <label className="min-w-0 flex-1">
                <span className="text-meta text-ink-muted">{`{{${n}}}`} is</span>
                <input
                  className={FIELD}
                  value={labels[i] ?? ""}
                  placeholder="Customer's name"
                  onChange={(e) => setLabels((all) => Object.assign([...all], { [i]: e.target.value }))}
                />
              </label>
              <label className="min-w-0 flex-1">
                <span className="text-meta text-ink-muted">Example for Meta</span>
                <input
                  className={FIELD}
                  value={examples[i] ?? ""}
                  placeholder="Ravi"
                  onChange={(e) => setExamples((all) => Object.assign([...all], { [i]: e.target.value }))}
                />
              </label>
            </div>
          ))}
        </fieldset>
      )}

      {body.trim() && (
        <div>
          <p className={FIELD_LABEL}>Your customer will read</p>
          <p className="mt-1 max-w-prose whitespace-pre-wrap rounded-md bg-ink/[0.04] px-3 py-2 text-body text-ink">
            {fillTemplate(body, examples)}
          </p>
        </div>
      )}

      {create.isError && <ProblemNotice error={create.error} />}
      <div className="flex flex-wrap gap-2">
        <button type="submit" className={PRIMARY_BUTTON_SM} disabled={!ready || create.isPending}>
          {create.isPending ? "Sending…" : "Send to Meta for review"}
        </button>
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}
