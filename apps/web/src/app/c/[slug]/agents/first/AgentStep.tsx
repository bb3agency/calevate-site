"use client";

import { useId, useState } from "react";
import { ArrowRight } from "lucide-react";

import { useActionFeedback } from "@/components/arc/feedback";
import { CHOICE_OFF, CHOICE_ON } from "@/components/console/choiceCard";
import { ClientEngineVoices } from "@/components/engineCatalogueList";
import { FIELD, ProblemNotice } from "@/components/ui";
import { defaultExtraLanguages } from "@/lib/agentState";
import { useAgentLanguages } from "@/lib/api/agentLanguages";
import type { Agent } from "@/lib/api/agents";
import { useSaveFirstAgent, type FirstRun } from "@/lib/api/firstRun";
import { useClientSession } from "@/lib/api/session";
import { languageGlyph, languageShortLabel } from "@/lib/firstAgent";

import { ChipChoice, StepScreen } from "./shell";
import { FIRST } from "../../_ui/copy";
import { AGENT_NAME_MAX_CHARS } from "@/lib/textLimits";

/** The server's bound (`first_run/schemas.AgentIn.name`). */

/**
 * STEP 2, NAME AND VOICE (Phase 3b, founder 16 Nov 2026): the agent is staff, a name, a
 * voice and its languages, and nothing it says is written here.
 *
 * The name starts as the default agent's (`run.default_agent`, set in the admin console).
 * Pressing the step's button makes the agent with the default voice for its language; the
 * voice picker then shows that voice chosen, with the others to play and pick. A name or
 * language changed later is saved by the same button before the next step.
 */
export function AgentStep({
  run,
  agent,
  defaultLanguage,
  onBack,
  onDone,
}: {
  run: FirstRun;
  agent: Agent | null;
  defaultLanguage: string;
  onBack: () => void;
  onDone: () => void;
}) {
  const session = useClientSession();
  const save = useSaveFirstAgent(session);
  // The server's list for this account (D-855): a staged language switched on for it is a
  // tile here like the three every account has. The parent renders this step once it is in.
  const languages = useAgentLanguages(session);
  const saveFeedback = useActionFeedback(save, { errorDisplay: "inline" });
  const nameId = useId();
  const [name, setName] = useState(agent?.name ?? run.default_agent.name);
  const [primary, setPrimary] = useState(agent?.language_primary ?? run.language_primary ?? defaultLanguage);
  const [extra, setExtra] = useState<string[]>(
    agent?.reply_languages.slice(1) ?? (run.language_primary ? run.languages_extra : defaultExtraLanguages(defaultLanguage, languages.tags)),
  );
  const trimmed = name.trim();
  const changed =
    agent === null ||
    trimmed !== agent.name ||
    primary !== agent.language_primary ||
    extra.join() !== agent.reply_languages.slice(1).join();

  const choosePrimary = (tag: string) => {
    setPrimary(tag);
    setExtra((current) => current.filter((other) => other !== tag));
  };
  const submit = () => {
    if (!changed) {
      onDone();
      return;
    }
    save.mutate(
      { name: trimmed, language_primary: primary, languages_extra: extra },
      // A new agent stays on this step, so its voice can be heard and changed first.
      { onSuccess: () => (agent === null ? undefined : onDone()) },
    );
  };

  return (
    <StepScreen
      // The voice picker is a form of its own, so with it on screen the step is not one.
      asForm={agent === null}
      title="Name your agent and pick its voice"
      hint={FIRST.agentHint}
      onBack={onBack}
      primary={
        <>
          {agent === null ? "Choose its voice" : "Continue"}
          <ArrowRight aria-hidden className="h-4 w-4" />
        </>
      }
      status={saveFeedback.status}
      waitingFor={trimmed === "" ? "Give it a name." : null}
      onSubmit={submit}
    >
      <div>
        <label htmlFor={nameId} className="text-heading text-ink">
          Its name
        </label>
        <p className="text-meta text-ink-muted">{FIRST.nameHint}</p>
        <input
          id={nameId}
          value={name}
          maxLength={AGENT_NAME_MAX_CHARS}
          autoComplete="off"
          onChange={(event) => setName(event.target.value)}
          className={`${FIELD} mt-2 w-full text-[16px] sm:max-w-xs`}
        />
      </div>

      <fieldset>
        <legend className="text-heading text-ink">Which language does it speak first?</legend>
        <p className="text-meta text-ink-muted">{FIRST.languageHint}</p>
        <div className="mt-2 grid grid-cols-3 gap-2">
          {languages.choices.map((language) => (
            <LanguageTile
              key={language.value}
              tag={language.value}
              checked={primary === language.value}
              onChange={() => choosePrimary(language.value)}
            />
          ))}
        </div>
      </fieldset>

      <fieldset className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <legend className="sr-only">It also speaks</legend>
        <span aria-hidden className="text-body font-medium text-ink">
          It also speaks
        </span>
        <div className="flex flex-wrap gap-2">
          {languages.choices.filter((language) => language.value !== primary).map((language) => (
            <ChipChoice
              key={language.value}
              type="checkbox"
              name="also"
              value={language.value}
              size="sm"
              checked={extra.includes(language.value)}
              onChange={(on) =>
                setExtra((current) => (on ? [...current, language.value] : current.filter((tag) => tag !== language.value)))
              }
            >
              <span lang={language.value} aria-hidden className="font-semibold">
                {languageGlyph(language.value)}
              </span>
              {languageShortLabel(language.value)}
            </ChipChoice>
          ))}
        </div>
        <span className="text-meta text-ink-muted">{FIRST.switches}</span>
      </fieldset>

      {agent ? (
        <section aria-labelledby="first-agent-voice">
          <h3 id="first-agent-voice" className="text-heading text-ink">
            Its voice
          </h3>
          <p className="mb-2 text-meta text-ink-muted">Play a few. The one ticked is its voice now.</p>
          <ClientEngineVoices session={session} agentId={agent.id} />
        </section>
      ) : null}

      {save.error ? <ProblemNotice error={save.error} /> : null}
    </StepScreen>
  );
}

/** A language as a tile: its own script's syllable, then its name. */
function LanguageTile({ tag, checked, onChange }: { tag: string; checked: boolean; onChange: () => void }) {
  return (
    <label
      className={`press flex min-h-12 min-w-0 cursor-pointer flex-col items-center gap-1 rounded-card border px-2 py-2 max-sm:text-center sm:flex-row sm:gap-2.5 sm:px-2.5 transition-[border-color,box-shadow] duration-(--duration-fast) has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-strong has-[:focus-visible]:ring-offset-2 ${
        checked ? CHOICE_ON : CHOICE_OFF
      }`}
    >
      <input type="radio" name="language" value={tag} checked={checked} onChange={onChange} className="sr-only" />
      <span
        aria-hidden
        lang={tag}
        className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg text-[15px] font-semibold transition-colors duration-(--duration-fast) ${
          checked ? "bg-brand-strong text-white" : "bg-brand-soft text-brand-strong"
        }`}
      >
        {languageGlyph(tag)}
      </span>
      <span className={`min-w-0 truncate text-body ${checked ? "font-semibold text-ink" : "text-ink"}`}>
        {languageShortLabel(tag)}
      </span>
    </label>
  );
}
